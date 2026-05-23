"""Single-process worker daemon: drains the priority queue.

Architecture:
  - One worker per project (one ``library.db``), enforced by an
    exclusive ``flock`` on ``.rtfm/worker.lock``.
  - At each tick, dequeue the highest-priority pending job (P1 ingest
    → P2 embed → P3 OCR) and dispatch to the appropriate handler.
  - Between jobs, re-check the queue immediately — no sleep needed
    when there is work to do, so a fresh P1 enqueued by a hook is
    picked up before P2/P3 carryovers (cooperative preemption).
  - Idle: poll every ``IDLE_POLL_SECONDS`` until new work appears.
  - Status: written atomically to ``.rtfm/worker_state.json`` so
    ``rtfm status`` / ``/rtfm.status`` can show what's happening
    without touching the DB.

The worker process is **single-threaded** and respects ``nice``/
``ionice`` inherited from the launcher (see :func:`spawn_worker`).
Each handler does its own subprocess if it needs hard memory
isolation (OCR via marker — see :mod:`rtfm.parsers.pdf`).
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import socket
import time
import traceback
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Optional

from rtfm.core.queue import Queue, Job


# How long to sleep when the queue is empty before polling again.
# Short enough to feel responsive; long enough that an idle worker
# costs nothing.
IDLE_POLL_SECONDS = 5.0

# How often, while idle, to also re-scan the filesystem for new or
# moved files (cf. the old watcher.py poller — now folded in). 30 s
# matches the user-visible expectation: a file you save lands in the
# queue within ~30 s, automatically.
SCAN_INTERVAL_SECONDS = 30.0

# How often, while idle, to reconcile the DB (purge orphan embeddings,
# re-queue un-embedded chunks). Far less urgent than the file scan, and
# only ever runs at rest, so a long interval is fine.
RECONCILE_INTERVAL_SECONDS = 3600.0

# Status snapshot lives next to the DB so ``rtfm status`` can find it
# without re-reading config.
STATE_FILENAME = "worker_state.json"
LOCK_FILENAME = "worker.lock"


@dataclass
class WorkerState:
    """On-disk worker status. Mirrors what ``rtfm status`` will show."""
    pid: int
    host: str
    status: str  # 'idle' | 'busy' | 'stopping'
    current_job_id: Optional[int]
    current_job_type: Optional[str]
    current_job_payload: Optional[dict]
    started_at: str
    last_update: str
    jobs_done: int
    jobs_failed: int


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


def _state_path(rtfm_dir: Path) -> Path:
    return rtfm_dir / STATE_FILENAME


def _lock_path(rtfm_dir: Path) -> Path:
    return rtfm_dir / LOCK_FILENAME


def write_state(rtfm_dir: Path, state: WorkerState) -> None:
    """Atomic-replace the state file via temp + rename."""
    path = _state_path(rtfm_dir)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_state(rtfm_dir: Path) -> Optional[WorkerState]:
    path = _state_path(rtfm_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return WorkerState(**data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def clear_state(rtfm_dir: Path) -> None:
    path = _state_path(rtfm_dir)
    path.unlink(missing_ok=True)


def pid_alive(pid: int) -> bool:
    """Cheap liveness check via ``kill(pid, 0)``."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but belongs to someone else — counts as alive.
        return True
    except OSError:
        return False


def worker_running(rtfm_dir: Path) -> Optional[WorkerState]:
    """Return the live worker state if one is running, else ``None``.

    A stale state file (PID dead) is treated as no worker — caller is
    expected to clean it up before spawning a new one.
    """
    state = read_state(rtfm_dir)
    if state is None:
        return None
    if state.status == "stopping":
        return None
    if not pid_alive(state.pid):
        return None
    return state


