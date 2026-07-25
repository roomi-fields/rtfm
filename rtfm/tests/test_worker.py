"""Tests for the surviving worker-module helpers.

The per-project ``Worker`` loop was retired at 0.25 in favour of the
mutualised :mod:`rtfm.core.supervisor` (see ``test_supervisor.py``). What
stays in :mod:`rtfm.core.worker` is a set of shared primitives — here we
cover the memory-limit resolver the supervisor relies on.
"""
from __future__ import annotations


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
