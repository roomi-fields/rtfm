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


class TestModuleFlavouredJavaScript:
    """`.js` was indexed and `.mjs` was refused. Nothing chose that — the
    list simply predates the suffix. Reported by a repository whose tooling
    is written as ESM: eleven files rejected with "No parser available"."""

    @pytest.mark.parametrize("suffix", [".mjs", ".cjs", ".mts", ".cts"])
    def test_the_module_suffixes_are_indexed(self, tmp_path, suffix):
        from rtfm.parsers.base import ParserRegistry
        path = tmp_path / f"garde{suffix}"
        path.write_text("export function guard() { return 1 }\n",
                        encoding="utf-8")
        parser = ParserRegistry.get_parser(path)
        assert parser is not None, f"{suffix} has no parser"
        assert list(parser.parse(path)), f"{suffix} produced nothing"

    def test_it_is_the_same_parser_that_reads_plain_js(self, tmp_path):
        """Not a new format — the same one, spelled differently."""
        from rtfm.parsers.base import ParserRegistry
        js = tmp_path / "a.js"
        mjs = tmp_path / "a.mjs"
        for p in (js, mjs):
            p.write_text("const x = 1\n", encoding="utf-8")
        assert (ParserRegistry.get_parser(js).name
                == ParserRegistry.get_parser(mjs).name)


class TestTwoFilesWantingOneIdentity:
    """Losing a race for a slug is not a defect in the file.

    Found by the fleet audit. ``allocate_book_slug`` reads then writes, and
    a project's documents are ingested several at a time, so two paths that
    normalise to the same slug can both be told it is free. The second
    insert violated the unique index and was recorded as a *content*
    failure — and that record keys on the file's hash, so the file was never
    offered again. Two documents on this fleet were out of the index for
    good, with nothing but an audit line to say so.
    """

    def test_the_normalised_names_really_do_collide(self):
        """The premise. Three distinct files, one identity — separators
        collapse, so no naming rule can promise uniqueness."""
        from rtfm.core.sync import _path_to_slug
        slugs = {_path_to_slug(f"d/{name}", "c") for name in
                 ("-wg.dhin.txt", "-wg.dhin--.txt", "-wg.dhin-.txt")}
        assert len(slugs) == 1

    def test_the_second_file_gets_its_own_identity(self, tmp_path):
        from rtfm.core.sync import _path_to_slug
        db = tmp_path / "library.db"
        lib = Library(str(db))
        try:
            first = _path_to_slug("d/-wg.dhin.txt", "c")
            assert lib.allocate_book_slug(first, "d/-wg.dhin.txt", "c") == first
            # Nothing is written until a book exists, so put one there.
            lib._get_conn().execute(
                "INSERT INTO books (slug, title, filename, corpus) "
                "VALUES (?, ?, ?, ?)", (first, "t", "d/-wg.dhin.txt", "c"))
            lib._get_conn().commit()

            second = lib.allocate_book_slug(first, "d/-wg.dhin--.txt", "c")
            assert second != first
        finally:
            lib.close()

    def test_a_collision_is_retried_not_recorded_as_broken(self, tmp_path,
                                                           monkeypatch):
        """The handler's own path: the first insert loses the race, the
        second attempt asks again and succeeds. Nothing reaches the failure
        record, which is what made the loss permanent."""
        import sqlite3 as sq
        from rtfm.core import handlers

        rtfm_dir = tmp_path / ".rtfm"
        rtfm_dir.mkdir()
        doc = tmp_path / "note.md"
        doc.write_text("# Title\n\nbody\n", encoding="utf-8")

        attempts: list[str] = []
        real = Library.ingest

        def flaky(self, path, corpus=None, metadata=None, **kw):
            """The race, in the order it actually happens: the slug was free
            when this job asked for it, and the other file commits it before
            this insert lands."""
            slug = (metadata or {}).get("book_slug")
            attempts.append(slug)
            if len(attempts) == 1:
                self._get_conn().execute(
                    "INSERT INTO books (slug, title, filename, corpus) "
                    "VALUES (?, ?, ?, ?)", (slug, "t", "other.md", "c"))
                self._get_conn().commit()
                raise sq.IntegrityError(
                    "UNIQUE constraint failed: books.slug")
            return real(self, path, corpus=corpus, metadata=metadata, **kw)

        monkeypatch.setattr(Library, "ingest", flaky)

        recorded: list[tuple] = []
        monkeypatch.setattr(Library, "record_ingest_failure",
                            lambda self, *a, **k: recorded.append(a))

        from rtfm.core.queue import Job
        from rtfm.core.worker import JobContext
        job = Job(id=1, type="ingest", priority=10, payload={
            "root": str(tmp_path), "corpus": "c", "filepath": "note.md"},
            status="running", created_at="", started_at=None,
            finished_at=None, error=None, attempts=1)
        ctx = JobContext(str(rtfm_dir / "library.db"),
                                  lambda m: None)
        handlers.handle_ingest(job, ctx)

        assert len(attempts) == 2, "the collision was not retried"
        assert attempts[0] != attempts[1], "retried with the same identity"
        assert recorded == [], "a race was remembered as a broken file"

    def test_any_other_integrity_error_is_not_retried(self, tmp_path,
                                                      monkeypatch):
        """Only this one violation. A retry loop around every integrity
        error would hide real corruption."""
        import sqlite3 as sq
        from rtfm.core import handlers

        rtfm_dir = tmp_path / ".rtfm"
        rtfm_dir.mkdir()
        Library(str(rtfm_dir / "library.db")).close()
        (tmp_path / "note.md").write_text("# T\n\nb\n", encoding="utf-8")

        attempts: list[int] = []

        def always_fails(self, path, corpus=None, metadata=None, **kw):
            attempts.append(1)
            raise sq.IntegrityError("FOREIGN KEY constraint failed")

        monkeypatch.setattr(Library, "ingest", always_fails)
        monkeypatch.setattr(Library, "record_ingest_failure",
                            lambda self, *a, **k: None)

        from rtfm.core.queue import Job
        from rtfm.core.worker import JobContext
        job = Job(id=1, type="ingest", priority=10, payload={
            "root": str(tmp_path), "corpus": "c", "filepath": "note.md"},
            status="running", created_at="", started_at=None,
            finished_at=None, error=None, attempts=1)
        ctx = JobContext(str(rtfm_dir / "library.db"),
                                  lambda m: None)
        with pytest.raises(sq.IntegrityError):
            handlers.handle_ingest(job, ctx)
        assert len(attempts) == 1


