"""Magic-byte format sniffing for mislabeled files.

A surprising fraction of "PDFs" in real corpora are not PDFs: an EPUB
or DOCX (both ZIP containers) saved with a ``.pdf`` extension, an HTML
error page from a failed download, etc. pdftext/pdfium then fail with
an opaque "Data format error", and the file silently ends up with zero
chunks.

``detect_real_format`` reads the first few bytes and returns the true
container type, so the indexer can route the file to the right parser
(or flag it) instead of forcing it through the PDF path.

Deliberately tiny and dependency-free — just magic numbers.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def looks_binary(path: str | Path, probe: int = 8192) -> bool:
    """True when the file's first *probe* bytes contain a NUL byte.

    The single rule RTFM uses to decide "text or not" when no parser claims
    a file. Shared by the ingest catch-all and the edit hook so the hook
    never enqueues something ingest would refuse. An unreadable file is
    reported as binary (nothing to index either way).
    """
    try:
        with open(path, "rb") as fh:
            return b"\x00" in fh.read(probe)
    except OSError:
        return True


def detect_real_format(path: str | Path) -> Optional[str]:
    """Return a coarse real-format tag from the file's magic bytes:

        'pdf' | 'zip' | 'epub' | 'docx' | 'html' | 'rtf' | 'gzip'
        | 'empty' | 'unknown' | None (unreadable)

    ZIP-based formats (epub/docx/generic zip) are disambiguated by
    peeking for their signature member, which is cheap.
    """
    p = Path(path)
    try:
        with open(p, "rb") as f:
            head = f.read(16)
    except OSError:
        return None

    if not head:
        return "empty"

    if head.startswith(b"%PDF"):
        return "pdf"
    if head[:4] == b"PK\x03\x04" or head[:4] == b"PK\x05\x06":
        return _zip_subtype(p)
    if head[:5].lower() == b"<html" or head[:9].lower() == b"<!doctype":
        return "html"
    if head.startswith(b"{\\rtf"):
        return "rtf"
    if head[:2] == b"\x1f\x8b":
        return "gzip"
    return "unknown"


def _zip_subtype(p: Path) -> str:
    """Distinguish epub / docx / generic zip without a full unzip.

    EPUB: the first archive member is an uncompressed ``mimetype`` file
    whose content is ``application/epub+zip`` — and the spec puts it
    right after the local file header, so it shows up in the first KB.
    DOCX/XLSX/PPTX: contain a ``[Content_Types].xml`` member and
    ``word/`` | ``xl/`` | ``ppt/`` directories.
    """
    try:
        with open(p, "rb") as f:
            blob = f.read(2048)
    except OSError:
        return "zip"
    if b"application/epub+zip" in blob or b"mimetypeapplication/epub" in blob:
        return "epub"
    if b"word/" in blob or b"[Content_Types].xml" in blob and b"word" in blob:
        return "docx"
    if b"xl/" in blob:
        return "xlsx"
    if b"ppt/" in blob:
        return "pptx"
    return "zip"


# Map a detected real-format to the file extension RTFM's parser
# registry expects, when it differs from PDF.
FORMAT_TO_EXTENSION = {
    "epub": ".epub",
    "docx": ".docx",
    "xlsx": ".xlsx",
    "html": ".html",
    "rtf": ".rtf",
}
