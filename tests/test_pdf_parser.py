"""Tests for PDF parser."""

import pytest
from pathlib import Path

# Skip all tests if pdftext not installed
pdftext_available = False
try:
    import pdftext
    pdftext_available = True
except ImportError:
    pass

pytestmark = pytest.mark.skipif(
    not pdftext_available,
    reason="pdftext not installed"
)


class TestPDFParser:
    """Tests for PDF parser."""

    def test_import_parser(self):
        """Test that PDF parser can be imported."""
        from biblirag.parsers.pdf import PDFParser
        parser = PDFParser()
        assert parser.backend == 'pdftext'

    def test_parser_with_marker_backend(self):
        """Test parser initialization with marker backend."""
        from biblirag.parsers.pdf import PDFParser
        parser = PDFParser(backend='marker')
        assert parser.backend == 'marker'

    def test_invalid_backend(self):
        """Test that invalid backend raises error."""
        from biblirag.parsers.pdf import PDFParser
        with pytest.raises(ValueError):
            PDFParser(backend='invalid')

    def test_slugify(self):
        """Test slugify function."""
        from biblirag.parsers.pdf import slugify
        assert slugify("My Document.pdf") == "my-document"
        assert slugify("Test (2023)") == "test"

    def test_extract_title_from_filename(self):
        """Test title extraction."""
        from biblirag.parsers.pdf import extract_title_from_filename
        assert extract_title_from_filename("my-document.pdf") == "my document"
        assert extract_title_from_filename("Book_Title.pdf") == "Book Title"

    def test_split_into_paragraphs(self):
        """Test paragraph splitting."""
        from biblirag.parsers.pdf import split_into_paragraphs
        text = "First paragraph here.\n\nSecond paragraph here."
        paras = split_into_paragraphs(text)
        assert len(paras) == 2

    def test_merge_short_paragraphs(self):
        """Test paragraph merging."""
        from biblirag.parsers.pdf import merge_short_paragraphs
        short_paras = ["A", "B", "C"]  # Too short, won't be included
        result = merge_short_paragraphs(short_paras)
        # Short paragraphs get merged
        assert len(result) <= len(short_paras)


class TestPDFParserRegistry:
    """Test PDF parser registration."""

    def test_parser_registered(self):
        """Test that PDF parser is registered for .pdf extension."""
        from biblirag.parsers.base import ParserRegistry
        # Force import
        from biblirag.parsers import pdf

        extensions = ParserRegistry.list_extensions()
        assert '.pdf' in extensions or '.PDF' in extensions
