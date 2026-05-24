"""Tests for the worker daemon (``rtfm.core.worker.Worker``).

The worker no longer does scan/reconcile work inline — both are now
enqueued as regular jobs (``scan``, ``reconcile``) and drained by the
same dispatch loop. These tests cover the producer side of those two
periodic ticks: that ``_maybe_scan`` and ``_maybe_reconcile`` enqueue
exactly the right number of jobs with the right payloads, and that
the throttle prevents repeated ticks from re-enqueuing while a job is
still pending (queue dedup).
"""
from __future__ import annotations

import json
from pathlib import Path

from rtfm.core.handlers import HANDLERS
from rtfm.core.library import Library
from rtfm.core.queue import P_RECONCILE, P_SCAN, Queue
from rtfm.core.worker import Worker


def _write_config(rtfm_dir: Path, sources: list[dict]) -> None:
    """Write a minimal ``.rtfm/config.json`` with the given sources."""
    rtfm_dir.mkdir(parents=True, exist_ok=True)
    (rtfm_dir / "config.json").write_text(
        json.dumps({"sources": sources}), encoding="utf-8")


def _make_worker(rtfm_dir: Path, db: Path) -> Worker:
    """Build a Worker pointing at the given .rtfm dir + db.

    The dispatch table is real (``HANDLERS``) but we never call ``run()``,
    so handlers don't actually fire.
    """
    return Worker(rtfm_dir=rtfm_dir, db_path=db, handlers=HANDLERS)


def test_maybe_scan_enqueues_one_scan_per_source(tmp_path: Path):
    """With 2 sources in config.json, ``_maybe_scan`` enqueues exactly 2
    P1 ``scan`` jobs whose payloads carry the right root/corpus/ext."""
    rtfm_dir = tmp_path / ".rtfm"
    src_a = tmp_path / "src-a"
    src_b = tmp_path / "src-b"
    src_a.mkdir()
    src_b.mkdir()
    _write_config(rtfm_dir, [
        {"path": str(src_a), "corpus": "alpha", "extensions": ".md,.py"},
        {"path": str(src_b), "corpus": "beta"},
    ])
    db = rtfm_dir / "library.db"
    Library(str(db)).close()

    worker = _make_worker(rtfm_dir, db)
    worker._maybe_scan()

    q = Queue(db)
    try:
        pending = q.list_pending(limit=10_000)
        scans = [j for j in pending if j.type == "scan"]
        assert len(scans) == 2, f"expected 2 scan jobs, got {len(scans)}"
        # Each P1, default priority.
        for j in scans:
            assert j.priority == P_SCAN
        by_corpus = {j.payload["corpus"]: j for j in scans}
        assert set(by_corpus) == {"alpha", "beta"}
        assert by_corpus["alpha"].payload == {
            "root": str(src_a.resolve()),
            "corpus": "alpha",
            "extensions": ".md,.py",
        }
        assert by_corpus["beta"].payload == {
            "root": str(src_b.resolve()),
            "corpus": "beta",
            "extensions": None,
        }
    finally:
        q.close()


def test_maybe_scan_dedup_on_repeat_tick(tmp_path: Path):
    """Two back-to-back ticks (throttle bypassed) → still only one scan
    job per source, because the queue dedup index drops the duplicates."""
    rtfm_dir = tmp_path / ".rtfm"
    src = tmp_path / "src"
    src.mkdir()
    _write_config(rtfm_dir, [{"path": str(src), "corpus": "alpha"}])
    db = rtfm_dir / "library.db"
    Library(str(db)).close()

    worker = _make_worker(rtfm_dir, db)
    worker._maybe_scan()
    # Force the throttle to allow a second tick immediately. Using a
    # relative offset rather than 0.0 — time.monotonic()'s origin is
    # implementation-defined, so on a fresh CI runner monotonic() can
    # be smaller than the throttle interval.
    import time as _t
    worker._last_scan_at = _t.monotonic() - worker.scan_interval - 1
    worker._maybe_scan()

    q = Queue(db)
    try:
        pending = q.list_pending(limit=10_000)
        scans = [j for j in pending if j.type == "scan"]
        assert len(scans) == 1, (
            f"queue dedup must drop the duplicate scan, got {len(scans)}"
        )
    finally:
        q.close()


def test_maybe_reconcile_enqueues_one_reconcile(tmp_path: Path):
    """After the first idle tick seeds the clock, the next tick (with
    the interval expired) enqueues exactly one P4 ``reconcile`` job
    with an empty payload."""
    rtfm_dir = tmp_path / ".rtfm"
    rtfm_dir.mkdir(parents=True)
    db = rtfm_dir / "library.db"
    Library(str(db)).close()

    worker = _make_worker(rtfm_dir, db)
    # First call: seeds the clock, no enqueue.
    worker._maybe_reconcile()
    pending = worker._queue.list_pending(limit=10_000)
    assert [j for j in pending if j.type == "reconcile"] == []

    # Pretend the interval has expired. time.monotonic() has an
    # implementation-defined origin (boot time on Linux), so on a
    # short-lived CI runner monotonic() can return less than the default
    # reconcile_interval (3600s). Force expiration with a value that is
    # guaranteed to be old enough relative to whatever monotonic returns.
    import time as _t
    worker._last_reconcile_at = _t.monotonic() - worker.reconcile_interval - 1
    worker._maybe_reconcile()

    # Verify via the worker's own queue connection — on older SQLite
    # builds (Python 3.11 ships 3.40) a freshly-opened second connection
    # can briefly miss the very-recent WAL write, even in autocommit mode.
    pending = worker._queue.list_pending(limit=10_000)
    rec = [j for j in pending if j.type == "reconcile"]
    assert len(rec) == 1, f"expected 1 reconcile job, got {len(rec)}"
    assert rec[0].priority == P_RECONCILE
    assert rec[0].payload == {}


