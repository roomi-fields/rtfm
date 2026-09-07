"""What the index keeps about its own work, and for how long.

Two files grow beside every index and neither is content. One is the record
of jobs run — useful for a month, ruinous for ever: one project held 766 000
finished rows, 640 MB, and a failure count that still reported a defect
fixed four days earlier. A counter that never forgets is one nobody reads.

The other is the write-ahead file, and it is *not* a log. It holds no
history: once checkpointed, its content is already in the database and what
remains is a high-water mark SQLite never hands back on its own. One project
carried 4.37 GB of it beside a 4.36 GB database — of which three pages were
live. There is nothing there to keep for two weeks; there is only space to
give back.
"""
from __future__ import annotations

import sqlite3

import pytest

from rtfm.core.handlers import (
    JOB_HISTORY_DAYS, WAL_TRUNCATE_ABOVE_BYTES, _forget_old_jobs,
)
from rtfm.core.queue import Queue


class _Worker:
    def __init__(self, db_path):
        self.db_path = db_path
        self.lines: list[str] = []

    def _log(self, msg):
        self.lines.append(msg)


@pytest.fixture
def queue_with_history(tmp_path):
    """A queue holding old and recent work, finished and unfinished."""
    db = tmp_path / "library.db"
    q = Queue(db)
    q.close()
    conn = sqlite3.connect(db, isolation_level=None)
    rows = [
        ("ingest", "done", "-400 days"),
        ("ingest", "done", "-90 days"),
        ("embed", "failed", "-60 days"),
        ("embed", "done", "-2 days"),
        ("ingest", "failed", "-1 days"),
    ]
    for i, (kind, status, age) in enumerate(rows):
        conn.execute(
            "INSERT INTO work_queue (type, priority, payload, status, "
            "created_at, finished_at) VALUES (?,10,?,?,datetime('now',?),"
            "datetime('now',?))", (kind, f'{{"n":{i}}}', status, age, age))
    # Work that has not finished is the queue itself, whatever its age.
    conn.execute(
        "INSERT INTO work_queue (type, priority, payload, status, created_at) "
        "VALUES ('ingest',10,'{\"n\":99}','pending',datetime('now','-400 days'))")
    conn.commit()
    return db, conn


class TestForgettingFinishedWork:

    def test_old_finished_jobs_are_dropped(self, queue_with_history):
        db, conn = queue_with_history
        assert _forget_old_jobs(conn, _Worker(db)) == 3

    def test_recent_work_is_kept(self, queue_with_history):
        db, conn = queue_with_history
        _forget_old_jobs(conn, _Worker(db))
        kept = conn.execute(
            "SELECT COUNT(*) FROM work_queue WHERE status IN ('done','failed')"
        ).fetchone()[0]
        assert kept == 2, "a month of work must still be inspectable"

    def test_unfinished_work_is_never_dropped(self, queue_with_history):
        db, conn = queue_with_history
        _forget_old_jobs(conn, _Worker(db))
        assert conn.execute(
            "SELECT COUNT(*) FROM work_queue WHERE status='pending'"
        ).fetchone()[0] == 1, "a pending job is the queue, not its history"

    def test_a_second_pass_finds_nothing(self, queue_with_history):
        db, conn = queue_with_history
        _forget_old_jobs(conn, _Worker(db))
        assert _forget_old_jobs(conn, _Worker(db)) == 0

    def test_a_month_is_what_is_kept(self):
        assert JOB_HISTORY_DAYS == 30

    def test_a_database_with_no_queue_is_not_an_error(self, tmp_path):
        db = tmp_path / "vide.db"
        conn = sqlite3.connect(db)
        worker = _Worker(db)
        assert _forget_old_jobs(conn, worker) == 0
        assert worker.lines, "and it says why"


