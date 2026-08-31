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
import sqlite3
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import pytest

from rtfm.core import supervisor as sup_mod
from rtfm.core.supervisor import Supervisor, _Slot
from rtfm.core.library import Library
from rtfm.core.queue import Queue



def _sync(sup):
    """Sync the registry and wait for the projects to finish opening.

    Opening is asynchronous in the supervisor (each database is integrity-
    checked on a side pool so one big corpus cannot hold up the fleet); tests
    want the settled state.
    """
    sup._sync_registry()
    deadline = time.monotonic() + 30
    while sup._opening and time.monotonic() < deadline:
        sup._collect_opened()
        time.sleep(0.005)
    sup._collect_opened()


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
        _sync(sup)
        slot = _only_slot(sup)
        sup._enqueue_scans(slot)

        q = Queue(rtfm_dir / "library.db")
        try:
            scans = [j for j in q.list_pending(limit=10_000) if j.type == "scan"]
            assert len(scans) == 2
            by_corpus = {j.payload["corpus"]: j for j in scans}
            assert set(by_corpus) == {"alpha", "beta"}
            assert by_corpus["alpha"].payload["extensions"] == ".md,.py"
            # A source that restricts nothing says nothing: the queue
            # deduplicates on the payload JSON, so spelling out defaults
            # would stop identical scans from matching each other.
            assert "extensions" not in by_corpus["beta"].payload
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
        _sync(sup)
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
        _sync(sup)
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
        _sync(sup)
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
        _sync(sup)
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
        _sync(sup)
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
        _sync(sup)
        assert set(sup._slots) == {str(a)}

        # Add b.
        reg.write_text(json.dumps({"projects": [str(a), str(b)]}), encoding="utf-8")
        sup._registry_mtime = -1.0  # force re-read regardless of mtime granularity
        _sync(sup)
        assert set(sup._slots) == {str(a), str(b)}

        # Remove a (idle slot → dropped).
        reg.write_text(json.dumps({"projects": [str(b)]}), encoding="utf-8")
        sup._registry_mtime = -1.0
        _sync(sup)
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
        _sync(sup)
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


class TestHookRefresh:
    """A hook bug must not survive an upgrade just because the script lives
    inside the project. The supervisor always runs the installed code, so it
    is what brings every registered project's stubs up to date."""

    def _project(self, tmp_path):
        from rtfm.core.library import Library
        from rtfm.plugin.hooks import install_hook

        root = tmp_path / "proj"
        root.mkdir()
        Library(root / ".rtfm" / "library.db").close()
        install_hook(root, corpus="t")
        return root

    def test_outdated_stub_is_rewritten_when_the_project_is_picked_up(self, tmp_path):
        from rtfm.core.supervisor import Supervisor, _Slot

        root = self._project(tmp_path)
        stub = root / ".claude" / "hooks" / "rtfm_posttool_sync.py"
        stub.write_text("# logic from an RTFM release long gone\n")

        sup = Supervisor.__new__(Supervisor)
        sup._log = lambda msg: None
        sup._refresh_hooks(_Slot(root / ".rtfm"))

        assert "hook_runtime import on_file_edited" in stub.read_text()

    def test_project_without_hooks_is_left_alone(self, tmp_path):
        from rtfm.core.library import Library
        from rtfm.core.supervisor import Supervisor, _Slot

        root = tmp_path / "bare"
        root.mkdir()
        Library(root / ".rtfm" / "library.db").close()

        sup = Supervisor.__new__(Supervisor)
        sup._log = lambda msg: None
        sup._refresh_hooks(_Slot(root / ".rtfm"))  # must not raise

        assert not (root / ".claude").exists()


