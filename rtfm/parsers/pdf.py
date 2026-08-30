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
import threading
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


# How many leading pages to sample when measuring text density. The
# scan signal (chars/page near 0) is unambiguous on the first handful
# of pages, so there is no need to extract a 700-page book in full —
# that was a big part of what saturated I/O during the cross-team
# freeze. A born-digital PDF shows hundreds of chars on page 1.
SCAN_SAMPLE_PAGES = 10


def measure_pdf_text(path: Path, sample_pages: int = SCAN_SAMPLE_PAGES) -> dict:
    """Measure a PDF's real text density, deterministically and *cheaply*.

    Reads the actual file (never the DB's possibly-stale total_chars)
    but is hardened for huge corpora on slow DrvFs/9p (NTFS-via-WSL)
    mounts, per the freeze post-mortem:

    * **Buffer read** — the file bytes are read in Python
      (``open().read()``, an interruptible syscall we own) and handed to
      pypdfium2 as a buffer, instead of letting pdfium open the path and
      do the blocking I/O itself.
    * **Page sampling** — only the first ``sample_pages`` pages are
      text-extracted. The scan signal is unambiguous there; extracting a
      700-page book in full was pure I/O waste.
    * **In-process** — pypdfium2 means no ``pdfinfo``/``pdftotext``
      subprocess that could wedge in uninterruptible D-state on DrvFs.

    Returns ``{pages, sampled_pages, chars, chars_per_page, error}``.
    ``pages`` is the true total; ``chars_per_page`` is over the sampled
    pages. A non-None ``error`` is the third "unreadable" state — such a
    file can't be OCR'd by marker either (same backend).
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return {"pages": 0, "sampled_pages": 0, "chars": 0,
                "chars_per_page": 0.0, "error": "pypdfium2 not installed"}

    # Read bytes ourselves — interruptible, and keeps pdfium off the
    # raw DrvFs path syscall.
    try:
        data = path.read_bytes()
    except OSError as e:
        return {"pages": 0, "sampled_pages": 0, "chars": 0,
                "chars_per_page": 0.0, "error": f"read failed: {e}"}
    if not data:
        return {"pages": 0, "sampled_pages": 0, "chars": 0,
                "chars_per_page": 0.0, "error": "empty file"}

    import warnings
    try:
        # The one pdfium call left in-process (CLI `rtfm doctor`). The lock
        # keeps it from ever overlapping another one — see _PDFIUM_LOCK.
        with _PDFIUM_LOCK, warnings.catch_warnings():
            warnings.simplefilter("ignore")
            doc = pdfium.PdfDocument(data)
            try:
                n = len(doc)
                if n <= 0:
                    return {"pages": 0, "sampled_pages": 0, "chars": 0,
                            "chars_per_page": 0.0, "error": "zero pages"}
                sampled = min(sample_pages, n)
                total = 0
                for i in range(sampled):
                    tp = doc[i].get_textpage()
                    total += len(tp.get_text_bounded().strip())
            finally:
                doc.close()
    except Exception as e:
        return {"pages": 0, "sampled_pages": 0, "chars": 0,
                "chars_per_page": 0.0, "error": f"{type(e).__name__}: {e}"}

    return {"pages": n, "sampled_pages": sampled, "chars": total,
            "chars_per_page": total / sampled, "error": None}


# pdfium carries process-global, unsynchronised state. Two threads that
# open or page through a document at the same time corrupt it: the field
# report was "Failed to load document (PDFium: Data format error)" on
# files that read perfectly on their own, and — often enough — a segfault
# inside libpdfium.so. A segfault is not catchable: it took down the whole
# supervisor, stranding every claim its twelve lanes were holding, so one
# awkward PDF cost a fleet-wide stall.
#
# So no pdfium work runs in the daemon's own process any more. Every
# document goes through a one-shot child (the same shape as the marker
# child below): separate address space, separate pdfium globals, and a
# crash costs exactly one file. The lock below is what remains for the
# one in-process caller, ``measure_pdf_text``, which runs from the CLI.
_PDFIUM_LOCK = threading.Lock()

# Wall-clock budgets for the child. Text extraction of even a large book
# is seconds; ten minutes means pdfium is wedged (a dead network mount,
# a pathological file) and the lane is better spent elsewhere. OCR is
# legitimately slow, and is already cut into page tranches upstream.
_PDFTEXT_TIMEOUT_S = 10 * 60
_TESSERACT_TIMEOUT_S = 30 * 60

_PDFIUM_CHILD_CODE = r"""
import json, sys, traceback
try:
    from rtfm.parsers.pdf import run_pdfium_op
except Exception as e:
    print(json.dumps({"error": "import: %s" % e}))
    sys.exit(2)
