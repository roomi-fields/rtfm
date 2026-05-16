"""RTF (Rich Text Format) parser.

Uses striprtf to extract plain text from RTF markup. RTF has no
standardised hierarchy, so we chunk on paragraph boundaries.

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


class RTFExtractionError(Exception):
    pass


def _extract_text(path: Path) -> str:
    try:
        from striprtf.striprtf import rtf_to_text
    except ImportError:
        raise RTFExtractionError(
            "\n\n  RTF parsing requires the office extra.\n"
            "     Install with:  pip install rtfm-ai[office]\n"
        )
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        return rtf_to_text(raw, errors="ignore")
    except Exception as e:
        raise RTFExtractionError(f"striprtf failed: {e}")


@ParserRegistry.register
class RTFParser(BaseParser):
    """Parser for RTF (.rtf) documents."""

    extensions = [".rtf"]
    name = "rtf"

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None,
    ) -> Iterator[Chunk]:
        metadata = metadata or {}
        text = _extract_text(path)
        if not text.strip():
            return

        book_title = metadata.get("title") or extract_title_from_filename(path.stem)
        book_slug = metadata.get("book_slug") or slugify(book_title)
        book_file = metadata.get("source_file") or path.name

        paragraphs = split_into_paragraphs(text)
        chunks = merge_short_paragraphs(paragraphs)

        char_pos = 0
        for idx, chunk_text in enumerate(chunks, 1):
            page_start = estimate_page(char_pos)
            page_end = estimate_page(char_pos + len(chunk_text))

            yield Chunk(
                id=f"{book_slug}-{idx:04d}",
                content=chunk_text,
                book_title=book_title,
                book_slug=book_slug,
                book_file=book_file,
                chapter_title=path.name,
                chapter_num=idx,
                page_start=page_start,
                page_end=page_end,
                paragraph=1,
                section_type="paragraph",
                content_chars=len(chunk_text),
                content_hash=content_hash(chunk_text),
                metadata=metadata.get("extended", {}),
            )
            char_pos += len(chunk_text)

    def extract_metadata(self, path: Path) -> dict:
        return {
            "source_file": path.name,
            "book_slug": slugify(path.stem),
            "title": extract_title_from_filename(path.stem),
        }
