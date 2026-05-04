"""Tests for rtfm parsers."""

import pytest
from pathlib import Path
from rtfm.parsers.base import ParserRegistry
from rtfm.parsers.xml_legifrance import (
    XMLLegiFranceParser,
    lien_legifrance,
)
from rtfm.parsers.html_bofip import (
    HTMLBOFiPParser,
    extract_cgi_references,
    parse_boi_identifier,
    lien_bofip,
    HTMLTextExtractor,
)
from rtfm.parsers.sqlite_parser import SQLiteParser


class TestParserRegistry:
    """Tests for parser registry."""

    def test_registry_has_parsers(self):
        """Test that parsers are registered."""
        extensions = ParserRegistry.list_extensions()
        assert ".xml" in extensions
        assert ".html" in extensions or ".htm" in extensions

    def test_get_parser_for_xml(self):
        """Test getting parser for XML file."""
        parser = ParserRegistry.get_parser(Path("test.xml"))
        assert parser is not None
        assert isinstance(parser, XMLLegiFranceParser)

    def test_get_parser_for_html(self):
        """Test getting parser for HTML file."""
        parser = ParserRegistry.get_parser(Path("test.html"))
        assert parser is not None
        assert isinstance(parser, HTMLBOFiPParser)

    def test_get_parser_unknown(self):
        """Test getting parser for unknown extension."""
        parser = ParserRegistry.get_parser(Path("test.xyz"))
        assert parser is None

    def test_get_parser_for_sqlite(self):
        """Test getting parser for SQLite extensions."""
        for ext in (".sqlite", ".sqlite3"):
            parser = ParserRegistry.get_parser(Path(f"foo{ext}"))
            assert isinstance(parser, SQLiteParser), f"failed for {ext}"