class TestTheWriteAheadFile:

    def _grow(self, tmp_path, target_bytes):
        """A database whose journal has grown past *target_bytes*."""
        db = tmp_path / "library.db"
        q = Queue(db)
        q.close()
        conn = sqlite3.connect(db, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA journal_size_limit=-1")   # as it was before the fix
        conn.execute("PRAGMA wal_autocheckpoint=0")    # let it grow
        conn.execute("CREATE TABLE gros (x)")
        blob = b"x" * 65536
        wal = tmp_path / "library.db-wal"
        while not wal.exists() or wal.stat().st_size <= target_bytes:
            conn.executemany("INSERT INTO gros VALUES (?)", [(blob,)] * 64)
        return db, conn, wal

    def _reconcile(self, db):
        from rtfm.core.handlers import handle_reconcile
        from rtfm.core.queue import Job
        worker = _Worker(db)
        handle_reconcile(Job(id=1, type="reconcile", priority=40, payload={},
                             status="running", created_at="", started_at=None,
                             finished_at=None, error=None, attempts=1), worker)
        return worker

    def test_a_reconcile_hands_the_space_back(self, tmp_path, monkeypatch):
        """The measured shape: a journal grown by work long finished,
        holding almost nothing, that nothing was ever going to reclaim —
        4.37 GB beside a 4.36 GB database, three pages of it live."""
        import rtfm.core.handlers as handlers
        monkeypatch.setattr(handlers, "WAL_TRUNCATE_ABOVE_BYTES", 1 << 20)
        db, conn, wal = self._grow(tmp_path, 4 << 20)
        try:
            grown = wal.stat().st_size
            worker = self._reconcile(db)
            assert wal.stat().st_size < grown
            assert wal.stat().st_size <= (1 << 20)
            assert any("journal" in ln for ln in worker.lines)
        finally:
            conn.close()

    def test_a_small_journal_is_left_alone(self, tmp_path):
        """Truncating it would only make the next writer grow it again."""
        db = tmp_path / "library.db"
        q = Queue(db)
        q.close()
        worker = self._reconcile(db)
        assert not any("journal" in ln for ln in worker.lines)

    def test_new_connections_bound_the_journal(self, tmp_path):
        """The cause, not the symptom: with no limit SQLite keeps the file
        at its high-water mark for the life of the database."""
        from rtfm.core.library import Library

        db = tmp_path / "library.db"
        lib = Library(db)
        try:
            limit = lib._get_conn().execute(
                "PRAGMA journal_size_limit").fetchone()[0]
        finally:
            lib.close()
        assert 0 < limit <= 128 * 1024 * 1024

        q = Queue(tmp_path / "autre.db")
        try:
            assert 0 < q._get_conn().execute(
                "PRAGMA journal_size_limit").fetchone()[0] <= 128 * 1024 * 1024
        finally:
            q.close()

    def test_the_limit_actually_caps_a_growing_journal(self, tmp_path):
        """End to end: a writer going through RTFM cannot leave a journal
        larger than the bound, whatever it does."""
        from rtfm.core.library import Library

        db = tmp_path / "library.db"
        lib = Library(db)
        conn = lib._get_conn()
        conn.execute("CREATE TABLE gros (x)")
        blob = b"x" * 65536
        for _ in range(40):
            conn.executemany("INSERT INTO gros VALUES (?)", [(blob,)] * 64)
            conn.commit()
        wal = tmp_path / "library.db-wal"
        size = wal.stat().st_size if wal.exists() else 0
        lib.close()
        assert size <= 128 * 1024 * 1024, f"journal reached {size / 1e6:.0f}M"


class TestHistoryIsReachableByPath:
    """``rtfm history`` used to take the internal identity and nothing else.

    ``CLAUDE.md`` is filed under ``default--claude`` — a name nobody would
    guess, and one that for files indexed before 0.30 does not even carry
    the extension. Measured on a workshop of sixteen repositories: every
    attempt answered "No version history" while fifty versions of the file
    sat in the index, and the feature was written off as not working.
    """

    @pytest.fixture
    def indexed(self, tmp_path):
        from rtfm.core.library import Library
        root = tmp_path / "projet"
        root.mkdir()
        doc = root / "CLAUDE.md"
        doc.write_text("# Consignes\n\nUn premier etat.\n" * 10)
        db = tmp_path / "library.db"
        lib = Library(db)
        # The legacy identity: the extension is gone, as it was before 0.30.
        lib.ingest(doc, corpus="default",
                   metadata={"book_slug": "default--claude",
                             "source_file": "CLAUDE.md"})
        lib.set_sync_root("default", str(root))
        lib.update_indexed_file("CLAUDE.md", "h1", "default", "default--claude",
                                file_size=doc.stat().st_size)
        lib.save_file_version("default--claude", "h1")
        lib.close()
        return root, db

    def _history(self, db, source):
        import argparse
        import io
        from contextlib import redirect_stdout
        from rtfm.cli import cmd_history
        out = io.StringIO()
        with redirect_stdout(out):
            cmd_history(argparse.Namespace(db=str(db), source=source,
                                           version=None, format="text"))
        return out.getvalue()

    def test_a_path_finds_the_history(self, indexed):
        root, db = indexed
        assert "1 versions" in self._history(db, "CLAUDE.md")

    def test_an_absolute_path_finds_it_too(self, indexed):
        root, db = indexed
        assert "1 versions" in self._history(db, str(root / "CLAUDE.md"))

    def test_the_identity_still_works(self, indexed):
        _, db = indexed
        assert "1 versions" in self._history(db, "default--claude")

    def test_an_unknown_file_says_so(self, indexed):
        _, db = indexed
        assert "No version history" in self._history(db, "jamais-vu.md")
