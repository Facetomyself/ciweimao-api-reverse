"""不访问网络的核心回归测试。"""

import base64
import gzip
import hashlib
import json
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import Mock

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from client.api import ApiError, Session
from client import config, content, crypto, downloader, protocol


CURRENT_RESPONSE_SAMPLE = (
    "5DGa7wDsQ75CERueOQ4+MtGOVnZ2Uoqo0kMXkIhKYp/vRiyaM+fiOl/t3nmvNbLb"
    "Ix+4jUHa+wuj8MP1+FB9r2FQbhmn5KWsixOvawoERPeLm3+oTLRpMGbt8xnelTA3"
)


class PaginationTests(unittest.TestCase):
    def test_shelf_duplicate_page_stops_and_deduplicates(self):
        session = object.__new__(Session)
        session.get_shelf_list = Mock(return_value=[
            {"shelf_id": "1", "shelf_name": "默认"}
        ])
        page = [{"book_info": {"book_id": str(i), "book_name": str(i)}}
                for i in range(50)]
        session.get_shelf_books = Mock(side_effect=[page, page])

        books = session.get_all_shelf_books()

        self.assertEqual(50, len(books))
        self.assertEqual(2, session.get_shelf_books.call_count)

    def test_search_pages_are_zero_based_and_deduplicated(self):
        session = object.__new__(Session)
        session.search_books = Mock(side_effect=[
            {"data": {"book_list": [
                {"book_id": "1"}, {"book_id": "2"}
            ]}},
            {"data": {"book_list": [
                {"book_id": "2"}, {"book_id": "3"}
            ]}},
            {"data": {"book_list": []}},
        ])

        books = list(session.iter_search_books("测试"))

        self.assertEqual(["1", "2", "3"],
                         [item["book_id"] for item in books])
        self.assertEqual([0, 1, 2], [
            call.kwargs["page"] for call in session.search_books.call_args_list
        ])

    def test_all_site_pages_stop_on_repeated_signature(self):
        session = object.__new__(Session)
        page = [{"book_id": "1"}, {"book_id": "2"}]
        session.get_bookcity_books = Mock(side_effect=[page, page])

        books = list(session.iter_all_books())

        self.assertEqual(["1", "2"],
                         [item["book_id"] for item in books])
        self.assertEqual(2, session.get_bookcity_books.call_count)

    def test_pages_stop_when_page_contains_no_new_ids(self):
        session = object.__new__(Session)
        session.get_bookcity_books = Mock(side_effect=[
            [{"book_id": "1"}, {"book_id": "2"}],
            [{"book_id": "2"}, {"book_id": "1"}],
        ])

        books = list(session.iter_all_books())

        self.assertEqual(["1", "2"],
                         [item["book_id"] for item in books])
        self.assertEqual(2, session.get_bookcity_books.call_count)


class ProtocolTests(unittest.TestCase):
    def test_current_signature_matches_runtime_sample_shape(self):
        signed = protocol.sign_request(
            "书客1234567", "2.9.362", "10072263a65a4345")

        self.assertEqual("10072263a65a4345", signed["rand_str"])
        self.assertEqual(
            "RTemA7/IKa4GppnByNkaz0tVeAk1Cn8LnSM5NZ993Qc=",
            signed["p"],
        )
        self.assertEqual(
            "account=%E4%B9%A6%E5%AE%A21234567&app_version=2.9.362"
            "&rand_str=10072263a65a4345"
            "&signatures=a90f3731745f1c30ee77cb13fc00005aCkMxWNB666",
            protocol.build_signature_source(
                "书客1234567", "2.9.362", "10072263a65a4345"),
        )

    def test_current_response_sample_decrypts(self):
        plaintext = crypto.decrypt_response_for_version(
            CURRENT_RESPONSE_SAMPLE, "2.9.362")
        data = json.loads(plaintext)

        self.assertEqual("100000", data["code"])
        self.assertEqual(
            "7dc685cb3c7116e05b99081d52cc42b1",
            data["data"]["command"],
        )

    def test_legacy_response_key_remains_supported(self):
        raw = b'{"code":"100000","data":{}}'
        key = hashlib.sha256(config.LEGACY_API_KEY.encode()).digest()
        encrypted = AES.new(
            key, AES.MODE_CBC, bytes(16)).encrypt(pad(raw, 16))

        plaintext = crypto.decrypt_response_for_version(
            base64.b64encode(encrypted).decode(), "2.9.312")

        self.assertEqual(raw, plaintext)

    def test_current_session_signs_and_decrypts(self):
        session = Session(
            login_token="token",
            account="书客1234567",
            device_token="ciweimao_",
            app_version="2.9.362",
            rand_factory=lambda: "10072263a65a4345",
        )
        response = Mock(status_code=200, text=CURRENT_RESPONSE_SAMPLE)
        session._session = Mock()
        session._session.post.return_value = response

        command = session.get_chapter_command("113769038")

        self.assertEqual("7dc685cb3c7116e05b99081d52cc42b1", command)
        call = session._session.post.call_args
        self.assertEqual(
            "https://app1.happybooker.cn/chapter/get_chapter_cmd",
            call.args[0],
        )
        self.assertEqual("10072263a65a4345",
                         call.kwargs["data"]["rand_str"])
        self.assertEqual(
            "RTemA7/IKa4GppnByNkaz0tVeAk1Cn8LnSM5NZ993Qc=",
            call.kwargs["data"]["p"],
        )


