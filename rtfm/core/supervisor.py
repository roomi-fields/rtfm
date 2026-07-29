"""One mutualised worker for the whole fleet.

Replaces the old model of one detached daemon per project (16 resident
processes on a 6-core laptop, each idle-scanning every 30 s, each a
potential concurrent writer to its own DB). A single **supervisor**
process services every registered project's queue instead.

Why this is the right shape:

- **No concurrent-writer corruption.** The supervisor runs jobs in a
  bounded thread pool but never two jobs for the *same* project at once,
  so each ``library.db`` has exactly one writer at any instant. The whole
  class of "two workers raced and corrupted the DB" disappears — it was
  the root cause of the BPscript runaway.
- **Bounded load.** Pool size = the concurrency cap (``_max_concurrent``),
  so at most N heavy jobs run across the entire machine. Scans are staggered
  across projects instead of all firing on the same 30 s tick, killing the
  periodic scan storm.
- **One resident process** instead of N; the embedding model is loaded once
  and shared across pool threads.

Robustness carried over from the per-project worker:

- Exactly one supervisor, enforced by an exclusive flock on
  ``~/.rtfm/supervisor.lock``.
- Clean self-exit + respawn on package-version drift or an RSS ceiling.
- Zombie reaping at boot (``running`` rows from a previous crash → requeued).
- Integrity guard (:mod:`rtfm.core.dbcare`) on every project DB before it is
  serviced: a corrupt DB is quarantined and rebuilt once, never looped on.
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
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Callable, Optional

from rtfm.core.dbcare import ensure_healthy_db, make_rotating_logger
from rtfm.core.queue import Queue, Job
from rtfm.core.throttle import _max_concurrent
from rtfm.core.worker import (
    JobContext,
    IDLE_POLL_SECONDS,
    SCAN_INTERVAL_SECONDS,
    RECONCILE_INTERVAL_SECONDS,
    WORKER_RSS_EXIT_MB,
    _now_iso,
    _read_installed_version,
    _read_mem_total_mb,
    _read_rss_mb,
)


# ── Paths ────────────────────────────────────────────────────────────────

_RTFM_HOME = Path.home() / ".rtfm"
SUPERVISOR_LOCK = _RTFM_HOME / "supervisor.lock"
SUPERVISOR_STATE = _RTFM_HOME / "supervisor_state.json"
SUPERVISOR_LOG = _RTFM_HOME / "supervisor.log"
REGISTRY_PATH = _RTFM_HOME / "workers.json"


# ── On-disk state (so ``rtfm worker status`` can report without the DB) ──

@dataclass
class SupervisorState:
    pid: int
    host: str
    started_at: str
    last_update: str
    concurrency: int
    projects: int
    in_flight: int
    jobs_done: int
    jobs_failed: int
    installed_version: str = "unknown"
    per_project: dict = field(default_factory=dict)


def read_supervisor_state() -> Optional[SupervisorState]:
    if not SUPERVISOR_STATE.exists():
        return None
    try:
        data = json.loads(SUPERVISOR_STATE.read_text(encoding="utf-8"))
        return SupervisorState(**data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _lock_holder_pid() -> Optional[int]:
    """PID of the process holding the supervisor lock, or ``None`` if free.

    This is the **authoritative** liveness signal — it probes the ``flock``
    itself rather than trusting the lazily-written state file. The kernel
    releases a ``flock`` automatically when its holder dies, so "the lock is
    held" is exactly equivalent to "a live supervisor exists", with no window
    where a running-but-not-yet-snapshotted supervisor looks dead (the bug
    that made ``status`` lie, ``stop`` a no-op, and ``start`` spawn a double).
    """
    if not SUPERVISOR_LOCK.exists():
        return None
    try:
        fd = os.open(SUPERVISOR_LOCK, os.O_RDWR)
    except OSError:
        return None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # Held by a live supervisor — read the PID it stamped in.
            try:
                raw = os.pread(fd, 32, 0).decode().strip()
                return int(raw) if raw else None
            except (OSError, ValueError):
                return None
        else:
            # We acquired it → nobody was holding it. Release immediately;
            # any PID still in the file is stale (a dead holder).
            fcntl.flock(fd, fcntl.LOCK_UN)
            return None
    finally:
        os.close(fd)


def supervisor_running() -> Optional[SupervisorState]:
    """Return the live supervisor state, or ``None`` if none is running.

    Liveness comes from the global lock (see :func:`_lock_holder_pid`), not
    the state file. When the lock is held but the state snapshot is missing
    or stale (e.g. during the multi-second model preload right after a
    restart), a minimal live state carrying just the real PID is returned so
    callers never misread a running supervisor as down.
    """
    pid = _lock_holder_pid()
    if pid is None:
        return None
    state = read_supervisor_state()
    if state is not None and state.pid == pid:
        return state
    # Lock held by a live supervisor whose snapshot isn't on disk yet.
    return SupervisorState(
        pid=pid, host=socket.gethostname(), started_at="", last_update="",
        concurrency=0, projects=0, in_flight=0, jobs_done=0, jobs_failed=0,
    )


def clear_supervisor_state() -> None:
    SUPERVISOR_STATE.unlink(missing_ok=True)


# ── Global single-instance lock ──────────────────────────────────────────

class SupervisorLockHeld(RuntimeError):
    """Another supervisor already holds the global lock."""


class SupervisorLock:
    """Exclusive flock on ``~/.rtfm/supervisor.lock``. One supervisor only."""

    def __init__(self) -> None:
        self._fd: Optional[int] = None

    def __enter__(self) -> "SupervisorLock":
        SUPERVISOR_LOCK.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(SUPERVISOR_LOCK, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self._fd)
            self._fd = None
            raise SupervisorLockHeld(f"another supervisor holds {SUPERVISOR_LOCK}")
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


# Job types that must run alone within a project: they read-modify the whole
# index (scan, reconcile) or need an exclusive lock on the DB file (vacuum).
# Everything else (embed/ingest/remove) touches disjoint rows and may run
# concurrently for the same project — that is how a single big import fills
# every core instead of one.
EXCLUSIVE_JOB_TYPES = frozenset({"scan", "reconcile", "vacuum"})


# ── Per-project bookkeeping ──────────────────────────────────────────────

class _Slot:
    """Everything the supervisor tracks for one registered project.

    ``queue`` is touched **only** by the dispatcher (single) thread —
    dequeue / mark_done / mark_failed / periodic enqueue. Pool threads run
    handlers, which open their own short-lived Library/Queue connections.
    Combined with the "≤1 in-flight job per project" rule, that guarantees a
    single writer per ``library.db`` at all times.
    """

    def __init__(self, rtfm_dir: Path):
        self.rtfm_dir = rtfm_dir
        self.db_path = rtfm_dir / "library.db"
        self.log = make_rotating_logger(rtfm_dir / "rtfm.log", prefix="worker")
        self.queue: Optional[Queue] = None
        # Number of this project's jobs in flight in the pool. >1 is allowed
        # for parallelisable types (embed/ingest/remove touch disjoint rows;
        # SQLite WAL serialises the actual writes). ``exclusive`` is set while
        # a scan/reconcile/vacuum runs, and forces that job to run alone.
        self.inflight = 0
        self.exclusive = False
        self.next_scan_at = 0.0        # monotonic
        self.next_reconcile_at = 0.0   # monotonic; 0 until seeded
        self.reconcile_seeded = False
        self.jobs_done = 0
        self.jobs_failed = 0

    @property
    def active(self) -> bool:
        """True while at least one of this project's jobs is in the pool."""
        return self.inflight > 0

    def open(self, log: Callable[[str], None]) -> bool:
        """Integrity-guard the DB, then open the queue. Returns ``True`` if
        a rebuild was triggered (caller should force an immediate scan)."""
        rebuilt = ensure_healthy_db(self.db_path, log=self.log)
        self.queue = Queue(self.db_path)
        # Reap zombies left by a previous supervisor/worker that died
        # mid-job — every ``running`` row is orphaned now.
        try:
            self.queue.reap_zombies(rtfm_dir=None)
        except Exception as exc:  # pragma: no cover - defensive
            log(f"{self.rtfm_dir.parent.name}: boot reap error: {exc}")
        return rebuilt

    def close(self) -> None:
        if self.queue is not None:
            self.queue.close()
            self.queue = None


