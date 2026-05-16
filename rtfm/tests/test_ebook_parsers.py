"""Tests for ebook parsers (epub, fb2, mobi, djvu)."""

from pathlib import Path

import pytest

from rtfm.parsers.base import ParserRegistry


FB2_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
  <description>
    <title-info>
      <author>
        <first-name>Jorge Luis</first-name>
        <last-name>Borges</last-name>
      </author>
      <book-title>Ficciones</book-title>
    </title-info>
  </description>
  <body>
    <section>
      <title><p>El jardin de senderos que se bifurcan</p></title>
      <p>En su pagina 22, Liddell Hart refiere que una ofensiva de trece divisiones britanicas, apoyada por mil cuatrocientas piezas de artilleria, contra la linea Serre-Montauban, habia sido planeada para el 24 de julio de 1916 y debio postergarse hasta la manana del 29.</p>
      <p>Las lluvias torrenciales causaron esa demora, nada significativa por cierto. La siguiente declaracion, dictada, releida y firmada por el doctor Yu Tsun, antiguo catedratico de ingles en la Hochschule de Tsingtao, arroja una insospechada luz sobre el caso.</p>
    </section>
    <section>
      <title><p>La biblioteca de Babel</p></title>
      <p>El universo (que otros llaman la Biblioteca) se compone de un numero indefinido, y tal vez infinito, de galerias hexagonales, con vastos pozos de ventilacion en el medio, cercados por barandas bajisimas.</p>
      <p>Desde cualquier hexagono se ven los pisos inferiores y superiores: interminablemente. La distribucion de las galerias es invariable.</p>
    </section>
  </body>