try:
    print(json.dumps({"result": run_pdfium_op(json.loads(sys.argv[1]))}))
except Exception as e:
    print(json.dumps({"error": str(e), "kind": type(e).__name__,
                      "trace": traceback.format_exc()}))
    sys.exit(3)
"""


def run_pdfium_op(request: dict):
    """Execute one pdfium operation in the current process.

    The child's entry point — and the only place the in-process bodies are
    called from in the daemon. Kept public because the child imports it by
    name.
    """
    op = request.get("op")
    path = Path(request["path"])
    with _PDFIUM_LOCK:
        if op == "text":
            return _pdftext_inprocess(path)
        if op == "metadata":
            return _pdfmeta_inprocess(path)
        if op == "ocr":
            return _tesseract_inprocess(
                path,
                langs=request.get("langs", TESSERACT_DEFAULT_LANGS),
                page_start=request.get("page_start", 1),
                page_end=request.get("page_end"),
                scale=request.get("scale", TESSERACT_RENDER_SCALE),
            )
    raise PDFExtractionError(f"unknown pdfium operation: {op!r}")


def _call_pdfium_child(request: dict, timeout: int, what: str):
    """Run one pdfium operation in a disposable child process.

    Raises:
        PDFExtractionError: on crash, timeout, or a failure reported by the
            child. A crash names the signal — the caller's job fails, the
            worker does not.
    """
    import json
    import os
    import subprocess
    import sys

    # The child imports rtfm; make sure it can even when the interpreter
    # running us was started from somewhere else entirely.
    package_parent = str(Path(__file__).resolve().parents[2])
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    env["PYTHONPATH"] = os.pathsep.join(
        [package_parent, env["PYTHONPATH"]] if env.get("PYTHONPATH")
        else [package_parent]
    )

    try:
        proc = subprocess.run(
            [sys.executable, "-c", _PDFIUM_CHILD_CODE, json.dumps(request)],
            capture_output=True, text=True, errors="replace",
            timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        raise PDFExtractionError(
            f"{what} timed out after {timeout}s on {request['path']}"
        )

    if proc.returncode < 0:
        raise PDFExtractionError(
            f"pdfium crashed (signal {-proc.returncode}) on {request['path']} "
            f"— the file is skipped; the worker is unaffected"
        )

    payload = None
    if proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            payload = None

    if payload is None:
        msg = proc.stderr.strip() or proc.stdout.strip() or "no output"
        raise PDFExtractionError(f"{what} failed: {msg}")
    if "error" in payload:
        # A PDFExtractionError already reads as a full sentence about this
        # file — prefixing it again would say "pdftext extraction failed:
        # pdftext extraction failed: ...". Anything else needs the context.
        if payload.get("kind") == "PDFExtractionError":
            raise PDFExtractionError(payload["error"])
        raise PDFExtractionError(f"{what} failed: {payload['error']}")
    return payload.get("result")


def extract_with_pdftext(path: Path) -> list[dict]:
    """Extract text using pdftext, in a disposable child process.

    Returns list of dicts with 'page' and 'text' keys.
    """
    return _call_pdfium_child(
        {"op": "text", "path": str(path)},
        _PDFTEXT_TIMEOUT_S, "pdftext extraction",
    )


def _pdftext_inprocess(path: Path) -> list[dict]:
    """The pdftext body itself. Only ever called inside the child."""
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


# Default OCR languages and render scale for tesseract. scale=2.0 maps a
# typical PDF page to ~150-200 DPI, the sweet spot for tesseract accuracy
# vs. speed/memory.
TESSERACT_DEFAULT_LANGS = "eng+fra"
TESSERACT_RENDER_SCALE = 2.0


def extract_with_tesseract(
    path: Path,
    langs: str = TESSERACT_DEFAULT_LANGS,
    page_start: int = 1,
    page_end: Optional[int] = None,
    scale: float = TESSERACT_RENDER_SCALE,
) -> list[dict]:
    """OCR a (range of) PDF page(s) with tesseract, in a child process.

    ``page_start``/``page_end`` are 1-indexed and inclusive; this is what
    lets the worker split a big scan into short, resumable P3 tranches.

    Returns ``[{'page': n, 'text': ...}, ...]`` for pages with text.
    """
    return _call_pdfium_child(
        {"op": "ocr", "path": str(path), "langs": langs,
         "page_start": page_start, "page_end": page_end, "scale": scale},
        _TESSERACT_TIMEOUT_S, "tesseract extraction",
    )


def _tesseract_inprocess(
    path: Path,
    langs: str = TESSERACT_DEFAULT_LANGS,
    page_start: int = 1,
    page_end: Optional[int] = None,
    scale: float = TESSERACT_RENDER_SCALE,
) -> list[dict]:
    """The tesseract body itself. Only ever called inside the child.

    Renders each page to an image via pypdfium2 (already a dependency)
    and OCRs it with tesseract (a fast C binary, no multi-GB ML models
    → no OOM/timeout that sank marker on CPU). Pages are processed one
    at a time so memory stays bounded even on a 600-page book.

    ``page_start``/``page_end`` are 1-indexed and inclusive; this is what
    lets the worker split a big scan into short, resumable P3 tranches.

    Returns ``[{'page': n, 'text': ...}, ...]`` for pages with text.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise PDFExtractionError(
            "\n\n  ❌ OCR requires the pdf extra (pypdfium2).\n"
            "     Install with:  pip install rtfm-ai[pdf]\n"
        )
    try:
        import pytesseract
        from PIL import Image  # noqa: F401 — pytesseract needs PIL
    except ImportError:
        raise PDFExtractionError(
            "\n\n  ❌ tesseract OCR backend requires pytesseract + Pillow.\n"
            "     Install with:  pip install rtfm-ai[ocr]\n"
            "     and the tesseract binary (apt install tesseract-ocr).\n"
        )

    # Keep only languages actually installed, so a missing pack doesn't
    # abort the whole page with a tesseract error.
    try:
        available = set(pytesseract.get_languages(config=""))
        requested = [l for l in langs.split("+") if l in available]
        eff_langs = "+".join(requested) or "eng"
    except Exception:
        eff_langs = langs

    import warnings
    try:
        data = path.read_bytes()
    except OSError as e:
        raise PDFExtractionError(f"read failed: {e}")

    out: list[dict] = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            doc = pdfium.PdfDocument(data)
            try:
                n = len(doc)
                lo = max(1, page_start)
                hi = min(n, page_end if page_end is not None else n)
                for i in range(lo - 1, hi):  # 0-indexed range
                    page = doc[i]
                    bitmap = page.render(scale=scale)
                    pil = bitmap.to_pil()
                    try:
                        text = pytesseract.image_to_string(pil, lang=eff_langs)
                    finally:
                        pil.close()
                    if text and text.strip():
                        out.append({"page": i + 1, "text": text})
            finally:
                doc.close()
    except PDFExtractionError:
        raise
    except Exception as e:
        raise PDFExtractionError(f"tesseract extraction failed: {e}")
    return out


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


