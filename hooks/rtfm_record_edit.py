#!/usr/bin/env python3
"""RTFM PostToolUse hook — record file path edited this turn.

Fires on Write / Edit / MultiEdit / NotebookEdit. Appends the target
``file_path`` to ``.rtfm/touched_files.tmp`` so the Stop hook can run a
targeted ``sync(files=[...])`` instead of re-scanning every configured
source on every turn.

Reads the tool-use payload from stdin (per the Claude Code hooks
contract — see https://code.claude.com/docs/en/hooks.md). Silent on any
error: a sync hook must never crash the user's turn.
"""
import json
import os
import sys
from pathlib import Path


def main() -> None:
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    if not proj:
        return

    rtfm_dir = Path(proj) / ".rtfm"
    if not rtfm_dir.exists():
        return

    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return

    tool_input = payload.get("tool_input") or {}
    # Write / Edit / MultiEdit use "file_path". NotebookEdit uses
    # "notebook_path". Take whichever is present.
    fp = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not fp:
        return

    try:
        with open(rtfm_dir / "touched_files.tmp", "a", encoding="utf-8") as f:
            f.write(fp.rstrip("\n") + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()
