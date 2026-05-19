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