class TestUserLaneReserve:
    """Priority decides who takes the next free lane — but on a busy fleet
    there is no next free lane for minutes. P_USER work gets its own."""

    def _sup(self, tmp_path, slots):
        from rtfm.core.supervisor import Supervisor

        sup = Supervisor.__new__(Supervisor)
        sup._log = lambda msg: None
        sup._max_concurrent = 2
        sup._slots = slots
        sup._inflight = {}
        sup._pool = None
        return sup

    def _slot(self, tmp_path, name, head):
        """A slot whose queue reports *head* as ``(priority, created_at, type)``."""
        from rtfm.core.library import Library
        from rtfm.core.supervisor import _Slot

        root = tmp_path / name
        (root / ".rtfm").mkdir(parents=True)
        Library(root / ".rtfm" / "library.db").close()
        slot = _Slot(root / ".rtfm")

        class _Q:
            def __init__(self):
                self.dequeued = 0

            def peek(self_inner):
                return head

            def dequeue(self_inner):
                from rtfm.core.queue import Job
                self_inner.dequeued += 1
                return Job(id=1, type=head[2], priority=head[0],
                           payload={}, status="running", created_at=head[1],
                           started_at=None, finished_at=None, error=None,
                           attempts=1)

        slot.queue = _Q()
        return slot

    def test_user_job_starts_when_every_ordinary_lane_is_busy(self, tmp_path):
        from rtfm.core.queue import P_USER

        slot = self._slot(tmp_path, "urgent", (P_USER, "2026-01-01T00:00:00Z", "ingest"))
        sup = self._sup(tmp_path, {"a": slot})
        sup._pool = _RecordingPool()
        sup._inflight = {object(): (slot, None), object(): (slot, None)}  # cap full

        assert sup._dispatch() is True
        assert sup._pool.submitted >= 1

    def test_background_job_waits_for_an_ordinary_lane(self, tmp_path):
        from rtfm.core.queue import P_DOC

        slot = self._slot(tmp_path, "bg", (P_DOC, "2026-01-01T00:00:00Z", "ingest"))
        sup = self._sup(tmp_path, {"a": slot})
        sup._pool = _RecordingPool()
        sup._inflight = {object(): (slot, None), object(): (slot, None)}

        assert sup._dispatch() is False
        assert sup._pool.submitted == 0

    def test_reserve_is_bounded(self, tmp_path):
        """The reserve is extra capacity, not unlimited capacity."""
        from rtfm.core.queue import P_USER
        from rtfm.core.supervisor import P_USER_RESERVED_LANES

        slot = self._slot(tmp_path, "many", (P_USER, "2026-01-01T00:00:00Z", "ingest"))
        sup = self._sup(tmp_path, {"a": slot})
        sup._pool = _RecordingPool()
        sup._inflight = {object(): (slot, None) for _ in range(2)}

        sup._dispatch()
        assert sup._pool.submitted == P_USER_RESERVED_LANES


class _RecordingPool:
    def __init__(self):
        self.submitted = 0

    def submit(self, fn, *args):
        self.submitted += 1
        fut = Future()
        fut.set_result(None)
        return fut


class TestSchedulingNeverTouchesSourceFilesystem:
    """One source on an unreachable network mount must not be able to freeze
    scheduling for the whole fleet — the scheduler stays lexical."""

    def test_scan_is_enqueued_without_stat_ing_the_source(self, tmp_path, monkeypatch):
        from rtfm.config import add_source, save_config
        from rtfm.core.library import Library
        from rtfm.core.supervisor import Supervisor, _Slot

        root = tmp_path / "proj"
        (root / ".rtfm").mkdir(parents=True)
        Library(root / ".rtfm" / "library.db").close()
        save_config(root, {"corpus": "default"})
        add_source(root, "/mnt/unreachable/corpus", "remote")

        slot = _Slot(root / ".rtfm")
        slot.open(lambda m: None)

        def _explode(*a, **k):
            raise AssertionError("scheduler touched the source filesystem")

        monkeypatch.setattr(Path, "resolve", _explode)
        monkeypatch.setattr(Path, "is_dir", _explode)
        monkeypatch.setattr(os.path, "realpath", _explode)

        sup = Supervisor.__new__(Supervisor)
        sup._log = lambda msg: None
        sup._enqueue_scans(slot)

        head = slot.queue.peek()
        assert head is not None and head[2] == "scan"
        slot.close()


