"""Canonical on-disk path resolution for indexed files.

The CLI and the MCP server must report *identical* paths for the same search
result. Each used to carry its own ``_resolve_abs_path`` copy, and the CLI
called it with an empty corpus — so it always returned the stored *relative*
path while the MCP returned an *absolute* one whenever the file existed. That
split made the same file look present in one tool and missing in the other,
and made "restore a deleted file" flip a path from relative to absolute on one
install but not on another. One rule, used by both, removes the divergence.
"""
from __future__ import annotations

import os
from typing import Callable, Optional, Sequence  # noqa: F401 — Sequence in annotations


def resolve_source_path(filepath: str, roots: "Sequence[str] | str | None") -> str:
    """Return the absolute on-disk path when the file exists under one of
    ``roots``, otherwise the stored ``filepath`` unchanged.

    A corpus may gather several source directories, and a stored path is
    relative to whichever one it came from — so every root of the corpus is
    tried, in the order given, and the first that actually holds the file
    wins. Absolute inputs and empty inputs pass through untouched. This is
    the single rule both the CLI and the MCP server apply, so identical
    results always report identical paths.
    """
    if not filepath or os.path.isabs(filepath):
        return filepath
    if isinstance(roots, str):
        roots = [roots]
    for root in roots or ():
        if not root:
            continue
        abs_path = os.path.join(root, filepath)
        if os.path.exists(abs_path):
            return abs_path
    return filepath


def owning_root(abs_path: str, roots: "Sequence[str] | str | None") -> Optional[str]:
    """Which of ``roots`` a resolved path actually sits under.

    Re-indexing a single file needs the one directory it belongs to, not the
    whole list its corpus gathers. Returns None when the path belongs to none
    of them — a caller must not guess in that case.
    """
    if not abs_path:
        return None
    if isinstance(roots, str):
        roots = [roots]
    best = None
    for root in roots or ():
        if not root:
            continue
        prefix = root.rstrip(os.sep) + os.sep
        if abs_path.startswith(prefix) and (best is None or len(root) > len(best)):
            best = root
    return best


def build_slug_root_resolver(lib) -> Callable[[str], list]:
    """Return a ``book_slug -> source directories`` lookup for one result set.

    Batches ``books(slug, corpus)`` once and caches ``corpus -> roots`` so
    resolving a whole result set costs two queries rather than per-row SQL.
    Callers feed the returned list into :func:`resolve_source_path`.
    """
    slug_corpus: dict[str, str] = {}
    try:
        conn = lib._get_conn()
        for row in conn.execute("SELECT slug, corpus FROM books").fetchall():
            slug_corpus[row["slug"]] = row["corpus"] or ""
    except Exception:
        pass
    root_cache: dict[str, list] = {}

    def roots_for_slug(slug: str) -> list:
        corpus = slug_corpus.get(slug, "")
        if corpus not in root_cache:
            try:
                root_cache[corpus] = lib.list_sync_roots(corpus)
            except Exception:
                root_cache[corpus] = []
        return root_cache[corpus]

    return roots_for_slug
