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
from typing import Callable, Optional


def resolve_source_path(filepath: str, root: Optional[str]) -> str:
    """Return the absolute on-disk path when the file exists under ``root``,
    otherwise the stored ``filepath`` unchanged.

    Absolute inputs and empty inputs pass through untouched. This is the single
    rule both the CLI and the MCP server apply, so identical results always
    report identical paths.
    """
    if not filepath or os.path.isabs(filepath):
        return filepath
    if root:
        abs_path = os.path.join(root, filepath)
        if os.path.exists(abs_path):
            return abs_path
    return filepath


def build_slug_root_resolver(lib) -> Callable[[str], Optional[str]]:
    """Return a ``book_slug -> sync-root`` lookup for one result set.

    Batches ``books(slug, corpus)`` once and caches ``corpus -> sync_root`` so
    resolving a whole result set costs two queries rather than per-row SQL.
    Callers feed the returned root into :func:`resolve_source_path`.
    """
    slug_corpus: dict[str, str] = {}
    try:
        conn = lib._get_conn()
        for row in conn.execute("SELECT slug, corpus FROM books").fetchall():
            slug_corpus[row["slug"]] = row["corpus"] or ""
    except Exception:
        pass
    root_cache: dict[str, Optional[str]] = {}

    def root_for_slug(slug: str) -> Optional[str]:
        corpus = slug_corpus.get(slug, "")
        if corpus not in root_cache:
            try:
                root_cache[corpus] = lib.get_sync_root(corpus)
            except Exception:
                root_cache[corpus] = None
        return root_cache[corpus]

    return root_for_slug