def _pdfmeta_inprocess(path: Path) -> dict:
    """Read a PDF's own title/author. Only ever called inside the child."""
    from pdftext.extraction import dictionary_output

    info = dictionary_output(str(path), page_range=[0])
    if info and isinstance(info, dict):
        return info.get("metadata") or {}
    return {}


def pages_to_chunks(
    pages: list[dict],
    book_slug: str,
    book_title: str,
    book_file: str,
    ext_meta: Optional[dict] = None,
    page_offset: int = 0,
) -> Iterator[Chunk]:
    """Turn ``[{'page': n, 'text': ...}]`` into Chunks.

    Shared by ``PDFParser.parse`` and the P3 OCR handler so OCR'd page
    ranges produce exactly the same chunk shape as a normal parse.
    ``chunk_id`` embeds the page number, so a per-tranche re-run yields
    stable ids and the page-range delete in ``append_ocr_chunks`` is
    idempotent.
    """
    ext_meta = ext_meta or {}
    for page_info in pages:
        page_num = page_info['page']
        page_text = page_info['text']
        paragraphs = split_into_paragraphs(page_text)
        chunks = merge_short_paragraphs(paragraphs)
        for para_num, chunk_text in enumerate(chunks, 1):
            chunk_id = f"{book_slug}-p{page_num:03d}-{para_num:03d}"
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
                metadata=ext_meta,
            )


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

        # Surface the real page count so the indexer can store it and
        # compute a deterministic chars-per-page scan signal. ``metadata``
        # is the same dict ``Library.ingest`` passes to ``_index_chunks``,
        # so this write is visible there.
        metadata['page_count'] = len(pages)

        # Document metadata
        book_title = metadata.get('title') or extract_title_from_filename(path.stem)
        book_slug = metadata.get('book_slug') or slugify(book_title)
        book_file = metadata.get('source_file') or path.name

        yield from pages_to_chunks(
            pages, book_slug, book_title, book_file,
            ext_meta=metadata.get('extended', {}),
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
            pdf_meta = _call_pdfium_child(
                {"op": "metadata", "path": str(path)},
                _PDFTEXT_TIMEOUT_S, "pdf metadata",
            ) or {}
            if pdf_meta.get('title'):
                metadata['title'] = pdf_meta['title']
            if pdf_meta.get('author'):
                metadata['author'] = pdf_meta['author']
        except Exception:
            # Title and author are a nicety; the filename already gives a
            # usable title. Never let metadata cost us the document.
            pass

        return metadata
