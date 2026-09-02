"""App 310017 到公开 Web 章节链的最小集成回归。"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from client import async_downloader, downloader
from client.api import ApiError, AsyncSession, Session
from client.web import WebChapterError
from service.failures import FailureCategory, classify_failure


class WebFallbackIntegrationTests(unittest.TestCase):
    def test_sync_fallback_only_on_explicit_free_scope(self):
        session = object.__new__(Session)
        session.web_fallback_enabled = True
        session.web_fallback_used = False
        session._call = Mock(side_effect=ApiError(
            "310017", "请升级到最新版本客户端"))
        web = Mock()
        web.get_chapter_content.return_value = "网页正文"
        session._web_session = web

        self.assertEqual(
            "网页正文",
            session.get_chapter_content(
                "123", "command", allow_web_fallback=True),
        )
        self.assertTrue(session.web_fallback_used)
        web.get_chapter_content.assert_called_once_with("123")

    def test_sync_does_not_fallback_without_opt_in_or_when_disabled(self):
        for enabled, allow in ((True, False), (False, True)):
            session = object.__new__(Session)
            session.web_fallback_enabled = enabled
            session.web_fallback_used = False
            session._call = Mock(side_effect=ApiError("310017", "blocked"))
            session._web_session = Mock()
            with self.assertRaises(ApiError):
                session.get_chapter_content(
                    "123", "command", allow_web_fallback=allow)
            session._web_session.get_chapter_content.assert_not_called()


class AsyncWebFallbackIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_fallback_uses_web_client(self):
        session = object.__new__(AsyncSession)
        session.web_fallback_enabled = True
        session.web_fallback_used = False
        session._call = AsyncMock(side_effect=ApiError("310017", "blocked"))
        web = Mock()
        web.get_chapter_content = AsyncMock(return_value="网页正文")
        session._web_session = web

        result = await session.get_chapter_content(
            "123", "command", allow_web_fallback=True)

        self.assertEqual("网页正文", result)
        self.assertTrue(session.web_fallback_used)
        web.get_chapter_content.assert_awaited_once_with("123")

    async def test_async_lazy_web_session_is_created_once_under_concurrency(self):
        session = object.__new__(AsyncSession)
        session.web_fallback_enabled = True
        session.web_fallback_used = False
        session.proxy = None
        session.impersonate = None
        session.web_min_interval = 0
        session.web_base_url = None
        session._web_session = None
        session._web_session_factory = None
        session._call = AsyncMock(side_effect=ApiError("310017", "blocked"))
        web = Mock()
        web.get_chapter_content = AsyncMock(return_value="网页正文")
        created = []

        def build_web(**kwargs):
            created.append(kwargs)
            return web

        with patch("client.api.AsyncWebChapterSession", side_effect=build_web):
            results = await asyncio.gather(
                session.get_chapter_content("1", "cmd", allow_web_fallback=True),
                session.get_chapter_content("2", "cmd", allow_web_fallback=True),
            )

        self.assertEqual(["网页正文", "网页正文"], results)
        self.assertEqual(1, len(created))
        self.assertEqual(2, web.get_chapter_content.await_count)

    async def test_async_downloader_passes_web_scope_only_for_free_downloads(self):
        class FallbackSession:
            supports_web_fallback = True

            async def get_book_info(self, book_id):
                return {"data": {"book_info": {
                    "book_id": book_id,
                    "book_name": "测试书",
                }}}

            async def get_book_catalog(self, book_id):
                del book_id
                return {"data": {"chapter_list": [{
                    "division_id": "d1",
                    "chapter_list": [{
                        "chapter_id": "c1",
                        "chapter_index": "1",
                        "chapter_title": "免费章",
                        "is_paid": "0",
                        "auth_access": "1",
                    }],
                }]}}

            async def get_chapter_command(self, chapter_id):
                del chapter_id
                return "cmd"

            async def get_chapter_content(self, chapter_id, command, *,
                                          allow_web_fallback=False):
                del chapter_id, command
                self.allow_web_fallback = allow_web_fallback
                return "网页正文"

        session = FallbackSession()
        with tempfile.TemporaryDirectory() as temp:
            await async_downloader.download_book(
                session,
                "book-1",
                output_dir=temp,
                free_only=True,
                chapter_delay=0,
                chapter_concurrency=1,
            )
        self.assertTrue(session.allow_web_fallback)

    async def test_real_async_session_downloads_after_app_310017(self):
        session = AsyncSession(
            login_token="fixture-token",
            account="fixture-account",
            web_fallback_enabled=True,
            web_min_interval=0,
            max_retries=0,
        )

        async def app_call(endpoint, extra_params=None):
            del extra_params
            if endpoint == "/book/get_info_by_id":
                return {"data": {"book_info": {
                    "book_id": "book-1", "book_name": "测试书",
                }}}
            if endpoint == "/chapter/get_updated_chapter_by_division_new":
                return {"data": {"chapter_list": [{
                    "division_id": "d1",
                    "chapter_list": [{
                        "chapter_id": "c1", "chapter_index": "1",
                        "chapter_title": "免费章", "is_paid": "0",
                        "auth_access": "1",
                    }],
                }]}}
            if endpoint == "/chapter/get_chapter_cmd":
                return {"data": {"command": "cmd"}}
            if endpoint == "/chapter/get_cpt_ifm":
                raise ApiError("310017", "请升级到最新版本客户端")
            raise AssertionError(endpoint)

        session._call = app_call
        web = Mock()
        web.get_chapter_content = AsyncMock(return_value="网页正文")
        session._web_session = web
        try:
            with tempfile.TemporaryDirectory() as temp:
                output = await async_downloader.download_book(
                    session,
                    "book-1",
                    output_dir=temp,
                    free_only=True,
                    chapter_delay=0,
                    chapter_concurrency=1,
                )
                text = await asyncio.to_thread(
                    Path(output).read_text, encoding="utf-8")
                self.assertIn("网页正文", text)
            web.get_chapter_content.assert_awaited_once_with("c1")
            self.assertTrue(session.web_fallback_used)
        finally:
            await session.close()


class SyncDownloaderWebScopeTests(unittest.TestCase):
    def test_sync_downloader_passes_web_scope_only_for_free_downloads(self):
        class FallbackSession:
            supports_web_fallback = True

            def get_book_info(self, book_id):
                return {"data": {"book_info": {
                    "book_id": book_id, "book_name": "测试书",
                }}}

            def get_book_catalog(self, book_id):
                del book_id
                return {"data": {"chapter_list": [{
                    "division_id": "d1",
                    "chapter_list": [{
                        "chapter_id": "c1", "chapter_index": "1",
                        "chapter_title": "免费章", "is_paid": "0",
                        "auth_access": "1",
                    }],
                }]}}

            def get_chapter_command(self, chapter_id):
                del chapter_id
                return "cmd"

            def get_chapter_content(self, chapter_id, command, *,
                                   allow_web_fallback=False):
                del chapter_id, command
                self.allow_web_fallback = allow_web_fallback
                return "网页正文"

        session = FallbackSession()
        with tempfile.TemporaryDirectory() as temp:
            downloader.download_book(
                session,
                "book-1",
                output_dir=temp,
                free_only=True,
                chapter_delay=0,
            )
        self.assertTrue(session.allow_web_fallback)

    def test_web_error_is_not_written_as_success_text(self):
        class BrokenSession:
            supports_web_fallback = True

            def get_book_info(self, book_id):
                return {"data": {"book_info": {
                    "book_id": book_id, "book_name": "测试书",
                }}}

            def get_book_catalog(self, book_id):
                del book_id
                return {"data": {"chapter_list": [{
                    "division_id": "d1",
                    "chapter_list": [{
                        "chapter_id": "c1", "chapter_index": "1",
                        "chapter_title": "免费章", "is_paid": "0",
                        "auth_access": "1",
                    }],
                }]}}

            def get_chapter_command(self, chapter_id):
                del chapter_id
                return "cmd"

            def get_chapter_content(self, chapter_id, command, *,
                                   allow_web_fallback=False):
                del chapter_id, command, allow_web_fallback
                raise WebChapterError(
                    "网页被限流", stage="session", code="403",
                    status_code=403)

        with tempfile.TemporaryDirectory() as temp, self.assertRaises(
                WebChapterError):
            downloader.download_book(
                BrokenSession(), "book-1", output_dir=temp,
                free_only=True, chapter_delay=0)

    def test_web_risk_errors_use_egress_recovery_classification(self):
        info = classify_failure(WebChapterError(
            "网页被限流", stage="session", code="403", status_code=403))
        self.assertEqual(FailureCategory.RISK_REJECTED, info.category)
        self.assertTrue(info.retry_same_egress)
        self.assertTrue(info.switch_egress)


if __name__ == "__main__":
    unittest.main()