class TestTransientDatabaseSidecars:
    """A write-ahead log and its shared-memory index are not documents.

    The audit found one indexed nine times and removed three times in a
    single day, on three separate projects: it exists only while a database
    is open, so every scan sees it appear or vanish.
    """

    def _scan(self, root):
        from rtfm.core.sync import scan_directory
        return {p.name for p in scan_directory(root, honor_gitignore=False)}

    def test_the_sidecars_are_never_scanned(self, tmp_path):
        (tmp_path / "notes.md").write_text("x", encoding="utf-8")
        for name in ("codegraph.db-shm", "codegraph.db-wal",
                     "library.db-journal"):
            (tmp_path / name).write_bytes(b"\x00\x01")

        assert self._scan(tmp_path) == {"notes.md"}

    def test_the_database_itself_is_still_offered(self, tmp_path):
        """Only the sidecars. A SQLite file is a supported format and one
        somebody put in their project is theirs to index."""
        (tmp_path / "data.db").write_bytes(b"SQLite format 3\x00")
        assert "data.db" in self._scan(tmp_path)

    def test_another_tool_s_index_is_skipped_like_our_own(self, tmp_path):
        """``.codegraph`` holds this repository's content again, in a binary
        form nothing reads back — the same reason ``.rtfm`` is excluded."""
        (tmp_path / ".codegraph").mkdir()
        (tmp_path / ".codegraph" / "codegraph.db").write_bytes(b"x")
        (tmp_path / "keep.md").write_text("x", encoding="utf-8")

        assert self._scan(tmp_path) == {"keep.md"}


