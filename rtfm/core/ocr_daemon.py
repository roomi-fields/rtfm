"""Background-daemon helpers for `rtfm sync --ocr`.

OCR via marker-pdf is slow: minutes per scan, hours for a real corpus.
Running it inside the terminal (or worse, inside a Claude Code hook)
means a closed terminal or a timed-out hook kills the process and the
user loses the entire run.

The daemon model:

1. ``rtfm sync --ocr`` invalidates the file_hash of every entry listed
   in ``.rtfm/seen_scans.json`` (so the next incremental sync treats
   them as modified and re-ingests them with marker), then forks a
   detached subprocess running ``rtfm ocr-worker`` and exits. The
   subprocess is created with ``start_new_session=True`` so it has its
   own session and is immune to SIGHUP from the parent terminal /
   Claude Code hook.
2. The worker writes its live progress to ``.rtfm/ocr_state.json``
   (PID, total, done, current_file, started_at, last_update). If the
   process dies, the file stays — the next ``rtfm sync --ocr`` reads
   it, sees the PID is no longer alive, and resumes from where the
   incremental sync left off (files already re-OCR'd now have a real
   hash and are skipped).
3. ``rtfm status`` surfaces the live state when a daemon is running.

Lifecycle on disk:

    ├─ daemon starts → ocr_state.json appears (status="running", pid=...)
    ├─ daemon ticks   → ocr_state.json rewritten with new done/current
    ├─ daemon ends    → ocr_state.json deleted (clean exit)
    │                 → status="crashed" if exception bubbled up
    └─ daemon killed  → ocr_state.json stays with stale pid (resumable)
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATE_FILENAME = "ocr_state.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pid_alive(pid: int) -> bool:
    """Return True if a process with the given PID is currently alive.

    Uses ``os.kill(pid, 0)`` which sends no signal but raises ProcessLookupError
    if the PID is no longer valid. Cheap, ~µs.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # PID exists but belongs to another user — from our point of view it
        # is still alive enough that we don't want to overwrite its state.
        return True
    except OSError:
        return False
    return True


@dataclass
class OCRState:
    """Snapshot of the live OCR daemon, persisted as ocr_state.json."""

    pid: int
    status: str            # "running" | "finished" | "crashed"
    total: int
    done: int
    current_file: str
    started_at: str
    last_update: str
    error: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "pid": self.pid,
            "status": self.status,
            "total": self.total,
            "done": self.done,
            "current_file": self.current_file,
            "started_at": self.started_at,
            "last_update": self.last_update,
            "error": self.error,
            "history": self.history[-20:],  # keep tail only
        }


def _state_path(rtfm_dir: Path) -> Path:
    return rtfm_dir / STATE_FILENAME


def read_state(rtfm_dir: Path) -> OCRState | None:
    """Read ``ocr_state.json`` if it exists, else None.

    Returns None on a parse error rather than raising — the state file
    is best-effort UI, not a contract.
    """
    p = _state_path(rtfm_dir)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return OCRState(
            pid=int(data.get("pid", 0)),
            status=data.get("status", "unknown"),
            total=int(data.get("total", 0)),
            done=int(data.get("done", 0)),
            current_file=data.get("current_file", ""),
            started_at=data.get("started_at", ""),
            last_update=data.get("last_update", ""),
            error=data.get("error"),
            history=data.get("history", []),
        )
    except Exception:
        return None


def write_state(rtfm_dir: Path, state: OCRState) -> None:
    """Atomically replace ocr_state.json with the latest snapshot.

    Atomic because tooling (CLI status, hook) may read it concurrently
    with the worker rewriting it. We write to a sibling file and rename.
    """
    rtfm_dir.mkdir(parents=True, exist_ok=True)
    target = _state_path(rtfm_dir)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(target)


def clear_state(rtfm_dir: Path) -> None:
    """Remove the state file (clean-exit teardown)."""
    p = _state_path(rtfm_dir)
    try:
        p.unlink()
    except FileNotFoundError:
        pass


def daemon_running(rtfm_dir: Path) -> OCRState | None:
    """Return the OCRState if a worker is currently running, else None.

    "Running" means: state file exists, status == "running", and the
    recorded PID is still alive on this system.
    """
    state = read_state(rtfm_dir)
    if state is None:
        return None
    if state.status != "running":
        return None
    if not pid_alive(state.pid):
        return None
    return state


def format_progress(state: OCRState) -> str:
    """Render a human-readable progress line for a live or stale daemon."""
    pct = (state.done * 100 / state.total) if state.total else 0
    elapsed = _elapsed_seconds(state.started_at)
    elapsed_str = _format_duration(elapsed) if elapsed else "?"

    if state.status == "running":
        eta_str = ""
        if state.done > 0 and elapsed:
            rate = state.done / elapsed
            remaining = max(0, state.total - state.done)
            eta = remaining / rate if rate > 0 else 0
            eta_str = f", ETA ~{_format_duration(eta)}"
        line = (f"OCR running (PID {state.pid}): {state.done}/{state.total} "
                f"PDFs ({pct:.0f}%), {elapsed_str} elapsed{eta_str}")
        if state.current_file:
            line += f"\n  current: {state.current_file}"
        return line
    if state.status == "crashed":
        return (f"OCR interrupted at {state.done}/{state.total} "
                f"({pct:.0f}%, {elapsed_str} elapsed). "
                "Resume: rtfm sync --ocr")
    return (f"OCR last status: {state.status} "
            f"({state.done}/{state.total}, {elapsed_str} elapsed)")


def _elapsed_seconds(started_at: str) -> float:
    if not started_at:
        return 0.0
    try:
        t0 = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - t0).total_seconds())
    except Exception:
        return 0.0


def _format_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60}m"
