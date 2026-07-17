"""SQLite WAL 数据库与仓储接口。"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import asyncio
import json
from pathlib import Path
import uuid

import aiosqlite


TASK_STATUSES = {
    "queued", "running", "succeeded", "failed", "cancelled",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _json_dumps(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), default=str)


def _json_loads(value, default=None):
    if value is None or value == "":
        return default
    return json.loads(value)


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class Database:
    """每次操作使用短连接，依靠 WAL 与 busy timeout 协调并发。"""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()

    @asynccontextmanager
    async def connect(self):
        connection = await aiosqlite.connect(str(self.path))
        connection.row_factory = aiosqlite.Row
        await connection.execute("PRAGMA foreign_keys = ON")
        await connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        finally:
            close_task = asyncio.create_task(connection.close())
            try:
                await asyncio.shield(close_task)
            except asyncio.CancelledError:
                await close_task
                raise

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connect() as connection:
            await connection.execute("PRAGMA journal_mode = WAL")
            await connection.execute("PRAGMA synchronous = NORMAL")
            await connection.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    dedupe_key TEXT,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT NOT NULL,
                    CHECK (status IN (
                        'queued', 'running', 'succeeded',
                        'failed', 'cancelled'
                    ))
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_status_created
                    ON tasks(status, created_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_active_dedupe
                    ON tasks(dedupe_key)
                    WHERE dedupe_key IS NOT NULL
                      AND status IN ('queued', 'running');

                CREATE TABLE IF NOT EXISTS books (
                    book_id TEXT PRIMARY KEY,
                    book_name TEXT NOT NULL DEFAULT '',
                    author_name TEXT NOT NULL DEFAULT '',
                    cover TEXT NOT NULL DEFAULT '',
                    is_paid INTEGER,
                    total_word_count INTEGER NOT NULL DEFAULT 0,
                    raw_json TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_books_name
                    ON books(book_name);

                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    item_count INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_snapshots_latest
                    ON snapshots(kind, source_key, captured_at DESC);

                CREATE TABLE IF NOT EXISTS observations (
                    snapshot_id TEXT NOT NULL,
                    book_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    observed_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    PRIMARY KEY (snapshot_id, book_id),
                    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (book_id) REFERENCES books(book_id)
                );
                CREATE INDEX IF NOT EXISTS idx_observations_book
                    ON observations(book_id, observed_at DESC);

                CREATE TABLE IF NOT EXISTS downloads (
                    id TEXT PRIMARY KEY,
                    task_id TEXT UNIQUE,
                    query TEXT NOT NULL,
                    book_id TEXT NOT NULL,
                    book_name TEXT NOT NULL,
                    output_format TEXT NOT NULL,
                    output_path TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(id),
                    FOREIGN KEY (book_id) REFERENCES books(book_id)
                );
                CREATE INDEX IF NOT EXISTS idx_downloads_book
                    ON downloads(book_id, created_at DESC);

                PRAGMA user_version = 1;
            """)
            await connection.commit()

    async def health(self) -> dict:
        async with self.connect() as connection:
            cursor = await connection.execute("PRAGMA journal_mode")
            row = await cursor.fetchone()
            await cursor.close()
            await connection.execute("SELECT 1")
        return {
            "ok": True,
            "path": str(self.path),
            "journal_mode": str(row[0]).lower() if row else "unknown",
        }

    @staticmethod
    def _task_from_row(row) -> dict | None:
        if row is None:
            return None
        task = dict(row)
        task["payload"] = _json_loads(task.pop("payload_json"), {})
        task["result"] = _json_loads(task.pop("result_json"), None)
        return task

    async def create_task(self, task_type: str, payload: dict,
                          dedupe_key: str | None = None) -> tuple[dict, bool]:
        task_id = uuid.uuid4().hex
        now = utc_now()
        async with self.connect() as connection:
            try:
                await connection.execute("""
                    INSERT INTO tasks (
                        id, task_type, payload_json, dedupe_key, status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'queued', ?, ?)
                """, (
                    task_id, task_type, _json_dumps(payload),
                    dedupe_key, now, now,
                ))
                await connection.commit()
                cursor = await connection.execute(
                    "SELECT * FROM tasks WHERE id = ?", (task_id,))
                row = await cursor.fetchone()
                await cursor.close()
                return self._task_from_row(row), True
            except aiosqlite.IntegrityError:
                await connection.rollback()
                if dedupe_key is None:
                    raise
                cursor = await connection.execute("""
                    SELECT * FROM tasks
                    WHERE dedupe_key = ?
                      AND status IN ('queued', 'running')
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (dedupe_key,))
                row = await cursor.fetchone()
                await cursor.close()
                if row is None:
                    raise
                return self._task_from_row(row), False

    async def get_task(self, task_id: str) -> dict | None:
        async with self.connect() as connection:
            cursor = await connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = await cursor.fetchone()
            await cursor.close()
        return self._task_from_row(row)

    async def list_tasks(self, status: str | None = None,
                         task_type: str | None = None,
                         limit: int = 100) -> list[dict]:
        clauses = []
        params = []
        if status:
            if status not in TASK_STATUSES:
                raise ValueError(f"未知任务状态: {status}")
            clauses.append("status = ?")
            params.append(status)
        if task_type:
            clauses.append("task_type = ?")
            params.append(task_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        async with self.connect() as connection:
            cursor = await connection.execute(f"""
                SELECT * FROM tasks
                {where}
                ORDER BY created_at DESC
                LIMIT ?
            """, params)
            rows = await cursor.fetchall()
            await cursor.close()
        return [self._task_from_row(row) for row in rows]

    async def reset_running_tasks(self) -> int:
        now = utc_now()
        async with self.connect() as connection:
            cursor = await connection.execute("""
                UPDATE tasks
                SET status = 'queued', started_at = NULL,
                    finished_at = NULL, error = NULL, updated_at = ?
                WHERE status = 'running'
            """, (now,))
            await connection.commit()
            return cursor.rowcount

    async def list_queued_task_ids(self) -> list[str]:
        async with self.connect() as connection:
            cursor = await connection.execute("""
                SELECT id FROM tasks
                WHERE status = 'queued'
                ORDER BY created_at ASC
            """)
            rows = await cursor.fetchall()
            await cursor.close()
        return [str(row["id"]) for row in rows]

    async def claim_task(self, task_id: str) -> dict | None:
        now = utc_now()
        async with self.connect() as connection:
            cursor = await connection.execute("""
                UPDATE tasks
                SET status = 'running', started_at = ?, finished_at = NULL,
                    attempts = attempts + 1, error = NULL, updated_at = ?
                WHERE id = ? AND status = 'queued'
            """, (now, now, task_id))
            if cursor.rowcount != 1:
                await connection.rollback()
                return None
            await connection.commit()
            cursor = await connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = await cursor.fetchone()
            await cursor.close()
        return self._task_from_row(row)

    async def complete_task(self, task_id: str, result: dict) -> None:
        now = utc_now()
        async with self.connect() as connection:
            await connection.execute("""
                UPDATE tasks
                SET status = 'succeeded', result_json = ?, error = NULL,
                    finished_at = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
            """, (_json_dumps(result), now, now, task_id))
            await connection.commit()

    async def fail_task(self, task_id: str, error: str) -> None:
        now = utc_now()
        async with self.connect() as connection:
            await connection.execute("""
                UPDATE tasks
                SET status = 'failed', error = ?, finished_at = ?,
                    updated_at = ?
                WHERE id = ? AND status = 'running'
            """, (str(error)[:4000], now, now, task_id))
            await connection.commit()

    async def requeue_task(self, task_id: str) -> None:
        now = utc_now()
        async with self.connect() as connection:
            await connection.execute("""
                UPDATE tasks
                SET status = 'queued', started_at = NULL,
                    finished_at = NULL, updated_at = ?
                WHERE id = ? AND status = 'running'
            """, (now, task_id))
            await connection.commit()

    async def cancel_task(self, task_id: str) -> bool:
        now = utc_now()
        async with self.connect() as connection:
            cursor = await connection.execute("""
                UPDATE tasks
                SET status = 'cancelled', finished_at = ?, updated_at = ?
                WHERE id = ? AND status = 'queued'
            """, (now, now, task_id))
            await connection.commit()
            return cursor.rowcount == 1

    @staticmethod
    def _normalize_book(book: dict, observed_at: str) -> tuple:
        raw = dict(book.get("book_info", book) or {})
        book_id = str(raw.get("book_id", "")).strip()
        if not book_id:
            return ()
        is_paid_raw = raw.get("is_paid")
        is_paid = (None if is_paid_raw in (None, "")
                   else int(str(is_paid_raw) == "1"))
        return (
            book_id,
            str(raw.get("book_name", "")),
            str(raw.get("author_name", "")),
            str(raw.get("cover", raw.get("cover_url", ""))),
            is_paid,
            _as_int(raw.get("total_word_count", 0)),
            _json_dumps(raw),
            observed_at,
            observed_at,
            observed_at,
        )

    async def _upsert_books(self, connection, books: list[dict],
                            observed_at: str) -> list[dict]:
        normalized = []
        valid_books = []
        seen_ids = set()
        for book in books:
            row = self._normalize_book(book, observed_at)
            if row and row[0] not in seen_ids:
                seen_ids.add(row[0])
                normalized.append(row)
                valid_books.append(dict(book.get("book_info", book) or {}))
        if normalized:
            await connection.executemany("""
                INSERT INTO books (
                    book_id, book_name, author_name, cover, is_paid,
                    total_word_count, raw_json, first_seen_at,
                    last_seen_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    book_name = CASE
                        WHEN excluded.book_name <> ''
                        THEN excluded.book_name ELSE books.book_name END,
                    author_name = CASE
                        WHEN excluded.author_name <> ''
                        THEN excluded.author_name ELSE books.author_name END,
                    cover = CASE
                        WHEN excluded.cover <> ''
                        THEN excluded.cover ELSE books.cover END,
                    is_paid = COALESCE(excluded.is_paid, books.is_paid),
                    total_word_count = excluded.total_word_count,
                    raw_json = excluded.raw_json,
                    last_seen_at = excluded.last_seen_at,
                    updated_at = excluded.updated_at
            """, normalized)
        return valid_books

    async def upsert_books(self, books: list[dict]) -> int:
        now = utc_now()
        async with self.connect() as connection:
            valid = await self._upsert_books(connection, books, now)
            await connection.commit()
        return len(valid)

    async def create_snapshot(self, kind: str, source_key: str,
                              books: list[dict],
                              metadata: dict | None = None) -> dict:
        snapshot_id = uuid.uuid4().hex
        captured_at = utc_now()
        async with self.connect() as connection:
            valid_books = await self._upsert_books(
                connection, books, captured_at)
            await connection.execute("""
                INSERT INTO snapshots (
                    id, kind, source_key, captured_at,
                    item_count, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                snapshot_id, kind, source_key, captured_at,
                len(valid_books), _json_dumps(metadata or {}),
            ))
            observations = [(
                snapshot_id,
                str(book.get("book_id")),
                position,
                captured_at,
                _json_dumps(book),
            ) for position, book in enumerate(valid_books, start=1)]
            if observations:
                await connection.executemany("""
                    INSERT INTO observations (
                        snapshot_id, book_id, position,
                        observed_at, raw_json
                    ) VALUES (?, ?, ?, ?, ?)
                """, observations)
            await connection.commit()
        return {
            "id": snapshot_id,
            "kind": kind,
            "source_key": source_key,
            "captured_at": captured_at,
            "item_count": len(valid_books),
            "metadata": metadata or {},
        }

    async def _snapshot_items(self, connection,
                              snapshot_id: str) -> list[dict]:
        cursor = await connection.execute("""
            SELECT o.position, o.observed_at, o.raw_json,
                   b.book_id, b.book_name, b.author_name, b.cover,
                   b.is_paid, b.total_word_count
            FROM observations AS o
            JOIN books AS b ON b.book_id = o.book_id
            WHERE o.snapshot_id = ?
            ORDER BY o.position ASC
        """, (snapshot_id,))
        rows = await cursor.fetchall()
        await cursor.close()
        return [{
            "position": row["position"],
            "observed_at": row["observed_at"],
            "book_id": row["book_id"],
            "book_name": row["book_name"],
            "author_name": row["author_name"],
            "cover": row["cover"],
            "is_paid": row["is_paid"],
            "total_word_count": row["total_word_count"],
            "raw": _json_loads(row["raw_json"], {}),
        } for row in rows]

    async def get_latest_snapshot(self, kind: str,
                                  source_key: str) -> dict | None:
        async with self.connect() as connection:
            cursor = await connection.execute("""
                SELECT * FROM snapshots
                WHERE kind = ? AND source_key = ?
                ORDER BY captured_at DESC
                LIMIT 1
            """, (kind, source_key))
            row = await cursor.fetchone()
            await cursor.close()
            if row is None:
                return None
            items = await self._snapshot_items(connection, row["id"])
        return {
            "id": row["id"],
            "kind": row["kind"],
            "source_key": row["source_key"],
            "captured_at": row["captured_at"],
            "item_count": row["item_count"],
            "metadata": _json_loads(row["metadata_json"], {}),
            "items": items,
        }

    async def get_latest_snapshots(self, kind: str) -> list[dict]:
        async with self.connect() as connection:
            cursor = await connection.execute("""
                SELECT source_key, MAX(captured_at) AS captured_at
                FROM snapshots
                WHERE kind = ?
                GROUP BY source_key
                ORDER BY source_key ASC
            """, (kind,))
            rows = await cursor.fetchall()
            await cursor.close()
        snapshots = []
        for row in rows:
            snapshot = await self.get_latest_snapshot(
                kind, str(row["source_key"]))
            if snapshot:
                snapshots.append(snapshot)
        return snapshots

    async def record_download(self, task_id: str, query: str,
                              book: dict, output_path: str,
                              file_size: int, sha256: str,
                              output_format: str = "txt") -> dict:
        download_id = uuid.uuid4().hex
        created_at = utc_now()
        book_id = str(book.get("book_id", ""))
        book_name = str(book.get("book_name", book_id))
        await self.upsert_books([book])
        async with self.connect() as connection:
            await connection.execute("""
                INSERT INTO downloads (
                    id, task_id, query, book_id, book_name,
                    output_format, output_path, file_size,
                    sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    output_path = excluded.output_path,
                    file_size = excluded.file_size,
                    sha256 = excluded.sha256,
                    created_at = excluded.created_at
            """, (
                download_id, task_id, query, book_id, book_name,
                output_format, output_path, int(file_size),
                sha256, created_at,
            ))
            await connection.commit()
            cursor = await connection.execute(
                "SELECT * FROM downloads WHERE task_id = ?", (task_id,))
            row = await cursor.fetchone()
            await cursor.close()
        return {
            "id": row["id"],
            "task_id": row["task_id"],
            "book_id": row["book_id"],
            "book_name": row["book_name"],
            "output_format": row["output_format"],
            "output_path": row["output_path"],
            "file_size": row["file_size"],
            "sha256": row["sha256"],
            "created_at": row["created_at"],
        }
