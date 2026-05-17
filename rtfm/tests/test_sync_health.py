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

from rtfm.core.sync import SyncResult, sync


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
