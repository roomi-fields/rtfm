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
    """Create a temporary DB with synced content and point RTFM_DB at it."""
    db_path = tmp_path / "test.db"
    lib = Library(db_path)

    # Create a markdown file with searchable content
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
    # Use sync to set sync_root (enables path resolution in expand)
    lib.sync(root=tmp_path, corpus="test", extensions={".md"}, generate_embeddings=False)
    lib.close()

    with patch.dict(os.environ, {"RTFM_DB": str(db_path)}):
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

    # Use sync to set sync_root
    lib.sync(root=tmp_path, corpus="test", extensions={".md"}, generate_embeddings=False)
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
        assert "sources for" in result
        assert "L" in result  # line markers (L42-58 format)

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
    def test_context_returns_results(self, mcp_db):
        """rtfm_context returns relevant context for a topic."""
        from rtfm.mcp import rtfm_context
        result = rtfm_context("consciousness meditation")

        assert "sources for" in result
        assert "L" in result  # line markers (L42-58 format)

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

        # Header reports source count
        assert "1 sources for" in result or "0 sources for" in result or "No context" in result

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
        """Search returns 1 best chunk per unique source document."""
        from rtfm.mcp import rtfm_search
        result = rtfm_search("programming functions", limit=5)

        assert "sources" in result
        assert "L" in result  # line markers

    def test_search_shows_also_line(self, multi_source_db):
        """Sources with multiple relevant chunks show '+' continuation line."""
        from rtfm.mcp import rtfm_search
        result = rtfm_search("programming functions", limit=5)

        # Each guide has 3 chunks; multiple should match "programming functions"
        # so we expect "+" lines for at least some sources
        assert "\n  + " in result or "L" in result

    def test_search_returns_different_sources(self, multi_source_db):
        """With 3 sources all about programming, we should get 3 unique sources."""
        from rtfm.mcp import rtfm_search
        result = rtfm_search("programming", limit=10)

        # 3 unique source files appear in the output
        assert "python_guide.md" in result
        assert "javascript_guide.md" in result
        assert "rust_guide.md" in result

    def test_context_deduplicates(self, multi_source_db):
        """rtfm_context also returns 1 chunk per source."""
        from rtfm.mcp import rtfm_context
        result = rtfm_context("functions programming")

        assert "sources" in result
        assert "L" in result  # line markers

    def test_expand_first_chunk(self, multi_source_db):
        """rtfm_expand without target returns first chunk with line numbers."""
        from rtfm.mcp import rtfm_expand

        root = multi_source_db.parent
        filepath = str(root / "python_guide.md")
        result = rtfm_expand(filepath)

        # Header: path > section [1/N]
        assert "python_guide.md" in result
        assert "[1/" in result
        # Content with line numbers (tab-separated)
        assert "\t" in result
        # Navigation hint
        assert "Next in file" in result

    def test_expand_with_query(self, multi_source_db):
        """rtfm_expand with query shows matching chunk with line numbers."""
        from rtfm.mcp import rtfm_expand

        root = multi_source_db.parent
        filepath = str(root / "python_guide.md")
        result = rtfm_expand(filepath, query="programming")

        assert "python_guide.md" in result
        assert "\t" in result  # line-numbered content

    def test_expand_with_target_section(self, multi_source_db):
        """rtfm_expand with target jumps to a specific section."""
        from rtfm.mcp import rtfm_expand

        root = multi_source_db.parent
        filepath = str(root / "python_guide.md")
        result = rtfm_expand(filepath, target="Functions")

        assert "Functions" in result
        assert "\t" in result
        # Functions is not the first section
        assert "[1/" not in result or "Functions" in result

    def test_expand_with_target_line(self, multi_source_db):
        """rtfm_expand with L<number> target jumps to correct chunk."""
        from rtfm.mcp import rtfm_expand

        root = multi_source_db.parent
        filepath = str(root / "python_guide.md")
        # L1 should land on the first chunk
        result = rtfm_expand(filepath, target="L1")

        assert "python_guide.md" in result
        assert "[1/" in result  # first chunk

    def test_expand_nonexistent_source(self, multi_source_db):
        """rtfm_expand with unknown path returns not found."""
        from rtfm.mcp import rtfm_expand
        result = rtfm_expand("/nonexistent/path/file.py")
        assert "not found" in result.lower()

    def test_expand_target_not_found(self, multi_source_db):
        """rtfm_expand with nonexistent target lists available sections."""
        from rtfm.mcp import rtfm_expand

        root = multi_source_db.parent
        filepath = str(root / "python_guide.md")
        result = rtfm_expand(filepath, target="NonexistentSection")

        assert "Target not found" in result
        assert "Available sections" in result

    def test_search_limit_respected(self, multi_source_db):
        """limit=2 returns at most 2 unique sources."""
        from rtfm.mcp import rtfm_search
        result = rtfm_search("programming", limit=2)

        assert "2 sources for" in result


