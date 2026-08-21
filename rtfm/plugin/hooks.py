"""Claude Code hooks for RTFM.

Design (0.16.0+): the hooks are deliberately *lightweight*. All heavy
work — scanning sources, ingesting, embedding, OCR — is done by the single
background worker daemon, which scans non-destructively on an idle timer.
The hooks never run a full ``sync()`` (that re-MD5s the whole corpus on
every prompt — slow on NTFS-via-WSL — and, worse, could delete files that
a momentarily-incomplete scan failed to see). Instead:

  - UserPromptSubmit / Stop  → just ensure the worker is alive.
  - PostToolUse (Write/Edit)  → enqueue the one file the agent just wrote
                                as a P_USER ingest job. Non-destructive:
                                only ever ADDS work, never scans/removes.

Design (0.28.0+): the scripts written into a project are **stubs**. All the
logic lives in :mod:`rtfm.plugin.hook_runtime`, which ships with the
installed package, so a fix reaches every project through ``pipx upgrade``
instead of requiring a re-``init``. The heartbeat hook additionally
rewrites its sibling stubs whenever the package ships newer ones, so
projects initialised on an older version self-heal on the next prompt.
"""

from __future__ import annotations

import json
from pathlib import Path


#: Bumped whenever a stub's *body* changes, so the self-heal in
#: ``refresh_hook_scripts`` can tell an outdated stub from a current one.
HOOK_STUB_VERSION = 1

_STUB_HEADER = '''#!/usr/bin/env python3
"""RTFM {event} hook — stub. Logic lives in rtfm.plugin.hook_runtime.

Do not edit: rewritten automatically when the installed rtfm-ai package
ships a newer version (rtfm.plugin.hooks.HOOK_STUB_VERSION={version}).
"""
import os, sys
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
'''


# ── Worker heartbeat (UserPromptSubmit + Stop) ───────────────────────────
# Both events run the same tiny script: revive the background worker if it
# died, and refresh the hook stubs. No scan, no MD5, no DB writes on the
# user's hot path. Discovery of new/changed files is the worker's job.

HOOK_SCRIPT = _STUB_HEADER.format(event="UserPromptSubmit/Stop",
                                  version=HOOK_STUB_VERSION) + '''

try:
    from rtfm.plugin.hook_runtime import heartbeat
    heartbeat(PROJECT_ROOT)
except Exception:
    pass
'''


# The Stop hook is identical to the prompt hook: at session end, make sure
# the worker is alive so it drains anything the PostToolUse hook enqueued
# and idle-scans for anything missed. No full sync.
STOP_SYNC_SCRIPT = HOOK_SCRIPT


# ── File enqueue (PostToolUse: Write|Edit|MultiEdit) ─────────────────────
# Fires right after the agent writes a file. Maps that one file to its
# configured source/corpus and enqueues a single P_USER ingest job for the
# worker. This is the only place a hook touches the index directly, and it
# only ever adds work for the file that just changed — never scans, never
# deletes, never touches unrelated files.

POSTTOOL_HOOK_SCRIPT = _STUB_HEADER.format(event="PostToolUse",
                                           version=HOOK_STUB_VERSION) + \
"""

try:
    from rtfm.plugin.hook_runtime import on_file_edited, read_payload
    on_file_edited(PROJECT_ROOT, read_payload(sys.stdin))
except Exception:
    pass
"""


MEMORY_HOOK_SCRIPT = r'''#!/usr/bin/env python3
"""RTFM global memory hook — versioned snapshot of Claude memory files on session stop.

Runs after every Claude Code session. Discovers ~/.claude/projects/*/memory/
and re-syncs into ~/.rtfm/memory.db with unlimited version history (no prune).

Fast: only the project whose memory just changed actually re-indexes.
"""
import sys, time
from pathlib import Path

def main():
    db_path = Path.home() / ".rtfm" / "memory.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    projects_root = Path.home() / ".claude" / "projects"
    if not projects_root.exists():
        return

    memory_dirs = sorted(p for p in projects_root.glob("*/memory") if p.is_dir())
    if not memory_dirs:
        return

    try:
        from rtfm.core.library import Library
        from rtfm.core.sync import sync

        lib = Library(str(db_path))
        for mem_dir in memory_dirs:
            project_slug = mem_dir.parent.name.strip("-") or "root"
            corpus = f"claude-memory/{project_slug}"
            sync(
                library=lib,
                root=mem_dir,
                corpus=corpus,
                extensions={".md", ".txt"},
                generate_embeddings=False,
                retain_history=None,
            )
        lib.close()
    except Exception:
        pass  # silent — hook is best-effort


if __name__ == "__main__":
    main()
'''


def install_memory_hook() -> str:
    """Install a global SessionStop hook that snapshots Claude memory files.

    Writes the hook script to ~/.claude/hooks/rtfm_memory_sync.py and
    registers it under ~/.claude/settings.json Stop event.

    Returns:
        "installed" on success.
    """
    import sys

    home = Path.home()
    claude_dir = home / ".claude"
    hooks_dir = claude_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    hook_path = hooks_dir / "rtfm_memory_sync.py"
    hook_path.write_text(MEMORY_HOOK_SCRIPT, encoding="utf-8")

    settings_path = claude_dir / "settings.json"
    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            settings = {}

    hooks = settings.get("hooks", {})

    # Strip any previous RTFM memory hook from every event (we may have
    # previously registered under "Stop"; we now use "SessionEnd").
    for evt in list(hooks.keys()):
        hooks[evt] = [
            h for h in hooks[evt]
            if not any("rtfm_memory_sync" in sub.get("command", "")
                       for sub in h.get("hooks", []))
        ]
        if not hooks[evt]:
            del hooks[evt]

    session_end = hooks.get("SessionEnd", [])
    session_end.append({
        "hooks": [{
            "type": "command",
            "command": f"{sys.executable} {hook_path}",
            "timeout": 30,
        }],
    })
    hooks["SessionEnd"] = session_end
    settings["hooks"] = hooks

    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return "installed"


