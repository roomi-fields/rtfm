#!/usr/bin/env python3
"""RTFM Stop hook — targeted incremental sync.

Reads the list of files touched this turn from
``.rtfm/touched_files.tmp`` (populated by the PostToolUse hook), groups
them by the longest-matching configured source, and runs
``sync(files=[...])`` for each group. Resets the list on success.

Before 0.9.4 this hook re-scanned every configured source at every turn,
which on multi-session setups with 35 sources became unbearable and
fought the running OCR daemon for SQLite write locks.

Falls back to a no-op when no files were touched this turn.
"""
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

# Make the plugin-bundled rtfm code importable without pip.
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))


def _project_root() -> Path | None:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env).resolve() if env else None


def _log(project_root: Path, msg: str) -> None:
    try:
        ts = time.strftime("%H:%M:%S")
        log_path = project_root / ".rtfm" / "rtfm.log"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}]       hook | {msg}\n")
    except Exception:
        pass


def _load_sources(rtfm_dir: Path, project_root: Path) -> tuple[list[dict], str]:
    """Read sources + default_corpus from .rtfm/config.json, with project
    root as a single-source fallback."""
    config_path = rtfm_dir / "config.json"
    default_corpus = "default"
    sources: list[dict] = []
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            sources = cfg.get("sources", []) or []
            default_corpus = cfg.get("corpus", "default")
        except Exception:
            pass
    if not sources:
        sources = [{"path": str(project_root), "corpus": default_corpus}]
    return sources, default_corpus


def main() -> None:
    project_root = _project_root()
    if not project_root:
        return

    rtfm_dir = project_root / ".rtfm"
    if not rtfm_dir.exists():
        return

    db_path = rtfm_dir / "library.db"
    if not db_path.exists():
        return

    tmp = rtfm_dir / "touched_files.tmp"
    if not tmp.exists() or tmp.stat().st_size == 0:
        return

    try:
        touched = {ln.strip() for ln in tmp.read_text(encoding="utf-8").splitlines()
                   if ln.strip()}
    except Exception:
        return
    if not touched:
        tmp.unlink(missing_ok=True)
        return

    sources, default_corpus = _load_sources(rtfm_dir, project_root)

    # Group touched files by their owning source — pick the longest path
    # that contains the file, so a nested source wins over its parent.
    sources_sorted = sorted(
        (
            (Path(s.get("path", ".")).resolve(),
             s.get("corpus", default_corpus),
             s.get("extensions"))
            for s in sources
        ),
        key=lambda t: -len(str(t[0])),
    )
    by_source: dict[tuple, list[str]] = defaultdict(list)
    unmatched: list[str] = []
    for fp in touched:
        try:
            p = Path(fp).resolve()
        except Exception:
            unmatched.append(fp)
            continue
        matched = False
        for root, corpus, exts in sources_sorted:
            try:
                rel = p.relative_to(root)
            except ValueError:
                continue
            by_source[(root, corpus, exts)].append(str(rel))
            matched = True
            break
        if not matched:
            unmatched.append(fp)

    if not by_source:
        _log(project_root, f"stop-sync skipped: {len(touched)} file(s) outside any source")
        tmp.unlink(missing_ok=True)
        return

    _log(
        project_root,
        f"stop-sync targeted: {len(touched)} file(s) across {len(by_source)} source(s)"
        + (f", {len(unmatched)} outside any source" if unmatched else ""),
    )
    t0 = time.time()
    try:
        from rtfm.core.library import Library
        from rtfm.core.sync import sync

        lib = Library(str(db_path))
        total_added = total_modified = 0
        for (root, corpus, exts), files in by_source.items():
            ext_set = None
            if exts:
                ext_set = {e.strip() if e.strip().startswith(".") else f".{e.strip()}"
                           for e in exts.split(",")}
            result = sync(
                library=lib, root=root, corpus=corpus,
                files=files, extensions=ext_set,
                generate_embeddings=False,
            )
            total_added += result.added
            total_modified += result.modified
        lib.close()
        elapsed = time.time() - t0
        _log(project_root,
             f"stop-sync done +{total_added} ~{total_modified} time={elapsed:.2f}s")
        # Clear the queue only after a successful sync — if we crashed
        # mid-flight, the next turn will retry the same files.
        tmp.unlink(missing_ok=True)
    except Exception as e:
        _log(project_root, f"stop-sync ERROR: {e}")


if __name__ == "__main__":
    main()
