"""Tests for the priority-queue module (``rtfm.core.queue``).

Covers the on-disk schema, enqueue dedup, priority ordering, and the
status transitions. The worker loop itself is exercised in
``test_worker.py``.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rtfm.core.queue import Queue, Job, P_INGEST, P_EMBED, P_OCR


@pytest.fixture
def queue(tmp_path: Path) -> Queue:
    q = Queue(tmp_path / "library.db")
    yield q
    q.close()


def test_schema_creates_table_and_indexes(tmp_path: Path):
    Queue(tmp_path / "library.db").close()
    conn = sqlite3.connect(tmp_path / "library.db")
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "work_queue" in tables
    indexes = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()}
    assert "idx_queue_pending" in indexes
    assert "idx_queue_unique_pending" in indexes


def test_enqueue_assigns_priority_by_type(queue: Queue):
    a = queue.enqueue("ingest", {"f": "a"})
    b = queue.enqueue("embed", {"chunks": [1, 2]})
    c = queue.enqueue("ocr", {"f": "b.pdf"})
    rows = queue._get_conn().execute(
        "SELECT id, priority FROM work_queue ORDER BY id"
    ).fetchall()
    by_id = {r["id"]: r["priority"] for r in rows}
    assert by_id[a] == P_INGEST
    assert by_id[b] == P_EMBED
    assert by_id[c] == P_OCR


def test_dedup_pending_same_payload(queue: Queue):
    first = queue.enqueue("ingest", {"f": "a"})
    again = queue.enqueue("ingest", {"f": "a"})
    assert first is not None
    assert again is None, "same (type, payload) while pending must dedup"
    # Different payload → fresh row
    other = queue.enqueue("ingest", {"f": "b"})
    assert other is not None and other != first


def test_dedup_allows_retry_after_failed(queue: Queue):
    """Once a job is marked failed, the same payload can be queued again."""
    first = queue.enqueue("ingest", {"f": "a"})
    queue.dequeue()
    queue.mark_failed(first, "boom")
    again = queue.enqueue("ingest", {"f": "a"})
    assert again is not None, "failed row no longer blocks re-enqueue"
    assert again != first


def test_dequeue_returns_highest_priority_first(queue: Queue):
    # Insert in inverse priority order — dequeue must pick P1 first.
    queue.enqueue("ocr", {"f": "low.pdf"})
    queue.enqueue("embed", {"chunks": [1]})
    queue.enqueue("ingest", {"f": "high.md"})

    j = queue.dequeue()
    assert j is not None and j.type == "ingest"
    j = queue.dequeue()
    assert j is not None and j.type == "embed"
    j = queue.dequeue()
    assert j is not None and j.type == "ocr"
    assert queue.dequeue() is None


def test_dequeue_breaks_ties_by_created_at(queue: Queue):
    """Two jobs at the same priority: FIFO."""
    first = queue.enqueue("ingest", {"f": "1"})
    second = queue.enqueue("ingest", {"f": "2"})
    a = queue.dequeue()
    b = queue.dequeue()
    assert a.id == first
    assert b.id == second


def test_peek_returns_head_without_claiming(queue: Queue):
    """peek() reports the head job's (priority, created_at) but leaves it
    pending — only dequeue() flips a row to running."""
    assert queue.peek() is None
    queue.enqueue("ocr", {"f": "low.pdf"})
    queue.enqueue("ingest", {"f": "high.md"})  # higher priority

    head = queue.peek()
    assert head is not None
    prio, created, jtype = head
    assert prio == 10 and jtype == "ingest"  # P_INGEST (P_DOC) wins over P_OCR
    # Nothing was claimed: the row is still pending and a dequeue returns it.
    stats = queue.stats()
    assert stats.get("ingest", {}).get("running", 0) == 0
    j = queue.dequeue()
    assert j is not None and j.type == "ingest" and j.created_at == created


def test_dequeue_marks_running_atomically(queue: Queue):
    job_id = queue.enqueue("ingest", {"f": "a"})
    job = queue.dequeue()
    assert job is not None and job.id == job_id
    row = queue._get_conn().execute(
        "SELECT status, started_at, attempts FROM work_queue WHERE id = ?",
        (job_id,),
    ).fetchone()
    assert row["status"] == "running"
    assert row["started_at"] is not None
    assert row["attempts"] == 1


def test_mark_done_and_failed(queue: Queue):
    j1 = queue.enqueue("ingest", {"f": "ok"})
    j2 = queue.enqueue("ingest", {"f": "ko"})
    queue.dequeue()
    queue.dequeue()
    queue.mark_done(j1)
    queue.mark_failed(j2, "boom: stack trace here")
    rows = {r["id"]: dict(r) for r in queue._get_conn().execute(
        "SELECT id, status, error FROM work_queue"
    ).fetchall()}
    assert rows[j1]["status"] == "done"
    assert rows[j1]["error"] is None
    assert rows[j2]["status"] == "failed"
    assert "boom" in rows[j2]["error"]


def test_stats_groups_by_type_and_status(queue: Queue):
    queue.enqueue("ingest", {"f": "1"})
    queue.enqueue("ingest", {"f": "2"})
    queue.enqueue("embed", {"chunks": [1]})
    j = queue.dequeue()
    queue.mark_done(j.id)
    stats = queue.stats()
    assert stats["ingest"]["pending"] == 1
    assert stats["ingest"]["done"] == 1
    assert stats["embed"]["pending"] == 1


def test_enqueue_many_returns_inserted_and_deduped(queue: Queue):
    queue.enqueue("ingest", {"f": "a"})  # one pre-existing pending
    inserted, deduped = queue.enqueue_many("ingest", [
        {"f": "a"},  # dedup
        {"f": "b"},  # new
        {"f": "c"},  # new
        {"f": "b"},  # dedup within the batch
    ])
    assert inserted == 2
    assert deduped == 2


def test_retry_failed_brings_them_back_to_pending(queue: Queue):
    job_id = queue.enqueue("ingest", {"f": "a"})
    queue.dequeue()
    queue.mark_failed(job_id, "nope")
    assert queue.stats()["ingest"]["failed"] == 1
    moved = queue.retry_failed()
    assert moved == 1
    assert queue.stats()["ingest"]["pending"] == 1


def test_clear_done_keeps_last_n(queue: Queue):
    for i in range(5):
        jid = queue.enqueue("ingest", {"f": str(i)})
        queue.dequeue()
        queue.mark_done(jid)
    removed = queue.clear_done(keep_last=2)
    assert removed == 3
    assert queue.stats()["ingest"]["done"] == 2


def test_list_pending_orders_by_priority(queue: Queue):
    queue.enqueue("ocr", {"f": "p3.pdf"})
    queue.enqueue("ingest", {"f": "p1.md"})
    queue.enqueue("embed", {"chunks": [1]})
    rows = queue.list_pending()
    assert [r.type for r in rows] == ["ingest", "embed", "ocr"]


# ── New job types (0.18.0): scan, remove, reconcile, vacuum ──────────────

def test_new_job_types_can_be_enqueued(queue: Queue):
    """The 4 new structural job types must round-trip through the queue."""
    from rtfm.core.queue import (P_SCAN, P_REMOVE, P_RECONCILE, P_VACUUM,
                                 P_INGEST, P_EMBED, P_OCR, P_USER)
    expected = {
        "scan": P_SCAN,
        "remove": P_REMOVE,
        "ingest": P_INGEST,
        "reconcile": P_RECONCILE,
        "vacuum": P_VACUUM,
        "embed": P_EMBED,
        "ocr": P_OCR,
    }
    for t, p in expected.items():
        # Use a unique payload so dedup doesn't reject duplicates.
        jid = queue.enqueue(t, {"k": t})
        assert jid is not None, f"failed to enqueue {t}"
    pending = queue.list_pending(limit=20)
    by_type = {j.type: j.priority for j in pending}
    assert by_type == expected
    # P0 is the explicit-user lane, lower than every default.
    assert P_USER < min(expected.values())


def test_priority_order_user_then_arrival_then_low(queue: Queue):
    """P_USER preempts; document work (scan/remove/ingest) shares one tier
    served in arrival order; embed/ocr stay strictly below."""
    from rtfm.core.queue import P_USER
    queue.enqueue("ocr",       {"k": 1})  # low
    queue.enqueue("embed",     {"k": 2})  # low
    queue.enqueue("reconcile", {"k": 3})  # mid
    queue.enqueue("ingest",    {"k": 4})  # P_DOC — arrival 1
    queue.enqueue("remove",    {"k": 5})  # P_DOC — arrival 2
    queue.enqueue("scan",      {"k": 6})  # P_DOC — arrival 3
    queue.enqueue("ingest",    {"urgent": True}, priority=P_USER)  # P0 — wins
    out = []
    while True:
        j = queue.dequeue()
        if j is None:
            break
        out.append(j.type)
    # P0 first; then the P_DOC tier in strict arrival order (ingest, remove,
    # scan — the order they were enqueued); then reconcile, embed, ocr.
    assert out == ["ingest", "ingest", "remove", "scan", "reconcile",
                   "embed", "ocr"]


def test_migration_from_legacy_3_type_check(tmp_path: Path):
    """An existing DB with the legacy CHECK constraint (ingest/embed/ocr
    only) must be transparently migrated when Queue opens it, preserving
    rows and accepting the new types afterwards."""
    db = tmp_path / "library.db"
    # Hand-craft the OLD schema (what 0.17 and earlier shipped).
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE work_queue (
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
        INSERT INTO work_queue (type, priority, payload) VALUES
            ('ingest', 1, '{"f":"old"}'),
            ('embed', 2, '{"chunks":[1]}');
    """)
    conn.commit()
    conn.close()

    # Old rows must be preserved AND the new types must be accepted.
    q = Queue(db)
    try:
        assert q.stats().get("ingest", {}).get("pending", 0) == 1
        assert q.stats().get("embed", {}).get("pending", 0) == 1
        new_id = q.enqueue("scan", {"root": "/x"})
        assert new_id is not None
        new2 = q.enqueue("reconcile", {})
        assert new2 is not None
    finally:
        q.close()


