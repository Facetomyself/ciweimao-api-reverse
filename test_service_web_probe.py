"""Web fallback protocol probe 的离线回归。"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from client.api import ApiError
from service.config import Settings
from service.core import CiweimaoService
from service.database import Database
from service.schemas import ProtocolProbeRequest


class ProbeSession:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.web_fallback_used = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def search_books(self, keyword, page=0, count=10):
        del keyword, page, count
        return {"data": {"book_list": [{"book_id": "fixture-book"}]}}

    async def get_book_catalog(self, book_id):
        del book_id
        return {"data": {"chapter_list": [{
            "chapter_list": [{
                "chapter_id": "fixture-chapter",
                "is_paid": "0",
                "auth_access": "1",
            }],
        }]}}

    async def get_chapter_command(self, chapter_id):
        del chapter_id
        return "fixture-command"

    async def _call(self, endpoint, extra_params=None):
        del extra_params
        if endpoint == "/chapter/get_cpt_ifm":
            raise ApiError("310017", "请升级到最新版本客户端")
        return {"code": "100000"}

    async def get_chapter_content(self, chapter_id, command, *,
                                  allow_web_fallback=False,
                                  allow_gt3_stamp=False):
        del chapter_id, command, allow_gt3_stamp
        if not allow_web_fallback:
            raise ApiError("310017", "请升级到最新版本客户端")
        self.web_fallback_used = True
        return "网页正文"


class DownloadSession(ProbeSession):
    supports_web_fallback = True

    async def search_books(self, keyword, page=0, count=10):
        del keyword, count
        return {"data": {"book_list": ([{
            "book_id": "fixture-book",
            "book_name": "测试书",
            "author_name": "测试作者",
        }] if page == 0 else [])}}

    async def get_book_info(self, book_id):
        return {"data": {"book_info": {
            "book_id": book_id,
            "book_name": "测试书",
            "author_name": "测试作者",
        }}}

    async def get_chapter_content(self, chapter_id, command, *,
                                  allow_web_fallback=False,
                                  allow_gt3_stamp=False):
        del chapter_id, command, allow_gt3_stamp
        if not allow_web_fallback:
            raise AssertionError("free-only download must opt into Web")
        self.web_fallback_used = True
        return "网页正文"


class ServiceWebProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_app_gate_can_be_split_from_web_route(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            token_path = root / "tokens.json"
            token_path.write_text(
                json.dumps({
                    "login_token": "fixture-token",
                    "account": "fixture-account",
                    "device_token": "ciweimao_fixture",
                }),
                encoding="utf-8",
            )
            settings = Settings(
                database_path=root / "service.sqlite3",
                output_dir=root / "output",
                token_path=token_path,
                scheduler_enabled=False,
                proxy_provider="direct",
                web_fallback_enabled=True,
            )
            database = Database(settings.database_path)
            await database.initialize()
            service = CiweimaoService(
                settings, database, session_factory=ProbeSession)

            result = await service.probe_protocol(
                ProtocolProbeRequest(keyword="测试"))

            self.assertTrue(result["ok"])
            self.assertFalse(result["app_protocol_ok"])
            self.assertTrue(result["web_fallback_ok"])
            self.assertEqual("web_fallback", result["route"])
            self.assertEqual(
                [
                    "search/books",
                    "chapter/catalog",
                    "chapter/get_chapter_cmd",
                    "chapter/get_cpt_ifm",
                    "web/chapter",
                ],
                [item["endpoint"] for item in result["checks"]],
            )
            probes = await database.latest_protocol_probes()
            by_endpoint = {item["endpoint"]: item for item in probes}
            self.assertFalse(by_endpoint["chapter/get_cpt_ifm"]["ok"])
            self.assertEqual("310017", by_endpoint["chapter/get_cpt_ifm"]["code"])
            self.assertTrue(by_endpoint["web/chapter"]["ok"])

    async def test_download_result_identifies_web_fallback_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            token_path = root / "tokens.json"
            token_path.write_text(
                json.dumps({
                    "login_token": "fixture-token",
                    "account": "fixture-account",
                    "device_token": "ciweimao_fixture",
                }),
                encoding="utf-8",
            )
            settings = Settings(
                database_path=root / "service.sqlite3",
                output_dir=root / "output",
                token_path=token_path,
                scheduler_enabled=False,
                proxy_provider="direct",
                chapter_delay=0,
            )
            database = Database(settings.database_path)
            await database.initialize()
            service = CiweimaoService(
                settings, database, session_factory=DownloadSession)
            task, _ = await database.create_task(
                "download_by_name", {"book_name": "测试书"}, "download:web")
            await database.claim_task(task["id"])

            result = await service.handle_download_by_name(
                {"book_name": "测试书"}, task["id"])

            self.assertEqual("web_fallback", result["content_source"])
            text = await asyncio.to_thread(
                Path(result["output_path"]).read_text, encoding="utf-8")
            self.assertIn("网页正文", text)


if __name__ == "__main__":
    unittest.main()
