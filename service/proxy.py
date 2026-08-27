"""按需代理租约与快代理 DPS 提取。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import secrets
import time
from typing import Callable, Protocol
from urllib.parse import quote

from curl_cffi.requests.exceptions import (
    ConnectionError as CurlConnectionError,
)
from curl_cffi.requests.exceptions import ProxyError as CurlProxyError
from curl_cffi.requests.exceptions import Timeout as CurlTimeout

from .config import ConfigurationError, Settings
from .failures import (
    EgressUnavailableError,
    FailureCategory,
    ProxyAcquisitionError,
    classify_failure,
)


LOGGER = logging.getLogger(__name__)
_PROXY_AUTH_PATTERN = re.compile(
    r"(?P<scheme>(?:https?|socks5h?)://)[^\s/@:]+(?::[^\s/@]*)?@",
    re.IGNORECASE,
)
_SECRET_FIELD_PATTERN = re.compile(
    r"(?i)\b(secret_?id|secret_?key|login_token|device_token)"
    r"(?P<separator>\s*[=:]\s*)[^\s,;&]+"
)


def redact_error_text(value: object) -> str:
    """删除错误文本中的代理账密和常见身份字段。"""
    text = str(value)
    text = _PROXY_AUTH_PATTERN.sub(
        lambda match: f"{match.group('scheme')}***:***@", text)
    return _SECRET_FIELD_PATTERN.sub(
        lambda match: (
            f"{match.group(1)}{match.group('separator')}***"),
        text,
    )


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
            payload = client.get_proxy_authorization(
                plain_text=1,
                sign_type="hmacsha1",
            )
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
            "sign_type": "hmacsha1",
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
    slot_id: str = "default"

    def remaining_seconds(self, now: float) -> float | None:
        if self.expires_at is None:
            return None
        return max(0.0, self.expires_at - now)

    def is_usable(self, now: float, safety_seconds: float) -> bool:
        return (self.expires_at is None
                or now < self.expires_at - safety_seconds)


class ProxyLeaseContext:
    """一次业务流程持有的代理租约，可在失败后原位刷新。"""

    def __init__(self, manager, lease: ProxyLease,
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
                 slot_id: str = "default",
                 clock: Callable[[], float] = time.monotonic):
        self.provider = provider
        self.expiry_safety_seconds = max(
            0.0, float(expiry_safety_seconds))
        self._clock = clock
        self.slot_id = str(slot_id)
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
                slot_id=self.slot_id,
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
            "slot_id": self.slot_id,
            "dynamic": self.dynamic,
            "acquired": current is not None,
            "active": self._usable(current),
            "generation": current.generation if current else 0,
            "remaining_seconds": (
                round(remaining, 1) if remaining is not None else None),
        }

    def report_failure(self, lease: ProxyLease,
                       category: FailureCategory) -> None:
        del lease, category

    def report_success(self, lease: ProxyLease) -> None:
        del lease


def _utc_from_timestamp(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(
        value, timezone.utc).isoformat(timespec="milliseconds")


class _EgressStateStore:
    """只保存 breaker 元数据，不保存代理 URL 或凭据。"""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()

    @staticmethod
    def empty() -> dict:
        return {
            "schema": 1,
            "active_slot": "nas-primary",
            "manual_slot": None,
            "slots": {
                "nas-primary": {
                    "state": "closed",
                    "failure_streak": 0,
                    "risk_streak": 0,
                    "opened_until": None,
                    "probe_successes": 0,
                    "last_probe_success_at": None,
                },
                "dps-fallback": {
                    "state": "closed",
                    "failure_streak": 0,
                    "risk_streak": 0,
                    "opened_until": None,
                    "probe_successes": 0,
                    "last_probe_success_at": None,
                },
            },
        }

    def load(self) -> dict:
        if not self.path.is_file():
            return self.empty()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            LOGGER.warning("invalid egress state ignored: %s", self.path)
            return self.empty()
        if int(payload.get("schema", 0)) != 1:
            return self.empty()
        baseline = self.empty()
        baseline.update({
            key: payload.get(key, baseline[key])
            for key in ("active_slot", "manual_slot")
        })
        for slot_id in baseline["slots"]:
            baseline["slots"][slot_id].update(
                (payload.get("slots") or {}).get(slot_id, {}))
        return baseline

    def save(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
        text = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        descriptor = None
        try:
            descriptor = os.open(
                temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(
                    descriptor, "w", encoding="utf-8", newline="\n") as file:
                descriptor = None
                file.write(text)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temp.exists():
                temp.unlink()


class FailoverProxyLeaseManager:
    """固定住宅主链与 DPS 备援的持久 breaker。"""

    def __init__(
        self,
        primary: ProxyLeaseManager,
        fallback: ProxyLeaseManager,
        *,
        state_path: str | Path,
        failure_threshold: int = 3,
        risk_threshold: int = 2,
        cooldown_seconds: float = 900,
        failback_successes: int = 2,
        failback_interval_seconds: float = 300,
        wall_clock: Callable[[], float] = time.time,
    ):
        self.primary = primary
        self.fallback = fallback
        self.failure_threshold = max(1, int(failure_threshold))
        self.risk_threshold = max(1, int(risk_threshold))
        self.cooldown_seconds = max(1.0, float(cooldown_seconds))
        self.failback_successes = max(1, int(failback_successes))
        self.failback_interval_seconds = max(
            1.0, float(failback_interval_seconds))
        self._wall_clock = wall_clock
        self._store = _EgressStateStore(state_path)
        self._state = self._store.load()
        self._lock = asyncio.Lock()

    @property
    def dynamic(self) -> bool:
        return True

    def _slot(self, slot_id: str) -> dict:
        return self._state["slots"][slot_id]

    def _manager(self, slot_id: str) -> ProxyLeaseManager:
        return self.primary if slot_id == "nas-primary" else self.fallback

    def _choose_slot(self) -> str:
        manual = self._state.get("manual_slot")
        if manual in {"nas-primary", "dps-fallback"}:
            return manual
        now = self._wall_clock()
        primary = self._slot("nas-primary")
        if primary["state"] == "closed":
            return "nas-primary"
        opened_until = float(primary.get("opened_until") or 0)
        if now >= opened_until:
            primary["state"] = "half_open"
            return "nas-primary"
        return "dps-fallback"

    async def acquire(self, *, force_new: bool = False,
                      failed_lease: ProxyLease | None = None,
                      reason: str = "request") -> ProxyLease:
        async with self._lock:
            slot_id = self._choose_slot()
            manager = self._manager(slot_id)
            try:
                lease = await manager.acquire(
                    force_new=force_new,
                    failed_lease=(
                        failed_lease
                        if failed_lease and failed_lease.slot_id == slot_id
                        else None),
                    reason=reason,
                )
            except Exception as exc:
                info = classify_failure(exc)
                self._record_failure(slot_id, info.category)
                if slot_id == "nas-primary":
                    try:
                        lease = await self.fallback.acquire(
                            force_new=force_new,
                            reason=f"{reason}:primary-unavailable",
                        )
                        slot_id = "dps-fallback"
                    except Exception as fallback_exc:
                        self._record_failure(
                            "dps-fallback",
                            classify_failure(fallback_exc).category,
                        )
                        raise EgressUnavailableError(
                            "住宅出口与 DPS 备援均不可用",
                            retry_after=self.next_retry_at,
                        ) from fallback_exc
                else:
                    raise EgressUnavailableError(
                        "DPS 备援不可用且住宅出口仍在冷却",
                        retry_after=self.next_retry_at,
                    ) from exc
            self._state["active_slot"] = slot_id
            self._store.save(self._state)
            return lease

    async def context(self, *, force_new: bool = False,
                      reason: str = "request") -> ProxyLeaseContext:
        lease = await self.acquire(force_new=force_new, reason=reason)
        return ProxyLeaseContext(self, lease, reason)

    async def context_for_slot(
            self, slot_id: str, *, force_new: bool = False,
            reason: str = "probe") -> ProxyLeaseContext:
        """显式诊断某个出口，不修改 manual_slot，也不静默换到另一槽。"""
        if slot_id not in {"nas-primary", "dps-fallback"}:
            raise ValueError("未知出口槽")
        manager = self._manager(slot_id)
        try:
            lease = await manager.acquire(
                force_new=force_new, reason=reason)
        except Exception as exc:
            self._record_failure(
                slot_id, classify_failure(exc).category)
            raise
        self._state["active_slot"] = slot_id
        self._store.save(self._state)
        return ProxyLeaseContext(manager, lease, reason)

    def _record_failure(self, slot_id: str,
                        category: FailureCategory) -> None:
        state = self._slot(slot_id)
        if category == FailureCategory.RISK_REJECTED:
            state["risk_streak"] = int(state["risk_streak"]) + 1
        elif category in {
                FailureCategory.TRANSPORT_FAILED,
                FailureCategory.PROXY_SUPPLY_FAILED}:
            state["failure_streak"] = int(state["failure_streak"]) + 1
        else:
            return
        threshold_reached = (
            int(state["failure_streak"]) >= self.failure_threshold
            or int(state["risk_streak"]) >= self.risk_threshold
        )
        if threshold_reached:
            state.update({
                "state": "open",
                "opened_until": self._wall_clock() + self.cooldown_seconds,
                "probe_successes": 0,
            })
            if slot_id == "nas-primary":
                self._state["active_slot"] = "dps-fallback"
        self._store.save(self._state)

    def report_failure(self, lease: ProxyLease,
                       category: FailureCategory) -> None:
        self._record_failure(lease.slot_id, category)

    def report_success(self, lease: ProxyLease) -> None:
        state = self._slot(lease.slot_id)
        now = self._wall_clock()
        state["failure_streak"] = 0
        state["risk_streak"] = 0
        if lease.slot_id == "nas-primary" and state["state"] == "half_open":
            last = float(state.get("last_probe_success_at") or 0)
            if not last or now - last >= self.failback_interval_seconds:
                state["probe_successes"] = int(
                    state["probe_successes"]) + 1
                state["last_probe_success_at"] = now
            if int(state["probe_successes"]) >= self.failback_successes:
                state.update({
                    "state": "closed",
                    "opened_until": None,
                    "probe_successes": 0,
                })
                self._state["active_slot"] = "nas-primary"
            else:
                state["state"] = "open"
                state["opened_until"] = (
                    now + self.failback_interval_seconds)
        elif state["state"] != "open":
            state["state"] = "closed"
        self._store.save(self._state)

    def force_slot(self, slot_id: str | None) -> None:
        if slot_id not in {None, "nas-primary", "dps-fallback"}:
            raise ValueError("未知出口槽")
        self._state["manual_slot"] = slot_id
        if slot_id:
            self._state["active_slot"] = slot_id
        self._store.save(self._state)

    def reset_slot(self, slot_id: str) -> None:
        """显式清除 breaker；仅供受控运维任务使用。"""
        if slot_id not in {"nas-primary", "dps-fallback"}:
            raise ValueError("未知出口槽")
        self._state["slots"][slot_id].update({
            "state": "closed",
            "failure_streak": 0,
            "risk_streak": 0,
            "opened_until": None,
            "probe_successes": 0,
            "last_probe_success_at": None,
        })
        self._store.save(self._state)

    @property
    def next_retry_at(self) -> str | None:
        values = [
            float(slot.get("opened_until") or 0)
            for slot in self._state["slots"].values()
            if slot.get("state") == "open"
        ]
        return _utc_from_timestamp(min(values)) if values else None

    def snapshot(self) -> dict:
        slots = {}
        for slot_id, state in self._state["slots"].items():
            manager_snapshot = self._manager(slot_id).snapshot()
            slots[slot_id] = {
                **manager_snapshot,
                "state": state["state"],
                "failure_streak": int(state["failure_streak"]),
                "risk_streak": int(state["risk_streak"]),
                "opened_until": _utc_from_timestamp(
                    state.get("opened_until")),
                "probe_successes": int(state["probe_successes"]),
            }
        return {
            "provider": "nas_then_kuaidaili",
            "mode": "failover",
            "dynamic": True,
            "active_slot": self._state["active_slot"],
            "manual_slot": self._state.get("manual_slot"),
            "next_retry_at": self.next_retry_at,
            "slots": slots,
        }


def _build_provider(settings: Settings, provider_name: str,
                    *, static_url: str | None = None) -> ProxyProvider:
    provider_name = str(provider_name or "auto").strip().lower()
    if provider_name == "auto":
        provider_name = "static" if static_url else "direct"

    if provider_name in {"direct", "none"}:
        return DirectProxyProvider()
    if provider_name == "static":
        if not static_url:
            raise ConfigurationError(
                "static 出口必须配置代理 URL")
        return StaticProxyProvider(static_url)
    if provider_name in {"kuaidaili", "kuaidaili_dps", "kdl_dps"}:
        return KuaidailiDpsProvider(
            secret_id=settings.kdl_secret_id or "",
            secret_key=settings.kdl_secret_key or "",
            lease_seconds=settings.proxy_lease_seconds,
            area=settings.kdl_area,
            auth_mode=settings.kdl_auth_mode,
            proxy_username=settings.kdl_proxy_username or "",
            proxy_password=settings.kdl_proxy_password or "",
        )
    raise ConfigurationError(f"不支持的代理 provider: {provider_name}")


def build_proxy_manager(settings: Settings):
    if (settings.egress_mode in {"failover", "nas_then_dps"}
            or settings.primary_proxy_url
            or settings.fallback_proxy_provider):
        primary_url = settings.primary_proxy_url or settings.http_proxy_url
        if not primary_url:
            raise ConfigurationError("主备出口模式缺少住宅代理 URL")
        fallback_name = (
            settings.fallback_proxy_provider or "kuaidaili_dps")
        primary = ProxyLeaseManager(
            _build_provider(settings, "static", static_url=primary_url),
            expiry_safety_seconds=settings.proxy_expiry_safety_seconds,
            slot_id="nas-primary",
        )
        fallback = ProxyLeaseManager(
            _build_provider(settings, fallback_name),
            expiry_safety_seconds=settings.proxy_expiry_safety_seconds,
            slot_id="dps-fallback",
        )
        return FailoverProxyLeaseManager(
            primary,
            fallback,
            state_path=settings.resolved_egress_state_path,
            failure_threshold=settings.egress_failure_threshold,
            risk_threshold=settings.egress_risk_threshold,
            cooldown_seconds=settings.egress_cooldown_seconds,
            failback_successes=settings.egress_failback_successes,
            failback_interval_seconds=(
                settings.egress_failback_interval_seconds),
        )

    provider_name = str(settings.proxy_provider or "auto").strip().lower()
    if provider_name == "auto":
        provider_name = "static" if settings.http_proxy_url else "direct"
    provider = _build_provider(
        settings, provider_name, static_url=settings.http_proxy_url)

    return ProxyLeaseManager(
        provider,
        expiry_safety_seconds=settings.proxy_expiry_safety_seconds,
        slot_id="default",
    )


def is_proxy_failure_error(exc: BaseException) -> bool:
    """兼容旧调用方；协议错误不会再误判为代理故障。"""
    return classify_failure(exc).category in {
        FailureCategory.RISK_REJECTED,
        FailureCategory.PROXY_SUPPLY_FAILED,
        FailureCategory.TRANSPORT_FAILED,
    }
