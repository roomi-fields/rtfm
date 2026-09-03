"""Shared worker primitives: job context, tunables, memory/version guards.

The actual drain loop now lives in :mod:`rtfm.core.supervisor` — one
mutualised process for the whole fleet instead of a daemon per project.
This module keeps the pieces both the supervisor and the job handlers still
need:

  - :class:`JobContext` — the minimal ``{db_path, log}`` surface handed to
    each handler.
  - The interval / memory-ceiling constants and the RSS / package-version
    probes the supervisor uses to decide when to recycle.
  - The liveness probe the spawn path uses lives in
    :mod:`rtfm.core.portable`: ``kill(pid, 0)`` probes on Unix and
    terminates on Windows, so it is not the same call everywhere.

The per-project ``worker_state.json`` model that used to live here is gone.
It described one worker owning one job at a time; the supervisor runs a dozen
per project and never wrote the file, so its last reader — the queue's
zombie-reaper — could only ever conclude "no job is live" and reap the lot.
The reaper now takes the live job ids from whoever calls it.
"""
from __future__ import annotations

import os
import time
from typing import Callable, Optional

# How long to sleep when the queue is empty before polling again.
# Short enough to feel responsive; long enough that an idle worker
# costs nothing.
IDLE_POLL_SECONDS = 5.0

# How often, while idle, to also re-scan the filesystem for new or moved
# files (cf. the old watcher.py poller — now folded in). One mutualised
# supervisor serves dozens of projects, each with several sources; a 30 s
# per-source cadence flooded the queue with re-scans that churned the CPU
# and (pre-0.26.5) starved real work, which is why this sat at 300 s.
#
# Since 0.28.0 a scan no longer re-hashes untouched files (size+mtime
# short-circuit, see ``freshness.probably_unchanged``), so a pass is
# stat-bound instead of read-bound — cheap enough to run every minute, and
# still cheaper overall than the old five-minute full re-read. This is the
# discovery latency for everything the edit hook cannot see: files written
# by a shell command, a build step, a git checkout or another agent.
SCAN_INTERVAL_SECONDS = 60.0

# How often, while idle, to reconcile the DB (purge orphan embeddings,
# re-queue un-embedded chunks). Far less urgent than the file scan, and
# only ever runs at rest, so a long interval is fine.
RECONCILE_INTERVAL_SECONDS = 3600.0

# Memory safety. A runaway allocation in a handler (a malformed PDF
# that breaks pdfium, an embedder batch that explodes, a CSV row with
# a 1 GB cell) once consumed ~13 GB of RSS and triggered the global
# OOM-killer, which terminated the worker (and anything else fighting
# for memory) without a graceful exit. Two layers of defence:
#
# 1. ``RLIMIT_AS`` (virtual-address-space cap) so the next allocation
#    above the limit raises ``MemoryError`` — catchable by the per-job
#    handler, which then marks the job ``failed`` and moves on. This
#    converts a kernel SIGKILL into a normal Python exception.
# 2. RSS polling at every idle tick: above ``WORKER_RSS_EXIT_MB`` the
#    worker exits cleanly. Catches slow leaks that wouldn't trip a
#    single-shot allocation guard.
#
# Opt out via ``RTFM_WORKER_MEMORY_LIMIT_GB=0`` (or any non-positive
# value) when using marker-pdf, whose ML models legitimately need 3-8
# GB of RSS.
WORKER_MEMORY_LIMIT_GB = 8.0
WORKER_RSS_EXIT_MB = 5 * 1024

# Status snapshot lives next to the DB so ``rtfm status`` can find it
# without re-reading config.


class JobContext:
    """The minimal surface a job handler needs from its runner.

    Handlers only ever touch ``.db_path`` (to open their own
    :class:`~rtfm.core.library.Library` / :class:`~rtfm.core.queue.Queue`)
    and ``._log``. The mutualised :class:`~rtfm.core.supervisor.Supervisor`
    hands one of these to every ``HANDLERS[...]`` call instead of a whole
    per-project worker object — keeping handlers decoupled from the worker
    lifecycle.
    """

    __slots__ = ("db_path", "_log")

    def __init__(self, db_path: str, log: Callable[[str], None]):
        self.db_path = db_path
        self._log = log


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_installed_version() -> str:
    """Return the on-disk version of the ``rtfm-ai`` distribution.

    Each call re-reads the dist-info metadata, so it picks up a version
    bump done while the process is running (``pipx install --force``,
    ``pip install --force-reinstall``, …). Returns ``"unknown"`` if the
    distribution isn't installed (running from a source checkout).
    """
    try:
        import importlib.metadata as _m
        return _m.version("rtfm-ai")
    except Exception:
        return "unknown"


def _resolve_memory_limit_gb() -> float:
    """Effective virtual-memory cap in GB for this worker.

    Reads the ``RTFM_WORKER_MEMORY_LIMIT_GB`` environment variable so the
    cap can be raised (or disabled with ``0``) per project — useful for
    marker-pdf, whose ML models can need 3-8 GB. Defaults to
    :data:`WORKER_MEMORY_LIMIT_GB`. Returns ``0`` to mean "no cap".
    """
    import os
    raw = os.environ.get("RTFM_WORKER_MEMORY_LIMIT_GB")
    if raw is None or raw.strip() == "":
        return WORKER_MEMORY_LIMIT_GB
    try:
        v = float(raw)
    except ValueError:
        return WORKER_MEMORY_LIMIT_GB
    return v if v > 0 else 0.0


def _install_memory_limit(limit_gb: float) -> Optional[int]:
    """Set ``RLIMIT_AS`` so a runaway allocation raises ``MemoryError``
    instead of triggering the kernel OOM-killer. Returns the cap in
    bytes that was actually applied, or ``None`` when no cap was set.

    No-ops on platforms without ``resource.RLIMIT_AS`` (Windows), when
    ``limit_gb <= 0`` (explicit opt-out), or when the existing hard
    limit is already stricter than what we'd ask for.
    """
    if limit_gb <= 0:
        return None
    try:
        import resource
    except ImportError:
        return None
    cap = int(limit_gb * 1024 ** 3)
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    except (ValueError, OSError):
        return None
    new_hard = hard
    if hard != resource.RLIM_INFINITY and hard < cap:
        cap = hard  # never try to raise a hard limit, only tighten
    else:
        new_hard = cap
    try:
        resource.setrlimit(resource.RLIMIT_AS, (cap, new_hard))
    except (ValueError, OSError):
        return None
    return cap


def _read_mem_total_mb() -> float:
    """Total physical RAM in MB from ``/proc/meminfo`` (0 when unavailable).

    Used to bound the supervisor's RSS recycle ceiling: with the pool sized
    to the core count the naive ``per-lane × lanes`` ceiling can exceed
    physical RAM, so it is clamped to a fraction of this value."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def _read_rss_mb() -> float:
    """Current process RSS in MB by reading ``/proc/self/status``.

    Returns ``0`` when the file is unavailable (non-Linux). RSS rather
    than VSZ because RSS reflects resident pages (what actually counts
    against the system's available memory)."""
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


