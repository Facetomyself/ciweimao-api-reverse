"""身份、出口、归档和 durable 恢复链路测试。"""

import asyncio
import gzip
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from client.api import ApiError
from service.archive import ArchiveManager
from service.config import Settings
from service.database import Database, utc_now
from service.failures import (
    EgressUnavailableError,
    FailureCategory,
    classify_failure,
)
from service.identity import IdentityStore
from service.proxy import (
    FailoverProxyLeaseManager,
    ProxyLeaseManager,
)
from service.queue import PersistentTaskQueue


class FakeProvider:
    def __init__(self, name, url, *, dynamic=False, error=None):
        self.name = name
        self.url = url
        self.dynamic = dynamic
        self.lease_seconds = 1200 if dynamic else None
        self.error = error
        self.calls = 0

    async def acquire(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.url


class FailureAndIdentityTests(unittest.IsolatedAsyncioTestCase):
    def test_failure_categories_do_not_mix_risk_and_credentials(self):
        expired = classify_failure(ApiError("200100", "expired"))
        risk = classify_failure(ApiError("320002", "retry"))
        protocol = classify_failure(ApiError("310017", "bad sign"))

        self.assertEqual(FailureCategory.CREDENTIAL_EXPIRED, expired.category)
        self.assertTrue(expired.refresh_identity)
        self.assertEqual(FailureCategory.RISK_REJECTED, risk.category)
        self.assertFalse(risk.refresh_identity)
        self.assertTrue(risk.switch_egress)
        self.assertEqual(
            FailureCategory.PROTOCOL_INCOMPATIBLE, protocol.category)

    async def test_identity_slot_affinity_and_explicit_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "tokens.json"
            legacy.write_text(json.dumps({
                "account": "legacy-account",
                "login_token": "legacy-token",
            }), encoding="utf-8")
            store = IdentityStore(
                root / "identity.json", legacy_token_path=legacy)

            primary = await store.ensure_slot("nas-primary", "2.9.362")
            primary_again = await store.ensure_slot(
                "nas-primary", "2.9.362")
            fallback = await store.ensure_slot(
                "dps-fallback", "2.9.362")

            self.assertEqual(primary.profile.uuid, primary_again.profile.uuid)
            self.assertNotEqual(primary.profile.uuid, fallback.profile.uuid)
            self.assertIsNotNone(primary.identity)
            self.assertIsNone(fallback.identity)
            snapshot_text = json.dumps(await store.snapshot())
            self.assertNotIn("login_token", snapshot_text)
            self.assertNotIn("legacy-account", snapshot_text)
            rotated = await store.rotate_profile(
                "nas-primary", "2.9.362")
            self.assertNotEqual(primary.profile.uuid, rotated.profile.uuid)
            self.assertIsNone(rotated.identity)


class FailoverTests(unittest.IsolatedAsyncioTestCase):
    async def test_breaker_persists_and_fails_back_after_two_probes(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = [1000.0]
            state_path = Path(tmp) / "egress.json"
            primary_provider = FakeProvider(
                "static", "socks5h://nas:1080")
            fallback_provider = FakeProvider(
                "kuaidaili_dps", "http://fallback:8000", dynamic=True)

            def build():
                return FailoverProxyLeaseManager(
                    ProxyLeaseManager(
                        primary_provider, slot_id="nas-primary"),
                    ProxyLeaseManager(
                        fallback_provider, slot_id="dps-fallback"),
                    state_path=state_path,
                    risk_threshold=2,
                    cooldown_seconds=10,
                    failback_successes=2,
                    failback_interval_seconds=5,
                    wall_clock=lambda: now[0],
                )

            manager = build()
            primary = await manager.acquire()
            manager.report_failure(primary, FailureCategory.RISK_REJECTED)
            manager.report_failure(primary, FailureCategory.RISK_REJECTED)
            fallback = await manager.acquire()
            self.assertEqual("dps-fallback", fallback.slot_id)

            reloaded = build()
            self.assertEqual(
                "open",
                reloaded.snapshot()["slots"]["nas-primary"]["state"],
            )
            now[0] = 1011.0
            first_probe = await reloaded.acquire()
            self.assertEqual("nas-primary", first_probe.slot_id)
            reloaded.report_success(first_probe)
            self.assertEqual(
                "open",
                reloaded.snapshot()["slots"]["nas-primary"]["state"],
            )
            now[0] = 1017.0
            second_probe = await reloaded.acquire()
            reloaded.report_success(second_probe)
            self.assertEqual(
                "closed",
                reloaded.snapshot()["slots"]["nas-primary"]["state"],
            )


class ArchiveAndDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.database = Database(self.root / "service.sqlite3")
        await self.database.initialize()
        self.settings = Settings(
            database_path=self.database.path,
            output_dir=self.root / "output",
            token_path=self.root / "tokens.json",
            archive_dir=self.root / "archive",
            scheduler_enabled=False,
        )
        self.archive = ArchiveManager(self.settings, self.database)

    async def asyncTearDown(self):
        self.tempdir.cleanup()

    async def test_raw_archive_manifest_backup_and_compaction(self):
        snapshot = await self.database.create_snapshot(
            "ranking", "fans_value:week", [{
                "book_id": "1",
                "book_name": "测试书",
                "author_name": "作者",
                "total_word_count": "123",
            }], {"fixture": True})
        results = await self.archive.archive_pending_raw()
        self.assertEqual(1, len(results))
        artifact = results[0]
        self.assertTrue(Path(artifact["path"]).is_file())
        self.assertTrue(Path(artifact["manifest_path"]).is_file())
        with gzip.open(artifact["path"], "rt", encoding="utf-8") as handle:
            record = json.loads(handle.readline())
        self.assertEqual("1", record["payload"]["book_id"])
        self.assertEqual(
            [], await self.database.list_pending_raw_records(limit=10))

        backup = await self.archive.create_backup(label="test")
        check = sqlite3.connect(backup["path"])
        try:
            self.assertEqual(
                "ok", check.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            check.close()

        async with self.database.connect() as connection:
            await connection.execute(
                "UPDATE observations SET raw_json = ? WHERE snapshot_id = ?",
                (json.dumps({"legacy": True}), snapshot["id"]),
            )
            await connection.commit()
        legacy = await self.archive.archive_legacy_observations()
        self.assertEqual(1, len(legacy))
        compacted = await self.database.compact_observations()
        self.assertTrue(compacted["compacted"])
        latest = await self.database.get_latest_snapshot(
            "ranking", "fans_value:week")
        self.assertEqual("测试书", latest["items"][0]["book_name"])
        async with self.database.connect() as connection:
            columns = await self.database._table_columns(
                connection, "observations")
        self.assertNotIn("raw_json", columns)

    async def test_compaction_failure_keeps_original_table(self):
        await self.database.create_snapshot(
            "ranking", "fixture", [{"book_id": "1"}], {})
        await self.database.clear_legacy_observation_raw()
        async with self.database.connect() as connection:
            await connection.execute(
                "CREATE TABLE observations_compact (id TEXT)")
            await connection.commit()
        with self.assertRaises(sqlite3.OperationalError):
            await self.database.compact_observations()
        async with self.database.connect() as connection:
            cursor = await connection.execute(
                "SELECT COUNT(*) FROM observations")
            count = (await cursor.fetchone())[0]
            await cursor.close()
        self.assertEqual(1, count)

    async def test_confirmation_is_payload_bound_and_single_use(self):
        confirmation = await self.database.create_confirmation(
            action="identity_rotate", target="nas-primary",
            payload={"slot_id": "nas-primary"}, ttl_seconds=60)
        token = confirmation["confirmation_token"]
        self.assertFalse(await self.database.consume_confirmation(
            token, action="identity_rotate", target="nas-primary",
            payload={"slot_id": "dps-fallback"}))
        self.assertTrue(await self.database.consume_confirmation(
            token, action="identity_rotate", target="nas-primary",
            payload={"slot_id": "nas-primary"}))
        self.assertFalse(await self.database.consume_confirmation(
            token, action="identity_rotate", target="nas-primary",
            payload={"slot_id": "nas-primary"}))


class DeferredQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_deferred_task_is_polled_and_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Database(Path(tmp) / "queue.sqlite3")
            await database.initialize()
            calls = 0

            async def flaky(payload, task_id):
                nonlocal calls
                del payload, task_id
                calls += 1
                if calls == 1:
                    raise EgressUnavailableError(
                        "fixture", retry_after=utc_now())
                return {"recovered": True}

            queue = PersistentTaskQueue(
                database, {"flaky": flaky}, workers=1,
                poll_interval=0.02)
            await queue.start()
            try:
                submitted = await queue.submit("flaky", {}, "flaky")
                for _ in range(200):
                    task = await database.get_task(submitted["id"])
                    if task["status"] == "succeeded":
                        break
                    await asyncio.sleep(0.01)
                else:
                    self.fail("deferred task was not retried")
                self.assertEqual(2, task["attempts"])
                self.assertTrue(task["result"]["recovered"])
            finally:
                await queue.stop()


if __name__ == "__main__":
    unittest.main()
