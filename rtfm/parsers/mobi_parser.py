"""MOBI / AZW / AZW3 (Kindle) parser — best-effort.

Uses the `mobi` library to extract the book to a temp dir (HTML + assets),
then strips the HTML with BeautifulSoup. DRM-protected files cannot be
read; we surface a clean error rather than producing garbage.

Install: pip install rtfm-ai[mobi]
Note: Amazon DRM is not bypassed. Only DRM-free MOBI/AZW files are usable.
"""

import shutil
import tempfile
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


class MOBIExtractionError(Exception):
    pass


def _require_deps():
    try:
        import mobi  # noqa: F401
        from bs4 import BeautifulSoup  # noqa: F401
    except ImportError:
        raise MOBIExtractionError(
            "\n\n  MOBI parsing requires the mobi extra.\n"
            "     Install with:  pip install rtfm-ai[mobi]\n"
        )


def _html_to_text(html_bytes: bytes) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_bytes, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    blocks = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "blockquote"]):
        text = el.get_text(" ", strip=True)
        if text:
            blocks.append(text)
    if blocks:
        return "\n\n".join(blocks)
    return soup.get_text("\n", strip=True)


@ParserRegistry.register
class MOBIParser(BaseParser):
    """Parser for Kindle MOBI/AZW/AZW3 ebooks (DRM-free only)."""

    extensions = [".mobi", ".azw", ".azw3"]
    name = "mobi"

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None,
    ) -> Iterator[Chunk]:
        _require_deps()
        import mobi

        metadata = metadata or {}
        tempdir = None
        try:
            try:
                tempdir, extracted = mobi.extract(str(path))
            except Exception as e:
                raise MOBIExtractionError(
                    f"mobi extraction failed (possibly DRM-protected): {e}"
                )

            extracted_path = Path(extracted)
            if extracted_path.is_dir():
                html_files = sorted(extracted_path.glob("*.html")) + \
                             sorted(extracted_path.glob("*.xhtml"))
            elif extracted_path.is_file():
                html_files = [extracted_path]
            else:
                return

            if not html_files:
                return

            book_title = metadata.get("title") or extract_title_from_filename(path.stem)
            book_slug = metadata.get("book_slug") or slugify(book_title)
            book_file = metadata.get("source_file") or path.name

            chunk_counter = 0
            char_pos = 0

            for chapter_num, html_file in enumerate(html_files, 1):
                try:
                    html = html_file.read_bytes()
                except OSError:
                    continue
                text = _html_to_text(html)
                if not text.strip():
                    continue

                paragraphs = split_into_paragraphs(text)
                chunks = merge_short_paragraphs(paragraphs)

                for para_num, chunk_text in enumerate(chunks, 1):
                    chunk_counter += 1
                    page_start = estimate_page(char_pos)
                    page_end = estimate_page(char_pos + len(chunk_text))

                    yield Chunk(
                        id=f"{book_slug}-ch{chapter_num:03d}-{chunk_counter:04d}",
                        content=chunk_text,
                        book_title=book_title,
                        book_slug=book_slug,
                        book_file=book_file,
                        chapter_title=html_file.stem,
                        chapter_num=chapter_num,
                        page_start=page_start,
                        page_end=page_end,
                        paragraph=para_num,
                        section_type="chapter",
                        content_chars=len(chunk_text),
                        content_hash=content_hash(chunk_text),
                        metadata=metadata.get("extended", {}),
                    )
                    char_pos += len(chunk_text)
        finally:
            if tempdir and Path(tempdir).exists():
                shutil.rmtree(tempdir, ignore_errors=True)

    def extract_metadata(self, path: Path) -> dict:
        return {
            "source_file": path.name,
            "book_slug": slugify(path.stem),
            "title": extract_title_from_filename(path.stem),
        }
