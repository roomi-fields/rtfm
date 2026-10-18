"""Claude Code memory files, indexed with their whole history.

Each project's ``~/.claude/projects/<slug>/memory/`` becomes the corpus
``claude-memory/<slug>`` of one global index, ``~/.rtfm/memory.db``. Nothing
is ever removed from it: every version of every memory file is kept.

Run by ``rtfm memory`` and, at the end of every session, by the global hook
``rtfm memory --install-hook`` writes.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

DEFAULT_DB = Path.home() / ".rtfm" / "memory.db"


def memory_sources(projects_root: Path) -> tuple[list[tuple[str, Path]], list[str]]:
    """``([(corpus, directory)], [corpus indexing a directory twice])``.

    A project's memory directory can be a link to another's — two projects
    sharing one memory. Indexed under both names, the same files fought
    over one index entry on every pass ("UNIQUE constraint failed"). Each
    directory is indexed once, under the project that really holds it; the
    names that only link to it are returned as duplicates.
    """
    dirs = [p for p in projects_root.glob("*/memory") if p.is_dir()]
    # The real directory first, then the links to it.
    dirs.sort(key=lambda p: (p.is_symlink(), p.parent.name))
    seen: set[Path] = set()
    keep: list[tuple[str, Path]] = []
    duplicates: list[str] = []
    for d in dirs:
        corpus = f"claude-memory/{d.parent.name.strip('-') or 'root'}"
        real = d.resolve()
        if real in seen:
            duplicates.append(corpus)
            continue
        seen.add(real)
        keep.append((corpus, d))
    keep.sort(key=lambda t: t[1].parent.name)
    return keep, duplicates


def forget_corpus(lib, corpus: str) -> int:
    """Take a duplicate corpus out of the index. Its files stay indexed
    under the project that holds them."""
    removed = 0
    for rel in list(lib.list_indexed_files(corpus=corpus)):
        if lib.remove_file(rel, corpus):
            removed += 1
    conn = lib._get_conn()
    conn.execute("DELETE FROM sync_roots WHERE corpus = ?", (corpus,))
    conn.commit()
    return removed


def sync_memories(lib, projects_root: Path, generate_embeddings: bool = False,
                  on_project: Callable | None = None,
                  on_progress: Callable | None = None) -> list:
    """Index every project's memory. Returns ``[(corpus, directory, result)]``."""
    from rtfm.core.sync import sync

    keep, duplicates = memory_sources(projects_root)
    for corpus in duplicates:
        forget_corpus(lib, corpus)
    out = []
    for corpus, mem_dir in keep:
        if on_project:
            on_project(corpus, mem_dir)
        result = sync(
            library=lib, root=mem_dir, corpus=corpus,
            extensions={".md", ".txt"},
            generate_embeddings=generate_embeddings,
            on_progress=on_progress,
            retain_history=None,        # unlimited history for memory files
        )
        out.append((corpus, mem_dir, result))
    return out


def run_hook(db_path: Path = DEFAULT_DB,
             projects_root: Path | None = None) -> None:
    """The end-of-session pass: silent, and one at a time.

    Several sessions ending together each start one; the first takes the
    lock and the others leave — it reads every project anyway. Where the
    index cannot be written (an agent's sandbox), it does nothing.
    """
    from rtfm.core.library import Library
    from rtfm.core.portable import open_lock_file, try_lock_exclusive, unlock

    projects_root = projects_root or Path.home() / ".claude" / "projects"
    if not projects_root.is_dir():
        return
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        fd = open_lock_file(db_path.parent / "memory.lock")
    except OSError:
        return
    try:
        if not try_lock_exclusive(fd):
            return
        try:
            lib = Library(str(db_path))
            try:
                sync_memories(lib, projects_root)
            finally:
                lib.close()
        finally:
            unlock(fd)
    finally:
        os.close(fd)