#: Stub file name → its content, for the self-heal pass.
_PROJECT_STUBS = {
    "rtfm_sync.py": lambda: HOOK_SCRIPT,
    "rtfm_stop_sync.py": lambda: STOP_SYNC_SCRIPT,
    "rtfm_posttool_sync.py": lambda: POSTTOOL_HOOK_SCRIPT,
}


def refresh_hook_scripts(project_root: str | Path) -> list[str]:
    """Rewrite this project's hook stubs when the package ships newer ones.

    Called from the heartbeat hook, so a project initialised on an older
    RTFM picks up hook fixes on its next prompt instead of silently running
    stale logic until someone re-runs ``rtfm init``. Only rewrites files
    RTFM installed itself, only when the content actually differs, and
    never registers anything in ``settings.json`` (that stays ``init``'s
    job). Returns the names rewritten.
    """
    hooks_dir = Path(project_root) / ".claude" / "hooks"
    if not hooks_dir.is_dir():
        return []
    updated = []
    for name, body in _PROJECT_STUBS.items():
        path = hooks_dir / name
        if not path.exists():
            continue  # not installed here — installing is init's decision
        wanted = body()
        try:
            if path.read_text(encoding="utf-8") == wanted:
                continue
            path.write_text(wanted, encoding="utf-8")
        except OSError:
            continue
        updated.append(name)
    return updated


def install_hook(project_root: str | Path, corpus: str = "default") -> str:
    """Install Claude Code hooks for RTFM.

    Hooks installed (all lightweight — the background worker does the work):
    1. UserPromptSubmit → rtfm_sync.py        (revive worker if dead)
    2. Stop             → rtfm_stop_sync.py   (revive worker to drain/scan)
    3. PostToolUse      → rtfm_posttool_sync.py (enqueue the just-written
                          file as a P1 ingest, on Write|Edit|MultiEdit)

    Also writes .rtfm/config.json with the corpus setting.

    Args:
        project_root: Project root directory.
        corpus: Corpus name to use for auto-sync.

    Returns:
        One of "installed", "skipped" (if already present).
    """
    import sys

    project_root = Path(project_root)
    claude_dir = project_root / ".claude"
    hooks_dir = claude_dir / "hooks"

    # Write hook scripts
    hooks_dir.mkdir(parents=True, exist_ok=True)

    sync_path = hooks_dir / "rtfm_sync.py"
    sync_path.write_text(HOOK_SCRIPT, encoding="utf-8")

    stop_sync_path = hooks_dir / "rtfm_stop_sync.py"
    stop_sync_path.write_text(STOP_SYNC_SCRIPT, encoding="utf-8")

    posttool_path = hooks_dir / "rtfm_posttool_sync.py"
    posttool_path.write_text(POSTTOOL_HOOK_SCRIPT, encoding="utf-8")

    # Clean up old hook scripts
    for old in ["rtfm_remember_reminder.py", "rtfm_remember_stamp.py"]:
        old_path = hooks_dir / old
        if old_path.exists():
            old_path.unlink()

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
    python = sys.executable

    def _clean_hooks(hook_list):
        """Remove all RTFM hooks from a hook list."""
        cleaned = []
        for existing in hook_list:
            cmd = existing.get("command", "")
            if cmd and "rtfm" in cmd:
                continue
            inner = existing.get("hooks", [])
            if any("rtfm" in h.get("command", "") for h in inner):
                continue
            cleaned.append(existing)
        return cleaned

    # Hook paths must be resolvable regardless of the agent's current working
    # directory. Relative paths break when Claude Code runs from a subdirectory.
    # $CLAUDE_PROJECT_DIR always resolves to the project root at runtime.
    sync_rel = sync_path.relative_to(project_root).as_posix()
    stop_sync_rel = stop_sync_path.relative_to(project_root).as_posix()
    posttool_rel = posttool_path.relative_to(project_root).as_posix()

    # 1. UserPromptSubmit → revive worker (no sync).
    ups = _clean_hooks(hooks.get("UserPromptSubmit", []))
    ups.append({
        "hooks": [{
            "type": "command",
            "command": f'{python} "$CLAUDE_PROJECT_DIR"/{sync_rel}',
            "timeout": 10,
        }],
    })
    hooks["UserPromptSubmit"] = ups

    # 2. Stop → revive worker to drain/scan after the session.
    stop = _clean_hooks(hooks.get("Stop", []))
    stop.append({
        "hooks": [{
            "type": "command",
            "command": f'{python} "$CLAUDE_PROJECT_DIR"/{stop_sync_rel}',
            "timeout": 10,
        }],
    })
    hooks["Stop"] = stop

    # 3. PostToolUse → enqueue the just-written file (Write|Edit|MultiEdit).
    ptu = _clean_hooks(hooks.get("PostToolUse", []))
    ptu.append({
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [{
            "type": "command",
            "command": f'{python} "$CLAUDE_PROJECT_DIR"/{posttool_rel}',
            "timeout": 10,
        }],
    })
    hooks["PostToolUse"] = ptu

    # Clean up old hooks that are no longer needed
    for old_event in ["SessionStart"]:
        if old_event in hooks:
            cleaned = _clean_hooks(hooks[old_event])
            if cleaned:
                hooks[old_event] = cleaned
            else:
                del hooks[old_event]

    settings["hooks"] = hooks
    settings_path.write_text(
        json.dumps(settings, indent=2) + "\n",
        encoding="utf-8",
    )

    return "installed"
