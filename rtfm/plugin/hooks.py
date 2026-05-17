"""Claude Code hooks for RTFM — auto-sync on prompt + final sync on stop."""

from __future__ import annotations

import json
from pathlib import Path


# ── Final sync (Stop hook) ───────────────────────────────────────────────

STOP_SYNC_SCRIPT = r'''#!/usr/bin/env python3
"""RTFM Stop hook — final sync to catch files created/modified this turn.

The UserPromptSubmit hook syncs every 30s, but the last Write/Edit may
happen right before the agent stops. This hook runs a final sync to
ensure everything is indexed.
"""
import json, os, sys, time
from pathlib import Path

# Resolve project root from $CLAUDE_PROJECT_DIR so the hook works regardless
# of the agent's current working directory.
PROJECT_ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])

def _log(msg):
    try:
        ts = time.strftime("%H:%M:%S")
        log_path = PROJECT_ROOT / ".rtfm" / "rtfm.log"
        with open(log_path, "a") as f:
            f.write(f"[{ts}]       hook | {msg}\n")
    except Exception:
        pass

def main():
    rtfm_dir = PROJECT_ROOT / ".rtfm"
    if not rtfm_dir.exists():
        return

    db_path = rtfm_dir / "library.db"
    if not db_path.exists():
        return

    # Read sources from config
    config_path = rtfm_dir / "config.json"
    sources = []
    default_corpus = "default"
    ocr_fallback = False
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text())
            sources = cfg.get("sources", [])
            default_corpus = cfg.get("corpus", "default")
            ocr_fallback = cfg.get("ocr_fallback", False)
        except Exception:
            pass

    if not sources:
        sources = [{"path": str(PROJECT_ROOT), "corpus": default_corpus}]

    _log(f"stop-sync starting {len(sources)} source(s)")
    t0 = time.time()
    try:
        from rtfm.core.library import Library
        from rtfm.core.sync import sync

        lib = Library(str(db_path))
        total_added = total_modified = 0
        for src in sources:
            src_path = Path(src.get("path", ".")).resolve()
            src_corpus = src.get("corpus", default_corpus)
            ext_set = None
            if src.get("extensions"):
                ext_set = {e.strip() if e.strip().startswith(".") else f".{e.strip()}"
                           for e in src["extensions"].split(",")}
            result = sync(
                library=lib,
                root=src_path,
                corpus=src_corpus,
                extensions=ext_set,
                generate_embeddings=False,
                ocr_fallback=ocr_fallback,
            )
            total_added += result.added
            total_modified += result.modified
        lib.close()
        elapsed = time.time() - t0
        _log(f"stop-sync done +{total_added} ~{total_modified} time={elapsed:.2f}s")
    except Exception as e:
        _log(f"stop-sync ERROR: {e}")


if __name__ == "__main__":
    main()
'''


# ── Sync hook (UserPromptSubmit) ─────────────────────────────────────────

