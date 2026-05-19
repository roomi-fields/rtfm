"""Filesystem watcher daemon: periodic poll → enqueue P1 ingest.

Why poll instead of inotify:

  * RTFM frequently indexes Obsidian vaults on ``/mnt/d/`` (NTFS via
    WSL). inotify does **not** propagate filesystem events across
    that boundary, so a pure-inotify watcher would silently miss
    every change there.
  * A 30 s poll with the existing ``quick_diff`` (size + mtime, no
    MD5) is cheap enough on WSL/NTFS and works identically on ext4.
  * Granularity matches what the user already expects from the
    existing hooks: changes show up within seconds of a save, not
    instantly. The priority queue absorbs the rest.

The watcher is a long-running process, started on demand by
``rtfm watch start`` (or by a future SessionStart hook). It holds
its own ``flock`` (``.rtfm/watcher.lock``) so at most one watcher
per project, mirrors the worker's state-file pattern
(``.rtfm/watcher_state.json``), and respects ``nice``/``ionice``
inherited from the launcher.
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import socket
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Optional


POLL_INTERVAL_SECONDS = 30.0
STATE_FILENAME = "watcher_state.json"
LOCK_FILENAME = "watcher.lock"


@dataclass
class WatcherState:
    pid: int
    host: str
    status: str  # 'idle' | 'scanning' | 'stopping'
    sources_count: int
    last_scan_at: Optional[str]
    last_enqueued: int
    total_enqueued: int
    total_scans: int
    started_at: str
    last_update: str


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _state_path(rtfm_dir: Path) -> Path:
    return rtfm_dir / STATE_FILENAME


def _lock_path(rtfm_dir: Path) -> Path:
    return rtfm_dir / LOCK_FILENAME


def write_state(rtfm_dir: Path, state: WatcherState) -> None:
    path = _state_path(rtfm_dir)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_state(rtfm_dir: Path) -> Optional[WatcherState]:
    path = _state_path(rtfm_dir)
    if not path.exists():
        return None
    try:
        return WatcherState(**json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def clear_state(rtfm_dir: Path) -> None:
    _state_path(rtfm_dir).unlink(missing_ok=True)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def watcher_running(rtfm_dir: Path) -> Optional[WatcherState]:
    state = read_state(rtfm_dir)
    if state is None:
        return None
    if state.status == "stopping":
        return None
    if not pid_alive(state.pid):
        return None
    return state


class WatcherLockHeld(RuntimeError):
    """Raised when another watcher already holds the lock."""


class WatcherLock:
    """Exclusive flock on ``.rtfm/watcher.lock``."""

    def __init__(self, rtfm_dir: Path):
        self.path = _lock_path(rtfm_dir)
        self._fd: Optional[int] = None

    def __enter__(self) -> "WatcherLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self._fd)
            self._fd = None
            raise WatcherLockHeld(f"another watcher holds {self.path}")
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


class Watcher:
    """The poll loop.

    Construct with the project's ``.rtfm/`` directory and call ``run()``.
    Reads the current source list from ``config.json`` on every tick so
    a config edit is picked up at the next scan without restarting.
    """

    def __init__(self, rtfm_dir: Path,
                 poll_interval: float = POLL_INTERVAL_SECONDS,
                 log: Optional[Callable[[str], None]] = None):
        self.rtfm_dir = rtfm_dir
        self.project_root = rtfm_dir.parent
        self.db_path = rtfm_dir / "library.db"
        self.poll_interval = poll_interval
        self._log = log or (lambda msg: None)
        self._stop = False
        self._total_enqueued = 0
        self._total_scans = 0
        self._started_at = _now_iso()

    def run(self) -> None:
        self._install_signal_handlers()
        self._snapshot("idle", 0, 0, None)
        self._log(f"watcher started pid={os.getpid()} poll={self.poll_interval}s")
        try:
            while not self._stop:
                last_count, sources_n = self._scan_once()
                self._snapshot("idle", last_count, sources_n, _now_iso())
                self._sleep(self.poll_interval)
        finally:
            self._snapshot("stopping", 0, 0, _now_iso())
            self._log(f"watcher stopping pid={os.getpid()} scans={self._total_scans} enqueued={self._total_enqueued}")
            clear_state(self.rtfm_dir)

    # ── Internals ───────────────────────────────────────────────────────

    def _scan_once(self) -> tuple[int, int]:
        """Scan every configured source once. Returns (enqueued_this_scan, sources_count)."""
        from rtfm.config import load_config
        from rtfm.core.library import Library
        from rtfm.core.queue import Queue
        from rtfm.core.sync import quick_diff

        try:
            cfg = load_config(self.project_root)
        except Exception:
            cfg = {}
        sources = cfg.get("sources") or [
            {"path": str(self.project_root),
             "corpus": cfg.get("corpus", "default")}
        ]
        sources_n = len(sources)
        self._snapshot("scanning", 0, sources_n, _now_iso())

        enqueued = 0
        lib = Library(str(self.db_path))
        queue = Queue(str(self.db_path))
        try:
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
                    diff = quick_diff(lib, src_path, src_corpus,
                                      extensions=ext_set)
                except Exception as exc:
                    self._log(f"scan error [{src_corpus}] {src_path}: {exc}")
                    continue

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
                if not payloads:
                    continue
                inserted, _ = queue.enqueue_many("ingest", payloads)
                enqueued += inserted
                if inserted:
                    self._log(f"enqueued {inserted} from [{src_corpus}] "
                              f"{src_path.name}")
        finally:
            queue.close()
            lib.close()

        self._total_scans += 1
        self._total_enqueued += enqueued

        if enqueued > 0:
            try:
                from rtfm.cli_worker import ensure_worker_running
                ensure_worker_running(self.rtfm_dir)
            except Exception as exc:
                self._log(f"could not spawn worker after enqueue: {exc}")

        return enqueued, sources_n

    def _snapshot(self, status: str, last_count: int,
                  sources_n: int, last_scan_at: Optional[str]) -> None:
        write_state(self.rtfm_dir, WatcherState(
            pid=os.getpid(),
            host=socket.gethostname(),
            status=status,
            sources_count=sources_n,
            last_scan_at=last_scan_at,
            last_enqueued=last_count,
            total_enqueued=self._total_enqueued,
            total_scans=self._total_scans,
            started_at=self._started_at,
            last_update=_now_iso(),
        ))

    def _sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while not self._stop and time.monotonic() < end:
            time.sleep(min(0.5, end - time.monotonic()))

    def _install_signal_handlers(self) -> None:
        def _handler(signum, _frame):
            self._stop = True
        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)
