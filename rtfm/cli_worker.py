"""CLI commands for the priority-queue worker (0.10.0+).

Three user-facing subcommands:
  - ``rtfm worker``      → start, stop, restart-all, or report worker status
  - ``rtfm queue``       → inspect/manage the work queue
  - ``rtfm worker-daemon`` (hidden) → the actual long-running loop,
                                       invoked by ``ensure_worker_running``
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from rtfm.config import find_rtfm_root
from rtfm.core.queue import Queue
from rtfm.core.worker import (
    Worker, WorkerLock, WorkerLockHeld,
    SCAN_INTERVAL_SECONDS,
    pid_alive, read_state, worker_running, clear_state,
)


# ── Cross-project worker registry ───────────────────────────────────────
# Tracks every ``.rtfm/`` dir that has ever had a worker spawned, so that
# ``rtfm worker restart-all`` can find them all in one shot (the typical
# post-``pip install`` operation — without a registry we'd have to walk
# the filesystem looking for ``.rtfm/`` dirs).

_REGISTRY = Path.home() / ".rtfm" / "workers.json"


def _load_registry() -> list[str]:
    if not _REGISTRY.exists():
        return []
    try:
        data = json.loads(_REGISTRY.read_text(encoding="utf-8"))
        return list(data.get("projects", []))
    except Exception:
        return []


def _save_registry(projects: list[str]) -> None:
    _REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    # Dedup + sort for stable on-disk diff.
    cleaned = sorted({p for p in projects if p})
    _REGISTRY.write_text(
        json.dumps({"projects": cleaned}, indent=2) + "\n",
        encoding="utf-8",
    )


def _register_project(rtfm_dir: Path) -> None:
    """Add this ``.rtfm/`` dir to the registry. Idempotent, best-effort."""
    try:
        path = str(rtfm_dir.resolve())
        current = _load_registry()
        if path not in current:
            current.append(path)
            _save_registry(current)
    except Exception:
        pass  # registry is best-effort; don't break the spawn


# How often (seconds) the lazy-check CLI hook actually runs. The marker
# file lives at ~/.rtfm/last-version-check so all CLI commands share
# the throttle. We don't want every ``rtfm queue stats`` to scan every
# worker_state.json.
_LAZY_CHECK_INTERVAL_S = 60.0
_LAZY_CHECK_MARKER = Path.home() / ".rtfm" / "last-version-check"


def _maybe_lazy_restart_stale_workers() -> None:
    """Throttled check: if any registered worker is running on a
    different version of ``rtfm-ai`` than the one this CLI just loaded,
    trigger ``restart-all`` once.

    Called from ``cli.main`` at the start of every command. Best-effort:
    any error is swallowed (we never block the user's actual command).
    The throttle marker is updated on every call (success or not) to
    avoid a thundering herd of restart-all calls when many commands
    fire in quick succession (e.g. multiple hooks at once).
    """
    import importlib.metadata as _m
    import time as _t

    # Throttle.
    try:
        last = _LAZY_CHECK_MARKER.stat().st_mtime
        if _t.time() - last < _LAZY_CHECK_INTERVAL_S:
            return
    except OSError:
        pass
    try:
        _LAZY_CHECK_MARKER.parent.mkdir(parents=True, exist_ok=True)
        _LAZY_CHECK_MARKER.touch()
    except OSError:
        pass  # best-effort

    try:
        current_version = _m.version("rtfm-ai")
    except _m.PackageNotFoundError:
        return  # source checkout: nothing to compare against

    stale: list[str] = []
    for path in _load_registry():
        rtfm_dir = Path(path)
        if not rtfm_dir.is_dir():
            continue  # project moved/deleted — registry cleanup is a separate concern
        state = read_state(rtfm_dir)
        if state is None or not pid_alive(state.pid):
            # Registered but no live worker → respawn. Covers the
            # post-SIGKILL / post-crash case, where the user expects
            # the worker to come back the next time they touch the CLI.
            stale.append(path)
            continue
        worker_v = getattr(state, "installed_version", None) or "unknown"
        if worker_v == "unknown":
            continue  # pre-0.22 state file; the worker will self-detect
        if worker_v != current_version:
            stale.append(path)

    if not stale:
        return

    # At least one worker is on a different version. Trigger restart-all
    # once. We don't print anything — this is meant to be invisible.
    try:
        subprocess.Popen(
            [sys.executable, "-m", "rtfm.cli", "worker", "restart-all"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


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
    _register_project(rtfm_dir)
    return proc.pid


def _which(binname: str) -> str | None:
    from shutil import which
    return which(binname)


def _spawn_worker_direct(rtfm_dir: Path,
                         scan_interval: float | None = None) -> int | None:
    """Fork a worker daemon unconditionally (no liveness check first).
    Used by the explicit ``rtfm worker start`` path so the caller can
    pass ``--scan-interval``."""
    cmd = [sys.executable, "-m", "rtfm.cli", "worker-daemon"]
    if scan_interval is not None:
        cmd += ["--scan-interval", str(scan_interval)]
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
        start_new_session=True,
    )
    _register_project(rtfm_dir)
    return proc.pid


# ── ``rtfm worker-daemon`` (hidden) ─────────────────────────────────────

def cmd_worker_daemon(args):
    """Long-running queue drain + idle scanner. Hidden from --help.

    Holds an exclusive flock on ``.rtfm/worker.lock`` so a second
    invocation exits immediately rather than racing.
    """
    rtfm_root = find_rtfm_root()
    if rtfm_root is None:
        sys.exit("worker-daemon: no .rtfm/ project root in the cwd chain.")
    rtfm_dir = rtfm_root / ".rtfm"
    db_path = rtfm_dir / "library.db"
    scan_interval = getattr(args, "scan_interval", None) or SCAN_INTERVAL_SECONDS

    try:
        with WorkerLock(rtfm_dir):
            from rtfm.core.handlers import HANDLERS
            _log(rtfm_dir, f"worker-daemon starting pid={os.getpid()} "
                            f"scan_interval={scan_interval}s")
            worker = Worker(
                rtfm_dir=rtfm_dir, db_path=db_path,
                handlers=HANDLERS,
                scan_interval=scan_interval,
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
    action = getattr(args, "action", "status") or "status"

    # restart-all is project-agnostic — it reads the registry instead of
    # requiring the user to be inside a specific project root.
    if action == "restart-all":
        return _cmd_worker_restart_all()

    rtfm_root = find_rtfm_root()
    if rtfm_root is None:
        sys.exit("worker: no .rtfm/ project root in the cwd chain.")
    rtfm_dir = rtfm_root / ".rtfm"

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
        scan_interval = getattr(args, "scan_interval", None)
        if scan_interval is not None:
            # We can't easily thread an arg through ensure_worker_running
            # without complicating its signature for a niche use; the
            # CLI explicit start path is allowed to fork directly.
            pid = _spawn_worker_direct(rtfm_dir, scan_interval=scan_interval)
        else:
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
            extra = f", scan={scan_interval}s" if scan_interval else ""
            print(f"worker: started (PID {state.pid}{extra}).")
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

    sys.exit(
        f"worker: unknown action {action!r}. "
        "Use start | stop | status | restart-all."
    )


def _cmd_worker_restart_all() -> None:
    """Restart every registered worker. Called after ``pip install`` so
    fresh code takes effect immediately, instead of waiting for the
    next user prompt (which fires the only respawn hook today).

    Reads ``~/.rtfm/workers.json`` for the project list. For each:

    1. SIGTERM the running worker (the new self-restart logic from 0.19
       would catch the version drift on its next tick anyway, but we
       speed that up here);
    2. Wait briefly for graceful shutdown;
    3. SIGKILL if it's still alive after the grace period;
    4. Drop the stale state file;
    5. Spawn a fresh worker.

    Reports per-project: old PID → new PID.
    """
    import signal

    projects = _load_registry()
    if not projects:
        print("worker restart-all: no registered projects yet "
              "(run `rtfm worker start` in each project at least once).")
        return

    print(f"worker restart-all: cycling {len(projects)} project(s)")
    failures: list[str] = []
    for path in projects:
        rtfm_dir = Path(path)
        label = str(rtfm_dir.parent)
        if not rtfm_dir.is_dir():
            print(f"  [missing]  {label}")
            failures.append(label)
            continue

        # Stop the existing worker, if any.
        old_pid = None
        state = worker_running(rtfm_dir)
        if state:
            old_pid = state.pid
            try:
                os.kill(old_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            for _ in range(30):  # up to 3 seconds
                time.sleep(0.1)
                if not pid_alive(old_pid):
                    break
            if pid_alive(old_pid):
                try:
                    os.kill(old_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                time.sleep(0.5)
            clear_state(rtfm_dir)

        # Fresh start.
        new_pid = ensure_worker_running(rtfm_dir)
        if new_pid is None:
            print(f"  [skip]     {label} — spawn failed")
            failures.append(label)
            continue
        # Give the worker a moment to write its state.
        for _ in range(20):
            time.sleep(0.1)
            if worker_running(rtfm_dir):
                break

        if old_pid is not None:
            print(f"  [restart]  {label}  ({old_pid} → {new_pid})")
        else:
            print(f"  [start]    {label}  (new PID {new_pid})")

    if failures:
        sys.exit(1)


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
