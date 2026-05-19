"""Tests for the priority-queue worker handlers (``rtfm.core.handlers``).

P1 ingest is exercised end-to-end in the smoke tests; here we cover
the contract pieces that matter for the queue:

  * After P1 finishes, follow-up P2 embed jobs are enqueued, batched
    at ``EMBED_BATCH_SIZE``.
  * P2 with an empty / unknown chunk-id list is a no-op (idempotent).
  * P2 actually writes embeddings into ``chunk_embeddings`` when the
    embeddings extra is installed.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from rtfm.core.handlers import (
    handle_ingest, handle_embed, EMBED_BATCH_SIZE, HANDLERS,
)
from rtfm.core.library import Library
from rtfm.core.queue import Queue, Job


def _fake_worker(db_path: Path):
    """Minimal stand-in for ``rtfm.core.worker.Worker`` — handlers only
    use ``worker.db_path``."""
    return SimpleNamespace(db_path=db_path)


def _make_md(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_handlers_dispatch_table_lists_ingest_and_embed():
    """Sanity: the dispatch table the worker reads exposes both
    job types Phase 2 ships."""
    assert "ingest" in HANDLERS
    assert "embed" in HANDLERS


def test_handle_ingest_enqueues_followup_embed_jobs(tmp_path: Path):
    """After a P1 ingest succeeds, the chunks of the new book get
    queued for P2 embedding, batched at ``EMBED_BATCH_SIZE``."""
    root = tmp_path / "src"
    _make_md(root / "doc.md", "# Title\n\nFirst paragraph.\n\n## Sub\n\nSecond paragraph.\n")
    db = tmp_path / "library.db"
    Library(str(db)).close()

    job = Job(id=1, type="ingest", priority=1, payload={
        "root": str(root), "corpus": "test", "filepath": "doc.md",
    }, status="running", created_at="", started_at=None,
       finished_at=None, error=None, attempts=1)
    handle_ingest(job, _fake_worker(db))

    # The book and its chunks exist
    lib = Library(str(db))
    try:
        books = lib.list_books(corpus="test")
        assert len(books) == 1
        slug = books[0]["slug"]
        chunk_ids = lib.chunk_ids_for_book(slug)
        assert len(chunk_ids) > 0
    finally:
        lib.close()

    # Embed jobs were enqueued, batched at EMBED_BATCH_SIZE
    q = Queue(db)
    try:
        pending = q.list_pending()
        embed_jobs = [j for j in pending if j.type == "embed"]
        assert embed_jobs, "P1 must enqueue follow-up P2 jobs"
        # Their payload chunk_ids sum back to the book's chunks
        all_ids = []
        for j in embed_jobs:
            assert len(j.payload["chunk_ids"]) <= EMBED_BATCH_SIZE
            all_ids.extend(j.payload["chunk_ids"])
        assert sorted(all_ids) == sorted(chunk_ids)
    finally:
        q.close()


def test_handle_embed_empty_payload_is_noop(tmp_path: Path):
    """A P2 job with no chunk_ids must not raise — the worker would
    then mark it ``failed`` for nothing."""
    db = tmp_path / "library.db"
    Library(str(db)).close()

    job = Job(id=1, type="embed", priority=2, payload={"chunk_ids": []},
              status="running", created_at="", started_at=None,
              finished_at=None, error=None, attempts=1)
    handle_embed(job, _fake_worker(db))  # must not raise


def test_handle_embed_skips_unknown_ids(tmp_path: Path):
    """Chunk ids that don't exist in the DB are silently skipped —
    the library uses an ``IN (...)`` filter."""
    db = tmp_path / "library.db"
    Library(str(db)).close()

    job = Job(id=1, type="embed", priority=2,
              payload={"chunk_ids": [9999, 10000]},
              status="running", created_at="", started_at=None,
              finished_at=None, error=None, attempts=1)
    handle_embed(job, _fake_worker(db))  # must not raise


@pytest.mark.skipif(
    pytest.importorskip("fastembed", reason="fastembed not installed") is None,
    reason="fastembed not installed",
)
def test_handle_embed_writes_embeddings(tmp_path: Path):
    """Full path: ingest a small file, run the auto-enqueued P2 job(s)
    through ``handle_embed``, then check ``chunk_embeddings`` is
    populated. This integration test pays the fastembed cold-start
    once but otherwise stays under ~30s."""
    pytest.importorskip("fastembed")

    root = tmp_path / "src"
    _make_md(root / "doc.md", "# Title\n\nSome searchable content here.\n")
    db = tmp_path / "library.db"
    Library(str(db)).close()

    # P1: ingest
    handle_ingest(
        Job(id=1, type="ingest", priority=1,
            payload={"root": str(root), "corpus": "test", "filepath": "doc.md"},
            status="running", created_at="", started_at=None,
            finished_at=None, error=None, attempts=1),
        _fake_worker(db),
    )

    # Drain the P2 jobs that P1 enqueued
    q = Queue(db)
    try:
        while True:
            job = q.dequeue()
            if job is None or job.type != "embed":
                break
            handle_embed(job, _fake_worker(db))
            q.mark_done(job.id)
    finally:
        q.close()

    import sqlite3
    conn = sqlite3.connect(db)
    n_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    n_emb = conn.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
    assert n_chunks > 0
    assert n_emb == n_chunks, f"every chunk must have an embedding ({n_emb}/{n_chunks})"
