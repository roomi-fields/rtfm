"""Tests for sync health signals: suspect PDF scans + empty files.

These tests exercise the health-warning plumbing that detects PDFs which
parsed without error but produced zero text (likely scans) and surfaces
the signal through SyncResult, the CLI, the MCP server, and the
UserPromptSubmit hook.
"""

from __future__ import annotations

import io
from pathlib import Path
from contextlib import redirect_stdout

import pytest

from rtfm.core.sync import SyncResult, quick_diff, sync


# ── SyncResult ────────────────────────────────────────────────────────────

def test_sync_result_has_health_fields():
    """SyncResult exposes suspect_scans + empty_files as empty lists by default."""
    r = SyncResult()
    assert r.suspect_scans == []
    assert r.empty_files == []
    d = r.to_dict()
    assert "suspect_scans" in d and "empty_files" in d


# ── End-to-end: monkeypatched ingest produces 0 chunks ────────────────────

def test_sync_flags_pdf_as_suspect_when_zero_chunks(library, tmp_path, monkeypatch):
    """A .pdf that ingests to 0 chunks goes into result.suspect_scans."""
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%fake\n%%EOF\n")

    def fake_ingest(self, path, corpus="default", parser=None, metadata=None):
        return {"chunks": 0, "chars": 0}

    monkeypatch.setattr(type(library), "ingest", fake_ingest)

    result = sync(
        library=library,
        root=tmp_path,
        corpus="test",
        extensions={".pdf"},
        generate_embeddings=False,
    )

    assert "scan.pdf" in result.suspect_scans
    assert result.empty_files == []


def test_sync_flags_non_pdf_as_empty_when_zero_chunks(library, tmp_path, monkeypatch):
    """A non-pdf that ingests to 0 chunks goes into result.empty_files."""
    md = tmp_path / "vide.md"
    md.write_text("")

    def fake_ingest(self, path, corpus="default", parser=None, metadata=None):
        return {"chunks": 0, "chars": 0}

    monkeypatch.setattr(type(library), "ingest", fake_ingest)

    result = sync(
        library=library,
        root=tmp_path,
        corpus="test",
        extensions={".md"},
        generate_embeddings=False,
    )

    assert "vide.md" in result.empty_files
    assert result.suspect_scans == []


def test_sync_does_not_flag_when_chunks_extracted(library, tmp_path, monkeypatch):
    """Healthy ingest (>0 chunks) leaves both lists empty."""
    pdf = tmp_path / "ok.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%real\n%%EOF\n")

    def fake_ingest(self, path, corpus="default", parser=None, metadata=None):
        return {"chunks": 5, "chars": 1234}

    monkeypatch.setattr(type(library), "ingest", fake_ingest)

    result = sync(
        library=library,
        root=tmp_path,
        corpus="test",
        extensions={".pdf"},
        generate_embeddings=False,
    )

    assert result.suspect_scans == []
    assert result.empty_files == []


# ── quick_diff: cheap path/size comparison for status ────────────────────

def test_quick_diff_detects_new_files(library, tmp_path):
    """quick_diff reports brand-new files as added without hashing."""
    (tmp_path / "a.md").write_text("hello")
    (tmp_path / "b.md").write_text("world")
    qd = quick_diff(library, tmp_path, "test", extensions={".md"})
    rels = {str(p.relative_to(tmp_path)) for p in qd.added}
    assert rels == {"a.md", "b.md"}
    assert qd.modified == []


def test_quick_diff_detects_modified_when_size_changes(library, tmp_path, monkeypatch):
    """quick_diff flags a tracked file whose on-disk size differs from the
    stored file_size as modified."""
    (tmp_path / "doc.md").write_text("hello")

    def fake_indexed(self, corpus=None):
        return {
            "doc.md": {
                "file_hash": "stale",
                "corpus": "test",
                "book_slug": "doc",
                "indexed_at": "2026-01-01T00:00:00",
                "file_size": 999,  # disk file is 5 bytes — size mismatch
            }
        }

    monkeypatch.setattr(type(library), "list_indexed_files", fake_indexed)
    qd = quick_diff(library, tmp_path, "test", extensions={".md"})
    assert [str(p.name) for p in qd.modified] == ["doc.md"]
    assert qd.added == []


