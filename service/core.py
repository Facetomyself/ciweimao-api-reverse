"""搜索、榜单、新书与按书名下载的异步业务编排。"""

from contextlib import asynccontextmanager
import asyncio
import hashlib
from pathlib import Path

from client import async_downloader, config as client_config
from client.api import AsyncSession

from .config import Settings
from .database import Database
from .schemas import (
    DownloadByNameRequest,
    SyncNewBooksRequest,
    SyncRankingsRequest,
)


class BookNotFoundError(RuntimeError):
    """搜索结果中没有满足书名/作者约束的书籍。"""


def _normalize_name(value: str) -> str:
    return "".join(str(value or "").casefold().split())


def _file_digest(path: str) -> tuple[int, str]:
    target = Path(path)
    digest = hashlib.sha256()
    with open(target, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return target.stat().st_size, digest.hexdigest()


class CiweimaoService:
    def __init__(self, settings: Settings, database: Database,
                 session_factory=AsyncSession):
        self.settings = settings
        self.database = database
        self.session_factory = session_factory

    @property
    def task_handlers(self):
        return {
            "download_by_name": self.handle_download_by_name,
            "sync_rankings": self.handle_sync_rankings,
            "sync_new_books": self.handle_sync_new_books,
        }

    @asynccontextmanager
    async def client(self):
        credentials = self.settings.load_credentials()
        session = self.session_factory(
            login_token=credentials.login_token,
            account=credentials.account,
            device_token=credentials.device_token,
            app_version=client_config.APP_VERSION,
            timeout=self.settings.http_timeout,
            impersonate=self.settings.http_impersonate,
            max_clients=self.settings.http_max_clients,
            max_retries=self.settings.http_max_retries,
            retry_backoff=self.settings.http_retry_backoff,
            transient_api_retries=(
                self.settings.http_transient_api_retries),
            proxy=self.settings.http_proxy_url,
        )
        async with session:
            yield session

    async def search_books(self, keyword: str, max_pages: int = 1,
                           count: int = 10) -> list[dict]:
        books = []
        seen_ids: set[str] = set()
        seen_pages: set[tuple[str, ...]] = set()
        for page in range(max_pages):
            async with self.client() as session:
                data = await session.search_books(
                    keyword, page=page, count=count)
            fresh, stop = self._dedupe_page(
                data.get("data", {}).get("book_list", []),
                seen_ids,
                seen_pages,
            )
            books.extend(fresh)
            if stop:
                break
            if self.settings.list_request_delay > 0:
                await asyncio.sleep(self.settings.list_request_delay)
        await self.database.upsert_books(books)
        return books

    @staticmethod
    def _dedupe_page(page_books: list[dict], seen_ids: set[str],
                     seen_pages: set[tuple[str, ...]]) -> tuple[list[dict], bool]:
        books = list(page_books or [])
        if not books:
            return [], True
        signature = tuple(str(book.get("book_id", "")) for book in books)
        if signature in seen_pages:
            return [], True
        seen_pages.add(signature)
        fresh = []
        for book in books:
            book_id = str(book.get("book_id", ""))
            if not book_id or book_id in seen_ids:
                continue
            seen_ids.add(book_id)
            fresh.append(book)
        return fresh, not fresh

    @staticmethod
    def _select_book(books: list[dict], request: DownloadByNameRequest) -> dict:
        wanted_name = _normalize_name(request.book_name)
        wanted_author = _normalize_name(request.author_name or "")

        def author_matches(book: dict) -> bool:
            return (not wanted_author
                    or _normalize_name(book.get("author_name", ""))
                    == wanted_author)

        exact = [book for book in books
                 if _normalize_name(book.get("book_name", "")) == wanted_name
                 and author_matches(book)]
        if exact:
            return exact[0]
        if request.exact_match:
            author_tip = (f"，作者={request.author_name}"
                          if request.author_name else "")
            raise BookNotFoundError(
                f"未找到精确书名: {request.book_name}{author_tip}")

        fuzzy = [book for book in books
                 if wanted_name in _normalize_name(book.get("book_name", ""))
                 and author_matches(book)]
        if fuzzy:
            return fuzzy[0]
        if books and not wanted_author:
            return books[0]
        raise BookNotFoundError(f"未找到书籍: {request.book_name}")

    async def handle_download_by_name(self, payload: dict,
                                      task_id: str) -> dict:
        request = DownloadByNameRequest.model_validate(payload)
        books = await self.search_books(
            request.book_name,
            max_pages=request.max_search_pages,
            count=10,
        )
        selected = self._select_book(books, request)
        book_id = str(selected.get("book_id", ""))
        if not book_id:
            raise BookNotFoundError(
                f"搜索结果缺少 book_id: {request.book_name}")
        async with self.client() as session:
            output_path = await async_downloader.download_book(
                session,
                book_id,
                output_dir=str(self.settings.output_dir),
                book_info=selected,
                skip_existing=request.skip_existing,
                free_only=True,
                include_book_id=request.include_book_id,
                chapter_delay=self.settings.chapter_delay,
                chapter_concurrency=self.settings.chapter_concurrency,
            )

        file_size, sha256 = await asyncio.to_thread(
            _file_digest, output_path)
        artifact = await self.database.record_download(
            task_id=task_id,
            query=request.book_name,
            book=selected,
            output_path=str(Path(output_path).resolve()),
            file_size=file_size,
            sha256=sha256,
        )
        return {
            "book_id": book_id,
            "book_name": selected.get("book_name", ""),
            "author_name": selected.get("author_name", ""),
            "output_path": artifact["output_path"],
            "file_size": artifact["file_size"],
            "sha256": artifact["sha256"],
            "free_only": True,
        }

    async def handle_sync_rankings(self, payload: dict,
                                   task_id: str) -> dict:
        del task_id
        request = SyncRankingsRequest.model_validate(payload)
        snapshots = []
        for index, spec in enumerate(request.specs):
            async with self.client() as session:
                books = await session.get_rank_books(
                    order=spec.order,
                    time_type=spec.time_type,
                    page=0,
                    count=request.count,
                    category_index=request.category_index,
                )
            snapshot = await self.database.create_snapshot(
                kind="ranking",
                source_key=spec.source_key,
                books=books,
                metadata={
                    "order": spec.order,
                    "time_type": spec.time_type,
                    "page": 0,
                    "count": request.count,
                    "category_index": request.category_index,
                },
            )
            snapshots.append(snapshot)
            if (index + 1 < len(request.specs)
                    and self.settings.list_request_delay > 0):
                await asyncio.sleep(self.settings.list_request_delay)
        return {
            "snapshot_count": len(snapshots),
            "item_count": sum(item["item_count"] for item in snapshots),
            "snapshots": snapshots,
        }

    async def handle_sync_new_books(self, payload: dict,
                                    task_id: str) -> dict:
        del task_id
        request = SyncNewBooksRequest.model_validate(payload)
        books = []
        seen_ids: set[str] = set()
        seen_pages: set[tuple[str, ...]] = set()
        for page in range(request.max_pages):
            async with self.client() as session:
                page_books = await session.get_bookcity_books(
                    page=page, count=request.count, order="newtime")
            fresh, stop = self._dedupe_page(
                page_books, seen_ids, seen_pages)
            books.extend(fresh)
            if stop:
                break
            if (page + 1 < request.max_pages
                    and self.settings.list_request_delay > 0):
                await asyncio.sleep(self.settings.list_request_delay)
        snapshot = await self.database.create_snapshot(
            kind="new_books",
            source_key="newtime",
            books=books,
            metadata={
                "order": "newtime",
                "max_pages": request.max_pages,
                "count": request.count,
            },
        )
        return {
            "snapshot_id": snapshot["id"],
            "item_count": snapshot["item_count"],
            "captured_at": snapshot["captured_at"],
        }
