"""FastAPI lifespan、路由、队列与 scheduler 测试。"""

import asyncio
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
                jobs_by_id = {
                    item["id"]: item for item in jobs.json()["jobs"]
                }
                self.assertEqual(
                    {"sync-all", "archive-maintenance"},
                    set(jobs_by_id),
                )
                self.assertIn(
                    "0:30:00", jobs_by_id["sync-all"]["trigger"])

                search = client.get(
                    "/api/books/search", params={"q": "书名"})
                self.assertEqual("书名", search.json()["books"][0]["book_name"])

                stats = client.get("/api/downloads/stats")
                self.assertEqual(200, stats.status_code)
                self.assertEqual(0, stats.json()["downloaded_books"])

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

    def test_control_plane_files_confirmations_and_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = Settings(
                database_path=root / "service.sqlite3",
                output_dir=root / "output",
                token_path=root / "tokens.json",
                archive_dir=root / "archive",
                scheduler_enabled=False,
                readiness_require_protocol_probe=False,
            )
            app = create_app(settings)
            with TestClient(app) as client:
                self.assertEqual(200, client.get("/health/live").status_code)
                ready = client.get("/health/ready")
                self.assertEqual(200, ready.status_code)
                self.assertTrue(ready.json()["ready"])

                paused = client.post(
                    "/api/controls/scheduler/pause",
                    json={"reason": "fixture"},
                )
                self.assertTrue(paused.json()["paused"])
                resumed = client.post(
                    "/api/controls/scheduler/resume", json={"reason": ""})
                self.assertFalse(resumed.json()["paused"])

                asyncio.run(app.state.database.upsert_books([{
                    "book_id": "fixture-book",
                    "book_name": "控制面测试书",
                    "author_name": "测试作者",
                }]))
                output = settings.output_dir / "fixture.txt"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("免费正文\n", encoding="utf-8")

                async def seed_download():
                    task, _ = await app.state.database.create_task(
                        "fixture", {}, "fixture-download")
                    await app.state.database.claim_task(task["id"])
                    item = await app.state.database.record_download(
                        task_id=task["id"],
                        query="fixture",
                        book={
                            "book_id": "fixture-book",
                            "book_name": "控制面测试书",
                        },
                        output_path=str(output),
                        file_size=output.stat().st_size,
                        sha256="fixture-sha",
                    )
                    await app.state.database.complete_task(
                        task["id"], {"fixture": True})
                    return item

                item = asyncio.run(seed_download())
                books = client.get("/api/books").json()
                self.assertEqual("fixture-book", books["items"][0]["book_id"])
                downloaded = client.get(
                    f"/api/downloads/{item['id']}/file")
                self.assertEqual(200, downloaded.status_code)
                self.assertIn("免费正文", downloaded.text)

                preview = client.post(
                    "/api/storage/maintenance/preview",
                    json={"compact": False},
                )
                self.assertEqual(200, preview.status_code)
                token = preview.json()["confirmation_token"]
                run = client.post(
                    "/api/storage/maintenance/run",
                    json={
                        "compact": False,
                        "confirmation_token": token,
                    },
                )
                self.assertEqual(202, run.status_code)
                repeated = client.post(
                    "/api/storage/maintenance/run",
                    json={
                        "compact": False,
                        "confirmation_token": token,
                    },
                )
                self.assertEqual(409, repeated.status_code)

                config_text = client.get("/api/config").text
                self.assertNotIn("login_token", config_text)
                self.assertNotIn("kdl_secret", config_text.lower())
                self.assertEqual(200, client.get("/api/overview").status_code)

    def test_protocol_probe_is_a_real_readiness_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = Settings(
                database_path=root / "service.sqlite3",
                output_dir=root / "output",
                token_path=root / "tokens.json",
                scheduler_enabled=False,
                readiness_require_protocol_probe=True,
                readiness_auto_probe_enabled=False,
            )
            app = create_app(settings)
            with TestClient(app) as client:
                self.assertEqual(200, client.get("/health/live").status_code)
                ready = client.get("/health/ready")
                self.assertEqual(503, ready.status_code)
                self.assertFalse(ready.json()["checks"]["protocol_probe"])
