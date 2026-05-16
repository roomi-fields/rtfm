"""ODT (OpenDocument Text) parser.

Uses odfpy. Walks the body, treats text:h headings as section breaks based
on the text:outline-level attribute. Tables are flattened to "cell | cell".

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


class ODTExtractionError(Exception):
    pass


def _require_odf():
    try:
        from odf.opendocument import load  # noqa: F401
    except ImportError:
        raise ODTExtractionError(
            "\n\n  ODT parsing requires the office extra.\n"
            "     Install with:  pip install rtfm-ai[office]\n"
        )


def _element_text(node) -> str:
    """Recursively collect text from an odf XML node."""
    parts: list[str] = []
    if node.nodeType == 3:  # TEXT_NODE
        return node.data or ""
    for child in getattr(node, "childNodes", []) or []:
        parts.append(_element_text(child))
    return "".join(parts)


def _table_text(table) -> str:
    from odf.table import TableRow, TableCell
    lines: list[str] = []
    for row in table.getElementsByType(TableRow):
        cells: list[str] = []
        for cell in row.getElementsByType(TableCell):
            cells.append(" ".join(_element_text(cell).split()))
        lines.append(" | ".join(cells))
    return "\n".join(lines)


@ParserRegistry.register
class ODTParser(BaseParser):
    """Parser for ODT (.odt) documents."""

    extensions = [".odt"]
    name = "odt"

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None,
    ) -> Iterator[Chunk]:
        _require_odf()
        from odf.opendocument import load
        from odf.text import H, P
        from odf.table import Table

        metadata = metadata or {}
        try:
            doc = load(str(path))
        except Exception as e:
            raise ODTExtractionError(f"odt load failed: {e}")

        meta_title = ""
        meta_author = ""
        try:
            from odf.meta import Title, InitialCreator, Creator
            titles = doc.meta.getElementsByType(Title) if doc.meta else []
            if titles:
                meta_title = _element_text(titles[0]).strip()
            creators = doc.meta.getElementsByType(Creator) if doc.meta else []
            if creators:
                meta_author = _element_text(creators[0]).strip()
            if not meta_author:
                init = doc.meta.getElementsByType(InitialCreator) if doc.meta else []
                if init:
                    meta_author = _element_text(init[0]).strip()
        except Exception:
            pass

        book_title = (
            metadata.get("title")
            or meta_title
            or extract_title_from_filename(path.stem)
        )
        book_slug = metadata.get("book_slug") or slugify(book_title)
        book_file = metadata.get("source_file") or path.name

        extended = dict(metadata.get("extended", {}))
        if meta_author and "author" not in extended:
            extended["author"] = meta_author

        # Walk in document order
        body = doc.text
        sections: list[dict] = []
        current = {"title": "", "level": 0, "blocks": []}

        def _flush():
            if current["blocks"] or current["title"]:
                sections.append(dict(current))

        for child in body.childNodes:
            qname = getattr(child, "qname", None)
            if not qname:
                continue
            tag = qname[1]  # (namespace, local)
            if tag == "h":
                _flush()
                outline = child.getAttribute("outlinelevel")
                try:
                    level = int(outline) if outline else 1
                except ValueError:
                    level = 1
                current = {
                    "title": _element_text(child).strip(),
                    "level": level,
                    "blocks": [],
                }
            elif tag == "p":
                text = _element_text(child).strip()
                if text:
                    current["blocks"].append(text)
            elif tag == "table":
                tbl = _table_text(child)
                if tbl.strip():
                    current["blocks"].append(tbl)
            elif tag == "list":
                # render list items as a flat block
                lines = []
                for li in child.childNodes:
                    li_text = _element_text(li).strip()
                    if li_text:
                        lines.append(f"- {li_text}")
                if lines:
                    current["blocks"].append("\n".join(lines))

        _flush()

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
            _require_odf()
            from odf.opendocument import load
            from odf.meta import Title, Creator
            doc = load(str(path))
            if doc.meta:
                titles = doc.meta.getElementsByType(Title)
                if titles:
                    title = _element_text(titles[0]).strip()
                    if title:
                        meta["title"] = title
                        meta["book_slug"] = slugify(title)
                creators = doc.meta.getElementsByType(Creator)
                if creators:
                    author = _element_text(creators[0]).strip()
                    if author:
                        meta["author"] = author
        except Exception:
            pass
        return meta
