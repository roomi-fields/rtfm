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
    handle_ingest, handle_embed, handle_ocr,
    EMBED_BATCH_SIZE, HANDLERS,
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


def test_handlers_dispatch_table_lists_ingest_embed_ocr():
    """Sanity: the dispatch table the worker reads exposes every
    job type phases 1-3 ship."""
    assert set(HANDLERS) == {"ingest", "embed", "ocr"}


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


def test_handle_ingest_enqueues_ocr_for_zero_chunk_pdf_with_fallback(
    tmp_path: Path, monkeypatch
):
    """A PDF that produces 0 chunks AND ``ocr_fallback: true`` in
    config.json must auto-enqueue a P3 OCR job (and skip the P2
    follow-up). Regression for the "scans never get OCR'd" case."""
    import json as _json
    from unittest.mock import patch

    root = tmp_path / "src"
    pdf = root / "scan.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4\nfake\n%%EOF\n")  # not a real PDF
    db = tmp_path / ".rtfm" / "library.db"
    db.parent.mkdir(parents=True)
    Library(str(db)).close()
    # ocr_fallback on
    (tmp_path / ".rtfm" / "config.json").write_text(
        _json.dumps({"ocr_fallback": True})
    )

    # Mock lib.ingest to return 0 chunks (=scan suspect)
    with patch.object(Library, "ingest", return_value={"chunks": 0, "chars": 0}):
        handle_ingest(
            Job(id=1, type="ingest", priority=1,
                payload={"root": str(root), "corpus": "test",
                         "filepath": "scan.pdf"},
                status="running", created_at="", started_at=None,
                finished_at=None, error=None, attempts=1),
            _fake_worker(db),
        )

    q = Queue(db)
    try:
        pending = q.list_pending()
        # Exactly one P3 OCR job, no P2.
        ocr_jobs = [j for j in pending if j.type == "ocr"]
        embed_jobs = [j for j in pending if j.type == "embed"]
        assert len(ocr_jobs) == 1, f"expected 1 P3, got {len(ocr_jobs)}"
        assert ocr_jobs[0].payload["filepath"] == "scan.pdf"
        assert not embed_jobs, "no P2 when P3 takes over"
    finally:
        q.close()


def test_handle_ingest_no_ocr_when_fallback_disabled(tmp_path: Path):
    """Same as above but with ``ocr_fallback: false`` (or absent) —
    no P3 is enqueued. The PDF stays unindexed; the user must opt in
    explicitly via ``rtfm sync --ocr``."""
    import json as _json
    from unittest.mock import patch

    root = tmp_path / "src"
    pdf = root / "scan.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4\nfake\n%%EOF\n")
    db = tmp_path / ".rtfm" / "library.db"
    db.parent.mkdir(parents=True)
    Library(str(db)).close()
    # No config.json → ocr_fallback defaults to false

    with patch.object(Library, "ingest", return_value={"chunks": 0, "chars": 0}):
        handle_ingest(
            Job(id=1, type="ingest", priority=1,
                payload={"root": str(root), "corpus": "test",
                         "filepath": "scan.pdf"},
                status="running", created_at="", started_at=None,
                finished_at=None, error=None, attempts=1),
            _fake_worker(db),
        )

    q = Queue(db)
    try:
        pending = q.list_pending()
        assert not [j for j in pending if j.type == "ocr"], \
            "ocr_fallback off → never auto-enqueue P3"
    finally:
        q.close()


def test_handle_ocr_rejects_non_pdf(tmp_path: Path):
    """P3 OCR is PDF-only — non-PDF payload must raise before touching
    marker, so the worker marks the job ``failed`` cleanly."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.md").write_text("# Hello", encoding="utf-8")
    db = tmp_path / "library.db"
    Library(str(db)).close()

    job = Job(id=1, type="ocr", priority=3,
              payload={"root": str(src), "corpus": "test",
                       "filepath": "foo.md"},
              status="running", created_at="", started_at=None,
              finished_at=None, error=None, attempts=1)
    with pytest.raises(ValueError, match="only handles .pdf"):
        handle_ocr(job, _fake_worker(db))


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
