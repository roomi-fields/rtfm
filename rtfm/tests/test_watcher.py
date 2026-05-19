"""Tests for the watcher daemon (``rtfm.core.watcher``).

The poll loop itself is exercised by a single-tick run on a tmp
project. The PID-liveness and lock semantics mirror the worker
module's contract and are validated through the same primitives.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from rtfm.core.library import Library
from rtfm.core.queue import Queue
from rtfm.core.watcher import (
    Watcher, WatcherLock, WatcherLockHeld,
    pid_alive, read_state, write_state, clear_state,
    watcher_running, WatcherState,
)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _make_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Return (rtfm_dir, src_dir, db_path) for a minimal RTFM project."""
    rtfm_dir = tmp_path / ".rtfm"
    rtfm_dir.mkdir(parents=True)
    src = tmp_path / "src"
    src.mkdir()
    db = rtfm_dir / "library.db"
    Library(str(db)).close()
    (rtfm_dir / "config.json").write_text(
        json.dumps({"sources": [{"path": str(src), "corpus": "test"}]}),
        encoding="utf-8",
    )
    return rtfm_dir, src, db


def test_pid_alive_for_self_and_garbage():
    assert pid_alive(os.getpid()) is True
    assert pid_alive(7_777_777) is False
    assert pid_alive(0) is False


def test_state_roundtrip(tmp_path: Path):
    rtfm_dir = tmp_path / ".rtfm"
    rtfm_dir.mkdir()
    s = WatcherState(
        pid=12345, host="h", status="idle", sources_count=2,
        last_scan_at=_now_iso(), last_enqueued=0, total_enqueued=0,
        total_scans=1, started_at=_now_iso(), last_update=_now_iso(),
    )
    write_state(rtfm_dir, s)
    loaded = read_state(rtfm_dir)
    assert loaded is not None
    assert loaded.pid == 12345
    assert loaded.status == "idle"
    assert loaded.sources_count == 2


def test_watcher_running_detects_dead_pid_as_not_running(tmp_path: Path):
    rtfm_dir = tmp_path / ".rtfm"
    rtfm_dir.mkdir()
    s = WatcherState(
        pid=7_777_777, host="h", status="idle", sources_count=0,
        last_scan_at=None, last_enqueued=0, total_enqueued=0,
        total_scans=0, started_at=_now_iso(), last_update=_now_iso(),
    )
    write_state(rtfm_dir, s)
    assert watcher_running(rtfm_dir) is None


def test_watcher_running_detects_self_as_alive(tmp_path: Path):
    rtfm_dir = tmp_path / ".rtfm"
    rtfm_dir.mkdir()
    s = WatcherState(
        pid=os.getpid(), host="h", status="idle", sources_count=0,
        last_scan_at=None, last_enqueued=0, total_enqueued=0,
        total_scans=0, started_at=_now_iso(), last_update=_now_iso(),
    )
    write_state(rtfm_dir, s)
    live = watcher_running(rtfm_dir)
    assert live is not None and live.pid == os.getpid()


def test_clear_state_is_idempotent(tmp_path: Path):
    rtfm_dir = tmp_path / ".rtfm"
    rtfm_dir.mkdir()
    clear_state(rtfm_dir)  # no file → no error
    write_state(rtfm_dir, WatcherState(
        pid=1, host="h", status="idle", sources_count=0,
        last_scan_at=None, last_enqueued=0, total_enqueued=0,
        total_scans=0, started_at=_now_iso(), last_update=_now_iso(),
    ))
    clear_state(rtfm_dir)
    assert not (rtfm_dir / "watcher_state.json").exists()


def test_lock_blocks_second_holder(tmp_path: Path):
    """flock semantic: a second WatcherLock raises WatcherLockHeld
    while the first is alive."""
    rtfm_dir = tmp_path / ".rtfm"
    rtfm_dir.mkdir()
    with WatcherLock(rtfm_dir):
        with pytest.raises(WatcherLockHeld):
            with WatcherLock(rtfm_dir):
                pass


def test_single_tick_enqueues_added_files(tmp_path: Path):
    """A scan_once cycle must enqueue P1 jobs for every new file."""
    rtfm_dir, src, db = _make_project(tmp_path)
    (src / "a.md").write_text("# A", encoding="utf-8")
    (src / "b.md").write_text("# B", encoding="utf-8")

    w = Watcher(rtfm_dir=rtfm_dir, poll_interval=999)
    enqueued, sources_n = w._scan_once()
    assert sources_n == 1
    assert enqueued == 2

    # Queue holds 2 P1 ingest jobs for those files
    q = Queue(db)
    try:
        pending = q.list_pending()
        rels = sorted(j.payload["filepath"] for j in pending if j.type == "ingest")
        assert rels == ["a.md", "b.md"]
    finally:
        q.close()


def test_second_tick_idempotent(tmp_path: Path):
    """A second tick on the same on-disk state must enqueue nothing
    (the queue's dedup index already holds the pending rows)."""
    rtfm_dir, src, db = _make_project(tmp_path)
    (src / "a.md").write_text("# A", encoding="utf-8")

    w = Watcher(rtfm_dir=rtfm_dir, poll_interval=999)
    n1, _ = w._scan_once()
    n2, _ = w._scan_once()
    assert n1 == 1
    assert n2 == 0


def test_new_file_in_second_tick(tmp_path: Path):
    """Adding a file between two ticks must surface as a new P1."""
    rtfm_dir, src, db = _make_project(tmp_path)
    (src / "a.md").write_text("# A", encoding="utf-8")

    w = Watcher(rtfm_dir=rtfm_dir, poll_interval=999)
    n1, _ = w._scan_once()
    assert n1 == 1

    (src / "b.md").write_text("# B", encoding="utf-8")
    n2, _ = w._scan_once()
    assert n2 == 1


def test_state_snapshot_after_run_cycle(tmp_path: Path):
    """``_scan_once`` updates the on-disk state with the right counts."""
    rtfm_dir, src, db = _make_project(tmp_path)
    (src / "a.md").write_text("# A", encoding="utf-8")

    w = Watcher(rtfm_dir=rtfm_dir, poll_interval=999)
    w._snapshot("idle", 0, 0, None)
    w._scan_once()
    w._snapshot("idle", 1, 1, _now_iso())

    state = read_state(rtfm_dir)
    assert state is not None
    assert state.total_enqueued == 1
    assert state.total_scans == 1
    assert state.sources_count == 1