class TestStallWatchdog:
    """A single-threaded scheduler that blocks stops serving every project.
    From outside, that is indistinguishable from idle — unless it says so."""

    def _sup(self, logged):
        from rtfm.core.supervisor import Supervisor

        sup = Supervisor.__new__(Supervisor)
        sup._log = logged.append
        sup._stop = False
        sup._step_name = None
        sup._step_started = 0.0
        sup._step_warned = False
        return sup

    def test_names_the_step_it_is_stuck_in(self, monkeypatch):
        from rtfm.core import supervisor as mod

        monkeypatch.setattr(mod, "STALL_WARN_SECONDS", 0.05)
        monkeypatch.setattr(mod, "STALL_POLL_SECONDS", 0.01)

        logged: list[str] = []
        sup = self._sup(logged)
        sup._start_stall_watchdog()

        with sup._step("enqueue-periodic"):
            time.sleep(0.3)
        sup._stop = True

        assert any("STALL" in m and "enqueue-periodic" in m for m in logged)

    def test_quiet_when_steps_are_quick(self, monkeypatch):
        from rtfm.core import supervisor as mod

        monkeypatch.setattr(mod, "STALL_WARN_SECONDS", 5.0)
        monkeypatch.setattr(mod, "STALL_POLL_SECONDS", 0.01)

        logged: list[str] = []
        sup = self._sup(logged)
        sup._start_stall_watchdog()

        for _ in range(20):
            with sup._step("dispatch"):
                pass
        time.sleep(0.1)
        sup._stop = True

        assert logged == []

    def test_warns_once_per_step(self, monkeypatch):
        from rtfm.core import supervisor as mod

        monkeypatch.setattr(mod, "STALL_WARN_SECONDS", 0.05)
        monkeypatch.setattr(mod, "STALL_POLL_SECONDS", 0.01)

        logged: list[str] = []
        sup = self._sup(logged)
        sup._start_stall_watchdog()

        with sup._step("dispatch"):
            time.sleep(0.4)
        sup._stop = True

        assert len([m for m in logged if "STALL" in m]) == 1


class TestProgressiveOpening:
    """A project joins the fleet as soon as its own database checks out.
    One large corpus must not keep every other project unserved while it is
    verified — that cost ten minutes of blindness on every restart."""

    def _project(self, tmp_path, name):
        rtfm_dir = tmp_path / name / ".rtfm"
        rtfm_dir.mkdir(parents=True)
        Library(str(rtfm_dir / "library.db")).close()
        return rtfm_dir

    def test_a_slow_database_does_not_hold_up_the_others(self, tmp_path, monkeypatch):
        slow = self._project(tmp_path, "slow")
        quick = self._project(tmp_path, "quick")

        release = threading.Event()
        real = sup_mod.ensure_healthy_db

        def gated(db_path, log=None):
            if Path(db_path).parent.parent.name == "slow":
                release.wait(timeout=10)
            return real(db_path, log=log)

        monkeypatch.setattr(sup_mod, "ensure_healthy_db", gated)

        sup = _make_sup(_registry(tmp_path, [slow, quick]))
        try:
            sup._sync_registry()
            deadline = time.monotonic() + 10
            while str(quick) not in sup._slots and time.monotonic() < deadline:
                sup._collect_opened()
                time.sleep(0.005)

            # Served already, while the slow one is still being checked.
            assert str(quick) in sup._slots
            assert str(slow) not in sup._slots

            release.set()
            deadline = time.monotonic() + 10
            while sup._opening and time.monotonic() < deadline:
                sup._collect_opened()
                time.sleep(0.005)
            assert str(slow) in sup._slots
        finally:
            release.set()
            sup._opener.shutdown(wait=False)
            sup._pool.shutdown(wait=False)

    def test_scheduling_is_not_blocked_while_a_project_opens(self, tmp_path, monkeypatch):
        """The whole point: the scheduling step returns immediately."""
        slow = self._project(tmp_path, "slow")
        release = threading.Event()

        monkeypatch.setattr(sup_mod, "ensure_healthy_db",
                            lambda db_path, log=None: release.wait(timeout=10) or False)

        sup = _make_sup(_registry(tmp_path, [slow]))
        try:
            t0 = time.monotonic()
            sup._sync_registry()
            assert time.monotonic() - t0 < 0.5
            assert sup._opening  # the work is in flight, not done inline
        finally:
            release.set()
            sup._opener.shutdown(wait=False)
            sup._pool.shutdown(wait=False)

    def test_a_project_unregistered_while_opening_is_dropped(self, tmp_path):
        gone = self._project(tmp_path, "gone")
        reg = _registry(tmp_path, [gone])
        sup = _make_sup(reg)
        try:
            sup._sync_registry()
            sup._wanted = set()  # unregistered before its check finished
            deadline = time.monotonic() + 10
            while sup._opening and time.monotonic() < deadline:
                sup._collect_opened()
                time.sleep(0.005)
            assert sup._slots == {}
        finally:
            sup._opener.shutdown(wait=False)
            sup._pool.shutdown(wait=False)