class TestSQLiteParser:
    """Tests for SQLite parser."""

    @pytest.fixture
    def sample_db(self, tmp_path):
        import sqlite3

        db_path = tmp_path / "sample.sqlite"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE authors (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE books (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                author_id INTEGER,
                FOREIGN KEY (author_id) REFERENCES authors(id)
            );
            CREATE VIEW recent_books AS SELECT * FROM books ORDER BY id DESC;
            INSERT INTO authors (id, name) VALUES (1, 'Borges'), (2, 'Calvino');
            INSERT INTO books (id, title, author_id) VALUES
                (1, 'Ficciones', 1),
                (2, 'Invisible Cities', 2);
            """
        )
        conn.commit()
        conn.close()
        return db_path

    def test_parse_produces_chunks(self, sample_db):
        parser = SQLiteParser()
        chunks = list(parser.parse(sample_db))
        # overview + (schema + sample) × 2 tables + 1 view = 6
        assert len(chunks) == 6

        titles = [c.chapter_title for c in chunks]
        assert "overview" in titles
        assert "table: authors (schema)" in titles
        assert "table: books (sample)" in titles
        assert "view: recent_books" in titles

    def test_overview_lists_tables_with_counts(self, sample_db):
        parser = SQLiteParser()
        overview = next(c for c in parser.parse(sample_db) if c.chapter_title == "overview")
        assert "authors (2 rows)" in overview.content
        assert "books (2 rows)" in overview.content

    def test_schema_chunk_includes_create_and_columns(self, sample_db):
        parser = SQLiteParser()
        chunk = next(c for c in parser.parse(sample_db) if c.chapter_title == "table: books (schema)")
        assert "CREATE TABLE books" in chunk.content
        assert "`title`" in chunk.content
        assert "`author_id`" in chunk.content
        assert "Foreign Keys" in chunk.content
        assert "authors" in chunk.content

    def test_sample_rows_rendered(self, sample_db):
        parser = SQLiteParser()
        chunk = next(c for c in parser.parse(sample_db) if c.chapter_title == "table: books (sample)")
        assert "Ficciones" in chunk.content
        assert "Invisible Cities" in chunk.content

    def test_extract_edges_returns_foreign_keys(self, sample_db):
        parser = SQLiteParser()
        edges = parser.extract_edges(sample_db)
        assert len(edges) == 1
        assert edges[0].relation_type == "fk"
        assert edges[0].target_ref == "authors"
        assert "books.author_id" in edges[0].source_detail

    def test_db_extension_requires_magic_bytes(self, tmp_path):
        """A `.db` file that is not actually SQLite should be skipped."""
        fake = tmp_path / "fake.db"
        fake.write_text("this is not a sqlite db at all")
        parser = SQLiteParser()
        assert parser.can_parse(fake) is False
        assert list(parser.parse(fake)) == []
        assert parser.extract_edges(fake) == []

    def test_corrupt_db_handled_gracefully(self, tmp_path):
        bad = tmp_path / "bad.sqlite"
        bad.write_bytes(b"\x00" * 100)  # not a valid SQLite file
        parser = SQLiteParser()
        # Doesn't raise — just yields nothing
        assert list(parser.parse(bad)) == []


class TestXMLLegiFranceParser:
    """Tests for Légifrance XML parser."""

    def test_parse_sample_cgi(self, sample_cgi_xml):
        """Test parsing sample CGI XML."""
        parser = XMLLegiFranceParser()
        chunks = list(parser.parse(sample_cgi_xml))

        assert len(chunks) == 2

        # Check first article - chapter_title format is "Article X"
        chunk1 = chunks[0]
        assert "Article" in chunk1.chapter_title
        assert "impôt annuel" in chunk1.content
        assert chunk1.metadata["legal_fr"]["etat"] == "VIGUEUR"

        # Check second article
        chunk2 = chunks[1]
        assert "Article" in chunk2.chapter_title
        assert "exonération" in chunk2.content

    def test_extract_metadata(self, sample_cgi_xml):
        """Test metadata extraction."""
        parser = XMLLegiFranceParser()
        meta = parser.extract_metadata(sample_cgi_xml)

        assert meta["source_file"] == "CGI.xml"
        assert "title" in meta or "book_slug" in meta  # Should have some identification

    def test_lien_legifrance(self):
        """Test Légifrance URL generation."""
        url = lien_legifrance("44 quinquies", "cgi")
        assert "legifrance.gouv.fr" in url
        assert "44" in url or "quinquies" in url


class TestHTMLBOFiPParser:
    """Tests for BOFiP HTML parser."""

    def test_parse_sample_bofip(self, sample_bofip_html):
        """Test parsing sample BOFiP HTML."""
        parser = HTMLBOFiPParser()
        chunks = list(parser.parse(sample_bofip_html))

        # Should have at least one chunk (content is >200 chars)
        assert len(chunks) >= 1

        # Check content contains TVA-related text
        all_content = " ".join(c.content for c in chunks)
        assert "TVA" in all_content or "taxe" in all_content.lower()

    def test_extract_cgi_references(self):
        """Test CGI reference extraction from text."""
        text = "Conformément à l'article 256 du CGI et à l'article 257 bis"
        refs = extract_cgi_references(text)

        assert "256" in refs
        assert "257 bis" in refs

    def test_extract_cgi_refs_with_suffixes(self):
        """Test extraction of articles with Latin suffixes."""
        text = """
        L'article 44 quinquies du CGI prévoit une exonération.
        L'art. 39 decies A permet des amortissements exceptionnels.
        Voir aussi article 238 bis du code général des impôts.
        """
        refs = extract_cgi_references(text)

        assert "44 quinquies" in refs
        assert "39 decies A" in refs
        assert "238 bis" in refs

    def test_extract_cgi_refs_no_false_positives(self):
        """Test that extraction doesn't capture false positives."""
        text = "L'article 44 quinquies du CGI mentionne les zones"
        refs = extract_cgi_references(text)

        # Should not capture "du" or "de" as part of article number
        for ref in refs:
            assert "du" not in ref.lower()
            assert "de" not in ref.lower()

    def test_parse_boi_identifier(self):
        """Test BOI identifier parsing."""
        result = parse_boi_identifier("BOI-TVA-CHAMP-30-10-20-10-20130523")

        assert result["identifiant"] == "BOI-TVA-CHAMP-30-10-20-10-20130523"
        assert result["serie"] == "TVA"
        assert result["division"] == "CHAMP"
        assert result["date_publication"] == "2013-05-23"

    def test_lien_bofip(self):
        """Test BOFiP URL generation."""
        url = lien_bofip("BOI-TVA-CHAMP-30-10-20-10-20130523")
        assert "bofip.impots.gouv.fr" in url
        assert "TVA-CHAMP" in url


class TestHTMLTextExtractor:
    """Tests for HTML text extraction."""

    def test_extract_simple_text(self):
        """Test extracting text from simple HTML."""
        html = "<p>Hello world</p>"
        extractor = HTMLTextExtractor()
        extractor.feed(html)
        text = extractor.get_text()

        assert "Hello world" in text

    def test_extract_with_sections(self):
        """Test extracting sections from HTML."""
        html = """
        <h1>Title</h1>
        <p>Introduction</p>
        <h2>Section 1</h2>
        <p>Content 1</p>
        <h2>Section 2</h2>
        <p>Content 2</p>
        """
        extractor = HTMLTextExtractor()
        extractor.feed(html)
        sections = extractor.get_sections()

        assert len(sections) >= 2
        titles = [s[0] for s in sections]
        assert "Title" in titles or "Section 1" in titles

    def test_skip_script_tags(self):
        """Test that script content is skipped."""
        html = """
        <p>Real content</p>
        <script>var x = 'should not appear';</script>
        <p>More content</p>
        """
        extractor = HTMLTextExtractor()
        extractor.feed(html)
        text = extractor.get_text()

        assert "Real content" in text
        assert "should not appear" not in text

    def test_preserve_list_items(self):
        """Test that list items are preserved."""
        html = """
        <ul>
            <li>Item 1</li>
            <li>Item 2</li>
        </ul>
        """
        extractor = HTMLTextExtractor()
        extractor.feed(html)
        text = extractor.get_text()

        assert "Item 1" in text
        assert "Item 2" in text
