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
            assert result == {"reattached": 1, "dropped": 0,
                              "undecidable": 0, "duplicates": 0}
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

    def test_a_book_with_no_filename_is_left_alone(self, project, tmp_path):
        """Nothing to look for means nothing can be concluded."""
        lib, root = project
        _book(lib, "nameless", "", "c")

        queue = Queue(str(tmp_path / "library.db"))
        try:
            result = repair_untracked_books(lib, queue, lambda m: None)
        finally:
            queue.close()
        assert result == {"reattached": 0, "dropped": 0,
                          "undecidable": 1, "duplicates": 0}
        assert lib.list_books(corpus="c")

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


class TestACorpusThatNoLongerExists:
    """Renaming a corpus in the config leaves its old name behind with no
    source directory. Those entries are not undecidable — they are somewhere
    on disk, or nowhere. 871 of them sat on one project."""

    def test_a_file_found_under_another_directory_is_re_indexed(
            self, project, tmp_path):
        lib, root = project
        (root / "kept.md").write_text("still here\n")
        _book(lib, "old-name", "kept.md", "a-corpus-that-was-renamed")

        queue = Queue(str(tmp_path / "library.db"))
        try:
            result = repair_untracked_books(lib, queue, lambda m: None)
        finally:
            queue.close()
        assert result["reattached"] == 1
        assert result["undecidable"] == 0

    def test_a_file_found_nowhere_is_dropped(self, project, tmp_path):
        lib, root = project
        _book(lib, "old-name", "nowhere.md", "a-corpus-that-was-renamed")

        queue = Queue(str(tmp_path / "library.db"))
        try:
            result = repair_untracked_books(lib, queue, lambda m: None)
        finally:
            queue.close()
        assert result["dropped"] == 1
        assert lib.list_books() == []


class TestAnImpossiblePathIsNotAnUnreadableOne:
    """One index held two entries whose "filename" was a queue payload —
    591 characters of JSON. Asking the disk about it raises, and reading that
    as "this location cannot be read" would protect the corruption for ever.
    """

    def test_a_name_too_long_to_exist_counts_as_absent(self, project, tmp_path):
        lib, root = project
        _book(lib, "junk", "{" + "x" * 600 + "}", "c")

        queue = Queue(str(tmp_path / "library.db"))
        try:
            result = repair_untracked_books(lib, queue, lambda m: None)
        finally:
            queue.close()
        assert result["dropped"] == 1
        assert result["undecidable"] == 0

    def test_a_location_that_cannot_be_read_still_holds_the_book(self, project):
        from rtfm.core.reconcile import _find_under

        class Unreadable:
            def __truediv__(self, other):
                return self

            def exists(self):
                raise OSError(5, "Input/output error")

        home, unreadable = _find_under([Unreadable()], "a.md")
        assert home is None
        assert unreadable is True


class TestReAttachingActuallyAttaches:
    """Queueing an indexing job was not enough.

    An untracked file is given a *fresh* identity when it is indexed, so the
    job created a second document and left the first orphaned exactly as
    before — 748 of them came back on the next audit, having been "repaired".
    The tracking row has to be written here, pointing at the identity the
    document already has.
    """

    def test_the_document_is_tracked_immediately(self, project, tmp_path):
        lib, root = project
        (root / "here.md").write_text("still on disk\n")
        _book(lib, "its-identity", "here.md", "c")

        queue = Queue(str(tmp_path / "library.db"))
        try:
            repair_untracked_books(lib, queue, lambda m: None)
        finally:
            queue.close()

        tracked = lib.list_indexed_files(corpus="c")
        assert tracked["here.md"]["book_slug"] == "its-identity"
        assert untracked_books(lib._get_conn()) == []

    def test_the_content_is_re_read_rather_than_trusted(self, project, tmp_path):
        """An empty hash never matches the file, so the next scan re-indexes
        it even if the queued job is lost."""
        lib, root = project
        (root / "here.md").write_text("still on disk\n")
        _book(lib, "its-identity", "here.md", "c")

        queue = Queue(str(tmp_path / "library.db"))
        try:
            repair_untracked_books(lib, queue, lambda m: None)
        finally:
            queue.close()

        assert lib.list_indexed_files(corpus="c")["here.md"]["file_hash"] == ""

    def test_running_it_twice_changes_nothing(self, project, tmp_path):
        lib, root = project
        (root / "here.md").write_text("still on disk\n")
        _book(lib, "its-identity", "here.md", "c")

        queue = Queue(str(tmp_path / "library.db"))
        try:
            first = repair_untracked_books(lib, queue, lambda m: None)
            second = repair_untracked_books(lib, queue, lambda m: None)
        finally:
            queue.close()
        assert first["reattached"] == 1
        assert second == {"reattached": 0, "dropped": 0,
                          "undecidable": 0, "duplicates": 0}


class TestADuplicateIsNotALostDocument:
    """Two entries for one file.

    The repair in 0.35.0 indexed an untracked file without attaching it, so
    the file was given a second identity and the first stayed orphaned — 748
    of them. An untracked entry whose path is *already tracked under another
    identity* is not a document that lost its tracking; it is a leftover that
    only duplicates the live one's answers.
    """

    def test_the_duplicate_goes_and_the_tracked_one_stays(self, project, tmp_path):
        lib, root = project
        (root / "doc.md").write_text("content\n")
        _book(lib, "doc-md", "doc.md", "c")          # the leftover
        _book(lib, "doc", "doc.md", "c")             # the live one
        lib.update_indexed_file(filepath="doc.md", file_hash="h",
                                corpus="c", book_slug="doc")

        queue = Queue(str(tmp_path / "library.db"))
        try:
            result = repair_untracked_books(lib, queue, lambda m: None)
        finally:
            queue.close()

        assert result["duplicates"] == 1
        assert result["reattached"] == 0
        assert {b["slug"] for b in lib.list_books(corpus="c")} == {"doc"}

    def test_a_genuinely_untracked_document_is_still_re_attached(
            self, project, tmp_path):
        """The distinction must not swallow the case it was built for."""
        lib, root = project
        (root / "alone.md").write_text("content\n")
        _book(lib, "alone", "alone.md", "c")

        queue = Queue(str(tmp_path / "library.db"))
        try:
            result = repair_untracked_books(lib, queue, lambda m: None)
        finally:
            queue.close()

        assert result["reattached"] == 1
        assert result["duplicates"] == 0
        assert lib.list_indexed_files(corpus="c")["alone.md"]["book_slug"] == "alone"

    def test_one_pass_settles_everything(self, project, tmp_path):
        """After a repair the audit must come back clean — 748 came back
        twice before this."""
        lib, root = project
        (root / "doc.md").write_text("content\n")
        _book(lib, "doc-md", "doc.md", "c")
        _book(lib, "doc", "doc.md", "c")
        lib.update_indexed_file(filepath="doc.md", file_hash="h",
                                corpus="c", book_slug="doc")
        _book(lib, "orphan", "orphan.md", "c")
        (root / "orphan.md").write_text("also here\n")

        queue = Queue(str(tmp_path / "library.db"))
        try:
            repair_untracked_books(lib, queue, lambda m: None)
        finally:
            queue.close()

        assert untracked_books(lib._get_conn()) == []