def test_quick_diff_detects_removed(library, tmp_path, monkeypatch):
    """A file present in the index but missing on disk shows as removed."""
    def fake_indexed(self, corpus=None):
        return {
            "ghost.md": {
                "file_hash": "h", "corpus": "test", "book_slug": "ghost",
                "indexed_at": "2026-01-01T00:00:00", "file_size": 10,
            }
        }
    monkeypatch.setattr(type(library), "list_indexed_files", fake_indexed)
    qd = quick_diff(library, tmp_path, "test", extensions={".md"})
    assert qd.removed == ["ghost.md"]


# ── CLI helper: _print_health_warnings ────────────────────────────────────

def test_cli_health_warnings_prints_scans():
    """_print_health_warnings emits a scan block when suspect_scans is set."""
    from rtfm.cli import _print_health_warnings

    r = SyncResult()
    r.suspect_scans = ["a.pdf", "b.pdf", "c.pdf"]
    buf = io.StringIO()
    with redirect_stdout(buf):
        _print_health_warnings(r)
    out = buf.getvalue()
    assert "3 PDF probablement scannés" in out
    assert "a.pdf" in out
    assert "OCR" in out


def test_cli_health_warnings_silent_when_clean():
    """No suspects + no empty files → no output."""
    from rtfm.cli import _print_health_warnings

    buf = io.StringIO()
    with redirect_stdout(buf):
        _print_health_warnings(SyncResult())
    assert buf.getvalue() == ""


def test_cli_health_warnings_truncates_long_lists():
    """Long lists are truncated with a '+N more' line."""
    from rtfm.cli import _print_health_warnings

    r = SyncResult()
    r.suspect_scans = [f"scan_{i}.pdf" for i in range(15)]
    buf = io.StringIO()
    with redirect_stdout(buf):
        _print_health_warnings(r)
    out = buf.getvalue()
    assert "scan_0.pdf" in out
    assert "scan_9.pdf" in out
    assert "scan_14.pdf" not in out
    assert "5 autre(s)" in out


# ── MCP rtfm_sync: ACTION REQUIRED block on suspect scans ─────────────────

def test_mcp_sync_emits_action_required_for_scans(library, tmp_path, monkeypatch):
    """rtfm_sync surfaces an ACTION REQUIRED block when scans are detected."""
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

    def fake_ingest(self, path, corpus="default", parser=None, metadata=None):
        return {"chunks": 0, "chars": 0}

    monkeypatch.setattr(type(library), "ingest", fake_ingest)

    # Point the MCP module at our temp library
    import rtfm.mcp as mcp_mod
    monkeypatch.setattr(mcp_mod, "_get_library", lambda: library)
    monkeypatch.setattr(mcp_mod, "_embed_in_background", lambda corpus=None: None)

    out = mcp_mod.rtfm_sync(path=str(tmp_path), corpus="test", extensions="pdf")
    assert "ACTION REQUIRED" in out
    assert "scan.pdf" in out
    assert "OCR" in out


def test_mcp_sync_silent_when_clean(library, tmp_path, monkeypatch):
    """rtfm_sync omits ACTION REQUIRED block when no scans detected."""
    import rtfm.mcp as mcp_mod
    monkeypatch.setattr(mcp_mod, "_get_library", lambda: library)
    monkeypatch.setattr(mcp_mod, "_embed_in_background", lambda corpus=None: None)

    out = mcp_mod.rtfm_sync(path=str(tmp_path), corpus="test", extensions="md")
    assert "ACTION REQUIRED" not in out


def test_mcp_action_required_points_to_rtfm_sync_ocr(library, tmp_path, monkeypatch):
    """The ACTION REQUIRED block must point to `rtfm sync --ocr` so the
    agent can propose an exact, executable command to the user."""
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

    def fake_ingest(self, path, corpus="default", parser=None, metadata=None):
        return {"chunks": 0, "chars": 0}

    monkeypatch.setattr(type(library), "ingest", fake_ingest)
    import rtfm.mcp as mcp_mod
    monkeypatch.setattr(mcp_mod, "_get_library", lambda: library)
    monkeypatch.setattr(mcp_mod, "_embed_in_background", lambda corpus=None: None)

    out = mcp_mod.rtfm_sync(path=str(tmp_path), corpus="test", extensions="pdf")
    assert "rtfm sync --ocr" in out
    assert "ON APPROVAL RUN: rtfm sync --ocr" in out


# ── OCR fallback: PDFParser backend='auto' ────────────────────────────────