# ── Reaper / zombie-detection tests ─────────────────────────────────────


def test_reap_no_worker_marks_all_running_pending(queue: Queue):
    """When no worker is alive, every ``running`` row is a zombie."""
    j1 = queue.enqueue("ingest", {"f": "a"})
    j2 = queue.enqueue("ingest", {"f": "b"})
    queue.dequeue(); queue.dequeue()  # both now 'running'

    # rtfm_dir=None → treat all running as zombies
    result = queue.reap_zombies(rtfm_dir=None)
    assert result["requeued"] == 2
    assert result["failed"] == 0
    assert queue.stats()["ingest"]["pending"] == 2
    assert queue.stats()["ingest"].get("running", 0) == 0


def test_reap_failed_after_max_attempts(queue: Queue):
    """A zombie with ``attempts >= max_attempts`` bypasses pending and is
    marked failed — guards against infinite crash-loops."""
    queue.enqueue("ingest", {"f": "loops"})
    # Three crashes: dequeue increments attempts, then we kill the worker
    # so the row stays running.
    for _ in range(3):
        queue.dequeue()
        # simulate crash mid-job: row stays 'running'; bring it back manually
        queue._get_conn().execute(
            "UPDATE work_queue SET status='pending' WHERE id=?",
            (1,),
        )
    queue.dequeue()  # 4th dequeue, attempts now = 4, status='running'

    result = queue.reap_zombies(rtfm_dir=None, max_attempts=3)
    assert result["failed"] == 1
    assert queue.stats()["ingest"].get("failed", 0) == 1


