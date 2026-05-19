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
import sys
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
                 log: Optional[Callable[[str], None]] = None):
        self.rtfm_dir = rtfm_dir
        self.db_path = db_path
        self.handlers = handlers
        self.scan_interval = scan_interval
        self._stop = False
        self._jobs_done = 0
        self._jobs_failed = 0
        self._last_scan_at = 0.0  # monotonic, 0 = scan ASAP on first idle
        self._log = log or (lambda msg: None)
        self._queue = Queue(db_path)
        self._started_at = _now_iso()

    # ── Public entry point ──────────────────────────────────────────────

    def run(self) -> None:
        """Main loop. Blocks until SIGTERM/SIGINT or no-work-forever."""
        self._install_signal_handlers()
        self._snapshot("idle", None)
        self._log(f"worker started pid={os.getpid()} "
                  f"scan_interval={self.scan_interval}s")
        try:
            while not self._stop:
                job = self._queue.dequeue()
                if job is None:
                    # Idle: opportunity to fold-in the watcher tick.
                    self._maybe_scan()
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
        """Run a full-corpus scan if enough idle time has elapsed since
        the last one. No-op otherwise.

        Uses :func:`rtfm.core.sync.compute_diff` (MD5) so it can detect
        cross-corpus moves and skip mtime false-positives that bit
        the legacy ``quick_diff`` poller. Cross-corpus moves are
        applied inline via :meth:`Library.move_file` (preserving
        chunks + embeddings + tags). The rest goes to the queue.
        """
        import time as _t
        now = _t.monotonic()
        if now - self._last_scan_at < self.scan_interval:
            return
        self._last_scan_at = now

        try:
            self._scan_once()
        except Exception as exc:
            # A scan failure must never bring the worker down — the
            # priority drain is more important.
            self._log(f"scan error: {exc}")

    def _scan_once(self) -> int:
        """One pass over every configured source. Returns the count of
        files enqueued (P1 ingest). Cross-corpus moves are applied
        inline, not counted here.
        """
        from rtfm.config import load_config
        from rtfm.core.library import Library
        from rtfm.core.sync import compute_diff, scan_directory, _path_to_slug

        try:
            cfg = load_config(self.rtfm_dir.parent)
        except Exception:
            cfg = {}
        sources = cfg.get("sources") or [
            {"path": str(self.rtfm_dir.parent),
             "corpus": cfg.get("corpus", "default")}
        ]

        enqueued = 0
        moved = 0
        lib = Library(str(self.db_path))
        try:
            indexed_global = lib.list_indexed_files()
            for src in sources:
                if self._stop:
                    break
                src_path = Path(src.get("path", ".")).resolve()
                if not src_path.is_dir():
                    continue
                src_corpus = src.get("corpus", cfg.get("corpus", "default"))
                ext_set = None
                if src.get("extensions"):
                    ext_set = {
                        e.strip() if e.strip().startswith(".") else f".{e.strip()}"
                        for e in src["extensions"].split(",")
                    }
                try:
                    files_on_disk = scan_directory(src_path, ext_set)
                    indexed = lib.list_indexed_files(corpus=src_corpus)
                    lib.set_sync_root(src_corpus, str(src_path))
                    diff = compute_diff(
                        files_on_disk, indexed, src_path,
                        indexed_global=indexed_global,
                        current_corpus=src_corpus,
                    )
                except Exception as exc:
                    self._log(f"scan error [{src_corpus}] {src_path}: {exc}")
                    continue

                # Cross-corpus move: in place, no re-ingest.
                for old_rel, _old_corpus, new_path in diff.cross_moved:
                    try:
                        new_rel = str(new_path.relative_to(src_path))
                    except ValueError:
                        new_rel = str(new_path)
                    try:
                        new_slug = _path_to_slug(new_rel, src_corpus)
                        if lib.move_file(old_rel, new_rel, new_slug,
                                         new_corpus=src_corpus):
                            moved += 1
                    except Exception as exc:
                        self._log(f"cross-move error {old_rel}: {exc}")

                # Genuinely new/modified files → P1.
                payloads = []
                for fpath in diff.added + diff.modified:
                    try:
                        rel = str(fpath.relative_to(src_path))
                    except ValueError:
                        rel = str(fpath)
                    payloads.append({
                        "root": str(src_path),
                        "corpus": src_corpus,
                        "filepath": rel,
                    })
                if payloads:
                    inserted, _ = self._queue.enqueue_many("ingest", payloads)
                    enqueued += inserted
        finally:
            lib.close()

        if enqueued or moved:
            self._log(f"scan: +{enqueued} queued, {moved} cross-corpus moved")
        return enqueued

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
