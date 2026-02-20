"""Tests for rtfm_context MCP tool."""

import os
import pytest
from pathlib import Path

from rtfm.core.library import Library


@pytest.fixture
def context_lib(tmp_path):
    """Library with some indexed content for context tests."""
    db_path = tmp_path / "test.db"
    lib = Library(db_path)

    # Create a markdown file
    md_file = tmp_path / "docs" / "architecture.md"
    md_file.parent.mkdir()
    md_file.write_text(
        "# Architecture\n\n"
        "The system uses a modular architecture with plugins.\n\n"
        "## Core Module\n\n"
        "The core module handles database operations and search.\n\n"
        "## Plugin System\n\n"
        "Plugins extend functionality through a registry pattern.\n"
    )

    lib.ingest(md_file, corpus="docs")
    yield lib, tmp_path, db_path
    lib.close()


class TestRtfmContext:
    """Tests for the rtfm_context tool logic."""

    def test_context_by_topic(self, context_lib):
        """Search by topic returns relevant chunks."""
        lib, tmp_path, db_path = context_lib

        results = lib.search("architecture modular", limit=5)

        assert len(results) > 0
        assert any("modular" in r.content.lower() or "architecture" in r.content.lower()
                    for r in results)

    def test_context_no_results(self, context_lib):
        """Search for non-existent topic returns empty."""
        lib, tmp_path, db_path = context_lib

        results = lib.search("xyznonexistent12345", limit=5)

        assert len(results) == 0

    def test_context_limit(self, context_lib):
        """Limit parameter is respected."""
        lib, tmp_path, db_path = context_lib

        results = lib.search("system", limit=1)

        assert len(results) <= 1