def test_reap_dedups_running_twins(queue: Queue):
    """Two ``running`` rows with the same (type, payload) — keep one,
    drop the rest, so requeuing doesn't violate the dedup index."""
    queue.enqueue("ingest", {"f": "x"})
    queue.dequeue()
    # Force a second running row with identical payload — only possible
    # by hand-crafting; the dedup index only covers pending rows so this
    # can occur after a partial crash.
    queue._get_conn().execute(
        "INSERT INTO work_queue (type, priority, payload, status, attempts) "
        "VALUES ('ingest', 30, '{\"f\": \"x\"}', 'running', 1)"
    )
    assert queue.stats()["ingest"]["running"] == 2

    result = queue.reap_zombies(rtfm_dir=None)
    assert result["deduped"] >= 1
    assert queue.stats()["ingest"]["pending"] == 1
    assert queue.stats()["ingest"].get("running", 0) == 0


def test_reap_preserves_current_worker_job(queue: Queue, tmp_path: Path):
    """When a worker is alive and is on job X, X must NOT be reaped."""
    import json, os
    queue.enqueue("ingest", {"f": "active"})
    queue.enqueue("ingest", {"f": "zombie"})
    job_a = queue.dequeue()
    job_b = queue.dequeue()

    rtfm_dir = tmp_path / ".rtfm"
    rtfm_dir.mkdir(exist_ok=True)
    # Write a worker_state.json pointing to job_a; use our own PID as
    # "alive". The reaper's pid_alive(os.getpid()) is True by definition.
    state = {
        "pid": os.getpid(),
        "host": "test",
        "status": "busy",
        "current_job_id": job_a.id,
        "current_job_type": "ingest",
        "current_job_payload": {"f": "active"},
        "started_at": "2026-01-01T00:00:00Z",
        "last_update": "2026-01-01T00:00:00Z",
        "jobs_done": 0,
        "jobs_failed": 0,
        "installed_version": "test",
    }
    (rtfm_dir / "worker_state.json").write_text(json.dumps(state))

    result = queue.reap_zombies(rtfm_dir=rtfm_dir)
    assert result["requeued"] == 1  # only job_b
    # job_a still running, job_b back to pending
    assert queue.stats()["ingest"]["running"] == 1
    assert queue.stats()["ingest"]["pending"] == 1


