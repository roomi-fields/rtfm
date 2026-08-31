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
import threading
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Callable, Optional

from rtfm.core.dbcare import ensure_healthy_db, make_rotating_logger
from rtfm.core.queue import Queue, Job, P_USER
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


# ── Corruption detection ─────────────────────────────────────────────────

#: Substrings SQLite uses for on-disk corruption (as opposed to a transient
#: "database is locked"/"busy", which must NOT trigger quarantine). Matched
#: case-insensitively against the exception message.
_CORRUPTION_MARKERS = (
    "malformed",
    "file is not a database",
    "disk image",
    "database corruption",
)


def _is_db_corruption(exc: BaseException) -> bool:
    """True when *exc* signals structural corruption of the DB file.

    Message-based on purpose: ``sqlite3.DatabaseError`` also covers benign
    lock/busy conditions, which must self-clear, not quarantine a live DB.
    """
    msg = str(exc).lower()
    return any(m in msg for m in _CORRUPTION_MARKERS)


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

#: Lanes held back for P_USER work, on top of the concurrency cap.
#:
#: Priority alone is not enough: it decides who gets the *next* free lane,
#: and on a busy fleet there is no next free lane for minutes — a scan of a
#: large or slow-mounted corpus holds one for as long as it takes. Meanwhile
#: the one job that someone is actually waiting on — the file an agent just
#: edited, a file a search found to be out of date — sits pending. These
#: jobs are single-file ingests, so letting them run slightly over the cap
#: costs almost nothing and is the difference between "indexed now" and
#: "indexed in three minutes".
P_USER_RESERVED_LANES = 2

#: How long a single scheduling step may run before the watchdog says so,
#: and how often it looks. A healthy step is milliseconds; anything near a
#: minute means the loop is stuck on something outside its control.
STALL_WARN_SECONDS = 30.0

#: How often to check every project for ``running`` rows the supervisor is
#: not actually running. Cheap (one indexed UPDATE per project, almost always
#: matching nothing), so it can run often enough that a lost claim costs a
#: minute rather than the rest of the daemon's life.
CLAIM_SWEEP_SECONDS = 60.0

# How often the supervisor checks its own indexes against the invariants a
# healthy one holds (rtfm/core/audit.py). Hourly: the checks are SQL-only and
# cost milliseconds, and every defect they look for is one that ran for weeks
# before anyone noticed. The first pass runs a few minutes after boot, once
# the slots are open and the initial scans have settled.
AUDIT_INTERVAL_SECONDS = 3600.0
AUDIT_FIRST_DELAY_SECONDS = 300.0
STALL_POLL_SECONDS = 5.0

