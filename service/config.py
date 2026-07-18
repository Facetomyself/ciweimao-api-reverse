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
    guest_bootstrap_enabled: bool = False
    scheduler_enabled: bool = True
    scheduler_timezone: str = "Asia/Shanghai"
    ranking_interval_minutes: int = 30
    new_books_interval_minutes: int = 10
    queue_workers: int = 1
    http_timeout: float = 30
    http_max_clients: int = 5
    http_max_retries: int = 2
    http_retry_backoff: float = 0.25
    http_transient_api_retries: int = 1
    http_impersonate: str | None = None
    http_proxy_url: str | None = field(default=None, repr=False)
    proxy_provider: str = "auto"
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

    @classmethod
    def from_env(cls) -> "Settings":
        impersonate = os.getenv("CIWEIMAO_HTTP_IMPERSONATE", "").strip()
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
            guest_bootstrap_enabled=_env_bool(
                "CIWEIMAO_GUEST_BOOTSTRAP_ENABLED", False),
            scheduler_enabled=_env_bool(
                "CIWEIMAO_SCHEDULER_ENABLED", True),
            scheduler_timezone=os.getenv(
                "CIWEIMAO_SCHEDULER_TIMEZONE", "Asia/Shanghai"),
            ranking_interval_minutes=_env_int(
                "CIWEIMAO_RANKING_INTERVAL_MINUTES", 30),
            new_books_interval_minutes=_env_int(
                "CIWEIMAO_NEW_BOOKS_INTERVAL_MINUTES", 10),
            queue_workers=_env_int("CIWEIMAO_QUEUE_WORKERS", 1),
            http_timeout=_env_float("CIWEIMAO_HTTP_TIMEOUT", 30, 0.1),
            http_max_clients=_env_int("CIWEIMAO_HTTP_MAX_CLIENTS", 5),
            http_max_retries=_env_int(
                "CIWEIMAO_HTTP_MAX_RETRIES", 2, 0),
            http_retry_backoff=_env_float(
                "CIWEIMAO_HTTP_RETRY_BACKOFF", 0.25, 0),
            http_transient_api_retries=_env_int(
                "CIWEIMAO_HTTP_TRANSIENT_API_RETRIES", 1, 0),
            http_impersonate=impersonate or None,
            http_proxy_url=(
                os.getenv("CIWEIMAO_PROXY_URL", "").strip() or None),
            proxy_provider=os.getenv(
                "CIWEIMAO_PROXY_PROVIDER", "auto").strip().lower(),
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
        )

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
