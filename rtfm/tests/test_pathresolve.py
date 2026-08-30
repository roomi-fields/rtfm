"""Tests for the shared on-disk path resolver used by the CLI and MCP.

Guards the fix for the CLI/MCP divergence: the CLI used to resolve with an
empty corpus and always returned relative paths, while the MCP returned
absolute paths — the same result reported two different paths. One rule now.
"""
from __future__ import annotations

import os
from pathlib import Path

from rtfm.core.library import Library
from rtfm.core.pathresolve import resolve_source_path, build_slug_root_resolver


def test_resolve_source_path_absolute_when_file_exists(tmp_path):
    (tmp_path / "a.md").write_text("x")
    assert resolve_source_path("a.md", str(tmp_path)) == str(tmp_path / "a.md")


def test_resolve_source_path_relative_when_missing(tmp_path):
    assert resolve_source_path("gone.md", str(tmp_path)) == "gone.md"


def test_resolve_source_path_relative_when_no_root():
    assert resolve_source_path("a.md", None) == "a.md"


def test_resolve_source_path_absolute_passthrough(tmp_path):
    assert resolve_source_path("/abs/y.md", str(tmp_path)) == "/abs/y.md"


def test_resolve_source_path_empty_passthrough():
    assert resolve_source_path("", str("/whatever")) == ""


def test_slug_root_resolver_maps_slug_to_correct_corpus_root(tmp_path):
    """The resolver must find a book's corpus and that corpus's sync root —
    the exact step the CLI skipped by passing an empty corpus."""
    db = tmp_path / "library.db"
    root_a = tmp_path / "corpus-a"
    root_a.mkdir()
    (root_a / "doc.md").write_text("# doc\n\nbody\n")

    lib = Library(str(db))
    try:
        lib.set_sync_root("A", str(root_a))
        conn = lib._get_conn()
        conn.execute(
            "INSERT INTO books (slug, title, filename, corpus) "
            "VALUES (?, ?, ?, ?)",
            ("doc-slug", "Doc", "doc.md", "A"))
        conn.commit()

        roots_for_slug = build_slug_root_resolver(lib)
        # A corpus may gather several directories, so the resolver hands back
        # every one of them, most recently scanned first.
        assert roots_for_slug("doc-slug") == [str(root_a)]
        # End-to-end: an existing file resolves to its absolute path.
        assert resolve_source_path("doc.md", roots_for_slug("doc-slug")) \
            == str(root_a / "doc.md")
        # Unknown slug → no root → relative passthrough (never crashes).
        assert resolve_source_path("x.md", roots_for_slug("nope")) == "x.md"
    finally:
        lib.close()
