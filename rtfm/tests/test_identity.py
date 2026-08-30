"""Two files are two files, whatever their names look like.

Identity was derived from the file's *stem*, which drops everything after the
last dot. `timed_events.h` and `timed_events.c` became one identity; so did
`+sc.Ruwet` and `+sc.tryMe`, where the stem stops at the first dot and leaves
both called `+sc`. The second file to arrive hit a UNIQUE violation and never
entered the index — no error surfaced anywhere a person would look. 1 750
files across this fleet were missing for that reason.

Two rules keep it from coming back: the name (extension included) decides the
identity, and the write side refuses to hand one identity to two files even if
some future naming rule collides again.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rtfm.core.library import Library
from rtfm.core.sync import _path_to_slug, sync


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestTheNameDecides:
    @pytest.mark.parametrize("a, b", [
        ("bp3/timed_events.h", "bp3/timed_events.c"),
        ("scripts/+sc.Ruwet", "scripts/+sc.tryMe"),
        ("notes.md", "notes.txt"),
        ("archive.tar.gz", "archive.tar.bz2"),
    ])
    def test_two_files_get_two_identities(self, a, b):
        assert _path_to_slug(a, "corp") != _path_to_slug(b, "corp")

    def test_both_files_actually_reach_the_index(self, tmp_path):
        """The end that matters: before, one of the two was simply absent."""
        root = tmp_path / "src"
        _write(root / "timed_events.h", "// header " * 40)
        _write(root / "timed_events.c", "// source " * 40)

        lib = Library(str(tmp_path / "library.db"))
        try:
            sync(library=lib, root=root, corpus="code",
                 extensions={".h", ".c"}, generate_embeddings=False)
            indexed = lib.list_indexed_files(corpus="code")
            assert set(indexed) == {"timed_events.h", "timed_events.c"}
            slugs = {b["slug"] for b in lib.list_books(corpus="code")}
            assert len(slugs) == 2
        finally:
            lib.close()


class TestAnIdentityIsNeverGivenTwice:
    def test_a_collision_is_settled_instead_of_dropping_the_file(self, tmp_path):
        """No naming rule can promise uniqueness for ever. When two paths do
        normalise to the same string, the second file gets a free identity —
        it is never dropped."""
        lib = Library(str(tmp_path / "library.db"))
        try:
            conn = lib._get_conn()
            conn.execute(
                "INSERT INTO books (slug, title, filename, corpus) "
                "VALUES ('c--x', 'X', 'first.md', 'c')")
            conn.commit()

            assert lib.allocate_book_slug("c--x", "second.md", "c") == "c--x-2"
        finally:
            lib.close()

    def test_a_file_keeps_the_identity_it_already_owns(self, tmp_path):
        lib = Library(str(tmp_path / "library.db"))
        try:
            conn = lib._get_conn()
            conn.execute(
                "INSERT INTO books (slug, title, filename, corpus) "
                "VALUES ('c--x', 'X', 'first.md', 'c')")
            conn.commit()

            assert lib.allocate_book_slug("c--x", "first.md", "c") == "c--x"
        finally:
            lib.close()


class TestAnIndexedFileKeepsItsIdentity:
    """Recomputing identities would re-index every project the day a naming
    rule changes — and throw away every embedding with it. A file that has not
    moved keeps what it was indexed under."""

    def test_the_recorded_identity_wins_over_a_fresh_one(self, tmp_path):
        lib = Library(str(tmp_path / "library.db"))
        try:
            lib.update_indexed_file(filepath="a.md", file_hash="h",
                                    corpus="c", book_slug="an-old-style-slug")
            assert lib.book_slug_for("a.md", "c") == "an-old-style-slug"
        finally:
            lib.close()

    def test_a_newcomer_has_none(self, tmp_path):
        lib = Library(str(tmp_path / "library.db"))
        try:
            assert lib.book_slug_for("never-seen.md", "c") is None
        finally:
            lib.close()

    def test_re_indexing_does_not_rename_anything(self, tmp_path):
        """The scenario that would have cost the fleet its embeddings: a file
        indexed under the old naming, re-ingested after the change."""
        root = tmp_path / "src"
        f = _write(root / "notes.md", "First revision. " * 40)

        lib = Library(str(tmp_path / "library.db"))
        try:
            sync(library=lib, root=root, corpus="c",
                 extensions={".md"}, generate_embeddings=False)
            before = lib.list_indexed_files(corpus="c")["notes.md"]["book_slug"]

            f.write_text("Second revision. " * 40, encoding="utf-8")
            sync(library=lib, root=root, corpus="c",
                 extensions={".md"}, generate_embeddings=False)
            after = lib.list_indexed_files(corpus="c")["notes.md"]["book_slug"]

            assert before == after
            assert len(lib.list_books(corpus="c")) == 1, "no orphan left behind"
        finally:
            lib.close()


class TestRetryingAFailureAlsoForgetsIt:
    """A failure is remembered twice: as a queue row, and as "this content
    does not parse" so scans stop re-proposing the file. When the reason is
    fixed in RTFM itself, clearing only the queue row leaves the file out of
    the index anyway — which is what kept 58 files invisible after the
    identity fix landed."""

    def test_the_memory_is_cleared_too(self, tmp_path):
        lib = Library(str(tmp_path / "library.db"))
        try:
            lib.record_ingest_failure("a.md", "c", "hash", 10, "boom")
            lib.record_ingest_failure("b.md", "c", "hash", 10, "boom")
            assert len(lib.list_ingest_failures()) == 2

            assert lib.forget_ingest_failures() == 2
            assert lib.list_ingest_failures() == {}
        finally:
            lib.close()
