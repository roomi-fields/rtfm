"""
PDF parser for rtfm.

Supports two extraction modes:
- pdftext: Fast, basic text extraction (default)
- marker: High-quality extraction with layout awareness (optional)

Install dependencies:
    pip install rtfm[pdf]
    # or
    pip install pdftext marker-pdf
"""

import re
import hashlib
from pathlib import Path
from typing import Iterator, Optional

from rtfm.core.models import Chunk
from rtfm.parsers.base import BaseParser, ParserRegistry


# Chunk sizing (same as markdown parser)
TARGET_CHUNK_CHARS = 1500
MIN_CHUNK_CHARS = 200
MAX_CHUNK_CHARS = 3000


def slugify(text: str) -> str:
    """Convert text to a slug."""
    text = re.sub(r'\([^)]*\)', '', text)
    text = text.replace('.pdf', '')
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')[:50]


def content_hash(text: str) -> str:
    """Generate a short hash of content."""
    return hashlib.md5(text.encode()).hexdigest()[:12]


def extract_title_from_filename(filename: str) -> str:
    """Extract a clean title from the filename."""
    title = re.sub(r'\([^)]*\)', '', filename)
    title = title.replace('.pdf', '')
    title = title.replace('-', ' ').replace('_', ' ')
    title = ' '.join(title.split())
    return title.strip()


