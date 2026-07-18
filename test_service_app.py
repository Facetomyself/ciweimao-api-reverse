"""FastAPI lifespan、路由、队列与 scheduler 测试。"""

import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from service.app import create_app
from service.config import Settings


class FakeService:
    def __init__(self, settings, database):
        self.settings = settings
        self.database = database

    @property
    def task_handlers(self):
        return {
            "download_by_name": self.download,
            "sync_rankings": self.rankings,
            "sync_new_books": self.new_books,
            "sync_all": self.all_sync,
        }

    async def search_books(self, keyword, max_pages=1, count=10):
        del max_pages, count
        return [{"book_id": "1", "book_name": keyword}]

    async def download(self, payload, task_id):
        return {"book_name": payload["book_name"], "task_id": task_id}

    async def rankings(self, payload, task_id):
        del payload
        return {"snapshot_count": 0, "task_id": task_id}

    async def new_books(self, payload, task_id):
        del payload
        return {"item_count": 0, "task_id": task_id}

    async def all_sync(self, payload, task_id):
        del payload
        return {
            "rankings": {"snapshot_count": 0, "item_count": 0},
            "new_books": {"item_count": 0},
            "task_id": task_id,
        }


class FastApiTests(unittest.TestCase):
    def test_http_queue_and_scheduler_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = Settings(
                database_path=root / "service.sqlite3",
                output_dir=root / "output",
                token_path=root / "missing-tokens.json",
                scheduler_enabled=True,
                sync_interval_minutes=30,
                queue_workers=1,
            )
            app = create_app(settings, service_factory=FakeService)
            with TestClient(app) as client:
                health = client.get("/health")
                self.assertEqual(200, health.status_code)
                self.assertEqual(
                    "wal", health.json()["database"]["journal_mode"])

                jobs = client.get("/api/scheduler/jobs")
                self.assertEqual(1, len(jobs.json()["jobs"]))
                self.assertEqual("sync-all", jobs.json()["jobs"][0]["id"])
                self.assertIn(
                    "0:30:00", jobs.json()["jobs"][0]["trigger"])

                search = client.get(
                    "/api/books/search", params={"q": "书名"})
                self.assertEqual("书名", search.json()["books"][0]["book_name"])

                response = client.post("/api/downloads/by-name", json={
                    "book_name": "书名",
                })
                self.assertEqual(202, response.status_code)
                task_id = response.json()["id"]
                for _ in range(100):
                    task = client.get(f"/api/tasks/{task_id}").json()
                    if task["status"] == "succeeded":
                        break
                    time.sleep(0.01)
                else:
                    self.fail("HTTP 创建的任务未完成")
                self.assertEqual("书名", task["result"]["book_name"])

                no_body = client.post("/api/sync/new-books")
                self.assertEqual(202, no_body.status_code)
                sync_task_id = no_body.json()["id"]
                for _ in range(100):
                    sync_task = client.get(
                        f"/api/tasks/{sync_task_id}").json()
                    if sync_task["status"] == "succeeded":
                        break
                    time.sleep(0.01)
                else:
                    self.fail("无 body 的同步任务未完成")

                merged = client.post("/api/sync/all")
                self.assertEqual(202, merged.status_code)
                merged_task_id = merged.json()["id"]
                for _ in range(100):
                    merged_task = client.get(
                        f"/api/tasks/{merged_task_id}").json()
                    if merged_task["status"] == "succeeded":
                        break
                    time.sleep(0.01)
                else:
                    self.fail("合并同步任务未完成")
                self.assertEqual(
                    0, merged_task["result"]["rankings"]["snapshot_count"])
                self.assertEqual(
                    0, merged_task["result"]["new_books"]["item_count"])

    def test_dynamic_proxy_bootstrap_is_deferred_until_first_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = Settings(
                database_path=root / "service.sqlite3",
                output_dir=root / "output",
                token_path=root / "missing-tokens.json",
                guest_bootstrap_enabled=True,
                scheduler_enabled=False,
                proxy_provider="kuaidaili_dps",
                kdl_secret_id="fixture-id",
                kdl_secret_key="fixture-key",
            )

            app = create_app(settings)
            with TestClient(app) as client:
                health = client.get("/health").json()

            self.assertEqual(
                "deferred-until-first-use",
                health["guest_bootstrap"]["source"],
            )
            self.assertFalse(health["proxy"]["acquired"])
            self.assertEqual(
                "kuaidaili_dps", health["proxy"]["provider"])