class TestStrandedClaims:
    """A ``running`` row is a promise that something is working on it. When
    that stops being true and nobody notices, the file is silently never
    indexed. Twenty-six rows sat that way for up to fifty hours on a live,
    healthy, busy supervisor — because the only reclaim ran at startup."""

    def _count(self, slot, status: str) -> int:
        row = slot.queue._get_conn().execute(
            "SELECT COUNT(*) FROM work_queue WHERE status = ?", (status,)
        ).fetchone()
        return row[0]

    def _project(self, tmp_path: Path) -> Path:
        rtfm_dir = tmp_path / "proj" / ".rtfm"
        src = tmp_path / "src"
        src.mkdir()
        _write_config(rtfm_dir, [{"path": str(src), "corpus": "default"}])
        Library(str(rtfm_dir / "library.db")).close()
        return rtfm_dir

    def test_a_claim_nobody_runs_is_returned_to_the_queue(self, tmp_path):
        rtfm_dir = self._project(tmp_path)
        sup = _make_sup(_registry(tmp_path, [rtfm_dir]))
        try:
            _sync(sup)
            slot = _only_slot(sup)
            slot.queue.enqueue("ingest", {"f": "stranded"})
            job = slot.queue.dequeue()            # claimed…
            assert self._count(slot, "running") == 1
            # …and nothing in _inflight is running it. That is the whole bug.
            assert not sup._inflight

            sup._sweep_stale_claims()

            assert self._count(slot, "running") == 0
            assert self._count(slot, "pending") == 1
            assert slot.queue.dequeue().id == job.id
        finally:
            sup._shutdown()

    def test_the_sweep_never_touches_a_job_actually_in_flight(self, tmp_path):
        """The sweep runs every minute against live projects, so a false
        positive would requeue running work and index the same file twice."""
        rtfm_dir = self._project(tmp_path)
        sup = _make_sup(_registry(tmp_path, [rtfm_dir]))
        try:
            _sync(sup)
            slot = _only_slot(sup)
            slot.queue.enqueue("ingest", {"f": "live"})
            slot.queue.enqueue("ingest", {"f": "stranded"})
            live = slot.queue.dequeue()
            slot.queue.dequeue()

            # Stand in for a dispatched job: present in _inflight, unfinished.
            fut: Future = Future()
            sup._inflight[fut] = (slot, live)

            sup._sweep_stale_claims()

            assert self._count(slot, "running") == 1, "the live job was reaped"
            assert self._count(slot, "pending") == 1
            sup._inflight.pop(fut)
        finally:
            sup._shutdown()

    def test_a_failed_submit_hands_the_claim_back(self, tmp_path):
        """``dequeue`` marks the row running before the future exists. If the
        submit raises in between, the row belongs to nobody."""
        rtfm_dir = self._project(tmp_path)
        sup = _make_sup(_registry(tmp_path, [rtfm_dir]))
        try:
            _sync(sup)
            slot = _only_slot(sup)
            slot.queue.enqueue("ingest", {"f": "doomed"})

            class _RefusingPool:
                def submit(self, *a, **k):
                    raise RuntimeError("cannot schedule new futures")

            sup._pool = _RefusingPool()
            sup._dispatch()

            assert self._count(slot, "running") == 0, \
                "claim left dangling after submit"
            assert self._count(slot, "pending") == 1
        finally:
            sup._pool = ThreadPoolExecutor(max_workers=1)
            sup._shutdown()

    def test_a_close_that_cannot_be_written_is_reported_not_swallowed(
            self, tmp_path):
        """The closing write is what releases a claim. Losing it silently is
        how a row stays running forever with nothing in any log."""
        rtfm_dir = self._project(tmp_path)
        lines: list[str] = []
        sup = _make_sup(_registry(tmp_path, [rtfm_dir]))
        try:
            _sync(sup)
            slot = _only_slot(sup)
            slot.log = lines.append
            slot.queue.enqueue("ingest", {"f": "unclosable"})
            job = slot.queue.dequeue()

            def _refuse(*a, **k):
                raise sqlite3.OperationalError("database is locked")

            slot.queue.mark_done = _refuse
            fut: Future = Future()
            fut.set_result(None)
            sup._inflight[fut] = (slot, job)

            sup._reap_finished()

            assert any("mark_done failed after 3 tries" in ln for ln in lines), \
                f"the lost close left no trace: {lines}"
            # And the sweep is what actually repairs it.
            sup._sweep_stale_claims()
            assert self._count(slot, "pending") == 1
        finally:
            sup._shutdown()


