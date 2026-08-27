"""SQLite WAL 数据库与仓储接口。"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import asyncio
import base64
import hashlib
import json
from pathlib import Path
import uuid

import aiosqlite


TASK_STATUSES = {
    "queued", "running", "succeeded", "failed", "cancelled",
}
AUTO_DOWNLOAD_TERMINAL_STATUSES = {
    "succeeded", "no_free", "failed",
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


def _encode_cursor(*values: str) -> str:
    raw = _json_dumps(list(values)).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> list[str]:
    padded = str(value) + "=" * (-len(str(value)) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        result = json.loads(decoded.decode("utf-8"))
    except Exception as exc:
        raise ValueError("无效 cursor") from exc
    if not isinstance(result, list) or not all(
            isinstance(item, str) for item in result):
        raise ValueError("无效 cursor")
    return result


class Database:
    """每次操作使用短连接，依靠 WAL 与 busy timeout 协调并发。"""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self._observations_has_raw_json = True

    @staticmethod
    async def _table_columns(connection, table: str) -> set[str]:
        cursor = await connection.execute(f"PRAGMA table_info({table})")
        rows = await cursor.fetchall()
        await cursor.close()
        return {str(row["name"]) for row in rows}

    @classmethod
    async def _ensure_column(cls, connection, table: str,
                             column: str, declaration: str) -> None:
        if column not in await cls._table_columns(connection, table):
            await connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

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

                CREATE TABLE IF NOT EXISTS auto_download_states (
                    book_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_task_id TEXT,
                    last_error TEXT,
                    retry_after TEXT,
                    updated_at TEXT NOT NULL,
                    CHECK (status IN (
                        'queued', 'running', 'succeeded',
                        'no_free', 'failed'
                    )),
                    FOREIGN KEY (book_id) REFERENCES books(book_id)
                );
                CREATE INDEX IF NOT EXISTS idx_auto_download_retry
                    ON auto_download_states(status, retry_after, updated_at);

            """)
            for column, declaration in (
                ("failure_category", "TEXT"),
                ("failure_code", "TEXT"),
                ("parent_task_id", "TEXT"),
                ("next_retry_at", "TEXT"),
            ):
                await self._ensure_column(
                    connection, "tasks", column, declaration)
            for column, declaration in (
                ("book_name", "TEXT"),
                ("author_name", "TEXT"),
                ("cover", "TEXT"),
                ("is_paid", "INTEGER"),
                ("total_word_count", "INTEGER"),
            ):
                await self._ensure_column(
                    connection, "observations", column, declaration)
            await connection.executescript("""
                CREATE INDEX IF NOT EXISTS idx_tasks_retry
                    ON tasks(status, next_retry_at, created_at);
                CREATE INDEX IF NOT EXISTS idx_tasks_failure
                    ON tasks(failure_category, finished_at DESC);

                CREATE TABLE IF NOT EXISTS operation_events (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    component TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    code TEXT NOT NULL DEFAULT '',
                    task_id TEXT,
                    endpoint TEXT NOT NULL DEFAULT '',
                    slot_id TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_created
                    ON operation_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_category
                    ON operation_events(category, created_at DESC);

                CREATE TABLE IF NOT EXISTS runtime_controls (
                    scope TEXT PRIMARY KEY,
                    paused INTEGER NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS archive_catalog (
                    id TEXT PRIMARY KEY,
                    archive_type TEXT NOT NULL,
                    period TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    nas_path TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    record_count INTEGER NOT NULL DEFAULT 0,
                    file_size INTEGER NOT NULL DEFAULT 0,
                    sha256 TEXT NOT NULL DEFAULT '',
                    first_record_at TEXT,
                    last_record_at TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_identity
                    ON archive_catalog(archive_type, period, local_path);
                CREATE INDEX IF NOT EXISTS idx_archive_status
                    ON archive_catalog(status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS protocol_probes (
                    id TEXT PRIMARY KEY,
                    protocol_profile TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    slot_id TEXT NOT NULL,
                    ok INTEGER NOT NULL,
                    category TEXT NOT NULL DEFAULT '',
                    code TEXT NOT NULL DEFAULT '',
                    latency_ms REAL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_probes_latest
                    ON protocol_probes(slot_id, endpoint, created_at DESC);

                CREATE TABLE IF NOT EXISTS raw_archive_queue (
                    id TEXT PRIMARY KEY,
                    record_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    archived_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_raw_archive_pending
                    ON raw_archive_queue(archived_at, captured_at);

                CREATE TABLE IF NOT EXISTS action_confirmations (
                    id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL DEFAULT '',
                    payload_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_confirmations_expiry
                    ON action_confirmations(expires_at, consumed_at);

                PRAGMA user_version = 4;
            """)
            now = utc_now()
            await connection.executemany("""
                INSERT INTO runtime_controls (scope, paused, reason, updated_at)
                VALUES (?, 0, '', ?)
                ON CONFLICT(scope) DO NOTHING
            """, (("all", now), ("scheduler", now),
                    ("auto_download", now)))
            await connection.commit()
            self._observations_has_raw_json = (
                "raw_json" in await self._table_columns(
                    connection, "observations"))

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
        task["effective_status"] = task["status"]
        if (task["status"] == "queued" and task.get("next_retry_at")
                and task["next_retry_at"] > utc_now()):
            task["effective_status"] = "deferred"
        return task

    async def create_task(self, task_type: str, payload: dict,
                          dedupe_key: str | None = None,
                          parent_task_id: str | None = None,
                          next_retry_at: str | None = None
                          ) -> tuple[dict, bool]:
        task_id = uuid.uuid4().hex
        now = utc_now()
        async with self.connect() as connection:
            try:
                await connection.execute("""
                    INSERT INTO tasks (
                        id, task_type, payload_json, dedupe_key, status,
                        parent_task_id, next_retry_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?)
                """, (
                    task_id, task_type, _json_dumps(payload),
                    dedupe_key, parent_task_id, next_retry_at, now, now,
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
            if status not in TASK_STATUSES | {"deferred"}:
                raise ValueError(f"未知任务状态: {status}")
            if status == "deferred":
                clauses.append(
                    "status = 'queued' AND next_retry_at > ?")
                params.append(utc_now())
            else:
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
        now = utc_now()
        async with self.connect() as connection:
            cursor = await connection.execute("""
                SELECT id FROM tasks
                WHERE status = 'queued'
                  AND (next_retry_at IS NULL OR next_retry_at <= ?)
                ORDER BY created_at ASC
            """, (now,))
            rows = await cursor.fetchall()
            await cursor.close()
        return [str(row["id"]) for row in rows]

    async def claim_task(self, task_id: str) -> dict | None:
        now = utc_now()
        async with self.connect() as connection:
            cursor = await connection.execute("""
                UPDATE tasks
                SET status = 'running', started_at = ?, finished_at = NULL,
                    attempts = attempts + 1, error = NULL,
                    next_retry_at = NULL, updated_at = ?
                WHERE id = ? AND status = 'queued'
                  AND (next_retry_at IS NULL OR next_retry_at <= ?)
            """, (now, now, task_id, now))
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
                    failure_category = NULL, failure_code = NULL,
                    next_retry_at = NULL, finished_at = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
            """, (_json_dumps(result), now, now, task_id))
            await connection.commit()

    async def fail_task(self, task_id: str, error: str, *,
                        category: str = "internal",
                        code: str = "") -> None:
        now = utc_now()
        async with self.connect() as connection:
            await connection.execute("""
                UPDATE tasks
                SET status = 'failed', error = ?, finished_at = ?,
                    failure_category = ?, failure_code = ?,
                    next_retry_at = NULL, updated_at = ?
                WHERE id = ? AND status = 'running'
            """, (
                str(error)[:4000], now, str(category), str(code),
                now, task_id,
            ))
            await connection.commit()

    async def defer_task(self, task_id: str, *, error: str,
                         category: str,
                         code: str = "",
                         next_retry_at: str | None = None) -> None:
        retry_at = next_retry_at or (
            datetime.now(timezone.utc) + timedelta(minutes=15)
        ).isoformat(timespec="milliseconds")
        now = utc_now()
        async with self.connect() as connection:
            await connection.execute("""
                UPDATE tasks
                SET status = 'queued', started_at = NULL,
                    finished_at = NULL, error = ?,
                    failure_category = ?, failure_code = ?,
                    next_retry_at = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
            """, (
                str(error)[:4000], str(category), str(code),
                retry_at, now, task_id,
            ))
            await connection.commit()

    async def requeue_task(self, task_id: str) -> None:
        now = utc_now()
        async with self.connect() as connection:
            await connection.execute("""
                UPDATE tasks
                SET status = 'queued', started_at = NULL,
                    finished_at = NULL, next_retry_at = NULL,
                    updated_at = ?
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

    async def retry_task(self, task_id: str) -> tuple[dict, bool]:
        task = await self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        if task["status"] not in {"failed", "cancelled"}:
            raise ValueError("只有 failed/cancelled 任务可重试")
        return await self.create_task(
            task["task_type"],
            task["payload"],
            dedupe_key=task.get("dedupe_key"),
            parent_task_id=task_id,
        )

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
                _json_dumps({}),
                str(book.get("book_name", "")),
                str(book.get("author_name", "")),
                str(book.get("cover", book.get("cover_url", ""))),
                (None if book.get("is_paid") in (None, "")
                 else int(str(book.get("is_paid")) == "1")),
                _as_int(book.get("total_word_count", 0)),
            ) for position, book in enumerate(valid_books, start=1)]
            if observations:
                if self._observations_has_raw_json:
                    await connection.executemany("""
                        INSERT INTO observations (
                            snapshot_id, book_id, position,
                            observed_at, raw_json, book_name,
                            author_name, cover, is_paid, total_word_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, observations)
                else:
                    await connection.executemany("""
                        INSERT INTO observations (
                            snapshot_id, book_id, position,
                            observed_at, book_name, author_name,
                            cover, is_paid, total_word_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, [
                        row[:4] + row[5:] for row in observations
                    ])
                await connection.executemany("""
                    INSERT INTO raw_archive_queue (
                        id, record_type, source_id,
                        captured_at, payload_json
                    ) VALUES (?, 'observation', ?, ?, ?)
                """, [(
                    uuid.uuid4().hex,
                    f"{snapshot_id}:{position}",
                    captured_at,
                    _json_dumps(book),
                ) for position, book in enumerate(valid_books, start=1)])
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
        raw_projection = (
            "o.raw_json" if self._observations_has_raw_json
            else "'{}' AS raw_json")
        cursor = await connection.execute(f"""
            SELECT o.position, o.observed_at, {raw_projection},
                   b.book_id,
                   COALESCE(NULLIF(o.book_name, ''), b.book_name) AS book_name,
                   COALESCE(NULLIF(o.author_name, ''), b.author_name)
                       AS author_name,
                   COALESCE(NULLIF(o.cover, ''), b.cover) AS cover,
                   COALESCE(o.is_paid, b.is_paid) AS is_paid,
                   COALESCE(o.total_word_count, b.total_word_count)
                       AS total_word_count
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

    @staticmethod
    def _book_from_row(row) -> dict:
        raw = _json_loads(row["raw_json"], {})
        raw.setdefault("book_id", row["book_id"])
        raw.setdefault("book_name", row["book_name"])
        raw.setdefault("author_name", row["author_name"])
        raw.setdefault("cover", row["cover"])
        raw.setdefault("is_paid", row["is_paid"])
        raw.setdefault("total_word_count", row["total_word_count"])
        return raw

    async def list_auto_download_candidates(
            self, limit: int = 100) -> list[dict]:
        """返回未下载且当前允许重试的书籍，优先从未尝试者。"""
        now = utc_now()
        async with self.connect() as connection:
            cursor = await connection.execute("""
                SELECT b.*
                FROM books AS b
                LEFT JOIN auto_download_states AS s
                    ON s.book_id = b.book_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM downloads AS d
                    WHERE d.book_id = b.book_id
                )
                  AND (
                    s.book_id IS NULL
                    OR (
                        s.status IN ('failed', 'no_free')
                        AND (s.retry_after IS NULL OR s.retry_after <= ?)
                    )
                    OR (
                        s.status IN ('queued', 'running')
                        AND NOT EXISTS (
                            SELECT 1 FROM tasks AS t
                            WHERE t.id = s.last_task_id
                              AND t.status IN ('queued', 'running')
                        )
                    )
                  )
                ORDER BY
                    CASE WHEN s.book_id IS NULL THEN 0 ELSE 1 END ASC,
                    COALESCE(s.updated_at, b.first_seen_at) ASC,
                    b.book_id ASC
                LIMIT ?
            """, (now, max(1, min(int(limit), 1000))))
            rows = await cursor.fetchall()
            await cursor.close()
        return [self._book_from_row(row) for row in rows]

    async def mark_auto_download_queued(
            self, book_id: str, task_id: str) -> None:
        now = utc_now()
        async with self.connect() as connection:
            await connection.execute("""
                INSERT INTO auto_download_states (
                    book_id, status, attempts, last_task_id,
                    last_error, retry_after, updated_at
                ) VALUES (?, 'queued', 0, ?, NULL, NULL, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    status = 'queued',
                    last_task_id = excluded.last_task_id,
                    last_error = NULL,
                    retry_after = NULL,
                    updated_at = excluded.updated_at
                WHERE auto_download_states.last_task_id
                        IS NOT excluded.last_task_id
                   OR auto_download_states.status = 'queued'
            """, (str(book_id), str(task_id), now))
            await connection.commit()

    async def mark_auto_download_running(
            self, book_id: str, task_id: str) -> None:
        now = utc_now()
        async with self.connect() as connection:
            await connection.execute("""
                INSERT INTO auto_download_states (
                    book_id, status, attempts, last_task_id,
                    last_error, retry_after, updated_at
                ) VALUES (?, 'running', 1, ?, NULL, NULL, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    status = 'running',
                    attempts = auto_download_states.attempts + 1,
                    last_task_id = excluded.last_task_id,
                    last_error = NULL,
                    retry_after = NULL,
                    updated_at = excluded.updated_at
            """, (str(book_id), str(task_id), now))
            await connection.commit()

    async def finish_auto_download(
            self, book_id: str, task_id: str, status: str,
            *, error: str | None = None,
            retry_after: str | None = None) -> None:
        if status not in AUTO_DOWNLOAD_TERMINAL_STATUSES:
            raise ValueError(f"非法自动下载状态: {status}")
        now = utc_now()
        async with self.connect() as connection:
            await connection.execute("""
                INSERT INTO auto_download_states (
                    book_id, status, attempts, last_task_id,
                    last_error, retry_after, updated_at
                ) VALUES (?, ?, 1, ?, ?, ?, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    status = excluded.status,
                    last_task_id = excluded.last_task_id,
                    last_error = excluded.last_error,
                    retry_after = excluded.retry_after,
                    updated_at = excluded.updated_at
            """, (
                str(book_id), status, str(task_id),
                str(error)[:4000] if error else None,
                retry_after, now,
            ))
            await connection.commit()

    async def get_auto_download_state(
            self, book_id: str) -> dict | None:
        async with self.connect() as connection:
            cursor = await connection.execute(
                "SELECT * FROM auto_download_states WHERE book_id = ?",
                (str(book_id),),
            )
            row = await cursor.fetchone()
            await cursor.close()
        return dict(row) if row is not None else None

    async def get_download_stats(self) -> dict:
        now = utc_now()
        async with self.connect() as connection:
            cursor = await connection.execute(
                "SELECT COUNT(*) FROM books")
            indexed_books = int((await cursor.fetchone())[0])
            await cursor.close()
            cursor = await connection.execute("""
                SELECT COUNT(*) AS records,
                       COUNT(DISTINCT book_id) AS books
                FROM downloads
            """)
            download_row = await cursor.fetchone()
            await cursor.close()
            cursor = await connection.execute("""
                SELECT status, COUNT(*) AS count
                FROM auto_download_states
                GROUP BY status
            """)
            state_rows = await cursor.fetchall()
            await cursor.close()
            cursor = await connection.execute("""
                SELECT COUNT(*)
                FROM books AS b
                LEFT JOIN auto_download_states AS s
                    ON s.book_id = b.book_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM downloads AS d
                    WHERE d.book_id = b.book_id
                )
                  AND (
                    s.book_id IS NULL
                    OR (
                        s.status IN ('failed', 'no_free')
                        AND (s.retry_after IS NULL OR s.retry_after <= ?)
                    )
                    OR (
                        s.status IN ('queued', 'running')
                        AND NOT EXISTS (
                            SELECT 1 FROM tasks AS t
                            WHERE t.id = s.last_task_id
                              AND t.status IN ('queued', 'running')
                        )
                    )
                  )
            """, (now,))
            eligible = int((await cursor.fetchone())[0])
            await cursor.close()
        return {
            "indexed_books": indexed_books,
            "download_records": int(download_row["records"]),
            "downloaded_books": int(download_row["books"]),
            "eligible_books": eligible,
            "auto_states": {
                row["status"]: int(row["count"])
                for row in state_rows
            },
        }

    async def record_event(
        self,
        *,
        event_type: str,
        component: str = "",
        category: str = "",
        code: str = "",
        task_id: str | None = None,
        endpoint: str = "",
        slot_id: str = "",
        message: str = "",
        metadata: dict | None = None,
    ) -> dict:
        event_id = uuid.uuid4().hex
        created_at = utc_now()
        async with self.connect() as connection:
            await connection.execute("""
                INSERT INTO operation_events (
                    id, event_type, component, category, code,
                    task_id, endpoint, slot_id, message,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event_id, str(event_type), str(component), str(category),
                str(code), task_id, str(endpoint), str(slot_id),
                str(message)[:2000], _json_dumps(metadata or {}), created_at,
            ))
            await connection.commit()
        return {"id": event_id, "created_at": created_at}

    async def list_events(self, *, category: str | None = None,
                          component: str | None = None,
                          limit: int = 100) -> list[dict]:
        clauses = []
        params: list[object] = []
        if category:
            clauses.append("category = ?")
            params.append(str(category))
        if component:
            clauses.append("component = ?")
            params.append(str(component))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        async with self.connect() as connection:
            cursor = await connection.execute(f"""
                SELECT * FROM operation_events
                {where}
                ORDER BY created_at DESC
                LIMIT ?
            """, params)
            rows = await cursor.fetchall()
            await cursor.close()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = _json_loads(
                item.pop("metadata_json"), {})
            result.append(item)
        return result

    async def get_controls(self) -> dict:
        async with self.connect() as connection:
            cursor = await connection.execute("""
                SELECT * FROM runtime_controls ORDER BY scope
            """)
            rows = await cursor.fetchall()
            await cursor.close()
        return {
            str(row["scope"]): {
                "paused": bool(row["paused"]),
                "reason": str(row["reason"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        }

    async def set_control(self, scope: str, *, paused: bool,
                          reason: str = "") -> dict:
        if scope not in {"all", "scheduler", "auto_download"}:
            raise ValueError("未知控制范围")
        now = utc_now()
        async with self.connect() as connection:
            await connection.execute("""
                INSERT INTO runtime_controls (scope, paused, reason, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(scope) DO UPDATE SET
                    paused = excluded.paused,
                    reason = excluded.reason,
                    updated_at = excluded.updated_at
            """, (scope, int(bool(paused)), str(reason)[:500], now))
            await connection.commit()
        await self.record_event(
            event_type="control_changed",
            component=scope,
            message=("paused" if paused else "resumed"),
            metadata={"reason": str(reason)[:500]},
        )
        return {
            "scope": scope,
            "paused": bool(paused),
            "reason": str(reason)[:500],
            "updated_at": now,
        }

    async def is_paused(self, scope: str) -> bool:
        controls = await self.get_controls()
        return bool(
            controls.get("all", {}).get("paused")
            or controls.get(scope, {}).get("paused")
        )

    async def record_protocol_probe(
            self, *, protocol_profile: str, endpoint: str,
            slot_id: str, ok: bool, category: str = "",
            code: str = "", latency_ms: float | None = None) -> dict:
        probe_id = uuid.uuid4().hex
        created_at = utc_now()
        async with self.connect() as connection:
            await connection.execute("""
                INSERT INTO protocol_probes (
                    id, protocol_profile, endpoint, slot_id, ok,
                    category, code, latency_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                probe_id, protocol_profile, endpoint, slot_id, int(ok),
                category, code, latency_ms, created_at,
            ))
            await connection.commit()
        return {"id": probe_id, "created_at": created_at}

    async def latest_protocol_probes(self) -> list[dict]:
        async with self.connect() as connection:
            cursor = await connection.execute("""
                SELECT p.*
                FROM protocol_probes AS p
                JOIN (
                    SELECT slot_id, endpoint, MAX(created_at) AS created_at
                    FROM protocol_probes
                    GROUP BY slot_id, endpoint
                ) AS latest
                  ON latest.slot_id = p.slot_id
                 AND latest.endpoint = p.endpoint
                 AND latest.created_at = p.created_at
                ORDER BY p.slot_id, p.endpoint
            """)
            rows = await cursor.fetchall()
            await cursor.close()
        return [{**dict(row), "ok": bool(row["ok"])} for row in rows]

    async def operation_health(self, *, limit: int = 100) -> dict:
        """汇总最近 App 请求结果；控制类事件不会污染连续失败计数。"""
        async with self.connect() as connection:
            cursor = await connection.execute("""
                SELECT event_type, category, code, slot_id, created_at
                FROM operation_events
                WHERE event_type IN (
                    'request_success', 'request_failure',
                    'protocol_probe_succeeded', 'protocol_probe_failed'
                )
                ORDER BY created_at DESC
                LIMIT ?
            """, (max(1, min(int(limit), 1000)),))
            rows = await cursor.fetchall()
            await cursor.close()
        failure_streak = 0
        last_success_at = None
        last_failure_at = None
        for row in rows:
            event_type = str(row["event_type"])
            if event_type in {"request_success", "protocol_probe_succeeded"}:
                if last_success_at is None:
                    last_success_at = str(row["created_at"])
                break
            if last_failure_at is None:
                last_failure_at = str(row["created_at"])
            failure_streak += 1
        if last_success_at is None:
            for row in rows:
                if str(row["event_type"]) in {
                        "request_success", "protocol_probe_succeeded"}:
                    last_success_at = str(row["created_at"])
                    break
        return {
            "failure_streak": failure_streak,
            "last_success_at": last_success_at,
            "last_failure_at": last_failure_at,
            "sample_size": len(rows),
        }

    @staticmethod
    def _confirmation_payload_hash(payload: dict) -> str:
        canonical = _json_dumps(payload).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    async def create_confirmation(
            self, *, action: str, target: str, payload: dict,
            ttl_seconds: int = 300) -> dict:
        confirmation_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        created_at = now.isoformat(timespec="milliseconds")
        expires_at = (
            now + timedelta(seconds=max(30, int(ttl_seconds)))
        ).isoformat(timespec="milliseconds")
        async with self.connect() as connection:
            await connection.execute("""
                DELETE FROM action_confirmations
                WHERE expires_at < ? OR consumed_at IS NOT NULL
            """, (created_at,))
            await connection.execute("""
                INSERT INTO action_confirmations (
                    id, action, target, payload_hash,
                    expires_at, consumed_at, created_at
                ) VALUES (?, ?, ?, ?, ?, NULL, ?)
            """, (
                confirmation_id, str(action), str(target),
                self._confirmation_payload_hash(payload),
                expires_at, created_at,
            ))
            await connection.commit()
        return {
            "confirmation_token": confirmation_id,
            "action": str(action),
            "target": str(target),
            "expires_at": expires_at,
        }

    async def consume_confirmation(
            self, confirmation_token: str, *, action: str,
            target: str, payload: dict) -> bool:
        now = utc_now()
        async with self.connect() as connection:
            cursor = await connection.execute("""
                UPDATE action_confirmations
                SET consumed_at = ?
                WHERE id = ? AND action = ? AND target = ?
                  AND payload_hash = ? AND consumed_at IS NULL
                  AND expires_at >= ?
            """, (
                now, str(confirmation_token), str(action), str(target),
                self._confirmation_payload_hash(payload), now,
            ))
            await connection.commit()
            return cursor.rowcount == 1

    async def list_books(self, *, query: str | None = None,
                         cursor: str | None = None,
                         limit: int = 50) -> dict:
        clauses = []
        params: list[object] = []
        if query:
            clauses.append("(book_name LIKE ? OR author_name LIKE ?)")
            pattern = f"%{str(query).strip()}%"
            params.extend((pattern, pattern))
        if cursor:
            values = _decode_cursor(cursor)
            if len(values) != 2:
                raise ValueError("无效 cursor")
            clauses.append("""
                (last_seen_at < ? OR
                 (last_seen_at = ? AND book_id > ?))
            """)
            params.extend((values[0], values[0], values[1]))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        page_size = max(1, min(int(limit), 100))
        params.append(page_size + 1)
        async with self.connect() as connection:
            cursor_obj = await connection.execute(f"""
                SELECT b.*,
                       EXISTS(SELECT 1 FROM downloads d
                              WHERE d.book_id = b.book_id) AS downloaded
                FROM books b
                {where}
                ORDER BY last_seen_at DESC, book_id ASC
                LIMIT ?
            """, params)
            rows = await cursor_obj.fetchall()
            await cursor_obj.close()
        has_more = len(rows) > page_size
        page = rows[:page_size]
        items = []
        for row in page:
            item = self._book_from_row(row)
            item.update({
                "first_seen_at": row["first_seen_at"],
                "last_seen_at": row["last_seen_at"],
                "downloaded": bool(row["downloaded"]),
            })
            items.append(item)
        next_cursor = None
        if has_more and page:
            last = page[-1]
            next_cursor = _encode_cursor(
                str(last["last_seen_at"]), str(last["book_id"]))
        return {"items": items, "next_cursor": next_cursor}

    async def get_book(self, book_id: str) -> dict | None:
        async with self.connect() as connection:
            cursor = await connection.execute("""
                SELECT b.*,
                       EXISTS(SELECT 1 FROM downloads d
                              WHERE d.book_id = b.book_id) AS downloaded
                FROM books b WHERE b.book_id = ?
            """, (str(book_id),))
            row = await cursor.fetchone()
            await cursor.close()
        if row is None:
            return None
        item = self._book_from_row(row)
        item.update({
            "first_seen_at": row["first_seen_at"],
            "last_seen_at": row["last_seen_at"],
            "downloaded": bool(row["downloaded"]),
        })
        return item

    async def list_downloads(self, *, limit: int = 100) -> list[dict]:
        async with self.connect() as connection:
            cursor = await connection.execute("""
                SELECT * FROM downloads
                ORDER BY created_at DESC
                LIMIT ?
            """, (max(1, min(int(limit), 500)),))
            rows = await cursor.fetchall()
            await cursor.close()
        return [dict(row) for row in rows]

    async def get_download(self, download_id: str) -> dict | None:
        async with self.connect() as connection:
            cursor = await connection.execute(
                "SELECT * FROM downloads WHERE id = ?", (download_id,))
            row = await cursor.fetchone()
            await cursor.close()
        return dict(row) if row is not None else None

    async def get_ranking_history(
            self, source_key: str, *, book_id: str | None = None,
            since: str | None = None, until: str | None = None,
            limit: int = 500) -> list[dict]:
        clauses = ["s.kind = 'ranking'", "s.source_key = ?"]
        params: list[object] = [source_key]
        if since:
            clauses.append("s.captured_at >= ?")
            params.append(since)
        if until:
            clauses.append("s.captured_at <= ?")
            params.append(until)
        if book_id:
            clauses.append("o.book_id = ?")
            params.append(book_id)
        params.append(max(1, min(int(limit), 5000)))
        async with self.connect() as connection:
            cursor = await connection.execute(f"""
                SELECT s.id AS snapshot_id, s.captured_at,
                       s.source_key, s.item_count,
                       o.book_id, o.position,
                       COALESCE(NULLIF(o.book_name, ''), b.book_name)
                           AS book_name
                FROM snapshots s
                JOIN observations o ON o.snapshot_id = s.id
                JOIN books b ON b.book_id = o.book_id
                WHERE {' AND '.join(clauses)}
                ORDER BY s.captured_at DESC, o.position ASC
                LIMIT ?
            """, params)
            rows = await cursor.fetchall()
            await cursor.close()
        return [dict(row) for row in rows]

    async def overview(self) -> dict:
        async with self.connect() as connection:
            cursor = await connection.execute("""
                SELECT status, COUNT(*) AS count
                FROM tasks GROUP BY status
            """)
            task_rows = await cursor.fetchall()
            await cursor.close()
            cursor = await connection.execute("""
                SELECT MAX(finished_at) AS last_success_at
                FROM tasks WHERE status = 'succeeded'
            """)
            success_row = await cursor.fetchone()
            await cursor.close()
            cursor = await connection.execute("""
                SELECT failure_category, COUNT(*) AS count
                FROM tasks
                WHERE status = 'failed'
                  AND finished_at >= ?
                GROUP BY failure_category
            """, ((datetime.now(timezone.utc) - timedelta(days=1))
                   .isoformat(timespec="milliseconds"),))
            failure_rows = await cursor.fetchall()
            await cursor.close()
            cursor = await connection.execute(
                "SELECT COUNT(*) FROM raw_archive_queue "
                "WHERE archived_at IS NULL")
            raw_pending = int((await cursor.fetchone())[0])
            await cursor.close()
        return {
            "tasks": {row["status"]: int(row["count"])
                      for row in task_rows},
            "last_success_at": success_row["last_success_at"],
            "failures_24h": {
                str(row["failure_category"] or "internal"):
                    int(row["count"])
                for row in failure_rows
            },
            "raw_archive_pending": raw_pending,
            "database_bytes": (
                self.path.stat().st_size if self.path.exists() else 0),
        }

    async def list_pending_raw_records(
            self, *, limit: int = 10000) -> list[dict]:
        async with self.connect() as connection:
            cursor = await connection.execute("""
                SELECT * FROM raw_archive_queue
                WHERE archived_at IS NULL
                ORDER BY captured_at ASC, id ASC
                LIMIT ?
            """, (max(1, min(int(limit), 100000)),))
            rows = await cursor.fetchall()
            await cursor.close()
        return [dict(row) for row in rows]

    async def mark_raw_records_archived(self, ids: list[str]) -> None:
        if not ids:
            return
        now = utc_now()
        async with self.connect() as connection:
            await connection.executemany("""
                UPDATE raw_archive_queue SET archived_at = ?
                WHERE id = ? AND archived_at IS NULL
            """, ((now, str(record_id)) for record_id in ids))
            await connection.commit()

    async def delete_archived_raw_records(self, ids: list[str]) -> int:
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        async with self.connect() as connection:
            cursor = await connection.execute(f"""
                DELETE FROM raw_archive_queue
                WHERE archived_at IS NOT NULL
                  AND id IN ({placeholders})
            """, [str(record_id) for record_id in ids])
            await connection.commit()
            return cursor.rowcount

    async def purge_archived_raw_records(self, *, older_than: str) -> int:
        async with self.connect() as connection:
            cursor = await connection.execute("""
                DELETE FROM raw_archive_queue
                WHERE archived_at IS NOT NULL AND archived_at < ?
            """, (older_than,))
            await connection.commit()
            return cursor.rowcount

    async def list_legacy_observation_raw(
            self, *, limit: int = 100000) -> list[dict]:
        if not self._observations_has_raw_json:
            return []
        async with self.connect() as connection:
            cursor = await connection.execute("""
                SELECT snapshot_id, book_id, position,
                       observed_at, raw_json
                FROM observations
                WHERE raw_json IS NOT NULL
                  AND raw_json NOT IN ('', '{}')
                ORDER BY observed_at ASC, snapshot_id, position
                LIMIT ?
            """, (max(1, min(int(limit), 500000)),))
            rows = await cursor.fetchall()
            await cursor.close()
        return [dict(row) for row in rows]

    async def upsert_archive(self, *, archive_type: str, period: str,
                             local_path: str, nas_path: str = "",
                             status: str, record_count: int = 0,
                             file_size: int = 0, sha256: str = "",
                             first_record_at: str | None = None,
                             last_record_at: str | None = None,
                             error: str | None = None) -> dict:
        now = utc_now()
        archive_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{archive_type}:{period}:{local_path}",
        ).hex
        async with self.connect() as connection:
            await connection.execute("""
                INSERT INTO archive_catalog (
                    id, archive_type, period, local_path, nas_path,
                    status, record_count, file_size, sha256,
                    first_record_at, last_record_at, error,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(archive_type, period, local_path) DO UPDATE SET
                    nas_path = excluded.nas_path,
                    status = excluded.status,
                    record_count = excluded.record_count,
                    file_size = excluded.file_size,
                    sha256 = excluded.sha256,
                    first_record_at = excluded.first_record_at,
                    last_record_at = excluded.last_record_at,
                    error = excluded.error,
                    updated_at = excluded.updated_at
            """, (
                archive_id, archive_type, period, local_path, nas_path,
                status, int(record_count), int(file_size), sha256,
                first_record_at, last_record_at,
                str(error)[:2000] if error else None, now, now,
            ))
            await connection.commit()
        return {"id": archive_id, "status": status, "updated_at": now}

    async def list_archives(self, *, limit: int = 200) -> list[dict]:
        async with self.connect() as connection:
            cursor = await connection.execute("""
                SELECT * FROM archive_catalog
                ORDER BY period DESC, created_at DESC
                LIMIT ?
            """, (max(1, min(int(limit), 1000)),))
            rows = await cursor.fetchall()
            await cursor.close()
        return [dict(row) for row in rows]

    async def get_archive(self, archive_id: str) -> dict | None:
        async with self.connect() as connection:
            cursor = await connection.execute(
                "SELECT * FROM archive_catalog WHERE id = ?",
                (str(archive_id),),
            )
            row = await cursor.fetchone()
            await cursor.close()
        return dict(row) if row is not None else None

    async def compact_observations(self) -> dict:
        """移除已冷归档的重复 raw_json；调用方须先完成归档校验。"""
        if not self._observations_has_raw_json:
            return {"compacted": False, "reason": "already-compact"}
        if await self.list_legacy_observation_raw(limit=1):
            raise RuntimeError("仍存在未清空的 legacy observation raw_json")
        async with self.connect() as connection:
            await connection.execute("PRAGMA foreign_keys = OFF")
            await connection.execute("BEGIN EXCLUSIVE")
            try:
                # sqlite3.executescript() 会在执行脚本前隐式 COMMIT，放在
                # BEGIN EXCLUSIVE 后会把本应原子的表替换拆开。逐条执行可
                # 保证任一步失败都能回滚到原 observations 表。
                statements = ("""
                    CREATE TABLE observations_compact (
                        snapshot_id TEXT NOT NULL,
                        book_id TEXT NOT NULL,
                        position INTEGER NOT NULL,
                        observed_at TEXT NOT NULL,
                        book_name TEXT,
                        author_name TEXT,
                        cover TEXT,
                        is_paid INTEGER,
                        total_word_count INTEGER,
                        PRIMARY KEY (snapshot_id, book_id),
                        FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
                            ON DELETE CASCADE,
                        FOREIGN KEY (book_id) REFERENCES books(book_id)
                    )
                """, """
                    INSERT INTO observations_compact (
                        snapshot_id, book_id, position, observed_at,
                        book_name, author_name, cover,
                        is_paid, total_word_count
                    )
                    SELECT snapshot_id, book_id, position, observed_at,
                           book_name, author_name, cover,
                           is_paid, total_word_count
                    FROM observations
                """, "DROP TABLE observations", """
                    ALTER TABLE observations_compact RENAME TO observations
                """, """
                    CREATE INDEX idx_observations_book
                        ON observations(book_id, observed_at DESC)
                """)
                for statement in statements:
                    await connection.execute(statement)
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise
            finally:
                await connection.execute("PRAGMA foreign_keys = ON")
        self._observations_has_raw_json = False
        return {"compacted": True}

    async def clear_legacy_observation_raw(self) -> int:
        if not self._observations_has_raw_json:
            return 0
        async with self.connect() as connection:
            cursor = await connection.execute("""
                UPDATE observations SET raw_json = '{}'
                WHERE raw_json IS NOT NULL AND raw_json NOT IN ('', '{}')
            """)
            await connection.commit()
            return cursor.rowcount

    async def prune_semantic_history(self, *, before: str) -> dict:
        async with self.connect() as connection:
            snapshots = await connection.execute(
                "DELETE FROM snapshots WHERE captured_at < ?", (before,))
            events = await connection.execute(
                "DELETE FROM operation_events WHERE created_at < ?", (before,))
            probes = await connection.execute(
                "DELETE FROM protocol_probes WHERE created_at < ?", (before,))
            tasks = await connection.execute("""
                DELETE FROM tasks
                WHERE status IN ('succeeded', 'failed', 'cancelled')
                  AND finished_at < ?
                  AND NOT EXISTS (
                      SELECT 1 FROM downloads d WHERE d.task_id = tasks.id
                  )
            """, (before,))
            await connection.commit()
        return {
            "snapshots": snapshots.rowcount,
            "events": events.rowcount,
            "probes": probes.rowcount,
            "tasks": tasks.rowcount,
        }
