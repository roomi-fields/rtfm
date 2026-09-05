"""A project's database can be replaced while RTFM holds it open.

Reported from a fleet of sixteen agents, each confined to its own repository
and reading its neighbours through RTFM alone. Every repository republishes
a copy of itself into a shared directory, and each publication re-creates the
copy's index. Fourteen of the fifteen published indexes sat frozen at exactly
two indexed documents — the two prose files at the repository root — while
7 110 jobs waited in their queues and 193 unlinked file descriptors stayed
open in the supervisor. No log carried an error. The scan line printed every
minute throughout.

The cause is that unlinking a file does not close it. A connection opened
before the replacement keeps reading and writing the old inode, which no
longer has a name; a connection opened afterwards, by path, gets the new
file. The supervisor holds its queue connection for its whole life, and the
handlers open theirs per job — so the two halves ended up on different files
and stayed there:

* the scan handler wrote its findings into the live file;
* the dispatcher looked for work in the dead one, found only the periodic
  scans it had queued there itself, and never took a single ingest job.

Self-sustaining, and silent in both directions. Worse than a stall: the
index still answered, from the two documents it had, with a relevance score
and no indication that the code had never been read.

The fix is to notice. Device and inode say "another file with the same name"
where a path comparison cannot.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from rtfm.core import supervisor as sup_mod
from rtfm.core.library import Library
from rtfm.core.queue import Queue
from rtfm.core.supervisor import Supervisor, _file_identity


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(sup_mod, "_RTFM_HOME", tmp_path)
    monkeypatch.setattr(sup_mod, "SUPERVISOR_LOCK", tmp_path / "supervisor.lock")
    monkeypatch.setattr(sup_mod, "SUPERVISOR_STATE",
                        tmp_path / "supervisor_state.json")
    monkeypatch.setattr(sup_mod, "SUPERVISOR_STOP", tmp_path / "supervisor.stop")
    return tmp_path


def _make_project(home: Path, name: str = "proj") -> Path:
    rtfm_dir = home / name / ".rtfm"
    rtfm_dir.mkdir(parents=True)
    Library(str(rtfm_dir / "library.db")).close()
    return rtfm_dir


def _replace_database(rtfm_dir: Path) -> None:
    """Do what re-running ``rtfm init`` on a wiped directory does: unlink
    the database and create a fresh one at the same path."""
    for suffix in ("", "-wal", "-shm"):
        Path(str(rtfm_dir / "library.db") + suffix).unlink(missing_ok=True)
    Library(str(rtfm_dir / "library.db")).close()


class TestFileIdentity:
    def test_a_replaced_file_is_a_different_file(self, tmp_path):
        path = tmp_path / "library.db"
        path.write_text("one")
        before = _file_identity(path)
        # Replacement, not truncation: a fresh file put at the same path.
        # Swapped in rather than unlinked-then-created, so the old inode is
        # still allocated and cannot be handed back — which is exactly the
        # situation the check runs in, the supervisor holding the previous
        # file open. Unlinking here with nothing holding it would let the
        # filesystem reuse the number at once and measure the allocator
        # instead of the check.
        other = tmp_path / "other"
        other.write_text("two")
        other.replace(path)

        assert _file_identity(path) != before, (
            "same path, same name, different file — if this compares equal "
            "the whole detection is worthless")

    def test_rewriting_in_place_is_the_same_file(self, tmp_path):
        """Ordinary writes must not look like a replacement, or every busy
        project would be reopened continuously."""
        path = tmp_path / "library.db"
        path.write_text("one")
        before = _file_identity(path)
        path.write_text("two-much-longer")

        assert _file_identity(path) == before

    def test_a_missing_file_has_no_identity(self, tmp_path):
        assert _file_identity(tmp_path / "gone.db") is None


class TestTheSupervisorNoticesTheSwap:
    def _sup(self, home: Path, registry: Path) -> Supervisor:
        return Supervisor(registry_path=registry, log=lambda m: None,
                          max_concurrent=1)

    @pytest.fixture
    def sup_with_slot(self, home):
        registry = home / "workers.json"
        rtfm_dir = _make_project(home)
        registry.write_text(json.dumps({"projects": [str(rtfm_dir)]}),
                            encoding="utf-8")
        sup = self._sup(home, registry)
        sup._sync_registry()
        deadline = time.monotonic() + 60
        while not sup._slots and time.monotonic() < deadline:
            sup._collect_opened()
            time.sleep(0.02)
        assert sup._slots, "the project never joined"
        slot = next(iter(sup._slots.values()))
        try:
            yield sup, slot, rtfm_dir
        finally:
            sup._pool.shutdown(wait=False)
            sup._opener.shutdown(wait=False)
            slot.close()

    def test_an_untouched_database_is_left_alone(self, sup_with_slot):
        sup, slot, _ = sup_with_slot
        before = slot.queue
        sup._next_identity_check = 0.0
        sup._reopen_replaced_databases()

        assert slot.queue is before, "reopened a database nothing had touched"

    def test_a_replaced_database_is_reconnected(self, sup_with_slot):
        sup, slot, rtfm_dir = sup_with_slot
        before_identity = slot.identity
        _replace_database(rtfm_dir)

        sup._next_identity_check = 0.0
        sup._reopen_replaced_databases()

        assert slot.identity != before_identity
        assert slot.identity == _file_identity(slot.db_path)

    def test_the_work_waiting_in_the_new_file_becomes_visible(
            self, sup_with_slot):
        """The whole failure in one assertion. Before the reopen the
        dispatcher peeks at the dead file and sees nothing, so the jobs the
        handlers queued in the live one are never dispatched — which is how
        893 documents sat waiting for a day in a queue that was polled every
        minute."""
        sup, slot, rtfm_dir = sup_with_slot
        _replace_database(rtfm_dir)

        q = Queue(rtfm_dir / "library.db")   # by path: the live file
        try:
            q.enqueue("ingest", {"filepath": "waiting.md", "corpus": "default"})
        finally:
            q.close()

        assert slot.queue.peek() is None, (
            "the stale connection should not see the new file's work — "
            "if it does, this test is no longer reproducing the defect")

        sup._next_identity_check = 0.0
        sup._reopen_replaced_databases()

        head = slot.queue.peek()
        assert head is not None and head[2] == "ingest"

    def test_a_project_with_a_job_in_flight_is_not_swapped(self,
                                                           sup_with_slot):
        """A claimed job owes its closing write to the queue it was claimed
        from. Marking it done against the replacement would update whatever
        row happens to carry that id there."""
        sup, slot, rtfm_dir = sup_with_slot
        before = slot.queue
        _replace_database(rtfm_dir)
        slot.inflight = 1
        try:
            sup._next_identity_check = 0.0
            sup._reopen_replaced_databases()
            assert slot.queue is before
        finally:
            slot.inflight = 0

        sup._next_identity_check = 0.0
        sup._reopen_replaced_databases()
        assert slot.queue is not before, "never picked up once idle"

    def test_the_swap_is_said_out_loud(self, home, sup_with_slot):
        """This defect cost a fleet a day of silence. The log is the fix as
        much as the reconnection is."""
        sup, slot, rtfm_dir = sup_with_slot
        _replace_database(rtfm_dir)
        sup._next_identity_check = 0.0
        sup._reopen_replaced_databases()

        text = (rtfm_dir / "rtfm.log").read_text(encoding="utf-8")
        assert "replaced" in text

    def test_looking_is_throttled(self, sup_with_slot):
        """One ``stat`` per project per pass of a loop that spins hot."""
        sup, slot, rtfm_dir = sup_with_slot
        sup._next_identity_check = 0.0
        sup._reopen_replaced_databases()          # takes the time slot
        before = slot.queue
        _replace_database(rtfm_dir)
        sup._reopen_replaced_databases()          # too soon to look
        assert slot.queue is before

        sup._next_identity_check = 0.0
        sup._reopen_replaced_databases()
        assert slot.queue is not before

    def test_a_database_that_vanished_is_not_reopened(self, sup_with_slot):
        """Gone is not replaced. Reopening would re-create an index for a
        project that may simply have been deleted."""
        sup, slot, rtfm_dir = sup_with_slot
        before = slot.queue
        (rtfm_dir / "library.db").unlink()

        sup._next_identity_check = 0.0
        sup._reopen_replaced_databases()
        assert slot.queue is before


class TestTheServerNoticesTheSwap:
    """An agent's session outlives the index it reads. Serving a neighbour
    from a snapshot nobody else can see is the worst of the three failures
    here: it looks like an answer."""

    @pytest.fixture
    def index(self, tmp_path, monkeypatch):
        db = tmp_path / "library.db"
        Library(str(db)).close()
        monkeypatch.setenv("RTFM_DB", str(db))
        import rtfm.mcp as mcp
        monkeypatch.setattr(mcp, "_library", None)
        monkeypatch.setattr(mcp, "_library_identity", None)
        return db

    def test_the_same_index_is_not_reopened_every_call(self, index):
        import rtfm.mcp as mcp
        assert mcp._get_library() is mcp._get_library()

    def test_a_replaced_index_is_reopened(self, index):
        import rtfm.mcp as mcp
        first = mcp._get_library()
        index.unlink()
        Library(str(index)).close()

        assert mcp._get_library() is not first

    def test_a_deleted_index_is_reported_not_served_from_memory(self, index):
        """Answering from an index the user deleted is a lie with a
        relevance score attached."""
        import rtfm.mcp as mcp
        mcp._get_library()
        index.unlink()

        with pytest.raises(mcp.NoIndexHere):
            mcp._get_library()


class TestAnIndexOnAReadOnlyMount:
    """The second half of the report: a shared index is published read-only,
    and searching it died in the connection setup."""

    @pytest.fixture
    def read_only_index(self, tmp_path):
        rtfm_dir = tmp_path / ".rtfm"
        rtfm_dir.mkdir()
        db = rtfm_dir / "library.db"
        lib = Library(str(db))
        lib.close()
        # Checkpoint and drop the WAL sidecars: a published copy is a plain
        # file, and their absence is what forces the read-only path to be
        # able to stand on its own.
        for suffix in ("-wal", "-shm"):
            Path(str(db) + suffix).unlink(missing_ok=True)
        os.chmod(db, 0o444)
        os.chmod(rtfm_dir, 0o555)
        try:
            yield db
        finally:
            os.chmod(rtfm_dir, 0o755)
            os.chmod(db, 0o644)

    def test_it_opens_and_can_be_searched(self, read_only_index):
        """``PRAGMA journal_mode = WAL`` is a write. Running it
        unconditionally is what made a read-only mount answer "unable to
        open database file" to a plain search."""
        lib = Library(str(read_only_index), create=False)
        try:
            assert lib.read_only is True
            assert lib.search("anything") is not None
        finally:
            lib.close()

    def test_it_does_not_take_the_database_out_of_wal(self, read_only_index):
        """Nothing about opening a shared index read-only may change what
        the writer sees when its mount comes back."""
        before = read_only_index.stat().st_mtime_ns
        lib = Library(str(read_only_index), create=False)
        try:
            lib.search("anything")
        finally:
            lib.close()
        assert read_only_index.stat().st_mtime_ns == before

    def test_a_writable_index_is_untouched_by_any_of_this(self, tmp_path):
        db = tmp_path / "library.db"
        lib = Library(str(db))
        try:
            assert lib.read_only is False
            assert lib._get_conn().execute(
                "PRAGMA journal_mode").fetchone()[0] == "wal"
        finally:
            lib.close()

    def test_a_write_still_fails_rather_than_being_swallowed(
            self, read_only_index):
        """Read-only must mean refused, never "accepted and discarded" —
        that is the same silence this whole file is about."""
        lib = Library(str(read_only_index), create=False)
        try:
            with pytest.raises(Exception):
                lib._get_conn().execute(
                    "INSERT INTO books (slug, title, filename, corpus) "
                    "VALUES ('x', 'x', 'x', 'x')")
                lib._get_conn().commit()
        finally:
            lib.close()


