"""FastAPI 控制面、健康检查与同源 SPA 入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse

from .config import PROJECT_ROOT, ConfigurationError, Settings
from .core import CiweimaoService
from .credentials import (
    CredentialBootstrapResult,
    GuestCredentialBootstrapper,
)
from .database import Database
from .proxy import redact_error_text
from .queue import PersistentTaskQueue
from .scheduler import build_scheduler, task_dedupe_key
from .schemas import (
    ArchiveMaintenanceRequest,
    ArchivePreviewRequest,
    ControlRequest,
    DirectBookDownloadRequest,
    DownloadBookRequest,
    DownloadByNameRequest,
    EgressModeRequest,
    IdentityRotateRequest,
    ProtocolProbeRequest,
    SyncAllRequest,
    SyncNewBooksRequest,
    SyncRankingsRequest,
    TaskStatus,
)

CONTROL_SCOPES = {"all", "scheduler", "auto_download"}
IDENTITY_SLOTS = {"default", "nas-primary", "dps-fallback"}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_file(path: str | Path, root: str | Path) -> Path:
    target = Path(path).resolve()
    allowed = Path(root).resolve()
    try:
        target.relative_to(allowed)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="文件不在允许目录") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return target


def _proxy_snapshot(service) -> dict:
    manager = getattr(service, "proxy_manager", None)
    if manager is None:
        return {
            "provider": "unmanaged",
            "dynamic": False,
            "acquired": False,
            "active": True,
            "generation": 0,
            "remaining_seconds": None,
        }
    return manager.snapshot()


def _egress_ready(snapshot: dict) -> bool:
    slots = snapshot.get("slots")
    if isinstance(slots, dict):
        manual = snapshot.get("manual_slot")
        if manual and manual in slots:
            return slots[manual].get("state") != "open"
        return any(slot.get("state") != "open" for slot in slots.values())
    # 静态/直连在首个请求前尚无 lease，不应因此判死配置。
    return bool(snapshot.get("active") or not snapshot.get("acquired"))


async def _health_payload(request: Request) -> dict:
    settings: Settings = request.app.state.settings
    database = request.app.state.database
    database_health = await database.health()
    controls = await database.get_controls()
    probes = await database.latest_protocol_probes()
    operation = await database.operation_health()
    proxy = _proxy_snapshot(request.app.state.service)
    now = datetime.now(timezone.utc)
    dated_probes = [
        probe for probe in probes
        if _parse_time(probe.get("created_at")) is not None
    ]
    freshest_probe = max(
        dated_probes,
        key=lambda probe: _parse_time(probe.get("created_at")),
        default=None,
    )
    probe_age = None
    if freshest_probe is not None:
        probe_age = max(
            0.0,
            (now - _parse_time(freshest_probe["created_at"])).total_seconds(),
        )
    chapter_probe = next(
        (probe for probe in dated_probes
         if probe.get("endpoint") == "chapter/get_cpt_ifm"),
        None,
    )
    web_probe = next(
        (probe for probe in dated_probes
         if probe.get("endpoint") == "web/chapter"),
        None,
    )
    app_probes = [
        probe for probe in dated_probes
        if probe.get("endpoint") != "web/chapter"
    ]
    app_freshest_probe = max(
        app_probes,
        key=lambda probe: _parse_time(probe.get("created_at")),
        default=None,
    )
    app_probe_age = None
    if app_freshest_probe is not None:
        app_probe_age = max(
            0.0,
            (now - _parse_time(
                app_freshest_probe["created_at"])).total_seconds(),
        )
    web_probe_age = None
    if web_probe is not None and _parse_time(web_probe.get("created_at")):
        web_probe_age = max(
            0.0,
            (now - _parse_time(web_probe["created_at"])).total_seconds(),
        )
    strict_protocol_ok = bool(
        app_probes
        and all(probe.get("ok") for probe in app_probes)
        and chapter_probe is not None
        and app_probe_age is not None
        and app_probe_age <= settings.readiness_probe_max_age_seconds
    )
    web_route_ok = False
    web_route_slot = None
    if (getattr(settings, "readiness_allow_web_fallback", False)
            and settings.web_fallback_enabled):
        # A probe is only meaningful when all App and Web steps belong to the
        # same sticky identity/egress slot.  Never combine a healthy search
        # from one slot with a Web chapter from another slot.
        for slot_id in {
                str(probe.get("slot_id", "")) for probe in dated_probes}:
            slot_probes = [
                probe for probe in dated_probes
                if str(probe.get("slot_id", "")) == slot_id
            ]
            slot_chapter = next(
                (probe for probe in slot_probes
                 if probe.get("endpoint") == "chapter/get_cpt_ifm"),
                None,
            )
            slot_web = next(
                (probe for probe in slot_probes
                 if probe.get("endpoint") == "web/chapter"),
                None,
            )
            slot_other = [
                probe for probe in slot_probes
                if probe.get("endpoint") != "chapter/get_cpt_ifm"
                and probe.get("endpoint") != "web/chapter"
            ]
            required_app_endpoints = {
                "search/books",
                "chapter/catalog",
                "chapter/get_chapter_cmd",
            }
            slot_other_endpoints = {
                str(probe.get("endpoint", "")) for probe in slot_other
            }
            slot_web_age = None
            if slot_web is not None and _parse_time(
                    slot_web.get("created_at")):
                slot_web_age = max(
                    0.0,
                    (now - _parse_time(slot_web["created_at"])).total_seconds(),
                )
            if (
                    slot_web is not None
                    and slot_web.get("ok")
                    and slot_web_age is not None
                    and slot_web_age <= settings.readiness_probe_max_age_seconds
                    and slot_chapter is not None
                    and str(slot_chapter.get("code", "")) == "310017"
                    and required_app_endpoints <= slot_other_endpoints
                    and all(probe.get("ok") for probe in slot_other)
            ):
                web_route_ok = True
                web_route_slot = slot_id
                web_probe_age = slot_web_age
                break
    protocol_ok = (
        not settings.readiness_require_protocol_probe
        or strict_protocol_ok
        or web_route_ok
    )
    checks = {
        "database": bool(database_health["ok"]),
        "queue": bool(request.app.state.queue.running),
        "not_paused": not bool(controls.get("all", {}).get("paused")),
        "egress": _egress_ready(proxy),
        "protocol_probe": protocol_ok,
        "failure_streak": (
            int(operation["failure_streak"])
            < settings.readiness_failure_streak_threshold
        ),
    }
    scheduler = request.app.state.scheduler
    bootstrap_result = request.app.state.credential_bootstrap_result
    return {
        "status": "ready" if all(checks.values()) else "not_ready",
        "ready": all(checks.values()),
        "checks": checks,
        "database": {
            "ok": database_health["ok"],
            "journal_mode": database_health["journal_mode"],
        },
        "queue": {
            "running": request.app.state.queue.running,
            "pending": request.app.state.queue.pending_count,
            "workers": settings.queue_workers,
        },
        "scheduler": {
            "enabled": settings.scheduler_enabled,
            "running": bool(scheduler and scheduler.running),
        },
        "controls": controls,
        "operation": operation,
        "protocol": {
            "profile": settings.protocol.name,
            "app_version": settings.app_version,
            "required": settings.readiness_require_protocol_probe,
            "route": (
                "disabled" if not settings.readiness_require_protocol_probe
                else "app" if strict_protocol_ok
                else "web_fallback" if web_route_ok
                else "unverified"
            ),
            "app_gate_ok": strict_protocol_ok,
            "web_fallback_slot": web_route_slot,
            "web_fallback": {
                "enabled": settings.web_fallback_enabled,
                "readiness_allowed": getattr(
                    settings, "readiness_allow_web_fallback", False),
                "probe_ok": bool(web_probe and web_probe.get("ok")),
                "probe": web_probe,
                "age_seconds": (
                    round(web_probe_age, 1)
                    if web_probe_age is not None else None
                ),
            },
            "app_gate_probe": chapter_probe,
            "max_age_seconds": settings.readiness_probe_max_age_seconds,
            "freshest_success": freshest_probe,
            "age_seconds": round(probe_age, 1) if probe_age is not None else None,
            "app_gate_age_seconds": (
                round(app_probe_age, 1)
                if app_probe_age is not None else None
            ),
            "latest": probes,
        },
        "credentials_configured": settings.credentials_configured(),
        "guest_bootstrap": {
            "enabled": settings.guest_bootstrap_enabled,
            "created": bool(bootstrap_result and bootstrap_result.created),
            "source": bootstrap_result.source if bootstrap_result else None,
            "runtime_refresh": bool(
                request.app.state.credential_bootstrap),
        },
        "proxy": proxy,
    }


def _public_config(settings: Settings, service) -> dict:
    proxy = _proxy_snapshot(service)
    return {
        "protocol": {
            "profile": settings.protocol.name,
            "app_version": settings.app_version,
            "transport_profile": settings.protocol.transport_profile,
        },
        "scheduler": {
            "enabled": settings.scheduler_enabled,
            "timezone": settings.scheduler_timezone,
            "sync_interval_minutes": settings.sync_interval_minutes,
        },
        "queue": {"workers": settings.queue_workers},
        "auto_download": {
            "enabled": settings.auto_download_enabled,
            "batch_size": settings.auto_download_batch_size,
            "free_only": True,
        },
        "web_fallback": {
            "enabled": settings.web_fallback_enabled,
            "min_interval_seconds": settings.web_min_interval_seconds,
            "scope": "free_only_after_app_310017",
            "readiness_allowed": settings.readiness_allow_web_fallback,
        },
        "egress": {
            "mode": settings.egress_mode,
            "provider": proxy.get("provider"),
            "fallback_provider": settings.fallback_proxy_provider or None,
            "failure_threshold": settings.egress_failure_threshold,
            "risk_threshold": settings.egress_risk_threshold,
            "cooldown_seconds": settings.egress_cooldown_seconds,
        },
        "storage": {
            "database_path": str(settings.database_path),
            "output_dir": str(settings.output_dir),
            "archive_dir": str(
                settings.archive_dir
                or settings.database_path.parent / "archive"),
            "semantic_retention_days": settings.semantic_retention_days,
            "local_mirror_retention_days": (
                settings.archive_local_retention_days),
            "maintenance_interval_hours": (
                settings.archive_maintenance_interval_hours),
            "archive_spool_max_bytes": settings.archive_spool_max_bytes,
            "nas_mirror_configured": bool(
                getattr(service, "archive_manager", None)
                and service.archive_manager.remote_configured),
        },
    }


def create_app(settings: Settings | None = None,
               service_factory=CiweimaoService,
               credential_bootstrap_factory=(
                   GuestCredentialBootstrapper)) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        active_settings = settings or Settings.from_env()
        database = Database(active_settings.database_path)
        await database.initialize()
        service = service_factory(active_settings, database)
        credential_bootstrap = None
        credential_bootstrap_result = None
        if active_settings.guest_bootstrap_enabled:
            credential_bootstrap = credential_bootstrap_factory(
                active_settings)
            proxy_manager = getattr(service, "proxy_manager", None)
            if proxy_manager is not None and proxy_manager.dynamic:
                credential_bootstrap_result = CredentialBootstrapResult(
                    created=False,
                    source="deferred-until-first-use",
                )
            else:
                credential_bootstrap_result = (
                    await credential_bootstrap.ensure(
                        proxy_url=active_settings.http_proxy_url))
        if hasattr(service, "set_credential_bootstrap"):
            service.set_credential_bootstrap(credential_bootstrap)
        queue = PersistentTaskQueue(
            database,
            service.task_handlers,
            workers=active_settings.queue_workers,
        )
        if hasattr(service, "set_task_submitter"):
            service.set_task_submitter(queue.submit)
        await queue.start()
        if (active_settings.readiness_auto_probe_enabled
                and "protocol_probe" in service.task_handlers):
            probe_payload = ProtocolProbeRequest().model_dump(mode="json")
            await queue.submit(
                "protocol_probe",
                probe_payload,
                task_dedupe_key("startup_protocol_probe", probe_payload),
            )
        scheduler = None
        if active_settings.scheduler_enabled:
            scheduler = build_scheduler(active_settings, queue)
            scheduler.start()

        application.state.settings = active_settings
        application.state.credential_bootstrap = credential_bootstrap
        application.state.credential_bootstrap_result = (
            credential_bootstrap_result)
        application.state.database = database
        application.state.service = service
        application.state.queue = queue
        application.state.scheduler = scheduler
        try:
            yield
        finally:
            if scheduler is not None and scheduler.running:
                scheduler.shutdown(wait=False)
            await queue.stop()

    application = FastAPI(
        title="Ciweimao App Collector",
        version="2.0.0",
        description="刺猬猫游客态免费内容采集与运维控制面",
        lifespan=lifespan,
    )

    async def submit_task(request: Request, task_type: str,
                          payload: dict, *, key_type: str | None = None):
        return await request.app.state.queue.submit(
            task_type,
            payload,
            task_dedupe_key(key_type or task_type, payload),
        )

    @application.get("/health/live")
    async def health_live():
        return {"status": "alive"}

    @application.get("/health/ready")
    async def health_ready(request: Request):
        payload = await _health_payload(request)
        return JSONResponse(
            payload,
            status_code=(200 if payload["ready"] else 503),
        )

    @application.get("/health")
    async def health(request: Request):
        payload = await _health_payload(request)
        return JSONResponse(
            payload,
            status_code=(200 if payload["ready"] else 503),
        )

    @application.get("/api/overview")
    async def overview(request: Request):
        database = request.app.state.database
        service = request.app.state.service
        payload = await database.overview()
        payload.update({
            "controls": await database.get_controls(),
            "egress": _proxy_snapshot(service),
            "protocol_probes": await database.latest_protocol_probes(),
            "operation": await database.operation_health(),
        })
        archive = getattr(service, "archive_manager", None)
        if archive is not None:
            payload["archive"] = await archive.status()
        identity = getattr(service, "identity_store", None)
        if identity is not None:
            payload["identity"] = await identity.snapshot()
        return payload

    @application.get("/api/config")
    async def public_config(request: Request):
        return _public_config(
            request.app.state.settings,
            request.app.state.service,
        )

    @application.get("/api/books/search")
    async def search_books(
        request: Request,
        q: str = Query(min_length=1, max_length=200),
        max_pages: int = Query(default=1, ge=1, le=20),
        count: int = Query(default=10, ge=1, le=10),
    ):
        try:
            books = await request.app.state.service.search_books(
                q, max_pages=max_pages, count=count)
        except ConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=redact_error_text(exc),
            ) from exc
        return {"query": q, "count": len(books), "books": books}

    @application.get("/api/books")
    async def list_books(
        request: Request,
        q: str | None = Query(default=None, max_length=200),
        cursor: str | None = Query(default=None, max_length=500),
        limit: int = Query(default=50, ge=1, le=100),
    ):
        try:
            return await request.app.state.database.list_books(
                query=q, cursor=cursor, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @application.get("/api/books/{book_id}")
    async def get_book(book_id: str, request: Request):
        book = await request.app.state.database.get_book(book_id)
        if book is None:
            raise HTTPException(status_code=404, detail="书籍不存在")
        return book

    @application.post(
        "/api/books/{book_id}/download",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def download_book(
            book_id: str, payload: DirectBookDownloadRequest,
            request: Request):
        book = await request.app.state.database.get_book(book_id)
        if book is None:
            raise HTTPException(status_code=404, detail="书籍不存在")
        task_payload = DownloadBookRequest(
            book_id=book_id,
            book_name=book.get("book_name", ""),
            author_name=book.get("author_name", ""),
            source="control_plane",
            **payload.model_dump(mode="json"),
        ).model_dump(mode="json")
        return await request.app.state.queue.submit(
            "download_book", task_payload, f"download_book:{book_id}")

    @application.post(
        "/api/downloads/by-name", status_code=status.HTTP_202_ACCEPTED)
    async def download_by_name(payload: DownloadByNameRequest,
                               request: Request):
        task_payload = payload.model_dump(mode="json")
        return await submit_task(
            request, "download_by_name", task_payload)

    @application.get("/api/downloads")
    async def list_downloads(
            request: Request,
            limit: int = Query(default=100, ge=1, le=500)):
        items = await request.app.state.database.list_downloads(limit=limit)
        return {"count": len(items), "downloads": items}

    @application.get("/api/downloads/stats")
    async def download_stats(request: Request):
        return await request.app.state.database.get_download_stats()

    @application.get("/api/downloads/{download_id}/file")
    async def download_file(download_id: str, request: Request):
        item = await request.app.state.database.get_download(download_id)
        if item is None:
            raise HTTPException(status_code=404, detail="下载记录不存在")
        target = _safe_file(
            item["output_path"], request.app.state.settings.output_dir)
        return FileResponse(
            target,
            filename=target.name,
            media_type="text/plain; charset=utf-8",
        )

    @application.post(
        "/api/sync/rankings", status_code=status.HTTP_202_ACCEPTED)
    async def sync_rankings(
        request: Request,
        payload: SyncRankingsRequest | None = Body(default=None),
    ):
        model = payload or SyncRankingsRequest()
        return await submit_task(
            request, "sync_rankings", model.model_dump(mode="json"))

    @application.post(
        "/api/sync/new-books", status_code=status.HTTP_202_ACCEPTED)
    async def sync_new_books(
        request: Request,
        payload: SyncNewBooksRequest | None = Body(default=None),
    ):
        model = payload or SyncNewBooksRequest()
        return await submit_task(
            request, "sync_new_books", model.model_dump(mode="json"))

    @application.post(
        "/api/sync/all", status_code=status.HTTP_202_ACCEPTED)
    async def sync_all(
        request: Request,
        payload: SyncAllRequest | None = Body(default=None),
    ):
        model = payload or SyncAllRequest()
        return await submit_task(
            request, "sync_all", model.model_dump(mode="json"))

    @application.get("/api/tasks")
    async def list_tasks(
        request: Request,
        task_status: TaskStatus | None = Query(default=None, alias="status"),
        task_type: str | None = Query(default=None, max_length=64),
        limit: int = Query(default=100, ge=1, le=500),
    ):
        tasks = await request.app.state.database.list_tasks(
            status=task_status, task_type=task_type, limit=limit)
        return {"count": len(tasks), "tasks": tasks}

    @application.get("/api/tasks/{task_id}")
    async def get_task(task_id: str, request: Request):
        task = await request.app.state.database.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return task

    @application.post("/api/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str, request: Request):
        cancelled = await request.app.state.queue.cancel(task_id)
        if not cancelled:
            task = await request.app.state.database.get_task(task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="任务不存在")
            raise HTTPException(
                status_code=409,
                detail=f"只有 queued/deferred 任务可取消，当前状态: {task['status']}",
            )
        await request.app.state.database.record_event(
            event_type="task_cancelled", component="control_plane",
            task_id=task_id, message="task cancelled")
        return {"id": task_id, "status": "cancelled"}

    @application.post(
        "/api/tasks/{task_id}/retry",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def retry_task(task_id: str, request: Request):
        try:
            return await request.app.state.queue.retry(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @application.get("/api/events")
    async def list_events(
        request: Request,
        category: str | None = Query(default=None, max_length=64),
        task_id: str | None = Query(default=None, max_length=64),
        limit: int = Query(default=100, ge=1, le=500),
    ):
        events = await request.app.state.database.list_events(
            category=category, task_id=task_id, limit=limit)
        return {"count": len(events), "events": events}

    @application.get("/api/controls")
    async def get_controls(request: Request):
        return await request.app.state.database.get_controls()

    @application.post("/api/controls/{scope}/pause")
    async def pause(scope: str, payload: ControlRequest, request: Request):
        if scope not in CONTROL_SCOPES:
            raise HTTPException(status_code=404, detail="未知控制范围")
        return await request.app.state.database.set_control(
            scope, paused=True, reason=payload.reason)

    @application.post("/api/controls/{scope}/resume")
    async def resume(scope: str, payload: ControlRequest, request: Request):
        if scope not in CONTROL_SCOPES:
            raise HTTPException(status_code=404, detail="未知控制范围")
        return await request.app.state.database.set_control(
            scope, paused=False, reason=payload.reason)

    @application.get("/api/rankings/latest")
    async def latest_rankings(
        request: Request,
        source_key: str | None = Query(default=None, max_length=128),
    ):
        database = request.app.state.database
        if source_key:
            snapshot = await database.get_latest_snapshot(
                "ranking", source_key)
            if snapshot is None:
                raise HTTPException(status_code=404, detail="暂无榜单快照")
            return snapshot
        snapshots = await database.get_latest_snapshots("ranking")
        return {"count": len(snapshots), "snapshots": snapshots}

    @application.get("/api/rankings/{source_key}/history")
    async def ranking_history(
        source_key: str,
        request: Request,
        book_id: str | None = Query(default=None, max_length=64),
        since: str | None = Query(default=None, max_length=64),
        until: str | None = Query(default=None, max_length=64),
        limit: int = Query(default=500, ge=1, le=5000),
    ):
        items = await request.app.state.database.get_ranking_history(
            source_key, book_id=book_id, since=since,
            until=until, limit=limit)
        return {"count": len(items), "history": items}

    @application.get("/api/new-books/latest")
    async def latest_new_books(request: Request):
        snapshot = await request.app.state.database.get_latest_snapshot(
            "new_books", "newtime")
        if snapshot is None:
            raise HTTPException(status_code=404, detail="暂无新书快照")
        return snapshot

    @application.get("/api/protocol/probes")
    async def protocol_probes(request: Request):
        items = await request.app.state.database.latest_protocol_probes()
        return {"count": len(items), "probes": items}

    @application.post(
        "/api/egress/probe", status_code=status.HTTP_202_ACCEPTED)
    async def egress_probe(payload: ProtocolProbeRequest, request: Request):
        task_payload = payload.model_dump(mode="json")
        return await submit_task(
            request, "protocol_probe", task_payload,
            key_type="protocol_probe")

    @application.get("/api/egress")
    async def egress(request: Request):
        return _proxy_snapshot(request.app.state.service)

    @application.post(
        "/api/egress/mode", status_code=status.HTTP_202_ACCEPTED)
    async def egress_mode(payload: EgressModeRequest, request: Request):
        task_payload = payload.model_dump(mode="json")
        return await submit_task(request, "egress_mode", task_payload)

    @application.get("/api/identity")
    async def identity(request: Request):
        store = getattr(request.app.state.service, "identity_store", None)
        if store is None:
            raise HTTPException(status_code=501, detail="身份存储不可用")
        return await store.snapshot()

    @application.post(
        "/api/identity/{slot_id}/validate",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def identity_validate(slot_id: str, request: Request):
        if slot_id not in IDENTITY_SLOTS:
            raise HTTPException(status_code=404, detail="未知身份槽")
        payload = {"slot_id": slot_id, "force_new_proxy": False}
        return await submit_task(request, "identity_validate", payload)

    @application.post("/api/identity/{slot_id}/rotate/preview")
    async def identity_rotate_preview(slot_id: str, request: Request):
        if slot_id not in IDENTITY_SLOTS:
            raise HTTPException(status_code=404, detail="未知身份槽")
        confirmation = await request.app.state.database.create_confirmation(
            action="identity_rotate",
            target=slot_id,
            payload={"slot_id": slot_id},
            ttl_seconds=request.app.state.settings.confirmation_ttl_seconds,
        )
        return {
            "warning": "将删除该出口现有游客身份并生成新设备 UUID",
            "slot_id": slot_id,
            **confirmation,
        }

    @application.post(
        "/api/identity/{slot_id}/rotate",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def identity_rotate(
            slot_id: str, payload: IdentityRotateRequest,
            request: Request):
        if slot_id not in IDENTITY_SLOTS:
            raise HTTPException(status_code=404, detail="未知身份槽")
        valid = await request.app.state.database.consume_confirmation(
            payload.confirmation_token,
            action="identity_rotate",
            target=slot_id,
            payload={"slot_id": slot_id},
        )
        if not valid:
            raise HTTPException(
                status_code=409, detail="确认令牌无效、过期或已使用")
        return await submit_task(
            request, "identity_rotate", {"slot_id": slot_id})

    @application.get("/api/storage")
    async def storage_status(request: Request):
        manager = getattr(request.app.state.service, "archive_manager", None)
        if manager is None:
            raise HTTPException(status_code=501, detail="归档管理不可用")
        return await manager.status()

    @application.get("/api/storage/archives")
    async def archives(
            request: Request,
            limit: int = Query(default=200, ge=1, le=1000)):
        items = await request.app.state.database.list_archives(limit=limit)
        return {"count": len(items), "archives": items}

    @application.get("/api/storage/archives/{archive_id}/file")
    async def archive_file(archive_id: str, request: Request):
        archive = await request.app.state.database.get_archive(archive_id)
        if archive is None:
            raise HTTPException(status_code=404, detail="归档不存在")
        manager = request.app.state.service.archive_manager
        try:
            path = await manager.ensure_local(archive)
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=redact_error_text(exc)) from exc
        target = _safe_file(path, manager.root)
        return FileResponse(
            target, filename=target.name,
            media_type="application/octet-stream")

    @application.post(
        "/api/storage/backup", status_code=status.HTTP_202_ACCEPTED)
    async def storage_backup(request: Request):
        return await submit_task(
            request, "archive_backup", {"label": "manual"})

    @application.post(
        "/api/storage/archive-pending",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def archive_pending(request: Request):
        return await submit_task(request, "archive_pending", {})

    @application.post(
        "/api/storage/retry-mirrors",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def retry_mirrors(request: Request):
        return await submit_task(request, "archive_retry_mirrors", {})

    @application.post("/api/storage/maintenance/preview")
    async def maintenance_preview(
            payload: ArchivePreviewRequest, request: Request):
        manager = request.app.state.service.archive_manager
        preview = await manager.preview_maintenance()
        action_payload = {"compact": payload.compact}
        confirmation = await request.app.state.database.create_confirmation(
            action="archive_maintenance",
            target="database",
            payload=action_payload,
            ttl_seconds=request.app.state.settings.confirmation_ttl_seconds,
        )
        return {**preview, "requested": action_payload, **confirmation}

    @application.post(
        "/api/storage/maintenance/run",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def maintenance_run(
            payload: ArchiveMaintenanceRequest, request: Request):
        task_payload = {"compact": payload.compact}
        valid = await request.app.state.database.consume_confirmation(
            payload.confirmation_token,
            action="archive_maintenance",
            target="database",
            payload=task_payload,
        )
        if not valid:
            raise HTTPException(
                status_code=409, detail="确认令牌无效、过期或已使用")
        return await submit_task(
            request, "archive_maintenance", task_payload)

    @application.get("/api/scheduler/jobs")
    async def scheduler_jobs(request: Request):
        scheduler = request.app.state.scheduler
        if scheduler is None:
            return {"enabled": False, "jobs": []}
        jobs = [{
            "id": job.id,
            "name": job.name,
            "next_run_time": (
                job.next_run_time.isoformat()
                if job.next_run_time else None
            ),
            "trigger": str(job.trigger),
        } for job in scheduler.get_jobs()]
        return {"enabled": True, "jobs": jobs}

    frontend_dist = (PROJECT_ROOT / "frontend" / "dist").resolve()

    @application.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith(("api/", "health/")):
            raise HTTPException(status_code=404, detail="Not Found")
        index = frontend_dist / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="SPA 尚未构建")
        candidate = (frontend_dist / full_path).resolve()
        try:
            candidate.relative_to(frontend_dist)
        except ValueError:
            candidate = index
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)

    return application


app = create_app()
