"""Tests for office parsers (docx, odt, rtf)."""

from pathlib import Path

import pytest

from rtfm.parsers.base import ParserRegistry


class TestRegistry:
    @pytest.mark.parametrize(
        "ext,parser_name",
        [
            (".docx", "docx"),
            (".odt", "odt"),
            (".rtf", "rtf"),
        ],
    )
    def test_registry_resolves_extension(self, ext, parser_name):
        if ext not in ParserRegistry.list_extensions():
            pytest.skip(f"{ext} parser not registered (optional dep missing)")
        parser = ParserRegistry.get_parser(Path(f"sample{ext}"))
        assert parser is not None
        assert parser.name == parser_name


class TestDOCXParser:
    @pytest.fixture
    def docx_file(self, tmp_path):
        docx_mod = pytest.importorskip("docx")
        doc = docx_mod.Document()
        doc.core_properties.title = "Sample DOCX"
        doc.core_properties.author = "Test Author"

        doc.add_heading("Introduction", level=1)
        doc.add_paragraph(
            "This is the introductory paragraph of the sample document. "
            "It contains enough text to survive the minimum-length filter "
            "applied by the chunker, so the parser produces at least one chunk."
        )
        doc.add_paragraph(
            "A second paragraph in the introduction section, adding more body text "
            "so the merged chunk reaches a reasonable size for indexing."
        )

        doc.add_heading("Main Content", level=1)
        doc.add_paragraph(
            "Here begins the main content of the document. We want enough text "
            "in this second section so that the parser emits at least one chunk "
            "with a non-trivial body. This sentence helps reach that length."
        )

        path = tmp_path / "sample.docx"
        doc.save(str(path))
        return path

    def test_parse_produces_chunks(self, docx_file):
        from rtfm.parsers.docx import DOCXParser
        parser = DOCXParser()
        chunks = list(parser.parse(docx_file))
        assert len(chunks) >= 2

        content = " ".join(c.content for c in chunks)
        assert "introductory paragraph" in content
        assert "main content" in content

    def test_section_titles(self, docx_file):
        from rtfm.parsers.docx import DOCXParser
        parser = DOCXParser()
        chunks = list(parser.parse(docx_file))
        titles = {c.chapter_title for c in chunks}
        assert "Introduction" in titles
        assert "Main Content" in titles

    def test_metadata(self, docx_file):
        from rtfm.parsers.docx import DOCXParser
        parser = DOCXParser()
        meta = parser.extract_metadata(docx_file)
        assert meta.get("title") == "Sample DOCX"
        assert meta.get("author") == "Test Author"


class TestODTParser:
    @pytest.fixture
    def odt_file(self, tmp_path):
        opendoc = pytest.importorskip("odf.opendocument")
        text_mod = pytest.importorskip("odf.text")
        meta_mod = pytest.importorskip("odf.meta")
        dc_mod = pytest.importorskip("odf.dc")

        doc = opendoc.OpenDocumentText()

        # metadata
        title_el = dc_mod.Title()
        title_el.addText("Sample ODT")
        doc.meta.addElement(title_el)
        creator_el = dc_mod.Creator()
        creator_el.addText("Test Author")
        doc.meta.addElement(creator_el)

        h1 = text_mod.H(outlinelevel=1)
        h1.addText("Section One")
        doc.text.addElement(h1)
        p1 = text_mod.P()
        p1.addText(
            "Body text of the first section. It needs to be long enough to "
            "pass the chunker's minimum-length filter and produce at least "
            "one real chunk in the output for the test to assert against."
        )
        doc.text.addElement(p1)

        h2 = text_mod.H(outlinelevel=1)
        h2.addText("Section Two")
        doc.text.addElement(h2)
        p2 = text_mod.P()
        p2.addText(
            "Second section body. Also reasonably long so the chunker is "
            "happy and produces measurable output we can verify in tests."
        )
        doc.text.addElement(p2)

        path = tmp_path / "sample.odt"
        doc.save(str(path))
        return path

    def test_parse_produces_chunks(self, odt_file):
        from rtfm.parsers.odt import ODTParser
        parser = ODTParser()
        chunks = list(parser.parse(odt_file))
        assert len(chunks) >= 2

        content = " ".join(c.content for c in chunks)
        assert "first section" in content
        assert "Second section" in content

    def test_section_titles(self, odt_file):
        from rtfm.parsers.odt import ODTParser
        parser = ODTParser()
        chunks = list(parser.parse(odt_file))
        titles = {c.chapter_title for c in chunks}
        assert "Section One" in titles
        assert "Section Two" in titles

    def test_metadata(self, odt_file):
        from rtfm.parsers.odt import ODTParser
        parser = ODTParser()
        meta = parser.extract_metadata(odt_file)
        assert meta.get("title") == "Sample ODT"
        assert meta.get("author") == "Test Author"


# Minimal RTF — striprtf handles this fine
RTF_SAMPLE = (
    r"{\rtf1\ansi\deff0"
    r"{\fonttbl{\f0 Times New Roman;}}"
    r"\f0\fs24 "
    r"This is the first paragraph of the sample RTF document. "
    r"It contains enough text to make it past the chunker's minimum-length "
    r"filter, so the parser will produce at least one chunk in the output.\par "
    r"\par "
    r"And here is the second paragraph, with additional content to ensure "
    r"the chunker produces a non-trivial result.\par"
    r"}"
)


class TestRTFParser:
    @pytest.fixture
    def rtf_file(self, tmp_path):
        pytest.importorskip("striprtf")
        path = tmp_path / "sample.rtf"
        path.write_text(RTF_SAMPLE, encoding="utf-8")
        return path

    def test_parse_produces_chunks(self, rtf_file):
        from rtfm.parsers.rtf import RTFParser
        parser = RTFParser()
        chunks = list(parser.parse(rtf_file))
        assert len(chunks) >= 1

        content = " ".join(c.content for c in chunks)
        assert "first paragraph" in content
        assert "second paragraph" in content

    def test_missing_dep_raises(self, monkeypatch, tmp_path):
        """If striprtf isn't installed, parsing should raise a clean error."""
        # Simulate the import failing
        import sys
        monkeypatch.setitem(sys.modules, "striprtf.striprtf", None)
        from rtfm.parsers import rtf as rtf_mod
        path = tmp_path / "x.rtf"
        path.write_text(RTF_SAMPLE, encoding="utf-8")
        parser = rtf_mod.RTFParser()
        with pytest.raises(rtf_mod.RTFExtractionError):
            list(parser.parse(path))
