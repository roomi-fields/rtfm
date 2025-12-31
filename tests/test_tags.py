"""Tests for tag management."""

import pytest
from biblirag import Library


class TestTagManagement:
    """Tests for tag CRUD operations."""

    def test_list_tags_empty(self, library):
        """Test listing tags when none exist."""
        tags = library.list_tags()
        assert tags == []

    def test_add_tags_to_chunk(self, library, sample_cgi_xml):
        """Test adding tags to a chunk."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        # Get a chunk ID
        books = library.list_books()
        assert len(books) > 0

        # Search to get a chunk
        results = library.search("impôt")
        assert len(results) > 0

        chunk_id = results[0].chunk.id

        # Add tags
        success = library.add_tags(chunk_id, ["fiscal", "important"])
        assert success

        # Verify tags were added
        tags = library.list_tags()
        tag_names = [t["tag"] for t in tags]
        assert "fiscal" in tag_names
        assert "important" in tag_names

    def test_remove_tags_from_chunk(self, library, sample_cgi_xml):
        """Test removing tags from a chunk."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        results = library.search("impôt")
        chunk_id = results[0].chunk.id

        # Add then remove tags
        library.add_tags(chunk_id, ["tag1", "tag2", "tag3"])
        library.remove_tags(chunk_id, ["tag2"])

        # Verify
        tags = library.list_tags()
        tag_names = [t["tag"] for t in tags]
        assert "tag1" in tag_names
        assert "tag2" not in tag_names
        assert "tag3" in tag_names

    def test_tag_chunks_by_corpus(self, library, sample_cgi_xml):
        """Test tagging all chunks in a corpus."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        count = library.tag_chunks(["legal", "cgi"], corpus="cgi")
        assert count == 2  # Two articles in sample

        tags = library.list_tags()
        tag_dict = {t["tag"]: t["count"] for t in tags}
        assert tag_dict.get("legal") == 2
        assert tag_dict.get("cgi") == 2

    def test_get_chunks_by_tag(self, library, sample_cgi_xml):
        """Test getting chunks by tag."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        # Tag only the first chunk
        results = library.search("impôt annuel")
        chunk_id = results[0].chunk.id
        library.add_tags(chunk_id, ["special"])

        # Get chunks by tag
        chunks = library.get_chunks_by_tag("special")
        assert len(chunks) == 1
        assert chunks[0].id == chunk_id

    def test_list_tags_by_corpus(self, library, sample_cgi_xml, sample_bofip_html):
        """Test listing tags filtered by corpus."""
        library.ingest(sample_cgi_xml, corpus="cgi")
        library.ingest(sample_bofip_html, corpus="bofip")

        # Tag each corpus differently
        library.tag_chunks(["legal"], corpus="cgi")
        library.tag_chunks(["doctrine"], corpus="bofip")

        # List tags for each corpus
        cgi_tags = library.list_tags(corpus="cgi")
        bofip_tags = library.list_tags(corpus="bofip")

        cgi_tag_names = [t["tag"] for t in cgi_tags]
        bofip_tag_names = [t["tag"] for t in bofip_tags]

        assert "legal" in cgi_tag_names
        assert "doctrine" not in cgi_tag_names
        assert "doctrine" in bofip_tag_names
        assert "legal" not in bofip_tag_names

    def test_search_with_tag_filter(self, library, sample_cgi_xml):
        """Test searching with tag filter."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        # Tag only one chunk
        results = library.search("exonération")
        chunk_id = results[0].chunk.id
        library.add_tags(chunk_id, ["selected"])

        # Search with tag filter
        filtered = library.search("impôt", tags=["selected"])

        # Should only return the tagged chunk
        for r in filtered:
            assert "selected" in (r.tags or [])

    def test_add_tags_nonexistent_chunk(self, library):
        """Test adding tags to nonexistent chunk."""
        success = library.add_tags("nonexistent-chunk-id", ["tag"])
        assert not success

    def test_remove_tags_nonexistent_chunk(self, library):
        """Test removing tags from nonexistent chunk."""
        success = library.remove_tags("nonexistent-chunk-id", ["tag"])
        assert not success
