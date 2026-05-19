"""CLI commands for the priority-queue worker (0.10.0+).

Three user-facing subcommands:
  - ``rtfm worker``      → start, stop, or report worker status
  - ``rtfm queue``       → inspect/manage the work queue
  - ``rtfm worker-daemon`` (hidden) → the actual long-running loop,
                                       invoked by ``ensure_worker_running``
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from rtfm.config import find_rtfm_root
from rtfm.core.queue import Queue
from rtfm.core.worker import (
    Worker, WorkerLock, WorkerLockHeld,
    pid_alive, read_state, worker_running, clear_state,
)


# ── Logging helper (matches hook / ocr-worker log format) ────────────────

def _log(rtfm_dir: Path, msg: str) -> None:
    try:
        ts = time.strftime("%H:%M:%S")
        with open(rtfm_dir / "rtfm.log", "a", encoding="utf-8") as f:
            f.write(f"[{ts}]     worker | {msg}\n")
    except Exception:
        pass


# ── Spawn helper (called by producers: rtfm sync, hooks, MCP) ────────────

def ensure_worker_running(rtfm_dir: Path) -> int | None:
    """Spawn a worker daemon if none is alive. Returns the PID, or
    ``None`` when spawning is impossible (e.g. another worker won the
    lock race a moment earlier). Idempotent."""
    if worker_running(rtfm_dir):
        return worker_running(rtfm_dir).pid  # type: ignore[union-attr]

    # Stale state file from a crashed worker — drop it.
    state = read_state(rtfm_dir)
    if state and not pid_alive(state.pid):
        clear_state(rtfm_dir)

    # Fork a detached worker. ``ionice -c 3 nice -n 19`` keeps it
    # off the user's hot path; if those binaries aren't around, fall
    # back to a bare python.
    cmd = [sys.executable, "-m", "rtfm.cli", "worker-daemon"]
    wrappers = []
    for binname, flags in (("ionice", ["-c", "3"]), ("nice", ["-n", "19"])):
        if _which(binname):
            wrappers += [binname, *flags]
    proc = subprocess.Popen(
        wrappers + cmd,
        cwd=str(rtfm_dir.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # immune to parent SIGHUP / hook timeout
    )
    return proc.pid


def _which(binname: str) -> str | None:
    from shutil import which
    return which(binname)


# ── ``rtfm worker-daemon`` (hidden) ─────────────────────────────────────

def cmd_worker_daemon(args):
    """Long-running queue drain. Hidden from --help.

    Holds an exclusive flock on ``.rtfm/worker.lock`` so a second
    invocation exits immediately rather than racing.
    """
    rtfm_root = find_rtfm_root()
    if rtfm_root is None:
        sys.exit("worker-daemon: no .rtfm/ project root in the cwd chain.")
    rtfm_dir = rtfm_root / ".rtfm"
    db_path = rtfm_dir / "library.db"

    try:
        with WorkerLock(rtfm_dir):
            from rtfm.core.handlers import HANDLERS
            _log(rtfm_dir, f"worker-daemon starting pid={os.getpid()}")
            worker = Worker(
                rtfm_dir=rtfm_dir, db_path=db_path,
                handlers=HANDLERS,
                log=lambda m: _log(rtfm_dir, m),
            )
            worker.run()
    except WorkerLockHeld:
        # Another worker is already draining the queue — that's fine,
        # we just exit silently. The caller (``ensure_worker_running``)
        # has already confirmed the live worker.
        return


# ── ``rtfm worker [start|stop|status]`` ─────────────────────────────────

def cmd_worker(args):
    rtfm_root = find_rtfm_root()
    if rtfm_root is None:
        sys.exit("worker: no .rtfm/ project root in the cwd chain.")
    rtfm_dir = rtfm_root / ".rtfm"

    action = getattr(args, "action", "status") or "status"

    if action == "status":
        state = worker_running(rtfm_dir)
        if not state:
            print("worker: not running.")
            stale = read_state(rtfm_dir)
            if stale and not pid_alive(stale.pid):
                print(f"  (stale state file from dead PID {stale.pid} — will be cleaned on next spawn)")
            return
        print(f"worker: running (PID {state.pid}, host {state.host})")
        print(f"  status:   {state.status}")
        if state.current_job_id is not None:
            payload_preview = ""
            if state.current_job_payload:
                fp = state.current_job_payload.get("filepath")
                if fp:
                    payload_preview = f"  file: {fp}"
            print(f"  current:  #{state.current_job_id} [{state.current_job_type}]{payload_preview}")
        print(f"  started:  {state.started_at}")
        print(f"  jobs:     {state.jobs_done} done, {state.jobs_failed} failed")
        return

    if action == "start":
        pid = ensure_worker_running(rtfm_dir)
        if pid is None:
            print("worker: could not start (another worker won the race).")
            return
        # Give it a moment to write its state file before we report.
        for _ in range(20):
            time.sleep(0.1)
            if worker_running(rtfm_dir):
                break
        state = worker_running(rtfm_dir)
        if state:
            print(f"worker: started (PID {state.pid}).")
        else:
            print(f"worker: spawned (PID {pid}) — waiting on state file...")
        return

    if action == "stop":
        state = worker_running(rtfm_dir)
        if not state:
            print("worker: not running.")
            return
        try:
            import signal
            os.kill(state.pid, signal.SIGTERM)
        except ProcessLookupError:
            print("worker: process already gone.")
            clear_state(rtfm_dir)
            return
        # Wait briefly for graceful shutdown.
        for _ in range(50):
            time.sleep(0.1)
            if not pid_alive(state.pid):
                break
        if pid_alive(state.pid):
            print(f"worker: SIGTERM sent to PID {state.pid} — still running, will exit after current job.")
        else:
            print(f"worker: stopped (PID {state.pid}).")
            clear_state(rtfm_dir)
        return

    sys.exit(f"worker: unknown action {action!r}. Use start | stop | status.")


# ── ``rtfm queue [stats|list|clear-done|retry-failed]`` ─────────────────

def cmd_queue(args):
    rtfm_root = find_rtfm_root()
    if rtfm_root is None:
        sys.exit("queue: no .rtfm/ project root in the cwd chain.")
    db_path = rtfm_root / ".rtfm" / "library.db"
    queue = Queue(db_path)

    action = getattr(args, "action", "stats") or "stats"
    try:
        if action == "stats":
            stats = queue.stats()
            if not stats:
                print("queue: empty.")
                return
            for jtype in sorted(stats):
                breakdown = stats[jtype]
                parts = [f"{status}={count}" for status, count in sorted(breakdown.items())]
                print(f"  {jtype:<8} {' '.join(parts)}")
            return

        if action == "list":
            jobs = queue.list_pending(limit=getattr(args, "limit", 20) or 20)
            if not jobs:
                print("queue: no pending jobs.")
                return
            for j in jobs:
                fp = j.payload.get("filepath") or j.payload.get("file_path") or ""
                print(f"  #{j.id:<6} P{j.priority} {j.type:<8} {fp}")
            return

        if action == "failed":
            jobs = queue.list_failed(limit=getattr(args, "limit", 20) or 20)
            if not jobs:
                print("queue: no failed jobs.")
                return
            for j in jobs:
                fp = j.payload.get("filepath") or ""
                err = (j.error or "").splitlines()[0][:80]
                print(f"  #{j.id:<6} {j.type:<8} {fp}")
                print(f"          ! {err}")
            return

        if action == "clear-done":
            keep = getattr(args, "keep", 100) or 100
            n = queue.clear_done(keep_last=keep)
            print(f"queue: removed {n} done row(s), kept last {keep}.")
            return

        if action == "retry-failed":
            n = queue.retry_failed()
            print(f"queue: moved {n} failed row(s) back to pending.")
            return

        sys.exit(f"queue: unknown action {action!r}.")
    finally:
        queue.close()
