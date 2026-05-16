"""EPUB parser.

Uses ebooklib to read the ZIP container + manifest, and BeautifulSoup to
strip the XHTML markup of each chapter. Each spine item becomes a chunked
"chapter". Metadata (title, author) is read from the OPF when available.

Install: pip install rtfm-ai[epub]
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


class EPUBExtractionError(Exception):
    """Raised when EPUB extraction fails."""
    pass


def _require_deps():
    try:
        import ebooklib  # noqa: F401
        from ebooklib import epub  # noqa: F401
        from bs4 import BeautifulSoup  # noqa: F401
    except ImportError:
        raise EPUBExtractionError(
            "\n\n  EPUB parsing requires the epub extra.\n"
            "     Install with:  pip install rtfm-ai[epub]\n"
        )


def _html_to_text(html_bytes: bytes) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_bytes, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    # collapse runs of whitespace inside each block, separate blocks with \n\n
    blocks = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "blockquote"]):
        text = el.get_text(" ", strip=True)
        if text:
            blocks.append(text)
    if blocks:
        return "\n\n".join(blocks)
    # fallback: full text
    return soup.get_text("\n", strip=True)


def _chapter_title(html_bytes: bytes) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_bytes, "html.parser")
    for tag in ("h1", "h2", "h3", "title"):
        el = soup.find(tag)
        if el:
            text = el.get_text(" ", strip=True)
            if text:
                return text
    return ""


@ParserRegistry.register
class EPUBParser(BaseParser):
    """Parser for EPUB (.epub) ebooks."""

    extensions = [".epub"]
    name = "epub"

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None,
    ) -> Iterator[Chunk]:
        _require_deps()
        from ebooklib import epub, ITEM_DOCUMENT

        metadata = metadata or {}

        try:
            book = epub.read_epub(str(path), options={"ignore_ncx": True})
        except Exception as e:
            raise EPUBExtractionError(f"epub read failed: {e}")

        opf_title = ""
        opf_author = ""
        try:
            titles = book.get_metadata("DC", "title")
            if titles:
                opf_title = titles[0][0]
            authors = book.get_metadata("DC", "creator")
            if authors:
                opf_author = authors[0][0]
        except Exception:
            pass

        book_title = metadata.get("title") or opf_title or extract_title_from_filename(path.stem)
        book_slug = metadata.get("book_slug") or slugify(book_title)
        book_file = metadata.get("source_file") or path.name

        extended = dict(metadata.get("extended", {}))
        if opf_author and "author" not in extended:
            extended["author"] = opf_author

        chunk_counter = 0
        char_pos = 0
        chapter_num = 0

        # Walk spine order if available, else iterate documents
        spine_ids = [s[0] for s in book.spine] if book.spine else []
        items = []
        for sid in spine_ids:
            item = book.get_item_with_id(sid)
            if item is not None:
                items.append(item)
        if not items:
            items = list(book.get_items_of_type(ITEM_DOCUMENT))

        for item in items:
            html = item.get_content()
            if not html:
                continue
            text = _html_to_text(html)
            if not text.strip():
                continue

            chapter_num += 1
            title = _chapter_title(html) or f"Chapter {chapter_num}"

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
                    chapter_title=title,
                    chapter_num=chapter_num,
                    page_start=page_start,
                    page_end=page_end,
                    paragraph=para_num,
                    section_type="chapter",
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
            _require_deps()
            from ebooklib import epub
            book = epub.read_epub(str(path), options={"ignore_ncx": True})
            titles = book.get_metadata("DC", "title")
            if titles:
                meta["title"] = titles[0][0]
                meta["book_slug"] = slugify(titles[0][0])
            authors = book.get_metadata("DC", "creator")
            if authors:
                meta["author"] = authors[0][0]
        except Exception:
            pass
        return meta
