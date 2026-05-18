"""Cross-corpus move detection by content hash.

When a tracked file is moved across corpus boundaries (e.g. the user
reorganises their Obsidian vault from `Projets/Foo/` into `Publications/`),
RTFM must detect that the new "added" file in corpus B matches the
content_hash of an existing file in corpus A and *transfer* the book +
chunks + embeddings + tags instead of re-indexing from scratch. That
preserves potentially-expensive computation (semantic embeddings, OCR
output) when the user only changed where a file lives.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from rtfm import Library
from rtfm.core.sync import sync


def _make_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_cross_corpus_move_preserves_chunk_ids(library, tmp_path):
    """Moving a file from corpus A to corpus B keeps the same book_id
    (and therefore the same chunk_ids, embeddings, tags)."""
    src_a = tmp_path / "corpus_a"
    src_b = tmp_path / "corpus_b"
    src_a.mkdir()
    src_b.mkdir()

    note = src_a / "note.md"
    _make_md(note, "# Title\n\nSome content paragraph.\n\nAnother paragraph here.\n")

    # Initial sync into corpus_a
    sync(library=library, root=src_a, corpus="alpha",
         extensions={".md"}, generate_embeddings=False)

    indexed = library.list_indexed_files()
    assert "note.md" in indexed
    assert indexed["note.md"]["corpus"] == "alpha"
    old_slug = indexed["note.md"]["book_slug"]

    # Capture chunk_ids before the move so we can assert they survive
    conn = library._get_conn()
    book_id_a = conn.execute(
        "SELECT id FROM books WHERE slug = ?", (old_slug,)
    ).fetchone()["id"]
    chunk_ids_before = {
        row["id"] for row in conn.execute(
            "SELECT id FROM chunks WHERE book_id = ?", (book_id_a,)
        ).fetchall()
    }
    assert chunk_ids_before, "should have at least one chunk"

    # User moves the file to corpus_b on disk (same bytes → same hash)
    shutil.move(str(note), str(src_b / "note.md"))

    # Sync corpus_b — must detect the cross-corpus move
    result = sync(library=library, root=src_b, corpus="beta",
                  extensions={".md"}, generate_embeddings=False)
    assert result.moved == 1, "should report exactly one move"
    assert result.added == 0, "should not re-ingest"

    indexed = library.list_indexed_files()
    assert "note.md" in indexed
    assert indexed["note.md"]["corpus"] == "beta", \
        "tracking row must now belong to corpus beta"

    # Same book_id, same chunk_ids (embeddings/tags survive automatically
    # because they reference chunk_id, not the on-disk path)
    new_slug = indexed["note.md"]["book_slug"]
    book_id_b = conn.execute(
        "SELECT id FROM books WHERE slug = ?", (new_slug,)
    ).fetchone()["id"]
    assert book_id_b == book_id_a, "book row must be reused, not recreated"

    chunk_ids_after = {
        row["id"] for row in conn.execute(
            "SELECT id FROM chunks WHERE book_id = ?", (book_id_b,)
        ).fetchall()
    }
    assert chunk_ids_after == chunk_ids_before, \
        "chunk_ids must be preserved across the cross-corpus move"


def test_within_corpus_move_still_works(library, tmp_path):
    """Regression: in-corpus moves keep working after the cross-corpus
    plumbing was added."""
    root = tmp_path
    note = root / "sub_a" / "note.md"
    _make_md(note, "# Title\n\nContent here.\n")

    sync(library=library, root=root, corpus="alpha",
         extensions={".md"}, generate_embeddings=False)

    (root / "sub_b").mkdir(exist_ok=True)
    shutil.move(str(note), str(root / "sub_b" / "note.md"))

    result = sync(library=library, root=root, corpus="alpha",
                  extensions={".md"}, generate_embeddings=False)
    assert result.moved == 1
    assert result.added == 0


def test_cross_corpus_move_handles_no_global_match(library, tmp_path):
    """A genuinely new file (no hash match anywhere) goes through the
    normal added path."""
    src_a = tmp_path / "corpus_a"
    src_b = tmp_path / "corpus_b"
    src_a.mkdir()
    src_b.mkdir()

    _make_md(src_a / "alpha.md", "alpha content")
    sync(library=library, root=src_a, corpus="alpha",
         extensions={".md"}, generate_embeddings=False)

    _make_md(src_b / "totally_new.md", "different content entirely")
    result = sync(library=library, root=src_b, corpus="beta",
                  extensions={".md"}, generate_embeddings=False)

    assert result.added == 1
    assert result.moved == 0
