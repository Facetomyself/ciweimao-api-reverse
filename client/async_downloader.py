"""基于 :mod:`curl_cffi` 异步会话的免费章节下载器。"""

import asyncio
import inspect
import os
from pathlib import Path

from . import api as _api
from . import models
from .downloader import NoDownloadableChapters


async def _notify(callback, current: int, total: int) -> None:
    if callback is None:
        return
    result = callback(current, total)
    if inspect.isawaitable(result):
        await result


def _chapter_from_info(chapter_info: dict, is_paid: bool,
                       auth_access: bool) -> models.Chapter:
    return models.Chapter(
        chapter_id=str(chapter_info.get("chapter_id", "")),
        chapter_index=int(chapter_info.get("chapter_index", 0) or 0),
        chapter_title=str(chapter_info.get("chapter_title", "")),
        word_count=int(chapter_info.get("word_count", 0) or 0),
        is_vip=is_paid,
        auth_access=auth_access,
    )


async def get_book(session: _api.AsyncSession, book_id: str,
                   on_chapter=None, book_info: dict = None,
                   free_only: bool = False,
                   chapter_delay: float = 0.05,
                   chapter_concurrency: int = 3) -> models.Book:
    """异步获取书籍、目录及可读正文，并保持原始章节顺序。"""
    info = dict(book_info or {})
    try:
        data = await session.get_book_info(book_id)
        info.update(data.get("data", {}).get("book_info", {}))
    except _api.ApiError as exc:
        if exc.code != "320001" or not info:
            raise

    book = models.Book(
        book_id=str(book_id),
        book_name=info.get("book_name", "未命名"),
        author_name=info.get("author_name", "佚名"),
        cover_url=info.get("cover", ""),
        total_word_count=int(info.get("total_word_count", 0) or 0),
        category_name=info.get("category_name", ""),
        description=info.get("description", ""),
    )

    try:
        catalog_data = await session.get_book_catalog(book_id)
        division_list = catalog_data.get("data", {}).get(
            "chapter_list", [])
        embedded_chapters = True
    except (AttributeError, _api.ApiError, RuntimeError):
        division_data = await session.get_division_list(book_id)
        division_list = division_data.get("data", {}).get(
            "division_list", [])
        embedded_chapters = False

    pending: list[models.Chapter] = []
    for division_info in division_list:
        if embedded_chapters:
            chapter_list = list(division_info.get("chapter_list", []))
        else:
            chapter_data = await session.get_chapter_list(
                str(division_info.get("division_id", "")))
            chapter_list = list(chapter_data.get("data", {}).get(
                "chapter_list", []))

        division = models.Division(
            division_id=str(division_info.get("division_id", "")),
            division_name=str(division_info.get("division_name", "")),
        )
        for chapter_info in chapter_list:
            is_paid = str(chapter_info.get(
                "is_paid", chapter_info.get("is_vip", "0"))) == "1"
            auth_raw = chapter_info.get("auth_access")
            auth_access = (str(auth_raw) == "1"
                           if auth_raw is not None else not is_paid)
            if free_only and (is_paid or not auth_access):
                continue
            chapter = _chapter_from_info(
                chapter_info, is_paid, auth_access)
            division.chapters.append(chapter)
            pending.append(chapter)
        if division.chapters:
            book.divisions.append(division)

    total = len(pending)
    completed = 0
    semaphore = asyncio.Semaphore(max(1, int(chapter_concurrency)))

    async def populate(chapter: models.Chapter) -> None:
        nonlocal completed
        if not chapter.auth_access:
            chapter.content = "【未购买本章】"
        else:
            async with semaphore:
                try:
                    command = await session.get_chapter_command(
                        chapter.chapter_id)
                    chapter.content = await session.get_chapter_content(
                        chapter.chapter_id, command)
                except Exception as exc:
                    chapter.content = f"【下载失败: {exc}】"
                if chapter_delay > 0:
                    await asyncio.sleep(chapter_delay)
        completed += 1
        await _notify(on_chapter, completed, total)

    if pending:
        await asyncio.gather(*(populate(chapter) for chapter in pending))
    return book


def _write_txt(book: models.Book, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(".txt.part")
    try:
        with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
            for division in book.divisions:
                for chapter in division.chapters:
                    handle.write(chapter.chapter_title + "\n")
                    handle.write(chapter.content + "\n\n")
        os.replace(temp_path, output_path)
    finally:
        temp_path.unlink(missing_ok=True)


async def download_book(session: _api.AsyncSession, book_id: str,
                        output_dir: str = "output",
                        progress_callback=None, book_info: dict = None,
                        skip_existing: bool = False,
                        free_only: bool = False,
                        include_book_id: bool = False,
                        chapter_delay: float = 0.05,
                        chapter_concurrency: int = 3) -> str:
    """异步下载一本书并原子导出 TXT。"""
    output_root = Path(output_dir)
    if skip_existing and book_info:
        stem = models.safe_book_name(book_info.get("book_name", book_id))
        if include_book_id:
            stem = f"{book_id} - {stem}"
        candidate = output_root / f"{stem}.txt"
        if candidate.exists():
            return str(candidate)

    book = await get_book(
        session,
        book_id,
        on_chapter=progress_callback,
        book_info=book_info,
        free_only=free_only,
        chapter_delay=chapter_delay,
        chapter_concurrency=chapter_concurrency,
    )
    if not any(division.chapters for division in book.divisions):
        label = "免费" if free_only else ""
        raise NoDownloadableChapters(
            f"书籍 {book_id} 没有可导出的{label}章节")

    stem = book.safe_stem if include_book_id else book.safe_name
    output_path = output_root / f"{stem}.txt"
    await asyncio.to_thread(_write_txt, book, output_path)
    return str(output_path)
