"""搜索、榜单、新书与按书名下载的异步业务编排。"""

from contextlib import asynccontextmanager
import asyncio
import hashlib
from pathlib import Path

from client import async_downloader, config as client_config
from client.api import AsyncSession

from .config import ConfigurationError, Settings
from .credentials import (
    GuestCredentialBootstrapper,
    is_invalid_credentials_error,
)
from .database import Database
from .proxy import (
    ProxyLeaseContext,
    ProxyLeaseManager,
    build_proxy_manager,
    is_proxy_failure_error,
)
from .schemas import (
    DownloadByNameRequest,
    SyncAllRequest,
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
                 session_factory=AsyncSession,
                 credential_bootstrap: GuestCredentialBootstrapper | None = None,
                 proxy_manager: ProxyLeaseManager | None = None):
        self.settings = settings
        self.database = database
        self.session_factory = session_factory
        self.credential_bootstrap = credential_bootstrap
        self.proxy_manager = proxy_manager or build_proxy_manager(settings)
        # 游客身份与出口相关，所有 App 网络工作流必须串行切换租约。
        self._workflow_lock = asyncio.Lock()

    def set_credential_bootstrap(
            self, bootstrap: GuestCredentialBootstrapper | None) -> None:
        self.credential_bootstrap = bootstrap

    @property
    def task_handlers(self):
        return {
            "download_by_name": self.handle_download_by_name,
            "sync_rankings": self.handle_sync_rankings,
            "sync_new_books": self.handle_sync_new_books,
            "sync_all": self.handle_sync_all,
        }

    @asynccontextmanager
    async def client(self, credentials=None, proxy_url: str | None = None):
        credentials = credentials or self.settings.load_credentials()
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
            proxy=proxy_url,
        )
        async with session:
            yield session

    @asynccontextmanager
    async def _workflow(self, *, force_new_proxy: bool,
                        reason: str):
        async with self._workflow_lock:
            context = await self.proxy_manager.context(
                force_new=force_new_proxy,
                reason=reason,
            )
            yield context

    async def _load_credentials(
            self, proxy_url: str | None):
        try:
            return self.settings.load_credentials()
        except ConfigurationError:
            if self.credential_bootstrap is None:
                raise
            await self.credential_bootstrap.ensure(proxy_url=proxy_url)
            return self.settings.load_credentials()

    async def _run_with_client(self, operation,
                               proxy_context: ProxyLeaseContext):
        refreshed_credentials: set[int] = set()
        refreshed_proxies: set[int] = set()
        last_error: BaseException | None = None
        for _ in range(6):
            lease = proxy_context.lease
            credentials = None
            try:
                credentials = await self._load_credentials(lease.proxy_url)
                async with self.client(
                        credentials, proxy_url=lease.proxy_url) as session:
                    return await operation(session)
            except Exception as exc:
                last_error = exc
                generation = lease.generation
                if (credentials is not None
                        and self.credential_bootstrap is not None
                        and generation not in refreshed_credentials
                        and is_invalid_credentials_error(exc)):
                    refreshed_credentials.add(generation)
                    try:
                        await self.credential_bootstrap.refresh(
                            credentials,
                            proxy_url=lease.proxy_url,
                        )
                    except Exception as refresh_exc:
                        last_error = refresh_exc
                    else:
                        continue

                if (self.proxy_manager.dynamic
                        and generation not in refreshed_proxies
                        and is_proxy_failure_error(last_error)):
                    refreshed_proxies.add(generation)
                    await proxy_context.refresh("request-failure")
                    continue
                raise last_error
        if last_error is not None:
            raise last_error
        raise RuntimeError("App 请求未执行")

    async def search_books(self, keyword: str, max_pages: int = 1,
                           count: int = 10) -> list[dict]:
        async with self._workflow(
                force_new_proxy=False, reason="search") as proxy_context:
            return await self._search_books(
                keyword,
                max_pages=max_pages,
                count=count,
                proxy_context=proxy_context,
            )

    async def _search_books(self, keyword: str, max_pages: int,
                            count: int,
                            proxy_context: ProxyLeaseContext) -> list[dict]:
        books = []
        seen_ids: set[str] = set()
        seen_pages: set[tuple[str, ...]] = set()
        for page in range(max_pages):
            data = await self._run_with_client(
                lambda session: session.search_books(
                    keyword, page=page, count=count),
                proxy_context,
            )
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
        async with self._workflow(
                force_new_proxy=False,
                reason="download_by_name") as proxy_context:
            books = await self._search_books(
                request.book_name,
                max_pages=request.max_search_pages,
                count=10,
                proxy_context=proxy_context,
            )
            selected = self._select_book(books, request)
            book_id = str(selected.get("book_id", ""))
            if not book_id:
                raise BookNotFoundError(
                    f"搜索结果缺少 book_id: {request.book_name}")
            output_path = await self._run_with_client(
                lambda session: async_downloader.download_book(
                    session,
                    book_id,
                    output_dir=str(self.settings.output_dir),
                    book_info=selected,
                    skip_existing=request.skip_existing,
                    free_only=True,
                    include_book_id=request.include_book_id,
                    chapter_delay=self.settings.chapter_delay,
                    chapter_concurrency=self.settings.chapter_concurrency,
                ),
                proxy_context,
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

    async def _sync_rankings(self, request: SyncRankingsRequest,
                             proxy_context: ProxyLeaseContext) -> dict:
        snapshots = []
        for index, spec in enumerate(request.specs):
            books = await self._run_with_client(
                lambda session: session.get_rank_books(
                    order=spec.order,
                    time_type=spec.time_type,
                    page=0,
                    count=request.count,
                    category_index=request.category_index,
                ),
                proxy_context,
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

    async def _sync_new_books(self, request: SyncNewBooksRequest,
                              proxy_context: ProxyLeaseContext) -> dict:
        books = []
        seen_ids: set[str] = set()
        seen_pages: set[tuple[str, ...]] = set()
        for page in range(request.max_pages):
            page_books = await self._run_with_client(
                lambda session: session.get_bookcity_books(
                    page=page, count=request.count, order="newtime"),
                proxy_context,
            )
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

    async def handle_sync_rankings(self, payload: dict,
                                   task_id: str) -> dict:
        del task_id
        request = SyncRankingsRequest.model_validate(payload)
        async with self._workflow(
                force_new_proxy=True,
                reason="sync_rankings") as proxy_context:
            return await self._sync_rankings(request, proxy_context)

    async def handle_sync_new_books(self, payload: dict,
                                    task_id: str) -> dict:
        del task_id
        request = SyncNewBooksRequest.model_validate(payload)
        async with self._workflow(
                force_new_proxy=True,
                reason="sync_new_books") as proxy_context:
            return await self._sync_new_books(request, proxy_context)

    async def handle_sync_all(self, payload: dict, task_id: str) -> dict:
        """在一次 workflow 内完成榜单和新书同步，初始只获取一个 IP。"""
        del task_id
        request = SyncAllRequest.model_validate(payload)
        async with self._workflow(
                force_new_proxy=True,
                reason="sync_all") as proxy_context:
            rankings = await self._sync_rankings(
                request.rankings, proxy_context)
            new_books = await self._sync_new_books(
                request.new_books, proxy_context)
        return {
            "rankings": rankings,
            "new_books": new_books,
        }
