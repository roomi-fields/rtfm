"""FictionBook (FB2) parser.

FB2 is an XML-based ebook format. We use stdlib xml.etree.ElementTree —
no external dependency. Each <section> becomes a chunked unit; the optional
<title> at the top of a section is used as the chapter heading.
"""

from pathlib import Path
from typing import Iterator, Optional
import xml.etree.ElementTree as ET

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


FB2_NS = "{http://www.gribuser.ru/xml/fictionbook/2.0}"


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _text_content(elem: ET.Element) -> str:
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(_text_content(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _section_title(section: ET.Element) -> str:
    title_elem = section.find(f"{FB2_NS}title")
    if title_elem is None:
        return ""
    return " ".join(_text_content(title_elem).split())


def _section_body_text(section: ET.Element) -> str:
    """Collect all <p> text in the section, skipping the leading <title>."""
    paragraphs: list[str] = []
    for child in section:
        tag = _strip_ns(child.tag)
        if tag == "title":
            continue
        if tag == "section":
            # nested sections handled at higher loop
            continue
        paragraphs.append(_text_content(child))
    text = "\n\n".join(p.strip() for p in paragraphs if p and p.strip())
    return text


def _iter_sections(body: ET.Element):
    """Yield (depth, section) for every <section>, depth-first."""
    stack = [(1, child) for child in reversed(list(body))
             if _strip_ns(child.tag) == "section"]
    while stack:
        depth, section = stack.pop()
        yield depth, section
        children = [c for c in section if _strip_ns(c.tag) == "section"]
        for c in reversed(children):
            stack.append((depth + 1, c))


def _extract_metadata(root: ET.Element) -> dict:
    desc = root.find(f"{FB2_NS}description")
    if desc is None:
        return {}
    info = desc.find(f"{FB2_NS}title-info")
    if info is None:
        return {}
    meta: dict = {}
    title_elem = info.find(f"{FB2_NS}book-title")
    if title_elem is not None and title_elem.text:
        meta["title"] = title_elem.text.strip()
    author = info.find(f"{FB2_NS}author")
    if author is not None:
        first = author.find(f"{FB2_NS}first-name")
        last = author.find(f"{FB2_NS}last-name")
        name_parts = [
            (first.text or "").strip() if first is not None else "",
            (last.text or "").strip() if last is not None else "",
        ]
        full = " ".join(p for p in name_parts if p)
        if full:
            meta["author"] = full
    return meta


@ParserRegistry.register
class FB2Parser(BaseParser):
    """Parser for FictionBook (.fb2) ebooks."""

    extensions = [".fb2"]
    name = "fb2"

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None,
    ) -> Iterator[Chunk]:
        metadata = metadata or {}

        try:
            tree = ET.parse(str(path))
        except ET.ParseError:
            return
        root = tree.getroot()

        file_meta = _extract_metadata(root)
        book_title = (
            metadata.get("title")
            or file_meta.get("title")
            or extract_title_from_filename(path.stem)
        )
        book_slug = metadata.get("book_slug") or slugify(book_title)
        book_file = metadata.get("source_file") or path.name

        body = root.find(f"{FB2_NS}body")
        if body is None:
            return

        chunk_counter = 0
        char_pos = 0

        for chapter_num, (depth, section) in enumerate(_iter_sections(body), 1):
            title = _section_title(section)
            body_text = _section_body_text(section)
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
                    chapter_title=title or f"Section {chapter_num}",
                    chapter_num=chapter_num,
                    page_start=page_start,
                    page_end=page_end,
                    paragraph=para_num,
                    section_type="section" if depth > 1 else "chapter",
                    content_chars=len(chunk_text),
                    content_hash=content_hash(chunk_text),
                    metadata=metadata.get("extended", {}),
                )
                char_pos += len(chunk_text)

    def extract_metadata(self, path: Path) -> dict:
        meta = {
            "source_file": path.name,
            "book_slug": slugify(path.stem),
            "title": extract_title_from_filename(path.stem),
        }
        try:
            tree = ET.parse(str(path))
            file_meta = _extract_metadata(tree.getroot())
            meta.update(file_meta)
            if "title" in file_meta:
                meta["book_slug"] = slugify(file_meta["title"])
        except ET.ParseError:
            pass
        return meta
