"""Tests for biblirag.core.models."""

import json
import pytest
from biblirag.core.models import Chunk, SearchResult, SearchResults


class TestChunk:
    """Tests for Chunk dataclass."""

    def test_chunk_creation_minimal(self):
        """Test creating a chunk with minimal fields."""
        chunk = Chunk(
            id="test-001",
            content="Test content",
            book_title="Test Book",
            book_slug="test-book",
            page_start=1,
            page_end=1,
        )
        assert chunk.id == "test-001"
        assert chunk.content == "Test content"
        assert chunk.book_title == "Test Book"
        assert chunk.metadata == {}

    def test_chunk_creation_full(self):
        """Test creating a chunk with all fields."""
        chunk = Chunk(
            id="test-001",
            content="Test content",
            book_title="Test Book",
            book_slug="test-book",
            book_file="test.md",
            chapter_title="Chapter 1",
            chapter_num=1,
            page_start=10,
            page_end=15,
            paragraph=3,
            section_type="section",
            content_chars=12,
            content_hash="abc123",
            metadata={"custom": "data"},
        )
        assert chunk.chapter_title == "Chapter 1"
        assert chunk.page_start == 10
        assert chunk.metadata == {"custom": "data"}

    def test_chunk_to_dict(self):
        """Test converting chunk to dictionary."""
        chunk = Chunk(
            id="test-001",
            content="Test content",
            book_title="Test Book",
            book_slug="test-book",
            page_start=1,
            page_end=1,
            metadata={"key": "value"},
        )
        d = chunk.to_dict()
        assert d["id"] == "test-001"
        assert d["content"] == "Test content"
        assert d["metadata"] == {"key": "value"}

    def test_chunk_source_property(self):
        """Test source property."""
        chunk = Chunk(
            id="test-001",
            content="Test",
            book_title="My Book",
            book_slug="my-book",
            page_start=1,
            page_end=1,
            chapter_title="Chapter 1",
        )
        assert "My Book" in chunk.source
        assert "Chapter 1" in chunk.source

    def test_chunk_page_property(self):
        """Test page property."""
        chunk = Chunk(
            id="test-001",
            content="Test",
            book_title="Book",
            book_slug="book",
            page_start=5,
            page_end=5,
        )
        assert chunk.page == "p.5"

        chunk2 = Chunk(
            id="test-002",
            content="Test",
            book_title="Book",
            book_slug="book",
            page_start=5,
            page_end=10,
        )
        assert chunk2.page == "pp.5-10"

    def test_chunk_auto_content_chars(self):
        """Test automatic content_chars calculation."""
        chunk = Chunk(
            id="test-001",
            content="Hello World",
            book_title="Book",
            book_slug="book",
            page_start=1,
            page_end=1,
        )
        assert chunk.content_chars == 11


class TestSearchResult:
    """Tests for SearchResult dataclass."""

    def test_search_result_creation(self):
        """Test creating a search result."""
        chunk = Chunk(
            id="test-001",
            content="Test content",
            book_title="Test Book",
            book_slug="test-book",
            page_start=1,
            page_end=1,
        )
        result = SearchResult(chunk=chunk, score=0.95, rank=1)
        assert result.chunk.id == "test-001"
        assert result.score == 0.95
        assert result.rank == 1

    def test_search_result_to_dict(self):
        """Test converting search result to dictionary."""
        chunk = Chunk(
            id="test-001",
            content="Test content",
            book_title="Test Book",
            book_slug="test-book",
            page_start=1,
            page_end=1,
        )
        result = SearchResult(chunk=chunk, score=0.95, rank=1)
        d = result.to_dict()
        assert d["score"] == 0.95
        assert d["rank"] == 1
        assert d["chunk"]["id"] == "test-001"

    def test_search_result_convenience_properties(self):
        """Test convenience property accessors."""
        chunk = Chunk(
            id="test-001",
            content="Test content here",
            book_title="My Book",
            book_slug="my-book",
            page_start=5,
            page_end=5,
            chapter_title="Chapter 1",
            tags=["tag1", "tag2"],
        )
        result = SearchResult(chunk=chunk, score=0.9, rank=1)

        assert result.content == "Test content here"
        assert result.book_title == "My Book"
        assert result.chapter_title == "Chapter 1"
        assert result.tags == ["tag1", "tag2"]
        assert "My Book" in result.source


class TestSearchResults:
    """Tests for SearchResults collection."""

    def test_search_results_empty(self):
        """Test empty search results."""
        results = SearchResults(query="test", results=[], total_found=0)
        assert len(results) == 0
        assert results.total_found == 0

    def test_search_results_iteration(self):
        """Test iterating over search results."""
        chunks = [
            Chunk(
                id=f"test-{i}",
                content=f"Content {i}",
                book_title="Book",
                book_slug="book",
                page_start=i,
                page_end=i,
            )
            for i in range(3)
        ]
        search_results = [
            SearchResult(chunk=c, score=1.0 - i * 0.1, rank=i + 1)
            for i, c in enumerate(chunks)
        ]
        results = SearchResults(query="test", results=search_results, total_found=3)

        assert len(results) == 3
        ids = [r.chunk.id for r in results]
        assert ids == ["test-0", "test-1", "test-2"]

    def test_search_results_indexing(self):
        """Test indexing into results."""
        chunk = Chunk(
            id="test-001",
            content="Test",
            book_title="Book",
            book_slug="book",
            page_start=1,
            page_end=1,
        )
        result = SearchResult(chunk=chunk, score=0.9, rank=1)
        results = SearchResults(query="test", results=[result], total_found=1)

        assert results[0].chunk.id == "test-001"

    def test_search_results_to_dict(self):
        """Test converting results to dictionary."""
        chunk = Chunk(
            id="test-001",
            content="Test",
            book_title="Book",
            book_slug="book",
            page_start=1,
            page_end=1,
        )
        result = SearchResult(chunk=chunk, score=0.9, rank=1)
        results = SearchResults(query="test query", results=[result], total_found=1)

        d = results.to_dict()
        assert d["query"] == "test query"
        assert d["total_found"] == 1
        assert len(d["results"]) == 1

    def test_search_results_to_json(self):
        """Test JSON serialization."""
        chunk = Chunk(
            id="test-001",
            content="Test",
            book_title="Book",
            book_slug="book",
            page_start=1,
            page_end=1,
        )
        result = SearchResult(chunk=chunk, score=0.9, rank=1)
        results = SearchResults(query="test", results=[result], total_found=1)

        json_str = results.to_json()
        parsed = json.loads(json_str)
        assert parsed["query"] == "test"

    def test_search_results_to_markdown(self):
        """Test markdown export."""
        chunk = Chunk(
            id="test-001",
            content="Test content here",
            book_title="My Book",
            book_slug="my-book",
            page_start=5,
            page_end=5,
            chapter_title="Chapter 1",
        )
        result = SearchResult(chunk=chunk, score=0.9, rank=1)
        results = SearchResults(query="test", results=[result], total_found=1)

        md = results.to_markdown()
        assert "Search" in md
        assert "My Book" in md
        assert "Test content here" in md

    def test_search_results_to_prompt(self):
        """Test prompt format export."""
        chunk = Chunk(
            id="test-001",
            content="Important information",
            book_title="Reference Book",
            book_slug="ref-book",
            page_start=1,
            page_end=1,
        )
        result = SearchResult(chunk=chunk, score=0.9, rank=1)
        results = SearchResults(query="info", results=[result], total_found=1)

        prompt = results.to_prompt()
        assert "<search_results" in prompt
        assert "Important information" in prompt
        assert "Reference Book" in prompt
        assert "</search_results>" in prompt
