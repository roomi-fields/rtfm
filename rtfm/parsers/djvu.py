"""DJVU parser via the djvutxt CLI (djvulibre-bin).

DJVU is a scanned-document format common for academic papers. We shell out
to `djvutxt`, parse the per-page form-feed-separated output, and chunk like
the PDF parser. The lib is system-installed (apt install djvulibre-bin),
not a Python dependency.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Iterator, Optional

from rtfm.core.models import Chunk
from rtfm.parsers.base import BaseParser, ParserRegistry
from rtfm.parsers._chunking import (
    content_hash,
    extract_title_from_filename,
    merge_short_paragraphs,
    slugify,
    split_into_paragraphs,
)


class DJVUExtractionError(Exception):
    pass


def _djvutxt_available() -> bool:
    return shutil.which("djvutxt") is not None


def _extract_pages(path: Path) -> list[str]:
    if not _djvutxt_available():
        raise DJVUExtractionError(
            "\n\n  DJVU parsing requires djvulibre.\n"
            "     Install with:  sudo apt install djvulibre-bin\n"
            "                    (or `brew install djvulibre` on macOS)\n"
        )
    try:
        proc = subprocess.run(
            ["djvutxt", str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        raise DJVUExtractionError("djvutxt timed out (>120s)")
    if proc.returncode != 0:
        raise DJVUExtractionError(
            f"djvutxt failed (exit {proc.returncode}): {proc.stderr.strip()[:200]}"
        )
    text = proc.stdout
    # djvutxt separates pages with form feeds
    if "\f" in text:
        pages = text.split("\f")
    else:
        pages = [text]
    return [p for p in pages if p.strip()]


@ParserRegistry.register
class DJVUParser(BaseParser):
    """Parser for DJVU (.djvu, .djv) scanned documents."""

    extensions = [".djvu", ".djv"]
    name = "djvu"

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None,
    ) -> Iterator[Chunk]:
        metadata = metadata or {}
        pages = _extract_pages(path)
        if not pages:
            return

        book_title = metadata.get("title") or extract_title_from_filename(path.stem)
        book_slug = metadata.get("book_slug") or slugify(book_title)
        book_file = metadata.get("source_file") or path.name

        chunk_counter = 0
        for page_num, page_text in enumerate(pages, 1):
            paragraphs = split_into_paragraphs(page_text)
            chunks = merge_short_paragraphs(paragraphs)

            for para_num, chunk_text in enumerate(chunks, 1):
                chunk_counter += 1
                yield Chunk(
                    id=f"{book_slug}-p{page_num:03d}-{chunk_counter:04d}",
                    content=chunk_text,
                    book_title=book_title,
                    book_slug=book_slug,
                    book_file=book_file,
                    chapter_title=f"Page {page_num}",
                    chapter_num=page_num,
                    page_start=page_num,
                    page_end=page_num,
                    paragraph=para_num,
                    section_type="page",
                    content_chars=len(chunk_text),
                    content_hash=content_hash(chunk_text),
                    metadata=metadata.get("extended", {}),
                )

    def extract_metadata(self, path: Path) -> dict:
        return {
            "source_file": path.name,
            "book_slug": slugify(path.stem),
            "title": extract_title_from_filename(path.stem),
        }
