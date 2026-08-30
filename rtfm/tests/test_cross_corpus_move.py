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


def test_corpus_rename_in_place_no_unique_conflict(library, tmp_path):
    """Regression for the 0.9.1 UNIQUE-constraint bug.

    When the user keeps the same physical path but renames the corpus in
    config.json (e.g. ``code`` → ``musicology-phd`` both rooted at
    ``/home/romi/dev/musicology-phd``), every file's *relative* path is
    identical in the old and new corpus, so ``move_file()`` is called with
    ``old_filepath == new_filepath``. The previous ``DELETE + plain INSERT``
    raised ``UNIQUE constraint failed: indexed_files.filepath`` mid-sync
    and stranded the ``books`` rows without their tracking entry.
    """
    root = tmp_path
    _make_md(root / "a.md", "alpha content")
    _make_md(root / "b.md", "beta content")

    # Initial sync under corpus="code"
    sync(library=library, root=root, corpus="code",
         extensions={".md"}, generate_embeddings=False)

    # Same root, new corpus name → every file is a cross-corpus move
    # with old_filepath == new_filepath
    result = sync(library=library, root=root, corpus="musicology-phd",
                  extensions={".md"}, generate_embeddings=False)

    # 2 cross-corpus moves succeeded, 0 errors, 0 re-ingest
    assert result.moved == 2, f"expected 2 cross-moves, got {result.moved}"
    assert result.added == 0, f"expected no re-ingest, got {result.added} added"
    assert not result.errors, f"unexpected errors: {result.errors}"

    # Tracking rows must be present under the new corpus, with the
    # same filepath, and NOT under the old one.
    conn = library._get_conn()
    rows = conn.execute(
        "SELECT filepath, corpus FROM indexed_files ORDER BY filepath"
    ).fetchall()
    by_corpus = {r["corpus"] for r in rows}
    assert by_corpus == {"musicology-phd"}, by_corpus
    filepaths = {r["filepath"] for r in rows}
    assert filepaths == {"a.md", "b.md"}, filepaths

    # And books table is consistent with tracking (the original bug
    # symptom was books orphaned from indexed_files).
    orphans = conn.execute(
        """SELECT COUNT(*) FROM books b
           LEFT JOIN indexed_files i ON i.book_slug = b.slug
           WHERE i.id IS NULL"""
    ).fetchone()[0]
    assert orphans == 0, f"{orphans} books left without tracking row"


def test_move_file_preexisting_target_filepath(library, tmp_path):
    """``move_file()`` must tolerate a pre-existing row at ``new_filepath``.

    Belt-and-braces unit test of the UPSERT fix: call ``move_file`` directly
    after seeding a colliding tracking row, ensure no UNIQUE error and the
    row ends up with the new corpus/slug.
    """
    conn = library._get_conn()
    # Seed the "old" tracking row
    conn.execute(
        "INSERT INTO indexed_files (filepath, file_hash, corpus, book_slug, indexed_at, file_size) "
        "VALUES ('foo.md', 'h1', 'corp_old', 'old-slug', datetime('now'), 100)"
    )
    conn.commit()
    # Same filepath already exists once — that's the pre-existing row
    # at *new_filepath* the bug used to choke on.
    library.move_file(
        old_filepath="foo.md",
        new_filepath="foo.md",
        new_slug="new-slug",
        corpus="corp_old",
        new_corpus="corp_new",
    )
    row = conn.execute(
        "SELECT corpus, book_slug FROM indexed_files WHERE filepath = 'foo.md'"
    ).fetchone()
    assert row["corpus"] == "corp_new"
    assert row["book_slug"] == "new-slug"


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
