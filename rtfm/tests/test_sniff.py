"""Tests for magic-byte format sniffing (``rtfm.core.sniff``)."""
from __future__ import annotations

from pathlib import Path

from rtfm.core.sniff import detect_real_format, FORMAT_TO_EXTENSION


def _write(p: Path, data: bytes) -> Path:
    p.write_bytes(data)
    return p


def test_detects_pdf(tmp_path):
    p = _write(tmp_path / "a.pdf", b"%PDF-1.4\n...")
    assert detect_real_format(p) == "pdf"


def test_detects_html(tmp_path):
    p = _write(tmp_path / "page.pdf", b"<!DOCTYPE html><html>...")
    assert detect_real_format(p) == "html"
    p2 = _write(tmp_path / "page2.pdf", b"<html><body>err</body></html>")
    assert detect_real_format(p2) == "html"


def test_detects_rtf(tmp_path):
    p = _write(tmp_path / "x.pdf", b"{\\rtf1\\ansi ...")
    assert detect_real_format(p) == "rtf"


def test_detects_gzip(tmp_path):
    p = _write(tmp_path / "x.pdf", b"\x1f\x8b\x08\x00...")
    assert detect_real_format(p) == "gzip"


def test_empty_file(tmp_path):
    p = _write(tmp_path / "x.pdf", b"")
    assert detect_real_format(p) == "empty"


def test_unknown(tmp_path):
    p = _write(tmp_path / "x.pdf", b"\x00\x01\x02\x03random")
    assert detect_real_format(p) == "unknown"


def test_missing_file_returns_none(tmp_path):
    assert detect_real_format(tmp_path / "nope.pdf") is None


def test_detects_epub(tmp_path):
    # Minimal EPUB: ZIP local header + the mimetype member content.
    blob = b"PK\x03\x04" + b"\x00" * 20 + b"mimetypeapplication/epub+zip" + b"\x00" * 10
    p = _write(tmp_path / "book.pdf", blob)
    assert detect_real_format(p) == "epub"


def test_detects_docx(tmp_path):
    blob = b"PK\x03\x04" + b"\x00" * 20 + b"[Content_Types].xml" + b"word/document.xml"
    p = _write(tmp_path / "doc.pdf", blob)
    assert detect_real_format(p) == "docx"


def test_generic_zip(tmp_path):
    blob = b"PK\x03\x04" + b"\x00" * 40
    p = _write(tmp_path / "z.pdf", blob)
    assert detect_real_format(p) == "zip"


def test_format_to_extension_map():
    assert FORMAT_TO_EXTENSION["epub"] == ".epub"
    assert FORMAT_TO_EXTENSION["docx"] == ".docx"
    assert "pdf" not in FORMAT_TO_EXTENSION  # pdf needs no rerouting
