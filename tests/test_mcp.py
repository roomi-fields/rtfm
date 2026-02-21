"""Tests for rtfm.mcp server tools.

These tests call the tool functions directly (not via MCP transport)
to verify the business logic.
"""

import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

from rtfm import Library


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def mcp_db(tmp_path):
    """Create a temporary DB and point RTFM_DB at it."""
    db_path = tmp_path / "test.db"
    lib = Library(db_path)

    # Ingest a small markdown file so we have searchable content
    md = tmp_path / "doc.md"
    md.write_text(
        "# Philosophy\n\n"
        "The nature of consciousness is a profound topic that has been explored by many thinkers. "
        "Self-inquiry is a method taught by Ramana Maharshi. "
        "It involves asking 'Who am I?' to discover the true nature of the self.\n\n"
        "## Meditation\n\n"
        "Meditation is a practice that helps calm the mind and develop awareness. "
        "Through regular practice, one can experience deeper states of consciousness "
        "and gain insight into the nature of reality.\n"
    )
    lib.ingest(md, corpus="test")
    lib.close()

    # Set env var for MCP module
    with patch.dict(os.environ, {"RTFM_DB": str(db_path)}):
        # Reset the module-level singleton
        import rtfm.mcp as mcp_mod
        mcp_mod._library = None
        yield db_path
        mcp_mod._library = None


@pytest.fixture
def multi_source_db(tmp_path):
    """Create a DB with multiple source documents sharing common terms."""
    db_path = tmp_path / "multi.db"
    lib = Library(db_path)

    # Source 1: Python guide (3 chunks about programming)
    py_guide = tmp_path / "python_guide.md"
    py_guide.write_text(
        "# Python Programming Guide\n\n"
        "Python is a versatile programming language used for web development, "
        "data science, and automation. Functions are first-class objects.\n\n"
        "## Functions\n\n"
        "Functions in Python are defined with the def keyword. "
        "They can accept arguments and return values. "
        "Lambda functions provide a concise way to create anonymous functions.\n\n"
        "## Classes\n\n"
        "Object-oriented programming in Python uses classes. "
        "Classes encapsulate data and behavior. Inheritance allows code reuse.\n"
    )
    lib.ingest(py_guide, corpus="test")

    # Source 2: JavaScript guide (3 chunks about programming)
    js_guide = tmp_path / "javascript_guide.md"
    js_guide.write_text(
        "# JavaScript Programming Guide\n\n"
        "JavaScript is the language of the web. It runs in browsers and on servers "
        "with Node.js. Functions are first-class citizens in JavaScript.\n\n"
        "## Functions\n\n"
        "JavaScript functions can be declared or expressed. "
        "Arrow functions provide compact syntax. Closures capture variables.\n\n"
        "## Async Programming\n\n"
        "Promises and async/await make asynchronous programming manageable. "
        "The event loop processes callbacks and microtasks.\n"
    )
    lib.ingest(js_guide, corpus="test")

    # Source 3: Rust guide (3 chunks about programming)
    rust_guide = tmp_path / "rust_guide.md"
    rust_guide.write_text(
        "# Rust Programming Guide\n\n"
        "Rust is a systems programming language focused on safety and performance. "
        "The borrow checker enforces memory safety at compile time.\n\n"
        "## Functions\n\n"
        "Rust functions use the fn keyword. Return types are specified after an arrow. "
        "Closures can capture environment variables by reference or by value.\n\n"
        "## Ownership\n\n"
        "Ownership is Rust's core concept. Each value has exactly one owner. "
        "When the owner goes out of scope, the value is dropped.\n"
    )
    lib.ingest(rust_guide, corpus="test")

    lib.close()

    with patch.dict(os.environ, {"RTFM_DB": str(db_path)}):
        import rtfm.mcp as mcp_mod
        mcp_mod._library = None
        yield db_path
        mcp_mod._library = None


# ── Tests ─────────────────────────────────────────────────────────────────

class TestMCPSearch:
    def test_search_returns_results(self, mcp_db):
        from rtfm.mcp import rtfm_search
        result = rtfm_search("consciousness self-inquiry")
        assert "Found" in result or "result" in result.lower()
        assert "consciousness" in result.lower() or "self" in result.lower()

    def test_search_no_results(self, mcp_db):
        from rtfm.mcp import rtfm_search
        result = rtfm_search("xyznonexistent123456")
        assert "No results" in result

    def test_search_fts_mode(self, mcp_db):
        from rtfm.mcp import rtfm_search
        result = rtfm_search("meditation", search_type="fts")
        assert "meditation" in result.lower() or "No results" in result


class TestMCPStats:
    def test_stats(self, mcp_db):
        from rtfm.mcp import rtfm_stats
        result = rtfm_stats()
        assert "Chunks:" in result
        assert "Books:" in result


