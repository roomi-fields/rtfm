"""Runtime behind the Claude Code hooks.

The hook *scripts* dropped into a project's ``.claude/hooks/`` are thin
stubs: they locate the project root and call into this module, which ships
with the installed package. Any fix here reaches every project on the next
``pipx install --upgrade`` — no re-``init`` needed. Before 0.28.0 the logic
lived inline in the copied scripts, so a project initialised months ago kept
running months-old logic forever (that is how the 0.27.0 "index all text"
change silently bypassed the edit hook for extension-less files).

Two entry points:

``heartbeat(project_root)``
    UserPromptSubmit / Stop — revive the supervisor, and refresh the hook
    stubs if the installed package ships newer ones.

``on_file_edited(project_root, payload)``
    PostToolUse(Write|Edit|MultiEdit) — enqueue the single file the agent
    just wrote as a **P_USER** ingest, so it lands ahead of every background
    job. Non-destructive: only ever adds work.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional


def log(project_root: Path, msg: str) -> None:
    try:
        ts = time.strftime("%H:%M:%S")
        with open(Path(project_root) / ".rtfm" / "rtfm.log", "a") as fh:
            fh.write(f"[{ts}]       hook | {msg}\n")
    except Exception:
        pass


# ── source selection ─────────────────────────────────────────────────────

def _source_admits(src: dict, name: str, rel: str) -> bool:
    """Apply a source's selection rules to one file.

    Same three-rule contract as :func:`rtfm.core.sync.scan_directory`:
    ``exclude`` always wins; with no ``extensions`` and no ``include`` the
    source takes every text file; otherwise the file must match one of them.
    """
    from rtfm.core.sync import _matches_pattern

    for pat in src.get("exclude") or []:
        if _matches_pattern(name, rel, pat):
            return False

    raw = src.get("extensions")
    exts: set[str] = set()
    wildcard = False
    if raw:
        for e in str(raw).split(","):
            e = e.strip().lower()
            if not e:
                continue
            if e in ("*", ".*", "**"):
                wildcard = True
                continue
            exts.add(e if e.startswith(".") else f".{e}")
    include = list(src.get("include") or [])

    if wildcard or (not exts and not include):
        return True
    if exts and Path(name).suffix.lower() in exts:
        return True
    return any(_matches_pattern(name, rel, pat) for pat in include)


def match_source(project_root: Path, fpath: Path) -> Optional[tuple[Path, str]]:
    """Return ``(root, corpus)`` of the most specific source holding *fpath*."""
    from rtfm.config import load_config

    try:
        cfg = load_config(project_root)
    except Exception:
        cfg = {}
    default_corpus = cfg.get("corpus", "default")
    sources = cfg.get("sources") or [
        {"path": str(project_root), "corpus": default_corpus}]

    best: Optional[tuple[Path, str, int]] = None
    for src in sources:
        try:
            root = Path(src.get("path", ".")).resolve()
            rel = str(fpath.relative_to(root))
        except (ValueError, OSError):
            continue
        if not _source_admits(src, fpath.name, rel):
            continue
        depth = len(root.parts)
        if best is None or depth > best[2]:
            best = (root, src.get("corpus", default_corpus), depth)
    return (best[0], best[1]) if best else None


# ── PostToolUse: one edited file ─────────────────────────────────────────

def on_file_edited(project_root: str | Path, payload: dict[str, Any]) -> None:
    project_root = Path(project_root)
    rtfm_dir = project_root / ".rtfm"
    if not (rtfm_dir / "library.db").exists():
        return

    ti = payload.get("tool_input") or {}
    raw = ti.get("file_path") or ti.get("path") or ti.get("notebook_path")
    if not raw:
        return
    try:
        fpath = Path(raw).resolve()
    except OSError:
        return
    if not fpath.is_file():
        return

    matched = match_source(project_root, fpath)
    if matched is None:
        return
    root, corpus = matched

    # A file no parser claims is still indexed as plain text (0.27.0+) — the
    # only thing ingest refuses is binary, so that is the only gate here.
    from rtfm.core.sniff import looks_binary
    from rtfm.parsers.base import ParserRegistry
    import rtfm.parsers  # noqa: F401 — registers the parsers

    if ParserRegistry.get_parser(fpath) is None and looks_binary(fpath):
        return

    rel = str(fpath.relative_to(root))
    try:
        from rtfm.core.queue import Queue, P_USER
        from rtfm.cli_worker import ensure_worker_running

        q = Queue(str(rtfm_dir / "library.db"))
        try:
            # P_USER: an agent is *about to read this back*. It must not wait
            # behind a background re-index wave (measured: 104 s at P_DOC on a
            # 25-project machine).
            q.enqueue("ingest",
                      {"root": str(root), "corpus": corpus, "filepath": rel},
                      priority=P_USER)
        finally:
            q.close()
        ensure_worker_running(rtfm_dir)
        log(project_root, f"enqueued ingest [{corpus}] {rel}")
    except Exception as exc:
        log(project_root, f"enqueue ERROR: {exc}")


# ── UserPromptSubmit / Stop: keep the pipeline alive & the stubs current ──

def heartbeat(project_root: str | Path) -> None:
    project_root = Path(project_root)
    rtfm_dir = project_root / ".rtfm"
    if not (rtfm_dir / "library.db").exists():
        return
    try:
        from rtfm.plugin.hooks import refresh_hook_scripts
        updated = refresh_hook_scripts(project_root)
        if updated:
            log(project_root, f"hook scripts refreshed: {', '.join(updated)}")
    except Exception as exc:
        log(project_root, f"hook refresh ERROR: {exc}")
    try:
        from rtfm.cli_worker import ensure_worker_running
        pid = ensure_worker_running(rtfm_dir)
        if pid:
            log(project_root, f"worker alive pid={pid}")
    except Exception as exc:
        log(project_root, f"worker ensure ERROR: {exc}")


def read_payload(stream) -> dict[str, Any]:
    try:
        return json.load(stream) or {}
    except Exception:
        return {}
