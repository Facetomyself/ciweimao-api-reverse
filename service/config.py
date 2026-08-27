"""FastAPI 服务配置与本地凭据加载。"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import secrets

from client import config as client_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ConfigurationError(RuntimeError):
    """服务配置或本地凭据不完整。"""


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ConfigurationError(f"{name} 必须是整数") from exc
    return max(minimum, value)


def _env_float(name: str, default: float, minimum: float = 0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ConfigurationError(f"{name} 必须是数字") from exc
    return max(minimum, value)


def _env_secret(name: str, file_name: str) -> str | None:
    value = os.getenv(name, "").strip()
    if value:
        return value
    secret_path = os.getenv(file_name, "").strip()
    if not secret_path:
        return None
    try:
        return Path(secret_path).read_text(encoding="utf-8").strip() or None
    except OSError as exc:
        raise ConfigurationError(
            f"读取密钥文件失败: {file_name}={secret_path}") from exc


@dataclass(frozen=True, repr=False)
class Credentials:
    login_token: str
    account: str
    device_token: str


@dataclass(frozen=True)
class Settings:
    database_path: Path
    output_dir: Path
    token_path: Path
    identity_store_path: Path | None = None
    egress_state_path: Path | None = None
    protocol_profile: str = client_config.APP_VERSION
    guest_bootstrap_enabled: bool = False
    scheduler_enabled: bool = True
    scheduler_timezone: str = "Asia/Shanghai"
    sync_interval_minutes: int = 30
    auto_download_enabled: bool = True
    auto_download_batch_size: int = 100
    auto_download_failure_retry_minutes: int = 60
    auto_download_no_free_retry_hours: int = 24
    queue_workers: int = 1
    http_timeout: float = 30
    http_max_clients: int = 5
    http_max_retries: int = 2
    http_retry_backoff: float = 0.25
    http_transient_api_retries: int = 0
    http_impersonate: str | None = None
    http_proxy_url: str | None = field(default=None, repr=False)
    proxy_provider: str = "auto"
    egress_mode: str = "single"
    primary_proxy_url: str | None = field(default=None, repr=False)
    fallback_proxy_provider: str = ""
    egress_failure_threshold: int = 3
    egress_risk_threshold: int = 2
    egress_cooldown_seconds: float = 900
    egress_failback_successes: int = 2
    egress_failback_interval_seconds: float = 300
    proxy_lease_seconds: float = 1200
    proxy_expiry_safety_seconds: float = 30
    kdl_secret_id: str | None = field(default=None, repr=False)
    kdl_secret_key: str | None = field(default=None, repr=False)
    kdl_area: str = ""
    kdl_auth_mode: str = "auto"
    kdl_proxy_username: str | None = field(default=None, repr=False)
    kdl_proxy_password: str | None = field(default=None, repr=False)
    list_request_delay: float = 0.25
    chapter_concurrency: int = 3
    chapter_delay: float = 0.05
    readiness_require_protocol_probe: bool = False
    readiness_auto_probe_enabled: bool = False
    readiness_probe_max_age_seconds: int = 3600
    readiness_failure_streak_threshold: int = 3
    confirmation_ttl_seconds: int = 300
    archive_dir: Path | None = None
    archive_spool_max_bytes: int = 8 * 1024 * 1024 * 1024
    archive_local_retention_days: int = 7
    archive_maintenance_interval_hours: int = 24
    semantic_retention_days: int = 400
    archive_nas_path: str = (
        "/volume1/docker/ciweimao-api-reverse/archive")
    archive_ssh_host: str | None = field(default=None, repr=False)
    archive_ssh_port: int = 22
    archive_ssh_username: str | None = field(default=None, repr=False)
    archive_ssh_password: str | None = field(default=None, repr=False)
    archive_known_hosts_path: Path | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> "Settings":
        impersonate = os.getenv("CIWEIMAO_HTTP_IMPERSONATE", "").strip()
        if os.getenv("CIWEIMAO_SYNC_INTERVAL_MINUTES") is not None:
            sync_interval_minutes = _env_int(
                "CIWEIMAO_SYNC_INTERVAL_MINUTES", 30)
        elif os.getenv("CIWEIMAO_RANKING_INTERVAL_MINUTES") is not None:
            # 旧配置只保留榜单周期时，以它作为合并周期。
            sync_interval_minutes = _env_int(
                "CIWEIMAO_RANKING_INTERVAL_MINUTES", 30)
        elif os.getenv("CIWEIMAO_NEW_BOOKS_INTERVAL_MINUTES") is not None:
            sync_interval_minutes = _env_int(
                "CIWEIMAO_NEW_BOOKS_INTERVAL_MINUTES", 30)
        else:
            sync_interval_minutes = 30
        return cls(
            database_path=Path(os.getenv(
                "CIWEIMAO_DB_PATH",
                str(PROJECT_ROOT / "data" / "ciweimao.sqlite3"),
            )).expanduser().resolve(),
            output_dir=Path(os.getenv(
                "CIWEIMAO_OUTPUT_DIR",
                str(PROJECT_ROOT / "output_api"),
            )).expanduser().resolve(),
            token_path=Path(os.getenv(
                "CIWEIMAO_TOKEN_PATH",
                str(PROJECT_ROOT / "tokens.json"),
            )).expanduser().resolve(),
            identity_store_path=Path(os.getenv(
                "CIWEIMAO_IDENTITY_STORE_PATH",
                str(PROJECT_ROOT / "data" / "identity-store.json"),
            )).expanduser().resolve(),
            egress_state_path=Path(os.getenv(
                "CIWEIMAO_EGRESS_STATE_PATH",
                str(PROJECT_ROOT / "data" / "egress-state.json"),
            )).expanduser().resolve(),
            protocol_profile=os.getenv(
                "CIWEIMAO_PROTOCOL_PROFILE",
                client_config.APP_VERSION,
            ).strip(),
            guest_bootstrap_enabled=_env_bool(
                "CIWEIMAO_GUEST_BOOTSTRAP_ENABLED", False),
            scheduler_enabled=_env_bool(
                "CIWEIMAO_SCHEDULER_ENABLED", True),
            scheduler_timezone=os.getenv(
                "CIWEIMAO_SCHEDULER_TIMEZONE", "Asia/Shanghai"),
            sync_interval_minutes=sync_interval_minutes,
            auto_download_enabled=_env_bool(
                "CIWEIMAO_AUTO_DOWNLOAD_ENABLED", True),
            auto_download_batch_size=_env_int(
                "CIWEIMAO_AUTO_DOWNLOAD_BATCH_SIZE", 100),
            auto_download_failure_retry_minutes=_env_int(
                "CIWEIMAO_AUTO_DOWNLOAD_FAILURE_RETRY_MINUTES", 60),
            auto_download_no_free_retry_hours=_env_int(
                "CIWEIMAO_AUTO_DOWNLOAD_NO_FREE_RETRY_HOURS", 24),
            queue_workers=_env_int("CIWEIMAO_QUEUE_WORKERS", 1),
            http_timeout=_env_float("CIWEIMAO_HTTP_TIMEOUT", 30, 0.1),
            http_max_clients=_env_int("CIWEIMAO_HTTP_MAX_CLIENTS", 5),
            http_max_retries=_env_int(
                "CIWEIMAO_HTTP_MAX_RETRIES", 2, 0),
            http_retry_backoff=_env_float(
                "CIWEIMAO_HTTP_RETRY_BACKOFF", 0.25, 0),
            http_transient_api_retries=_env_int(
                "CIWEIMAO_HTTP_TRANSIENT_API_RETRIES", 0, 0),
            http_impersonate=impersonate or None,
            http_proxy_url=(
                os.getenv("CIWEIMAO_PROXY_URL", "").strip() or None),
            proxy_provider=os.getenv(
                "CIWEIMAO_PROXY_PROVIDER", "auto").strip().lower(),
            egress_mode=os.getenv(
                "CIWEIMAO_EGRESS_MODE", "single").strip().lower(),
            primary_proxy_url=(
                os.getenv("CIWEIMAO_PRIMARY_PROXY_URL", "").strip()
                or None),
            fallback_proxy_provider=os.getenv(
                "CIWEIMAO_FALLBACK_PROXY_PROVIDER", "").strip().lower(),
            egress_failure_threshold=_env_int(
                "CIWEIMAO_EGRESS_FAILURE_THRESHOLD", 3),
            egress_risk_threshold=_env_int(
                "CIWEIMAO_EGRESS_RISK_THRESHOLD", 2),
            egress_cooldown_seconds=_env_float(
                "CIWEIMAO_EGRESS_COOLDOWN_SECONDS", 900, 1),
            egress_failback_successes=_env_int(
                "CIWEIMAO_EGRESS_FAILBACK_SUCCESSES", 2),
            egress_failback_interval_seconds=_env_float(
                "CIWEIMAO_EGRESS_FAILBACK_INTERVAL_SECONDS", 300, 1),
            proxy_lease_seconds=_env_float(
                "CIWEIMAO_PROXY_LEASE_SECONDS", 1200, 1),
            proxy_expiry_safety_seconds=_env_float(
                "CIWEIMAO_PROXY_EXPIRY_SAFETY_SECONDS", 30, 0),
            kdl_secret_id=_env_secret(
                "KDL_SECRET_ID", "KDL_SECRET_ID_FILE"),
            kdl_secret_key=_env_secret(
                "KDL_SECRET_KEY", "KDL_SECRET_KEY_FILE"),
            kdl_area=os.getenv("CIWEIMAO_KDL_AREA", "").strip(),
            kdl_auth_mode=os.getenv(
                "CIWEIMAO_KDL_AUTH_MODE", "auto").strip().lower(),
            kdl_proxy_username=_env_secret(
                "KDL_PROXY_USERNAME", "KDL_PROXY_USERNAME_FILE"),
            kdl_proxy_password=_env_secret(
                "KDL_PROXY_PASSWORD", "KDL_PROXY_PASSWORD_FILE"),
            list_request_delay=_env_float(
                "CIWEIMAO_LIST_REQUEST_DELAY", 0.25, 0),
            chapter_concurrency=_env_int(
                "CIWEIMAO_CHAPTER_CONCURRENCY", 3),
            chapter_delay=_env_float(
                "CIWEIMAO_CHAPTER_DELAY", 0.05, 0),
            readiness_require_protocol_probe=_env_bool(
                "CIWEIMAO_READINESS_REQUIRE_PROTOCOL_PROBE", True),
            readiness_auto_probe_enabled=_env_bool(
                "CIWEIMAO_READINESS_AUTO_PROBE_ENABLED", True),
            readiness_probe_max_age_seconds=_env_int(
                "CIWEIMAO_READINESS_PROBE_MAX_AGE_SECONDS", 3600),
            readiness_failure_streak_threshold=_env_int(
                "CIWEIMAO_READINESS_FAILURE_STREAK_THRESHOLD", 3),
            confirmation_ttl_seconds=_env_int(
                "CIWEIMAO_CONFIRMATION_TTL_SECONDS", 300),
            archive_dir=Path(os.getenv(
                "CIWEIMAO_ARCHIVE_DIR",
                str(PROJECT_ROOT / "runtime" / "archive"),
            )).expanduser().resolve(),
            archive_spool_max_bytes=_env_int(
                "CIWEIMAO_ARCHIVE_SPOOL_MAX_BYTES",
                8 * 1024 * 1024 * 1024,
            ),
            archive_local_retention_days=_env_int(
                "CIWEIMAO_ARCHIVE_LOCAL_RETENTION_DAYS", 7),
            archive_maintenance_interval_hours=_env_int(
                "CIWEIMAO_ARCHIVE_MAINTENANCE_INTERVAL_HOURS", 24),
            semantic_retention_days=_env_int(
                "CIWEIMAO_SEMANTIC_RETENTION_DAYS", 400),
            archive_nas_path=os.getenv(
                "CIWEIMAO_ARCHIVE_NAS_PATH",
                "/volume1/docker/ciweimao-api-reverse/archive",
            ).strip(),
            archive_ssh_host=(
                os.getenv("CIWEIMAO_ARCHIVE_SSH_HOST", "").strip()
                or os.getenv("SSH_EXEC_HOST", "").strip()
                or None),
            archive_ssh_port=_env_int(
                "CIWEIMAO_ARCHIVE_SSH_PORT",
                _env_int("SSH_EXEC_PORT", 22)),
            archive_ssh_username=(
                os.getenv("CIWEIMAO_ARCHIVE_SSH_USERNAME", "").strip()
                or os.getenv("SSH_EXEC_USERNAME", "").strip()
                or None),
            archive_ssh_password=_env_secret(
                "CIWEIMAO_ARCHIVE_SSH_PASSWORD",
                "CIWEIMAO_ARCHIVE_SSH_PASSWORD_FILE",
            ),
            archive_known_hosts_path=(
                Path(os.getenv(
                    "CIWEIMAO_ARCHIVE_KNOWN_HOSTS_FILE", ""
                )).expanduser().resolve()
                if os.getenv(
                    "CIWEIMAO_ARCHIVE_KNOWN_HOSTS_FILE", "").strip()
                else None
            ),
        )

    @property
    def protocol(self) -> client_config.ProtocolProfile:
        try:
            return client_config.get_protocol_profile(self.protocol_profile)
        except ValueError as exc:
            raise ConfigurationError(str(exc)) from exc

    @property
    def app_version(self) -> str:
        return self.protocol.app_version

    @property
    def resolved_identity_store_path(self) -> Path:
        return (self.identity_store_path
                or self.token_path.with_name("identity-store.json"))

    @property
    def resolved_egress_state_path(self) -> Path:
        return (self.egress_state_path
                or self.token_path.with_name("egress-state.json"))

    def env_credentials_configured(self) -> bool:
        return bool(
            os.getenv("CIWEIMAO_LOGIN_TOKEN")
            and os.getenv("CIWEIMAO_ACCOUNT")
        )

    def credentials_configured(self) -> bool:
        return self.env_credentials_configured() or self.token_path.is_file()

    def load_credentials(self) -> Credentials:
        login_token = os.getenv("CIWEIMAO_LOGIN_TOKEN", "").strip()
        account = os.getenv("CIWEIMAO_ACCOUNT", "").strip()
        device_token = os.getenv("CIWEIMAO_DEVICE_TOKEN", "").strip()
        if not (login_token and account):
            if not self.token_path.is_file():
                raise ConfigurationError(
                    f"缺少 App 凭据文件: {self.token_path}")
            try:
                with open(self.token_path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, ValueError) as exc:
                raise ConfigurationError(
                    f"读取 App 凭据失败: {self.token_path}") from exc
            login_token = str(payload.get("login_token", "")).strip()
            account = str(payload.get("account", "")).strip()
            device_token = str(payload.get("device_token", "")).strip()
        if not login_token or not account:
            raise ConfigurationError("App 凭据缺少 login_token 或 account")
        return Credentials(
            login_token=login_token,
            account=account,
            device_token=(device_token
                          or client_config.DEVICE_TOKEN_PREFIX),
        )

    def save_credentials(self, credentials: Credentials,
                         *, reader_id: str = "") -> None:
        """以 0600 权限原子写入凭据文件。"""
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "login_token": credentials.login_token,
            "account": credentials.account,
            "device_token": credentials.device_token,
        }
        if reader_id:
            payload["reader_id"] = str(reader_id)
        text = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        temp_path = self.token_path.with_name(
            f".{self.token_path.name}.{os.getpid()}."
            f"{secrets.token_hex(4)}.tmp"
        )
        descriptor = None
        try:
            descriptor = os.open(
                temp_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(
                    descriptor, "w", encoding="utf-8", newline="\n") as handle:
                descriptor = None
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.token_path)
            os.chmod(self.token_path, 0o600)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temp_path.exists():
                temp_path.unlink()
