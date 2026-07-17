"""业务 handler、队列、文件与快照的离线端到端测试。"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from client.api import ApiError
from service.config import Credentials, Settings
from service.core import CiweimaoService
from service.database import Database
from service.queue import PersistentTaskQueue
from service.schemas import (
    DownloadByNameRequest,
    RankingSpec,
    SyncNewBooksRequest,
    SyncRankingsRequest,
)


class FakeAppSession:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.__class__.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def search_books(self, keyword, page=0, count=10):
        del keyword, count
        books = ([{
            "book_id": "100",
            "book_name": "离线测试书",
            "author_name": "测试作者",
            "is_paid": "1",
        }] if page == 0 else [])
        return {"data": {"book_list": books}}

    async def get_book_info(self, book_id):
        return {"data": {"book_info": {
            "book_id": book_id,
            "book_name": "离线测试书",
            "author_name": "测试作者",
        }}}

    async def get_book_catalog(self, book_id):
        del book_id
        return {"data": {"chapter_list": [{
            "division_id": "d1",
            "division_name": "正文",
            "chapter_list": [{
                "chapter_id": "c1", "chapter_index": "1",
                "chapter_title": "免费章", "word_count": "2",
                "is_paid": "0", "auth_access": "1",
            }, {
                "chapter_id": "c2", "chapter_index": "2",
                "chapter_title": "付费章", "word_count": "2",
                "is_paid": "1", "auth_access": "1",
            }],
        }]}}

    async def get_chapter_command(self, chapter_id):
        return f"command-{chapter_id}"

    async def get_chapter_content(self, chapter_id, command):
        del command
        return f"正文-{chapter_id}"

    async def get_rank_books(self, order, time_type, page=0, count=10,
                             category_index=0):
        del page, count, category_index
        return [{
            "book_id": f"rank-{order}-{time_type}",
            "book_name": f"榜单-{order}-{time_type}",
            "author_name": "榜单作者",
        }]

    async def get_bookcity_books(self, page=0, count=100,
                                 order="newtime"):
        del count, order
        return ([{
            "book_id": "new-1",
            "book_name": "新书一号",
            "author_name": "新书作者",
        }] if page == 0 else [])


class RefreshingSession(FakeAppSession):
    async def search_books(self, keyword, page=0, count=10):
        if self.kwargs["login_token"] == "fixture-token":
            raise ApiError("320002", "网络出错，请重试或重新登录")
        return await super().search_books(
            keyword, page=page, count=count)


class FakeCredentialBootstrap:
    def __init__(self, settings):
        self.settings = settings
        self.calls = 0

    async def refresh(self, failed_credentials):
        self.calls += 1
        self.settings.save_credentials(Credentials(
            login_token="fresh-token",
            account="fresh-account",
            device_token=failed_credentials.device_token,
        ))


class ServiceCoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        token_path = root / "tokens.json"
        token_path.write_text(json.dumps({
            "login_token": "fixture-token",
            "account": "fixture-account",
            "device_token": "ciweimao_fixture",
        }), encoding="utf-8")
        self.settings = Settings(
            database_path=root / "data.sqlite3",
            output_dir=root / "output",
            token_path=token_path,
            scheduler_enabled=False,
            queue_workers=2,
            chapter_delay=0,
            http_proxy_url="socks5://egress:1080",
        )
        self.database = Database(self.settings.database_path)
        await self.database.initialize()
        self.service = CiweimaoService(
            self.settings,
            self.database,
            session_factory=FakeAppSession,
        )
        self.queue = PersistentTaskQueue(
            self.database, self.service.task_handlers, workers=2)
        await self.queue.start()

    async def asyncTearDown(self):
        await self.queue.stop()
        self.tempdir.cleanup()

    async def _wait(self, task_id: str) -> dict:
        for _ in range(200):
            task = await self.database.get_task(task_id)
            if task["status"] in {"succeeded", "failed"}:
                return task
            await asyncio.sleep(0.01)
        self.fail(f"任务超时: {task_id}")

    async def test_download_rankings_and_new_books_flow(self):
        FakeAppSession.instances.clear()
        download = await self.queue.submit(
            "download_by_name",
            DownloadByNameRequest(
                book_name="离线测试书",
                author_name="测试作者",
            ).model_dump(mode="json"),
            "download:offline",
        )
        rankings = await self.queue.submit(
            "sync_rankings",
            SyncRankingsRequest(
                specs=[RankingSpec(
                    order="fans_value", time_type="week")]
            ).model_dump(mode="json"),
            "rankings:offline",
        )
        new_books = await self.queue.submit(
            "sync_new_books",
            SyncNewBooksRequest().model_dump(mode="json"),
            "new-books:offline",
        )

        download_task, ranking_task, new_task = await asyncio.gather(
            self._wait(download["id"]),
            self._wait(rankings["id"]),
            self._wait(new_books["id"]),
        )

        self.assertEqual("succeeded", download_task["status"])
        self.assertEqual("succeeded", ranking_task["status"])
        self.assertEqual("succeeded", new_task["status"])
        target = Path(download_task["result"]["output_path"])
        text = target.read_text(encoding="utf-8")
        self.assertIn("免费章\n正文-c1", text)
        self.assertNotIn("付费章", text)

        ranking_snapshot = await self.database.get_latest_snapshot(
            "ranking", "fans_value:week")
        new_snapshot = await self.database.get_latest_snapshot(
            "new_books", "newtime")
        self.assertEqual(1, ranking_snapshot["item_count"])
        self.assertEqual("new-1", new_snapshot["items"][0]["book_id"])
        self.assertTrue(FakeAppSession.instances)
        self.assertTrue(all(
            session.kwargs["proxy"] == "socks5://egress:1080"
            for session in FakeAppSession.instances
        ))

    async def test_invalid_guest_is_refreshed_and_request_retried(self):
        bootstrap = FakeCredentialBootstrap(self.settings)
        service = CiweimaoService(
            self.settings,
            self.database,
            session_factory=RefreshingSession,
            credential_bootstrap=bootstrap,
        )

        books = await service.search_books(
            "离线测试书", max_pages=1, count=10)

        self.assertEqual(1, bootstrap.calls)
        self.assertEqual("100", books[0]["book_id"])
        self.assertEqual(
            "fresh-token",
            self.settings.load_credentials().login_token,
        )