class TestAnExcludedPathLeavesTheIndex:
    """Adding an exclusion rule must also undo what it used to allow.

    The scan simply stops offering the file, so it lands in ``removed`` —
    and there the disk check holds it back, because the file is still
    perfectly present. Three projects were carrying a database's
    shared-memory sidecar for exactly that reason.
    """

    def test_a_rule_excluded_file_is_removed_even_though_it_is_there(
            self, tmp_path):
        from rtfm.core.sync import confirm_removals
        (tmp_path / ".codegraph").mkdir()
        present = tmp_path / ".codegraph" / "codegraph.db"
        present.write_bytes(b"x")

        confirmed, kept = confirm_removals(
            tmp_path, [".codegraph/codegraph.db"])
        assert confirmed == [".codegraph/codegraph.db"]
        assert kept == []
        assert present.exists(), "the file itself must not be touched"

    def test_a_sidecar_is_removed_the_same_way(self, tmp_path):
        from rtfm.core.sync import confirm_removals
        (tmp_path / "notes.db-shm").write_bytes(b"x")
        confirmed, _ = confirm_removals(tmp_path, ["notes.db-shm"])
        assert confirmed == ["notes.db-shm"]

    def test_an_ordinary_file_still_gets_the_disk_check(self, tmp_path):
        """The guard that stands between a dark mount and deleting real
        content is untouched: a file that is still there stays indexed."""
        from rtfm.core.sync import confirm_removals
        (tmp_path / "kept.md").write_text("x", encoding="utf-8")
        confirmed, kept = confirm_removals(tmp_path, ["kept.md"])
        assert confirmed == []
        assert kept == ["kept.md"]

    def test_a_genuinely_deleted_file_is_still_removed(self, tmp_path):
        from rtfm.core.sync import confirm_removals
        confirmed, kept = confirm_removals(tmp_path, ["gone.md"])
        assert confirmed == ["gone.md"]

    def test_the_user_s_own_ignore_files_are_not_treated_this_way(self,
                                                                 tmp_path):
        """``.gitignore`` is editable and can be unreadable on a dark mount.
        Only the built-in rules are certain enough to delete on."""
        from rtfm.core.sync import is_excluded_by_rule
        assert is_excluded_by_rule("docs/notes.md") is False
        assert is_excluded_by_rule("node_modules/x/index.js") is True


class TestTheRemoveHandlerHonoursTheSameRule:
    """The removal is queued, then refused. Two guards, and fixing only the
    first left the entry exactly where it was: the handler takes its own
    last look at the disk before destroying chunks, and the file is there.
    """

    def _run_remove(self, tmp_path, rel):
        from rtfm.core import handlers
        from rtfm.core.queue import Job
        from rtfm.core.worker import JobContext
        rtfm_dir = tmp_path / ".rtfm"
        rtfm_dir.mkdir(exist_ok=True)
        db = rtfm_dir / "library.db"
        lib = Library(str(db))
        lib.set_sync_root("c", str(tmp_path))
        lib.close()
        job = Job(id=1, type="remove", priority=10,
                  payload={"filepath": rel, "corpus": "c"},
                  status="running", created_at="", started_at=None,
                  finished_at=None, error=None, attempts=1)
        lines: list[str] = []
        handlers.handle_remove(job, JobContext(str(db), lines.append))
        return "\n".join(lines)

    def test_an_excluded_file_is_removed_though_it_is_on_disk(self, tmp_path):
        (tmp_path / ".codegraph").mkdir()
        (tmp_path / ".codegraph" / "codegraph.db-shm").write_bytes(b"x")
        out = self._run_remove(tmp_path, ".codegraph/codegraph.db-shm")
        assert "still on disk, kept" not in out
        assert "excluded by rule" in out or "not in index" in out

    def test_an_ordinary_file_on_disk_is_still_kept(self, tmp_path):
        """The guard that stands between a stale job and a destroyed index
        must survive this."""
        (tmp_path / "real.md").write_text("x", encoding="utf-8")
        out = self._run_remove(tmp_path, "real.md")
        assert "still on disk, kept" in out


