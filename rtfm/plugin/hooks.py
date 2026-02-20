"""Claude Code hooks for RTFM — auto-refresh discover on prompt submit."""

from __future__ import annotations

import json
from pathlib import Path

HOOK_SCRIPT = """#!/usr/bin/env python3
\"\"\"RTFM UserPromptSubmit hook — refreshes project map if stale.\"\"\"
import json, os, sys, time
from pathlib import Path

STALE_SECONDS = 300  # 5 minutes

def main():
    rtfm_dir = Path(".rtfm")
    stamp_file = rtfm_dir / ".discover_ts"

    if not rtfm_dir.exists():
        return

    now = time.time()
    if stamp_file.exists():
        last = float(stamp_file.read_text().strip())
        if now - last < STALE_SECONDS:
            return

    # Refresh discover
    try:
        from rtfm.plugin.discover import discover
        discover(".")
        stamp_file.write_text(str(now))
    except Exception:
        pass  # Non-blocking — never fail the user's prompt

if __name__ == "__main__":
    main()
"""


def install_hook(project_root: str | Path) -> str:
    """Install a Claude Code UserPromptSubmit hook for RTFM.

    Writes the hook script to .claude/hooks/rtfm_discover.py and
    registers it in .claude/settings.json.

    Args:
        project_root: Project root directory.

    Returns:
        One of "installed", "skipped" (if already present), or "no_claude_dir".
    """
    project_root = Path(project_root)
    claude_dir = project_root / ".claude"
    hooks_dir = claude_dir / "hooks"

    # Write hook script
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "rtfm_discover.py"
    hook_path.write_text(HOOK_SCRIPT, encoding="utf-8")

    # Register in settings.json
    settings_path = claude_dir / "settings.json"
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    else:
        settings = {}

    hooks = settings.get("hooks", {})
    user_prompt_hooks = hooks.get("UserPromptSubmit", [])

    # Check if already registered
    hook_cmd = f"python {hook_path.relative_to(project_root)}"
    for existing in user_prompt_hooks:
        if "rtfm_discover" in existing.get("command", ""):
            return "skipped"

    user_prompt_hooks.append({
        "command": hook_cmd,
        "timeout": 5000,
    })

    hooks["UserPromptSubmit"] = user_prompt_hooks
    settings["hooks"] = hooks

    settings_path.write_text(
        json.dumps(settings, indent=2) + "\n",
        encoding="utf-8",
    )

    return "installed"
