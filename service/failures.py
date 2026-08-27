"""可执行的故障分类，避免把协议、身份和出口混成一次重试。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from curl_cffi.requests.exceptions import (
    ConnectionError as CurlConnectionError,
)
from curl_cffi.requests.exceptions import ProxyError as CurlProxyError
from curl_cffi.requests.exceptions import Timeout as CurlTimeout

from client.api import ApiError
from client.downloader import NoDownloadableChapters
from client.guest import GuestRegistrationError


class FailureCategory(StrEnum):
    CREDENTIAL_EXPIRED = "credential_expired"
    RISK_REJECTED = "risk_rejected"
    PROTOCOL_INCOMPATIBLE = "protocol_incompatible"
    PROXY_SUPPLY_FAILED = "proxy_supply_failed"
    TRANSPORT_FAILED = "transport_failed"
    CONTENT_UNAVAILABLE = "content_unavailable"
    INTERNAL = "internal"


@dataclass(frozen=True)
class FailureInfo:
    category: FailureCategory
    code: str = ""
    retry_same_egress: bool = False
    switch_egress: bool = False
    refresh_identity: bool = False


class ProxyAcquisitionError(RuntimeError):
    """代理供应商没有返回可用租约。"""


class EgressUnavailableError(RuntimeError):
    """所有出口均处于 breaker，任务应延后而不是标成永久失败。"""

    def __init__(self, message: str, *, retry_after: str | None = None):
        self.retry_after = retry_after
        super().__init__(message)


def _walk_exception(exc: BaseException):
    visited: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def classify_failure(exc: BaseException) -> FailureInfo:
    """返回故障唯一分类及允许的恢复动作。"""
    for current in _walk_exception(exc):
        if isinstance(current, EgressUnavailableError):
            return FailureInfo(
                FailureCategory.PROXY_SUPPLY_FAILED,
                code="egress-unavailable",
            )
        if isinstance(current, ProxyAcquisitionError):
            return FailureInfo(
                FailureCategory.PROXY_SUPPLY_FAILED,
                code="proxy-acquisition",
                switch_egress=True,
            )
        if isinstance(current, ApiError):
            if current.code == "200100":
                return FailureInfo(
                    FailureCategory.CREDENTIAL_EXPIRED,
                    code=current.code,
                    refresh_identity=True,
                )
            if current.code == "320002":
                return FailureInfo(
                    FailureCategory.RISK_REJECTED,
                    code=current.code,
                    retry_same_egress=True,
                    switch_egress=True,
                )
            if current.code == "310017":
                return FailureInfo(
                    FailureCategory.PROTOCOL_INCOMPATIBLE,
                    code=current.code,
                )
            return FailureInfo(FailureCategory.INTERNAL, code=current.code)
        if isinstance(current, GuestRegistrationError):
            if current.code == "200100":
                return FailureInfo(
                    FailureCategory.CREDENTIAL_EXPIRED,
                    code=current.code,
                    refresh_identity=True,
                )
            if current.code == "320002":
                return FailureInfo(
                    FailureCategory.RISK_REJECTED,
                    code=current.code,
                    retry_same_egress=True,
                    switch_egress=True,
                )
            if current.code in {"empty-response", "no-response"}:
                return FailureInfo(
                    FailureCategory.TRANSPORT_FAILED,
                    code=current.code,
                    retry_same_egress=True,
                    switch_egress=True,
                )
            if current.code == "decode-failed":
                return FailureInfo(
                    FailureCategory.PROTOCOL_INCOMPATIBLE,
                    code=current.code,
                )
            if current.code in {
                    "http-407", "http-502", "http-503", "http-504"}:
                return FailureInfo(
                    FailureCategory.TRANSPORT_FAILED,
                    code=current.code,
                    retry_same_egress=True,
                    switch_egress=True,
                )
        if isinstance(current, (
                CurlConnectionError, CurlProxyError, CurlTimeout)):
            return FailureInfo(
                FailureCategory.TRANSPORT_FAILED,
                code=type(current).__name__,
                retry_same_egress=True,
                switch_egress=True,
            )
        if isinstance(current, NoDownloadableChapters):
            return FailureInfo(FailureCategory.CONTENT_UNAVAILABLE)

        message = str(current).lower()
        if "login_token 已过期" in message:
            return FailureInfo(
                FailureCategory.CREDENTIAL_EXPIRED,
                code="200100",
                refresh_identity=True,
            )
        if any(marker in message for marker in (
                "http 407", "http 502", "http 503", "http 504",
                "proxy connect", "proxy connection", "timed out")):
            return FailureInfo(
                FailureCategory.TRANSPORT_FAILED,
                retry_same_egress=True,
                switch_egress=True,
            )
        if any(marker in message for marker in (
                "解密/解析失败", "decode", "signature", "签名")):
            return FailureInfo(FailureCategory.PROTOCOL_INCOMPATIBLE)

    return FailureInfo(FailureCategory.INTERNAL)