def test_pdf_parser_auto_falls_back_to_marker(monkeypatch, tmp_path):
    """backend='auto' tries pdftext first, then marker when pdftext
    returns no extractable text (i.e. the file is a scan)."""
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

    pdftext_calls = []
    marker_calls = []

    def fake_pdftext(path):
        pdftext_calls.append(path)
        return [{"page": 1, "text": "   "}]  # blank — triggers fallback

    def fake_marker(path):
        marker_calls.append(path)
        return [{"page": 1, "text": "OCR'd content paragraph " * 30}]

    from rtfm.parsers import pdf as pdf_mod
    monkeypatch.setattr(pdf_mod, "extract_with_pdftext", fake_pdftext)
    monkeypatch.setattr(pdf_mod, "extract_with_marker", fake_marker)

    parser = pdf_mod.PDFParser(backend="auto")
    chunks = list(parser.parse(pdf))
    assert len(pdftext_calls) == 1
    assert len(marker_calls) == 1
    assert chunks, "auto backend should produce chunks via marker fallback"


def test_pdf_parser_auto_skips_marker_when_pdftext_works(monkeypatch, tmp_path):
    """auto must NOT spin up marker when pdftext already returned text."""
    pdf = tmp_path / "real.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

    marker_calls = []
    def fake_pdftext(path):
        return [{"page": 1, "text": "real text " * 50}]
    def fake_marker(path):
        marker_calls.append(path)
        return []

    from rtfm.parsers import pdf as pdf_mod
    monkeypatch.setattr(pdf_mod, "extract_with_pdftext", fake_pdftext)
    monkeypatch.setattr(pdf_mod, "extract_with_marker", fake_marker)

    parser = pdf_mod.PDFParser(backend="auto")
    list(parser.parse(pdf))
    assert marker_calls == [], "marker should not run when pdftext succeeded"


def test_pdf_parser_rejects_unknown_backend():
    """The constructor must refuse unknown backend names."""
    from rtfm.parsers import pdf as pdf_mod
    import pytest
    with pytest.raises(ValueError):
        pdf_mod.PDFParser(backend="ocr-magic")


# ── sync(ocr_fallback=True) wires the auto-backend PDFParser ──────────────

def test_sync_ocr_fallback_injects_auto_parser(library, tmp_path, monkeypatch):
    """When ocr_fallback=True, sync() must pass a PDFParser(backend='auto')
    to library.ingest for .pdf files."""
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")

    captured: dict = {}

    def fake_ingest(self, path, corpus="default", parser=None, metadata=None):
        captured["parser"] = parser
        captured["suffix"] = path.suffix.lower()
        return {"chunks": 1, "chars": 100}

    monkeypatch.setattr(type(library), "ingest", fake_ingest)

    sync(
        library=library, root=tmp_path, corpus="t",
        extensions={".pdf"}, generate_embeddings=False,
        ocr_fallback=True,
    )

    assert captured["suffix"] == ".pdf"
    from rtfm.parsers.pdf import PDFParser
    assert isinstance(captured["parser"], PDFParser)
    assert captured["parser"].backend == "auto"


def test_sync_no_ocr_fallback_uses_registry_default(library, tmp_path, monkeypatch):
    """Without ocr_fallback, sync() must not pre-instantiate a parser
    (parser=None means library.ingest picks the registry default)."""
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")

    captured: dict = {}

    def fake_ingest(self, path, corpus="default", parser=None, metadata=None):
        captured["parser"] = parser
        return {"chunks": 1, "chars": 100}

    monkeypatch.setattr(type(library), "ingest", fake_ingest)

    sync(
        library=library, root=tmp_path, corpus="t",
        extensions={".pdf"}, generate_embeddings=False,
    )
    assert captured["parser"] is None


# ── Progress reporter ─────────────────────────────────────────────────────

def test_sync_emits_progress_callback_at_interval(library, tmp_path, monkeypatch):
    """With progress_interval set, sync() must fire 'progress' callbacks
    while iterating over many files."""
    # Create 5 files so we have iterations to observe
    for i in range(5):
        (tmp_path / f"f{i}.md").write_text(f"content {i}")

    def fake_ingest(self, path, corpus="default", parser=None, metadata=None):
        return {"chunks": 1, "chars": 10}

    monkeypatch.setattr(type(library), "ingest", fake_ingest)

    progress_events = []
    def cb(action, fp, detail):
        if action == "progress":
            progress_events.append(detail)

    # Tiny interval so every iteration triggers it.
    sync(
        library=library, root=tmp_path, corpus="t",
        extensions={".md"}, generate_embeddings=False,
        on_progress=cb, progress_interval=0.000001,
    )
    assert len(progress_events) >= 1
    assert "files" in progress_events[0]