class ContentTests(unittest.TestCase):
    def test_decode_cdn_payload_zlib_html(self):
        payload = zlib.compress(
            "<p>　第一段</p><p>第二段<br>换行</p>".encode("utf-8"))

        text = content.decode_cdn_payload(payload)

        self.assertEqual("第一段\n第二段\n换行", text.replace("　", ""))

    def test_decode_cdn_payload_gzip_then_zlib(self):
        payload = gzip.compress(zlib.compress("<p>正文</p>".encode("utf-8")))

        self.assertEqual("正文", content.decode_cdn_payload(payload))

    def test_session_downloads_cdn_content(self):
        session = object.__new__(Session)
        session._call = Mock(return_value={
            "data": {"chapter_info": {
                "txt_content": "http://cdn.example/chapter.txt"
            }}
        })
        response = Mock()
        response.content = zlib.compress("<p>正文</p>".encode("utf-8"))
        session._session = Mock()
        session._session.get.return_value = response

        text = session.get_chapter_content("c1", "command")

        self.assertEqual("正文", text)
        response.raise_for_status.assert_called_once_with()


class DownloaderTests(unittest.TestCase):
    def _session(self):
        session = Mock()
        session.get_book_info.side_effect = ApiError("320001", "已下架")
        session.get_book_catalog.return_value = {
            "data": {"chapter_list": [{
                "division_id": "d1",
                "division_name": "正文",
                "chapter_list": [{
                    "chapter_id": "c1",
                    "chapter_index": "1",
                    "chapter_title": "第一章",
                    "word_count": "2",
                    "is_paid": "1",
                    "auth_access": "1",
                }],
            }]}
        }
        session.get_chapter_command.return_value = "command"
        session.get_chapter_content.return_value = "正文"
        return session

    def test_delisted_book_uses_shelf_metadata(self):
        book = downloader.get_book(
            self._session(), "100", book_info={
                "book_id": "100", "book_name": "下架书", "author_name": "作者"
            }, chapter_delay=0)
        self.assertEqual("下架书", book.book_name)
        self.assertEqual("正文", book.divisions[0].chapters[0].content)

    def test_unauthorized_chapter_is_marked_without_content_request(self):
        session = self._session()
        chapter = session.get_book_catalog.return_value[
            "data"]["chapter_list"][0]["chapter_list"][0]
        chapter["auth_access"] = "0"
        book = downloader.get_book(
            session, "100", book_info={"book_name": "未购买测试"},
            chapter_delay=0)
        self.assertEqual("【未购买本章】",
                         book.divisions[0].chapters[0].content)
        session.get_chapter_command.assert_not_called()
        session.get_chapter_content.assert_not_called()

    def test_free_only_skips_paid_chapters(self):
        session = self._session()
        chapters = session.get_book_catalog.return_value[
            "data"]["chapter_list"][0]["chapter_list"]
        chapters.append({
            "chapter_id": "c2", "chapter_index": "2",
            "chapter_title": "免费章", "word_count": "2",
            "is_paid": "0", "auth_access": "1",
        })

        book = downloader.get_book(
            session, "100", book_info={"book_name": "免费测试"},
            free_only=True, chapter_delay=0)

        self.assertEqual(["c2"], [
            chapter.chapter_id
            for division in book.divisions
            for chapter in division.chapters
        ])
        session.get_chapter_command.assert_called_once_with("c2")

    def test_free_only_skips_free_but_unauthorized_chapter(self):
        session = self._session()
        chapter = session.get_book_catalog.return_value[
            "data"]["chapter_list"][0]["chapter_list"][0]
        chapter.update({"is_paid": "0", "auth_access": "0"})

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(downloader.NoDownloadableChapters):
                downloader.download_book(
                    session,
                    "100",
                    output_dir=tmp,
                    book_info={"book_name": "不可访问免费章"},
                    free_only=True,
                    chapter_delay=0,
                )

        session.get_chapter_command.assert_not_called()

    def test_skip_existing_does_not_call_api(self):
        session = Mock()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "已有书.txt"
            target.write_text("existing", encoding="utf-8")
            result = downloader.download_book(
                session, "100", output_dir=tmp,
                book_info={"book_name": "已有书"}, skip_existing=True)
        self.assertEqual(str(target), result)
        session.get_book_info.assert_not_called()

    def test_no_free_chapters_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(downloader.NoDownloadableChapters):
                downloader.download_book(
                    self._session(), "100", output_dir=tmp,
                    book_info={"book_name": "全付费"},
                    free_only=True, chapter_delay=0)


if __name__ == "__main__":
    unittest.main()
