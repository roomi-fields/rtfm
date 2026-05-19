"""Persistent work queue for the RTFM worker daemon.

A single ``work_queue`` table in ``library.db`` holds pending jobs at
three priority levels:

  P1 = ingest  → a single file to (re)index
  P2 = embed   → a batch of chunks without embeddings
  P3 = ocr     → a single scan-suspect PDF to OCR

The worker (see :mod:`rtfm.core.worker`) pops the highest-priority
pending job at every tick — so a freshly-enqueued P1 always preempts a
P2/P3 backlog. Granularity is intentionally fine (1 file / 1 batch /
1 PDF) so preemption is responsive.

Concurrency contract:

* Only one worker process at a time (enforced via a flock on
  ``.rtfm/worker.lock`` — see :mod:`rtfm.core.worker`).
* The queue itself is safe under concurrent ``enqueue()`` from multiple
  producers (CLI, hooks, MCP tools); rows go through the SQLite WAL.
* ``dequeue()`` atomically flips a row from ``pending`` → ``running``
  with a single UPDATE+RETURNING so two workers (if ever) cannot both
  claim it.

Dedup: ``UNIQUE(type, payload) WHERE status='pending'`` prevents the
same file from being queued twice while waiting. A retry of a failed
job is a brand-new row.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


# Priority constants — lower number runs first.
P_INGEST = 1
P_EMBED = 2
P_OCR = 3

JobType = str  # 'ingest' | 'embed' | 'ocr'
JobStatus = str  # 'pending' | 'running' | 'done' | 'failed'


SCHEMA = """
CREATE TABLE IF NOT EXISTS work_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK(type IN ('ingest', 'embed', 'ocr')),
    priority INTEGER NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'running', 'done', 'failed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    started_at TEXT,
    finished_at TEXT,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0
);

-- Hot index for the dequeue path.
CREATE INDEX IF NOT EXISTS idx_queue_pending
    ON work_queue(priority ASC, created_at ASC)
    WHERE status = 'pending';

-- Dedup: don't queue the same (type, payload) twice while the first
-- attempt is still pending. Retries after a failure are a new row.
CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_unique_pending
    ON work_queue(type, payload)
    WHERE status = 'pending';
