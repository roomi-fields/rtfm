"""Claude Code hooks for RTFM.

Design (0.16.0+): the hooks are deliberately *lightweight*. All heavy
work — scanning sources, ingesting, embedding, OCR — is done by the single
background worker daemon, which scans non-destructively on an idle timer.
The hooks never run a full ``sync()`` (that re-MD5s the whole corpus on
every prompt — slow on NTFS-via-WSL — and, worse, could delete files that
a momentarily-incomplete scan failed to see). Instead:

  - UserPromptSubmit / Stop  → just ensure the worker is alive.
  - PostToolUse (Write/Edit)  → enqueue the one file the agent just wrote
                                as a P1 ingest job. Non-destructive: only
                                ever ADDS work, never scans or removes.
"""

from __future__ import annotations

import json
from pathlib import Path


# ── Worker heartbeat (UserPromptSubmit + Stop) ───────────────────────────
# Both events run the same tiny script: revive the background worker if it
# died. No scan, no MD5, no DB writes on the user's hot path. Discovery of
# new/changed files is the worker's job (idle-scan, non-destructive).

HOOK_SCRIPT = r'''#!/usr/bin/env python3
"""RTFM UserPromptSubmit hook — keep the background worker alive.

No sync here. The single background worker handles discovery (idle-scan),
ingestion, embeddings and OCR. This hook only revives that worker if it
died, so a new session brings the pipeline back. Cheap by design: no
filesystem scan, no hashing, nothing on the user's hot path.
"""
import os, time
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])


def _log(msg):
    try:
        ts = time.strftime("%H:%M:%S")
        with open(PROJECT_ROOT / ".rtfm" / "rtfm.log", "a") as f:
            f.write(f"[{ts}]       hook | {msg}\n")
    except Exception:
        pass


def main():
    rtfm_dir = PROJECT_ROOT / ".rtfm"
    if not (rtfm_dir / "library.db").exists():
        return
    try:
        from rtfm.cli_worker import ensure_worker_running
        pid = ensure_worker_running(rtfm_dir)
        if pid:
            _log(f"worker alive pid={pid}")
    except Exception as e:
        _log(f"worker ensure ERROR: {e}")


if __name__ == "__main__":
    main()
'''


# The Stop hook is identical to the prompt hook: at session end, make sure
# the worker is alive so it drains anything the PostToolUse hook enqueued
# and idle-scans for anything missed. No full sync.
STOP_SYNC_SCRIPT = HOOK_SCRIPT


# ── File enqueue (PostToolUse: Write|Edit|MultiEdit) ─────────────────────
# Fires right after the agent writes a file. Maps that one file to its
# configured source/corpus and enqueues a single P1 ingest job for the
# worker. This is the only place a hook touches the index directly, and it
# only ever adds work for the file that just changed — never scans, never
# deletes, never touches unrelated files.

POSTTOOL_HOOK_SCRIPT = r'''#!/usr/bin/env python3
"""RTFM PostToolUse hook — enqueue the just-written file for ingestion.

Reads the edited file path from the hook payload (stdin JSON), maps it to a
configured source (corpus + root), and enqueues ONE P1 ingest job. The
worker does the actual parse/index. Non-destructive: only ever adds a job.
"""
import json, os, sys, time
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])


def _log(msg):
    try:
        ts = time.strftime("%H:%M:%S")
        with open(PROJECT_ROOT / ".rtfm" / "rtfm.log", "a") as f:
            f.write(f"[{ts}]       hook | {msg}\n")
    except Exception:
        pass


def _edited_path(payload):
    ti = payload.get("tool_input") or {}
    p = ti.get("file_path") or ti.get("path") or ti.get("notebook_path")
    if not p:
        return None
    try:
        return Path(p).resolve()
    except Exception:
        return None


def main():
    rtfm_dir = PROJECT_ROOT / ".rtfm"
    db_path = rtfm_dir / "library.db"
    if not db_path.exists():
        return

    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    fpath = _edited_path(payload)
    if not fpath or not fpath.is_file():
        return

    # Only enqueue files RTFM can actually parse.
    try:
        from rtfm.parsers.base import ParserRegistry
        import rtfm.parsers  # noqa: F401 — register all parsers
        if ParserRegistry.get_parser(fpath) is None:
            return
    except Exception:
        return

    cfg = {}
    cfg_path = rtfm_dir / "config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
        except Exception:
            pass
    sources = cfg.get("sources") or [
        {"path": str(PROJECT_ROOT), "corpus": cfg.get("corpus", "default")}]

    # Pick the most specific (deepest-rooted) source that contains the file
    # and whose extension filter (if any) admits it.
    best = None  # (root, corpus, depth)
    for src in sources:
        try:
            root = Path(src.get("path", ".")).resolve()
        except Exception:
            continue
        try:
            fpath.relative_to(root)
        except ValueError:
            continue
        exts = src.get("extensions")
        if exts:
            allowed = {e.strip().lower() if e.strip().startswith(".")
                       else f".{e.strip().lower()}" for e in exts.split(",")}
            if fpath.suffix.lower() not in allowed:
                continue
        depth = len(root.parts)
        if best is None or depth > best[2]:
            best = (root, src.get("corpus", cfg.get("corpus", "default")), depth)

    if best is None:
        return
    root, corpus, _ = best
    rel = str(fpath.relative_to(root))

    try:
        from rtfm.core.queue import Queue
        from rtfm.cli_worker import ensure_worker_running
        q = Queue(str(db_path))
        try:
            q.enqueue("ingest", {"root": str(root), "corpus": corpus,
                                 "filepath": rel})
        finally:
            q.close()
        ensure_worker_running(rtfm_dir)
        _log(f"enqueued ingest [{corpus}] {rel}")
    except Exception as e:
        _log(f"enqueue ERROR: {e}")


if __name__ == "__main__":
    main()
'''


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
