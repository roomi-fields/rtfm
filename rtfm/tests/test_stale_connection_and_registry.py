"""Two ways a project stops being served without anything saying so.

Both were measured on the same fleet, on the same morning: sixteen
repositories, each published as a read-only mirror, each mirror indexed.

The first is a connection that outlived the conditions it was opened in.
SQLite decides whether a database is writable once, when it opens the file,
and never revisits that decision. A publication that holds its directory
read-only for a second while it swaps content is enough: whatever opened the
database in that second keeps a read-only handle for ever, and every attempt
to take a job from the queue fails with the same message, several times a
second, for as long as the process lives.

The second is the enrolment list itself. Adding a project reads the whole
list, appends one line and writes the whole list back, so two enrolments that
overlap end with the second one's list — and the first one's project is not
in it. It has a database, a queue and a scan root, and nothing will ever look
at it again.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from rtfm.core.supervisor import (
    Supervisor, _Slot, _is_stale_handle, _is_db_corruption,
)


# ── Telling a dead handle from a dead file ───────────────────────────────

class TestWhatTheMessageMeans:

    @pytest.mark.parametrize("msg", [
        "attempt to write a readonly database",
        "unable to open database file",
        "disk I/O error",
    ])
    def test_the_connection_is_the_problem(self, msg):
        assert _is_stale_handle(sqlite3.OperationalError(msg))

    @pytest.mark.parametrize("msg", [
        "database disk image is malformed",
        "file is not a database",
    ])
    def test_the_file_is_the_problem(self, msg):
        assert _is_db_corruption(sqlite3.OperationalError(msg))
        assert not _is_stale_handle(sqlite3.OperationalError(msg))

    def test_a_lock_is_neither(self):
        exc = sqlite3.OperationalError("database is locked")
        assert not _is_stale_handle(exc)
        assert not _is_db_corruption(exc)


# ── The supervisor's reaction ────────────────────────────────────────────

def _supervisor(tmp_path: Path, lines: list[str]) -> Supervisor:
    registry = tmp_path / "workers.json"
    registry.write_text(json.dumps({"projects": []}))
    return Supervisor(registry_path=registry, log=lines.append,
                      max_concurrent=1)


def _slot(tmp_path: Path, name: str = "projet") -> _Slot:
    rtfm_dir = tmp_path / name / ".rtfm"
    rtfm_dir.mkdir(parents=True)
    slot = _Slot(rtfm_dir)
    slot.open(lambda m: None)
    return slot


class TestAConnectionThatWentReadOnly:

    def test_the_slot_is_reopened(self, tmp_path):
        lines: list[str] = []
        sup = _supervisor(tmp_path, lines)
        slot = _slot(tmp_path)
        before = slot.queue

        sup._note_queue_error(
            slot, sqlite3.OperationalError("attempt to write a readonly database"),
            "dequeue")

        assert slot.queue is not before, "the dead handle was kept"
        assert slot.queue is not None
        assert any("reopening" in ln for ln in lines)

    def test_a_reopened_slot_is_tried_again_at_once(self, tmp_path):
        sup = _supervisor(tmp_path, [])
        slot = _slot(tmp_path)
        sup._note_queue_error(
            slot, sqlite3.OperationalError("attempt to write a readonly database"),
            "dequeue")
        assert slot.retry_at == 0.0
        assert slot.queue_errors == 0

    def test_a_busy_slot_keeps_its_handle(self, tmp_path):
        """A job in flight was claimed in this queue and owes it a closing
        write; swapping the connection under it would strand that claim."""
        sup = _supervisor(tmp_path, [])
        slot = _slot(tmp_path)
        slot.inflight = 1
        before = slot.queue
        sup._note_queue_error(
            slot, sqlite3.OperationalError("attempt to write a readonly database"),
            "dequeue")
        assert slot.queue is before

    def test_a_scan_is_re_armed_after_the_swap(self, tmp_path):
        sup = _supervisor(tmp_path, [])
        slot = _slot(tmp_path)
        slot.scan_paused = True
        slot.next_scan_at = time.monotonic() + 10_000
        sup._note_queue_error(
            slot, sqlite3.OperationalError("unable to open database file"),
            "peek")
        assert not slot.scan_paused
        assert slot.next_scan_at <= time.monotonic() + 0.5


class TestAFailureThatKeepsFailing:

    def test_the_project_is_left_alone_a_while(self, tmp_path):
        sup = _supervisor(tmp_path, [])
        slot = _slot(tmp_path)
        # A cause reopening cannot fix: a lock nobody releases.
        for _ in range(3):
            slot.retry_at = 0.0
            sup._note_queue_error(
                slot, sqlite3.OperationalError("database is locked"), "peek")
        assert slot.queue_errors == 3
        assert slot.retry_at > time.monotonic()

    def test_the_wait_grows_and_stops_growing(self, tmp_path):
        sup = _supervisor(tmp_path, [])
        slot = _slot(tmp_path)
        waits = []
        for _ in range(12):
            sup._note_queue_error(
                slot, sqlite3.OperationalError("database is locked"), "peek")
            waits.append(slot.retry_at - time.monotonic())
        assert waits[1] > waits[0]
        assert max(waits) <= 301, "a project would be parked for ever"

    def test_the_log_does_not_repeat_itself(self, tmp_path):
        """33 707 identical lines in eighty minutes is what this prevents."""
        lines: list[str] = []
        sup = _supervisor(tmp_path, lines)
        slot = _slot(tmp_path)
        for _ in range(200):
            sup._note_queue_error(
                slot, sqlite3.OperationalError("database is locked"), "peek")
        assert len(lines) < 30, f"{len(lines)} lines for one stuck project"
        assert lines, "and not silent either"


# ── The enrolment list ───────────────────────────────────────────────────

class TestEnrollingTwoProjectsAtOnce:

    def test_neither_is_lost(self, tmp_path, monkeypatch):
        import rtfm.cli_worker as cw
        registry = tmp_path / "workers.json"
        monkeypatch.setattr(cw, "_REGISTRY", registry)

        dirs = []
        for i in range(24):
            d = tmp_path / f"projet{i}" / ".rtfm"
            d.mkdir(parents=True)
            dirs.append(d)

        start = threading.Barrier(len(dirs))

        def enrol(d):
            start.wait()
            cw._register_project(d)

        threads = [threading.Thread(target=enrol, args=(d,)) for d in dirs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        listed = set(json.loads(registry.read_text())["projects"])
        missing = [str(d.resolve()) for d in dirs
                   if str(d.resolve()) not in listed]
        assert not missing, f"{len(missing)} project(s) enrolled and dropped"

    def test_a_reader_never_sees_half_a_list(self, tmp_path, monkeypatch):
        import rtfm.cli_worker as cw
        registry = tmp_path / "workers.json"
        monkeypatch.setattr(cw, "_REGISTRY", registry)
        cw._save_registry([str(tmp_path / f"p{i}" / ".rtfm") for i in range(500)])

        seen: list[int] = []
        stop = threading.Event()

        def read():
            while not stop.is_set():
                try:
                    seen.append(len(json.loads(registry.read_text())["projects"]))
                except Exception as exc:  # a torn file
                    seen.append(-1)

        reader = threading.Thread(target=read)
        reader.start()
        for i in range(500, 560):
            d = tmp_path / f"p{i}" / ".rtfm"
            d.mkdir(parents=True)
            cw._register_project(d)
        stop.set()
        reader.join()

        assert -1 not in seen, "a reader caught the file mid-write"
        assert seen, "the reader never ran"

    def test_enrolling_twice_changes_nothing(self, tmp_path, monkeypatch):
        import rtfm.cli_worker as cw
        registry = tmp_path / "workers.json"
        monkeypatch.setattr(cw, "_REGISTRY", registry)
        d = tmp_path / "projet" / ".rtfm"
        d.mkdir(parents=True)
        cw._register_project(d)
        first = registry.read_text()
        cw._register_project(d)
        assert registry.read_text() == first

    def test_a_jammed_lock_does_not_block_the_caller(self, tmp_path, monkeypatch):
        """A hook that saves a file must not wait on the registry."""
        import rtfm.cli_worker as cw
        registry = tmp_path / "workers.json"
        monkeypatch.setattr(cw, "_REGISTRY", registry)
        monkeypatch.setattr(cw, "try_lock_exclusive", lambda fd: False)
        d = tmp_path / "projet" / ".rtfm"
        d.mkdir(parents=True)
        started = time.monotonic()
        cw._register_project(d)
        assert time.monotonic() - started < 5.0
