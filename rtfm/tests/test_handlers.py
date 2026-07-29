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

import os
import time
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


def test_handlers_dispatch_table_lists_all_job_types():
    """Sanity: the dispatch table the worker reads exposes every
    job type the queue accepts."""
    assert set(HANDLERS) == {
        "scan", "remove", "ingest", "reconcile", "vacuum", "embed", "ocr",
    }


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


def test_looks_like_partial_write_detects_change(tmp_path: Path):
    """A file whose size changed since the recorded stamp was still being
    written under us — a parse failure on it is not a real failure."""
    from rtfm.core import handlers
    p = tmp_path / "dl.pdf"
    p.write_bytes(b"partial")
    st = p.stat()
    p.write_bytes(b"partial-and-more")  # grew
    assert handlers._looks_like_partial_write(p, st.st_mtime, st.st_size) is True


def test_looks_like_partial_write_false_for_settled(tmp_path: Path, monkeypatch):
    """A file untouched long before we parsed it is a genuine failure — and
    we must not even pay the observation sleep for it."""
    from rtfm.core import handlers
    p = tmp_path / "old.pdf"
    p.write_bytes(b"complete")
    old = time.time() - (handlers.INGEST_SETTLE_GRACE_SECONDS + 10)
    os.utime(p, (old, old))
    st = p.stat()
    monkeypatch.setattr(
        handlers.time, "sleep",
        lambda *_: (_ for _ in ()).throw(AssertionError("must not sleep")))
    assert handlers._looks_like_partial_write(p, st.st_mtime, st.st_size) is False


def test_looks_like_partial_write_detects_growth_during_observation(
        tmp_path: Path, monkeypatch):
    """Unchanged at first stat but still growing across the short
    observation window → still being written."""
    from rtfm.core import handlers
    p = tmp_path / "recent.pdf"
    p.write_bytes(b"partial")
    st = p.stat()  # fresh mtime, within grace

    def grow(_seconds):
        p.write_bytes(b"partial-plus-more")

    monkeypatch.setattr(handlers.time, "sleep", grow)
    assert handlers._looks_like_partial_write(p, st.st_mtime, st.st_size) is True


def test_handle_ingest_requeues_on_partial_write(tmp_path: Path, monkeypatch):
    """A parse error on a file that changed mid-parse re-queues the ingest
    instead of raising (which would mark it failed for good)."""
    from rtfm.core import handlers
    db = tmp_path / "library.db"
    Library(str(db)).close()
    root = tmp_path / "src"; root.mkdir()
    f = root / "book.pdf"
    f.write_bytes(b"%PDF-partial")

    class _FakeLib:
        def __init__(self, *a, **k): pass
        def set_sync_root(self, *a, **k): pass
        def list_indexed_files(self, *a, **k): return {}
        def ingest(self, *a, **k):
            f.write_bytes(b"%PDF-partial-and-then-more")  # completes mid-parse
            raise ValueError("PDFium: Data format error")
        def close(self): pass

    monkeypatch.setattr(handlers, "Library", _FakeLib)

    logs: list[str] = []
    worker = SimpleNamespace(db_path=db, _log=logs.append)
    job = Job(id=1, type="ingest", priority=1, payload={
        "root": str(root), "corpus": "t", "filepath": "book.pdf",
    }, status="running", created_at="", started_at=None,
       finished_at=None, error=None, attempts=1)

    handle_ingest(job, worker)  # must NOT raise

    q = Queue(db)
    try:
        pend = [j for j in q.list_pending(limit=100) if j.type == "ingest"]
        assert len(pend) == 1
        assert pend[0].payload["filepath"] == "book.pdf"
    finally:
        q.close()
    assert any("re-queued" in m for m in logs)


def test_handle_ingest_reraises_genuine_failure(tmp_path: Path, monkeypatch):
    """A parse error on a settled (unchanged) file propagates — it is a real
    failure the queue must record."""
    from rtfm.core import handlers
    db = tmp_path / "library.db"
    Library(str(db)).close()
    root = tmp_path / "src"; root.mkdir()
    f = root / "book.pdf"
    f.write_bytes(b"%PDF-broken")
    old = time.time() - (handlers.INGEST_SETTLE_GRACE_SECONDS + 10)
    os.utime(f, (old, old))

    class _FakeLib:
        def __init__(self, *a, **k): pass
        def set_sync_root(self, *a, **k): pass
        def list_indexed_files(self, *a, **k): return {}
        def ingest(self, *a, **k):
            raise ValueError("PDFium: Data format error")
        def close(self): pass

    monkeypatch.setattr(handlers, "Library", _FakeLib)
    worker = SimpleNamespace(db_path=db, _log=lambda m: None)
    job = Job(id=1, type="ingest", priority=1, payload={
        "root": str(root), "corpus": "t", "filepath": "book.pdf",
    }, status="running", created_at="", started_at=None,
       finished_at=None, error=None, attempts=1)

    with pytest.raises(ValueError):
        handle_ingest(job, worker)


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