#: How many project databases are integrity-checked at once when they join.
SLOT_OPEN_CONCURRENCY = 2


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
        # mid-job. Nothing can legitimately be in flight at boot, so every
        # ``running`` row is a stale claim — keep_ids stays empty.
        try:
            self.queue.reap_zombies()
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

        # Stall watchdog state (see ``_step``).
        self._step_name: Optional[str] = None
        self._step_started = 0.0
        self._step_warned = False

        self._slots: dict[str, _Slot] = {}
        # Projects being integrity-checked before they join the fleet, and
        # the small side pool that does it — see ``_sync_registry``. Two at a
        # time: enough to overlap the I/O, few enough not to storm the disk.
        self._opening: dict[str, tuple[_Slot, Future]] = {}
        self._wanted: set[str] = set()
        self._open_stagger = 0
        self._opener = ThreadPoolExecutor(
            max_workers=SLOT_OPEN_CONCURRENCY, thread_name_prefix="rtfm-open")
        self._pool = ThreadPoolExecutor(
            max_workers=self._max_concurrent + P_USER_RESERVED_LANES)
        self._inflight: dict[Future, tuple[_Slot, Job]] = {}
        # First sweep happens on the first tick, not a minute in: a claim
        # stranded by the previous incarnation should not outlive boot.
        self._next_claim_sweep = 0.0
        self._next_audit = time.monotonic() + AUDIT_FIRST_DELAY_SECONDS

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
        self._start_stall_watchdog()
        try:
            while not self._stop:
                with self._step("recycle-check"):
                    recycle = self._should_recycle()
                if recycle:
                    self._auto_respawn = True
                    break
                with self._step("sync-registry"):
                    self._sync_registry()
                with self._step("collect-opened"):
                    self._collect_opened()
                with self._step("reap"):
                    self._reap_finished()
                with self._step("sweep-claims"):
                    self._sweep_stale_claims()
                with self._step("audit"):
                    self._audit_indexes()
                with self._step("enqueue-periodic"):
                    self._enqueue_periodic()
                with self._step("dispatch"):
                    dispatched = self._dispatch()
                with self._step("snapshot"):
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

    # ── stall watchdog ───────────────────────────────────────────────────
    # The scheduling loop is single-threaded: whatever blocks it blocks every
    # project at once. Most of it is local SQLite and cannot block for long,
    # but a source on a dead network mount can park a syscall for a minute at
    # a time — and from the outside that is indistinguishable from "idle".
    # The watchdog turns that silence into a log line naming the step.

    @contextmanager
    def _step(self, name: str):
        self._step_name = name
        self._step_started = time.monotonic()
        try:
            yield
        finally:
            self._step_name = None
            self._step_warned = False

    def _start_stall_watchdog(self) -> None:
        def watch() -> None:
            while not self._stop:
                time.sleep(STALL_POLL_SECONDS)
                name = self._step_name
                if name is None or self._step_warned:
                    continue
                held = time.monotonic() - self._step_started
                if held >= STALL_WARN_SECONDS:
                    self._step_warned = True
                    self._log(f"STALL: scheduling blocked in '{name}' for "
                              f"{held:.0f}s — no project is being served")

        threading.Thread(target=watch, name="rtfm-stall-watchdog",
                         daemon=True).start()

    # ── registry → slots ─────────────────────────────────────────────────

    def _sync_registry(self) -> None:
        """Rebuild the slot set from ``workers.json`` when it changes.

        Opening a project is **not** done here. ``_Slot.open`` integrity-scans
        the whole database (:func:`ensure_healthy_db`), which on a large
        corpus means reading gigabytes; doing that for 25 projects on the
        scheduling thread left the fleet unserved for the ten minutes it took,
        every single restart — the stall watchdog named this step. Opening now
        happens on a small side pool and each project joins the fleet the
        moment its own check passes, so a small project is served while a big
        one is still being verified. The guarantee is unchanged: every
        database is still integrity-checked before it is serviced.
        """
        try:
            mtime = self._registry_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        if mtime == self._registry_mtime and (self._slots or self._opening):
            return
        self._registry_mtime = mtime

        try:
            data = json.loads(self._registry_path.read_text(encoding="utf-8"))
            projects = list(data.get("projects", []))
        except (OSError, ValueError):
            projects = []

        wanted = {p for p in projects if Path(p).is_dir()}
        self._wanted = wanted
        for path in sorted(wanted):
            if path in self._slots or path in self._opening:
                continue
            slot = _Slot(Path(path))
            self._opening[path] = (slot, self._opener.submit(slot.open, self._log))
        # Drop removed (only if idle — never yank a slot mid-job).
        for path in list(self._slots):
            if path not in wanted and not self._slots[path].active:
                self._slots[path].close()
                del self._slots[path]
                self._log(f"- project {Path(path).parent.name}")

    def _collect_opened(self) -> None:
        """Admit projects whose integrity check has finished."""
        for path in [p for p, (_, fut) in self._opening.items() if fut.done()]:
            slot, fut = self._opening.pop(path)
            if path not in self._wanted:
                slot.close()  # unregistered while we were checking it
                continue
            try:
                rebuilt = fut.result()
            except Exception as exc:
                self._log(f"{Path(path).parent.name}: open failed: {exc}")
                continue
            # Stagger first scans across the interval so N projects don't all
            # scan at once (the storm we're eliminating). A rebuilt DB scans
            # ASAP to repopulate.
            now = time.monotonic()
            if rebuilt:
                slot.next_scan_at = now
            else:
                span = self._scan_interval / max(1, len(self._wanted))
                slot.next_scan_at = now + (self._open_stagger * span)
                self._open_stagger = (self._open_stagger + 1) % max(1, len(self._wanted))
            self._slots[path] = slot
            self._log(f"+ project {Path(path).parent.name}"
                      + (" (rebuilding: corrupt DB)" if rebuilt else ""))
            self._refresh_hooks(slot)

    def _refresh_hooks(self, slot: "_Slot") -> None:
        """Bring a project's Claude Code hook stubs up to the installed code.

        Hook *scripts* live inside each project, so a project keeps running
        the logic that was current the day it was initialised — a hook bug
        then survives every upgrade. The supervisor always runs the installed
        package and knows every registered project, so it is the one place
        that can close that gap. Only files RTFM installed itself are
        rewritten, and only when they differ.
        """
        try:
            from rtfm.plugin.hooks import refresh_hook_scripts
            updated = refresh_hook_scripts(slot.rtfm_dir.parent)
        except Exception as exc:
            slot.log(f"hook refresh error: {exc}")
            return
        if updated:
            msg = f"hook scripts updated: {', '.join(updated)}"
            slot.log(msg)
            self._log(f"  {Path(slot.rtfm_dir).parent.name}: {msg}")

    # ── dispatch / reap ──────────────────────────────────────────────────

    def _free(self) -> int:
        return self._max_concurrent - len(self._inflight)

    def _free_reserved(self) -> int:
        """Lanes available counting the P_USER reserve."""
        return (self._max_concurrent + P_USER_RESERVED_LANES
                - len(self._inflight))

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
        while self._free_reserved() > 0:
            # Once the ordinary lanes are full, only P_USER work may start —
            # the reserve exists so a file an agent just edited is indexed
            # now, instead of waiting behind long scans in other projects.
            user_only = self._free() <= 0
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
                    if _is_db_corruption(exc):
                        self._recover_slot(slot)
                    continue
                if head is None:
                    continue
                priority, created_at, head_type = head
                if user_only and priority > P_USER:
                    continue
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
                if _is_db_corruption(exc):
                    self._recover_slot(best_slot)
                continue
            if job is None:
                # Race: head vanished between peek and dequeue. Single
                # dispatcher makes this unexpected; skip the slot this pass.
                skip.add(id(best_slot))
                continue
            # From here the row says 'running'. Until the future exists,
            # nothing is running it — so a failed submit must hand the claim
            # back rather than leave a row no one will ever finish.
            try:
                fut = self._pool.submit(self._run_job, best_slot, job)
            except Exception as exc:
                self._log(f"{best_slot.rtfm_dir.parent.name}: submit error "
                          f"on job#{job.id}: {exc}")
                try:
                    best_slot.queue.mark_pending(job.id)
                except Exception:
                    pass  # the claim sweep will pick it up
                skip.add(id(best_slot))
                continue
            best_slot.inflight += 1
            if job.type in EXCLUSIVE_JOB_TYPES:
                best_slot.exclusive = True
            self._inflight[fut] = (best_slot, job)
            dispatched = True
        return dispatched

    def _recover_slot(self, slot: _Slot) -> None:
        """Self-heal a DB that turned corrupt **while the supervisor ran**.

        The boot integrity guard only runs at ``slot.open``; a corruption
        that lands mid-run (hard kill / OOM in a write) makes ``peek``/
        ``dequeue`` raise on every dispatch pass — the dispatcher then
        hot-loops, logging forever and burning a core (one project did this
        for days). Here we close the slot, re-run the integrity guard
        (quarantines the malformed file), reopen a fresh DB, and schedule an
        immediate rebuild scan from source. If quarantine/reopen itself
        fails, the slot is parked (``queue = None``) so it is skipped until
        the next restart rather than looped on.
        """
        name = slot.rtfm_dir.parent.name
        try:
            slot.close()
        except Exception:
            pass
        try:
            rebuilt = slot.open(self._log)
        except Exception as exc:  # pragma: no cover - defensive
            slot.queue = None
            self._log(f"{name}: runtime-corruption recovery failed, parking "
                      f"until restart: {exc}")
            return
        slot.next_scan_at = time.monotonic()  # rebuild from source ASAP
        self._log(f"{name}: runtime DB corruption healed"
                  + (" (quarantined + rebuilding from source)" if rebuilt
                     else " (reopened)"))

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
            # BaseException too: a job popped from _inflight owes the queue a
            # closing write, and letting anything escape here strands the row
            # for good — the pop already happened.
            try:
                fut.result()
            except BaseException as exc:
                tb = traceback.format_exc(limit=20)
                self._close(slot, job, "mark_failed",
                            f"{type(exc).__name__}: {exc}\n{tb}")
                slot.jobs_failed += 1
                self._jobs_failed += 1
                slot.log(f"job#{job.id} {job.type} FAILED: {exc}")
                continue
            self._close(slot, job, "mark_done")
            slot.jobs_done += 1
            self._jobs_done += 1

    def _close(self, slot: _Slot, job: Job, how: str, *args) -> None:
        """Write a finished job's terminal state, and say so if we cannot.

        The closing write is the only thing that releases a claim. It used to
        be best-effort — ``mark_failed`` swallowed its exception entirely and
        ``mark_done`` logged one and moved on — so a write lost to a locked
        database left the row ``running`` forever with no trace in any log.
        A lost close is now loud, and the claim sweep repairs it within the
        minute instead of at the next restart.
        """
        for attempt in range(3):
            try:
                getattr(slot.queue, how)(job.id, *args)
                return
            except Exception as exc:
                if attempt == 2:
                    slot.log(f"job#{job.id} {job.type}: {how} failed after "
                             f"3 tries ({exc}) — the claim sweep will "
                             f"requeue it")
                    return
                time.sleep(0.2 * (attempt + 1))

    def _audit_indexes(self) -> None:
        """Check every open index against the invariants, and say what fails.

        Nothing here repairs anything: the supervisor's job is to make the
        state legible, not to act on a heuristic. Every serious defect this
        index has had was plain in the data for weeks while the logs and the
        test suite said everything was fine — a line in the log the day it
        starts is the whole point.

        Runs on its own thread. The checks are read-only and cheap on a
        healthy index, but "cheap" is not "instant" on a queue holding three
        million rows, and the first version ran inline: it blocked scheduling
        for a full half-minute every hour, with no project served meanwhile.
        A watchdog that stops the work it watches is worse than none.
        """
        now = time.monotonic()
        if now < self._next_audit:
            return
        self._next_audit = now + AUDIT_INTERVAL_SECONDS

        slots = list(self._slots.values())
        if not slots:
            return

        def run() -> None:
            from rtfm.core.audit import audit_project

            for slot in slots:
                try:
                    findings = audit_project(slot.db_path, slot.rtfm_dir.parent)
                except Exception as exc:
                    slot.log(f"audit error: {exc}")
                    continue
                for finding in findings:
                    slot.log(f"audit: {finding.check}: {finding.detail}")

        threading.Thread(target=run, name="rtfm-audit", daemon=True).start()

    def _sweep_stale_claims(self) -> None:
        """Return ``running`` rows this supervisor is not actually running.

        A ``running`` row is a claim, and the claim is only true while the
        job sits in ``self._inflight``. Everything that can break that link
        — a dispatch that raised after the row was already claimed, a closing
        write that failed, a pool thread killed under us — leaves a row no
        one will ever finish. Nothing retried those rows and nothing reported
        them: the file was silently never indexed.

        Until now the only reclaim ran at ``slot.open``, so a claim lost at
        11:50 on Thursday stayed lost until the daemon next restarted. On this
        machine that meant twenty-six files stranded for up to fifty hours
        under a supervisor that was up, healthy and busy the whole time.

        The sweep is cheap because it is exact: we know our own live job ids,
        so the query touches nothing else and normally matches zero rows.
        """
        now = time.monotonic()
        if now < self._next_claim_sweep:
            return
        self._next_claim_sweep = now + CLAIM_SWEEP_SECONDS

        live: dict[int, set[int]] = {}
        for slot, job in self._inflight.values():
            live.setdefault(id(slot), set()).add(job.id)

        for slot in self._slots.values():
            if slot.queue is None:
                continue
            try:
                result = slot.queue.reap_zombies(live.get(id(slot)) or set())
            except Exception as exc:
                slot.log(f"claim sweep error: {exc}")
                continue
            lost = result["requeued"] + result["failed"] + result["deduped"]
            if lost:
                slot.log(
                    f"claim sweep: {lost} job(s) were marked running with "
                    f"nothing running them — {result['requeued']} requeued, "
                    f"{result['failed']} failed, {result['deduped']} dropped "
                    f"as duplicates")
                self._log(f"{slot.rtfm_dir.parent.name}: recovered {lost} "
                          f"stranded job(s)")

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
            from rtfm.config import build_scan_payload, load_config
            try:
                cfg = load_config(slot.rtfm_dir.parent)
            except Exception:
                cfg = {}
            sources = cfg.get("sources") or [
                {"path": str(slot.rtfm_dir.parent),
                 "corpus": cfg.get("corpus", "default")}
            ]
            for src in sources:
                # ``build_scan_payload`` is lexical by contract — it never
                # touches the filesystem. That matters most here: ``resolve()``
                # stats every path component, and one source on an unreachable
                # network mount would block this thread in uninterruptible I/O,
                # freezing dispatch, reaping and scheduling for *every* project
                # (observed: the whole fleet stalled on a 9p mount while twelve
                # jobs sat finished and unreaped).
                slot.queue.enqueue("scan", build_scan_payload(src, cfg))
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
        self._opener.shutdown(wait=False, cancel_futures=True)
        for slot, _ in self._opening.values():
            slot.close()
        self._opening.clear()
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