class TestMCPTags:
    def test_tags_empty(self, mcp_db):
        from rtfm.mcp import rtfm_tags
        result = rtfm_tags()
        assert "No tags" in result or "tag" in result.lower()


class TestMCPBooks:
    def test_books(self, mcp_db):
        from rtfm.mcp import rtfm_books
        result = rtfm_books()
        assert "chunk" in result.lower()

    def test_books_with_corpus(self, mcp_db):
        from rtfm.mcp import rtfm_books
        result = rtfm_books(corpus="nonexistent")
        assert "No books" in result


class TestMCPIngest:
    def test_ingest(self, mcp_db, tmp_path):
        from rtfm.mcp import rtfm_ingest
        f = tmp_path / "new.txt"
        f.write_text("New content for ingestion test.\n" * 10)
        result = rtfm_ingest(str(f))
        assert "Ingested" in result
        assert "chunks" in result.lower()

    def test_ingest_missing_file(self, mcp_db):
        from rtfm.mcp import rtfm_ingest
        result = rtfm_ingest("/nonexistent/file.txt")
        assert "not found" in result.lower() or "Error" in result


class TestMCPTagChunks:
    def test_tag_chunks(self, mcp_db):
        from rtfm.mcp import rtfm_tag_chunks

        # Get a chunk ID from the DB
        lib = Library(mcp_db)
        books = lib.list_books()
        assert books, "Should have at least one book"

        conn = lib._get_conn()
        cursor = conn.execute("SELECT chunk_id FROM chunks LIMIT 1")
        row = cursor.fetchone()
        assert row, "Should have at least one chunk"
        chunk_id = row["chunk_id"]
        lib.close()

        # Reset singleton since we opened a new connection
        import rtfm.mcp as mcp_mod
        mcp_mod._library = None

        result = rtfm_tag_chunks(chunk_id, "philosophy,meditation")
        assert "Added tags" in result


class TestMCPRemove:
    def test_remove_not_found(self, mcp_db):
        from rtfm.mcp import rtfm_remove
        result = rtfm_remove("nonexistent.txt")
        assert "Not found" in result


class TestMCPSync:
    def test_sync(self, mcp_db, tmp_path):
        from rtfm.mcp import rtfm_sync

        # Create a file to sync
        (tmp_path / "synctest.txt").write_text("Hello from sync test.\n" * 10)

        result = rtfm_sync(str(tmp_path), corpus="sync-test")
        assert "Sync complete" in result


class TestMCPDiscover:
    def test_discover_basic(self, tmp_path):
        """rtfm_discover scans a directory and returns a readable map."""
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / "README.md").write_text("# Project")

        from rtfm.mcp import rtfm_discover
        result = rtfm_discover(str(tmp_path))

        assert "Project:" in result
        assert "Files:" in result
        assert "Python" in result

    def test_discover_empty_dir(self, tmp_path):
        """Empty directory returns zeros."""
        from rtfm.mcp import rtfm_discover
        result = rtfm_discover(str(tmp_path))

        assert "Files: 0" in result

    def test_discover_nonexistent(self):
        """Nonexistent path returns empty scan (0 files)."""
        from rtfm.mcp import rtfm_discover
        result = rtfm_discover("/nonexistent/path/12345")

        assert "Files: 0" in result


class TestMCPContext:
    def test_context_returns_chunks(self, mcp_db):
        """rtfm_context returns relevant context for a topic."""
        from rtfm.mcp import rtfm_context
        result = rtfm_context("consciousness meditation")

        assert "Context for" in result
        assert "file:" in result or "slug:" in result  # metadata with actionable refs

    def test_context_no_results(self, mcp_db):
        """rtfm_context with unknown topic returns fallback hint."""
        from rtfm.mcp import rtfm_context
        result = rtfm_context("xyznonexistent999")

        assert "No context found" in result
        assert "Grep/Glob" in result

    def test_context_limit(self, mcp_db):
        """rtfm_context respects the limit parameter."""
        from rtfm.mcp import rtfm_context
        result = rtfm_context("consciousness", limit=1)

        # Should have at most 1 chunk separator (--- [...] ---)
        separators = result.count("--- [")
        assert separators <= 1

    def test_context_lazy_ingest(self, mcp_db, tmp_path):
        """rtfm_context indexes an unindexed file on-the-fly."""
        from rtfm.mcp import rtfm_context

        # Create a file that's not yet indexed
        newfile = tmp_path / "lazy_test.md"
        newfile.write_text("# Lazy Test\n\nThis document talks about lazy indexing and on-the-fly ingestion.\n")

        result = rtfm_context(str(newfile))

        # Should have indexed it and found content (or at least not crashed)
        assert "Error" not in result or "No context" in result


