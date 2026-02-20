"""Tests for rtfm.plugin.discover."""

import os
import pytest
from pathlib import Path

from rtfm.plugin.discover import discover, format_discover


class TestDiscover:
    """Tests for the project scanner."""

    def test_basic_scan(self, tmp_path):
        """Scan a simple project structure."""
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / "README.md").write_text("# Hello")
        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'")

        result = discover(tmp_path)

        assert result["total_files"] == 3
        assert result["total_size"] > 0
        assert "Python" in result["languages"]
        assert "code" in result["file_types"]
        assert "docs" in result["file_types"]

    def test_excludes_venv(self, tmp_path):
        """Hidden and venv directories are excluded by default."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("pass")
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "lib.py").write_text("pass")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "cache.pyc").write_bytes(b"\x00")

        result = discover(tmp_path)

        assert result["total_files"] == 1  # Only src/app.py

    def test_entry_points_detected(self, tmp_path):
        """Known entry points are detected at root level."""
        (tmp_path / "README.md").write_text("# Project")
        (tmp_path / "pyproject.toml").write_text("[project]")
        (tmp_path / "Makefile").write_text("all:")
        # Nested README should NOT be an entry point
        sub = tmp_path / "docs"
        sub.mkdir()
        (sub / "README.md").write_text("# Docs")

        result = discover(tmp_path)

        assert "README.md" in result["entry_points"]
        assert "pyproject.toml" in result["entry_points"]
        assert "Makefile" in result["entry_points"]
        assert result["total_files"] == 4

    def test_categories(self, tmp_path):
        """Extensions are mapped to the right categories."""
        (tmp_path / "app.py").write_text("pass")
        (tmp_path / "style.css").write_text("body {}")
        (tmp_path / "config.yaml").write_text("key: val")
        (tmp_path / "data.csv").write_text("a,b")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")

        result = discover(tmp_path)

        assert result["file_types"]["code"] == 1
        assert result["file_types"]["style"] == 1
        assert result["file_types"]["config"] == 1
        assert result["file_types"]["data"] == 1
        assert result["file_types"]["other"] == 1

    def test_empty_directory(self, tmp_path):
        """Empty dir returns zeros."""
        result = discover(tmp_path)

        assert result["total_files"] == 0
        assert result["total_size"] == 0
        assert result["languages"] == []
        assert result["entry_points"] == []

    def test_format_discover(self, tmp_path):
        """format_discover produces readable text."""
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / "README.md").write_text("# Hello")

        info = discover(tmp_path)
        text = format_discover(info)

        assert "Project:" in text
        assert "Files:" in text
        assert "Python" in text