class TestUnreadableIsNotCorrupt:
    """The guard that renames a database out of the way must be sure.

    Found in the same investigation, in the supervisor log of the fleet
    above: two published mirrors were declared corrupt at boot and the
    quarantine rename failed with ``Read-only file system``. The rename
    failing is the only reason the indexes survived — the file was healthy,
    the directory was merely read-only for the duration of a publication.
    On a writable directory the same misdiagnosis renames a good index away
    and re-indexes the project from nothing.
    """

    def _corrupt(self, path: Path) -> None:
        """A file that is emphatically not a database."""
        path.write_bytes(b"this is not a database, not even slightly")

    def test_a_healthy_database_passes(self, tmp_path):
        from rtfm.core.dbcare import check_integrity
        db = tmp_path / "library.db"
        Library(str(db)).close()
        assert check_integrity(db) is True

    def test_a_genuinely_corrupt_file_still_fails(self, tmp_path):
        """The whole point of the guard: one project once looped for weeks
        on a malformed file. Loosening the diagnosis must not lose that."""
        from rtfm.core.dbcare import check_integrity
        db = tmp_path / "library.db"
        self._corrupt(db)
        assert check_integrity(db) is False

    def test_a_read_only_directory_is_not_a_corruption(self, tmp_path):
        from rtfm.core.dbcare import check_integrity
        rtfm_dir = tmp_path / ".rtfm"
        rtfm_dir.mkdir()
        db = rtfm_dir / "library.db"
        Library(str(db)).close()
        for suffix in ("-wal", "-shm"):
            Path(str(db) + suffix).unlink(missing_ok=True)
        os.chmod(db, 0o444)
        os.chmod(rtfm_dir, 0o555)
        try:
            assert check_integrity(db) is True
        finally:
            os.chmod(rtfm_dir, 0o755)
            os.chmod(db, 0o644)

    def test_an_unopenable_database_is_not_quarantined(self, tmp_path,
                                                       monkeypatch):
        """"I could not read it" must never reach the rename. Simulated
        with the error SQLite actually raises when a file is locked or its
        mount refuses it."""
        import sqlite3
        from rtfm.core import dbcare
        db = tmp_path / "library.db"
        Library(str(db)).close()

        def refuse(*a, **k):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(sqlite3, "connect", refuse)
        assert dbcare.check_integrity(db) is True

        quarantined = []
        monkeypatch.setattr(dbcare, "quarantine_db",
                            lambda p: quarantined.append(p))
        assert dbcare.ensure_healthy_db(db) is False
        assert quarantined == [], "renamed a database it could not even read"

    def test_the_check_needs_no_write_access_to_what_it_checks(self,
                                                              tmp_path):
        """It used to open read-write, which is why a read-only mount read
        as corruption in the first place."""
        from rtfm.core.dbcare import check_integrity
        db = tmp_path / "library.db"
        Library(str(db)).close()
        before = db.stat().st_mtime_ns
        assert check_integrity(db) is True
        assert db.stat().st_mtime_ns == before