def test_retry_failed_coalesces_duplicate_failures(queue: Queue):
    """Multiple failed rows with the same (type, payload) — common when
    a pile of similar files all errored — must coalesce on retry instead
    of raising on the dedup index."""
    # Three failed rows with identical payload (e.g. same EPUB enqueued
    # repeatedly by successive scans).
    for attempts in (1, 2, 3):
        queue._get_conn().execute(
            "INSERT INTO work_queue (type, priority, payload, status, attempts) "
            "VALUES ('ingest', 30, '{\"f\": \"dup\"}', 'failed', ?)",
            (attempts,),
        )
    # And a fourth, different payload, also failed.
    queue._get_conn().execute(
        "INSERT INTO work_queue (type, priority, payload, status, attempts) "
        "VALUES ('ingest', 30, '{\"f\": \"other\"}', 'failed', 1)"
    )
    assert queue.stats()["ingest"]["failed"] == 4

    n = queue.retry_failed()
    # Only the highest-attempts duplicate survives + the other payload.
    assert n == 2
    assert queue.stats()["ingest"]["pending"] == 2
    assert queue.stats()["ingest"].get("failed", 0) == 0


def test_retry_failed_skips_when_pending_twin_exists(queue: Queue):
    """A failed row whose twin is already pending must be dropped, not
    requeued — otherwise the unique index rejects."""
    queue._get_conn().execute(
        "INSERT INTO work_queue (type, priority, payload, status) "
        "VALUES ('ingest', 30, '{\"f\": \"both\"}', 'pending')"
    )
    queue._get_conn().execute(
        "INSERT INTO work_queue (type, priority, payload, status, attempts) "
        "VALUES ('ingest', 30, '{\"f\": \"both\"}', 'failed', 1)"
    )
    n = queue.retry_failed()
    assert n == 0  # the failed twin was dropped; the pending one stays
    assert queue.stats()["ingest"]["pending"] == 1
    assert queue.stats()["ingest"].get("failed", 0) == 0
