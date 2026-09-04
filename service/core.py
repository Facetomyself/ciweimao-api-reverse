"""搜索、榜单、新书与按书名下载的异步业务编排。"""

import asyncio
import hashlib
import inspect
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from client import async_downloader
from client.api import ApiError, AsyncSession
from client.downloader import NoDownloadableChapters
from client.web import WebChapterError

from .archive import ArchiveManager
from .config import ConfigurationError, Settings
from .credentials import (
    GuestCredentialBootstrapper,
)
from .database import Database
from .failures import FailureCategory, classify_failure
from .identity import IdentityStore
from .proxy import (
    ProxyLeaseContext,
    build_proxy_manager,
    redact_error_text,
)
from .schemas import (
    DownloadBookRequest,
    DownloadByNameRequest,
    EgressModeRequest,
    ProtocolProbeRequest,
    SyncAllRequest,
    SyncNewBooksRequest,
    SyncRankingsRequest,
)

TaskSubmitter = Callable[[str, dict, str | None], Awaitable[dict]]


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


def _utc_after(*, minutes: int = 0, hours: int = 0) -> str:
    value = datetime.now(timezone.utc) + timedelta(
        minutes=max(0, int(minutes)),
        hours=max(0, int(hours)),
    )
    return value.isoformat(timespec="milliseconds")


def _build_session(factory, **kwargs):
    """给自定义 session_factory 过滤未知关键字，保持旧替身兼容。"""
    try:
        signature = inspect.signature(factory)
    except (TypeError, ValueError):
        return factory(**kwargs)
    parameters = signature.parameters.values()
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD
           for parameter in parameters):
        return factory(**kwargs)
    allowed = {
        parameter.name
        for parameter in parameters
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    }
    return factory(**{
        key: value for key, value in kwargs.items() if key in allowed
    })