"""


@dataclass
class Job:
    """A row from ``work_queue`` materialised in Python."""
    id: int
    type: JobType
    priority: int
    payload: dict[str, Any]
    status: JobStatus
    created_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    error: Optional[str]
    attempts: int

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Job":
        return cls(
            id=row["id"],
            type=row["type"],
            priority=row["priority"],
            payload=json.loads(row["payload"]),
            status=row["status"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            error=row["error"],
            attempts=row["attempts"],
        )


class Queue:
    """Thin facade over the ``work_queue`` table.

    Holds its own connection (separate from :class:`Library`) so producers
    and the worker can talk to the queue without serialising on the
    library's single shared connection.
    """

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(self._db_path, isolation_level=None,
                                   check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            # 60s. The original 10s was breaking on multi-session Claude
            # Code setups where ~3 MCP servers + the worker + a CLI
            # ``rtfm sync`` all touch the same DB. WAL allows N readers
            # + 1 writer but only one can hold the write lock at a time.
            conn.execute("PRAGMA busy_timeout=60000")
            self._conn = conn
        return self._conn

    def _init_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript(SCHEMA)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ── Producers ────────────────────────────────────────────────────────

    def enqueue(self, type: JobType, payload: dict[str, Any],
                priority: Optional[int] = None) -> Optional[int]:
        """Queue a job. Returns the new row id, or ``None`` if a pending
        job with the same ``(type, payload)`` already exists (dedup)."""
        if priority is None:
            priority = {"ingest": P_INGEST, "embed": P_EMBED,
                        "ocr": P_OCR}[type]
        body = json.dumps(payload, sort_keys=True)
        try:
            cur = self._get_conn().execute(
                "INSERT INTO work_queue (type, priority, payload) VALUES (?, ?, ?)",
                (type, priority, body),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            # Duplicate against the partial-unique index — already pending.
            return None

    def enqueue_many(self, type: JobType,
                     payloads: Iterable[dict[str, Any]],
                     priority: Optional[int] = None) -> tuple[int, int]:
        """Bulk enqueue. Returns ``(inserted, deduped)``.

        Wraps the batch in a single ``BEGIN IMMEDIATE`` transaction so
        the writer takes the lock once instead of N times, and so the
        batch is atomic — either all rows land or none. On a transient
        ``database is locked`` (the busy_timeout already buys us 60 s,
        so this only fires under sustained extreme contention) we
        retry the whole batch a few times before giving up.
        """
        if priority is None:
            priority = {"ingest": P_INGEST, "embed": P_EMBED,
                        "ocr": P_OCR}[type]
        payloads = list(payloads)  # we need to iterate twice on retry
        conn = self._get_conn()

        last_exc: Optional[Exception] = None
        for attempt in range(3):
            inserted = deduped = 0
            try:
                conn.execute("BEGIN IMMEDIATE")
                for payload in payloads:
                    body = json.dumps(payload, sort_keys=True)
                    try:
                        conn.execute(
                            "INSERT INTO work_queue (type, priority, payload) "
                            "VALUES (?, ?, ?)",
                            (type, priority, body),
                        )
                        inserted += 1
                    except sqlite3.IntegrityError:
                        deduped += 1
                conn.execute("COMMIT")
                return inserted, deduped
            except sqlite3.OperationalError as exc:
                # Roll back if the transaction is still open
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.OperationalError:
                    pass
                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                    raise
                last_exc = exc
                import time as _t
                _t.sleep(0.5 * (attempt + 1))
        # All retries exhausted
        if last_exc is not None:
            raise last_exc
        return 0, 0

    # ── Consumer ─────────────────────────────────────────────────────────

    def dequeue(self) -> Optional[Job]:
        """Atomically pick the highest-priority pending job and mark it
        ``running``. Returns ``None`` when the queue is empty."""
        conn = self._get_conn()
        # RETURNING is available since SQLite 3.35 (Python 3.11+ ships it).
        row = conn.execute(
            """UPDATE work_queue
               SET status = 'running',
                   started_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                   attempts = attempts + 1
               WHERE id = (
                   SELECT id FROM work_queue
                   WHERE status = 'pending'
                   ORDER BY priority ASC, created_at ASC
                   LIMIT 1
               )
               RETURNING *""",
        ).fetchone()
        return Job.from_row(row) if row else None

    def mark_done(self, job_id: int) -> None:
        self._get_conn().execute(
            """UPDATE work_queue SET status = 'done',
               finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
               WHERE id = ?""",
            (job_id,),
        )

    def mark_failed(self, job_id: int, error: str) -> None:
        self._get_conn().execute(
            """UPDATE work_queue SET status = 'failed',
               finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
               error = ?
               WHERE id = ?""",
            (error[:2000], job_id),
        )

    # ── Inspection ──────────────────────────────────────────────────────

    def stats(self) -> dict[str, dict[str, int]]:
        """Return ``{type: {status: count}}`` for the whole queue."""
        rows = self._get_conn().execute(
            "SELECT type, status, COUNT(*) AS n FROM work_queue GROUP BY type, status"
        ).fetchall()
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            out.setdefault(r["type"], {})[r["status"]] = r["n"]
        return out

    def list_pending(self, limit: int = 20) -> list[Job]:
        rows = self._get_conn().execute(
            """SELECT * FROM work_queue
               WHERE status = 'pending'
               ORDER BY priority ASC, created_at ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [Job.from_row(r) for r in rows]

    def list_failed(self, limit: int = 20) -> list[Job]:
        rows = self._get_conn().execute(
            """SELECT * FROM work_queue
               WHERE status = 'failed'
               ORDER BY finished_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [Job.from_row(r) for r in rows]

    def clear_done(self, keep_last: int = 100) -> int:
        """Garbage-collect ``done`` rows older than ``keep_last`` newest.
        Returns the number of rows deleted."""
        cur = self._get_conn().execute(
            """DELETE FROM work_queue
               WHERE id IN (
                   SELECT id FROM work_queue
                   WHERE status = 'done'
                   ORDER BY finished_at DESC
                   LIMIT -1 OFFSET ?
               )""",
            (keep_last,),
        )
        return cur.rowcount

    def retry_failed(self) -> int:
        """Move ``failed`` rows back to ``pending``. Returns affected count.
        The dedup index allows this because a failed row no longer
        collides with a pending one."""
        cur = self._get_conn().execute(
            """UPDATE work_queue
               SET status = 'pending',
                   started_at = NULL,
                   finished_at = NULL,
                   error = NULL
               WHERE status = 'failed'""",
        )
        return cur.rowcount
