"""Persistent work queue for the RTFM worker daemon.

A single ``work_queue`` table in ``library.db`` holds pending jobs at
seven priority levels — every DB-writing operation in RTFM goes through
this queue. The CLI, hooks, slash commands and the worker's own periodic
ticks are all *producers*; only the worker writes to the library.

  P0 = user-explicit (slash commands, manual ``rtfm <cmd>``)
  P1 = scan       — discover changes in a source
  P2 = remove     — delete an indexed file whose source disappeared
  P3 = ingest     — parse one file → chunks
  P4 = reconcile / vacuum — short maintenance work
  P5 = embed      — vectorise a batch of chunks
  P6 = ocr        — OCR one page-range of a scanned PDF

The worker (see :mod:`rtfm.core.worker`) pops the highest-priority
pending job at every tick — so a fresh P0 always preempts a P5/P6
backlog. Granularity is intentionally fine (1 source / 1 file / 1 batch
/ 1 page-range) so preemption is responsive.

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


# Priority constants — lower number runs first. The space between levels
# is intentional: leaves room for future intermediate priorities without
# renumbering. P_USER (0) is the explicit user-request lane that wins
# over every periodic/background producer.
#
# Document work — remove, ingest AND scan — shares ONE tier (P_DOC) so it is
# served in strict arrival order across all projects, exactly as the operator
# mandated in 0.26.0. Keeping scan *above* remove/ingest (the pre-0.26.5
# scheme, scan=10 < remove=20 < ingest=30) was a starvation bug: a scan is
# re-enqueued every interval per source, so with many projects a fresh scan
# perpetually preempted removals and ingestions queued far earlier — the
# machine scanned forever and never served the work the scans produced. At
# equal priority a just-enqueued scan sorts *after* older pending work, so
# discovery can never jump ahead of the correction it feeds. embed/ocr stay
# strictly below so a large embedding backlog can never starve index-
# correcting work.
P_USER = 0
P_DOC = 10
P_SCAN = P_DOC
P_REMOVE = P_DOC
P_INGEST = P_DOC
P_RECONCILE = 40
P_VACUUM = 40
P_EMBED = 50
P_OCR = 60

#: Default priority for a given job type when the caller doesn't override.
DEFAULT_PRIORITY: dict[str, int] = {
    "scan": P_SCAN,
    "remove": P_REMOVE,
    "ingest": P_INGEST,
    "reconcile": P_RECONCILE,
    "vacuum": P_VACUUM,
    "embed": P_EMBED,
    "ocr": P_OCR,
}

#: All currently-recognised job types. The DB-side CHECK constraint is
#: kept in sync with this set via the migration in :meth:`Queue._init_schema`.
JOB_TYPES: tuple[str, ...] = ("scan", "remove", "ingest",
                              "reconcile", "vacuum", "embed", "ocr")

JobType = str
JobStatus = str  # 'pending' | 'running' | 'done' | 'failed'


# Built so the in-DB CHECK constraint stays in lockstep with JOB_TYPES.
_TYPE_CHECK_SQL = "CHECK(type IN (" + ", ".join(f"'{t}'" for t in JOB_TYPES) + "))"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS work_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL {_TYPE_CHECK_SQL},
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
        # On a brand-new DB, this creates the table with the current CHECK.
        conn.executescript(SCHEMA)
        # On a pre-existing DB, the IF NOT EXISTS above is a no-op and the
        # old CHECK still rejects the new job types. Detect that, and
        # rebuild the table in-place if so.
        self._migrate_table_check(conn)

    def _migrate_table_check(self, conn: sqlite3.Connection) -> None:
        """If ``work_queue.type`` still has the legacy 3-type CHECK,
        rebuild the table with the current 7-type CHECK. Preserves data."""
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='work_queue'"
        ).fetchone()
        if not row or not row["sql"]:
            return
        # Cheap fingerprint: the old schema listed exactly three types.
        current_sql = row["sql"]
        if "'reconcile'" in current_sql:
            return  # already migrated
        # Rebuild. CREATE TABLE …_new with the up-to-date schema, copy
        # rows, swap.
        conn.executescript(f"""
            BEGIN;
            CREATE TABLE work_queue_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL {_TYPE_CHECK_SQL},
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
            INSERT INTO work_queue_new
              SELECT id, type, priority, payload, status,
                     created_at, started_at, finished_at, error, attempts
              FROM work_queue;
            DROP TABLE work_queue;
            ALTER TABLE work_queue_new RENAME TO work_queue;
            CREATE INDEX IF NOT EXISTS idx_queue_pending
                ON work_queue(priority ASC, created_at ASC)
                WHERE status = 'pending';
            CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_unique_pending
                ON work_queue(type, payload)
                WHERE status = 'pending';
            COMMIT;
        """)

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
            priority = DEFAULT_PRIORITY[type]
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
            priority = DEFAULT_PRIORITY[type]
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

    def peek(self) -> Optional[tuple[int, str, str]]:
        """Return ``(priority, created_at, type)`` of the head pending job
        without claiming it, or ``None`` if the queue is empty.

        Used by the supervisor to compare each project's next job across
        projects and dispatch in **global arrival order** — the ``created_at``
        stamps are UTC ISO strings in a fixed format, so they compare
        correctly across different project databases. The ``type`` lets the
        dispatcher tell an exclusive job (vacuum/reconcile/scan) from a
        parallelisable one (embed/ingest/remove). Read-only: it never flips a
        row to ``running`` (only :meth:`dequeue` does).
        """
        row = self._get_conn().execute(
            """SELECT priority, created_at, type FROM work_queue
               WHERE status = 'pending'
               ORDER BY priority ASC, created_at ASC
               LIMIT 1"""
        ).fetchone()
        return (row["priority"], row["created_at"], row["type"]) if row else None

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

    def mark_pending(self, job_id: int) -> None:
        """Send a currently-``running`` job back to ``pending`` without
        counting it as a failed attempt. Used when the worker is asked
        to stop while waiting on an external resource (e.g. the global
        embed-slot semaphore) — the job hasn't started yet, so we must
        not consume one of its retry attempts."""
        self._get_conn().execute(
            """UPDATE work_queue
               SET status = 'pending',
                   started_at = NULL,
                   attempts = MAX(attempts - 1, 0)
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
        """Move ``failed`` rows back to ``pending``. Returns the number of
        rows that ended up pending again.

        Two dedup conditions must be honoured before the bulk UPDATE so
        the unique-pending index can't reject:

        - failed rows whose ``(type, payload)`` matches an already-pending
          row are dropped (the pending one is good enough).
        - failed rows that share ``(type, payload)`` with another failed
          row are coalesced: only the one with the highest ``attempts``
          (then lowest ``id``) survives, the rest are dropped.

        Without these passes, retrying a pile of look-alike failures
        (e.g. 1330 EPUBs with the same shape of error) raises
        ``sqlite3.IntegrityError`` and nothing moves.
        """
        conn = self._get_conn()

        # 1) failed rows that already have a pending twin.
        conn.execute(
            """DELETE FROM work_queue
               WHERE id IN (
                   SELECT f.id FROM work_queue f
                   WHERE f.status = 'failed'
                     AND EXISTS (
                         SELECT 1 FROM work_queue p
                         WHERE p.status = 'pending'
                           AND p.type = f.type
                           AND p.payload = f.payload
                     )
               )"""
        )

        # 2) duplicate failed rows — keep one per (type, payload).
        conn.execute(
            """DELETE FROM work_queue
               WHERE id IN (
                   SELECT id FROM (
                       SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY type, payload
                               ORDER BY attempts DESC, id ASC
                           ) AS rn
                       FROM work_queue
                       WHERE status = 'failed'
                   )
                   WHERE rn > 1
               )"""
        )

        # 3) requeue the survivors.
        cur = conn.execute(
            """UPDATE work_queue
               SET status = 'pending',
                   started_at = NULL,
                   finished_at = NULL,
                   error = NULL
               WHERE status = 'failed'""",
        )
        return cur.rowcount

    def reap_zombies(
        self,
        keep_ids: "Optional[set[int]]" = None,
        *,
        max_age_seconds: int = 3 * 3600,
        max_attempts: int = 3,
    ) -> dict[str, int]:
        """Return ``running`` rows nobody is actually working on to the queue.

        A ``running`` row is a claim: some executor said "this is mine" and
        owes the queue a closing write. When that write never comes — the
        process died, the dispatch raised after the claim, the closing write
        itself failed — the row is stranded. Nothing retries it and nothing
        reports it: the file is silently never indexed. Twenty-six rows once
        sat this way for up to fifty hours under a live supervisor.

        *keep_ids* is the caller's honest answer to "what am I still running?"
        Everything else in ``running`` is a zombie. ``None`` protects nothing,
        which is what a fresh start wants: at boot no job can legitimately be
        in flight, so every claim is stale by definition.

        Kept ids are not protected forever — one older than *max_age_seconds*
        is reaped anyway. An executor that has held a claim for hours is a
        deadlock, not a worker, and the alternative is a job that never moves
        again.

        This replaced a single-``keep_id`` design read from the per-project
        worker's state file. The supervisor runs a dozen jobs per project at
        once and never wrote that file, so it could only ever say "keep
        nothing" — safe at boot and unusable afterwards. That is why the
        stranded rows survived: there was no way to express the running
        fleet's actual claims, so no sweep could run while it mattered.

        Behaviour:

        - Zombies at or past *max_attempts* are marked ``failed`` — a
          poisonous file must not crash-loop forever.
        - Duplicates are dropped rather than requeued, so the partial unique
          index on pending rows still holds.
        - The rest go back to ``pending`` with ``started_at`` cleared.

        Returns ``{"requeued": N, "failed": M, "deduped": K}``.
        """
        keep = sorted(keep_ids or ())
        cutoff_sql = "datetime('now', ?)"
        cutoff_arg = f"-{int(max_age_seconds)} seconds"

        # "Not mine, or mine but stuck long past any plausible run."
        if keep:
            marks = ",".join("?" * len(keep))
            zombie_sql = f"(id NOT IN ({marks}) OR started_at < {cutoff_sql})"
            zombie_args: list = [*keep, cutoff_arg]
            zombie_sql_z = (f"(z.id NOT IN ({marks}) "
                            f"OR z.started_at < {cutoff_sql})")
        else:
            zombie_sql = "1"
            zombie_args = []
            zombie_sql_z = "1"

        conn = self._get_conn()

        # Step 1: zombies that have already retried too many times → failed.
        cur = conn.execute(
            f"""UPDATE work_queue
                SET status = 'failed',
                    finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    error = 'reaped: exceeded retry limit after worker crash'
                WHERE status = 'running'
                  AND attempts >= ?
                  AND {zombie_sql}
            """,
            [max_attempts, *zombie_args],
        )
        failed_count = cur.rowcount

        # Step 2: remaining zombies → pending. First drop the ones that would
        # violate the dedup index on requeue — either an identical pending row
        # already exists, or several zombies share one (type, payload).

        # 2a) zombies whose twin is already pending
        cur = conn.execute(
            f"""DELETE FROM work_queue
                WHERE id IN (
                    SELECT z.id FROM work_queue z
                    WHERE z.status = 'running'
                      AND {zombie_sql_z}
                      AND EXISTS (
                          SELECT 1 FROM work_queue p
                          WHERE p.status = 'pending'
                            AND p.type = z.type
                            AND p.payload = z.payload
                      )
                )
            """,
            zombie_args,
        )
        deduped = cur.rowcount

        # 2b) duplicate zombies amongst themselves — keep one per
        # (type, payload), drop the others. We keep the one with the most
        # attempts so we converge toward 'failed' faster.
        cur = conn.execute(
            f"""DELETE FROM work_queue
                WHERE id IN (
                    SELECT z.id FROM work_queue z
                    WHERE z.status = 'running'
                      AND {zombie_sql_z}
                      AND z.id NOT IN (
                          SELECT id FROM (
                              SELECT id,
                                  ROW_NUMBER() OVER (
                                      PARTITION BY type, payload
                                      ORDER BY attempts DESC, id ASC
                                  ) AS rn
                              FROM work_queue
                              WHERE status = 'running'
                          )
                          WHERE rn = 1
                      )
                )
            """,
            zombie_args,
        )
        deduped += cur.rowcount

        cur = conn.execute(
            f"""UPDATE work_queue
                SET status = 'pending',
                    started_at = NULL,
                    finished_at = NULL,
                    error = 'reaped: worker crashed mid-job'
                WHERE status = 'running'
                  AND {zombie_sql}
            """,
            zombie_args,
        )
        requeued = cur.rowcount

        return {"requeued": requeued, "failed": failed_count, "deduped": deduped}