class TestMetadataOnlyOutput:
    """Tests for the new metadata-only search output."""

    def test_search_no_content_in_output(self, multi_source_db):
        """Search results should NOT contain actual chunk content."""
        from rtfm.mcp import rtfm_search
        result = rtfm_search("programming functions", limit=3)

        # Should have metadata
        assert "L" in result  # line markers

        # Should NOT have full content from the documents
        assert "first-class" not in result  # content from Python/JS guides

    def test_search_shows_file_path(self, multi_source_db):
        """Search results include file paths (absolute, no 'file:' prefix)."""
        from rtfm.mcp import rtfm_search
        result = rtfm_search("programming", limit=3)

        # New format shows path directly, not "file: path"
        assert "_guide.md" in result

    def test_context_no_content_in_output(self, multi_source_db):
        """Context results should NOT contain chunk content."""
        from rtfm.mcp import rtfm_context
        result = rtfm_context("programming functions")

        assert "sources for" in result
        assert "L" in result  # line markers
        # Should not have full content
        assert "first-class" not in result

    def test_expand_has_content(self, multi_source_db):
        """Expand SHOULD return full content (that's its purpose)."""
        from rtfm.mcp import rtfm_expand

        root = multi_source_db.parent
        filepath = str(root / "python_guide.md")
        result = rtfm_expand(filepath, query="programming")

        # Should have actual content with line numbers
        assert len(result) > 200
        assert "\t" in result

    def test_expand_shows_path_in_header(self, multi_source_db):
        """Expand header shows file path and section."""
        from rtfm.mcp import rtfm_expand

        root = multi_source_db.parent
        filepath = str(root / "python_guide.md")
        result = rtfm_expand(filepath)

        # Header format: path > section [N/M]
        assert "python_guide.md" in result
        assert ">" in result

    def test_expand_navigation_hints(self, multi_source_db):
        """Expand shows navigation hints for next chunk."""
        from rtfm.mcp import rtfm_expand

        root = multi_source_db.parent
        filepath = str(root / "python_guide.md")
        result = rtfm_expand(filepath)

        assert "⏹" in result
        assert "Next in file" in result

    def test_expand_query_pagination(self, multi_source_db):
        """Expand with query supports offset pagination."""
        from rtfm.mcp import rtfm_expand

        root = multi_source_db.parent
        filepath = str(root / "python_guide.md")

        # First result
        result0 = rtfm_expand(filepath, query="programming", offset=0)
        assert "\t" in result0

        # High offset should give "no more results"
        result_high = rtfm_expand(filepath, query="programming", offset=100)
        assert "No more results" in result_high or "No chunks" in result_high


class TestResolveBookByPath:
    """Tests for _resolve_book_by_path helper."""

    def test_resolve_by_absolute_path(self, multi_source_db):
        """Resolve book using absolute file path via sync_root."""
        from rtfm.mcp import _resolve_book_by_path, _get_library

        lib = _get_library()
        conn = lib._get_conn()

        root = multi_source_db.parent
        filepath = str(root / "python_guide.md")
        row = _resolve_book_by_path(conn, filepath)

        assert row is not None
        assert row["filename"] == "python_guide.md"

    def test_resolve_nonexistent(self, multi_source_db):
        """Unknown path returns None."""
        from rtfm.mcp import _resolve_book_by_path, _get_library

        lib = _get_library()
        conn = lib._get_conn()

        row = _resolve_book_by_path(conn, "/nonexistent/file.py")
        assert row is None

    def test_resolve_relative_direct(self, multi_source_db):
        """Resolve book by exact match on relative filename."""
        from rtfm.mcp import _resolve_book_by_path, _get_library

        lib = _get_library()
        conn = lib._get_conn()

        # Relative filename stored by sync
        row = _resolve_book_by_path(conn, "python_guide.md")
        assert row is not None
        assert row["filename"] == "python_guide.md"


