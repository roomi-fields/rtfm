#!/usr/bin/env python3
"""RTFM UserPromptSubmit hook — catch-up sync for orphan touched files.

The new (0.9.4+) design records every Write / Edit / MultiEdit /
NotebookEdit target into ``.rtfm/touched_files.tmp`` via the
PostToolUse hook, and the Stop hook drains that queue at end-of-turn.

If a previous session was abandoned (closed window, crash, ...) before
its Stop hook ran, ``touched_files.tmp`` survives across sessions.
This hook is the safety net: at the start of the next user prompt,
delegate to the Stop hook's drain logic so those orphan files don't
sit unindexed.

Crucially: no full source scan. Only drains the queue if any. Empty
queue → instant no-op (sub-millisecond).
"""
import os
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))


def main() -> None:
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    if not proj:
        return
    tmp = Path(proj) / ".rtfm" / "touched_files.tmp"
    if not tmp.exists() or tmp.stat().st_size == 0:
        return
    # Delegate to the Stop-hook drain — same code path, same semantics.
    try:
        import importlib
        mod = importlib.import_module("hooks.rtfm_stop_sync")
        mod.main()
    except Exception:
        # Last resort: try direct script
        try:
            stop_script = _PLUGIN_ROOT / "hooks" / "rtfm_stop_sync.py"
            if stop_script.exists():
                import runpy
                runpy.run_path(str(stop_script), run_name="__main__")
        except Exception:
            pass


if __name__ == "__main__":
    main()
