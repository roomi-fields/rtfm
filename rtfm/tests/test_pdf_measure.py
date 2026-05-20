"""Robustness tests for measure_pdf_text — it must never crash or hang
on bad input, since it runs unattended over whole corpora on slow
DrvFs mounts."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pypdfium2")

from rtfm.parsers.pdf import measure_pdf_text, SCAN_SAMPLE_PAGES


def test_missing_file_returns_error(tmp_path):
    r = measure_pdf_text(tmp_path / "nope.pdf")
    assert r["error"] is not None
    assert r["pages"] == 0
    assert r["chars_per_page"] == 0.0


def test_empty_file_returns_error(tmp_path):
    p = tmp_path / "empty.pdf"
    p.write_bytes(b"")
    r = measure_pdf_text(p)
    assert r["error"] == "empty file"


def test_non_pdf_bytes_return_error_not_exception(tmp_path):
    """A file with a PDF extension but garbage content must surface as
    an 'error' result, never raise (would abort a corpus scan)."""
    p = tmp_path / "fake.pdf"
    p.write_bytes(b"this is plainly not a pdf " * 100)
    r = measure_pdf_text(p)
    assert r["error"] is not None
    assert r["pages"] == 0


def test_truncated_pdf_header_returns_error(tmp_path):
    p = tmp_path / "trunc.pdf"
    p.write_bytes(b"%PDF-1.4\n garbage truncated")
    r = measure_pdf_text(p)
    # pdfium rejects it — error, not a crash
    assert r["error"] is not None


def test_result_shape_keys():
    """Contract: result always has these keys regardless of outcome."""
    r = measure_pdf_text(Path("/does/not/exist.pdf"))
    assert set(r) == {"pages", "sampled_pages", "chars",
                      "chars_per_page", "error"}


def test_default_sample_is_bounded():
    assert SCAN_SAMPLE_PAGES <= 20  # cheap by design
