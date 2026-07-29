"""Database self-care: corruption detection + log rotation.

Two hardening primitives that turn silent, unbounded failure modes into
bounded, self-healing ones:

1. **Integrity guard** (:func:`ensure_healthy_db`). A SQLite file can be
   corrupted by a hard kill (SIGKILL from ``restart-all``'s 3-second grace,
   or the OOM-killer) landing mid-write. Once corrupt, every open raises
   ``database disk image is malformed`` and the worker either crash-loops or
   — worse — can no longer see which files it already indexed, so it
   re-ingests and re-embeds everything on every scan. One project ran that
   loop for weeks, growing a 2 GB DB and a 2.4 GB log. The fix is detection:
   ``PRAGMA quick_check`` at startup; if it fails, quarantine the file and
   let a fresh DB rebuild once from source — instead of looping forever.

2. **Log rotation** (:func:`rotate_log_if_large`, :func:`make_rotating_logger`).
   The worker log was append-only and unbounded. Cap it so a chatty or
   looping worker can never fill the disk.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Callable, Optional


# ── Integrity guard ─────────────────────────────────────────────────────


def check_integrity(db_path: str | Path) -> bool:
    """Return ``True`` iff ``PRAGMA quick_check`` reports ``ok``.

    A missing file is considered healthy (a fresh DB will be created on
    first write). ``quick_check`` is used rather than the exhaustive
    ``integrity_check`` because it is far cheaper on a multi-GB file and
    still catches the structural corruption (out-of-order rowids, dangling
    page references) that breaks normal queries.
    """
    p = Path(db_path)
    if not p.exists():
        return True
    try:
        conn = sqlite3.connect(str(p))
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        # "file is not a database" / "malformed" both surface here.
        return False
    return bool(row) and row[0] == "ok"


def quarantine_db(db_path: str | Path) -> Optional[Path]:
    """Move a (corrupt) DB and its WAL/SHM sidecars aside so a fresh one
    can be created in its place. Returns the quarantine path of the main
    file, or ``None`` if there was nothing to move.

    The corrupt file is *kept* (renamed, not deleted) so it can be
    inspected or salvaged with ``sqlite3 .recover`` later.
    """
    p = Path(db_path)
    if not p.exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    dest = p.with_name(f"{p.name}.corrupt-{stamp}")
    p.rename(dest)
    # Sidecars are only meaningful next to their DB; move them too so a
    # fresh DB doesn't inherit a stale WAL.
    for suffix in ("-wal", "-shm"):
        side = p.with_name(p.name + suffix)
        if side.exists():
            try:
                side.rename(dest.with_name(dest.name + suffix))
            except OSError:
                side.unlink(missing_ok=True)
    return dest


def ensure_healthy_db(
    db_path: str | Path,
    log: Optional[Callable[[str], None]] = None,
) -> bool:
    """Guard a DB before it is opened for work.

    Runs :func:`check_integrity`; if the DB is corrupt, quarantines it via
    :func:`quarantine_db` so the caller's next open creates a clean file.
    Runs on **every** supervisor start — the deep scan is the price of never
    letting a hard-kill-mid-write corruption go undetected (it once looped a
    project for weeks).

    Returns ``True`` when a corrupt DB was quarantined (the caller should
    trigger a full re-index), ``False`` when the DB was already healthy.
    """
    if check_integrity(db_path):
        return False
    dest = quarantine_db(db_path)
    if log is not None:
        log(f"integrity: corrupt DB quarantined → {dest.name if dest else '?'}; "
            f"rebuilding from source")
    return True


# ── Log rotation ─────────────────────────────────────────────────────────

#: Rotate the worker log once it crosses this size. One backup (``.1``) is
#: kept, so worst-case disk use is ~2× this.
DEFAULT_LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB


def rotate_log_if_large(log_path: str | Path,
                        max_bytes: int = DEFAULT_LOG_MAX_BYTES) -> bool:
    """If ``log_path`` exceeds ``max_bytes``, move it to ``<path>.1``
    (overwriting any previous backup). Returns ``True`` if it rotated.

    Best-effort: any OS error is swallowed — logging must never take the
    process down.
    """
    p = Path(log_path)
    try:
        if p.exists() and p.stat().st_size > max_bytes:
            p.replace(p.with_name(p.name + ".1"))
            return True
    except OSError:
        pass
    return False


def make_rotating_logger(
    log_path: str | Path,
    prefix: str = "supervisor",
    max_bytes: int = DEFAULT_LOG_MAX_BYTES,
) -> Callable[[str], None]:
    """Return a ``log(msg)`` that timestamps, rotates when large, and
    appends one line to ``log_path``. Swallows all I/O errors."""
    path = Path(log_path)

    def _log(msg: str) -> None:
        try:
            rotate_log_if_large(path, max_bytes)
            ts = time.strftime("%H:%M:%S")
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {prefix} | {msg}\n")
        except OSError:
            pass

    return _log
