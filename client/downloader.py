"""批量下载编排器。

流程:
  get_book(book_id) → 获取完整书籍（info + divisions + chapters + content）
  download_book(book_id, output_dir) → 下载全本 → TXT 文件
"""

import os
import time
from pathlib import Path

from . import api as _api
from . import models
from .web import WebChapterError


class NoDownloadableChapters(RuntimeError):
    """目标书籍没有符合当前过滤条件的章节。"""


def get_book(session: _api.Session, book_id: str,
             on_chapter=None, book_info: dict = None,
             free_only: bool = False,
             chapter_delay: float = 0.05) -> models.Book:
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

    # Step 2: 新接口一次返回全部分卷与章节；旧接口作为兼容回退。
    try:
        catalog_data = session.get_book_catalog(book_id)
        div_list = catalog_data.get("data", {}).get("chapter_list", [])
        embedded_chapters = True
    except (AttributeError, _api.ApiError, RuntimeError):
        div_data = session.get_division_list(book_id)
        div_list = div_data.get("data", {}).get("division_list", [])
        embedded_chapters = False

    prepared = []
    for div_info in div_list:
        if embedded_chapters:
            chap_list = list(div_info.get("chapter_list", []))
        else:
            chap_data = session.get_chapter_list(
                div_info.get("division_id", ""))
            chap_list = list(
                chap_data.get("data", {}).get("chapter_list", []))
        selected = []
        for chap_info in chap_list:
            is_paid = str(chap_info.get(
                "is_paid", chap_info.get("is_vip", "0"))) == "1"
            auth_raw = chap_info.get("auth_access")
            auth_access = (str(auth_raw) == "1"
                           if auth_raw is not None else not is_paid)
            if free_only and (is_paid or not auth_access):
                continue
            selected.append((chap_info, is_paid, auth_access))
        if selected:
            prepared.append((div_info, selected))

    total_chapters = sum(len(chapters) for _, chapters in prepared)
    completed = 0
    for div_info, selected in prepared:
        division = models.Division(
            division_id=div_info.get("division_id", ""),
            division_name=div_info.get("division_name", ""),
        )
        for chap_info, is_paid, auth_access in selected:
            chapter = models.Chapter(
                chapter_id=chap_info.get("chapter_id", ""),
                chapter_index=int(chap_info.get("chapter_index", 0)),
                chapter_title=chap_info.get("chapter_title", ""),
                word_count=int(chap_info.get("word_count", 0)),
                is_vip=is_paid,
                auth_access=auth_access,
            )

            if not chapter.auth_access:
                chapter.content = "【未购买本章】"
            else:
                try:
                    # Step 4: 获取内容密钥
                    command = session.get_chapter_command(
                        chapter.chapter_id)
                    # Step 5: 获取并解密内容
                    if (free_only
                            and getattr(session, "supports_web_fallback", False)
                            is True):
                        chapter.content = session.get_chapter_content(
                            chapter.chapter_id,
                            command,
                            allow_web_fallback=True,
                        )
                    else:
                        chapter.content = session.get_chapter_content(
                            chapter.chapter_id, command)
                except Exception as e:
                    if isinstance(e, WebChapterError):
                        raise
                    chapter.content = f"【下载失败: {e}】"

            division.chapters.append(chapter)
            completed += 1

            if on_chapter:
                on_chapter(completed, total_chapters)

            if chapter_delay > 0:
                time.sleep(chapter_delay)

        book.divisions.append(division)

    return book


def download_book(session: _api.Session, book_id: str,
                  output_dir: str = "output",
                  progress_callback=None, book_info: dict = None,
                  skip_existing: bool = False,
                  free_only: bool = False,
                  include_book_id: bool = False,
                  chapter_delay: float = 0.05) -> str:
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
        stem = models.safe_book_name(book_info.get("book_name", book_id))
        if include_book_id:
            stem = f"{book_id} - {stem}"
        candidate = Path(output_dir) / f"{stem}.txt"
        if candidate.exists():
            return str(candidate)

    book = get_book(
        session, book_id, on_chapter=_on_chapter, book_info=book_info,
        free_only=free_only, chapter_delay=chapter_delay)

    if not any(division.chapters for division in book.divisions):
        raise NoDownloadableChapters(
            f"书籍 {book_id} 没有可导出的{'免费' if free_only else ''}章节")

    # 写入 TXT
    os.makedirs(output_dir, exist_ok=True)
    stem = book.safe_stem if include_book_id else book.safe_name
    output_path = Path(output_dir) / f"{stem}.txt"
    temp_path = output_path.with_suffix(".txt.part")

    try:
        with open(temp_path, "w", encoding="utf-8", newline="\n") as f:
            for division in book.divisions:
                for chapter in division.chapters:
                    f.write(chapter.chapter_title + "\n")
                    f.write(chapter.content + "\n\n")
        os.replace(temp_path, output_path)
    finally:
        temp_path.unlink(missing_ok=True)

    return str(output_path)
