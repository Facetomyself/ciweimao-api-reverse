"""SQLite 一致性备份、raw 冷档与 NAS 镜像。"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import sqlite3
from typing import Iterable
import uuid

from .config import ConfigurationError, Settings
from .database import Database, utc_now


class ArchiveError(RuntimeError):
    pass


class ArchiveSpoolFull(ArchiveError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(
        item.stat().st_size for item in path.rglob("*") if item.is_file())


class ArchiveManager:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        self.root = (settings.archive_dir
                     or settings.database_path.parent / "archive")
        self.root = self.root.resolve()
        self._lock = asyncio.Lock()

    @property
    def remote_configured(self) -> bool:
        return bool(
            self.settings.archive_ssh_host
            and self.settings.archive_ssh_username
            and self.settings.archive_ssh_password
            and self.settings.archive_known_hosts_path
        )

    def _ensure_capacity(self, incoming_bytes: int = 0) -> None:
        used = _directory_size(self.root)
        if used + max(0, int(incoming_bytes)) > int(
                self.settings.archive_spool_max_bytes):
            raise ArchiveSpoolFull(
                "archive spool 已达到配额，raw 归档暂停")

    @staticmethod
    def _record_line(record: dict) -> bytes:
        payload = {
            "id": record.get("id"),
            "record_type": record.get("record_type"),
            "source_id": record.get("source_id"),
            "captured_at": record.get("captured_at"),
            "payload": json.loads(record.get("payload_json") or "{}"),
        }
        return (json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"))
            + "\n").encode("utf-8")

    def _write_records(self, records: list[dict], *,
                       archive_type: str, period: str) -> dict:
        if not records:
            raise ValueError("归档记录不能为空")
        target_dir = self.root / archive_type / period[:7]
        target_dir.mkdir(parents=True, exist_ok=True)
        suffix = uuid.uuid4().hex[:8]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"{period}-{stamp}-{suffix}.jsonl.gz"
        target = target_dir / filename
        partial = target.with_suffix(target.suffix + ".partial")
        estimated = sum(len(str(row.get("payload_json", ""))) for row in records)
        self._ensure_capacity(estimated)
        try:
            with gzip.open(partial, "wb", compresslevel=6) as output:
                for record in records:
                    output.write(self._record_line(record))
            os.replace(partial, target)
        finally:
            if partial.exists():
                partial.unlink()
        digest = _sha256(target)
        manifest = {
            "schema": "ciweimao-raw-archive.v1",
            "archive_type": archive_type,
            "period": period,
            "file": target.name,
            "record_count": len(records),
            "first_record_at": records[0].get("captured_at"),
            "last_record_at": records[-1].get("captured_at"),
            "file_size": target.stat().st_size,
            "sha256": digest,
            "created_at": utc_now(),
        }
        manifest_path = target.with_suffix(target.suffix + ".manifest.json")
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
        return {**manifest, "path": str(target),
                "manifest_path": str(manifest_path)}

    def _connect_ssh(self):
        if not self.remote_configured:
            raise ConfigurationError("NAS archive SSH 未完整配置")
        try:
            import paramiko
        except ImportError as exc:
            raise ArchiveError("缺少 paramiko") from exc
        known_hosts = self.settings.archive_known_hosts_path
        if known_hosts is None or not known_hosts.is_file():
            raise ConfigurationError("NAS archive known_hosts 不存在")
        client = paramiko.SSHClient()
        client.load_host_keys(str(known_hosts))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(
            hostname=self.settings.archive_ssh_host,
            port=self.settings.archive_ssh_port,
            username=self.settings.archive_ssh_username,
            password=self.settings.archive_ssh_password,
            look_for_keys=False,
            allow_agent=False,
            timeout=15,
            banner_timeout=15,
            auth_timeout=15,
        )
        return client

    @staticmethod
    def _mkdir_sftp(sftp, remote_dir: str) -> None:
        current = PurePosixPath("/")
        for part in PurePosixPath(remote_dir).parts[1:]:
            current /= part
            try:
                sftp.stat(str(current))
            except OSError:
                sftp.mkdir(str(current))

    def _upload(self, local_path: Path, remote_path: str,
                expected_sha256: str) -> None:
        client = self._connect_ssh()
        try:
            sftp = client.open_sftp()
            try:
                self._mkdir_sftp(
                    sftp, str(PurePosixPath(remote_path).parent))
                partial = remote_path + ".partial"
                sftp.put(str(local_path), partial)
                if int(sftp.stat(partial).st_size) != local_path.stat().st_size:
                    raise ArchiveError("NAS 上传后文件大小不一致")
                try:
                    sftp.posix_rename(partial, remote_path)
                except (AttributeError, OSError):
                    try:
                        sftp.remove(remote_path)
                    except OSError:
                        pass
                    sftp.rename(partial, remote_path)
            finally:
                sftp.close()
            command = "sha256sum -- " + shlex.quote(remote_path)
            _, stdout, stderr = client.exec_command(command, timeout=120)
            remote_digest = stdout.read().decode("utf-8", "replace").split()
            error = stderr.read().decode("utf-8", "replace").strip()
            if not remote_digest or remote_digest[0] != expected_sha256:
                raise ArchiveError(
                    f"NAS SHA-256 校验失败: {error or 'digest mismatch'}")
        finally:
            client.close()

    def _download(self, remote_path: str, local_path: Path,
                  expected_sha256: str) -> None:
        self._ensure_capacity()
        client = self._connect_ssh()
        local_path.parent.mkdir(parents=True, exist_ok=True)
        partial = local_path.with_suffix(local_path.suffix + ".partial")
        try:
            sftp = client.open_sftp()
            try:
                self._ensure_capacity(int(sftp.stat(remote_path).st_size))
                sftp.get(remote_path, str(partial))
            finally:
                sftp.close()
            if _sha256(partial) != expected_sha256:
                raise ArchiveError("NAS 恢复文件 SHA-256 不一致")
            os.replace(partial, local_path)
        finally:
            client.close()
            if partial.exists():
                partial.unlink()

    async def _catalog_and_mirror(self, artifact: dict, *,
                                  archive_type: str,
                                  period: str) -> dict:
        local = Path(artifact["path"])
        relative = local.relative_to(self.root).as_posix()
        remote = str(PurePosixPath(
            self.settings.archive_nas_path) / relative)
        status = "local_only"
        error = None
        if self.remote_configured:
            try:
                await asyncio.to_thread(
                    self._upload, local, remote, artifact["sha256"])
                manifest = Path(artifact["manifest_path"])
                await asyncio.to_thread(
                    self._upload,
                    manifest,
                    remote + ".manifest.json",
                    _sha256(manifest),
                )
                status = "mirrored"
            except Exception as exc:
                error = str(exc)
        catalog = await self.database.upsert_archive(
            archive_type=archive_type,
            period=period,
            local_path=str(local),
            nas_path=remote if self.remote_configured else "",
            status=status,
            record_count=artifact["record_count"],
            file_size=artifact["file_size"],
            sha256=artifact["sha256"],
            first_record_at=artifact["first_record_at"],
            last_record_at=artifact["last_record_at"],
            error=error,
        )
        return {**catalog, **artifact, "nas_path": remote,
                "status": status, "error": error}

    async def archive_pending_raw(self) -> list[dict]:
        async with self._lock:
            records = await self.database.list_pending_raw_records(
                limit=100000)
            grouped: dict[str, list[dict]] = defaultdict(list)
            for record in records:
                grouped[str(record["captured_at"])[:10]].append(record)
            results = []
            for period, group in sorted(grouped.items()):
                artifact = await asyncio.to_thread(
                    self._write_records,
                    group,
                    archive_type="raw",
                    period=period,
                )
                result = await self._catalog_and_mirror(
                    artifact, archive_type="raw", period=period)
                record_ids = [str(row["id"]) for row in group]
                await self.database.mark_raw_records_archived(record_ids)
                # gzip + manifest 已原子落盘并登记 catalog 后，SQLite 中的
                # raw payload 只是重复副本，应立即删除以避免热库再膨胀。
                await self.database.delete_archived_raw_records(record_ids)
                results.append(result)
            return results

    async def archive_legacy_observations(self) -> list[dict]:
        async with self._lock:
            rows = await self.database.list_legacy_observation_raw(
                limit=500000)
            if not rows:
                return []
            records = [{
                "id": f"legacy:{row['snapshot_id']}:{row['book_id']}",
                "record_type": "legacy_observation",
                "source_id": (
                    f"{row['snapshot_id']}:{row['position']}"),
                "captured_at": row["observed_at"],
                "payload_json": row["raw_json"],
            } for row in rows]
            grouped: dict[str, list[dict]] = defaultdict(list)
            for record in records:
                grouped[str(record["captured_at"])[:7]].append(record)
            results = []
            for period, group in sorted(grouped.items()):
                artifact = await asyncio.to_thread(
                    self._write_records,
                    group,
                    archive_type="legacy-observations",
                    period=f"{period}-01",
                )
                result = await self._catalog_and_mirror(
                    artifact,
                    archive_type="legacy-observations",
                    period=period,
                )
                if self.remote_configured and result["status"] != "mirrored":
                    raise ArchiveError("legacy raw 尚未成功镜像 NAS")
                results.append(result)
            await self.database.clear_legacy_observation_raw()
            return results

    def _backup_sync(self, target: Path) -> dict:
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".partial")
        source = sqlite3.connect(str(self.database.path))
        destination = sqlite3.connect(str(partial))
        backup_error = None
        try:
            source.backup(destination)
        except Exception as exc:
            backup_error = exc
        finally:
            destination.close()
            source.close()
        if backup_error is not None:
            partial.unlink(missing_ok=True)
            raise backup_error
        os.replace(partial, target)
        check = sqlite3.connect(str(target))
        try:
            integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            check.close()
        if integrity != "ok":
            target.unlink(missing_ok=True)
            raise ArchiveError(f"SQLite backup integrity_check={integrity}")
        return {
            "path": str(target),
            "record_count": 1,
            "file_size": target.stat().st_size,
            "sha256": _sha256(target),
            "first_record_at": utc_now(),
            "last_record_at": utc_now(),
        }

    async def create_backup(self, *, label: str = "daily") -> dict:
        async with self._lock:
            self._ensure_capacity(
                self.database.path.stat().st_size
                if self.database.path.exists() else 0)
            period = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            path = self.root / "backups" / period[:7] / (
                f"ciweimao-{period}-{label}-{uuid.uuid4().hex[:8]}.sqlite3")
            artifact = await asyncio.to_thread(self._backup_sync, path)
            artifact["manifest_path"] = str(path) + ".manifest.json"
            Path(artifact["manifest_path"]).write_text(
                json.dumps({
                    "schema": "ciweimao-sqlite-backup.v1",
                    **artifact,
                    "created_at": utc_now(),
                }, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8", newline="\n")
            return await self._catalog_and_mirror(
                artifact, archive_type="sqlite-backup", period=period)

    async def retry_mirrors(self) -> list[dict]:
        if not self.remote_configured:
            return []
        results = []
        for archive in await self.database.list_archives(limit=1000):
            if archive["status"] == "mirrored":
                continue
            local = Path(archive["local_path"])
            if not local.is_file():
                continue
            remote_path = archive.get("nas_path") or str(
                PurePosixPath(self.settings.archive_nas_path)
                / local.relative_to(self.root).as_posix())
            try:
                await asyncio.to_thread(
                    self._upload, local, remote_path,
                    archive["sha256"])
                manifest = Path(str(local) + ".manifest.json")
                if manifest.is_file():
                    await asyncio.to_thread(
                        self._upload,
                        manifest,
                        remote_path + ".manifest.json",
                        _sha256(manifest),
                    )
                status, error = "mirrored", None
            except Exception as exc:
                status, error = "local_only", str(exc)
            await self.database.upsert_archive(
                archive_type=archive["archive_type"],
                period=archive["period"],
                local_path=archive["local_path"],
                nas_path=remote_path,
                status=status,
                record_count=archive["record_count"],
                file_size=archive["file_size"],
                sha256=archive["sha256"],
                first_record_at=archive["first_record_at"],
                last_record_at=archive["last_record_at"],
                error=error,
            )
            results.append({"id": archive["id"], "status": status,
                            "error": error})
        return results

    async def ensure_local(self, archive: dict) -> Path:
        path = Path(archive["local_path"]).resolve()
        if path.is_file() and _sha256(path) == archive["sha256"]:
            return path
        if not archive.get("nas_path"):
            raise ArchiveError("归档本地缺失且没有 NAS 副本")
        await asyncio.to_thread(
            self._download,
            archive["nas_path"],
            path,
            archive["sha256"],
        )
        return path

    async def prune_mirrored_local(self) -> dict:
        """NAS 校验后的本地副本只保留短窗口，catalog 与远端长期保留。"""
        if not self.remote_configured:
            return {"removed": 0, "bytes": 0, "reason": "remote-disabled"}
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=self.settings.archive_local_retention_days)
        removed = 0
        released = 0
        for archive in await self.database.list_archives(limit=1000):
            if archive.get("status") != "mirrored":
                continue
            try:
                updated = datetime.fromisoformat(
                    str(archive["updated_at"]).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if updated.astimezone(timezone.utc) > cutoff:
                continue
            local = Path(archive["local_path"])
            manifest = Path(str(local) + ".manifest.json")
            for target in (local, manifest):
                if target.is_file():
                    released += target.stat().st_size
                    target.unlink()
            removed += 1
        return {"removed": removed, "bytes": released}

    async def status(self) -> dict:
        pending = await self.database.list_pending_raw_records(limit=100000)
        archives = await self.database.list_archives(limit=1000)
        used = await asyncio.to_thread(_directory_size, self.root)
        return {
            "root": str(self.root),
            "spool_bytes": used,
            "spool_limit_bytes": self.settings.archive_spool_max_bytes,
            "spool_ratio": round(
                used / max(1, self.settings.archive_spool_max_bytes), 4),
            "pending_raw_records": len(pending),
            "remote_configured": self.remote_configured,
            "archives": len(archives),
            "mirrored": sum(
                1 for item in archives if item["status"] == "mirrored"),
            "local_only": sum(
                1 for item in archives if item["status"] != "mirrored"),
        }

    async def preview_maintenance(self) -> dict:
        legacy = await self.database.list_legacy_observation_raw(limit=500000)
        pending = await self.database.list_pending_raw_records(limit=100000)
        cutoff = (
            datetime.now(timezone.utc) - timedelta(
                days=self.settings.semantic_retention_days)
        ).isoformat(timespec="milliseconds")
        return {
            "legacy_raw_records": len(legacy),
            "pending_raw_records": len(pending),
            "semantic_cutoff": cutoff,
            "database_bytes": (
                self.database.path.stat().st_size
                if self.database.path.exists() else 0),
            "archive": await self.status(),
        }

    async def run_maintenance(self, *, compact: bool = False) -> dict:
        mirrors_before = await self.retry_mirrors()
        local_prune = await self.prune_mirrored_local()
        backup = await self.create_backup(label="pre-maintenance")
        pending = await self.archive_pending_raw()
        legacy = await self.archive_legacy_observations()
        compact_result = None
        if compact:
            compact_result = await self.database.compact_observations()
        cutoff = (
            datetime.now(timezone.utc) - timedelta(
                days=self.settings.semantic_retention_days)
        ).isoformat(timespec="milliseconds")
        pruned = await self.database.prune_semantic_history(before=cutoff)
        mirrors_after = await self.retry_mirrors()
        return {
            "backup": backup,
            "pending_archives": pending,
            "legacy_archives": legacy,
            "compaction": compact_result,
            "pruned": pruned,
            "mirrors_before": mirrors_before,
            "mirrors_after": mirrors_after,
            "local_prune": local_prune,
        }
