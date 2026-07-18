"""按需代理租约与快代理 DPS 提取。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import ipaddress
import logging
import time
from typing import Callable, Protocol
from urllib.parse import quote

from curl_cffi.requests.exceptions import (
    ConnectionError as CurlConnectionError,
)
from curl_cffi.requests.exceptions import ProxyError as CurlProxyError
from curl_cffi.requests.exceptions import Timeout as CurlTimeout

from client.api import ApiError
from client.guest import GuestRegistrationError

from .config import ConfigurationError, Settings


LOGGER = logging.getLogger(__name__)


class ProxyAcquisitionError(RuntimeError):
    """代理供应商没有返回可用租约。"""


class ProxyProvider(Protocol):
    name: str
    dynamic: bool
    lease_seconds: float | None

    async def acquire(self) -> str | None:
        """返回 curl_cffi 可直接使用的代理 URL。"""


class DirectProxyProvider:
    name = "direct"
    dynamic = False
    lease_seconds = None

    async def acquire(self) -> None:
        return None


class StaticProxyProvider:
    name = "static"
    dynamic = False
    lease_seconds = None

    def __init__(self, proxy_url: str):
        self._proxy_url = proxy_url

    async def acquire(self) -> str:
        return self._proxy_url


class KuaidailiDpsProvider:
    """只在 ``acquire`` 时调用快代理 GetDPS。"""

    name = "kuaidaili_dps"
    dynamic = True

    def __init__(
        self,
        *,
        secret_id: str,
        secret_key: str,
        lease_seconds: float = 1200,
        area: str = "",
        auth_mode: str = "auto",
        proxy_username: str = "",
        proxy_password: str = "",
        client_factory: Callable | None = None,
    ):
        if not secret_id or not secret_key:
            raise ConfigurationError("快代理缺少 KDL_SECRET_ID/KDL_SECRET_KEY")
        auth_mode = str(auth_mode or "auto").strip().lower()
        if auth_mode not in {"auto", "required", "whitelist"}:
            raise ConfigurationError(
                "CIWEIMAO_KDL_AUTH_MODE 必须是 auto/required/whitelist")
        if bool(proxy_username) != bool(proxy_password):
            raise ConfigurationError("快代理用户名和密码必须同时配置")

        self._secret_id = secret_id
        self._secret_key = secret_key
        self.lease_seconds = max(1.0, float(lease_seconds))
        self._area = str(area or "").strip()
        self._auth_mode = auth_mode
        self._proxy_username = proxy_username
        self._proxy_password = proxy_password
        self._client_factory = client_factory or self._default_client_factory
        self._client = None
        self._authorization: tuple[str, str] | None = None

    @staticmethod
    def _default_client_factory(secret_id: str, secret_key: str):
        try:
            import kdl
        except ImportError as exc:
            raise ProxyAcquisitionError(
                "缺少快代理 SDK，请安装 requirements.txt") from exc
        return kdl.Client(kdl.Auth(secret_id, secret_key))

    def _get_client(self):
        if self._client is None:
            self._client = self._client_factory(
                self._secret_id, self._secret_key)
        return self._client

    def _get_authorization(self, client) -> tuple[str, str]:
        if self._authorization is not None:
            return self._authorization
        if self._proxy_username and self._proxy_password:
            self._authorization = (
                self._proxy_username, self._proxy_password)
            return self._authorization
        if self._auth_mode == "whitelist":
            self._authorization = ("", "")
            return self._authorization

        try:
            payload = client.get_proxy_authorization(plain_text=1)
        except Exception as exc:
            if self._auth_mode == "required":
                raise ProxyAcquisitionError(
                    "获取快代理鉴权信息失败") from exc
            LOGGER.info("KDL authorization unavailable; using whitelist mode")
            self._authorization = ("", "")
            return self._authorization

        username = str((payload or {}).get("username", "")).strip()
        password = str((payload or {}).get("password", "")).strip()
        if bool(username) != bool(password):
            raise ProxyAcquisitionError("快代理鉴权信息不完整")
        if not username and self._auth_mode == "required":
            raise ProxyAcquisitionError("快代理没有返回代理鉴权信息")
        self._authorization = (username, password)
        return self._authorization

    @staticmethod
    def _build_proxy_url(ip_port: str, username: str,
                         password: str) -> str:
        value = str(ip_port or "").strip()
        host, separator, port_text = value.rpartition(":")
        try:
            address = ipaddress.ip_address(host.strip("[]"))
            port = int(port_text)
        except (TypeError, ValueError) as exc:
            raise ProxyAcquisitionError(
                "快代理返回了无效的 IP:PORT") from exc
        if (not separator or not 1 <= port <= 65535
                or any(character.isspace() for character in value)):
            raise ProxyAcquisitionError("快代理返回了无效的 IP:PORT")
        rendered_host = (
            f"[{address.compressed}]"
            if address.version == 6 else address.compressed
        )
        endpoint = f"{rendered_host}:{port}"
        if username and password:
            return (
                f"http://{quote(username, safe='')}:"
                f"{quote(password, safe='')}@{endpoint}"
            )
        return f"http://{endpoint}"

    def _acquire_sync(self) -> str:
        client = self._get_client()
        # 鉴权信息先取，避免 GetDPS 返回后再浪费租约时间。
        username, password = self._get_authorization(client)
        params = {
            "num": 1,
            "format": "json",
            "sign_type": "token",
            "pt": 1,
        }
        if self._area:
            params["area"] = self._area
        try:
            result = client.get_dps(**params)
        except Exception as exc:
            raise ProxyAcquisitionError("快代理 GetDPS 提取失败") from exc
        proxies = result if isinstance(result, list) else [result]
        if not proxies:
            raise ProxyAcquisitionError("快代理 GetDPS 没有返回 IP")
        return self._build_proxy_url(proxies[0], username, password)

    async def acquire(self) -> str:
        return await asyncio.to_thread(self._acquire_sync)


@dataclass(frozen=True, repr=False)
class ProxyLease:
    proxy_url: str | None = field(repr=False)
    provider: str
    generation: int
    acquired_at: float
    expires_at: float | None

    def remaining_seconds(self, now: float) -> float | None:
        if self.expires_at is None:
            return None
        return max(0.0, self.expires_at - now)

    def is_usable(self, now: float, safety_seconds: float) -> bool:
        return (self.expires_at is None
                or now < self.expires_at - safety_seconds)


class ProxyLeaseContext:
    """一次业务流程持有的代理租约，可在失败后原位刷新。"""

    def __init__(self, manager: "ProxyLeaseManager", lease: ProxyLease,
                 reason: str):
        self._manager = manager
        self.lease = lease
        self.reason = reason
        self._refresh_lock = asyncio.Lock()

    @property
    def proxy_url(self) -> str | None:
        return self.lease.proxy_url

    async def refresh(self, reason: str) -> ProxyLease:
        async with self._refresh_lock:
            self.lease = await self._manager.acquire(
                force_new=True,
                failed_lease=self.lease,
                reason=f"{self.reason}:{reason}",
            )
            return self.lease


class ProxyLeaseManager:
    """全进程只缓存一个代理，按业务流程决定复用或强制换新。"""

    def __init__(self, provider: ProxyProvider, *,
                 expiry_safety_seconds: float = 30,
                 clock: Callable[[], float] = time.monotonic):
        self.provider = provider
        self.expiry_safety_seconds = max(
            0.0, float(expiry_safety_seconds))
        self._clock = clock
        self._lock = asyncio.Lock()
        self._current: ProxyLease | None = None
        self._generation = 0

    @property
    def dynamic(self) -> bool:
        return bool(self.provider.dynamic)

    def _usable(self, lease: ProxyLease | None) -> bool:
        return bool(lease and lease.is_usable(
            self._clock(), self.expiry_safety_seconds))

    async def acquire(self, *, force_new: bool = False,
                      failed_lease: ProxyLease | None = None,
                      reason: str = "request") -> ProxyLease:
        async with self._lock:
            current = self._current
            if (failed_lease is not None and current is not None
                    and current.generation != failed_lease.generation
                    and self._usable(current)):
                return current
            if self._usable(current) and (
                    not force_new or not self.provider.dynamic):
                return current

            proxy_url = await self.provider.acquire()
            now = self._clock()
            self._generation += 1
            lease_seconds = self.provider.lease_seconds
            lease = ProxyLease(
                proxy_url=proxy_url,
                provider=self.provider.name,
                generation=self._generation,
                acquired_at=now,
                expires_at=(
                    now + float(lease_seconds)
                    if lease_seconds is not None else None
                ),
            )
            self._current = lease
            LOGGER.info(
                "proxy lease acquired: provider=%s generation=%s reason=%s",
                lease.provider,
                lease.generation,
                reason,
            )
            return lease

    async def context(self, *, force_new: bool = False,
                      reason: str = "request") -> ProxyLeaseContext:
        lease = await self.acquire(force_new=force_new, reason=reason)
        return ProxyLeaseContext(self, lease, reason)

    def snapshot(self) -> dict:
        current = self._current
        now = self._clock()
        remaining = (
            current.remaining_seconds(now) if current is not None else None)
        return {
            "provider": self.provider.name,
            "dynamic": self.dynamic,
            "acquired": current is not None,
            "active": self._usable(current),
            "generation": current.generation if current else 0,
            "remaining_seconds": (
                round(remaining, 1) if remaining is not None else None),
        }


def build_proxy_manager(settings: Settings) -> ProxyLeaseManager:
    provider_name = str(settings.proxy_provider or "auto").strip().lower()
    if provider_name == "auto":
        provider_name = "static" if settings.http_proxy_url else "direct"

    if provider_name in {"direct", "none"}:
        provider: ProxyProvider = DirectProxyProvider()
    elif provider_name == "static":
        if not settings.http_proxy_url:
            raise ConfigurationError(
                "CIWEIMAO_PROXY_PROVIDER=static 时必须配置 CIWEIMAO_PROXY_URL")
        provider = StaticProxyProvider(settings.http_proxy_url)
    elif provider_name in {"kuaidaili", "kuaidaili_dps", "kdl_dps"}:
        provider = KuaidailiDpsProvider(
            secret_id=settings.kdl_secret_id or "",
            secret_key=settings.kdl_secret_key or "",
            lease_seconds=settings.proxy_lease_seconds,
            area=settings.kdl_area,
            auth_mode=settings.kdl_auth_mode,
            proxy_username=settings.kdl_proxy_username or "",
            proxy_password=settings.kdl_proxy_password or "",
        )
    else:
        raise ConfigurationError(
            f"不支持的 CIWEIMAO_PROXY_PROVIDER: {provider_name}")

    return ProxyLeaseManager(
        provider,
        expiry_safety_seconds=settings.proxy_expiry_safety_seconds,
    )


def is_proxy_failure_error(exc: BaseException) -> bool:
    """判断是否应丢弃当前动态代理并提取新 IP。"""
    visited: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, (
                CurlConnectionError, CurlProxyError, CurlTimeout)):
            return True
        if isinstance(current, ApiError) and current.code == "320002":
            return True
        if isinstance(current, GuestRegistrationError):
            if current.code == "320002":
                return True
            if current.code in {
                    "empty-response", "no-response", "decode-failed"}:
                return True
            if current.code in {
                    "http-407", "http-502", "http-503", "http-504"}:
                return True
        message = str(current).lower()
        if any(marker in message for marker in (
                "http 407", "http 502", "http 503", "http 504",
                "proxy connect", "proxy connection")):
            return True
        current = current.__cause__ or current.__context__
    return False
