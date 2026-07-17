"""SQLite 仓储与 durable queue 回归测试。"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from service.database import Database
from service.queue import PersistentTaskQueue


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = Database(
            Path(self.tempdir.name) / "service.sqlite3")
        await self.database.initialize()

    async def asyncTearDown(self):
        self.tempdir.cleanup()

    async def test_active_dedupe_and_restart_recovery(self):
        first, created = await self.database.create_task(
            "sync_new_books", {"max_pages": 1}, "new-books")
        second, second_created = await self.database.create_task(
            "sync_new_books", {"max_pages": 2}, "new-books")

        self.assertTrue(created)
        self.assertFalse(second_created)
        self.assertEqual(first["id"], second["id"])

        claimed = await self.database.claim_task(first["id"])
        self.assertEqual("running", claimed["status"])
        self.assertEqual(1, await self.database.reset_running_tasks())
        recovered = await self.database.get_task(first["id"])
        self.assertEqual("queued", recovered["status"])

    async def test_snapshot_round_trip(self):
        created = await self.database.create_snapshot(
            "ranking",
            "fans_value:week",
            [{
                "book_id": "1", "book_name": "第一本",
                "author_name": "作者", "is_paid": "0",
            }, {
                "book_id": "2", "book_name": "第二本",
                "author_name": "作者", "is_paid": "1",
            }],
            {"order": "fans_value", "time_type": "week"},
        )

        snapshot = await self.database.get_latest_snapshot(
            "ranking", "fans_value:week")

        self.assertEqual(created["id"], snapshot["id"])
        self.assertEqual(["1", "2"], [
            item["book_id"] for item in snapshot["items"]])
        self.assertEqual([1, 2], [
            item["position"] for item in snapshot["items"]])


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_queue_executes_and_persists_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Database(Path(tmp) / "queue.sqlite3")
            await database.initialize()

            async def handler(payload, task_id):
                return {"value": payload["value"], "task_id": task_id}

            queue = PersistentTaskQueue(
                database, {"echo": handler}, workers=1)
            await queue.start()
            try:
                submitted = await queue.submit(
                    "echo", {"value": 7}, dedupe_key="echo:7")
                for _ in range(100):
                    task = await database.get_task(submitted["id"])
                    if task["status"] == "succeeded":
                        break
                    await asyncio.sleep(0.01)
                else:
                    self.fail("任务未在预期时间内完成")

                self.assertEqual(7, task["result"]["value"])
                self.assertEqual(1, task["attempts"])
            finally:
                await queue.stop()