class Worker:
    """The actual loop. Construct, ``run()``.

    Single consumer process: drains the priority queue *and* periodically
    re-scans configured sources to enqueue P1 ingest jobs (the old
    standalone watcher's job, folded in here per the 0.10.4 redesign).
    Scanning only happens while the queue is empty — a long ingest /
    OCR run is never interrupted to scan.
    """

    def __init__(self, rtfm_dir: Path, db_path: Path,
                 handlers: dict[str, Callable[[Job, "Worker"], None]],
                 scan_interval: float = SCAN_INTERVAL_SECONDS,
                 reconcile_interval: float = RECONCILE_INTERVAL_SECONDS,
                 log: Optional[Callable[[str], None]] = None):
        self.rtfm_dir = rtfm_dir
        self.db_path = db_path
        self.handlers = handlers
        self.scan_interval = scan_interval
        self.reconcile_interval = reconcile_interval
        self._stop = False
        self._jobs_done = 0
        self._jobs_failed = 0
        self._last_scan_at = 0.0  # monotonic, 0 = scan ASAP on first idle
        # Don't reconcile immediately on startup — let the first scan +
        # any backlog drain first. Seed with "now" so the first
        # reconcile happens one interval in.
        self._last_reconcile_at = 0.0
        self._reconcile_seeded = False
        self._log = log or (lambda msg: None)
        self._queue = Queue(db_path)
        self._started_at = _now_iso()
        # Capture the on-disk package version at startup. When a new
        # version lands (pipx install, pip install --force, etc.) the
        # idle tick will see the version on disk diverge from this and
        # exit cleanly — the next hook/CLI call respawns a fresh worker
        # with the new code. Without this, a long-running worker keeps
        # executing the code it loaded into memory at startup and silently
        # ignores every subsequent install (bit the project once already).
        self._our_version = _read_installed_version()

    # ── Public entry point ──────────────────────────────────────────────

    def run(self) -> None:
        """Main loop. Blocks until SIGTERM/SIGINT or no-work-forever."""
        self._install_signal_handlers()
        self._snapshot("idle", None)
        self._log(f"worker started pid={os.getpid()} "
                  f"scan_interval={self.scan_interval}s")
        try:
            while not self._stop:
                # Exit cleanly if a new version of the package landed on
                # disk while we were running — the next hook will respawn
                # us with the up-to-date code.
                if self._version_changed():
                    self._log(
                        f"version changed on disk "
                        f"({self._our_version} → {_read_installed_version()}), "
                        f"exiting for restart"
                    )
                    break
                job = self._queue.dequeue()
                if job is None:
                    # Idle: fold-in the watcher tick + DB reconciliation.
                    # Both run only at rest, so they never fight an
                    # in-flight ingest/move.
                    self._maybe_scan()
                    self._maybe_reconcile()
                    self._snapshot("idle", None)
                    self._sleep(IDLE_POLL_SECONDS)
                    continue
                self._handle(job)
        finally:
            self._log(f"worker stopping pid={os.getpid()} done={self._jobs_done} failed={self._jobs_failed}")
            self._snapshot("stopping", None)
            self._queue.close()
            clear_state(self.rtfm_dir)

    # ── Internals ───────────────────────────────────────────────────────

    def _maybe_scan(self) -> None:
        """Enqueue one P1 ``scan`` job per configured source if the throttle
        interval has elapsed since the last tick. No-op otherwise.

        The scan itself is now done by :func:`rtfm.core.handlers.handle_scan`
        (one job per source), so the worker loop stays uniform: every unit
        of work goes through the queue and is dispatched via ``HANDLERS``.
        Duplicate ``scan`` jobs are silently dropped by the queue's pending
        dedup index (``UNIQUE(type, payload) WHERE status='pending'``),
        so spamming this tick is safe.
        """
        import time as _t
        now = _t.monotonic()
        if now - self._last_scan_at < self.scan_interval:
            return
        self._last_scan_at = now

        try:
            from rtfm.config import load_config
            try:
                cfg = load_config(self.rtfm_dir.parent)
            except Exception:
                cfg = {}
            sources = cfg.get("sources") or [
                {"path": str(self.rtfm_dir.parent),
                 "corpus": cfg.get("corpus", "default")}
            ]

            enqueued = 0
            for src in sources:
                src_path = Path(src.get("path", ".")).resolve()
                src_corpus = src.get("corpus", cfg.get("corpus", "default"))
                payload = {
                    "root": str(src_path),
                    "corpus": src_corpus,
                    "extensions": src.get("extensions") or None,
                }
                job_id = self._queue.enqueue("scan", payload)
                if job_id is not None:
                    enqueued += 1
            if enqueued:
                self._log(f"enqueued {enqueued} P1 scan(s)")
        except Exception as exc:
            # A scan-enqueue failure must never bring the worker down —
            # the priority drain is more important.
            self._log(f"scan enqueue error: {exc}")

    def _maybe_reconcile(self) -> None:
        """Enqueue one P4 ``reconcile`` job if enough idle time has elapsed.
        No-op otherwise.

        The reconciliation itself is now handled by
        :func:`rtfm.core.handlers.handle_reconcile`. As with ``scan``, the
        queue dedup index makes repeated calls a no-op while a previous
        reconcile job is still pending.
        """
        import time as _t
        now = _t.monotonic()
        if not self._reconcile_seeded:
            # First idle: don't reconcile yet, just start the clock.
            self._last_reconcile_at = now
            self._reconcile_seeded = True
            return
        if now - self._last_reconcile_at < self.reconcile_interval:
            return
        self._last_reconcile_at = now
        try:
            self._queue.enqueue("reconcile", {})
        except Exception as exc:
            self._log(f"reconcile enqueue error: {exc}")

    def _handle(self, job: Job) -> None:
        self._snapshot("busy", job)
        handler = self.handlers.get(job.type)
        if handler is None:
            err = f"no handler for type={job.type!r}"
            self._queue.mark_failed(job.id, err)
            self._jobs_failed += 1
            self._log(f"job#{job.id} {job.type}: {err}")
            return
        try:
            handler(job, self)
            self._queue.mark_done(job.id)
            self._jobs_done += 1
        except Exception as e:
            tb = traceback.format_exc(limit=20)
            self._queue.mark_failed(job.id, f"{type(e).__name__}: {e}\n{tb}")
            self._jobs_failed += 1
            self._log(f"job#{job.id} {job.type} FAILED: {e}")

    def _snapshot(self, status: str, job: Optional[Job]) -> None:
        write_state(self.rtfm_dir, WorkerState(
            pid=os.getpid(),
            host=socket.gethostname(),
            status=status,
            current_job_id=job.id if job else None,
            current_job_type=job.type if job else None,
            current_job_payload=job.payload if job else None,
            started_at=self._started_at,
            last_update=_now_iso(),
            jobs_done=self._jobs_done,
            jobs_failed=self._jobs_failed,
        ))

    def _sleep(self, seconds: float) -> None:
        """Sleep, but exit early if a stop signal arrives."""
        end = time.monotonic() + seconds
        while not self._stop and time.monotonic() < end:
            time.sleep(min(0.5, end - time.monotonic()))

    def _version_changed(self) -> bool:
        """True iff the on-disk ``rtfm-ai`` version differs from the one
        we captured at startup. A long-running worker keeps the code it
        imported into memory at startup; without this check it would
        silently ignore every subsequent ``pipx install`` until killed.
        Returns ``False`` when either side is ``unknown`` (running from
        a source checkout — no metadata to compare)."""
        current = _read_installed_version()
        if current == "unknown" or self._our_version == "unknown":
            return False
        return current != self._our_version

    def _install_signal_handlers(self) -> None:
        def _handler(signum, _frame):
            self._stop = True
        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)


# ── Lock primitives ─────────────────────────────────────────────────────

class WorkerLockHeld(RuntimeError):
    """Raised when another worker already holds the lock."""


class WorkerLock:
    """Exclusive flock on ``.rtfm/worker.lock``. Use as a context manager."""

    def __init__(self, rtfm_dir: Path):
        self.path = _lock_path(rtfm_dir)
        self._fd: Optional[int] = None

    def __enter__(self) -> "WorkerLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self._fd)
            self._fd = None
            raise WorkerLockHeld(f"another worker holds {self.path}")
        # Write our PID into the lockfile so external readers can see it.
        os.ftruncate(self._fd, 0)
        os.write(self._fd, f"{os.getpid()}\n".encode())
        return self

    def __exit__(self, *args) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None