def split_into_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs."""
    paragraphs = re.split(r'\n\s*\n', text)
    result = []
    for p in paragraphs:
        p = ' '.join(p.split())
        if p and len(p) > 20:
            result.append(p)
    return result


def split_on_sentence(text: str, max_chars: int) -> list[str]:
    """Split text at sentence boundaries."""
    if len(text) <= max_chars:
        return [text]

    sentence_ends = []
    for i, char in enumerate(text):
        if char in '.!?' and (i + 1 >= len(text) or text[i + 1] in ' \n'):
            sentence_ends.append(i + 1)

    if not sentence_ends:
        return [text[:max_chars].strip(), text[max_chars:].strip()]

    chunks = []
    chunk_start = 0
    prev_end = 0

    for end in sentence_ends:
        current_len = end - chunk_start
        if current_len > max_chars and prev_end > chunk_start:
            chunks.append(text[chunk_start:prev_end].strip())
            chunk_start = prev_end
        prev_end = end

    if chunk_start < len(text):
        remaining = text[chunk_start:].strip()
        if remaining:
            chunks.append(remaining)

    return chunks if chunks else [text]


def merge_short_paragraphs(paragraphs: list[str]) -> list[str]:
    """Merge paragraphs that are too short, split those that are too long."""
    if not paragraphs:
        return []

    result = []
    buffer = ""

    for p in paragraphs:
        if buffer:
            buffer += "\n\n" + p
        else:
            buffer = p

        if len(buffer) >= TARGET_CHUNK_CHARS:
            if len(buffer) > MAX_CHUNK_CHARS:
                chunks = split_on_sentence(buffer, MAX_CHUNK_CHARS)
                result.extend(chunks[:-1])
                buffer = chunks[-1] if chunks else ""
            else:
                result.append(buffer)
                buffer = ""

    if buffer:
        if result and len(buffer) < MIN_CHUNK_CHARS:
            result[-1] += "\n\n" + buffer
        else:
            result.append(buffer)

    return result


class PDFExtractionError(Exception):
    """Raised when PDF extraction fails."""
    pass


def extract_with_pdftext(path: Path) -> list[dict]:
    """
    Extract text using pdftext (fast, basic).

    Returns list of dicts with 'page' and 'text' keys.
    """
    try:
        from pdftext.extraction import plain_text_output
    except ImportError:
        raise PDFExtractionError(
            "pdftext not installed. Install with: pip install pdftext"
        )

    try:
        # pdftext returns text per page
        pages_text = plain_text_output(str(path))

        # Handle different return types
        if isinstance(pages_text, str):
            # Single string - split by form feeds or treat as one page
            if '\f' in pages_text:
                pages = pages_text.split('\f')
            else:
                pages = [pages_text]
        elif isinstance(pages_text, list):
            pages = pages_text
        else:
            pages = [str(pages_text)]

        return [
            {'page': i + 1, 'text': text}
            for i, text in enumerate(pages)
            if text.strip()
        ]
    except Exception as e:
        raise PDFExtractionError(f"pdftext extraction failed: {e}")


def extract_with_marker(path: Path) -> list[dict]:
    """
    Extract text using marker-pdf (high quality, slower).

    Returns list of dicts with 'page' and 'text' keys.
    """
    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
    except ImportError:
        raise PDFExtractionError(
            "marker-pdf not installed. Install with: pip install marker-pdf"
        )

    try:
        # Initialize converter
        models = create_model_dict()
        converter = PdfConverter(artifact_dict=models)

        # Convert PDF
        result = converter(str(path))

        # Extract markdown content
        if hasattr(result, 'markdown'):
            markdown = result.markdown
        elif isinstance(result, tuple) and len(result) > 0:
            markdown = result[0]
        else:
            markdown = str(result)

        # Split by page markers or treat as single page
        # Marker doesn't always provide page breaks, so we estimate
        return [{'page': 1, 'text': markdown}]

    except Exception as e:
        raise PDFExtractionError(f"marker extraction failed: {e}")


@ParserRegistry.register
class PDFParser(BaseParser):
    """
    Parser for PDF files.

    Supports two extraction backends:
    - 'pdftext': Fast, basic extraction (default)
    - 'marker': High-quality with layout awareness

    Usage:
        parser = PDFParser(backend='pdftext')  # or 'marker'
        chunks = list(parser.parse(Path('document.pdf')))
    """

    extensions = ['.pdf', '.PDF']
    name = "pdf"

    def __init__(self, backend: str = 'pdftext', **config):
        """
        Initialize PDF parser.

        Args:
            backend: 'pdftext' (fast) or 'marker' (quality)
            **config: Additional configuration
        """
        super().__init__(**config)
        self.backend = backend

        if backend not in ('pdftext', 'marker'):
            raise ValueError(f"Unknown backend: {backend}. Use 'pdftext' or 'marker'.")

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None
    ) -> Iterator[Chunk]:
        """Parse a PDF file into chunks."""
        metadata = metadata or {}
        path = Path(path)

        # Extract text based on backend
        if self.backend == 'marker':
            pages = extract_with_marker(path)
        else:
            pages = extract_with_pdftext(path)

        if not pages:
            return

        # Document metadata
        book_title = metadata.get('title') or extract_title_from_filename(path.stem)
        book_slug = metadata.get('book_slug') or slugify(book_title)
        book_file = metadata.get('source_file') or path.name

        # Process each page
        chunk_counter = 0
        for page_info in pages:
            page_num = page_info['page']
            page_text = page_info['text']

            # Split into paragraphs and merge/split as needed
            paragraphs = split_into_paragraphs(page_text)
            chunks = merge_short_paragraphs(paragraphs)

            for para_num, chunk_text in enumerate(chunks, 1):
                chunk_counter += 1

                chunk_id = f"{book_slug}-p{page_num:03d}-{chunk_counter:04d}"

                yield Chunk(
                    id=chunk_id,
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
                    metadata=metadata.get('extended', {}),
                )

    def extract_metadata(self, path: Path) -> dict:
        """Extract metadata from PDF file."""
        metadata = {
            "source_file": path.name,
            "book_slug": slugify(path.stem),
            "title": extract_title_from_filename(path.stem),
        }

        # Try to extract PDF metadata
        try:
            from pdftext.extraction import dictionary_output
            info = dictionary_output(str(path), page_range=[0])
            if info and isinstance(info, dict):
                if 'metadata' in info:
                    pdf_meta = info['metadata']
                    if pdf_meta.get('title'):
                        metadata['title'] = pdf_meta['title']
                    if pdf_meta.get('author'):
                        metadata['author'] = pdf_meta['author']
        except:
            pass

        return metadata
