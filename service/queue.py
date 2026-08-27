"""SQLite 持久化任务状态 + asyncio 内存唤醒队列。"""

import asyncio
import logging
from typing import Awaitable, Callable

from .database import Database
from .failures import EgressUnavailableError, classify_failure
from .proxy import redact_error_text


TaskHandler = Callable[[dict, str], Awaitable[dict | None]]
logger = logging.getLogger(__name__)


class PersistentTaskQueue:
    def __init__(self, database: Database,
                 handlers: dict[str, TaskHandler], workers: int = 2,
                 poll_interval: float = 5):
        self.database = database
        self.handlers = dict(handlers)
        self.worker_count = max(1, int(workers))
        self.poll_interval = max(0.01, float(poll_interval))
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._poller: asyncio.Task | None = None
        self._queued_ids: set[str] = set()
        self._started = False

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    @property
    def running(self) -> bool:
        return self._started

    async def start(self) -> None:
        if self._started:
            return
        await self.database.reset_running_tasks()
        for task_id in await self.database.list_queued_task_ids():
            await self._enqueue(task_id)
        self._started = True
        self._workers = [asyncio.create_task(
            self._worker(index),
            name=f"ciweimao-task-worker-{index}",
        ) for index in range(1, self.worker_count + 1)]
        self._poller = asyncio.create_task(
            self._poll_due_tasks(), name="ciweimao-deferred-task-poller")

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        if self._poller is not None:
            self._poller.cancel()
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(
            *(self._workers + (
                [self._poller] if self._poller is not None else [])),
            return_exceptions=True,
        )
        self._poller = None
        self._workers.clear()
        self._queued_ids.clear()

    async def _enqueue(self, task_id: str) -> None:
        task_id = str(task_id)
        if task_id in self._queued_ids:
            return
        self._queued_ids.add(task_id)
        await self._queue.put(task_id)

    async def _poll_due_tasks(self) -> None:
        while True:
            await asyncio.sleep(self.poll_interval)
            for task_id in await self.database.list_queued_task_ids():
                await self._enqueue(task_id)

    async def submit(self, task_type: str, payload: dict,
                     dedupe_key: str | None = None) -> dict:
        task, created = await self.database.create_task(
            task_type, payload, dedupe_key=dedupe_key)
        if created:
            await self._enqueue(task["id"])
        task["deduplicated"] = not created
        return task

    async def cancel(self, task_id: str) -> bool:
        return await self.database.cancel_task(task_id)

    async def retry(self, task_id: str) -> dict:
        task, created = await self.database.retry_task(task_id)
        if created:
            await self._enqueue(task["id"])
        task["deduplicated"] = not created
        return task

    async def join(self) -> None:
        await self._queue.join()

    async def _worker(self, index: int) -> None:
        del index
        while True:
            task_id = await self._queue.get()
            self._queued_ids.discard(task_id)
            claimed = False
            try:
                if await self.database.is_paused("all"):
                    await asyncio.sleep(1)
                    await self._enqueue(task_id)
                    continue
                task = await self.database.claim_task(task_id)
                if task is None:
                    continue
                claimed = True
                handler = self.handlers.get(task["task_type"])
                if handler is None:
                    raise RuntimeError(
                        f"未注册任务处理器: {task['task_type']}")
                result = await handler(task["payload"], task_id)
                await self.database.complete_task(task_id, result or {})
                await self.database.record_event(
                    event_type="task_succeeded",
                    component=task["task_type"],
                    task_id=task_id,
                    message="task completed",
                )
            except asyncio.CancelledError:
                if claimed:
                    await asyncio.shield(
                        self.database.requeue_task(task_id))
                raise
            except Exception as exc:
                if claimed:
                    safe_error = redact_error_text(exc)
                    info = classify_failure(exc)
                    if isinstance(exc, EgressUnavailableError):
                        await self.database.defer_task(
                            task_id,
                            error=safe_error,
                            category=info.category.value,
                            code=info.code,
                            next_retry_at=exc.retry_after,
                        )
                    else:
                        await self.database.fail_task(
                            task_id,
                            safe_error,
                            category=info.category.value,
                            code=info.code,
                        )
                    await self.database.record_event(
                        event_type=(
                            "task_deferred"
                            if isinstance(exc, EgressUnavailableError)
                            else "task_failed"),
                        component="queue",
                        category=info.category.value,
                        code=info.code,
                        task_id=task_id,
                        message=safe_error,
                    )
                else:
                    safe_error = redact_error_text(exc)
                logger.error(
                    "任务执行失败: task_id=%s error=%s",
                    task_id,
                    safe_error,
                )
            finally:
                self._queue.task_done()
