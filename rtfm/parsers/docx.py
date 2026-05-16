"""DOCX (Office Open XML) parser.

Uses python-docx. Walks paragraphs in document order, treats Heading 1/2/3
styles as section breaks. Tables are flattened to "cell | cell | ...".

Install: pip install rtfm-ai[office]
"""

from pathlib import Path
from typing import Iterator, Optional

from rtfm.core.models import Chunk
from rtfm.parsers.base import BaseParser, ParserRegistry
from rtfm.parsers._chunking import (
    content_hash,
    estimate_page,
    extract_title_from_filename,
    merge_short_paragraphs,
    slugify,
    split_into_paragraphs,
)


class DOCXExtractionError(Exception):
    pass


def _require_docx():
    try:
        from docx import Document  # noqa: F401
    except ImportError:
        raise DOCXExtractionError(
            "\n\n  DOCX parsing requires the office extra.\n"
            "     Install with:  pip install rtfm-ai[office]\n"
        )


def _heading_level(style_name: str) -> int:
    """Return heading level 1..6 if the style is a Heading style, else 0."""
    if not style_name:
        return 0
    if style_name.startswith("Heading "):
        try:
            return int(style_name.split(" ", 1)[1])
        except (ValueError, IndexError):
            return 0
    if style_name == "Title":
        return 1
    return 0


def _walk_blocks(doc):
    """Yield (kind, payload) for each top-level paragraph or table in order.

    kind: 'p' | 'table'
    """
    from docx.oxml.ns import qn
    body = doc.element.body
    from docx.text.paragraph import Paragraph
    from docx.table import Table

    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield "p", Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield "table", Table(child, doc)


def _table_to_text(table) -> str:
    lines = []
    for row in table.rows:
        cells = [" ".join((c.text or "").split()) for c in row.cells]
        lines.append(" | ".join(cells))
    return "\n".join(lines)


@ParserRegistry.register
class DOCXParser(BaseParser):
    """Parser for DOCX (.docx) documents."""

    extensions = [".docx"]
    name = "docx"

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None,
    ) -> Iterator[Chunk]:
        _require_docx()
        from docx import Document

        metadata = metadata or {}
        doc = Document(str(path))

        props = doc.core_properties
        prop_title = (props.title or "").strip() if props else ""
        prop_author = (props.author or "").strip() if props else ""

        book_title = (
            metadata.get("title")
            or prop_title
            or extract_title_from_filename(path.stem)
        )
        book_slug = metadata.get("book_slug") or slugify(book_title)
        book_file = metadata.get("source_file") or path.name

        extended = dict(metadata.get("extended", {}))
        if prop_author and "author" not in extended:
            extended["author"] = prop_author

        # Group blocks into sections, separated by Heading styles
        sections: list[dict] = []
        current = {"title": "", "level": 0, "blocks": []}

        for kind, payload in _walk_blocks(doc):
            if kind == "p":
                style = payload.style.name if payload.style else ""
                level = _heading_level(style)
                if level > 0:
                    if current["blocks"] or current["title"]:
                        sections.append(current)
                    current = {
                        "title": payload.text.strip(),
                        "level": level,
                        "blocks": [],
                    }
                else:
                    text = payload.text
                    if text and text.strip():
                        current["blocks"].append(text)
            else:  # table
                tbl = _table_to_text(payload)
                if tbl.strip():
                    current["blocks"].append(tbl)

        if current["blocks"] or current["title"]:
            sections.append(current)

        chunk_counter = 0
        char_pos = 0

        for chapter_num, section in enumerate(sections, 1):
            body_text = "\n\n".join(section["blocks"])
            if not body_text.strip():
                continue

            paragraphs = split_into_paragraphs(body_text)
            chunks = merge_short_paragraphs(paragraphs)

            for para_num, chunk_text in enumerate(chunks, 1):
                chunk_counter += 1
                page_start = estimate_page(char_pos)
                page_end = estimate_page(char_pos + len(chunk_text))

                yield Chunk(
                    id=f"{book_slug}-s{chapter_num:03d}-{chunk_counter:04d}",
                    content=chunk_text,
                    book_title=book_title,
                    book_slug=book_slug,
                    book_file=book_file,
                    chapter_title=section["title"] or f"Section {chapter_num}",
                    chapter_num=chapter_num,
                    page_start=page_start,
                    page_end=page_end,
                    paragraph=para_num,
                    section_type="chapter" if section["level"] <= 2 else "section",
                    content_chars=len(chunk_text),
                    content_hash=content_hash(chunk_text),
                    metadata=extended,
                )
                char_pos += len(chunk_text)

    def extract_metadata(self, path: Path) -> dict:
        meta = {
            "source_file": path.name,
            "book_slug": slugify(path.stem),
            "title": extract_title_from_filename(path.stem),
        }
        try:
            _require_docx()
            from docx import Document
            doc = Document(str(path))
            props = doc.core_properties
            if props and props.title:
                meta["title"] = props.title.strip()
                meta["book_slug"] = slugify(props.title.strip())
            if props and props.author:
                meta["author"] = props.author.strip()
        except Exception:
            pass
        return meta
