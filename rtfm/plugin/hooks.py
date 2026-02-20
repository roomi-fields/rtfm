"""Claude Code hooks for RTFM — auto-sync on prompt submit."""

from __future__ import annotations

import json
from pathlib import Path

HOOK_SCRIPT = r'''#!/usr/bin/env python3
"""RTFM UserPromptSubmit hook — fast incremental FTS sync.

Runs on every prompt:
1. Reads corpus from .rtfm/config.json (set during init)
2. Quick incremental sync (FTS only, no embeddings) — typically <2s
3. Embeddings are handled by the MCP server in background (model stays loaded)
"""
import json, os, sys, time
from pathlib import Path

STALE_SECONDS = 30  # Re-sync at most every 30 seconds

def main():
    rtfm_dir = Path(".rtfm")
    if not rtfm_dir.exists():
        return

    db_path = rtfm_dir / "library.db"
    if not db_path.exists():
        return

    # Throttle: don't sync more than once every STALE_SECONDS
    stamp_file = rtfm_dir / ".sync_ts"
    now = time.time()
    if stamp_file.exists():
        try:
            last = float(stamp_file.read_text().strip())
            if now - last < STALE_SECONDS:
                return
        except (ValueError, OSError):
            pass

    # Read corpus from config
    corpus = "default"
    config_path = rtfm_dir / "config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text())
            corpus = cfg.get("corpus", "default")
        except Exception:
            pass

    # Quick incremental sync (no embeddings — fast)
    try:
        from rtfm.core.library import Library
        from rtfm.core.sync import sync

        lib = Library(str(db_path))
        sync(
            library=lib,
            root=Path(".").resolve(),
            corpus=corpus,
            generate_embeddings=False,
        )
        lib.close()
        stamp_file.write_text(str(now))
    except Exception:
        pass  # Never block the user's prompt


if __name__ == "__main__":
    main()
'''


def install_hook(project_root: str | Path, corpus: str = "default") -> str:
    """Install a Claude Code UserPromptSubmit hook for RTFM.

    Writes the hook script to .claude/hooks/rtfm_sync.py and
    registers it in .claude/settings.json.

    Also writes .rtfm/config.json with the corpus setting so the hook
    knows which corpus to sync.

    Args:
        project_root: Project root directory.
        corpus: Corpus name to use for auto-sync.

    Returns:
        One of "installed", "skipped" (if already present).
    """
    project_root = Path(project_root)
    claude_dir = project_root / ".claude"
    hooks_dir = claude_dir / "hooks"

    # Write hook script
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "rtfm_sync.py"
    hook_path.write_text(HOOK_SCRIPT, encoding="utf-8")

    # Write config with corpus
    rtfm_dir = project_root / ".rtfm"
    rtfm_dir.mkdir(parents=True, exist_ok=True)
    config_path = rtfm_dir / "config.json"
    config = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    config["corpus"] = corpus
    config_path.write_text(
        json.dumps(config, indent=2) + "\n",
        encoding="utf-8",
    )

    # Register in settings.json
    settings_path = claude_dir / "settings.json"
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    else:
        settings = {}

    hooks = settings.get("hooks", {})
    user_prompt_hooks = hooks.get("UserPromptSubmit", [])

    # Clean up old hooks (both old and new format)
    hook_cmd = f"python {hook_path.relative_to(project_root)}"
    cleaned = []
    for existing in user_prompt_hooks:
        # Old format: {"command": "..."}
        cmd = existing.get("command", "")
        if cmd and ("rtfm_discover" in cmd or "rtfm_sync" in cmd):
            continue
        # New format: {"matcher": {}, "hooks": [...]}
        inner_hooks = existing.get("hooks", [])
        if any("rtfm_sync" in h.get("command", "") for h in inner_hooks):
            continue
        cleaned.append(existing)

    # New Claude Code hook format with matcher
    cleaned.append({
        "matcher": {},
        "hooks": [
            {
                "type": "command",
                "command": hook_cmd,
                "timeout": 10000,
            }
        ],
    })

    hooks["UserPromptSubmit"] = cleaned
    settings["hooks"] = hooks

    settings_path.write_text(
        json.dumps(settings, indent=2) + "\n",
        encoding="utf-8",
    )

    return "installed"
