"""批量下载编排器。

流程:
  get_book(book_id) → 获取完整书籍（info + divisions + chapters + content）
  download_book(book_id, output_dir) → 下载全本 → TXT 文件
"""

import time
import os
from pathlib import Path
from . import api as _api
from . import models


def get_book(session: _api.Session, book_id: str,
             on_chapter=None, book_info: dict = None) -> models.Book:
    """获取完整书籍对象（含所有章节内容）。

    Args:
        session: API 会话
        book_id: 书籍 ID
        on_chapter: 回调 (current, total)，用于进度显示

    Returns:
        Book 对象，所有章节的 content 已填充
    """
    # Step 1: 书籍信息
    info = dict(book_info or {})
    try:
        data = session.get_book_info(book_id)
        info.update(data.get("data", {}).get("book_info", {}))
    except _api.ApiError as exc:
        if exc.code != "320001" or not info:
            raise
    book = models.Book(
        book_id=book_id,
        book_name=info.get("book_name", "未命名"),
        author_name=info.get("author_name", "佚名"),
        cover_url=info.get("cover", ""),
        total_word_count=info.get("total_word_count", 0),
        category_name=info.get("category_name", ""),
        description=info.get("description", ""),
    )

    # Step 2: 分卷列表
    div_data = session.get_division_list(book_id)
    div_list = div_data.get("data", {}).get("division_list", [])

    total_chapters = 0
    completed = 0

    for div_info in div_list:
        division = models.Division(
            division_id=div_info.get("division_id", ""),
            division_name=div_info.get("division_name", ""),
        )

        # Step 3: 章节列表
        chap_data = session.get_chapter_list(division.division_id)
        chap_list = chap_data.get("data", {}).get("chapter_list", [])
        total_chapters += len(chap_list)

        for chap_info in chap_list:
            chapter = models.Chapter(
                chapter_id=chap_info.get("chapter_id", ""),
                chapter_index=int(chap_info.get("chapter_index", 0)),
                chapter_title=chap_info.get("chapter_title", ""),
                word_count=int(chap_info.get("word_count", 0)),
                is_vip=chap_info.get("is_vip") == "1",
                auth_access=chap_info.get("auth_access") == "1",
            )

            if not chapter.auth_access:
                chapter.content = "【未购买本章】"
            else:
                try:
                    # Step 4: 获取内容密钥
                    command = session.get_chapter_command(
                        chapter.chapter_id)
                    # Step 5: 获取并解密内容
                    chapter.content = session.get_chapter_content(
                        chapter.chapter_id, command)
                except Exception as e:
                    chapter.content = f"【下载失败: {e}】"

            division.chapters.append(chapter)
            completed += 1

            if on_chapter:
                on_chapter(completed, total_chapters)

            # 小延迟，避免被限流
            time.sleep(0.05)

        book.divisions.append(division)

    return book


def download_book(session: _api.Session, book_id: str,
                  output_dir: str = "output",
                  progress_callback=None, book_info: dict = None,
                  skip_existing: bool = False) -> str:
    """下载一本书并导出为 TXT。

    Args:
        session: API 会话
        book_id: 书籍 ID
        output_dir: 输出目录
        progress_callback: 回调 (completed, total)

    Returns:
        输出 TXT 文件路径
    """
    def _on_chapter(current, total):
        if progress_callback:
            progress_callback(current, total)

    if skip_existing and book_info:
        candidate = Path(output_dir) / f"{models.safe_book_name(book_info.get('book_name', book_id))}.txt"
        if candidate.exists():
            return str(candidate)

    book = get_book(
        session, book_id, on_chapter=_on_chapter, book_info=book_info)

    # 写入 TXT
    os.makedirs(output_dir, exist_ok=True)
    output_path = Path(output_dir) / f"{book.safe_name}.txt"

    with open(output_path, "w", encoding="utf-8") as f:
        for division in book.divisions:
            for chapter in division.chapters:
                f.write(chapter.chapter_title + "\n")
                f.write(chapter.content + "\n\n")

    return str(output_path)
