"""Tests for rtfm.core.library."""

import pytest
from pathlib import Path
from rtfm import Library
from rtfm.core.models import Chunk


class TestLibraryInit:
    """Tests for Library initialization."""

    def test_create_new_database(self, temp_db):
        """Test creating a new database."""
        lib = Library(temp_db)
        assert temp_db.exists()
        stats = lib.get_stats()
        assert stats["chunks"] == 0

    def test_open_existing_database(self, temp_db):
        """Test opening an existing database."""
        lib1 = Library(temp_db)
        lib1.close()

        lib2 = Library(temp_db)
        assert lib2 is not None
        lib2.close()


class TestLibraryIngest:
    """Tests for document ingestion."""

    def test_ingest_markdown(self, library, sample_markdown):
        """Test ingesting a markdown file."""
        result = library.ingest(sample_markdown)

        assert result["chunks"] > 0
        stats = library.get_stats()
        assert stats["chunks"] == result["chunks"]

    def test_ingest_with_corpus(self, library, sample_markdown):
        """Test ingesting with corpus tag."""
        library.ingest(sample_markdown, corpus="test-corpus")

        corpora = library.list_corpora()
        corpus_names = [c["corpus"] for c in corpora]
        assert "test-corpus" in corpus_names

    def test_ingest_xml(self, library, sample_cgi_xml):
        """Test ingesting XML file."""
        result = library.ingest(sample_cgi_xml, corpus="cgi")

        assert result["chunks"] == 2  # Two articles in sample
        books = library.list_books(corpus="cgi")
        assert len(books) == 1

    def test_ingest_html(self, library, sample_bofip_html):
        """Test ingesting HTML file."""
        result = library.ingest(sample_bofip_html, corpus="bofip")

        assert result["chunks"] >= 1
        books = library.list_books(corpus="bofip")
        assert len(books) == 1

    def test_ingest_idempotent(self, library, sample_markdown):
        """Test that re-ingesting same file replaces chunks."""
        result1 = library.ingest(sample_markdown)
        result2 = library.ingest(sample_markdown)

        # Should have same number, not double
        stats = library.get_stats()
        assert stats["chunks"] == result1["chunks"]
        assert result1["chunks"] == result2["chunks"]


class TestLibrarySearch:
    """Tests for search functionality."""

    def test_search_basic(self, library, sample_cgi_xml):
        """Test basic search."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        results = library.search("impôt revenu")
        assert results.total_found > 0
        assert len(results) > 0

    def test_search_returns_relevant(self, library, sample_cgi_xml):
        """Test search returns relevant results."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        results = library.search("exonération bénéfices")
        assert results.total_found > 0

        # Should find the article about exoneration
        content = results.results[0].chunk.content
        assert "exonération" in content.lower() or "bénéfices" in content.lower()

    def test_search_with_corpus_filter(self, library, sample_cgi_xml, sample_bofip_html):
        """Test search filtered by corpus."""
        library.ingest(sample_cgi_xml, corpus="cgi")
        library.ingest(sample_bofip_html, corpus="bofip")

        # Search only in CGI
        results = library.search("impôt", corpus="cgi")
        cgi_books = library.list_books(corpus="cgi")
        cgi_slugs = [b["slug"] for b in cgi_books]

        for r in results:
            # All results should be from CGI corpus
            assert r.chunk.book_slug in cgi_slugs

    def test_search_with_limit(self, library, sample_cgi_xml):
        """Test search with result limit."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        results = library.search("impôt", limit=1)
        assert len(results) <= 1

    def test_search_no_results(self, library, sample_cgi_xml):
        """Test search with no matching results."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        results = library.search("xyznonexistent123")
        assert results.total_found == 0

    def test_search_special_characters(self, library, sample_cgi_xml):
        """Test search handles special characters."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        # These should not crash
        results = library.search("self-realization")
        results = library.search("article 44")
        results = library.search("CGI art")


class TestLibraryBooks:
    """Tests for book management."""

    def test_list_books_empty(self, library):
        """Test listing books when empty."""
        books = library.list_books()
        assert books == []

    def test_list_books(self, library, sample_cgi_xml, sample_bofip_html):
        """Test listing all books."""
        library.ingest(sample_cgi_xml, corpus="cgi")
        library.ingest(sample_bofip_html, corpus="bofip")

        books = library.list_books()
        assert len(books) == 2

    def test_list_books_by_corpus(self, library, sample_cgi_xml, sample_bofip_html):
        """Test listing books filtered by corpus."""
        library.ingest(sample_cgi_xml, corpus="cgi")
        library.ingest(sample_bofip_html, corpus="bofip")

        cgi_books = library.list_books(corpus="cgi")
        assert len(cgi_books) == 1

        bofip_books = library.list_books(corpus="bofip")
        assert len(bofip_books) == 1


class TestLibraryCorpora:
    """Tests for corpus management."""

    def test_list_corpora_empty(self, library):
        """Test listing corpora when empty."""
        corpora = library.list_corpora()
        assert corpora == []

    def test_list_corpora(self, library, sample_cgi_xml, sample_bofip_html):
        """Test listing all corpora."""
        library.ingest(sample_cgi_xml, corpus="cgi")
        library.ingest(sample_bofip_html, corpus="bofip")

        corpora = library.list_corpora()
        corpus_names = {c["corpus"] for c in corpora}
        assert corpus_names == {"cgi", "bofip"}


class TestLibraryStats:
    """Tests for statistics."""

    def test_stats_empty(self, library):
        """Test stats on empty library."""
        stats = library.get_stats()

        assert stats["chunks"] == 0
        assert stats["books"] == 0

    def test_stats_with_data(self, library, sample_cgi_xml):
        """Test stats with data."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        stats = library.get_stats()
        assert stats["chunks"] == 2
        assert stats["books"] == 1
        assert stats["corpora"] == 1


class TestChunkIdUniqueness:
    """Regression: content-hash chunk ids must not collide on the global
    UNIQUE(chunk_id) constraint (once aborted whole ingests — 69k on one repo)."""

    def test_duplicate_content_within_book_does_not_collide(self, library):
        dup = "identical boilerplate footer"
        chunks = [
            Chunk(id="abc123def456", content=dup, book_title="B", book_slug="b",
                  page_start=1, page_end=1, content_chars=len(dup)),
            Chunk(id="abc123def456", content=dup, book_title="B", book_slug="b",
                  page_start=2, page_end=2, content_chars=len(dup)),
        ]
        res = library.ingest_chunks(chunks, corpus="t")
        assert res["chunks"] == 2  # both stored — no IntegrityError

    def test_same_content_across_books_does_not_collide(self, library):
        dup = "a shared quotation"
        library.ingest_chunks(
            [Chunk(id="hh", content=dup, book_title="One", book_slug="one",
                   page_start=1, page_end=1, content_chars=len(dup))], corpus="t")
        library.ingest_chunks(
            [Chunk(id="hh", content=dup, book_title="Two", book_slug="two",
                   page_start=1, page_end=1, content_chars=len(dup))], corpus="t")
        conn = library._get_conn()
        ids = [r[0] for r in conn.execute("SELECT chunk_id FROM chunks")]
        assert len(ids) == 2 and len(set(ids)) == 2  # distinct, scoped by slug
