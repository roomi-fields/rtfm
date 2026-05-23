"""Tests for CLI ergonomics — auto-detect, add, sources, serve, sync without args."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from rtfm.config import add_source, save_config


@pytest.fixture
def rtfm_project(tmp_path):
    """Create a minimal .rtfm/ project with a real library DB."""
    from rtfm.core.library import Library

    rtfm_dir = tmp_path / ".rtfm"
    rtfm_dir.mkdir()
    db_path = rtfm_dir / "library.db"
    lib = Library(str(db_path))
    lib.close()
    return tmp_path


class TestSyncWithoutArgs:
    def test_sync_all_sources_from_config(self, rtfm_project, monkeypatch):
        """rtfm sync --background should enqueue P0 scan jobs for every source."""
        # Create two source directories with files
        docs_dir = rtfm_project / "docs"
        docs_dir.mkdir()
        (docs_dir / "readme.md").write_text("# Docs\nHello world")

        code_dir = rtfm_project / "code"
        code_dir.mkdir()
        (code_dir / "main.py").write_text("def main(): pass")

        # Register sources
        add_source(rtfm_project, str(docs_dir), "docs", extensions=".md")
        add_source(rtfm_project, str(code_dir), "code", extensions=".py")

        monkeypatch.chdir(rtfm_project)
        monkeypatch.delenv("RTFM_DB", raising=False)

        from rtfm.cli import main
        # --background avoids spawning a real worker subprocess and avoids
        # blocking on the watcher poll loop.
        with patch("rtfm.cli_worker.ensure_worker_running", return_value=12345), \
             patch("sys.argv", ["rtfm", "sync", "--background"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

        # Verify scan jobs were enqueued at P0.
        from rtfm.core.queue import Queue, P_USER
        q = Queue(str(rtfm_project / ".rtfm" / "library.db"))
        jobs = q.list_pending(limit=20)
        scans = [j for j in jobs if j.type == "scan"]
        assert len(scans) == 2, f"expected 2 scan jobs, got {len(scans)}"
        assert all(j.priority == P_USER for j in scans)
        q.close()

    def test_sync_explicit_overrides_config(self, rtfm_project, monkeypatch):
        """rtfm sync /path --corpus x --background enqueues a scan for that source."""
        src_dir = rtfm_project / "src"
        src_dir.mkdir()
        (src_dir / "test.md").write_text("# Test\n\nThis is a test document with enough content to create a chunk.")

        monkeypatch.chdir(rtfm_project)
        monkeypatch.delenv("RTFM_DB", raising=False)

        from rtfm.cli import main
        with patch("rtfm.cli_worker.ensure_worker_running", return_value=12345), \
             patch("sys.argv", ["rtfm", "sync", str(src_dir), "--corpus", "explicit",
                                "--background"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

        from rtfm.core.queue import Queue
        q = Queue(str(rtfm_project / ".rtfm" / "library.db"))
        jobs = q.list_pending(limit=20)
        assert any(j.type == "scan" and j.payload.get("corpus") == "explicit"
                   for j in jobs)
        q.close()


class TestAddAndSources:
    def test_add_then_list(self, rtfm_project, monkeypatch, capsys):
        """rtfm add + rtfm sources should work together."""
        monkeypatch.chdir(rtfm_project)
        monkeypatch.delenv("RTFM_DB", raising=False)

        from rtfm.cli import main

        # Add a source
        with patch("sys.argv", ["rtfm", "add", str(rtfm_project / "docs"), "--corpus", "docs"]):
            main()

        captured = capsys.readouterr()
        assert "Added source" in captured.out

        # List sources
        with patch("sys.argv", ["rtfm", "sources"]):
            main()

        captured = capsys.readouterr()
        assert "[docs]" in captured.out


class TestServe:
    def test_serve_sets_env(self, rtfm_project, monkeypatch):
        """rtfm serve should set RTFM_DB and call mcp main."""
        monkeypatch.chdir(rtfm_project)
        monkeypatch.delenv("RTFM_DB", raising=False)

        mock_mcp_main = MagicMock()
        with patch("rtfm.mcp.main", mock_mcp_main):
            from rtfm.cli import main
            with patch("sys.argv", ["rtfm", "serve"]):
                main()

        assert os.environ.get("RTFM_DB") == str(rtfm_project / ".rtfm" / "library.db")
        mock_mcp_main.assert_called_once()


class TestSearchAutoDb:
    def test_search_without_db_flag(self, rtfm_project, monkeypatch, capsys):
        """rtfm search should auto-detect .rtfm/library.db."""
        monkeypatch.chdir(rtfm_project)
        monkeypatch.delenv("RTFM_DB", raising=False)

        from rtfm.cli import main
        with patch("sys.argv", ["rtfm", "search", "test"]):
            main()

        # Should not crash — just find 0 results in empty DB
        captured = capsys.readouterr()
        # No error means auto-detect worked
        assert "error" not in captured.out.lower() or captured.out == ""