class TestTheSupervisorChecksItsOwnIndexes:
    """Findings have to reach a log, not wait for someone to run a command.

    Every defect the audit looks for ran for weeks while the logs said
    nothing was wrong. An hourly line the day it starts is the whole point.
    """

    def test_findings_are_written_to_the_project_log(self, tmp_path, monkeypatch):
        import rtfm.core.supervisor as sup
        from rtfm.core.library import Library

        rtfm_dir = tmp_path / "proj" / ".rtfm"
        rtfm_dir.mkdir(parents=True)
        db = rtfm_dir / "library.db"
        lib = Library(str(db))
        lib.record_ingest_failure("broken.pdf", "c", "h", 10, "boom")
        lib.close()

        logged: list[str] = []
        slot = sup._Slot(rtfm_dir)
        slot.log = logged.append

        supervisor = sup.Supervisor.__new__(sup.Supervisor)
        supervisor._slots = {str(rtfm_dir): slot}
        supervisor._next_audit = 0.0

        supervisor._audit_indexes()
        # It runs off the dispatcher thread — a watchdog must never be able
        # to block the work it watches.
        for t in threading.enumerate():
            if t.name == "rtfm-audit":
                t.join(timeout=10)

        assert any("audit: silent-drops" in line for line in logged), logged

    def test_it_only_runs_on_its_own_schedule(self, tmp_path):
        import time

        import rtfm.core.supervisor as sup
        from rtfm.core.library import Library

        rtfm_dir = tmp_path / "proj" / ".rtfm"
        rtfm_dir.mkdir(parents=True)
        lib = Library(str(rtfm_dir / "library.db"))
        lib.record_ingest_failure("broken.pdf", "c", "h", 10, "boom")
        lib.close()

        logged: list[str] = []
        slot = sup._Slot(rtfm_dir)
        slot.log = logged.append

        supervisor = sup.Supervisor.__new__(sup.Supervisor)
        supervisor._slots = {str(rtfm_dir): slot}
        supervisor._next_audit = time.monotonic() + 3600

        supervisor._audit_indexes()
        for t in threading.enumerate():
            if t.name == "rtfm-audit":
                t.join(timeout=10)
        assert logged == []


