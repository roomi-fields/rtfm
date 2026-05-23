"""Tests for the P4 reconcile job handler (``handle_reconcile``).

The handler is a thin wrapper around
:func:`rtfm.core.reconcile.reconcile` — the deep logic is covered by
``test_reconcile.py``. Here we only check the handler-specific contract:

  * orphan embeddings are gone after the handler runs;
  * ``payload={"vacuum": True}`` enqueues a follow-up P4 ``vacuum`` job
    *only when something was purged*;
  * ``payload={"vacuum": True}`` on a clean DB enqueues nothing — we
    don't VACUUM for free.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from rtfm.core.handlers import handle_reconcile
from rtfm.core.library import Library
from rtfm.core.queue import Queue, Job


def _fake_worker(db_path: Path):
    """Stand-in for ``rtfm.core.worker.Worker`` — ``handle_reconcile``
    only needs ``db_path`` and ``_log``."""
    return SimpleNamespace(db_path=db_path, _log=lambda msg: None)


def _seed_with_orphan(db: Path) -> list[int]:
    """Create a tiny DB with 3 chunks; chunks 1+2 get embeddings, then
    chunk 2 is deleted (with FK OFF) so its embedding becomes an orphan.
    Returns the chunk row ids."""
    lib = Library(str(db))
    conn = lib._get_conn()
    conn.execute("INSERT INTO books (slug, title, corpus) VALUES ('b','B','c')")
    bid = conn.execute("SELECT id FROM books WHERE slug='b'").fetchone()["id"]
    for cid in (1, 2, 3):
        conn.execute(
            "INSERT INTO chunks (chunk_id, book_id, content, content_chars) "
            "VALUES (?, ?, ?, ?)", (f"ck{cid}", bid, f"content {cid}", 9))
    rows = conn.execute("SELECT id FROM chunks ORDER BY id").fetchall()
    ids = [r["id"] for r in rows]
    for cid in ids[:2]:
        conn.execute(
            "INSERT INTO chunk_embeddings (chunk_id, model, embedding) "
            "VALUES (?, 'm', ?)", (cid, b"\x00\x00\x00\x00"))
    conn.commit()
    # Force FK off to recreate the historical orphan condition (modern
    # FK-ON would cascade-delete the embedding too). SQLite ignores the
    # PRAGMA inside an open transaction, so the commit above matters.
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM chunks WHERE id = ?", (ids[1],))
    conn.commit()
    lib.close()
    return ids


def _seed_clean(db: Path) -> None:
    """Create a tiny DB with 1 chunk + 1 embedding — no orphans, nothing
    to re-queue (the chunk already has an embedding)."""
    lib = Library(str(db))
    conn = lib._get_conn()
    conn.execute("INSERT INTO books (slug, title, corpus) VALUES ('b','B','c')")
    bid = conn.execute("SELECT id FROM books WHERE slug='b'").fetchone()["id"]
    conn.execute(
        "INSERT INTO chunks (chunk_id, book_id, content, content_chars) "
        "VALUES (?, ?, ?, ?)", ("ck1", bid, "content 1", 9))
    cid = conn.execute("SELECT id FROM chunks").fetchone()["id"]
    conn.execute(
        "INSERT INTO chunk_embeddings (chunk_id, model, embedding) "
        "VALUES (?, 'm', ?)", (cid, b"\x00\x00\x00\x00"))
    conn.commit()
    lib.close()


def _orphan_count(db: Path) -> int:
    from rtfm.core.reconcile import count_orphan_embeddings
    lib = Library(str(db))
    try:
        return count_orphan_embeddings(lib._get_conn())
    finally:
        lib.close()


def _reconcile_job(payload: dict | None = None) -> Job:
    return Job(id=1, type="reconcile", priority=4, payload=payload or {},
               status="running", created_at="", started_at=None,
               finished_at=None, error=None, attempts=1)


def test_reconcile_purges_orphans(tmp_path: Path):
    """After ``handle_reconcile`` runs on a DB with orphan embeddings,
    the orphan count must be zero."""
    db = tmp_path / "library.db"
    _seed_with_orphan(db)
    assert _orphan_count(db) == 1, "fixture should have created one orphan"

    handle_reconcile(_reconcile_job(), _fake_worker(db))

    assert _orphan_count(db) == 0


def test_reconcile_enqueues_vacuum_when_requested(tmp_path: Path):
    """With ``payload={'vacuum': True}`` AND orphans actually purged, a
    P4 ``vacuum`` job lands in the queue with the expected reason."""
    db = tmp_path / "library.db"
    _seed_with_orphan(db)

    handle_reconcile(_reconcile_job({"vacuum": True}), _fake_worker(db))

    q = Queue(str(db))
    try:
        pending = q.list_pending()
        vacuum_jobs = [j for j in pending if j.type == "vacuum"]
        assert len(vacuum_jobs) == 1, \
            f"expected one vacuum job, got {len(vacuum_jobs)}"
        assert vacuum_jobs[0].payload == {"reason": "after-reconcile"}
    finally:
        q.close()


def test_reconcile_no_vacuum_when_nothing_purged(tmp_path: Path):
    """``payload={'vacuum': True}`` on a clean DB must NOT enqueue a
    vacuum — vacuuming an untouched file is pure overhead."""
    db = tmp_path / "library.db"
    _seed_clean(db)
    assert _orphan_count(db) == 0

    handle_reconcile(_reconcile_job({"vacuum": True}), _fake_worker(db))

    q = Queue(str(db))
    try:
        pending = q.list_pending()
        assert not [j for j in pending if j.type == "vacuum"], \
            "no orphans purged → must not enqueue a vacuum"
    finally:
        q.close()
