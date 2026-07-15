"""Parser for the XMLittré dictionary (littre-dictionnaire.xml).

The XMLittré file distributed by François Gannaz concatenates 26
per-letter blocks into a single ``<littre-consolide>`` wrapper, and
each inner block carries its own ``<?xml version="1.0"?>`` declaration
and ``<!DOCTYPE xmlittre>``. Standard XML parsers refuse the result
(``xml.etree.ElementTree.ParseError: XML or text declaration not at
start of entity``), which left the 93 MB file spamming ~7000 failed
ingest attempts in the queue.

Strategy: strip the interior XML declarations and DOCTYPE lines before
feeding the text to :func:`xml.etree.ElementTree.iterparse`. One
:class:`~rtfm.core.models.Chunk` per ``<entree>`` element; entries are
released with ``elem.clear()`` as they are consumed so the peak memory
stays bounded even though the file is ~78 600 entries long.
"""
from __future__ import annotations

import hashlib
import re
from io import BytesIO
from pathlib import Path
from typing import Iterator, Optional
from xml.etree.ElementTree import Element, iterparse

from rtfm.core.models import Chunk
from rtfm.parsers.base import BaseParser, ParserRegistry


# Peek this many bytes when deciding whether a file is Littré. Enough
# to always see the ``<littre-consolide`` root element without loading
# the 93 MB body.
_MATCH_PEEK_BYTES = 512

# Any inner ``<?xml ...?>`` PI or ``<!DOCTYPE ...>`` after the first
# declaration is illegal-in-context but harmless if stripped.
_INNER_XML_DECL = re.compile(rb"<\?xml\b[^?]*\?>")
_INNER_DOCTYPE = re.compile(rb"<!DOCTYPE\b[^>]*>")


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def _element_text(elem: Element) -> str:
    """Recursively collect the text content of an element, preserving
    whitespace between children but not tags. Trailing whitespace is
    collapsed since the XML source uses generous formatting."""
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(_element_text(child))
        if child.tail:
            parts.append(child.tail)
    text = " ".join(p.strip() for p in parts if p and p.strip())
    return re.sub(r"\s+", " ", text)


def _preprocess(raw: bytes) -> bytes:
    """Return ``raw`` with all *inner* XML PIs and DOCTYPEs removed
    while preserving the first (outermost) ``<?xml ... ?>``."""
    # Preserve the outermost declaration if present; strip everything
    # inside the body.
    m = re.match(rb"\s*<\?xml[^?]*\?>", raw)
    if m:
        head = raw[: m.end()]
        body = raw[m.end():]
    else:
        head = b""
        body = raw
    body = _INNER_XML_DECL.sub(b"", body)
    body = _INNER_DOCTYPE.sub(b"", body)
    return head + body


@ParserRegistry.register
class LittreParser(BaseParser):
    """Content-routed parser for XMLittré (littre-dictionnaire.xml)."""

    # We register on ``.xml`` too so ``list_extensions()`` still lists
    # us, but the content-check pass in ParserRegistry.get_parser
    # ensures we only claim the Littré file and let other .xml files
    # fall through to the Legifrance parser.
    extensions = [".xml"]
    name = "littre"

    @classmethod
    def matches(cls, path: Path) -> bool:
        if path.suffix.lower() != ".xml":
            return False
        try:
            with open(path, "rb") as f:
                head = f.read(_MATCH_PEEK_BYTES)
        except OSError:
            return False
        # ``<littre-consolide`` is the unambiguous signature of the
        # consolidated file; ``XMLittre`` is the substring the author
        # puts in the ``source=`` attribute.
        return b"<littre-consolide" in head or b"XMLittre" in head

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None,
    ) -> Iterator[Chunk]:
        metadata = metadata or {}
        book_slug = metadata.get("book_slug", "littre")
        book_title = metadata.get("title", "Dictionnaire de la langue française (Littré)")
        book_file = metadata.get("source_file", str(path))

        cleaned = _preprocess(path.read_bytes())
        stream = BytesIO(cleaned)

        counter = 0
        current_letter = "?"
        # We need ``start`` events on <xmlittre> so we know the letter
        # before its child <entree> elements finish parsing (``end``
        # fires bottom-up, so an ``end`` on <xmlittre> would arrive
        # AFTER all its <entree> children).
        for event, elem in iterparse(stream, events=("start", "end")):
            tag = elem.tag
            if event == "start" and tag == "xmlittre":
                current_letter = elem.get("lettre", current_letter)
                continue
            if event != "end" or tag != "entree":
                if event == "end" and tag == "xmlittre":
                    # Release the (now-empty) letter block.
                    elem.clear()
                continue
            counter += 1
            terme = elem.get("terme", "").strip() or "?"
            sens = elem.get("sens", "")
            body = _element_text(elem)
            # Anchor each chunk with the head-word so a plain FTS on
            # "littré démocratie" matches the démocratie entry.
            title = f"{terme}" + (f" (sens {sens})" if sens else "")
            content = f"{title}\n{body}" if body else title

            yield Chunk(
                id=f"{book_slug}-{counter:06d}",
                content=content,
                book_title=book_title,
                book_slug=book_slug,
                book_file=book_file,
                chapter_title=f"Lettre {current_letter}",
                chapter_num=counter,
                page_start=counter,
                page_end=counter,
                paragraph=1,
                line_start=counter,
                line_end=counter,
                content_chars=len(content),
                content_hash=_content_hash(content),
                metadata={"terme": terme, "lettre": current_letter, **({"sens": sens} if sens else {})},
            )
            elem.clear()
