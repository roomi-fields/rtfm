"""CPU/parallelism throttling for the worker fleet.

Without a cap, each worker's embedding backend (fastembed → onnxruntime)
opens as many intra-op threads as the box has cores — a single active
worker on a 12-thread CPU eats ~5-6 cores. With 16 project workers
(one per ``.rtfm/`` directory in ``~/.rtfm/workers.json``), a couple of
concurrent embed jobs saturate the machine, load average climbs past
30, and VS Code Remote-SSH decouples (all terminal sessions lost).

Two independent knobs:

1. **Per-worker thread cap** — env vars set at worker launch cap OpenMP,
   MKL, OpenBLAS, NumExpr and HF-tokenizers to one thread each. One
   active worker ⇒ one core. Override with ``RTFM_EMBED_THREADS`` (int).
2. **Global concurrency semaphore** — a file-lock pool in
   ``~/.rtfm/slots/`` bounds how many workers may run a *heavy* job
   (ingest, embed, ocr) at the same time across all projects. Override
   with ``RTFM_MAX_CONCURRENT_INDEXERS`` (int, ``0`` = unlimited).

Both are opt-out (set the env var to ``0`` to disable that layer).
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from rtfm.core.portable import (
    open_lock_file,
    stamp_pid,
    try_lock_exclusive,
    unlock,
)


# ── Thread cap ──────────────────────────────────────────────────────────

_DEFAULT_EMBED_THREADS = "1"


def thread_cap_env(threads: Optional[str] = None) -> dict[str, str]:
    """Return the env-var dict that caps every known BLAS/OpenMP pool.

    ``threads=None`` reads ``RTFM_EMBED_THREADS`` (default ``"1"``).
    ``threads="0"`` returns an empty dict (opt-out — no cap applied).
    """
    n = threads if threads is not None else os.environ.get(
        "RTFM_EMBED_THREADS", _DEFAULT_EMBED_THREADS)
    if n == "0":
        return {}
    return {
        "OMP_NUM_THREADS": n,
        "MKL_NUM_THREADS": n,
        "OPENBLAS_NUM_THREADS": n,
        "NUMEXPR_NUM_THREADS": n,
        # HuggingFace tokenizers logs a nag every worker start if this is
        # unset. Keep it deterministic (no fork-parallelism → no warning).
        "TOKENIZERS_PARALLELISM": "false",
        # Propagate so grandchildren (delayed respawn, marker subproc)
        # inherit the same setting.
        "RTFM_EMBED_THREADS": n,
    }


def apply_thread_caps() -> None:
    """Set the thread-cap env vars on the *current* process' os.environ.

    Idempotent: ``setdefault`` never overrides an already-set variable,
    so a user who set ``OMP_NUM_THREADS=4`` in their shell keeps that.
    Called from the worker daemon before any fastembed/onnxruntime
    import so OpenMP reads our value at init time.
    """
    for k, v in thread_cap_env().items():
        os.environ.setdefault(k, v)


# ── Global concurrency semaphore ────────────────────────────────────────

_SLOT_DIR = Path.home() / ".rtfm" / "slots"
#: Default number of projects the supervisor services concurrently. One core
#: per lane (each job is thread-capped to 1 via :func:`thread_cap_env`), so
#: defaulting to the core count lets background indexing use all otherwise-idle
#: CPU while ``nice 19`` + ``ionice`` keep it out of the way of interactive
#: work. Override per machine via ``~/.rtfm/config.json`` or the env var.
_DEFAULT_MAX_CONCURRENT = os.cpu_count() or 4
_ACQUIRE_POLL_SECONDS = 0.5

#: Machine-local RTFM config, read for a durable concurrency setting that
#: survives worker respawns. ``.bashrc`` does NOT: non-interactive and
#: hook-spawned shells never source it, so an ``export`` there is invisible
#: to a respawned supervisor. A value here is the reliable per-machine knob.
_GLOBAL_CONFIG = Path.home() / ".rtfm" / "config.json"


def _config_max_concurrent() -> Optional[int]:
    """Read ``max_concurrent_indexers`` from ``~/.rtfm/config.json``.

    Returns ``None`` when the file is absent, unreadable, or the key is
    missing — the caller then falls back to the built-in default.
    """
    try:
        import json
        data = json.loads(_GLOBAL_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    v = data.get("max_concurrent_indexers")
    if v is None:
        return None
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return None


def _max_concurrent() -> int:
    """Effective concurrency cap for heavy indexing.

    Precedence: ``RTFM_MAX_CONCURRENT_INDEXERS`` env var (highest — lets a
    one-off override everything) → ``max_concurrent_indexers`` in
    ``~/.rtfm/config.json`` (the durable per-machine knob) → built-in
    default (:data:`_DEFAULT_MAX_CONCURRENT`). ``0`` = unlimited.
    """
    raw = os.environ.get("RTFM_MAX_CONCURRENT_INDEXERS")
    if raw is not None and raw.strip() != "":
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    cfg = _config_max_concurrent()
    if cfg is not None:
        return cfg
    return _DEFAULT_MAX_CONCURRENT


def _try_acquire_one(n: int) -> Optional[int]:
    """Try each of the ``n`` slot files in order; return an open fd on the
    first one we could lock without blocking, else ``None``."""
    _SLOT_DIR.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        path = _SLOT_DIR / f"slot-{i}.lock"
        fd = open_lock_file(path)
        if not try_lock_exclusive(fd):
            os.close(fd)
            continue
        # Stamp the slot with our PID so external readers can tell who
        # holds what. Not load-bearing — just observability.
        stamp_pid(fd)
        return fd
    return None


@contextmanager
def acquire_slot(
    should_stop: Optional[callable] = None,
    poll_seconds: float = _ACQUIRE_POLL_SECONDS,
) -> Iterator[bool]:
    """Block until one of the ``RTFM_MAX_CONCURRENT_INDEXERS`` global
    slots is free. Yields ``True`` on success, ``False`` when the caller
    asked us to stop (via ``should_stop``) before a slot opened.

    ``should_stop`` is polled between attempts so ``SIGTERM`` interrupts
    the wait promptly. If the cap is ``0`` (unlimited), yields ``True``
    immediately without touching the filesystem.
    """
    n = _max_concurrent()
    if n == 0:
        yield True
        return

    fd: Optional[int] = None
    try:
        while True:
            fd = _try_acquire_one(n)
            if fd is not None:
                break
            if should_stop is not None and should_stop():
                yield False
                return
            time.sleep(poll_seconds)
        yield True
    finally:
        if fd is not None:
            try:
                unlock(fd)
            finally:
                os.close(fd)


# Job types that spin the CPU hard and should go through the slot pool.
# Scan / remove / reconcile are cheap I/O and stay outside the pool so a
# fresh ingest can always be enqueued regardless of embed pressure.
HEAVY_JOB_TYPES = frozenset({"ingest", "embed", "ocr"})