# ── The supervisor ───────────────────────────────────────────────────────

class Supervisor:
    def __init__(
        self,
        registry_path: Path = REGISTRY_PATH,
        log: Optional[Callable[[str], None]] = None,
        max_concurrent: Optional[int] = None,
        scan_interval: float = SCAN_INTERVAL_SECONDS,
        reconcile_interval: float = RECONCILE_INTERVAL_SECONDS,
    ):
        self._registry_path = registry_path
        self._log = log or (lambda m: None)
        # 0 (unlimited) is meaningless for a thread pool; clamp to a sane
        # minimum of 1 so the supervisor always makes progress.
        cap = _max_concurrent() if max_concurrent is None else max_concurrent
        self._max_concurrent = max(1, cap)
        self._scan_interval = scan_interval
        self._reconcile_interval = reconcile_interval

        self._slots: dict[str, _Slot] = {}
        self._pool = ThreadPoolExecutor(max_workers=self._max_concurrent)
        self._inflight: dict[Future, tuple[_Slot, Job]] = {}

        self._stop = False
        self._auto_respawn = False
        self._started_at = _now_iso()
        self._our_version = _read_installed_version()
        self._registry_mtime = 0.0
        self._jobs_done = 0
        self._jobs_failed = 0

    # ── entry point ──────────────────────────────────────────────────────

    def run(self) -> None:
        self._install_signal_handlers()
        self._log(f"supervisor started pid={os.getpid()} "
                  f"concurrency={self._max_concurrent}")
        # Publish a snapshot *before* the (multi-second) model preload so
        # ``rtfm worker status`` reports real counters the instant the
        # process is up, not only after preload. Liveness itself already
        # comes from the lock, but the counters live here.
        self._snapshot()
        self._preload_model()
        try:
            while not self._stop:
                if self._should_recycle():
                    self._auto_respawn = True
                    break
                self._sync_registry()
                self._reap_finished()
                self._enqueue_periodic()
                dispatched = self._dispatch()
                self._snapshot()
                # Sleep only when fully idle: no dispatch this tick and
                # nothing in flight. Otherwise loop hot so finished jobs are
                # reaped and successors dispatched promptly.
                if not dispatched and not self._inflight:
                    self._sleep(IDLE_POLL_SECONDS)
                else:
                    self._sleep(0.2)
        finally:
            self._shutdown()

    # ── registry → slots ─────────────────────────────────────────────────

    def _sync_registry(self) -> None:
        """Rebuild the slot set from ``workers.json`` when it changes.

        New projects get a slot (integrity-guarded, queue opened). Projects
        dropped from the registry are closed once they are not mid-job.
        """
        try:
            mtime = self._registry_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        if mtime == self._registry_mtime and self._slots:
            return
        self._registry_mtime = mtime

        try:
            data = json.loads(self._registry_path.read_text(encoding="utf-8"))
            projects = list(data.get("projects", []))
        except (OSError, ValueError):
            projects = []

        wanted = {p for p in projects if Path(p).is_dir()}
        # Add new.
        stagger = 0
        for path in sorted(wanted):
            if path in self._slots:
                continue
            slot = _Slot(Path(path))
            rebuilt = slot.open(self._log)
            # Stagger first scans across the interval so N projects don't
            # all scan at once (the storm we're eliminating). A rebuilt DB
            # scans ASAP to repopulate.
            now = time.monotonic()
            if rebuilt:
                slot.next_scan_at = now
            else:
                span = self._scan_interval / max(1, len(wanted))
                slot.next_scan_at = now + (stagger * span)
                stagger += 1
            self._slots[path] = slot
            self._log(f"+ project {Path(path).parent.name}"
                      + (" (rebuilding: corrupt DB)" if rebuilt else ""))
        # Drop removed (only if idle — never yank a slot mid-job).
        for path in list(self._slots):
            if path not in wanted and not self._slots[path].active:
                self._slots[path].close()
                del self._slots[path]
                self._log(f"- project {Path(path).parent.name}")

    # ── dispatch / reap ──────────────────────────────────────────────────

    def _free(self) -> int:
        return self._max_concurrent - len(self._inflight)

    def _slot_can_accept(self, slot: "_Slot", head_type: str) -> bool:
        """Whether *slot* may take its head job right now.

        A slot running an exclusive job (scan/reconcile/vacuum) takes nothing
        more until it finishes. An exclusive head may only start when the
        project has nothing else in flight, so it runs alone. Parallelisable
        heads (embed/ingest/remove) may stack up to the pool's free lanes.
        """
        if slot.queue is None or slot.exclusive:
            return False
        if head_type in EXCLUSIVE_JOB_TYPES:
            return slot.inflight == 0
        return True

    def _dispatch(self) -> bool:
        """Fill free pool lanes in **global arrival order**.

        Documents are served in the order they were queued, regardless of
        which project they belong to: at each free lane we peek every
        project's head job and pick the globally oldest by ``(priority,
        created_at)``. ``priority`` still wins first — an explicit P0 always
        preempts background work.

        A project may hold **several** lanes at once for parallelisable job
        types (embed/ingest/remove write disjoint rows; SQLite WAL serialises
        the actual writes), so a single big import can fill every core.
        Scan/reconcile/vacuum still run alone per project (see
        :meth:`_slot_can_accept`). With no per-project lane cap, the oldest
        work naturally occupies the pool and newer work from other projects
        queues behind it — exactly arrival order across the whole machine.

        Returns ``True`` if at least one job was dispatched.
        """
        dispatched = False
        skip: set[int] = set()  # slots to ignore for the rest of this pass
        while self._free() > 0:
            # Pick the globally-oldest dispatchable head across all projects.
            best_slot: Optional[_Slot] = None
            best_key: Optional[tuple[int, str]] = None
            for slot in self._slots.values():
                if id(slot) in skip:
                    continue
                try:
                    head = slot.queue.peek() if slot.queue is not None else None
                except Exception as exc:
                    self._log(f"{slot.rtfm_dir.parent.name}: peek error: {exc}")
                    skip.add(id(slot))
                    continue
                if head is None:
                    continue
                priority, created_at, head_type = head
                if not self._slot_can_accept(slot, head_type):
                    continue
                key = (priority, created_at)
                if best_key is None or key < best_key:
                    best_key, best_slot = key, slot
            if best_slot is None:
                break  # nothing dispatchable anywhere

            try:
                job = best_slot.queue.dequeue()
            except Exception as exc:
                self._log(f"{best_slot.rtfm_dir.parent.name}: dequeue error: {exc}")
                skip.add(id(best_slot))  # don't re-pick it this pass
                continue
            if job is None:
                # Race: head vanished between peek and dequeue. Single
                # dispatcher makes this unexpected; skip the slot this pass.
                skip.add(id(best_slot))
                continue
            best_slot.inflight += 1
            if job.type in EXCLUSIVE_JOB_TYPES:
                best_slot.exclusive = True
            fut = self._pool.submit(self._run_job, best_slot, job)
            self._inflight[fut] = (best_slot, job)
            dispatched = True
        return dispatched

    def _run_job(self, slot: _Slot, job: Job) -> None:
        """Pool-thread body: run the handler with a minimal context.

        Raises on handler failure — the dispatcher reaps the future and
        records failure. Success returns ``None``.
        """
        from rtfm.core.handlers import HANDLERS
        handler = HANDLERS.get(job.type)
        if handler is None:
            raise RuntimeError(f"no handler for type={job.type!r}")
        ctx = JobContext(str(slot.db_path), slot.log)
        handler(job, ctx)

    def _reap_finished(self) -> None:
        done = [f for f in self._inflight if f.done()]
        for fut in done:
            slot, job = self._inflight.pop(fut)
            slot.inflight = max(0, slot.inflight - 1)
            if job.type in EXCLUSIVE_JOB_TYPES:
                slot.exclusive = False
            try:
                fut.result()
            except Exception as exc:
                tb = traceback.format_exc(limit=20)
                try:
                    slot.queue.mark_failed(job.id, f"{type(exc).__name__}: {exc}\n{tb}")
                except Exception:
                    pass
                slot.jobs_failed += 1
                self._jobs_failed += 1
                slot.log(f"job#{job.id} {job.type} FAILED: {exc}")
                continue
            try:
                slot.queue.mark_done(job.id)
            except Exception as exc:  # pragma: no cover - defensive
                slot.log(f"job#{job.id} {job.type} mark_done error: {exc}")
            slot.jobs_done += 1
            self._jobs_done += 1

    # ── periodic scan / reconcile (staggered) ────────────────────────────

    def _enqueue_periodic(self) -> None:
        now = time.monotonic()
        for slot in self._slots.values():
            if slot.queue is None:
                continue
            if now >= slot.next_scan_at:
                slot.next_scan_at = now + self._scan_interval
                self._enqueue_scans(slot)
            if not slot.reconcile_seeded:
                slot.next_reconcile_at = now + self._reconcile_interval
                slot.reconcile_seeded = True
            elif now >= slot.next_reconcile_at:
                slot.next_reconcile_at = now + self._reconcile_interval
                try:
                    slot.queue.enqueue("reconcile", {})
                except Exception as exc:
                    slot.log(f"reconcile enqueue error: {exc}")

    def _enqueue_scans(self, slot: _Slot) -> None:
        """Enqueue one P1 ``scan`` job per configured source for a project.

        Mirrors the retired ``Worker._maybe_scan`` — dedup on the queue's
        ``UNIQUE(type, payload) WHERE status='pending'`` index means a scan
        already pending is silently dropped.
        """
        try:
            from rtfm.config import load_config
            try:
                cfg = load_config(slot.rtfm_dir.parent)
            except Exception:
                cfg = {}
            sources = cfg.get("sources") or [
                {"path": str(slot.rtfm_dir.parent),
                 "corpus": cfg.get("corpus", "default")}
            ]
            for src in sources:
                src_path = Path(src.get("path", ".")).resolve()
                payload = {
                    "root": str(src_path),
                    "corpus": src.get("corpus", cfg.get("corpus", "default")),
                    "extensions": src.get("extensions") or None,
                }
                if src.get("honor_gitignore") is not None:
                    payload["honor_gitignore"] = bool(src["honor_gitignore"])
                slot.queue.enqueue("scan", payload)
        except Exception as exc:
            slot.log(f"scan enqueue error: {exc}")

    # ── lifecycle helpers ────────────────────────────────────────────────

    def _preload_model(self) -> None:
        """Load the embedding model once so pool threads share a single
        onnxruntime session instead of each loading its own. Best-effort:
        a source checkout without the ``embeddings`` extra just skips it."""
        try:
            from rtfm.core.embeddings import get_model
            get_model()
            self._log("embedding model preloaded (shared across pool)")
        except Exception:
            pass  # no embeddings installed, or model missing — fine

    def _should_recycle(self) -> bool:
        """True when the supervisor should exit and let a fresh one respawn:
        a new package version landed, or RSS crossed the safety ceiling."""
        cur = _read_installed_version()
        if cur != "unknown" and self._our_version != "unknown" and cur != self._our_version:
            self._log(f"version changed ({self._our_version} → {cur}), exiting for restart")
            return True
        rss = _read_rss_mb()
        # Scale the leak ceiling with the pool size, but never above ~60 % of
        # physical RAM — at a core-count-sized pool the naive per-lane × lanes
        # product can exceed total RAM and would never fire.
        ceiling = WORKER_RSS_EXIT_MB * self._max_concurrent
        total = _read_mem_total_mb()
        if total > 0:
            ceiling = min(ceiling, 0.6 * total)
        if rss > 0 and rss > ceiling:
            self._log(f"RSS {rss:.0f}M over ceiling {ceiling}M — exiting for restart")
            return True
        return False

    def _snapshot(self) -> None:
        per = {}
        for path, slot in self._slots.items():
            per[Path(path).parent.name] = {
                "active": slot.active,
                "done": slot.jobs_done,
                "failed": slot.jobs_failed,
            }
        state = SupervisorState(
            pid=os.getpid(),
            host=socket.gethostname(),
            started_at=self._started_at,
            last_update=_now_iso(),
            concurrency=self._max_concurrent,
            projects=len(self._slots),
            in_flight=len(self._inflight),
            jobs_done=self._jobs_done,
            jobs_failed=self._jobs_failed,
            installed_version=self._our_version,
            per_project=per,
        )
        tmp = SUPERVISOR_STATE.with_suffix(f".tmp.{os.getpid()}")
        try:
            tmp.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
            os.replace(tmp, SUPERVISOR_STATE)
        except OSError:
            pass

    def _sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while not self._stop and time.monotonic() < end:
            time.sleep(min(0.2, max(0.0, end - time.monotonic())))

    def _shutdown(self) -> None:
        self._log(f"supervisor stopping pid={os.getpid()} "
                  f"done={self._jobs_done} failed={self._jobs_failed}")
        # Let in-flight jobs finish (they hold the only writer for their DB;
        # killing them mid-write is exactly what corrupts a DB). Then close.
        self._pool.shutdown(wait=True)
        # Any job that completed during shutdown still needs its row closed.
        self._reap_finished()
        for slot in self._slots.values():
            slot.close()
        clear_supervisor_state()
        if self._auto_respawn:
            _spawn_delayed_supervisor(self._log)

    def _install_signal_handlers(self) -> None:
        def _handler(signum, _frame):
            self._stop = True
        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)


# ── respawn helper (version-drift / RSS self-exit) ───────────────────────

def _spawn_delayed_supervisor(log: Callable[[str], None]) -> None:
    """Fork a detached process that respawns the supervisor after the lock
    has been released. Mirrors the old per-worker respawn, now global."""
    import subprocess
    try:
        cmd = [
            sys.executable, "-c",
            "import time, sys; time.sleep(6);"
            f"sys.path.insert(0, {str(Path(__file__).resolve().parent.parent.parent)!r});"
            "from rtfm.cli_worker import ensure_supervisor_running;"
            "ensure_supervisor_running()",
        ]
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        log("scheduled supervisor respawn in ~6s")
    except Exception as exc:
        log(f"could not schedule respawn: {exc}")


def run_supervisor() -> None:
    """Acquire the global lock and run the supervisor loop. Exits silently
    if another supervisor already holds the lock."""
    from rtfm.core.throttle import apply_thread_caps
    apply_thread_caps()
    _RTFM_HOME.mkdir(parents=True, exist_ok=True)
    log = make_rotating_logger(SUPERVISOR_LOG, prefix="supervisor")
    try:
        with SupervisorLock():
            Supervisor(log=log).run()
    except SupervisorLockHeld:
        return
