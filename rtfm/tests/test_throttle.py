"""Tests for the worker CPU throttle (thread cap + global semaphore)."""
from __future__ import annotations

import multiprocessing as mp
import os
import time
from pathlib import Path

import pytest

from rtfm.core import throttle


# ── Thread cap ──────────────────────────────────────────────────────────


def test_thread_cap_env_default_is_one(monkeypatch):
    monkeypatch.delenv("RTFM_EMBED_THREADS", raising=False)
    env = throttle.thread_cap_env()
    assert env["OMP_NUM_THREADS"] == "1"
    assert env["MKL_NUM_THREADS"] == "1"
    assert env["OPENBLAS_NUM_THREADS"] == "1"
    assert env["NUMEXPR_NUM_THREADS"] == "1"
    assert env["TOKENIZERS_PARALLELISM"] == "false"
    assert env["RTFM_EMBED_THREADS"] == "1"


def test_thread_cap_env_respects_override(monkeypatch):
    monkeypatch.setenv("RTFM_EMBED_THREADS", "4")
    env = throttle.thread_cap_env()
    assert env["OMP_NUM_THREADS"] == "4"


def test_thread_cap_env_zero_disables(monkeypatch):
    monkeypatch.setenv("RTFM_EMBED_THREADS", "0")
    assert throttle.thread_cap_env() == {}


def test_apply_thread_caps_uses_setdefault(monkeypatch):
    """User-set OMP_NUM_THREADS wins over the cap default."""
    monkeypatch.delenv("RTFM_EMBED_THREADS", raising=False)
    monkeypatch.setenv("OMP_NUM_THREADS", "8")
    throttle.apply_thread_caps()
    assert os.environ["OMP_NUM_THREADS"] == "8"  # not clobbered
    # But the ones we didn't pre-set get the default.
    assert os.environ["MKL_NUM_THREADS"] == "1"


# ── Global semaphore ────────────────────────────────────────────────────


def test_semaphore_disabled_when_max_is_zero(monkeypatch, tmp_path):
    monkeypatch.setenv("RTFM_MAX_CONCURRENT_INDEXERS", "0")
    monkeypatch.setattr(throttle, "_SLOT_DIR", tmp_path / "slots")
    with throttle.acquire_slot() as got:
        assert got is True
    # No slot dir created — semaphore was a no-op.
    assert not (tmp_path / "slots").exists()


def test_semaphore_acquires_and_releases(monkeypatch, tmp_path):
    monkeypatch.setenv("RTFM_MAX_CONCURRENT_INDEXERS", "2")
    monkeypatch.setattr(throttle, "_SLOT_DIR", tmp_path / "slots")

    with throttle.acquire_slot() as got:
        assert got is True
        # Slot file exists and has our pid in it.
        slot_files = sorted((tmp_path / "slots").glob("slot-*.lock"))
        assert len(slot_files) == 1
        content = slot_files[0].read_text().strip()
        assert content == str(os.getpid())

    # After release the slot is unlocked; another acquire in the same
    # process succeeds instantly.
    t0 = time.monotonic()
    with throttle.acquire_slot() as got:
        assert got is True
    assert time.monotonic() - t0 < 0.5  # no polling — got a slot immediately


def _child_hold_slot(slot_dir: str, hold_seconds: float, ready_evt, done_evt):
    """Helper: acquire a slot in a subprocess and hold it briefly."""
    import os as _os
    from rtfm.core import throttle as _t
    _os.environ["RTFM_MAX_CONCURRENT_INDEXERS"] = "1"
    _t._SLOT_DIR = Path(slot_dir)
    with _t.acquire_slot() as got:
        assert got
        ready_evt.set()
        time.sleep(hold_seconds)
    done_evt.set()


def test_semaphore_blocks_when_full(monkeypatch, tmp_path):
    """With max=1, a second acquirer must wait for the first to release."""
    slot_dir = tmp_path / "slots"
    monkeypatch.setenv("RTFM_MAX_CONCURRENT_INDEXERS", "1")
    monkeypatch.setattr(throttle, "_SLOT_DIR", slot_dir)

    ctx = mp.get_context("fork")  # inherit monkeypatched env
    ready = ctx.Event()
    done = ctx.Event()
    p = ctx.Process(
        target=_child_hold_slot,
        args=(str(slot_dir), 0.8, ready, done),
    )
    p.start()
    try:
        assert ready.wait(timeout=5.0), "child never acquired its slot"
        # Now try to acquire from the parent — should block until child releases.
        t0 = time.monotonic()
        with throttle.acquire_slot(poll_seconds=0.05) as got:
            elapsed = time.monotonic() - t0
            assert got is True
            # Waited at least most of the child's hold time.
            assert elapsed > 0.5, f"acquired too fast: {elapsed:.2f}s"
        assert done.is_set()
    finally:
        p.join(timeout=2.0)
        if p.is_alive():
            p.terminate()


def test_semaphore_stops_on_should_stop(monkeypatch, tmp_path):
    """``should_stop`` returning True while waiting causes the manager
    to yield ``False`` promptly instead of blocking forever."""
    slot_dir = tmp_path / "slots"
    monkeypatch.setenv("RTFM_MAX_CONCURRENT_INDEXERS", "1")
    monkeypatch.setattr(throttle, "_SLOT_DIR", slot_dir)

    ctx = mp.get_context("fork")
    ready = ctx.Event()
    done = ctx.Event()
    p = ctx.Process(
        target=_child_hold_slot,
        args=(str(slot_dir), 3.0, ready, done),  # long hold
    )
    p.start()
    try:
        assert ready.wait(timeout=5.0)
        # Parent tries to acquire but signals stop after 0.3s.
        stop_at = time.monotonic() + 0.3

        def _should_stop():
            return time.monotonic() >= stop_at

        t0 = time.monotonic()
        with throttle.acquire_slot(
            should_stop=_should_stop, poll_seconds=0.05
        ) as got:
            elapsed = time.monotonic() - t0
            assert got is False, "expected to bail out on stop"
            assert elapsed < 1.0, f"stop honored too slowly: {elapsed:.2f}s"
    finally:
        p.terminate()
        p.join(timeout=2.0)


def test_heavy_job_types_are_the_expected_ones():
    """A regression guard — if someone adds a new job type they must
    consciously decide whether it belongs in the pool."""
    assert throttle.HEAVY_JOB_TYPES == frozenset({"ingest", "embed", "ocr"})
