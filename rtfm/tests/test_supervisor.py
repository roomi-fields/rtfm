"""Tests for the mutualised worker (:mod:`rtfm.core.supervisor`).

Covers the behaviours that used to live in the per-project ``Worker`` plus
the invariants that make the single-process model safe:

- staggered scan / reconcile enqueue (per source, deduped),
- recycle-on-version-drift and recycle-on-RSS,
- the integrity guard quarantining a corrupt DB on first open,
- the dispatcher running a handler and marking the row done,
- the single-writer invariant: never two in-flight jobs for one project.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from rtfm.core import supervisor as sup_mod
from rtfm.core.supervisor import Supervisor, _Slot
from rtfm.core.library import Library
from rtfm.core.queue import Queue


def _write_config(rtfm_dir: Path, sources: list[dict]) -> None:
    rtfm_dir.mkdir(parents=True, exist_ok=True)
    (rtfm_dir / "config.json").write_text(
        json.dumps({"sources": sources}), encoding="utf-8")


def _registry(tmp_path: Path, rtfm_dirs: list[Path]) -> Path:
    reg = tmp_path / "workers.json"
    reg.write_text(json.dumps({"projects": [str(d) for d in rtfm_dirs]}),
                   encoding="utf-8")
    return reg


def _make_sup(registry: Path, **kw) -> Supervisor:
    return Supervisor(registry_path=registry, log=lambda m: None,
                      max_concurrent=kw.pop("max_concurrent", 2), **kw)


def _only_slot(sup: Supervisor) -> _Slot:
    return next(iter(sup._slots.values()))


# ── scan / reconcile enqueue ─────────────────────────────────────────────


def test_enqueue_scans_one_per_source(tmp_path: Path):
    rtfm_dir = tmp_path / "proj" / ".rtfm"
    src_a = tmp_path / "src-a"; src_a.mkdir()
    src_b = tmp_path / "src-b"; src_b.mkdir()
    _write_config(rtfm_dir, [
        {"path": str(src_a), "corpus": "alpha", "extensions": ".md,.py"},
        {"path": str(src_b), "corpus": "beta"},
    ])
    Library(str(rtfm_dir / "library.db")).close()

    sup = _make_sup(_registry(tmp_path, [rtfm_dir]))
    try:
        sup._sync_registry()
        slot = _only_slot(sup)
        sup._enqueue_scans(slot)

        q = Queue(rtfm_dir / "library.db")
        try:
            scans = [j for j in q.list_pending(limit=10_000) if j.type == "scan"]
            assert len(scans) == 2
            by_corpus = {j.payload["corpus"]: j for j in scans}
            assert set(by_corpus) == {"alpha", "beta"}
            assert by_corpus["alpha"].payload["extensions"] == ".md,.py"
            assert by_corpus["beta"].payload["extensions"] is None
        finally:
            q.close()
    finally:
        sup._pool.shutdown(wait=False)


def test_enqueue_scans_dedup_on_repeat(tmp_path: Path):
    rtfm_dir = tmp_path / "proj" / ".rtfm"
    src = tmp_path / "src"; src.mkdir()
    _write_config(rtfm_dir, [{"path": str(src), "corpus": "alpha"}])
    Library(str(rtfm_dir / "library.db")).close()

    sup = _make_sup(_registry(tmp_path, [rtfm_dir]))
    try:
        sup._sync_registry()
        slot = _only_slot(sup)
        sup._enqueue_scans(slot)
        sup._enqueue_scans(slot)  # dedup index drops the duplicate
        q = Queue(rtfm_dir / "library.db")
        try:
            scans = [j for j in q.list_pending(limit=10_000) if j.type == "scan"]
            assert len(scans) == 1
        finally:
            q.close()
    finally:
        sup._pool.shutdown(wait=False)


def test_periodic_reconcile_seeds_then_enqueues(tmp_path: Path):
    rtfm_dir = tmp_path / "proj" / ".rtfm"
    rtfm_dir.mkdir(parents=True)
    Library(str(rtfm_dir / "library.db")).close()

    sup = _make_sup(_registry(tmp_path, [rtfm_dir]))
    try:
        sup._sync_registry()
        slot = _only_slot(sup)
        # Suppress scans so we isolate reconcile.
        slot.next_scan_at = time.monotonic() + 10_000

        sup._enqueue_periodic()          # first pass: seeds the reconcile clock
        q = Queue(rtfm_dir / "library.db")
        try:
            assert [j for j in q.list_pending(limit=10_000) if j.type == "reconcile"] == []
        finally:
            q.close()

        slot.next_reconcile_at = time.monotonic() - 1   # force expiry
        slot.next_scan_at = time.monotonic() + 10_000
        sup._enqueue_periodic()
        q = Queue(rtfm_dir / "library.db")
        try:
            rec = [j for j in q.list_pending(limit=10_000) if j.type == "reconcile"]
            assert len(rec) == 1 and rec[0].payload == {}
        finally:
            q.close()
    finally:
        sup._pool.shutdown(wait=False)


# ── recycle triggers ─────────────────────────────────────────────────────


def test_should_recycle_on_version_and_rss(tmp_path: Path, monkeypatch):
    sup = _make_sup(_registry(tmp_path, []))
    try:
        sup._our_version = "1.0.0"
        monkeypatch.setattr(sup_mod, "_read_installed_version", lambda: "1.0.0")
        monkeypatch.setattr(sup_mod, "_read_rss_mb", lambda: 100.0)
        assert sup._should_recycle() is False

        monkeypatch.setattr(sup_mod, "_read_installed_version", lambda: "2.0.0")
        assert sup._should_recycle() is True          # version drift

        monkeypatch.setattr(sup_mod, "_read_installed_version", lambda: "1.0.0")
        ceiling = sup_mod.WORKER_RSS_EXIT_MB * sup._max_concurrent
        monkeypatch.setattr(sup_mod, "_read_rss_mb", lambda: float(ceiling + 1))
        assert sup._should_recycle() is True          # RSS over ceiling
    finally:
        sup._pool.shutdown(wait=False)


# ── integrity guard ──────────────────────────────────────────────────────


def test_slot_open_quarantines_corrupt_db(tmp_path: Path):
    rtfm_dir = tmp_path / "proj" / ".rtfm"
    rtfm_dir.mkdir(parents=True)
    db = rtfm_dir / "library.db"
    db.write_bytes(b"not a sqlite database at all" * 100)

    slot = _Slot(rtfm_dir)
    rebuilt = slot.open(log=lambda m: None)
    try:
        assert rebuilt is True                        # signalled a rebuild
        # The corrupt file was moved aside; a fresh, working DB replaced it.
        assert list(rtfm_dir.glob("library.db.corrupt-*"))
        assert slot.queue is not None
        assert slot.queue.enqueue("reconcile", {}) is not None
    finally:
        slot.close()


# ── runtime corruption self-heal ─────────────────────────────────────────


def test_is_db_corruption_matches_only_corruption():
    from rtfm.core.supervisor import _is_db_corruption
    import sqlite3
    assert _is_db_corruption(sqlite3.DatabaseError("database disk image is malformed"))
    assert _is_db_corruption(sqlite3.DatabaseError("file is not a database"))
    # Transient lock/busy must NOT be treated as corruption.
    assert not _is_db_corruption(sqlite3.OperationalError("database is locked"))
    assert not _is_db_corruption(ValueError("some unrelated error"))


def test_recover_slot_quarantines_and_reopens(tmp_path: Path):
    rtfm_dir = tmp_path / "proj" / ".rtfm"
    rtfm_dir.mkdir(parents=True)
    # A DB that was healthy at boot then went malformed under the running
    # supervisor: quarantine it, reopen a fresh one, schedule a rebuild scan.
    (rtfm_dir / "library.db").write_bytes(b"corrupt bytes " * 500)

    sup = _make_sup(_registry(tmp_path, [rtfm_dir]))
    try:
        slot = _Slot(rtfm_dir)
        slot.next_scan_at = 1e18            # far future; recovery must reset it
        sup._recover_slot(slot)
        assert list(rtfm_dir.glob("library.db.corrupt-*"))   # quarantined
        assert slot.queue is not None                        # fresh queue open
        assert slot.queue.peek() is None                     # empty, no more errors
        assert slot.next_scan_at < 1e17                      # rebuild scheduled ASAP
    finally:
        sup._pool.shutdown(wait=False)


def test_dispatch_heals_runtime_peek_corruption(tmp_path: Path, monkeypatch):
    """A malformed DB surfacing at ``peek`` triggers recovery, not a hot loop."""
    rtfm_dir = tmp_path / "proj" / ".rtfm"
    rtfm_dir.mkdir(parents=True)
    Library(str(rtfm_dir / "library.db")).close()

    sup = _make_sup(_registry(tmp_path, [rtfm_dir]))
    try:
        sup._sync_registry()
        slot = _only_slot(sup)

        import sqlite3
        healed: list[_Slot] = []
        monkeypatch.setattr(sup, "_recover_slot", lambda s: healed.append(s))

        def boom():
            raise sqlite3.DatabaseError("database disk image is malformed")
        monkeypatch.setattr(slot.queue, "peek", boom)

        sup._dispatch()
        assert healed == [slot]             # recovery invoked exactly once
    finally:
        sup._pool.shutdown(wait=False)


# ── dispatch / reap ──────────────────────────────────────────────────────


def _drain(sup: Supervisor, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while sup._inflight and time.monotonic() < end:
        sup._reap_finished()
        time.sleep(0.02)
    sup._reap_finished()


def test_dispatch_runs_handler_and_marks_done(tmp_path: Path, monkeypatch):
    rtfm_dir = tmp_path / "proj" / ".rtfm"
    rtfm_dir.mkdir(parents=True)
    Library(str(rtfm_dir / "library.db")).close()

    calls: list[int] = []

    def fake_reconcile(job, ctx):
        calls.append(job.id)

    import rtfm.core.handlers as handlers_mod
    monkeypatch.setitem(handlers_mod.HANDLERS, "reconcile", fake_reconcile)

    sup = _make_sup(_registry(tmp_path, [rtfm_dir]))
    try:
        sup._sync_registry()
        slot = _only_slot(sup)
        slot.queue.enqueue("reconcile", {})

        assert sup._dispatch() is True
        assert len(sup._inflight) == 1 and slot.active is True
        _drain(sup)

        assert calls, "handler must have run"
        q = Queue(rtfm_dir / "library.db")
        try:
            assert q.stats().get("reconcile", {}).get("done", 0) == 1
        finally:
            q.close()
    finally:
        sup._pool.shutdown(wait=True)


def test_project_parallelises_writes_but_serialises_exclusive(
        tmp_path: Path, monkeypatch):
    """Parallelisable jobs (ingest/remove/embed) of one project run
    concurrently — that is how a single project fills several cores — while
    scan/reconcile/vacuum run alone (exclusive) so the whole-index operations
    never race a concurrent writer."""
    rtfm_dir = tmp_path / "proj" / ".rtfm"
    src = tmp_path / "src"; src.mkdir()
    rtfm_dir.mkdir(parents=True)
    Library(str(rtfm_dir / "library.db")).close()

    gate = threading.Event()

    def blocking(job, ctx):
        gate.wait(timeout=5.0)

    import rtfm.core.handlers as handlers_mod
    for t in ("ingest", "remove", "reconcile", "scan"):
        monkeypatch.setitem(handlers_mod.HANDLERS, t, blocking)

    sup = _make_sup(_registry(tmp_path, [rtfm_dir]), max_concurrent=4)
    try:
        sup._sync_registry()
        slot = _only_slot(sup)

        # Two parallelisable jobs for the SAME project → both run at once.
        slot.queue.enqueue("remove", {"filepath": "a", "corpus": "x"})
        slot.queue.enqueue("ingest", {"root": str(src), "corpus": "x",
                                      "filepath": "b"})
        sup._dispatch()
        assert len(sup._inflight) == 2
        assert slot.inflight == 2 and slot.exclusive is False

        gate.set(); _drain(sup)
        assert slot.inflight == 0

        # Two exclusive jobs → only one in flight at a time.
        gate.clear()
        slot.queue.enqueue("reconcile", {"n": 1})
        slot.queue.enqueue("scan", {"root": str(src), "corpus": "x"})
        sup._dispatch()
        assert len(sup._inflight) == 1
        assert slot.exclusive is True

        gate.set(); _drain(sup)
        sup._dispatch(); _drain(sup)   # the second exclusive now runs alone

        q = Queue(rtfm_dir / "library.db")
        try:
            stats = q.stats()
            assert stats.get("ingest", {}).get("done", 0) == 1
            assert stats.get("remove", {}).get("done", 0) == 1
            assert stats.get("reconcile", {}).get("done", 0) == 1
            assert stats.get("scan", {}).get("done", 0) == 1
        finally:
            q.close()
    finally:
        gate.set()
        sup._pool.shutdown(wait=True)


# ── registry sync ────────────────────────────────────────────────────────


def test_registry_sync_add_and_remove(tmp_path: Path):
    a = tmp_path / "a" / ".rtfm"; a.mkdir(parents=True)
    b = tmp_path / "b" / ".rtfm"; b.mkdir(parents=True)
    Library(str(a / "library.db")).close()
    Library(str(b / "library.db")).close()
    reg = _registry(tmp_path, [a])

    sup = _make_sup(reg)
    try:
        sup._sync_registry()
        assert set(sup._slots) == {str(a)}

        # Add b.
        reg.write_text(json.dumps({"projects": [str(a), str(b)]}), encoding="utf-8")
        sup._registry_mtime = -1.0  # force re-read regardless of mtime granularity
        sup._sync_registry()
        assert set(sup._slots) == {str(a), str(b)}

        # Remove a (idle slot → dropped).
        reg.write_text(json.dumps({"projects": [str(b)]}), encoding="utf-8")
        sup._registry_mtime = -1.0
        sup._sync_registry()
        assert set(sup._slots) == {str(b)}
    finally:
        sup._pool.shutdown(wait=False)


def test_dispatch_serves_global_arrival_order(tmp_path: Path, monkeypatch):
    """Documents run in the order they were queued, across projects — the
    oldest pending job anywhere goes first, regardless of project name. Here
    the alphabetically-last project ('zzz') queued first, so it must be
    served before 'aaa' which queued later."""
    served: list[str] = []

    def record(job, ctx):
        served.append(Path(ctx.db_path).parent.parent.name)

    import rtfm.core.handlers as handlers_mod
    monkeypatch.setitem(handlers_mod.HANDLERS, "reconcile", record)

    dirs = {}
    for name in ("aaa", "zzz"):
        d = tmp_path / name / ".rtfm"
        d.mkdir(parents=True)
        Library(str(d / "library.db")).close()
        dirs[name] = d

    sup = _make_sup(_registry(tmp_path, [dirs["aaa"], dirs["zzz"]]),
                    max_concurrent=1)
    try:
        sup._sync_registry()
        by_name = {Path(p).parent.name: s for p, s in sup._slots.items()}
        by_name["zzz"].queue.enqueue("reconcile", {"n": 1})   # oldest
        time.sleep(0.01)                                       # distinct stamp
        by_name["aaa"].queue.enqueue("reconcile", {"n": 1})   # newer

        for _ in range(10):
            sup._dispatch()
            _drain(sup)
            if len(served) >= 2:
                break

        assert served == ["zzz", "aaa"]  # arrival order, not alphabetical
    finally:
        sup._pool.shutdown(wait=True)


# ── lock-authoritative liveness (status / stop / no double-spawn) ────────


def test_supervisor_running_is_lock_authoritative(tmp_path: Path, monkeypatch):
    """Liveness comes from the flock, not the lazily-written state file — so a
    supervisor that holds the lock but hasn't snapshotted yet (the preload
    window) still reads as running. This is what makes ``stop`` actually stop
    and prevents ``start`` from spawning a second supervisor."""
    lock = tmp_path / "supervisor.lock"
    state = tmp_path / "supervisor_state.json"
    monkeypatch.setattr(sup_mod, "SUPERVISOR_LOCK", lock)
    monkeypatch.setattr(sup_mod, "SUPERVISOR_STATE", state)

    # Nothing held, no state file → not running.
    assert sup_mod._lock_holder_pid() is None
    assert sup_mod.supervisor_running() is None

    with sup_mod.SupervisorLock():
        # Held, but no snapshot on disk (mimics the preload window).
        assert sup_mod._lock_holder_pid() == os.getpid()
        st = sup_mod.supervisor_running()
        assert st is not None and st.pid == os.getpid()

    # Released → free again.
    assert sup_mod._lock_holder_pid() is None
    assert sup_mod.supervisor_running() is None


def test_concurrency_clamped_to_at_least_one(tmp_path: Path):
    # A configured 0 (unlimited) is meaningless for a thread pool → clamp.
    sup = Supervisor(registry_path=_registry(tmp_path, []),
                     log=lambda m: None, max_concurrent=0)
    try:
        assert sup._max_concurrent == 1
    finally:
        sup._pool.shutdown(wait=False)