</FictionBook>
"""


class TestRegistry:
    @pytest.mark.parametrize(
        "ext,parser_name",
        [
            (".epub", "epub"),
            (".fb2", "fb2"),
            (".mobi", "mobi"),
            (".azw", "mobi"),
            (".azw3", "mobi"),
            (".djvu", "djvu"),
            (".djv", "djvu"),
        ],
    )
    def test_registry_resolves_extension(self, ext, parser_name):
        # Some parsers are optional — skip if not registered
        if ext not in ParserRegistry.list_extensions():
            pytest.skip(f"{ext} parser not registered (optional dep missing)")
        parser = ParserRegistry.get_parser(Path(f"sample{ext}"))
        assert parser is not None
        assert parser.name == parser_name


class TestFB2Parser:
    @pytest.fixture
    def fb2_file(self, tmp_path):
        path = tmp_path / "ficciones.fb2"
        path.write_text(FB2_SAMPLE, encoding="utf-8")
        return path

    def test_parse_produces_chunks(self, fb2_file):
        from rtfm.parsers.fb2 import FB2Parser
        parser = FB2Parser()
        chunks = list(parser.parse(fb2_file))
        assert len(chunks) >= 2

        all_content = " ".join(c.content for c in chunks)
        assert "Liddell Hart" in all_content
        assert "Biblioteca" in all_content

    def test_titles_extracted(self, fb2_file):
        from rtfm.parsers.fb2 import FB2Parser
        parser = FB2Parser()
        chunks = list(parser.parse(fb2_file))
        titles = {c.chapter_title for c in chunks}
        # at least one chapter title should mention bifurcan or Babel
        assert any("bifurcan" in t or "Babel" in t for t in titles)

    def test_metadata_extracts_title_and_author(self, fb2_file):
        from rtfm.parsers.fb2 import FB2Parser
        parser = FB2Parser()
        meta = parser.extract_metadata(fb2_file)
        assert meta.get("title") == "Ficciones"
        assert "Borges" in (meta.get("author") or "")

    def test_book_title_uses_opf(self, fb2_file):
        from rtfm.parsers.fb2 import FB2Parser
        parser = FB2Parser()
        chunks = list(parser.parse(fb2_file))
        assert chunks[0].book_title == "Ficciones"

    def test_corrupt_file_returns_no_chunks(self, tmp_path):
        from rtfm.parsers.fb2 import FB2Parser
        bad = tmp_path / "bad.fb2"
        bad.write_text("this is not XML at all <broken")
        parser = FB2Parser()
        assert list(parser.parse(bad)) == []


class TestEPUBParser:
    @pytest.fixture
    def epub_file(self, tmp_path):
        epub = pytest.importorskip("ebooklib.epub")
        pytest.importorskip("bs4")

        book = epub.EpubBook()
        book.set_identifier("test-id")
        book.set_title("Sample EPUB")
        book.add_author("Test Author")

        ch1 = epub.EpubHtml(title="Chapter One", file_name="ch1.xhtml")
        ch1.content = (
            "<html><body>"
            "<h1>Chapter One</h1>"
            "<p>This is the first paragraph of chapter one. It contains enough text to be considered a real paragraph and pass the minimum-length filter that the chunker applies to discard tiny fragments.</p>"
            "<p>Second paragraph follows here, with more content to make the chunker happy and produce at least one real chunk in the output.</p>"
            "</body></html>"
        )
        ch2 = epub.EpubHtml(title="Chapter Two", file_name="ch2.xhtml")
        ch2.content = (
            "<html><body>"
            "<h1>Chapter Two</h1>"
            "<p>And here is the second chapter. It also has some text so that the parser produces measurable output that we can assert against in the test.</p>"
            "</body></html>"
        )
        book.add_item(ch1)
        book.add_item(ch2)
        book.toc = (ch1, ch2)
        book.spine = ["nav", ch1, ch2]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        path = tmp_path / "sample.epub"
        epub.write_epub(str(path), book)
        return path

    def test_parse_produces_chunks(self, epub_file):
        from rtfm.parsers.epub import EPUBParser
        parser = EPUBParser()
        chunks = list(parser.parse(epub_file))
        assert len(chunks) >= 2
        content = " ".join(c.content for c in chunks)
        assert "first paragraph" in content
        assert "second chapter" in content

    def test_metadata_extracts_title(self, epub_file):
        from rtfm.parsers.epub import EPUBParser
        parser = EPUBParser()
        meta = parser.extract_metadata(epub_file)
        assert meta.get("title") == "Sample EPUB"
        assert meta.get("author") == "Test Author"


class TestMOBIParser:
    """MOBI cannot easily be constructed in code — we test what we can without
    a fixture: registry resolution and a clear error on a non-MOBI file."""

    def test_module_importable(self):
        pytest.importorskip("mobi")
        pytest.importorskip("bs4")
        from rtfm.parsers.mobi_parser import MOBIParser
        assert MOBIParser.extensions == [".mobi", ".azw", ".azw3"]

    def test_garbage_file_raises_extraction_error(self, tmp_path):
        pytest.importorskip("mobi")
        pytest.importorskip("bs4")
        from rtfm.parsers.mobi_parser import MOBIParser, MOBIExtractionError

        bad = tmp_path / "not-a-mobi.mobi"
        bad.write_bytes(b"garbage bytes that are not a valid mobi file")
        parser = MOBIParser()
        with pytest.raises(MOBIExtractionError):
            list(parser.parse(bad))


class TestDJVUParser:
    """DJVU requires the djvulibre-bin system binary. We test only what
    works without it."""

    def test_module_importable(self):
        from rtfm.parsers.djvu import DJVUParser
        assert DJVUParser.extensions == [".djvu", ".djv"]

    def test_missing_binary_raises_extraction_error(self, tmp_path, monkeypatch):
        from rtfm.parsers import djvu as djvu_mod
        monkeypatch.setattr(djvu_mod.shutil, "which", lambda _: None)
        bad = tmp_path / "x.djvu"
        bad.write_bytes(b"")
        parser = djvu_mod.DJVUParser()
        with pytest.raises(djvu_mod.DJVUExtractionError):
            list(parser.parse(bad))
