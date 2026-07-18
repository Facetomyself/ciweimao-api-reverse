"""FastAPI 入口。"""

from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException, Query, Request, status

from .config import ConfigurationError, Settings
from .core import CiweimaoService
from .credentials import (
    CredentialBootstrapResult,
    GuestCredentialBootstrapper,
)
from .database import Database
from .queue import PersistentTaskQueue
from .proxy import redact_error_text
from .scheduler import build_scheduler, task_dedupe_key
from .schemas import (
    DownloadByNameRequest,
    SyncAllRequest,
    SyncNewBooksRequest,
    SyncRankingsRequest,
    TaskStatus,
)


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
        version="1.0.0",
        description="刺猬猫 App 搜索、榜单、新书与免费章节下载服务",
        lifespan=lifespan,
    )

    @application.get("/health")
    async def health(request: Request):
        database_health = await request.app.state.database.health()
        scheduler = request.app.state.scheduler
        settings_ = request.app.state.settings
        return {
            "status": "ok",
            "database": {
                "ok": database_health["ok"],
                "journal_mode": database_health["journal_mode"],
            },
            "queue": {
                "running": request.app.state.queue.running,
                "pending": request.app.state.queue.pending_count,
                "workers": settings_.queue_workers,
            },
            "scheduler": {
                "enabled": settings_.scheduler_enabled,
                "running": bool(scheduler and scheduler.running),
            },
            "credentials_configured": settings_.credentials_configured(),
            "guest_bootstrap": {
                "enabled": settings_.guest_bootstrap_enabled,
                "created": bool(
                    request.app.state.credential_bootstrap_result
                    and request.app.state.credential_bootstrap_result.created
                ),
                "source": (
                    request.app.state.credential_bootstrap_result.source
                    if request.app.state.credential_bootstrap_result
                    else None
                ),
                "runtime_refresh": bool(
                    request.app.state.credential_bootstrap),
            },
            "proxy": (
                request.app.state.service.proxy_manager.snapshot()
                if hasattr(request.app.state.service, "proxy_manager")
                else {
                    "provider": "unmanaged",
                    "dynamic": False,
                    "acquired": False,
                    "active": False,
                    "generation": 0,
                    "remaining_seconds": None,
                }
            ),
        }

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

    @application.post(
        "/api/downloads/by-name", status_code=status.HTTP_202_ACCEPTED)
    async def download_by_name(payload: DownloadByNameRequest,
                               request: Request):
        task_payload = payload.model_dump(mode="json")
        dedupe_key = task_dedupe_key("download_by_name", task_payload)
        return await request.app.state.queue.submit(
            "download_by_name", task_payload, dedupe_key)

    @application.get("/api/downloads/stats")
    async def download_stats(request: Request):
        return await request.app.state.database.get_download_stats()

    @application.post(
        "/api/sync/rankings", status_code=status.HTTP_202_ACCEPTED)
    async def sync_rankings(
        request: Request,
        payload: SyncRankingsRequest | None = Body(default=None),
    ):
        model = payload or SyncRankingsRequest()
        task_payload = model.model_dump(mode="json")
        return await request.app.state.queue.submit(
            "sync_rankings",
            task_payload,
            task_dedupe_key("sync_rankings", task_payload),
        )

    @application.post(
        "/api/sync/new-books", status_code=status.HTTP_202_ACCEPTED)
    async def sync_new_books(
        request: Request,
        payload: SyncNewBooksRequest | None = Body(default=None),
    ):
        model = payload or SyncNewBooksRequest()
        task_payload = model.model_dump(mode="json")
        return await request.app.state.queue.submit(
            "sync_new_books",
            task_payload,
            task_dedupe_key("sync_new_books", task_payload),
        )

    @application.post(
        "/api/sync/all", status_code=status.HTTP_202_ACCEPTED)
    async def sync_all(
        request: Request,
        payload: SyncAllRequest | None = Body(default=None),
    ):
        model = payload or SyncAllRequest()
        task_payload = model.model_dump(mode="json")
        return await request.app.state.queue.submit(
            "sync_all",
            task_payload,
            task_dedupe_key("sync_all", task_payload),
        )

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
                detail=f"只有 queued 任务可取消，当前状态: {task['status']}",
            )
        return {"id": task_id, "status": "cancelled"}

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

    @application.get("/api/new-books/latest")
    async def latest_new_books(request: Request):
        snapshot = await request.app.state.database.get_latest_snapshot(
            "new_books", "newtime")
        if snapshot is None:
            raise HTTPException(status_code=404, detail="暂无新书快照")
        return snapshot

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

    return application


app = create_app()