class TestRenderChunk:
    """Tests for _render_chunk helper."""

    def test_reads_file_lines(self, tmp_path):
        from rtfm.mcp import _render_chunk
        f = tmp_path / "test.py"
        f.write_text("line one\nline two\nline three\n")
        result = _render_chunk(str(f), 1, 3)
        lines = result.split("\n")
        assert len(lines) == 3
        assert "1" in lines[0] and "line one" in lines[0]
        assert "2" in lines[1] and "line two" in lines[1]
        assert "3" in lines[2] and "line three" in lines[2]
        assert "\t" in lines[0]

    def test_file_not_found(self):
        from rtfm.mcp import _render_chunk
        result = _render_chunk("/nonexistent/file.py", 1, 10)
        assert "not found" in result.lower()

    def test_no_path_returns_error(self):
        from rtfm.mcp import _render_chunk
        result = _render_chunk("", None, None)
        assert "not available" in result.lower()


class TestExpandCount:
    """Tests for the count parameter in rtfm_expand."""

    def test_count_default_one(self, multi_source_db):
        """Default count=1 returns exactly one chunk."""
        from rtfm.mcp import rtfm_expand

        root = multi_source_db.parent
        filepath = str(root / "python_guide.md")
        result = rtfm_expand(filepath)

        # Should show [1/N] (single chunk)
        assert "[1/" in result
        # No separator lines (only one chunk)
        assert "───" not in result

    def test_count_multiple(self, multi_source_db):
        """count=2 returns two consecutive chunks with separators."""
        from rtfm.mcp import rtfm_expand

        root = multi_source_db.parent
        filepath = str(root / "python_guide.md")
        result = rtfm_expand(filepath, count=2)

        # Should show range [1-2/N]
        assert "[1-2/" in result
        # Should have separator between chunks
        assert "───" in result

    def test_count_all(self, multi_source_db):
        """count=0 returns all chunks in file."""
        from rtfm.mcp import rtfm_expand

        root = multi_source_db.parent
        filepath = str(root / "python_guide.md")
        result = rtfm_expand(filepath, count=0)

        # End marker (last chunk, no "Next in file")
        assert "⏹" in result
        assert "Next in file" not in result

    def test_count_with_target(self, multi_source_db):
        """count with target starts from target chunk."""
        from rtfm.mcp import rtfm_expand

        root = multi_source_db.parent
        filepath = str(root / "python_guide.md")
        result = rtfm_expand(filepath, target="Functions", count=2)

        assert "Functions" in result
        # Should show separator if there's a second chunk
        assert "───" in result or "⏹" in result

    def test_count_exceeds_remaining(self, multi_source_db):
        """count larger than remaining chunks returns all remaining."""
        from rtfm.mcp import rtfm_expand

        root = multi_source_db.parent
        filepath = str(root / "python_guide.md")
        result = rtfm_expand(filepath, count=100)

        # Should get end marker (all chunks returned)
        assert "⏹" in result
        assert "Next in file" not in result

    def test_count_query_mode(self, multi_source_db):
        """count in query mode returns multiple relevant chunks."""
        from rtfm.mcp import rtfm_expand

        root = multi_source_db.parent
        filepath = str(root / "python_guide.md")
        result = rtfm_expand(filepath, query="programming", count=3)

        # Should contain content with line numbers
        assert "\t" in result


