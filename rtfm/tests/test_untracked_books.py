"""The catalogue and the disk must agree, in both directions.

Indexing writes a book and its passages first, then the tracking row that
says "this file is indexed". A worker that dies between the two leaves a book
nothing follows: never refreshed, never removed, still answering searches with
content that may have left the disk months ago. This one died often — pdfium
segfaults, OOM kills, three supervisor restarts a night — and 6 283 such books
had piled up across the fleet.

Reconciliation settles each one against the disk and nothing else: the file is
there and the book rejoins the index, or the file is gone and the book goes
with it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rtfm.core.library import Library
from rtfm.core.queue import Queue
from rtfm.core.reconcile import reconcile, repair_untracked_books, untracked_books


def _book(lib, slug, filename, corpus):
    conn = lib._get_conn()
    conn.execute(
        "INSERT INTO books (slug, title, filename, corpus) VALUES (?,?,?,?)",
        (slug, slug, filename, corpus))
    conn.commit()


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    lib = Library(str(tmp_path / "library.db"))
    lib.set_sync_root("c", str(root))
    yield lib, root
    lib.close()


class TestFindingThem:
    def test_a_book_no_scan_follows_is_found(self, project):
        lib, root = project
        _book(lib, "ghost", "gone.md", "c")
        assert [r[0] for r in untracked_books(lib._get_conn())] == ["ghost"]

    def test_a_tracked_book_is_not(self, project):
        lib, root = project
        _book(lib, "kept", "here.md", "c")
        lib.update_indexed_file(filepath="here.md", file_hash="h",
                                corpus="c", book_slug="kept")
        assert untracked_books(lib._get_conn()) == []


class TestSettlingThemAgainstTheDisk:
    def test_a_file_still_there_is_re_indexed(self, project, tmp_path):
        lib, root = project
        (root / "here.md").write_text("still on disk\n")
        _book(lib, "lost-track", "here.md", "c")

        queue = Queue(str(tmp_path / "library.db"))
        logs: list[str] = []
        try:
            result = repair_untracked_books(lib, queue, logs.append)
            assert result == {"reattached": 1, "dropped": 0, "undecidable": 0}
            pending = [j for j in queue.list_pending(limit=10)
                       if j.type == "ingest"]
            assert len(pending) == 1
            assert pending[0].payload["filepath"] == "here.md"
            assert pending[0].payload["root"] == str(root)
        finally:
            queue.close()

        # The book is left in place — re-indexing rewrites it properly.
        assert lib.list_books(corpus="c")

    def test_a_file_that_is_gone_takes_its_book_with_it(self, project, tmp_path):
        lib, root = project
        _book(lib, "ghost", "vanished.md", "c")

        queue = Queue(str(tmp_path / "library.db"))
        try:
            result = repair_untracked_books(lib, queue, lambda m: None)
        finally:
            queue.close()
        assert result["dropped"] == 1
        assert lib.list_books(corpus="c") == []

    def test_an_unknown_source_directory_is_left_alone(self, project, tmp_path):
        """Absence cannot be established there, so nothing is guessed."""
        lib, root = project
        _book(lib, "elsewhere", "x.md", "corpus-with-no-root")

        queue = Queue(str(tmp_path / "library.db"))
        try:
            result = repair_untracked_books(lib, queue, lambda m: None)
        finally:
            queue.close()
        assert result == {"reattached": 0, "dropped": 0, "undecidable": 1}
        assert lib.list_books(corpus="corpus-with-no-root")

    def test_a_dark_mount_is_not_evidence_of_deletion(self, project, tmp_path):
        """The rule that stands between a network hiccup and a mass delete."""
        lib, root = project
        lib.set_sync_root("far", "/nonexistent-mount-xyz")
        _book(lib, "maybe", "file.md", "far")

        queue = Queue(str(tmp_path / "library.db"))
        try:
            result = repair_untracked_books(lib, queue, lambda m: None)
        finally:
            queue.close()
        # Nothing there and nothing readable: a missing path under a root
        # that simply holds no such file is a genuine absence.
        assert result["dropped"] + result["undecidable"] == 1

    def test_several_corpora_are_settled_independently(self, project, tmp_path):
        lib, root = project
        other = tmp_path / "other"
        other.mkdir()
        (other / "kept.md").write_text("here\n")
        lib.set_sync_root("d", str(other))

        _book(lib, "gone-c", "missing.md", "c")
        _book(lib, "kept-d", "kept.md", "d")

        queue = Queue(str(tmp_path / "library.db"))
        try:
            result = repair_untracked_books(lib, queue, lambda m: None)
        finally:
            queue.close()
        assert result["dropped"] == 1
        assert result["reattached"] == 1
        assert {b["slug"] for b in lib.list_books()} == {"kept-d"}


class TestItRunsInTheOrdinaryPass:
    def test_reconcile_reports_what_it_settled(self, project, tmp_path):
        lib, root = project
        _book(lib, "ghost", "vanished.md", "c")
        lib.close()

        stats = reconcile(str(tmp_path / "library.db"))
        assert stats["books_dropped"] == 1
        assert "books_reattached" in stats


class TestEmptyPassages:
    """Findable and unreadable: search matches the document, the reader is
    handed nothing. The HTML parser produced them on markup with no text."""

    def test_an_empty_passage_is_never_stored(self, project):
        from rtfm.core.models import Chunk

        lib, root = project
        kept = Chunk(id="b-1", content="real text here", book_title="B",
                     book_slug="b", book_file="doc.html", page_start=1,
                     page_end=1, content_chars=14, content_hash="h1")
        blank = Chunk(id="b-2", content="   \n  ", book_title="B",
                      book_slug="b", book_file="doc.html", page_start=1,
                      page_end=1, content_chars=0, content_hash="h2")
        stats = lib._index_chunks([kept, blank], corpus="c", metadata={})

        assert stats["chunks"] == 1
        rows = lib._get_conn().execute(
            "SELECT chunk_id FROM chunks").fetchall()
        assert [r[0] for r in rows] == ["b:b-1"]

    def test_a_document_of_nothing_but_blanks_indexes_nothing(self, project):
        from rtfm.core.models import Chunk

        lib, root = project
        blank = Chunk(id="x-1", content="", book_title="X", book_slug="x",
                      book_file="empty.html", page_start=1, page_end=1,
                      content_chars=0, content_hash="h")
        assert lib._index_chunks([blank], corpus="c", metadata={})["chunks"] == 0

    def test_reconcile_purges_the_ones_already_stored(self, project, tmp_path):
        from rtfm.core.reconcile import purge_empty_chunks

        lib, root = project
        conn = lib._get_conn()
        conn.execute("INSERT INTO books (slug, title, filename, corpus) "
                     "VALUES ('b', 'B', 'doc.html', 'c')")
        conn.execute("INSERT INTO chunks (chunk_id, book_id, content) "
                     "VALUES ('b-1', 1, 'real text')")
        conn.execute("INSERT INTO chunks (chunk_id, book_id, content) "
                     "VALUES ('b-2', 1, '')")
        conn.commit()

        assert purge_empty_chunks(conn) == 1
        assert [r[0] for r in conn.execute("SELECT chunk_id FROM chunks")] == ["b-1"]
        assert conn.execute(
            "SELECT chunk_count FROM books WHERE slug='b'").fetchone()[0] == 1
