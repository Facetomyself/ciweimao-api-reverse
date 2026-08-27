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
from .identity import IdentityStore


LOGGER = logging.getLogger(__name__)
INVALID_CREDENTIAL_CODES = {"200100"}


@dataclass(frozen=True)
class CredentialBootstrapResult:
    created: bool
    source: str
    slot_id: str = "default"


class GuestCredentialBootstrapper:
    """只在缺失或失效时创建新游客，并原子替换本地凭据。"""

    def __init__(self, settings: Settings,
                 session_factory=AsyncSession,
                 registrar=register_guest,
                 identity_store: IdentityStore | None = None):
        self.settings = settings
        self.session_factory = session_factory
        self.registrar = registrar
        self.identity_store = identity_store or IdentityStore(
            settings.resolved_identity_store_path,
            legacy_token_path=settings.token_path,
        )
        self._lock = asyncio.Lock()

    async def ensure(
            self, proxy_url: str | None = None,
            identity_slot: str = "default") -> CredentialBootstrapResult:
        if proxy_url is None:
            proxy_url = self.settings.http_proxy_url
        async with self._lock:
            env_credentials = self.settings.env_credentials_configured()
            if env_credentials:
                credentials = self.settings.load_credentials()
            else:
                credentials = await self.identity_store.load_credentials(
                    identity_slot, self.settings.app_version)
            if credentials is None:
                return await self._register_and_persist(
                    "missing", proxy_url, identity_slot)

            try:
                await self._validate(credentials, proxy_url)
            except ApiError as exc:
                if exc.code not in INVALID_CREDENTIAL_CODES:
                    raise
                if env_credentials:
                    raise ConfigurationError(
                        "CIWEIMAO_* 环境凭据已失效，自动游客不能覆盖环境变量"
                    ) from exc
                return await self._register_and_persist(
                    f"invalid-{exc.code}", proxy_url, identity_slot)
            except RuntimeError as exc:
                if "login_token 已过期" not in str(exc):
                    raise
                if env_credentials:
                    raise ConfigurationError(
                        "CIWEIMAO_* 环境凭据已失效，自动游客不能覆盖环境变量"
                    ) from exc
                return await self._register_and_persist(
                    "expired", proxy_url, identity_slot)

            if not env_credentials:
                await self.identity_store.mark_validated(identity_slot)

            return CredentialBootstrapResult(
                created=False,
                source="environment" if env_credentials else "token-file",
                slot_id=identity_slot,
            )

    async def refresh(
            self, failed_credentials: Credentials,
            proxy_url: str | None = None,
            identity_slot: str = "default") -> CredentialBootstrapResult:
        """失效请求触发刷新；并发请求只允许第一个真正注册。"""
        if proxy_url is None:
            proxy_url = self.settings.http_proxy_url
        async with self._lock:
            if self.settings.env_credentials_configured():
                raise ConfigurationError(
                    "CIWEIMAO_* 环境凭据已失效，自动游客不能覆盖环境变量")
            current = await self.identity_store.load_credentials(
                identity_slot, self.settings.app_version)
            if current is None:
                return await self._register_and_persist(
                    "runtime-missing", proxy_url, identity_slot)
            if (_credential_fingerprint(current)
                    != _credential_fingerprint(failed_credentials)):
                return CredentialBootstrapResult(
                    created=False,
                    source="token-file-refreshed",
                    slot_id=identity_slot,
                )
            return await self._register_and_persist(
                "runtime-invalid", proxy_url, identity_slot)

    async def load_credentials(
            self, identity_slot: str,
            proxy_url: str | None = None) -> Credentials:
        if self.settings.env_credentials_configured():
            return self.settings.load_credentials()
        credentials = await self.identity_store.load_credentials(
            identity_slot, self.settings.app_version)
        if credentials is None:
            await self.ensure(
                proxy_url=proxy_url, identity_slot=identity_slot)
            credentials = await self.identity_store.load_credentials(
                identity_slot, self.settings.app_version)
        if credentials is None:
            raise ConfigurationError("游客身份创建后仍不可用")
        return credentials

    async def _register_and_persist(
            self, reason: str,
            proxy_url: str | None,
            identity_slot: str) -> CredentialBootstrapResult:
        LOGGER.info("guest credential bootstrap started: %s", reason)
        slot = await self.identity_store.ensure_slot(
            identity_slot, self.settings.app_version)
        guest = await self.registrar(
            app_version=self.settings.app_version,
            base_url=self.settings.protocol.guest_registration_base_url,
            timeout=self.settings.http_timeout,
            impersonate=(
                self.settings.http_impersonate
                or self.settings.protocol.impersonate),
            proxy=proxy_url,
            max_retries=self.settings.http_max_retries,
            retry_backoff=self.settings.http_retry_backoff,
            uuid_value=slot.profile.uuid,
        )
        credentials = Credentials(
            login_token=guest.login_token,
            account=guest.account,
            device_token=guest.device_token,
        )
        await self._validate(credentials, proxy_url)
        await self.identity_store.save_identity(
            identity_slot,
            self.settings.app_version,
            account=guest.account,
            login_token=guest.login_token,
            reader_id=guest.reader_id,
        )
        await asyncio.to_thread(
            self.settings.save_credentials,
            credentials,
            reader_id=guest.reader_id,
        )
        LOGGER.info("guest credential bootstrap completed")
        return CredentialBootstrapResult(
            created=True,
            source="guest-registration",
            slot_id=identity_slot,
        )

    async def _validate(self, credentials: Credentials,
                        proxy_url: str | None) -> None:
        session = self.session_factory(
            login_token=credentials.login_token,
            account=credentials.account,
            device_token=credentials.device_token,
            app_version=self.settings.app_version,
            base_url=self.settings.protocol.base_url,
            timeout=self.settings.http_timeout,
            impersonate=(
                self.settings.http_impersonate
                or self.settings.protocol.impersonate),
            max_clients=max(1, self.settings.http_max_clients),
            max_retries=self.settings.http_max_retries,
            retry_backoff=self.settings.http_retry_backoff,
            transient_api_retries=(
                self.settings.http_transient_api_retries),
            proxy=proxy_url,
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