class TestScanningDoesNotStarveTheWorkItFinds:
    """A scan holds the project's slot alone. On a project with two dozen
    source directories a full round takes minutes, and the round was
    re-enqueued every minute — so nothing else ever ran. One project sat at
    81 000 pending embeddings for a day, scanning without pause and finding
    nothing each time.

    Looking for more work while that much is already waiting is pointless.
    """

    def _slot_with_backlog(self, tmp_path, pending):
        import rtfm.core.supervisor as sup
        from rtfm.core.library import Library
        from rtfm.core.queue import Queue

        rtfm_dir = tmp_path / "proj" / ".rtfm"
        rtfm_dir.mkdir(parents=True)
        db = rtfm_dir / "library.db"
        Library(str(db)).close()
        q = Queue(str(db))
        for i in range(pending):
            q.enqueue("embed", {"chunk_id": f"c{i}"})

        slot = sup._Slot(rtfm_dir)
        slot.queue = q
        slot.logs = []
        slot.log = slot.logs.append
        return slot

    def _supervisor(self, slot):
        import rtfm.core.supervisor as sup

        s = sup.Supervisor.__new__(sup.Supervisor)
        s._slots = {"p": slot}
        s._scan_interval = 60.0
        s._reconcile_interval = 3600.0
        s.enqueued = []
        s._enqueue_scans = lambda sl: s.enqueued.append(sl)
        return s

    def test_a_large_backlog_pauses_the_periodic_scan(self, tmp_path):
        import rtfm.core.supervisor as sup

        slot = self._slot_with_backlog(tmp_path, sup.SCAN_BACKLOG_PAUSE + 5)
        supervisor = self._supervisor(slot)
        supervisor._enqueue_periodic()

        assert supervisor.enqueued == []
        assert any("paused" in line for line in slot.logs), slot.logs
        slot.queue.close()

    def test_a_quiet_project_still_gets_scanned(self, tmp_path):
        slot = self._slot_with_backlog(tmp_path, 3)
        supervisor = self._supervisor(slot)
        supervisor._enqueue_periodic()

        assert supervisor.enqueued == [slot]
        slot.queue.close()

    def test_pending_scans_do_not_count_as_a_backlog(self, tmp_path):
        """A queue full of scans is the state this stops, not a reason to
        keep going."""
        import rtfm.core.supervisor as sup

        slot = self._slot_with_backlog(tmp_path, 0)
        for i in range(sup.SCAN_BACKLOG_PAUSE + 5):
            slot.queue.enqueue("scan", {"root": f"/r{i}", "corpus": "c"})
        supervisor = self._supervisor(slot)
        supervisor._enqueue_periodic()

        assert supervisor.enqueued == [slot]
        slot.queue.close()

    def test_it_says_when_it_starts_again(self, tmp_path):
        import rtfm.core.supervisor as sup

        slot = self._slot_with_backlog(tmp_path, sup.SCAN_BACKLOG_PAUSE + 5)
        supervisor = self._supervisor(slot)
        supervisor._enqueue_periodic()
        assert supervisor.enqueued == []

        # Backlog drains; the next round goes ahead and says so.
        conn = slot.queue._get_conn()
        conn.execute("DELETE FROM work_queue WHERE type = 'embed'")
        conn.commit()
        slot.next_scan_at = 0.0
        supervisor._enqueue_periodic()

        assert supervisor.enqueued == [slot]
        assert any("resumed" in line for line in slot.logs), slot.logs
        slot.queue.close()
