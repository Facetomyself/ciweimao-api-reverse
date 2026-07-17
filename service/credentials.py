"""FastAPI 启动前的游客凭据校验与自举。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import logging

from client import config as client_config
from client.api import ApiError, AsyncSession
from client.guest import register_guest

from .config import ConfigurationError, Credentials, Settings


LOGGER = logging.getLogger(__name__)
INVALID_CREDENTIAL_CODES = {"200100", "320002"}


@dataclass(frozen=True)
class CredentialBootstrapResult:
    created: bool
    source: str


class GuestCredentialBootstrapper:
    """只在缺失或失效时创建新游客，并原子替换本地凭据。"""

    def __init__(self, settings: Settings,
                 session_factory=AsyncSession,
                 registrar=register_guest):
        self.settings = settings
        self.session_factory = session_factory
        self.registrar = registrar
        self._lock = asyncio.Lock()

    async def ensure(self) -> CredentialBootstrapResult:
        async with self._lock:
            env_credentials = self.settings.env_credentials_configured()
            try:
                credentials = self.settings.load_credentials()
            except ConfigurationError:
                if env_credentials:
                    raise
                return await self._register_and_persist("missing")

            try:
                await self._validate(credentials)
            except ApiError as exc:
                if exc.code not in INVALID_CREDENTIAL_CODES:
                    raise
                if env_credentials:
                    raise ConfigurationError(
                        "CIWEIMAO_* 环境凭据已失效，自动游客不能覆盖环境变量"
                    ) from exc
                return await self._register_and_persist(
                    f"invalid-{exc.code}")
            except RuntimeError as exc:
                if "login_token 已过期" not in str(exc):
                    raise
                if env_credentials:
                    raise ConfigurationError(
                        "CIWEIMAO_* 环境凭据已失效，自动游客不能覆盖环境变量"
                    ) from exc
                return await self._register_and_persist("expired")

            return CredentialBootstrapResult(
                created=False,
                source="environment" if env_credentials else "token-file",
            )

    async def refresh(
            self, failed_credentials: Credentials) -> CredentialBootstrapResult:
        """失效请求触发刷新；并发请求只允许第一个真正注册。"""
        async with self._lock:
            if self.settings.env_credentials_configured():
                raise ConfigurationError(
                    "CIWEIMAO_* 环境凭据已失效，自动游客不能覆盖环境变量")
            try:
                current = self.settings.load_credentials()
            except ConfigurationError:
                return await self._register_and_persist("runtime-missing")
            if (_credential_fingerprint(current)
                    != _credential_fingerprint(failed_credentials)):
                return CredentialBootstrapResult(
                    created=False,
                    source="token-file-refreshed",
                )
            return await self._register_and_persist("runtime-invalid")

    async def _register_and_persist(
            self, reason: str) -> CredentialBootstrapResult:
        LOGGER.info("guest credential bootstrap started: %s", reason)
        guest = await self.registrar(
            app_version=client_config.APP_VERSION,
            timeout=self.settings.http_timeout,
            impersonate=self.settings.http_impersonate,
            proxy=self.settings.http_proxy_url,
            max_retries=self.settings.http_max_retries,
            retry_backoff=self.settings.http_retry_backoff,
        )
        credentials = Credentials(
            login_token=guest.login_token,
            account=guest.account,
            device_token=guest.device_token,
        )
        await self._validate(credentials)
        await asyncio.to_thread(
            self.settings.save_credentials,
            credentials,
            reader_id=guest.reader_id,
        )
        LOGGER.info("guest credential bootstrap completed")
        return CredentialBootstrapResult(
            created=True,
            source="guest-registration",
        )

    async def _validate(self, credentials: Credentials) -> None:
        session = self.session_factory(
            login_token=credentials.login_token,
            account=credentials.account,
            device_token=credentials.device_token,
            app_version=client_config.APP_VERSION,
            timeout=self.settings.http_timeout,
            impersonate=self.settings.http_impersonate,
            max_clients=max(1, self.settings.http_max_clients),
            max_retries=self.settings.http_max_retries,
            retry_backoff=self.settings.http_retry_backoff,
            transient_api_retries=(
                self.settings.http_transient_api_retries),
            proxy=self.settings.http_proxy_url,
        )
        async with session:
            await session.search_books("魔法", page=0, count=1)


def _credential_fingerprint(credentials: Credentials) -> str:
    digest = hashlib.sha256()
    digest.update(credentials.account.encode("utf-8"))
    digest.update(b"\0")
    digest.update(credentials.login_token.encode("utf-8"))
    return digest.hexdigest()


def is_invalid_credentials_error(exc: BaseException) -> bool:
    if isinstance(exc, ApiError):
        return exc.code in INVALID_CREDENTIAL_CODES
    return (isinstance(exc, RuntimeError)
            and "login_token 已过期" in str(exc))
