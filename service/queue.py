"""SQLite 持久化任务状态 + asyncio 内存唤醒队列。"""

import asyncio
import logging
from typing import Awaitable, Callable

from .database import Database


TaskHandler = Callable[[dict, str], Awaitable[dict | None]]
logger = logging.getLogger(__name__)


class PersistentTaskQueue:
    def __init__(self, database: Database,
                 handlers: dict[str, TaskHandler], workers: int = 2):
        self.database = database
        self.handlers = dict(handlers)
        self.worker_count = max(1, int(workers))
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
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
            await self._queue.put(task_id)
        self._started = True
        self._workers = [asyncio.create_task(
            self._worker(index),
            name=f"ciweimao-task-worker-{index}",
        ) for index in range(1, self.worker_count + 1)]

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def submit(self, task_type: str, payload: dict,
                     dedupe_key: str | None = None) -> dict:
        task, created = await self.database.create_task(
            task_type, payload, dedupe_key=dedupe_key)
        if created:
            await self._queue.put(task["id"])
        task["deduplicated"] = not created
        return task

    async def cancel(self, task_id: str) -> bool:
        return await self.database.cancel_task(task_id)

    async def join(self) -> None:
        await self._queue.join()

    async def _worker(self, index: int) -> None:
        del index
        while True:
            task_id = await self._queue.get()
            claimed = False
            try:
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
            except asyncio.CancelledError:
                if claimed:
                    await asyncio.shield(
                        self.database.requeue_task(task_id))
                raise
            except Exception as exc:
                if claimed:
                    await self.database.fail_task(task_id, str(exc))
                logger.exception("任务执行失败: task_id=%s", task_id)
            finally:
                self._queue.task_done()
