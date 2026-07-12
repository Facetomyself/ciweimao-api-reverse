"""不访问网络的核心回归测试。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from client.api import ApiError, Session
from client import downloader


class ShelfPaginationTests(unittest.TestCase):
    def test_duplicate_page_stops_and_deduplicates(self):
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


class DownloaderTests(unittest.TestCase):
    def _session(self):
        session = Mock()
        session.get_book_info.side_effect = ApiError("320001", "已下架")
        session.get_division_list.return_value = {
            "data": {"division_list": [{
                "division_id": "d1", "division_name": "正文"
            }]}
        }
        session.get_chapter_list.return_value = {
            "data": {"chapter_list": [{
                "chapter_id": "c1", "chapter_index": "1",
                "chapter_title": "第一章", "word_count": "2",
                "is_vip": "1", "auth_access": "1"
            }]}
        }
        session.get_chapter_command.return_value = "command"
        session.get_chapter_content.return_value = "正文"
        return session

    def test_delisted_book_uses_shelf_metadata(self):
        book = downloader.get_book(
            self._session(), "100", book_info={
                "book_id": "100", "book_name": "下架书", "author_name": "作者"
            })
        self.assertEqual("下架书", book.book_name)
        self.assertEqual("正文", book.divisions[0].chapters[0].content)

    def test_unauthorized_chapter_is_marked_without_content_request(self):
        session = self._session()
        chapter = session.get_chapter_list.return_value["data"]["chapter_list"][0]
        chapter["auth_access"] = "0"
        book = downloader.get_book(
            session, "100", book_info={"book_name": "未购买测试"})
        self.assertEqual("【未购买本章】", book.divisions[0].chapters[0].content)
        session.get_chapter_command.assert_not_called()
        session.get_chapter_content.assert_not_called()

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


if __name__ == "__main__":
    unittest.main()