class CiweimaoService:
    def __init__(self, settings: Settings, database: Database,
                 session_factory=AsyncSession,
                 credential_bootstrap: GuestCredentialBootstrapper | None = None,
                 proxy_manager=None):
        self.settings = settings
        self.database = database
        self.session_factory = session_factory
        self.credential_bootstrap = credential_bootstrap
        self.proxy_manager = proxy_manager or build_proxy_manager(settings)
        self.identity_store = (
            getattr(credential_bootstrap, "identity_store", None)
            or IdentityStore(
                settings.resolved_identity_store_path,
                legacy_token_path=settings.token_path,
            )
        )
        self.archive_manager = ArchiveManager(settings, database)
        self._task_submitter: TaskSubmitter | None = None
        self._last_operation_source = "app"
        # 游客身份与出口相关，所有 App 网络工作流必须串行切换租约。
        self._workflow_lock = asyncio.Lock()

    def set_credential_bootstrap(
            self, bootstrap: GuestCredentialBootstrapper | None) -> None:
        self.credential_bootstrap = bootstrap
        if bootstrap is not None and getattr(
                bootstrap, "identity_store", None) is not None:
            self.identity_store = bootstrap.identity_store

    def set_task_submitter(self, submitter: TaskSubmitter) -> None:
        self._task_submitter = submitter

    @property
    def task_handlers(self):
        return {
            "download_by_name": self.handle_download_by_name,
            "download_book": self.handle_download_book,
            "sync_rankings": self.handle_sync_rankings,
            "sync_new_books": self.handle_sync_new_books,
            "sync_all": self.handle_sync_all,
            "protocol_probe": self.handle_protocol_probe,
            "identity_validate": self.handle_identity_validate,
            "identity_rotate": self.handle_identity_rotate,
            "egress_mode": self.handle_egress_mode,
            "archive_backup": self.handle_archive_backup,
            "archive_pending": self.handle_archive_pending,
            "archive_retry_mirrors": self.handle_archive_retry_mirrors,
            "archive_maintenance": self.handle_archive_maintenance,
        }

    @asynccontextmanager
    async def client(self, credentials=None, proxy_url: str | None = None):
        credentials = credentials or self.settings.load_credentials()
        session = _build_session(
            self.session_factory,
            login_token=credentials.login_token,
            account=credentials.account,
            device_token=credentials.device_token,
            app_version=self.settings.app_version,
            base_url=self.settings.protocol.base_url,
            timeout=self.settings.http_timeout,
            impersonate=(
                self.settings.http_impersonate
                or self.settings.protocol.impersonate),
            max_clients=self.settings.http_max_clients,
            max_retries=self.settings.http_max_retries,
            retry_backoff=self.settings.http_retry_backoff,
            transient_api_retries=(
                self.settings.http_transient_api_retries),
            proxy=proxy_url,
            web_fallback_enabled=self.settings.web_fallback_enabled,
            web_min_interval=self.settings.web_min_interval_seconds,
        )
        async with session:
            yield session

    @asynccontextmanager
    async def _workflow(self, *, force_new_proxy: bool,
                        reason: str, slot_id: str | None = None):
        async with self._workflow_lock:
            if slot_id is not None:
                context_factory = getattr(
                    self.proxy_manager, "context_for_slot", None)
                if context_factory is not None:
                    context = await context_factory(
                        slot_id,
                        force_new=force_new_proxy,
                        reason=reason,
                    )
                else:
                    snapshot = self.proxy_manager.snapshot()
                    managed_slot = snapshot.get("slot_id", "default")
                    if slot_id != managed_slot:
                        raise ConfigurationError(
                            f"当前出口模式不支持槽 {slot_id}")
                    context = await self.proxy_manager.context(
                        force_new=force_new_proxy,
                        reason=reason,
                    )
            else:
                context = await self.proxy_manager.context(
                    force_new=force_new_proxy,
                    reason=reason,
                )
            yield context

    async def _load_credentials(
            self, proxy_url: str | None, identity_slot: str):
        if self.credential_bootstrap is not None:
            loader = getattr(
                self.credential_bootstrap, "load_credentials", None)
            if loader is not None:
                return await loader(identity_slot, proxy_url=proxy_url)
            try:
                return self.settings.load_credentials()
            except ConfigurationError:
                await self.credential_bootstrap.ensure(proxy_url=proxy_url)
                return self.settings.load_credentials()
        return self.settings.load_credentials()

    async def _record_failure_event(self, *, task_type: str,
                                    lease, info, exc) -> None:
        if not hasattr(self.database, "record_event"):
            return
        await self.database.record_event(
            event_type="request_failure",
            component=task_type,
            category=info.category.value,
            code=info.code,
            slot_id=lease.slot_id,
            message=redact_error_text(exc),
        )

    async def _run_with_client(self, operation,
                               proxy_context: ProxyLeaseContext,
                               *, operation_name: str = "app_request"):
        refreshed_credentials: set[tuple[str, int]] = set()
        confirmed_failures: set[tuple[str, int, str]] = set()
        refreshed_egress: set[tuple[str, int, str]] = set()
        last_error: BaseException | None = None
        for _ in range(6):
            lease = proxy_context.lease
            credentials = None
            try:
                credentials = await self._load_credentials(
                    lease.proxy_url, lease.slot_id)
                async with self.client(
                        credentials, proxy_url=lease.proxy_url) as session:
                    result = await operation(session)
                    used_web_fallback = bool(
                        getattr(session, "web_fallback_used", False))
                self._last_operation_source = (
                    "web_fallback" if used_web_fallback else "app")
                self.proxy_manager.report_success(lease)
                identity_store = getattr(
                    self.credential_bootstrap, "identity_store", None)
                if identity_store is not None:
                    await identity_store.mark_validated(lease.slot_id)
                if hasattr(self.database, "record_event"):
                    await self.database.record_event(
                        event_type="request_success",
                        component=operation_name,
                        slot_id=lease.slot_id,
                        message=(
                            "Web fallback request succeeded"
                            if used_web_fallback
                            else "App request succeeded"
                        ),
                        metadata={
                            "source": (
                                "web_fallback"
                                if used_web_fallback else "app"
                            )
                        },
                    )
                return result
            except Exception as exc:
                last_error = exc
                info = classify_failure(exc)
                generation_key = (lease.slot_id, lease.generation)
                failure_key = (
                    lease.slot_id, lease.generation, info.category.value)
                await self._record_failure_event(
                    task_type=operation_name,
                    lease=lease,
                    info=info,
                    exc=exc,
                )
                self.proxy_manager.report_failure(lease, info.category)
                if (credentials is not None
                        and self.credential_bootstrap is not None
                        and generation_key not in refreshed_credentials
                        and info.refresh_identity):
                    refreshed_credentials.add(generation_key)
                    try:
                        if isinstance(
                                self.credential_bootstrap,
                                GuestCredentialBootstrapper):
                            await self.credential_bootstrap.refresh(
                                credentials,
                                proxy_url=lease.proxy_url,
                                identity_slot=lease.slot_id,
                            )
                        else:
                            await self.credential_bootstrap.refresh(
                                credentials, proxy_url=lease.proxy_url)
                    except Exception as refresh_exc:
                        last_error = refresh_exc
                    else:
                        continue

                if (info.category == FailureCategory.RISK_REJECTED
                        and not isinstance(exc, WebChapterError)):
                    identity_store = getattr(
                        self.credential_bootstrap, "identity_store", None)
                    if identity_store is not None:
                        await identity_store.invalidate(
                            lease.slot_id, "risk_rejected")

                if (info.retry_same_egress
                        and failure_key not in confirmed_failures):
                    confirmed_failures.add(failure_key)
                    continue

                if (info.switch_egress
                        and failure_key not in refreshed_egress):
                    refreshed_egress.add(failure_key)
                    previous = (
                        proxy_context.lease.slot_id,
                        proxy_context.lease.generation,
                    )
                    await proxy_context.refresh(
                        f"{info.category.value}:{info.code or 'unknown'}")
                    current = (
                        proxy_context.lease.slot_id,
                        proxy_context.lease.generation,
                    )
                    if current != previous:
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

    async def _download_book(self, *, book: dict, task_id: str,
                             query: str,
                             proxy_context: ProxyLeaseContext,
                             skip_existing: bool,
                             include_book_id: bool) -> dict:
        book_id = str(book.get("book_id", "")).strip()
        if not book_id:
            raise BookNotFoundError("下载目标缺少 book_id")
        output_path = await self._run_with_client(
            lambda session: async_downloader.download_book(
                session,
                book_id,
                output_dir=str(self.settings.output_dir),
                book_info=book,
                skip_existing=skip_existing,
                free_only=True,
                include_book_id=include_book_id,
                chapter_delay=self.settings.chapter_delay,
                chapter_concurrency=self.settings.chapter_concurrency,
            ),
            proxy_context,
        )
        file_size, sha256 = await asyncio.to_thread(
            _file_digest, output_path)
        artifact = await self.database.record_download(
            task_id=task_id,
            query=query,
            book=book,
            output_path=str(Path(output_path).resolve()),
            file_size=file_size,
            sha256=sha256,
        )
        return {
            "book_id": book_id,
            "book_name": book.get("book_name", ""),
            "author_name": book.get("author_name", ""),
            "output_path": artifact["output_path"],
            "file_size": artifact["file_size"],
            "sha256": artifact["sha256"],
            "free_only": True,
            "content_source": self._last_operation_source,
        }

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
            return await self._download_book(
                book=selected,
                task_id=task_id,
                query=request.book_name,
                proxy_context=proxy_context,
                skip_existing=request.skip_existing,
                include_book_id=request.include_book_id,
            )

    async def handle_download_book(self, payload: dict,
                                   task_id: str) -> dict:
        request = DownloadBookRequest.model_validate(payload)
        book = {
            "book_id": request.book_id,
            "book_name": request.book_name,
            "author_name": request.author_name,
        }
        await self.database.upsert_books([book])
        await self.database.mark_auto_download_running(
            request.book_id, task_id)
        try:
            async with self._workflow(
                    force_new_proxy=False,
                    reason="download_book") as proxy_context:
                result = await self._download_book(
                    book=book,
                    task_id=task_id,
                    query=f"auto:{request.source}",
                    proxy_context=proxy_context,
                    skip_existing=request.skip_existing,
                    include_book_id=request.include_book_id,
                )
        except NoDownloadableChapters as exc:
            retry_after = _utc_after(
                hours=self.settings.auto_download_no_free_retry_hours)
            await self.database.finish_auto_download(
                request.book_id,
                task_id,
                "no_free",
                error=str(exc),
                retry_after=retry_after,
            )
            return {
                "book_id": request.book_id,
                "book_name": request.book_name,
                "status": "no_free",
                "retry_after": retry_after,
            }
        except Exception as exc:
            retry_after = _utc_after(
                minutes=self.settings.auto_download_failure_retry_minutes)
            await self.database.finish_auto_download(
                request.book_id,
                task_id,
                "failed",
                error=redact_error_text(exc),
                retry_after=retry_after,
            )
            raise

        await self.database.finish_auto_download(
            request.book_id, task_id, "succeeded")
        result["status"] = "downloaded"
        result["source"] = request.source
        return result

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

    async def _enqueue_auto_downloads(self) -> dict:
        if (not self.settings.auto_download_enabled
                or await self.database.is_paused("auto_download")):
            return {
                "enabled": False,
                "selected": 0,
                "queued": 0,
                "deduplicated": 0,
            }
        if self._task_submitter is None:
            raise RuntimeError("自动下载未绑定持久化任务队列")

        candidates = await self.database.list_auto_download_candidates(
            self.settings.auto_download_batch_size)
        queued = 0
        deduplicated = 0
        for book in candidates:
            request = DownloadBookRequest(
                book_id=str(book.get("book_id", "")),
                book_name=str(book.get("book_name", "")),
                author_name=str(book.get("author_name", "")),
                source="sync_all",
                skip_existing=True,
                include_book_id=True,
            )
            task_payload = request.model_dump(mode="json")
            task = await self._task_submitter(
                "download_book",
                task_payload,
                f"download_book:{request.book_id}",
            )
            await self.database.mark_auto_download_queued(
                request.book_id, task["id"])
            if task.get("deduplicated"):
                deduplicated += 1
            else:
                queued += 1
        return {
            "enabled": True,
            "batch_size": self.settings.auto_download_batch_size,
            "selected": len(candidates),
            "queued": queued,
            "deduplicated": deduplicated,
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
        auto_download = await self._enqueue_auto_downloads()
        return {
            "rankings": rankings,
            "new_books": new_books,
            "auto_download": auto_download,
        }

    @staticmethod
    def _first_free_chapter_id(catalog: dict) -> str:
        for division in catalog.get("data", {}).get("chapter_list", []) or []:
            for chapter in division.get("chapter_list", []) or []:
                if (str(chapter.get("is_paid")) == "0"
                        and str(chapter.get("auth_access")) == "1"):
                    return str(chapter.get("chapter_id") or "")
        return ""

    async def _record_probe(self, *, endpoint: str, slot_id: str,
                            ok: bool, elapsed_ms: float, exc=None,
                            metadata: dict | None = None) -> None:
        info = classify_failure(exc) if exc is not None else None
        await self.database.record_protocol_probe(
            protocol_profile=self.settings.protocol.name,
            endpoint=endpoint,
            slot_id=slot_id or "automatic",
            ok=ok,
            category="" if info is None else info.category.value,
            code="" if info is None else info.code,
            latency_ms=elapsed_ms,
        )
        await self.database.record_event(
            event_type=(
                "protocol_probe_succeeded" if ok else "protocol_probe_failed"
            ),
            component="protocol",
            category="" if info is None else info.category.value,
            code="" if info is None else info.code,
            slot_id=slot_id or "automatic",
            endpoint=endpoint,
            message=(
                "protocol probe succeeded"
                if ok else redact_error_text(exc)
            ),
            metadata=metadata or {"latency_ms": round(elapsed_ms, 1)},
        )

    async def probe_protocol(
            self, request: ProtocolProbeRequest) -> dict:
        selected_slot = request.slot_id
        actual_slot = selected_slot or "automatic"
        current_endpoint = "search/books"
        started = time.perf_counter()
        checks: list[dict] = []
        app_protocol_ok = False
        web_fallback_ok = False

        async def _step(endpoint: str, operation):
            nonlocal current_endpoint, started
            current_endpoint = endpoint
            started = time.perf_counter()
            result = await self._run_with_client(
                operation,
                proxy_context,
                operation_name="protocol_probe",
            )
            elapsed = (time.perf_counter() - started) * 1000
            await self._record_probe(
                endpoint=endpoint,
                slot_id=actual_slot,
                ok=True,
                elapsed_ms=elapsed,
            )
            checks.append({
                "endpoint": endpoint,
                "ok": True,
                "latency_ms": round(elapsed, 1),
            })
            return result

        try:
            async with self._workflow(
                    force_new_proxy=request.force_new_proxy,
                    reason="protocol_probe",
                    slot_id=selected_slot) as proxy_context:
                actual_slot = proxy_context.lease.slot_id
                search = await _step(
                    "search/books",
                    lambda session: session.search_books(
                        request.keyword, page=0, count=1),
                )
                books = search.get("data", {}).get("book_list", []) or []
                if not books:
                    raise RuntimeError("protocol probe search returned no books")
                book_id = str(books[0].get("book_id") or "")
                catalog = await _step(
                    "chapter/catalog",
                    lambda session: session.get_book_catalog(book_id),
                )
                chapter_id = self._first_free_chapter_id(catalog)
                if not chapter_id:
                    raise RuntimeError(
                        "protocol probe found no free readable chapter")
                command = await _step(
                    "chapter/get_chapter_cmd",
                    lambda session, chapter_id=chapter_id: (
                        session.get_chapter_command(chapter_id)
                    ),
                )
                try:
                    await _step(
                        "chapter/get_cpt_ifm",
                        lambda session, chapter_id=chapter_id, command=command: (
                            session.get_chapter_content(
                                chapter_id,
                                command,
                                allow_gt3_stamp=True,
                            )
                        ),
                    )
                    app_protocol_ok = True
                except ApiError as exc:
                    # 310017 remains if GT3 stamp is unavailable. Keep the
                    # failed App probe in evidence, then optionally verify
                    # the isolated public Web route for free-only service use.
                    if (exc.code != "310017"
                            or not self.settings.web_fallback_enabled):
                        raise
                    app_elapsed = (time.perf_counter() - started) * 1000
                    await self._record_probe(
                        endpoint="chapter/get_cpt_ifm",
                        slot_id=actual_slot,
                        ok=False,
                        elapsed_ms=app_elapsed,
                        exc=exc,
                        metadata={"route": "app"},
                    )
                    checks.append({
                        "endpoint": "chapter/get_cpt_ifm",
                        "ok": False,
                        "code": exc.code,
                        "latency_ms": round(app_elapsed, 1),
                        "route": "app",
                    })
                    web_content = await _step(
                        "web/chapter",
                        lambda session, chapter_id=chapter_id, command=command: (
                            session.get_chapter_content(
                                chapter_id,
                                command,
                                allow_web_fallback=True,
                            )
                        ),
                    )
                    if not str(web_content or "").strip():
                        raise RuntimeError("web fallback returned empty chapter")
                    web_fallback_ok = True
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000
            await self._record_probe(
                endpoint=current_endpoint,
                slot_id=actual_slot,
                ok=False,
                elapsed_ms=elapsed,
                exc=exc,
            )
            checks.append({
                "endpoint": current_endpoint,
                "ok": False,
                "code": classify_failure(exc).code,
                "latency_ms": round(elapsed, 1),
            })
            raise
        return {
            # `ok` means the configured service route is usable.  The App
            # gate remains explicit below and is never promoted silently.
            "ok": bool(app_protocol_ok or web_fallback_ok),
            "protocol_profile": self.settings.protocol.name,
            "app_version": self.settings.app_version,
            "endpoint": "chapter/get_cpt_ifm",
            "route": "app" if app_protocol_ok else "web_fallback",
            "app_protocol_ok": app_protocol_ok,
            "web_fallback_ok": web_fallback_ok,
            "slot_id": actual_slot,
            "latency_ms": sum(item.get("latency_ms", 0) for item in checks),
            "result_count": len(books),
            "checks": checks,
        }

    async def handle_protocol_probe(self, payload: dict,
                                    task_id: str) -> dict:
        del task_id
        return await self.probe_protocol(
            ProtocolProbeRequest.model_validate(payload))

    async def handle_identity_validate(self, payload: dict,
                                       task_id: str) -> dict:
        del task_id
        slot_id = str(payload.get("slot_id") or "default")
        result = await self.probe_protocol(ProtocolProbeRequest(
            slot_id=slot_id,
            force_new_proxy=bool(payload.get("force_new_proxy", False)),
        ))
        result["identity"] = await self.identity_store.snapshot()
        return result

    async def handle_identity_rotate(self, payload: dict,
                                     task_id: str) -> dict:
        del task_id
        if self.settings.env_credentials_configured():
            raise ConfigurationError(
                "环境变量身份不可由控制面轮换")
        slot_id = str(payload.get("slot_id") or "default")
        await self.identity_store.rotate_profile(
            slot_id, self.settings.app_version)
        result = await self.probe_protocol(ProtocolProbeRequest(
            slot_id=slot_id,
            force_new_proxy=True,
        ))
        result["rotated"] = True
        result["identity"] = await self.identity_store.snapshot()
        return result

    async def handle_egress_mode(self, payload: dict,
                                 task_id: str) -> dict:
        del task_id
        request = EgressModeRequest.model_validate(payload)
        force_slot = getattr(self.proxy_manager, "force_slot", None)
        if force_slot is None:
            raise ConfigurationError("当前不是主备出口模式")
        slot_id = None if request.mode == "automatic" else request.mode
        if request.reset_breaker and slot_id:
            reset_slot = getattr(self.proxy_manager, "reset_slot", None)
            if reset_slot is not None:
                reset_slot(slot_id)
        force_slot(slot_id)
        await self.database.record_event(
            event_type="egress_mode_changed",
            component="egress",
            slot_id=slot_id or "automatic",
            message=request.mode,
            metadata={"reset_breaker": request.reset_breaker},
        )
        return self.proxy_manager.snapshot()

    async def handle_archive_backup(self, payload: dict,
                                    task_id: str) -> dict:
        del task_id
        label = str(payload.get("label") or "manual")[:64]
        return await self.archive_manager.create_backup(label=label)

    async def handle_archive_pending(self, payload: dict,
                                     task_id: str) -> dict:
        del payload, task_id
        return {"archives": await self.archive_manager.archive_pending_raw()}

    async def handle_archive_retry_mirrors(self, payload: dict,
                                           task_id: str) -> dict:
        del payload, task_id
        return {"mirrors": await self.archive_manager.retry_mirrors()}

    async def handle_archive_maintenance(self, payload: dict,
                                         task_id: str) -> dict:
        del task_id
        return await self.archive_manager.run_maintenance(
            compact=bool(payload.get("compact", False)))