class TestAnHtmlTitleIsNotAnIdentity:
    """The HTML parser recomputed the slug from the document's ``<title>``.

    Found by the fleet audit: six books in one catalogue that no scan
    tracked. The catalogue entry carried a title-derived slug while the file
    tracking carried the path-derived one, so the two never matched and
    every HTML document read as an untracked book for ever.

    The sharper consequence is collision. Two pages sharing a ``<title>`` —
    ordinary in a docs tree, a set of mockups, a generated site — collapsed
    onto one identity, and the second was refused.
    """

    def _parser(self):
        from rtfm.parsers.html_bofip import HTMLBOFiPParser
        return HTMLBOFiPParser()

    def _page(self, path: Path, title: str, body: str = "Some content here "
                                                        "with enough text.") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"<html><head><title>{title}</title></head>"
            f"<body><p>{body * 12}</p></body></html>", encoding="utf-8")
        return path

    def test_the_identity_it_is_given_is_the_identity_it_uses(self, tmp_path):
        page = self._page(tmp_path / "mockup.html", "Kanopi MySet")
        chunks = list(self._parser().parse(
            page, {"book_slug": "corpus--docs--mockup-html"}))

        assert chunks, "nothing parsed"
        assert {c.book_slug for c in chunks} == {"corpus--docs--mockup-html"}

    def test_two_pages_with_one_title_keep_two_identities(self, tmp_path):
        """The collision, in the shape a docs tree actually produces it."""
        a = self._page(tmp_path / "a" / "index.html", "Kanopi")
        b = self._page(tmp_path / "b" / "index.html", "Kanopi")
        p = self._parser()

        slugs = {next(iter(p.parse(page, {}))).book_slug for page in (a, b)}
        assert len(slugs) == 2, f"both pages claimed one identity: {slugs}"

    def test_with_no_caller_it_falls_back_to_the_path(self, tmp_path):
        page = self._page(tmp_path / "sub" / "page.html", "A Shared Title")
        chunk = next(iter(self._parser().parse(page, {})))

        assert "a-shared-title" not in chunk.book_slug
        assert chunk.book_slug.endswith("page.html")

    def test_the_title_is_still_the_book_title(self, tmp_path):
        """Only the identity moves. What the document is called is still
        read from the document — through the same two steps the library
        uses: metadata first, then parse."""
        page = self._page(tmp_path / "p.html", "Kanopi MySet")
        parser = self._parser()
        meta = parser.extract_metadata(page)
        chunk = next(iter(parser.parse(page, meta)))

        assert chunk.book_title == "Kanopi MySet"
        assert "kanopi-myset" not in chunk.book_slug

    def test_the_metadata_it_offers_is_path_derived_too(self, tmp_path):
        """``extract_metadata`` seeds the identity when a caller supplies
        none, so a title there is the same defect one step earlier."""
        page = self._page(tmp_path / "p.html", "Kanopi MySet")
        meta = self._parser().extract_metadata(page)

        assert meta["title"] == "Kanopi MySet"
        assert "kanopi-myset" not in meta["book_slug"]

    def test_the_catalogue_entry_matches_what_tracks_the_file(self, tmp_path):
        """End to end, and the exact thing the audit measures: the book the
        ingest creates is the one ``indexed_files`` points at."""
        from rtfm.core.sync import _path_to_slug
        page = self._page(tmp_path / "docs" / "index.html", "Kanopi")
        db = tmp_path / ".rtfm" / "library.db"
        db.parent.mkdir()
        lib = Library(str(db))
        try:
            rel = "docs/index.html"
            slug = _path_to_slug(rel, "c")
            lib.ingest(page, corpus="c",
                       metadata={"book_slug": slug, "source_file": rel})
            rows = [r["slug"] for r in lib._get_conn().execute(
                "SELECT slug FROM books")]
            assert rows == [slug], f"catalogue holds {rows}, tracking holds {slug}"
        finally:
            lib.close()


class TestReindexRepairsWhatTheCatalogueLost:
    """``reindex`` read the catalogue, so it could not repair the catalogue.

    A book deleted by the reconcile pass leaves its tracking row behind, and
    that is exactly the state a re-ingest exists to fix. Reading ``books``
    answered "no matching indexed files" for all 5 738 HTML documents this
    fleet had lost that way.
    """

    def _project(self, tmp_path):
        rtfm_dir = tmp_path / ".rtfm"
        rtfm_dir.mkdir()
        lib = Library(str(rtfm_dir / "library.db"))
        lib.set_sync_root("c", str(tmp_path))
        return lib, rtfm_dir

    def test_a_tracked_file_with_no_book_is_re_queued(self, tmp_path,
                                                      monkeypatch):
        page = tmp_path / "page.html"
        page.write_text("<html><body>x</body></html>", encoding="utf-8")
        lib, rtfm_dir = self._project(tmp_path)
        lib.update_indexed_file(filepath="page.html", file_hash="h",
                                corpus="c", book_slug="c--page-html",
                                file_size=27, root_path=str(tmp_path))
        lib.close()

        monkeypatch.chdir(tmp_path)
        import rtfm.cli as cli
        monkeypatch.setattr(cli, "ensure_worker_running", lambda *a, **k: None,
                            raising=False)

        class Args:
            ext, parser, corpus, background = "html", None, None, True
        with pytest.raises(SystemExit) as exit_info:
            cli.cmd_reindex(Args())
        assert exit_info.value.code == 0

        q = Queue(rtfm_dir / "library.db")
        try:
            head = q.peek()
            assert head is not None and head[2] == "ingest", (
                "the file the catalogue lost was not re-queued")
        finally:
            q.close()

    def test_an_unrelated_extension_is_left_alone(self, tmp_path, monkeypatch):
        (tmp_path / "notes.md").write_text("x", encoding="utf-8")
        lib, rtfm_dir = self._project(tmp_path)
        lib.update_indexed_file(filepath="notes.md", file_hash="h", corpus="c",
                                book_slug="c--notes-md", file_size=1,
                                root_path=str(tmp_path))
        lib.close()

        monkeypatch.chdir(tmp_path)
        import rtfm.cli as cli

        class Args:
            ext, parser, corpus, background = "html", None, None, True
        cli.cmd_reindex(Args())

        q = Queue(rtfm_dir / "library.db")
        try:
            assert q.peek() is None
        finally:
            q.close()