class TestExpandLineNumbersMatchFile:
    """Critical test: expand line numbers must match actual file lines.

    When an agent sees '     5\tsome content' in expand output, line 5 of the
    actual file MUST contain 'some content'.  Otherwise Edit/Read break.
    """

    def test_expand_lines_match_read(self, multi_source_db):
        """Every numbered line in expand output must match the actual file."""
        from rtfm.mcp import rtfm_expand

        root = multi_source_db.parent
        filepath = str(root / "python_guide.md")

        # Read the actual file
        with open(filepath) as f:
            file_lines = f.readlines()

        # Get expand output (all chunks)
        result = rtfm_expand(filepath, count=0)

        # Parse numbered lines from expand output
        for output_line in result.split("\n"):
            # Match lines like "     5\tcontent here"
            parts = output_line.split("\t", 1)
            if len(parts) == 2:
                num_str = parts[0].strip()
                content = parts[1]
                if num_str.isdigit():
                    line_num = int(num_str)
                    # Line numbers are 1-indexed
                    actual = file_lines[line_num - 1].rstrip("\n")
                    assert content == actual, (
                        f"Line {line_num} mismatch!\n"
                        f"  expand: {content!r}\n"
                        f"  file:   {actual!r}"
                    )

    def test_expand_lines_match_read_multiline_paragraphs(self, tmp_path):
        """Test with content that markdown parser would reformat."""
        from rtfm import Library

        db_path = tmp_path / "test_lines.db"
        lib = Library(db_path)

        # Create a markdown file with multi-line paragraphs that the parser
        # would normally collapse via ' '.join(p.split())
        md = tmp_path / "multiline.md"
        md.write_text(
            "# Introduction\n\n"
            "This is a paragraph that spans\n"
            "multiple lines in the source file.\n"
            "The markdown parser would normally\n"
            "collapse these into a single line.\n\n"
            "## Details\n\n"
            "Here is another paragraph with\n"
            "line breaks that should be\n"
            "preserved in the expand output.\n"
        )

        lib.sync(root=tmp_path, corpus="test", extensions={".md"},
                 generate_embeddings=False)
        lib.close()

        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"RTFM_DB": str(db_path)}):
            import rtfm.mcp as mcp_mod
            mcp_mod._library = None
            try:
                from rtfm.mcp import rtfm_expand

                # Read the actual file
                with open(md) as f:
                    file_lines = f.readlines()

                result = rtfm_expand(str(md), count=0)

                # Every numbered line must match
                for output_line in result.split("\n"):
                    parts = output_line.split("\t", 1)
                    if len(parts) == 2:
                        num_str = parts[0].strip()
                        content = parts[1]
                        if num_str.isdigit():
                            line_num = int(num_str)
                            actual = file_lines[line_num - 1].rstrip("\n")
                            assert content == actual, (
                                f"Line {line_num} mismatch!\n"
                                f"  expand: {content!r}\n"
                                f"  file:   {actual!r}"
                            )
            finally:
                mcp_mod._library = None


class TestSearchExpandEditWorkflow:
    """End-to-end test: search → expand → verify content can be used for Edit.

    Simulates the full agent workflow:
    1. rtfm_search to find relevant file
    2. rtfm_expand to read content with line numbers
    3. Extract a line from expand output
    4. Verify that exact string exists in the real file (Edit would succeed)
    """

    def test_search_expand_edit_roundtrip(self, multi_source_db):
        """Content from expand output can be found verbatim in the real file."""
        import re
        from rtfm.mcp import rtfm_search, rtfm_expand

        root = multi_source_db.parent

        # Step 1: Search
        search_result = rtfm_search("programming functions")
        assert "sources for" in search_result

        # Extract file path from search result (first result line)
        # Format: /path/to/file L<n>-<m> (section)
        path_match = re.search(r'^(/\S+\.md)', search_result, re.MULTILINE)
        assert path_match, f"Could not extract path from search result:\n{search_result}"
        filepath = path_match.group(1)
        assert os.path.isfile(filepath), f"Search returned non-existent path: {filepath}"

        # Step 2: Expand
        expand_result = rtfm_expand(filepath, count=0)
        assert "\t" in expand_result

        # Step 3: Extract lines from expand output
        expand_lines = {}
        for output_line in expand_result.split("\n"):
            parts = output_line.split("\t", 1)
            if len(parts) == 2:
                num_str = parts[0].strip()
                if num_str.isdigit():
                    expand_lines[int(num_str)] = parts[1]

        assert len(expand_lines) > 0, "No numbered lines in expand output"

        # Step 4: Verify each line matches the real file (Edit would work)
        with open(filepath) as f:
            real_content = f.read()
        real_lines = real_content.splitlines()

        for line_num, expand_content in expand_lines.items():
            real_line = real_lines[line_num - 1]
            assert expand_content == real_line, (
                f"Line {line_num}: expand content doesn't match file!\n"
                f"  expand: {expand_content!r}\n"
                f"  file:   {real_line!r}\n"
                f"  An Edit using this content would FAIL."
            )

        # Step 5: Verify non-empty lines can be used as old_string for Edit
        non_empty = [v for v in expand_lines.values() if v.strip()]
        assert len(non_empty) > 0
        for line_content in non_empty[:3]:  # Check first 3 non-empty
            assert line_content in real_content, (
                f"Content from expand not found in file (Edit old_string would fail):\n"
                f"  {line_content!r}"
            )