HOOK_SCRIPT = r'''#!/usr/bin/env python3
"""RTFM UserPromptSubmit hook — fast incremental FTS sync.

Runs on every prompt:
1. Reads corpus from .rtfm/config.json (set during init)
2. Dry-run diff first: if a lot of new files are detected, announce it
3. Quick incremental sync (FTS only, no embeddings) — typically <2s
4. After sync, surface result + any health warnings (PDF scans, ...)
5. Embeddings are handled by the MCP server in background

Anything printed to stdout is injected into the agent's context for the
current turn, so the agent will mention it to the user when relevant.
"""
import json, os, sys, time
from pathlib import Path

STALE_SECONDS = 30          # Re-sync at most every 30 seconds
ANNOUNCE_THRESHOLD = 50     # Pre-sync announce if > N files to index

# Resolve project root from $CLAUDE_PROJECT_DIR so the hook works regardless
# of the agent's current working directory.
PROJECT_ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])

def _log(msg):
    """Append to .rtfm/rtfm.log (inline, no imports)."""
    try:
        ts = time.strftime("%H:%M:%S")
        log_path = PROJECT_ROOT / ".rtfm" / "rtfm.log"
        with open(log_path, "a") as f:
            f.write(f"[{ts}]       hook | {msg}\n")
    except Exception:
        pass


def _load_seen_scans(rtfm_dir):
    """Scans already signalled to the agent during this project's lifetime.

    Stored as a JSON list so the hook doesn't repeat the same warning on
    every single turn. User can reset it by deleting .rtfm/seen_scans.json.
    """
    p = rtfm_dir / "seen_scans.json"
    if not p.exists():
        return set()
    try:
        return set(json.loads(p.read_text()))
    except Exception:
        return set()


def _save_seen_scans(rtfm_dir, seen):
    try:
        (rtfm_dir / "seen_scans.json").write_text(json.dumps(sorted(seen)))
    except Exception:
        pass


def main():
    rtfm_dir = PROJECT_ROOT / ".rtfm"
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
                _log(f"throttled (last sync {now - last:.0f}s ago)")
                return
        except (ValueError, OSError):
            pass

    # Read sources from config
    config_path = rtfm_dir / "config.json"
    sources = []
    default_corpus = "default"
    ocr_fallback = False
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text())
            sources = cfg.get("sources", [])
            default_corpus = cfg.get("corpus", "default")
            ocr_fallback = cfg.get("ocr_fallback", False)
        except Exception:
            pass

    # Fallback: no sources configured, sync project root with default corpus
    if not sources:
        sources = [{"path": str(PROJECT_ROOT), "corpus": default_corpus}]

    _log(f"sync starting {len(sources)} source(s)")
    t0 = time.time()
    try:
        from rtfm.core.library import Library
        from rtfm.core.sync import sync, quick_diff

        lib = Library(str(db_path))

        # 1. Quick path/size diff to count what's likely new or changed.
        #    Hash-free, but still stat()s every tracked file — which on
        #    NTFS-via-WSL or network shares can be tens of seconds per
        #    source. We bound the *total* preview time so the hook never
        #    blocks the user's prompt waiting on remote storage: if the
        #    budget is exhausted, we just skip the pre-sync announcement.
        PRE_BUDGET = 2.0
        pre_start = time.time()
        pending_total = 0
        announce_ready = True
        for src in sources:
            if time.time() - pre_start > PRE_BUDGET:
                announce_ready = False
                _log("pre-scan budget exceeded, skipping announcement")
                break
            src_path = Path(src.get("path", ".")).resolve()
            src_corpus = src.get("corpus", default_corpus)
            ext_set = None
            if src.get("extensions"):
                ext_set = {e.strip() if e.strip().startswith(".") else f".{e.strip()}"
                           for e in src["extensions"].split(",")}
            try:
                qd = quick_diff(
                    library=lib,
                    root=src_path,
                    corpus=src_corpus,
                    extensions=ext_set,
                )
                pending_total += len(qd.added) + len(qd.modified)
            except Exception:
                pass

        if announce_ready and pending_total >= ANNOUNCE_THRESHOLD:
            print(f"→ RTFM: indexing {pending_total} new/modified file(s)...",
                  flush=True)

        # 2. Real sync
        total_added = total_modified = total_removed = 0
        all_scans = []
        all_empty = []
        all_errors = []
        for src in sources:
            src_path = Path(src.get("path", ".")).resolve()
            src_corpus = src.get("corpus", default_corpus)
            ext_set = None
            if src.get("extensions"):
                ext_set = {e.strip() if e.strip().startswith(".") else f".{e.strip()}"
                           for e in src["extensions"].split(",")}
            result = sync(
                library=lib,
                root=src_path,
                corpus=src_corpus,
                extensions=ext_set,
                generate_embeddings=False,
                ocr_fallback=ocr_fallback,
            )
            total_added += result.added
            total_modified += result.modified
            total_removed += result.removed
            all_scans.extend(result.suspect_scans)
            all_empty.extend(result.empty_files)
            all_errors.extend(result.errors)

        lib.close()
        stamp_file.write_text(str(now))
        elapsed = time.time() - t0
        _log(f"sync done +{total_added} ~{total_modified} -{total_removed} "
             f"scans={len(all_scans)} empty={len(all_empty)} "
             f"time={elapsed:.2f}s ({len(sources)} sources)")

        # 3. Post-sync notifications (stdout = injected into agent context)
        had_changes = total_added or total_modified or total_removed
        if had_changes:
            parts = []
            if total_added:    parts.append(f"+{total_added}")
            if total_modified: parts.append(f"~{total_modified}")
            if total_removed:  parts.append(f"-{total_removed}")
            print(f"✓ RTFM sync: {' '.join(parts)} files ({elapsed:.1f}s)",
                  flush=True)

        # 4. Surface new suspect scans only — anti-spam: skip ones already
        #    reported in a previous turn for this project.
        if all_scans:
            seen = _load_seen_scans(rtfm_dir)
            fresh = [s for s in all_scans if s not in seen]
            if fresh:
                n = len(fresh)
                preview = ", ".join(fresh[:3])
                if n > 3:
                    preview += f", +{n - 3} more"
                print("")
                print("=" * 60, flush=True)
                print("ACTION REQUIRED — surface to the user verbatim:",
                      flush=True)
                print("=" * 60, flush=True)
                print(f"TRIGGER: {n} PDF file(s) extracted 0 text during "
                      "auto-sync — likely scanned images.", flush=True)
                print(f"FILES:   {preview}", flush=True)
                print(f"SAY TO USER: \"RTFM detected {n} PDF(s) that look "
                      "like scans (no extractable text). Want me to "
                      "enable OCR? You only run this command once — "
                      "future syncs will OCR new scans automatically.\"",
                      flush=True)
                print("EXACT COMMAND TO PROPOSE: rtfm sync --ocr",
                      flush=True)
                print("ON APPROVAL RUN: rtfm sync --ocr", flush=True)
                seen.update(fresh)
                _save_seen_scans(rtfm_dir, seen)
    except Exception as e:
        _log(f"sync ERROR: {e}")


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

    Hooks installed:
    1. UserPromptSubmit → rtfm_sync.py (incremental sync every 30s)
    2. Stop → rtfm_stop_sync.py (final sync to catch last writes)

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

    # 1. UserPromptSubmit → incremental sync (throttled every 30s)
    ups = _clean_hooks(hooks.get("UserPromptSubmit", []))
    ups.append({
        "hooks": [{
            "type": "command",
            "command": f'{python} "$CLAUDE_PROJECT_DIR"/{sync_rel}',
            "timeout": 10,
        }],
    })
    hooks["UserPromptSubmit"] = ups

    # 2. Stop → final sync (catches files written since last sync)
    stop = _clean_hooks(hooks.get("Stop", []))
    stop.append({
        "hooks": [{
            "type": "command",
            "command": f'{python} "$CLAUDE_PROJECT_DIR"/{stop_sync_rel}',
            "timeout": 15,
        }],
    })
    hooks["Stop"] = stop

    # Clean up old hooks that are no longer needed
    for old_event in ["PostToolUse", "SessionStart"]:
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
