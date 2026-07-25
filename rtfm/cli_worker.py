"""CLI commands for the mutualised worker (the *supervisor*).

Since 0.25 there is exactly **one** worker process for the whole machine —
the supervisor (see :mod:`rtfm.core.supervisor`) — instead of one detached
daemon per project. It reads ``~/.rtfm/workers.json`` and services every
registered project's queue, with a bounded thread pool and a single writer
per ``library.db``.

User-facing subcommands:
  - ``rtfm worker``        → start / stop / restart-all / status (the supervisor)
  - ``rtfm queue``         → inspect/manage one project's work queue
  - ``rtfm worker-daemon`` (hidden) → the supervisor loop itself, spawned by
                             :func:`ensure_supervisor_running`.

``ensure_worker_running(rtfm_dir)`` is kept as the public "make sure my
project gets serviced" entry point every producer (CLI, hooks, MCP) calls:
it registers the project and makes sure the one supervisor is alive.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from rtfm.config import find_rtfm_root
from rtfm.core.queue import Queue
from rtfm.core.supervisor import (
    supervisor_running, clear_supervisor_state, run_supervisor,
)
from rtfm.core.worker import pid_alive


# ── Cross-project worker registry ───────────────────────────────────────
# Every ``.rtfm/`` dir that has ever had work is listed here; the supervisor
# reads it to know which projects to service.

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


# ── Lazy version-drift restart (called from cli.main) ────────────────────

_LAZY_CHECK_INTERVAL_S = 60.0
_LAZY_CHECK_MARKER = Path.home() / ".rtfm" / "last-version-check"


def _maybe_lazy_restart_stale_workers() -> None:
    """Throttled check: if the supervisor is dead or running on a different
    ``rtfm-ai`` version than the CLI just loaded, restart it once.

    Called from ``cli.main`` at the start of every command. Best-effort:
    any error is swallowed. The marker is touched on every call so a burst
    of commands doesn't fire a burst of restarts.
    """
    import importlib.metadata as _m

    try:
        last = _LAZY_CHECK_MARKER.stat().st_mtime
        if time.time() - last < _LAZY_CHECK_INTERVAL_S:
            return
    except OSError:
        pass
    try:
        _LAZY_CHECK_MARKER.parent.mkdir(parents=True, exist_ok=True)
        _LAZY_CHECK_MARKER.touch()
    except OSError:
        pass

    # Nothing registered yet → nothing to supervise.
    if not _load_registry():
        return

    try:
        current_version = _m.version("rtfm-ai")
    except _m.PackageNotFoundError:
        return  # source checkout: nothing to compare against

    state = supervisor_running()
    if state is not None:
        worker_v = getattr(state, "installed_version", None) or "unknown"
        if worker_v == "unknown" or worker_v == current_version:
            return  # healthy and current — nothing to do
        # else: version drift → restart below.

    # Supervisor is either down or stale — (re)start it once, detached.
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


# ── Spawn helpers ────────────────────────────────────────────────────────

def _which(binname: str) -> str | None:
    from shutil import which
    return which(binname)


def _spawn_env() -> dict:
    """Env for the supervisor Popen: inherit the parent env and layer in the
    thread caps so onnxruntime initialises with a bounded intra-op pool."""
    from rtfm.core.throttle import thread_cap_env
    return {**os.environ, **thread_cap_env()}


def ensure_supervisor_running() -> int | None:
    """Spawn the one supervisor if it isn't already running. Returns its
    PID, or ``None`` if another starter won the race. Idempotent.

    Runs niced + ioniced (best-effort) so background indexing never
    competes with the user's interactive work.
    """
    state = supervisor_running()
    if state is not None:
        return state.pid
    # Stale state from a crashed supervisor — drop it before respawning.
    clear_supervisor_state()

    cmd = [sys.executable, "-m", "rtfm.cli", "worker-daemon"]
    wrappers: list[str] = []
    for binname, flags in (("ionice", ["-c", "3"]), ("nice", ["-n", "19"])):
        if _which(binname):
            wrappers += [binname, *flags]
    proc = subprocess.Popen(
        wrappers + cmd,
        cwd=str(Path.home()),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # immune to parent SIGHUP / hook timeout
        env=_spawn_env(),
    )
    return proc.pid


def ensure_worker_running(rtfm_dir: Path) -> int | None:
    """Register *rtfm_dir* and make sure the supervisor is alive.

    Kept as the stable entry point every producer (``rtfm sync``, the hooks,
    the MCP server) calls. In the mutualised model "start my project's
    worker" means "add my project to the registry and ensure the one
    supervisor is running" — the supervisor picks the new project up on its
    next registry poll. Returns the supervisor PID.
    """
    _register_project(rtfm_dir)
    return ensure_supervisor_running()


# ── ``rtfm worker-daemon`` (hidden) — the supervisor loop ────────────────

def cmd_worker_daemon(args):
    """Run the mutualised supervisor. Hidden from ``--help``; spawned by
    :func:`ensure_supervisor_running`. Exits silently if another supervisor
    already holds the global lock."""
    run_supervisor()


# ── ``rtfm worker [start|stop|status|restart-all]`` ──────────────────────

def cmd_worker(args):
    action = getattr(args, "action", "status") or "status"

    if action == "restart-all":
        return _cmd_worker_restart_all()

    if action == "status":
        state = supervisor_running()
        if not state:
            print("worker: supervisor not running.")
            return
        print(f"worker: supervisor running (PID {state.pid}, host {state.host})")
        print(f"  concurrency: {state.concurrency}")
        print(f"  projects:    {state.projects} ({state.in_flight} job(s) in flight)")
        print(f"  jobs:        {state.jobs_done} done, {state.jobs_failed} failed")
        print(f"  started:     {state.started_at}")
        busy = [name for name, p in (state.per_project or {}).items() if p.get("active")]
        if busy:
            print(f"  busy now:    {', '.join(sorted(busy))}")
        return

    if action == "start":
        # Register the current project if we're inside one, so a bare
        # ``rtfm worker start`` from a project root also enrolls it.
        rtfm_root = find_rtfm_root()
        if rtfm_root is not None:
            _register_project(rtfm_root / ".rtfm")
        pid = ensure_supervisor_running()
        if pid is None:
            print("worker: could not start (another starter won the race).")
            return
        for _ in range(20):
            time.sleep(0.1)
            if supervisor_running():
                break
        state = supervisor_running()
        if state:
            print(f"worker: supervisor started (PID {state.pid}).")
        else:
            print(f"worker: supervisor spawned (PID {pid}) — waiting on state file...")
        return

    if action == "stop":
        state = supervisor_running()
        if not state:
            print("worker: supervisor not running.")
            return
        try:
            os.kill(state.pid, signal.SIGTERM)
        except ProcessLookupError:
            print("worker: supervisor process already gone.")
            clear_supervisor_state()
            return
        for _ in range(60):  # up to 6s — let in-flight jobs finish cleanly
            time.sleep(0.1)
            if not pid_alive(state.pid):
                break
        if pid_alive(state.pid):
            print(f"worker: SIGTERM sent to PID {state.pid} — finishing in-flight jobs.")
        else:
            print(f"worker: supervisor stopped (PID {state.pid}).")
            clear_supervisor_state()
        return

    sys.exit(
        f"worker: unknown action {action!r}. "
        "Use start | stop | status | restart-all."
    )


def _cmd_worker_restart_all() -> None:
    """Restart the one supervisor. Named ``restart-all`` for continuity with
    the pre-0.25 fleet command and the hook/lazy-check callers.

    SIGTERM (graceful: in-flight jobs finish so no DB write is interrupted
    → no corruption), wait, SIGKILL only as a last resort, then respawn.
    """
    state = supervisor_running()
    old_pid = None
    if state is not None:
        old_pid = state.pid
        try:
            os.kill(old_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        for _ in range(80):  # up to 8s of graceful drain
            time.sleep(0.1)
            if not pid_alive(old_pid):
                break
        if pid_alive(old_pid):
            try:
                os.kill(old_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            time.sleep(0.5)
    clear_supervisor_state()

    new_pid = ensure_supervisor_running()
    if new_pid is None:
        print("worker restart-all: spawn failed")
        sys.exit(1)
    for _ in range(20):
        time.sleep(0.1)
        if supervisor_running():
            break
    if old_pid is not None:
        print(f"worker restart-all: supervisor restarted ({old_pid} → {new_pid})")
    else:
        print(f"worker restart-all: supervisor started (PID {new_pid})")


# ── ``rtfm queue [stats|list|failed|clear-done|retry-failed|reap]`` ──────

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

        if action == "reap":
            conn = queue._get_conn()
            zombies = list(conn.execute(
                "SELECT id, type, priority, payload, attempts, started_at "
                "FROM work_queue WHERE status = 'running' "
                "ORDER BY started_at"
            ).fetchall())
            if not zombies:
                print("queue: nothing to reap (no jobs in 'running' state).")
                return
            rtfm_dir = rtfm_root / ".rtfm"
            result = queue.reap_zombies(rtfm_dir=rtfm_dir)
            deduped_msg = (
                f", {result.get('deduped', 0)} duplicates dropped"
                if result.get("deduped") else ""
            )
            print(
                f"queue: reaped {result['requeued']} job(s) back to pending, "
                f"{result['failed']} marked failed (retry limit reached)"
                f"{deduped_msg}."
            )
            print()
            print(f"Details ({len(zombies)} candidate(s) before reap):")
            for z in zombies:
                try:
                    payload = json.loads(z["payload"])
                except Exception:
                    payload = {}
                fp = payload.get("filepath") or payload.get("root") or ""
                print(
                    f"  #{z['id']:<6} P{z['priority']} {z['type']:<10} "
                    f"attempts={z['attempts']} started={z['started_at']} {fp}"
                )
            return

        sys.exit(f"queue: unknown action {action!r}.")
    finally:
        queue.close()