def test_memory_limit_resolver_reads_env(monkeypatch):
    """RTFM_WORKER_MEMORY_LIMIT_GB overrides the default; an empty or
    non-positive value falls back / disables the cap."""
    from rtfm.core import worker as _wm
    monkeypatch.delenv("RTFM_WORKER_MEMORY_LIMIT_GB", raising=False)
    assert _wm._resolve_memory_limit_gb() == _wm.WORKER_MEMORY_LIMIT_GB
    monkeypatch.setenv("RTFM_WORKER_MEMORY_LIMIT_GB", "12")
    assert _wm._resolve_memory_limit_gb() == 12.0
    monkeypatch.setenv("RTFM_WORKER_MEMORY_LIMIT_GB", "0")
    assert _wm._resolve_memory_limit_gb() == 0.0  # opt-out
    monkeypatch.setenv("RTFM_WORKER_MEMORY_LIMIT_GB", "garbage")
    assert _wm._resolve_memory_limit_gb() == _wm.WORKER_MEMORY_LIMIT_GB


def test_rss_threshold_triggers_clean_exit(tmp_path: Path, monkeypatch):
    """When RSS climbs past the safety threshold, the worker's check
    flags it so the main loop exits cleanly (the next hook respawns)."""
    rtfm_dir = tmp_path / ".rtfm"
    rtfm_dir.mkdir(parents=True)
    db = rtfm_dir / "library.db"
    Library(str(db)).close()
    from rtfm.core import worker as _wm

    w = _wm.Worker(rtfm_dir=rtfm_dir, db_path=db, handlers=HANDLERS)
    # Below threshold → no exit.
    monkeypatch.setattr(_wm, "_read_rss_mb", lambda: 100.0)
    assert w._rss_over_threshold() is False
    # Above threshold → exit signal.
    monkeypatch.setattr(_wm, "_read_rss_mb", lambda: float(_wm.WORKER_RSS_EXIT_MB + 1))
    assert w._rss_over_threshold() is True
    # /proc unavailable (returns 0) → no decision, no exit.
    monkeypatch.setattr(_wm, "_read_rss_mb", lambda: 0.0)
    assert w._rss_over_threshold() is False


def test_version_changed_detects_upgrade(tmp_path: Path, monkeypatch):
    """The version-drift check must flag a divergence between the
    captured startup version and the on-disk one — so a long-running
    worker exits cleanly after ``pipx install --force`` instead of
    silently keeping the stale in-memory code.
    """
    rtfm_dir = tmp_path / ".rtfm"
    rtfm_dir.mkdir(parents=True)
    db = rtfm_dir / "library.db"
    Library(str(db)).close()
    from rtfm.core import worker as _wm

    # Pretend disk reports 0.18.0 for the duration of the test.
    current = {"v": "0.18.0"}
    monkeypatch.setattr(_wm, "_read_installed_version", lambda: current["v"])

    w = _wm.Worker(rtfm_dir=rtfm_dir, db_path=db, handlers=HANDLERS)
    # Startup captured 0.18.0; disk still 0.18.0 → no drift.
    assert w._version_changed() is False
    # Disk bumps to 0.19.0 → drift.
    current["v"] = "0.19.0"
    assert w._version_changed() is True
    # Source-checkout fallback ('unknown' on either side) disables
    # the check so a developer running from a working tree isn't
    # bothered.
    w._our_version = "unknown"
    assert w._version_changed() is False
    current["v"] = "unknown"
    w._our_version = "0.18.0"
    assert w._version_changed() is False


def test_maybe_scan_throttle_blocks_within_interval(tmp_path: Path):
    """A second call within ``scan_interval`` seconds of the first is a
    no-op — it never even reaches the queue, regardless of dedup."""
    rtfm_dir = tmp_path / ".rtfm"
    src = tmp_path / "src"
    src.mkdir()
    _write_config(rtfm_dir, [{"path": str(src), "corpus": "alpha"}])
    db = rtfm_dir / "library.db"
    Library(str(db)).close()

    worker = _make_worker(rtfm_dir, db)
    worker._maybe_scan()  # first tick: enqueues 1 scan

    q = Queue(db)
    try:
        n_before = len([j for j in q.list_pending() if j.type == "scan"])
    finally:
        q.close()

    # Second tick within the throttle window: no-op.
    worker._maybe_scan()
    q = Queue(db)
    try:
        n_after = len([j for j in q.list_pending() if j.type == "scan"])
    finally:
        q.close()

    assert n_before == 1
    assert n_after == 1  # throttle held; nothing new enqueued


def test_maybe_scan_falls_back_to_project_root_without_config(tmp_path: Path):
    """When ``.rtfm/config.json`` has no ``sources`` entry, the worker
    falls back to a single implicit source: the project root with the
    default corpus name."""
    rtfm_dir = tmp_path / ".rtfm"
    rtfm_dir.mkdir(parents=True)
    # No config.json on disk.
    db = rtfm_dir / "library.db"
    Library(str(db)).close()

    worker = _make_worker(rtfm_dir, db)
    worker._maybe_scan()

    q = Queue(db)
    try:
        scans = [j for j in q.list_pending() if j.type == "scan"]
        assert len(scans) == 1, f"expected 1 scan job, got {len(scans)}"
        assert scans[0].payload["root"] == str(tmp_path.resolve())
        assert scans[0].payload["corpus"] == "default"
        assert scans[0].payload["extensions"] is None
    finally:
        q.close()
