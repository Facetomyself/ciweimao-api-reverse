"""稳定设备档案与按出口隔离的游客身份存储。"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
from uuid import uuid4

from client import config as client_config

from .config import Credentials


IDENTITY_STORE_SCHEMA = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class DeviceProfile:
    profile_id: str
    app_version: str
    uuid: str
    device_token: str
    transport_profile: str
    created_at: str
    updated_at: str
    origin: str = "generated"


@dataclass(frozen=True, repr=False)
class GuestIdentity:
    account: str
    login_token: str
    reader_id: str
    status: str
    created_at: str
    updated_at: str
    last_validated_at: str | None = None

    def credentials(self, profile: DeviceProfile) -> Credentials:
        return Credentials(
            login_token=self.login_token,
            account=self.account,
            device_token=profile.device_token,
        )


@dataclass(frozen=True)
class IdentitySlot:
    slot_id: str
    profile: DeviceProfile
    identity: GuestIdentity | None


class IdentityStore:
    """版本化 JSON store；凭据不进入 SQLite 或 API。"""

    def __init__(self, path: str | Path, *,
                 legacy_token_path: str | Path | None = None):
        self.path = Path(path).resolve()
        self.legacy_token_path = (
            Path(legacy_token_path).resolve()
            if legacy_token_path is not None else None
        )
        self._lock = asyncio.Lock()

    @staticmethod
    def _empty() -> dict:
        return {"schema": IDENTITY_STORE_SCHEMA, "slots": {}}

    def _read(self) -> dict:
        if not self.path.is_file():
            return self._empty()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"读取身份存储失败: {self.path}") from exc
        if int(payload.get("schema", 0)) != IDENTITY_STORE_SCHEMA:
            raise RuntimeError("身份存储 schema 不受支持")
        if not isinstance(payload.get("slots"), dict):
            raise RuntimeError("身份存储缺少 slots")
        return payload

    def _write(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        temp = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
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

    @staticmethod
    def _slot_from_payload(slot_id: str, value: dict) -> IdentitySlot:
        profile = DeviceProfile(**value["profile"])
        identity_payload = value.get("identity")
        identity = (
            GuestIdentity(**identity_payload) if identity_payload else None)
        return IdentitySlot(slot_id=slot_id, profile=profile,
                            identity=identity)

    @staticmethod
    def _new_profile(app_version: str, *, origin: str) -> DeviceProfile:
        now = _utc_now()
        return DeviceProfile(
            profile_id=f"device-{uuid4()}",
            app_version=app_version,
            uuid=f"android{uuid4()}",
            device_token=client_config.DEVICE_TOKEN_PREFIX,
            transport_profile="native-curl",
            created_at=now,
            updated_at=now,
            origin=origin,
        )

    def _read_legacy_identity(self) -> dict | None:
        path = self.legacy_token_path
        if path is None or not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        account = str(payload.get("account", "")).strip()
        token = str(payload.get("login_token", "")).strip()
        if not account or not token:
            return None
        return {
            "account": account,
            "login_token": token,
            "reader_id": str(payload.get("reader_id", "")).strip(),
        }

    async def ensure_slot(self, slot_id: str,
                          app_version: str) -> IdentitySlot:
        async with self._lock:
            payload = self._read()
            existing = payload["slots"].get(slot_id)
            if existing:
                slot = self._slot_from_payload(slot_id, existing)
                if slot.profile.app_version == app_version:
                    return slot
                profile = DeviceProfile(
                    **{
                        **asdict(slot.profile),
                        "app_version": app_version,
                        "updated_at": _utc_now(),
                    }
                )
                existing["profile"] = asdict(profile)
                self._write(payload)
                return IdentitySlot(slot_id, profile, slot.identity)

            profile = self._new_profile(app_version, origin="generated")
            identity = None
            if slot_id in {"default", "nas-primary"}:
                legacy = self._read_legacy_identity()
                if legacy:
                    now = _utc_now()
                    profile = DeviceProfile(
                        **{**asdict(profile), "origin": "legacy-token-import"})
                    identity = GuestIdentity(
                        **legacy,
                        status="unvalidated",
                        created_at=now,
                        updated_at=now,
                    )
            payload["slots"][slot_id] = {
                "profile": asdict(profile),
                "identity": asdict(identity) if identity else None,
            }
            self._write(payload)
            return IdentitySlot(slot_id, profile, identity)

    async def load_credentials(self, slot_id: str,
                               app_version: str) -> Credentials | None:
        slot = await self.ensure_slot(slot_id, app_version)
        if slot.identity is None:
            return None
        return slot.identity.credentials(slot.profile)

    async def save_identity(self, slot_id: str, app_version: str, *,
                            account: str, login_token: str,
                            reader_id: str = "",
                            status: str = "valid") -> IdentitySlot:
        async with self._lock:
            payload = self._read()
            existing = payload["slots"].get(slot_id)
            if existing:
                profile = DeviceProfile(**existing["profile"])
            else:
                profile = self._new_profile(
                    app_version, origin="guest-registration")
            now = _utc_now()
            previous_identity = (
                (existing or {}).get("identity") or {})
            identity = GuestIdentity(
                account=str(account),
                login_token=str(login_token),
                reader_id=str(reader_id or ""),
                status=status,
                created_at=previous_identity.get("created_at", now),
                updated_at=now,
                last_validated_at=now if status == "valid" else None,
            )
            payload["slots"][slot_id] = {
                "profile": asdict(profile),
                "identity": asdict(identity),
            }
            self._write(payload)
            return IdentitySlot(slot_id, profile, identity)

    async def mark_validated(self, slot_id: str) -> None:
        async with self._lock:
            payload = self._read()
            slot = payload["slots"].get(slot_id)
            if not slot or not slot.get("identity"):
                return
            now = _utc_now()
            slot["identity"].update({
                "status": "valid",
                "updated_at": now,
                "last_validated_at": now,
            })
            self._write(payload)

    async def invalidate(self, slot_id: str, status: str) -> None:
        async with self._lock:
            payload = self._read()
            slot = payload["slots"].get(slot_id)
            if not slot or not slot.get("identity"):
                return
            slot["identity"].update({
                "status": str(status),
                "updated_at": _utc_now(),
            })
            self._write(payload)

    async def rotate_profile(self, slot_id: str,
                             app_version: str) -> IdentitySlot:
        async with self._lock:
            payload = self._read()
            profile = self._new_profile(
                app_version, origin="explicit-rotation")
            payload["slots"][slot_id] = {
                "profile": asdict(profile),
                "identity": None,
            }
            self._write(payload)
            return IdentitySlot(slot_id, profile, None)

    async def snapshot(self) -> dict:
        async with self._lock:
            payload = self._read()
            slots = []
            for slot_id, value in sorted(payload["slots"].items()):
                profile = value.get("profile") or {}
                identity = value.get("identity") or {}
                slots.append({
                    "slot_id": slot_id,
                    "profile_id": profile.get("profile_id"),
                    "app_version": profile.get("app_version"),
                    "transport_profile": profile.get("transport_profile"),
                    "origin": profile.get("origin"),
                    "has_identity": bool(identity),
                    "identity_status": identity.get("status"),
                    "last_validated_at": identity.get("last_validated_at"),
                    "updated_at": (
                        identity.get("updated_at")
                        or profile.get("updated_at")),
                })
            return {"schema": payload["schema"], "slots": slots}
