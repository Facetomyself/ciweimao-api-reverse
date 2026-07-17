"""APScheduler 仅负责向持久化队列投递定时任务。"""

import hashlib
import json

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import Settings
from .queue import PersistentTaskQueue
from .schemas import SyncNewBooksRequest, SyncRankingsRequest


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
    ranking_payload = SyncRankingsRequest().model_dump(mode="json")
    new_books_payload = SyncNewBooksRequest().model_dump(mode="json")

    async def submit_rankings():
        await queue.submit(
            "sync_rankings",
            ranking_payload,
            task_dedupe_key("sync_rankings", ranking_payload),
        )

    async def submit_new_books():
        await queue.submit(
            "sync_new_books",
            new_books_payload,
            task_dedupe_key("sync_new_books", new_books_payload),
        )

    scheduler.add_job(
        submit_rankings,
        trigger="interval",
        minutes=settings.ranking_interval_minutes,
        id="sync-rankings",
        name="同步 App 榜单",
        replace_existing=True,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        submit_new_books,
        trigger="interval",
        minutes=settings.new_books_interval_minutes,
        id="sync-new-books",
        name="同步 App 新书",
        replace_existing=True,
        misfire_grace_time=60,
    )
    return scheduler
