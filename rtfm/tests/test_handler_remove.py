"""Tests for the P2 ``remove`` worker handler (``handle_remove``).

These exercise the inverse of P1 ``ingest``: dropping a book + its
chunks + the ``indexed_files`` tracking row in a single transactional
unit, dispatched through the worker queue like every other write.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from rtfm.core.handlers import handle_ingest, handle_remove
from rtfm.core.library import Library
from rtfm.core.queue import Job, Queue
from rtfm.core.sync import sync as sync_files


def _fake_worker(db_path: Path, log_sink: list[str] | None = None):
    """Minimal stand-in for ``rtfm.core.worker.Worker``. Handlers only
    touch ``worker.db_path`` and ``worker._log``."""
    sink = log_sink if log_sink is not None else []
    return SimpleNamespace(db_path=db_path, _log=lambda msg: sink.append(msg))


def _make_md(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_remove_deletes_book_and_chunks(tmp_path: Path):
    """A real sync indexes a markdown file; ``handle_remove`` then
    drops the book row, cascades to chunks, and clears the
    ``indexed_files`` tracking entry."""
    root = tmp_path / "src"
    _make_md(root / "doc.md", "# Title\n\nFirst paragraph.\n\n## Sub\n\nSecond paragraph.\n")
    db = tmp_path / "library.db"

    # Sync via the real sync path so the DB looks exactly like
    # production: book + chunks + indexed_files row.
    lib = Library(str(db))
    try:
        sync_files(lib, root, corpus="test", generate_embeddings=False)
        books = lib.list_books(corpus="test")
        assert len(books) == 1
        slug = books[0]["slug"]
        chunk_ids_before = lib.chunk_ids_for_book(slug)
        assert chunk_ids_before, "sync must produce at least one chunk"
        assert "doc.md" in lib.list_indexed_files(corpus="test")
    finally:
        lib.close()

    # The file is gone from disk — that is what a scan detects and what the
    # handler re-checks before destroying anything.
    (root / "doc.md").unlink()

    sink: list[str] = []
    job = Job(id=1, type="remove", priority=2,
              payload={"filepath": "doc.md", "corpus": "test"},
              status="running", created_at="", started_at=None,
              finished_at=None, error=None, attempts=1)
    handle_remove(job, _fake_worker(db, sink))

    lib = Library(str(db))
    try:
        assert lib.list_books(corpus="test") == []
        assert lib.chunk_ids_for_book(slug) == []
        assert "doc.md" not in lib.list_indexed_files(corpus="test")
    finally:
        lib.close()

    # Success log line matches the contract (no "not in index").
    assert any("remove [test] doc.md" == m for m in sink), sink


def test_remove_unknown_file_is_noop(tmp_path: Path):
    """A filepath not present in ``indexed_files`` must not raise —
    the worker would otherwise mark a perfectly legitimate event
    ``failed``. The handler logs a 'not in index' line instead."""
    db = tmp_path / "library.db"
    Library(str(db)).close()

    sink: list[str] = []
    job = Job(id=1, type="remove", priority=2,
              payload={"filepath": "ghost.md", "corpus": "test"},
              status="running", created_at="", started_at=None,
              finished_at=None, error=None, attempts=1)
    handle_remove(job, _fake_worker(db, sink))  # must not raise

    assert any("not in index" in m and "ghost.md" in m for m in sink), sink


def test_remove_via_worker_dispatch(tmp_path: Path):
    """End-to-end through the queue: P1 ingest enqueues + runs, then a
    ``remove`` job goes through dequeue → handler, mirroring how the
    worker loop drives the dispatch table in production."""
    root = tmp_path / "src"
    _make_md(root / "doc.md", "# Title\n\nSome body content here.\n")
    db = tmp_path / "library.db"
    Library(str(db)).close()

    # P1: ingest via the handler so the queue/library look like the
    # worker would have produced them.
    handle_ingest(
        Job(id=1, type="ingest", priority=1,
            payload={"root": str(root), "corpus": "test", "filepath": "doc.md"},
            status="running", created_at="", started_at=None,
            finished_at=None, error=None, attempts=1),
        _fake_worker(db),
    )

    # Sanity: the book exists before we remove it.
    lib = Library(str(db))
    try:
        assert len(lib.list_books(corpus="test")) == 1
    finally:
        lib.close()

    # Enqueue the remove job and run one worker tick on it. We dequeue
    # in a loop because P1 also queued P2 embed jobs; we only act on
    # the ``remove`` one (same pattern as the embed-drain test).
    (root / "doc.md").unlink()

    q = Queue(db)
    try:
        q.enqueue("remove", {"filepath": "doc.md", "corpus": "test"})
        seen_remove = False
        while True:
            job = q.dequeue()
            if job is None:
                break
            if job.type == "remove":
                handle_remove(job, _fake_worker(db))
                q.mark_done(job.id)
                seen_remove = True
                break
            q.mark_done(job.id)
        assert seen_remove, "remove job must reach the dispatch loop"
    finally:
        q.close()

    lib = Library(str(db))
    try:
        assert lib.list_books(corpus="test") == []
        assert "doc.md" not in lib.list_indexed_files(corpus="test")
    finally:
        lib.close()


class TestOneLastLookBeforeDestroying:
    """A removal job carries out a decision the scan made earlier.

    Queues run minutes or days behind. The file may have come back since, or
    the job may predate a fix to the detection that queued it — as happened
    here: jobs enqueued by a buggy scan were still sitting in queues, each one
    ready to destroy a live file's chunks and its embeddings. One stat before
    the delete is the difference between an out-of-date index and a destroyed
    one.
    """

    def test_a_file_that_is_back_on_disk_is_kept(self, tmp_path):
        from rtfm.core.handlers import handle_remove
        from rtfm.core.library import Library
        from rtfm.core.queue import Job

        root = tmp_path / "src"
        root.mkdir()
        (root / "alive.md").write_text("still here\n")

        db = tmp_path / "library.db"
        lib = Library(str(db))
        lib.set_sync_root("code", str(root))
        lib.update_indexed_file(filepath="alive.md", file_hash="h",
                                corpus="code", book_slug="alive")
        lib.close()

        worker = _StubWorker(db)
        handle_remove(
            Job(id=1, type="remove", priority=10,
                payload={"filepath": "alive.md", "corpus": "code"},
                status="running", created_at="", started_at=None,
                finished_at=None, error=None, attempts=1),
            worker)

        lib = Library(str(db))
        try:
            assert "alive.md" in lib.list_indexed_files(corpus="code")
        finally:
            lib.close()
        assert any("kept" in line for line in worker.logs)

    def test_a_genuinely_deleted_file_is_still_removed(self, tmp_path):
        from rtfm.core.handlers import handle_remove
        from rtfm.core.library import Library
        from rtfm.core.queue import Job

        root = tmp_path / "src"
        root.mkdir()
        db = tmp_path / "library.db"
        lib = Library(str(db))
        lib.set_sync_root("code", str(root))
        lib.update_indexed_file(filepath="gone.md", file_hash="h",
                                corpus="code", book_slug="gone")
        lib.close()

        worker = _StubWorker(db)
        handle_remove(
            Job(id=1, type="remove", priority=10,
                payload={"filepath": "gone.md", "corpus": "code"},
                status="running", created_at="", started_at=None,
                finished_at=None, error=None, attempts=1),
            worker)

        lib = Library(str(db))
        try:
            assert "gone.md" not in lib.list_indexed_files(corpus="code")
        finally:
            lib.close()


class _StubWorker:
    def __init__(self, db_path):
        self.db_path = db_path
        self.logs: list[str] = []

    def _log(self, msg):
        self.logs.append(msg)
