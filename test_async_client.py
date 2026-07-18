"""异步客户端与下载器的不联网回归测试。"""

import tempfile
import unittest
import zlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError

from client import async_downloader
from client.api import ApiError, AsyncSession
from client.downloader import NoDownloadableChapters


class AsyncSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_session_downloads_cdn_content(self):
        session = object.__new__(AsyncSession)
        session._call = AsyncMock(return_value={
            "data": {"chapter_info": {
                "txt_content": "https://cdn.example/chapter.txt"
            }}
        })
        response = Mock()
        response.content = zlib.compress("<p>正文</p>".encode("utf-8"))
        session._session = Mock()
        session._session.get = AsyncMock(return_value=response)

        text = await session.get_chapter_content("c1", "command")

        self.assertEqual("正文", text)
        response.raise_for_status.assert_called_once_with()
        self.assertEqual(
            30, session._session.get.call_args.kwargs["timeout"])

    async def test_async_search_pages_are_deduplicated(self):
        session = object.__new__(AsyncSession)
        session.search_books = AsyncMock(side_effect=[
            {"data": {"book_list": [
                {"book_id": "1"}, {"book_id": "2"}
            ]}},
            {"data": {"book_list": [
                {"book_id": "2"}, {"book_id": "3"}
            ]}},
            {"data": {"book_list": []}},
        ])

        books = [book async for book in session.iter_search_books("测试")]

        self.assertEqual(["1", "2", "3"], [
            book["book_id"] for book in books])
        self.assertEqual([0, 1, 2], [
            call.kwargs["page"]
            for call in session.search_books.call_args_list
        ])

    async def test_async_session_retries_transient_connection_error(self):
        session = object.__new__(AsyncSession)
        session._init_protocol(
            "fixture-token", "fixture-account", "ciweimao_fixture", "2.9.362",
            None, lambda: "10072263a65a4345", 30)
        session.max_retries = 1
        session._retry_backoff = 0
        response = Mock(status_code=200, text=(
            "5DGa7wDsQ75CERueOQ4+MtGOVnZ2Uoqo0kMXkIhKYp/vRiyaM+fiOl/t3nmvNbLb"
            "Ix+4jUHa+wuj8MP1+FB9r2FQbhmn5KWsixOvawoERPeLm3+oTLRpMGbt8xnelTA3"
        ))
        session._session = Mock()
        session._session.post = AsyncMock(side_effect=[
            CurlConnectionError("connection reset", 56), response,
        ])

        command = await session.get_chapter_command("113769038")

        self.assertEqual("7dc685cb3c7116e05b99081d52cc42b1", command)
        self.assertEqual(2, session._session.post.await_count)

    async def test_async_session_retries_app_transient_code(self):
        session = object.__new__(AsyncSession)
        session._init_protocol(
            "fixture-token", "fixture-account", "ciweimao_fixture", "2.9.362",
            None, lambda: "10072263a65a4345", 30)
        session.max_retries = 0
        session.transient_api_retries = 1
        session._retry_backoff = 0
        transient = Mock(
            status_code=200,
            text=json.dumps({"code": "320002", "tip": "网络出错"}),
        )
        success = Mock(status_code=200, text=(
            "5DGa7wDsQ75CERueOQ4+MtGOVnZ2Uoqo0kMXkIhKYp/vRiyaM+fiOl/t3nmvNbLb"
            "Ix+4jUHa+wuj8MP1+FB9r2FQbhmn5KWsixOvawoERPeLm3+oTLRpMGbt8xnelTA3"
        ))
        session._session = Mock()
        session._session.post = AsyncMock(side_effect=[transient, success])

        command = await session.get_chapter_command("113769038")

        self.assertEqual("7dc685cb3c7116e05b99081d52cc42b1", command)
        self.assertEqual(2, session._session.post.await_count)


class AsyncDownloaderTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _session():
        session = Mock()
        session.get_book_info = AsyncMock(return_value={
            "data": {"book_info": {
                "book_id": "100", "book_name": "异步测试",
                "author_name": "作者",
            }}
        })
        session.get_book_catalog = AsyncMock(return_value={
            "data": {"chapter_list": [{
                "division_id": "d1",
                "division_name": "正文",
                "chapter_list": [{
                    "chapter_id": "c1", "chapter_index": "1",
                    "chapter_title": "第一章", "word_count": "2",
                    "is_paid": "0", "auth_access": "1",
                }, {
                    "chapter_id": "c2", "chapter_index": "2",
                    "chapter_title": "第二章", "word_count": "2",
                    "is_paid": "1", "auth_access": "1",
                }],
            }]}
        })
        session.get_chapter_command = AsyncMock(return_value="command")
        session.get_chapter_content = AsyncMock(return_value="正文")
        return session

    async def test_free_download_is_atomic_and_filters_paid_chapters(self):
        session = self._session()
        with tempfile.TemporaryDirectory() as tmp:
            result = await async_downloader.download_book(
                session,
                "100",
                output_dir=tmp,
                free_only=True,
                include_book_id=True,
                chapter_delay=0,
            )
            target = Path(result)
            text = target.read_text(encoding="utf-8")

            self.assertEqual("100 - 异步测试.txt", target.name)
            self.assertIn("第一章\n正文", text)
            self.assertNotIn("第二章", text)
            self.assertFalse(target.with_suffix(".txt.part").exists())
        session.get_chapter_command.assert_awaited_once_with("c1")

    async def test_no_free_chapters_raises(self):
        session = self._session()
        chapters = session.get_book_catalog.return_value[
            "data"]["chapter_list"][0]["chapter_list"]
        chapters[0]["is_paid"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(NoDownloadableChapters):
                await async_downloader.download_book(
                    session,
                    "100",
                    output_dir=tmp,
                    free_only=True,
                    chapter_delay=0,
                )

    async def test_proxy_failure_is_not_written_into_txt(self):
        session = self._session()
        session.get_chapter_command.side_effect = ApiError(
            "320002", "代理失效")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ApiError):
                await async_downloader.download_book(
                    session,
                    "100",
                    output_dir=tmp,
                    free_only=True,
                    chapter_delay=0,
                )
            self.assertFalse(list(Path(tmp).glob("*.txt")))
