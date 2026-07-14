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

import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional


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
_DEFAULT_MAX_CONCURRENT = 4
_ACQUIRE_POLL_SECONDS = 0.5


def _max_concurrent() -> int:
    """Read ``RTFM_MAX_CONCURRENT_INDEXERS`` (default 4). ``0`` = disabled."""
    raw = os.environ.get("RTFM_MAX_CONCURRENT_INDEXERS")
    if raw is None or raw.strip() == "":
        return _DEFAULT_MAX_CONCURRENT
    try:
        n = int(raw)
    except ValueError:
        return _DEFAULT_MAX_CONCURRENT
    return max(0, n)


def _try_acquire_one(n: int) -> Optional[int]:
    """Try each of the ``n`` slot files in order; return an open fd on the
    first one we could ``flock`` non-blockingly, else ``None``."""
    _SLOT_DIR.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        path = _SLOT_DIR / f"slot-{i}.lock"
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            continue
        # Stamp the slot with our PID so external readers can tell who
        # holds what. Not load-bearing — just observability.
        try:
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode())
        except OSError:
            pass
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
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


# Job types that spin the CPU hard and should go through the slot pool.
# Scan / remove / reconcile are cheap I/O and stay outside the pool so a
# fresh ingest can always be enqueued regardless of embed pressure.
HEAVY_JOB_TYPES = frozenset({"ingest", "embed", "ocr"})
