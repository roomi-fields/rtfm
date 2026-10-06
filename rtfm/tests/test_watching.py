"""Sources are looked at when they change, not every minute.

The periodic scan could not know a directory was idle, so it listed every
file of every source every minute: a project untouched for months cost as
much as an active one, and one with 48 sources never got past its own scans —
53 scanned PDFs waited five weeks behind them.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

from rtfm.core import supervisor as sup
from rtfm.core.watch import filesystem_type, watching_supported

linux_only = pytest.mark.skipif(not watching_supported(),
                                reason="change notification is Linux-only")


# ── the watcher ──────────────────────────────────────────────────────────

class _Recorder:
    def __init__(self):
        self.changed, self.failed = [], []
        self.event = threading.Event()

    def on_changed(self, key):
        self.changed.append(key)
        self.event.set()

    def on_failed(self, key, reason):
        self.failed.append((key, reason))
        self.event.set()

    def wait(self, timeout=5.0):
        ok = self.event.wait(timeout)
        self.event.clear()
        return ok


@pytest.fixture
def watcher():
    from rtfm.core.watch import TreeWatcher
    rec = _Recorder()
    w = TreeWatcher(rec.on_changed, rec.on_failed)
    yield w, rec
    w.close()


def _settle(w, n_dirs, timeout=5.0):
    deadline = time.monotonic() + timeout
    while w.watched_directories() < n_dirs and time.monotonic() < deadline:
        time.sleep(0.02)


EXCLUDED = frozenset({".git", "node_modules"})


@linux_only
def test_a_written_file_reports_its_source(watcher, tmp_path):
    w, rec = watcher
    (tmp_path / "docs").mkdir()
    w.watch("src", str(tmp_path), EXCLUDED)
    _settle(w, 2)
    (tmp_path / "docs" / "note.md").write_text("x")
    assert rec.wait() and set(rec.changed) == {"src"}


@linux_only
def test_what_the_scan_skips_reports_nothing(watcher, tmp_path):
    w, rec = watcher
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / ".gitignore").write_text("build/\n*.log\n")
    (tmp_path / "build").mkdir()
    w.watch("src", str(tmp_path), EXCLUDED)
    _settle(w, 1)
    assert w.watched_directories() == 1, "skipped directories must not be watched"
    (tmp_path / "trace.log").write_text("x")
    (tmp_path / "base.db-wal").write_text("x")
    assert not rec.wait(timeout=0.5)


@linux_only
def test_a_new_directory_is_watched_too(watcher, tmp_path):
    w, rec = watcher
    w.watch("src", str(tmp_path), EXCLUDED)
    _settle(w, 1)
    (tmp_path / "nouveau").mkdir()
    assert rec.wait()
    _settle(w, 2)
    rec.changed.clear()
    (tmp_path / "nouveau" / "a.md").write_text("x")
    assert rec.wait() and set(rec.changed) == {"src"}


@linux_only
def test_a_directory_shared_by_two_sources_reports_both(watcher, tmp_path):
    w, rec = watcher
    w.watch("projet-a", str(tmp_path), EXCLUDED)
    w.watch("projet-b", str(tmp_path), EXCLUDED)
    _settle(w, 1)
    time.sleep(0.1)
    (tmp_path / "a.md").write_text("x")
    assert rec.wait()
    time.sleep(0.1)
    assert sorted(set(rec.changed)) == ["projet-a", "projet-b"]


@linux_only
def test_an_unwatched_source_is_silent(watcher, tmp_path):
    w, rec = watcher
    w.watch("src", str(tmp_path), EXCLUDED)
    _settle(w, 1)
    w.unwatch("src")
    deadline = time.monotonic() + 5
    while w.watched_directories() and time.monotonic() < deadline:
        time.sleep(0.02)
    (tmp_path / "a.md").write_text("x")
    assert not rec.wait(timeout=0.5)


@linux_only
def test_a_spent_watch_budget_is_reported(watcher, tmp_path, monkeypatch):
    w, rec = watcher
    monkeypatch.setattr(w, "_add", lambda key, path: False)
    w.watch("src", str(tmp_path), EXCLUDED)
    assert rec.wait()
    assert rec.failed and "budget" in rec.failed[0][1]


def test_a_network_share_is_recognised(tmp_path):
    table = tmp_path / "mountinfo"
    table.write_text(
        "22 1 8:2 / / rw - ext4 /dev/sda2 rw\n"
        "40 22 0:40 / /mnt/pc1 rw - autofs systemd-1 rw\n"
        "41 40 0:41 / /mnt/pc1 rw - cifs //192.168.1.52/D rw\n")
    assert filesystem_type("/mnt/pc1/Obsidian/Notes", str(table)) == "cifs"
    assert filesystem_type("/home/romi/dev", str(table)) == "ext4"
    assert filesystem_type("/mnt/pc10/x", str(table)) == "ext4"


# ── the schedule ─────────────────────────────────────────────────────────

class _FakeQueue:
    def __init__(self):
        self.enqueued = []

    def enqueue(self, kind, payload):
        self.enqueued.append((kind, payload))


def _bare_supervisor(slot, watcher=None):
    s = sup.Supervisor.__new__(sup.Supervisor)
    s._slots = {"p": slot}
    s._scan_interval = 60.0
    s._reconcile_interval = 3600.0
    s._watcher = watcher
    s._changes_lock = threading.Lock()
    s._changes, s._watch_failures = {}, {}
    s._backlog = lambda sl: 0
    return s


def _slot(tmp_path, sources):
    import json
    rtfm_dir = tmp_path / "proj" / ".rtfm"
    rtfm_dir.mkdir(parents=True)
    (rtfm_dir / "config.json").write_text(json.dumps({"sources": sources}))
    slot = sup._Slot(rtfm_dir)
    slot.queue = _FakeQueue()
    slot.log = lambda m: None
    slot.reconcile_seeded = True
    slot.next_reconcile_at = 1e18
    return slot


class _FakeWatcher:
    def __init__(self):
        self.watched, self.unwatched = [], []

    def watch(self, key, root, exclude_dirs, honor_gitignore=True):
        self.watched.append(key)

    def unwatch(self, key):
        self.unwatched.append(key)


def _scanned(slot):
    return [p["corpus"] for kind, p in slot.queue.enqueued if kind == "scan"]


def _finish(s, slot, corpus, changes):
    sched = next(x for (c, _), x in slot.sources.items() if c == corpus)
    job = type("J", (), {"payload": sched.payload})()
    s._scan_finished(slot, job, changes)
    return sched


def test_a_source_on_a_clock_slows_down_while_nothing_changes(tmp_path, monkeypatch):
    monkeypatch.setattr("rtfm.core.watch.is_network_path", lambda p: True)
    slot = _slot(tmp_path, [{"path": str(tmp_path), "corpus": "partage"}])
    s = _bare_supervisor(slot, _FakeWatcher())
    s._enqueue_periodic()
    assert _scanned(slot) == ["partage"]
    intervals = [_finish(s, slot, "partage", 0).interval for _ in range(8)]
    assert intervals[:3] == [120.0, 240.0, 480.0]
    assert intervals[-1] == sup.POLL_MAX_SECONDS
    assert _finish(s, slot, "partage", 3).interval == 60.0


def test_the_next_look_is_timed_from_the_end_of_the_last(tmp_path, monkeypatch):
    monkeypatch.setattr("rtfm.core.watch.is_network_path", lambda p: True)
    slot = _slot(tmp_path, [{"path": str(tmp_path), "corpus": "partage"}])
    s = _bare_supervisor(slot)
    s._enqueue_periodic()
    s._enqueue_periodic()
    assert _scanned(slot) == ["partage"], "no second look while one is queued"
    sched = _finish(s, slot, "partage", 1)
    assert sched.next_at >= time.monotonic() + 59


def test_a_watched_source_waits_for_a_change(tmp_path):
    w = _FakeWatcher()
    slot = _slot(tmp_path, [{"path": str(tmp_path), "corpus": "local"}])
    s = _bare_supervisor(slot, w)
    s._enqueue_periodic()                      # the first look, at admission
    sched = _finish(s, slot, "local", 0)
    assert sched.watched and sched.interval == sup.SAFETY_SCAN_SECONDS
    slot.queue.enqueued.clear()

    s._enqueue_periodic()
    assert _scanned(slot) == [], "an idle watched source is not looked at"

    key = (str(slot.rtfm_dir), "local", sched.payload["root"])
    s._on_source_changed(key)
    s._enqueue_periodic()
    assert _scanned(slot) == [], "the activity has not settled yet"
    sched.changed_at -= sup.CHANGE_SETTLE_SECONDS
    s._enqueue_periodic()
    assert _scanned(slot) == ["local"]


def test_two_changes_in_a_row_are_spaced(tmp_path):
    slot = _slot(tmp_path, [{"path": str(tmp_path), "corpus": "local"}])
    s = _bare_supervisor(slot, _FakeWatcher())
    s._enqueue_periodic()
    sched = _finish(s, slot, "local", 0)
    slot.queue.enqueued.clear()
    for _ in range(2):
        sched.changed_at = time.monotonic() - sup.CHANGE_SETTLE_SECONDS
        s._enqueue_periodic()
    assert _scanned(slot) == ["local"]


def test_a_source_that_cannot_be_watched_goes_back_on_the_clock(tmp_path):
    slot = _slot(tmp_path, [{"path": str(tmp_path), "corpus": "local"}])
    s = _bare_supervisor(slot, _FakeWatcher())
    s._enqueue_periodic()
    sched = _finish(s, slot, "local", 0)
    slot.queue.enqueued.clear()
    s._on_watch_failed((str(slot.rtfm_dir), "local", sched.payload["root"]),
                       "budget spent")
    s._enqueue_periodic()
    assert not sched.watched and sched.interval == 60.0
    assert _scanned(slot) == ["local"]


def test_a_network_share_is_never_watched(tmp_path, monkeypatch):
    monkeypatch.setattr("rtfm.core.watch.is_network_path", lambda p: True)
    w = _FakeWatcher()
    slot = _slot(tmp_path, [{"path": str(tmp_path), "corpus": "partage"}])
    _bare_supervisor(slot, w)._enqueue_periodic()
    assert w.watched == []


def test_a_retired_source_stops_being_watched(tmp_path):
    import json
    w = _FakeWatcher()
    other = tmp_path / "autre"
    other.mkdir()
    slot = _slot(tmp_path, [{"path": str(tmp_path), "corpus": "a"},
                            {"path": str(other), "corpus": "b"}])
    s = _bare_supervisor(slot, w)
    s._enqueue_periodic()
    cfg = slot.rtfm_dir / "config.json"
    cfg.write_text(json.dumps({"sources": [{"path": str(tmp_path), "corpus": "a"}]}))
    os.utime(cfg, (time.time() + 5, time.time() + 5))
    s._enqueue_periodic()
    assert [k[1] for k in w.unwatched] == ["b"]
    assert [c for c, _ in slot.sources] == ["a"]


def test_a_scan_that_never_reports_back_is_retried(tmp_path, monkeypatch):
    monkeypatch.setattr("rtfm.core.watch.is_network_path", lambda p: True)
    slot = _slot(tmp_path, [{"path": str(tmp_path), "corpus": "partage"}])
    s = _bare_supervisor(slot)
    s._enqueue_periodic()
    sched = next(iter(slot.sources.values()))
    sched.queued_at -= sup.SCAN_LOST_AFTER_SECONDS + 1
    s._enqueue_periodic()
    assert _scanned(slot) == ["partage", "partage"]


def test_the_scan_says_what_it_found(tmp_path):
    from rtfm.core.handlers import handle_scan
    from rtfm.core.library import Library
    from rtfm.core.queue import Job
    from rtfm.core.worker import JobContext

    db = tmp_path / ".rtfm" / "library.db"
    db.parent.mkdir()
    Library(str(db)).close()
    (tmp_path / "a.md").write_text("# a\n\ntexte\n")
    job = Job(id=1, type="scan", priority=10,
              payload={"root": str(tmp_path), "corpus": "default"},
              status="running", created_at="", started_at=None,
              finished_at=None, error=None, attempts=1)
    assert handle_scan(job, JobContext(str(db), lambda m: None)) == 1
