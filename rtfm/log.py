"""Simple file logger for RTFM — writes to .rtfm/rtfm.log.

Usage:
    from rtfm.log import log
    log("search", "query='grammaire musicale' results=5 time=0.03s")

Monitor with:
    tail -f .rtfm/rtfm.log
"""

from __future__ import annotations

import os
import time
from pathlib import Path

_log_file = None


def _get_log_path() -> Path | None:
    """Find the log file path from RTFM_DB env or default."""
    db_path = os.environ.get("RTFM_DB", "")
    if db_path:
        return Path(db_path).parent / "rtfm.log"
    # Fallback: .rtfm/ in cwd
    rtfm_dir = Path(".rtfm")
    if rtfm_dir.exists():
        return rtfm_dir / "rtfm.log"
    return None


def log(category: str, message: str) -> None:
    """Append a timestamped log line to .rtfm/rtfm.log.

    Args:
        category: Short label (hook, search, context, sync, embed, etc.)
        message: Free-form detail string.
    """
    global _log_file
    try:
        if _log_file is None:
            path = _get_log_path()
            if path is None:
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            _log_file = open(path, "a", encoding="utf-8", buffering=1)  # line-buffered

        ts = time.strftime("%H:%M:%S")
        _log_file.write(f"[{ts}] {category:>10} | {message}\n")
    except Exception:
        pass  # Never crash the caller