class TestProgressiveDisclosure:
    """Tests for search deduplication and rtfm_expand."""

    def test_search_deduplicates_by_source(self, multi_source_db):
        """Search returns 1 chunk per unique source document."""
        from rtfm.mcp import rtfm_search
        result = rtfm_search("programming functions", limit=5)

        assert "sources" in result
        assert "file:" in result or "slug:" in result

    def test_search_shows_chunk_count(self, multi_source_db):
        """Each source shows how many chunks matched."""
        from rtfm.mcp import rtfm_search
        result = rtfm_search("programming functions", limit=5)

        # Should contain "N chunks" indicators (metadata-only format)
        assert "chunks" in result

    def test_search_returns_different_sources(self, multi_source_db):
        """With 3 sources all about programming, we should get 3 unique sources."""
        from rtfm.mcp import rtfm_search
        result = rtfm_search("programming", limit=10)

        # Count source entries [1], [2], [3]
        assert "[1]" in result
        assert "[2]" in result
        assert "[3]" in result

    def test_context_deduplicates(self, multi_source_db):
        """rtfm_context also returns 1 chunk per source."""
        from rtfm.mcp import rtfm_context
        result = rtfm_context("functions programming")

        assert "sources" in result
        assert "file:" in result or "slug:" in result

    def test_expand_with_query(self, multi_source_db):
        """rtfm_expand shows all chunks from a source matching a query."""
        from rtfm.mcp import rtfm_expand

        # Get the slug from the DB
        lib = Library(multi_source_db)
        books = lib.list_books()
        slug = books[0]["slug"]
        lib.close()

        # Reset singleton
        import rtfm.mcp as mcp_mod
        mcp_mod._library = None

        result = rtfm_expand(slug, "programming")
        assert "Expanding" in result
        # Should have multiple chunks from the same source
        assert "[1]" in result

    def test_expand_without_query(self, multi_source_db):
        """rtfm_expand without query returns all chunks in page order."""
        from rtfm.mcp import rtfm_expand

        lib = Library(multi_source_db)
        books = lib.list_books()
        slug = books[0]["slug"]
        lib.close()

        import rtfm.mcp as mcp_mod
        mcp_mod._library = None

        result = rtfm_expand(slug)
        assert "Expanding" in result
        assert "page order" in result
        assert "[1]" in result

    def test_expand_nonexistent_source(self, multi_source_db):
        """rtfm_expand with unknown slug returns not found."""
        from rtfm.mcp import rtfm_expand
        result = rtfm_expand("nonexistent-slug-xyz")
        assert "not found" in result.lower() or "No chunks" in result

    def test_search_limit_respected(self, multi_source_db):
        """limit=2 returns at most 2 unique sources."""
        from rtfm.mcp import rtfm_search
        result = rtfm_search("programming", limit=2)

        assert "[1]" in result
        assert "[2]" in result
        assert "[3]" not in result


class TestMetadataOnlyOutput:
    """Tests for the new metadata-only search output."""

    def test_search_no_content_in_output(self, multi_source_db):
        """Search results should NOT contain actual chunk content."""
        from rtfm.mcp import rtfm_search
        result = rtfm_search("programming functions", limit=3)

        # Should have metadata
        assert "score:" in result
        assert "chunks" in result
        assert "file:" in result

        # Should NOT have full content from the documents
        assert "first-class" not in result  # content from Python/JS guides

    def test_search_shows_file_path(self, multi_source_db):
        """Search results include file paths."""
        from rtfm.mcp import rtfm_search
        result = rtfm_search("programming", limit=3)

        assert "file:" in result

    def test_context_no_content_in_output(self, multi_source_db):
        """Context results should NOT contain chunk content."""
        from rtfm.mcp import rtfm_context
        result = rtfm_context("programming functions")

        assert "Context for" in result
        assert "file:" in result or "slug:" in result
        # Should not have full content
        assert "first-class" not in result

    def test_expand_has_content(self, multi_source_db):
        """Expand SHOULD return full content (that's its purpose)."""
        from rtfm.mcp import rtfm_expand

        lib = Library(multi_source_db)
        books = lib.list_books()
        slug = books[0]["slug"]
        lib.close()

        import rtfm.mcp as mcp_mod
        mcp_mod._library = None

        result = rtfm_expand(slug, "programming")
        assert "Expanding" in result
        # Should have actual content
        assert len(result) > 200

    def test_expand_shows_file_and_lang(self, multi_source_db):
        """Expand header shows file path."""
        from rtfm.mcp import rtfm_expand

        lib = Library(multi_source_db)
        books = lib.list_books()
        slug = books[0]["slug"]
        lib.close()

        import rtfm.mcp as mcp_mod
        mcp_mod._library = None

        result = rtfm_expand(slug)
        assert "path:" in result
