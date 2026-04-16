#!/usr/bin/env python3
"""RTFM plugin bootstrap — runs at SessionStart.

Pure Python, no pip. Initializes the current project (.rtfm/library.db,
CLAUDE.md injection) using the rtfm code bundled in the plugin directory.
Idempotent: safe to run on every SessionStart.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


# Resolve the plugin root so we can import bundled rtfm code without pip.
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))


def _log(msg: str, project_root: Path | None = None) -> None:
    """Append to .rtfm/rtfm.log if project root is known, else stderr."""
    try:
        ts = time.strftime("%H:%M:%S")
        if project_root and (project_root / ".rtfm").exists():
            log_path = project_root / ".rtfm" / "rtfm.log"
            with open(log_path, "a") as f:
                f.write(f"[{ts}]  bootstrap | {msg}\n")
        else:
            sys.stderr.write(f"[rtfm-bootstrap {ts}] {msg}\n")
    except Exception:
        pass


def _python_version_ok() -> bool:
    return sys.version_info >= (3, 10)


def _init_project(project_root: Path) -> bool:
    """Initialize .rtfm/ in the current project. Skips MCP and hook
    registration — those are provided by the plugin itself."""
    try:
        from rtfm.core.library import Library
        from rtfm.core.sync import sync
        from rtfm.plugin.claude_md import inject_claude_md

        rtfm_dir = project_root / ".rtfm"
        rtfm_dir.mkdir(parents=True, exist_ok=True)

        db_path = rtfm_dir / "library.db"
        config_path = rtfm_dir / "config.json"
        if not config_path.exists():
            config_path.write_text(
                json.dumps({"corpus": "default"}, indent=2) + "\n",
                encoding="utf-8",
            )

        lib = Library(str(db_path))
        sync(
            library=lib,
            root=project_root,
            corpus="default",
            generate_embeddings=False,
        )
        lib.close()

        try:
            inject_claude_md(project_root)
        except Exception:
            pass

        return True
    except Exception as e:
        _log(f"init ERROR: {e}", project_root)
        return False


def _grant_mcp_permissions(project_root: Path) -> None:
    """Pre-approve RTFM MCP tool calls in project settings so the user isn't
    prompted on every search/expand. Writes to .claude/settings.local.json
    (gitignored by default). Idempotent."""
    try:
        settings_path = project_root / ".claude" / "settings.local.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings: dict = {}
        if settings_path.exists():
            try:
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
            except Exception:
                settings = {}
        permissions = settings.get("permissions", {})
        allow = list(permissions.get("allow", []))
        rules = [
            "mcp__rtfm",
            "mcp__rtfm__*",
            "mcp__plugin_rtfm_rtfm",
            "mcp__plugin_rtfm_rtfm__*",
        ]
        changed = False
        for rule in rules:
            if rule not in allow:
                allow.append(rule)
                changed = True
        if changed:
            permissions["allow"] = allow
            settings["permissions"] = permissions
            settings_path.write_text(
                json.dumps(settings, indent=2) + "\n",
                encoding="utf-8",
            )
            _log("granted auto-allow for RTFM MCP tools", project_root)
    except Exception as e:
        _log(f"permission grant ERROR: {e}", project_root)


def main() -> None:
    project_root_env = os.environ.get("CLAUDE_PROJECT_DIR")
    if not project_root_env:
        return
    project_root = Path(project_root_env).resolve()

    if not _python_version_ok():
        _log(
            f"Python {sys.version_info.major}.{sys.version_info.minor} is too old, need 3.10+",
            project_root,
        )
        return

    db_path = project_root / ".rtfm" / "library.db"
    if not db_path.exists():
        _log("initializing project", project_root)
        if _init_project(project_root):
            _log("project initialized", project_root)
        else:
            _log("init failed", project_root)

    _grant_mcp_permissions(project_root)


if __name__ == "__main__":
    main()
