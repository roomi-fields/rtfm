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
    if not result:
        stripped = text.strip()
        if stripped:
            result.append(' '.join(stripped.split()))
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
            "\n\n  ❌ PDF parsing requires the pdf extra.\n"
            "     Install with:  pip install rtfm-ai[pdf]\n"
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


# Subprocess body for marker OCR. Run as a one-shot child process so
# every PDF starts with a fresh interpreter — marker's pipeline holds
# 3-8 GB of model state and never releases it in-process, so before
# 0.9.5 a long OCR run accumulated RAM until WSL OOM-killed the worker
# and froze the host. The OS reclaims everything when the child exits.
_MARKER_SUBPROCESS_CODE = r"""
import json, sys, traceback
try:
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
except Exception as e:
    print(json.dumps({"error": f"import: {e}"}))
    sys.exit(2)
try:
    models = create_model_dict()
    converter = PdfConverter(artifact_dict=models)
    result = converter(sys.argv[1])
    if hasattr(result, "markdown"):
        md = result.markdown
    elif isinstance(result, tuple) and result:
        md = result[0]
    else:
        md = str(result)
    print(json.dumps({"markdown": md}))
except Exception as e:
    print(json.dumps({"error": f"{type(e).__name__}: {e}",
                      "trace": traceback.format_exc()}))
    sys.exit(3)
"""

# Per-PDF wall-clock budget for the marker subprocess. 20 min covers
# very large scanned PDFs on CPU; anything longer almost certainly
# means the file is broken or marker is stuck — better to fail and
# move on than to block the whole sync.
_MARKER_TIMEOUT_S = 20 * 60


def extract_with_marker(path: Path) -> list[dict]:
    """Extract text using marker-pdf in an isolated subprocess.

    Why subprocess: ``marker.models.create_model_dict()`` loads 3-8 GB
    of ML state (layout + OCR + table + reading-order pipelines). Marker
    caches that state at module level and never releases it, so doing
    sequential OCR in-process accumulates RAM until the worker is
    OOM-killed (which on WSL takes the whole VM down). A fresh Python
    process per PDF lets the OS reclaim the full footprint on exit.

    Returns list of dicts with 'page' and 'text' keys.
    """
    import json
    import os
    import subprocess
    import sys

    try:
        result = subprocess.run(
            [sys.executable, "-c", _MARKER_SUBPROCESS_CODE, str(path)],
            capture_output=True,
            text=True,
            timeout=_MARKER_TIMEOUT_S,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except subprocess.TimeoutExpired:
        raise PDFExtractionError(
            f"marker extraction timed out after {_MARKER_TIMEOUT_S}s on {path.name}"
        )
    except FileNotFoundError:
        raise PDFExtractionError(
            "\n\n  ❌ PDF marker backend requires the pdf extra.\n"
            "     Install with:  pip install rtfm-ai[pdf]\n"
        )

    if result.returncode != 0:
        # The subprocess prints structured JSON on the last stdout line
        # even when it raises, so try that before falling back to stderr.
        msg = result.stderr.strip() or result.stdout.strip()
        try:
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            msg = payload.get("error", msg)
        except (ValueError, IndexError):
            pass
        raise PDFExtractionError(f"marker subprocess failed: {msg}")

    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as e:
        raise PDFExtractionError(f"marker subprocess returned invalid output: {e}")

    if "error" in payload:
        raise PDFExtractionError(f"marker extraction failed: {payload['error']}")

    return [{"page": 1, "text": payload.get("markdown", "")}]


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
            backend: 'pdftext' (fast), 'marker' (quality OCR), or 'auto'
                (try pdftext first, fall back to marker when 0 pages of
                text were extracted — i.e. the PDF is a scanned image).
            **config: Additional configuration
        """
        super().__init__(**config)
        self.backend = backend

        if backend not in ('pdftext', 'marker', 'auto'):
            raise ValueError(
                f"Unknown backend: {backend}. Use 'pdftext', 'marker', or 'auto'."
            )

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
        elif self.backend == 'auto':
            pages = extract_with_pdftext(path)
            if not pages or all(not p.get('text', '').strip() for p in pages):
                # pdftext produced nothing extractable — almost always a
                # scanned image. Fall back to marker (OCR).
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
