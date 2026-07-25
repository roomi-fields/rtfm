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


def test_single_writer_never_two_jobs_per_project(tmp_path: Path, monkeypatch):
    """The core corruption-proofing invariant: even with free pool slots and
    several pending jobs, a project never has two jobs in flight at once."""
    rtfm_dir = tmp_path / "proj" / ".rtfm"
    src = tmp_path / "src"; src.mkdir()
    rtfm_dir.mkdir(parents=True)
    Library(str(rtfm_dir / "library.db")).close()

    gate = threading.Event()

    def blocking(job, ctx):
        gate.wait(timeout=5.0)

    import rtfm.core.handlers as handlers_mod
    monkeypatch.setitem(handlers_mod.HANDLERS, "reconcile", blocking)
    monkeypatch.setitem(handlers_mod.HANDLERS, "scan", blocking)

    sup = _make_sup(_registry(tmp_path, [rtfm_dir]), max_concurrent=2)
    try:
        sup._sync_registry()
        slot = _only_slot(sup)
        # Two distinct pending jobs for the *same* project.
        slot.queue.enqueue("reconcile", {})
        slot.queue.enqueue("scan", {"root": str(src), "corpus": "x"})

        # Pool has 2 free slots, but the project may only run one at a time.
        assert sup._dispatch() is True
        assert len(sup._inflight) == 1
        # Dispatching again while the first is in flight must not start a
        # second job for this project.
        assert sup._dispatch() is False
        assert len(sup._inflight) == 1

        gate.set()
        _drain(sup)
        # After the first drains, the second finally runs.
        sup._dispatch()
        _drain(sup)
        q = Queue(rtfm_dir / "library.db")
        try:
            stats = q.stats()
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


def test_concurrency_clamped_to_at_least_one(tmp_path: Path):
    # A configured 0 (unlimited) is meaningless for a thread pool → clamp.
    sup = Supervisor(registry_path=_registry(tmp_path, []),
                     log=lambda m: None, max_concurrent=0)
    try:
        assert sup._max_concurrent == 1
    finally:
        sup._pool.shutdown(wait=False)
