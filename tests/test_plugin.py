"""Tests for rtfm plugin: claude_md, install, mcp.json generation."""

import json
import pytest
from pathlib import Path

from rtfm.plugin.claude_md import inject_claude_md, RTFM_MARKER
from rtfm.plugin.install import generate_mcp_json, write_mcp_json, init_project


class TestInjectClaudeMd:
    """Tests for CLAUDE.md injection."""

    def test_create_new(self, tmp_path):
        """Creates CLAUDE.md if it doesn't exist."""
        result = inject_claude_md(tmp_path)

        assert result == "created"
        content = (tmp_path / "CLAUDE.md").read_text()
        assert RTFM_MARKER in content
        assert "rtfm_context" in content

    def test_append_to_existing(self, tmp_path):
        """Appends to existing CLAUDE.md."""
        (tmp_path / "CLAUDE.md").write_text("# My Project\n\nExisting content.\n")
        result = inject_claude_md(tmp_path)

        assert result == "appended"
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "# My Project" in content
        assert RTFM_MARKER in content

    def test_skip_if_present(self, tmp_path):
        """Skips if RTFM section already exists."""
        (tmp_path / "CLAUDE.md").write_text(f"# Project\n\n{RTFM_MARKER}\nAlready here.\n")
        result = inject_claude_md(tmp_path)

        assert result == "skipped"

    def test_idempotent(self, tmp_path):
        """Multiple calls don't duplicate the section."""
        inject_claude_md(tmp_path)
        inject_claude_md(tmp_path)

        content = (tmp_path / "CLAUDE.md").read_text()
        assert content.count(RTFM_MARKER) == 1


class TestMcpJson:
    """Tests for .mcp.json generation and merging."""

    def test_generate_mcp_json(self):
        """Generates correct structure."""
        config = generate_mcp_json(".rtfm/library.db")

        assert "mcpServers" in config
        assert "rtfm" in config["mcpServers"]
        server = config["mcpServers"]["rtfm"]
        assert server["args"] == ["-m", "rtfm.mcp"]
        assert server["env"]["RTFM_DB"] == ".rtfm/library.db"

    def test_create_new_mcp_json(self, tmp_path):
        """Creates .mcp.json if it doesn't exist."""
        result = write_mcp_json(tmp_path)

        assert result == "created"
        content = json.loads((tmp_path / ".mcp.json").read_text())
        assert "rtfm" in content["mcpServers"]

    def test_merge_existing_mcp_json(self, tmp_path):
        """Merges into existing .mcp.json without overwriting other servers."""
        existing = {
            "mcpServers": {
                "other-tool": {
                    "command": "other-cmd",
                    "args": [],
                }
            }
        }
        (tmp_path / ".mcp.json").write_text(json.dumps(existing))

        result = write_mcp_json(tmp_path)

        assert result == "merged"
        content = json.loads((tmp_path / ".mcp.json").read_text())
        assert "other-tool" in content["mcpServers"]
        assert "rtfm" in content["mcpServers"]

    def test_skip_if_rtfm_present(self, tmp_path):
        """Skips if rtfm server already registered."""
        existing = {
            "mcpServers": {
                "rtfm": {"command": "python", "args": ["-m", "rtfm.mcp"], "env": {}}
            }
        }
        (tmp_path / ".mcp.json").write_text(json.dumps(existing))

        result = write_mcp_json(tmp_path)

        assert result == "skipped"


class TestInitProject:
    """Tests for full init_project flow."""

    def test_init_creates_all_artifacts(self, tmp_path):
        """init_project creates DB, .mcp.json, and CLAUDE.md."""
        (tmp_path / "README.md").write_text("# Test Project\n\nSome content here.")

        summary = init_project(tmp_path, no_embeddings=True)

        # DB created
        assert (tmp_path / ".rtfm" / "library.db").exists()

        # .mcp.json created
        assert (tmp_path / ".mcp.json").exists()
        mcp_config = json.loads((tmp_path / ".mcp.json").read_text())
        assert "rtfm" in mcp_config["mcpServers"]

        # CLAUDE.md created
        assert (tmp_path / "CLAUDE.md").exists()
        assert RTFM_MARKER in (tmp_path / "CLAUDE.md").read_text()

        # Discover ran
        assert summary["discover"]["total_files"] >= 1

        # Entry points synced
        assert summary["sync"]["added"] >= 0

    def test_init_idempotent(self, tmp_path):
        """Running init twice doesn't duplicate artifacts."""
        (tmp_path / "README.md").write_text("# Test")

        init_project(tmp_path, no_embeddings=True)
        summary2 = init_project(tmp_path, no_embeddings=True)

        assert summary2["mcp_json"] == "skipped"
        assert summary2["claude_md"] == "skipped"

    def test_init_custom_db_path(self, tmp_path):
        """Custom DB path is respected."""
        summary = init_project(tmp_path, db_path="custom/my.db", no_embeddings=True)

        assert (tmp_path / "custom" / "my.db").exists()
        assert "custom/my.db" in summary["db_path"]
