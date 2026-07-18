"""APScheduler 仅负责向持久化队列投递定时任务。"""

import hashlib
import json

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import Settings
from .queue import PersistentTaskQueue
from .schemas import SyncAllRequest


def task_dedupe_key(task_type: str, payload: dict) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    suffix = hashlib.sha256(canonical).hexdigest()[:20]
    return f"{task_type}:{suffix}"


def build_scheduler(settings: Settings,
                    queue: PersistentTaskQueue) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(
        timezone=settings.scheduler_timezone,
        job_defaults={"coalesce": True, "max_instances": 1},
    )
    sync_payload = SyncAllRequest().model_dump(mode="json")

    async def submit_sync_all():
        await queue.submit(
            "sync_all",
            sync_payload,
            task_dedupe_key("sync_all", sync_payload),
        )

    scheduler.add_job(
        submit_sync_all,
        trigger="interval",
        minutes=settings.sync_interval_minutes,
        id="sync-all",
        name="同步 App 榜单与新书",
        replace_existing=True,
        misfire_grace_time=60,
    )
    return scheduler