def test_pdf_is_scan_uses_chars_per_page():
    """Deterministic scan test: chars/page below threshold = scan."""
    from rtfm.core.handlers import _pdf_is_scan, SCAN_CHARS_PER_PAGE
    # 499-page textbook scan, ~2 chars/page → scan
    assert _pdf_is_scan({"chars": 950, "pages": 499, "chunks": 1}) is True
    # born-digital paper, ~2000 chars/page → not a scan
    assert _pdf_is_scan({"chars": 40000, "pages": 20, "chunks": 30}) is False
    # exactly at threshold is not a scan (strict <)
    assert _pdf_is_scan({"chars": SCAN_CHARS_PER_PAGE * 10,
                         "pages": 10, "chunks": 5}) is False


def test_pdf_is_scan_falls_back_to_zero_chunks_without_pages():
    """When page_count is unknown (old DB / parser), fall back to the
    zero-chunk signal."""
    from rtfm.core.handlers import _pdf_is_scan
    assert _pdf_is_scan({"chars": 0, "pages": None, "chunks": 0}) is True
    assert _pdf_is_scan({"chars": 500, "pages": None, "chunks": 3}) is False
    assert _pdf_is_scan({"chars": 0, "pages": 0, "chunks": 0}) is True


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


class TestOCRSplit:
    """Tests for the page-range-split OCR (P3) path."""

    def test_enqueue_ocr_jobs_splits_by_pages(self, tmp_path):
        from rtfm.core.handlers import enqueue_ocr_jobs, PAGES_PER_OCR_JOB
        from rtfm.core.library import Library
        from rtfm.core.queue import Queue
        db = tmp_path / "library.db"
        Library(str(db)).close()
        q = Queue(str(db))
        try:
            # 130 pages, 50/job → 3 tranches (1-50, 51-100, 101-130)
            n = enqueue_ocr_jobs(q, "/root", "c", "big.pdf", 130)
            assert n == 3
            ranges = sorted((j.payload["page_start"], j.payload["page_end"])
                            for j in q.list_pending() if j.type == "ocr")
            assert ranges == [(1, 50), (51, 100), (101, 130)]
        finally:
            q.close()

    def test_enqueue_ocr_jobs_zero_pages_noop(self, tmp_path):
        from rtfm.core.handlers import enqueue_ocr_jobs
        from rtfm.core.library import Library
        from rtfm.core.queue import Queue
        db = tmp_path / "library.db"
        Library(str(db)).close()
        q = Queue(str(db))
        try:
            assert enqueue_ocr_jobs(q, "/root", "c", "x.pdf", 0) == 0
        finally:
            q.close()

    def test_handle_ocr_appends_tranche_idempotently(self, tmp_path, monkeypatch):
        """handle_ocr OCRs a page range and appends chunks; re-running
        the same tranche replaces (not duplicates) its chunks."""
        from rtfm.core import handlers
        from rtfm.core.library import Library
        from rtfm.core.queue import Job

        root = tmp_path / "src"
        root.mkdir()
        pdf = root / "scan.pdf"
        pdf.write_bytes(b"%PDF-1.4\nfake\n%%EOF\n")
        db = tmp_path / ".rtfm" / "library.db"
        db.parent.mkdir(parents=True)
        Library(str(db)).close()
        (tmp_path / ".rtfm" / "config.json").write_text(
            '{"ocr_backend":"tesseract","ocr_langs":"eng"}')

        # Mock the OCR extraction — return fake text for pages 1-2.
        def fake_tess(path, langs="eng", page_start=1, page_end=None, scale=2.0):
            return [{"page": p, "text": f"ocr text page {p}\n\nsecond para {p}"}
                    for p in range(page_start, (page_end or 2) + 1)]
        monkeypatch.setattr(handlers, "extract_with_tesseract", fake_tess, raising=False)
        # patch the name imported inside handle_ocr
        import rtfm.parsers.pdf as pdfmod
        monkeypatch.setattr(pdfmod, "extract_with_tesseract", fake_tess)

        worker = SimpleNamespace(db_path=db)
        job = Job(id=1, type="ocr", priority=3,
                  payload={"root": str(root), "corpus": "test",
                           "filepath": "scan.pdf", "page_start": 1, "page_end": 2},
                  status="running", created_at="", started_at=None,
                  finished_at=None, error=None, attempts=1)
        handlers.handle_ocr(job, worker)

        import sqlite3
        c = sqlite3.connect(db)
        n1 = c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        c.close()
        assert n1 > 0

        # Re-run the same tranche → idempotent (count unchanged, no dup).
        handlers.handle_ocr(job, worker)
        c = sqlite3.connect(db)
        n2 = c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        c.close()
        assert n2 == n1
