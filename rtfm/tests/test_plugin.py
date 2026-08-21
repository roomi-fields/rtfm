"""Tests for rtfm plugin: claude_md, install, mcp.json generation."""

import json
import pytest
from pathlib import Path

from rtfm.plugin.claude_md import inject_claude_md, RTFM_MARKER
from rtfm.plugin.install import generate_mcp_json, write_mcp_json, init_project
from rtfm.plugin.hooks import install_hook


class TestInstallHook:
    """The hooks must stay lightweight: revive the worker on prompt/stop,
    enqueue a single file on edit. They must NOT run a full sync (that
    re-MD5s the corpus and can mass-delete on an incomplete scan)."""

    def test_registers_three_hooks(self, tmp_path):
        install_hook(tmp_path, corpus="t")
        settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
        hooks = settings["hooks"]
        assert "UserPromptSubmit" in hooks
        assert "Stop" in hooks
        assert "PostToolUse" in hooks

        # PostToolUse must target file-edit tools only.
        ptu = hooks["PostToolUse"]
        assert any(e.get("matcher") == "Write|Edit|MultiEdit" for e in ptu)

        # All three scripts written.
        hooks_dir = tmp_path / ".claude" / "hooks"
        assert (hooks_dir / "rtfm_sync.py").exists()
        assert (hooks_dir / "rtfm_stop_sync.py").exists()
        assert (hooks_dir / "rtfm_posttool_sync.py").exists()

    def test_prompt_hook_delegates_and_does_not_full_sync(self, tmp_path):
        install_hook(tmp_path, corpus="t")
        script = (tmp_path / ".claude" / "hooks" / "rtfm_sync.py").read_text()
        # Heartbeat only — delegates to the installed package and must NOT
        # import/run the heavy sync().
        assert "hook_runtime import heartbeat" in script
        assert "from rtfm.core.sync import sync" not in script

    def test_posttool_hook_delegates_and_does_not_full_sync(self, tmp_path):
        install_hook(tmp_path, corpus="t")
        script = (tmp_path / ".claude" / "hooks" / "rtfm_posttool_sync.py").read_text()
        assert "hook_runtime import on_file_edited" in script
        assert "from rtfm.core.sync import sync" not in script

    def test_stubs_carry_no_logic(self, tmp_path):
        """The logic must live in the package, not in the copied script —
        otherwise a project keeps running the version it was created with."""
        install_hook(tmp_path, corpus="t")
        for name in ("rtfm_sync.py", "rtfm_stop_sync.py", "rtfm_posttool_sync.py"):
            script = (tmp_path / ".claude" / "hooks" / name).read_text()
            assert len(script.splitlines()) < 25, f"{name} is not a stub"

    def test_refresh_rewrites_outdated_stub(self, tmp_path):
        from rtfm.plugin.hooks import refresh_hook_scripts

        install_hook(tmp_path, corpus="t")
        stub = tmp_path / ".claude" / "hooks" / "rtfm_posttool_sync.py"
        stub.write_text("# stale content from an older RTFM\n")

        updated = refresh_hook_scripts(tmp_path)
        assert "rtfm_posttool_sync.py" in updated
        assert "hook_runtime import on_file_edited" in stub.read_text()

        # Already current → nothing rewritten (no churn on every prompt).
        assert refresh_hook_scripts(tmp_path) == []

    def test_refresh_does_not_install_missing_hooks(self, tmp_path):
        """Refresh heals what init installed; deciding to install is init's."""
        from rtfm.plugin.hooks import refresh_hook_scripts

        (tmp_path / ".claude" / "hooks").mkdir(parents=True)
        assert refresh_hook_scripts(tmp_path) == []
        assert not (tmp_path / ".claude" / "hooks" / "rtfm_sync.py").exists()

    def test_idempotent_no_duplicate_hooks(self, tmp_path):
        install_hook(tmp_path, corpus="t")
        install_hook(tmp_path, corpus="t")
        settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
        for evt in ("UserPromptSubmit", "Stop", "PostToolUse"):
            rtfm_entries = [
                e for e in settings["hooks"][evt]
                if any("rtfm" in h.get("command", "") for h in e.get("hooks", []))
            ]
            assert len(rtfm_entries) == 1, f"{evt} duplicated"


class TestInjectClaudeMd:
    """Tests for CLAUDE.md injection."""

    def test_create_new(self, tmp_path):
        """Creates CLAUDE.md if it doesn't exist."""
        result = inject_claude_md(tmp_path)

        assert result == "created"
        content = (tmp_path / "CLAUDE.md").read_text()
        assert RTFM_MARKER in content
        assert "rtfm_search" in content

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

    def test_init_enables_mcp_in_settings(self, tmp_path):
        """init_project adds rtfm to enabledMcpjsonServers."""
        (tmp_path / "README.md").write_text("# Test")
        # Pre-existing settings with another server
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.local.json").write_text(json.dumps({
            "enabledMcpjsonServers": ["other-tool"],
            "permissions": {},
        }))

        summary = init_project(tmp_path, no_embeddings=True)

        assert summary["claude_settings"] == "enabled"
        settings = json.loads((claude_dir / "settings.local.json").read_text())
        assert "rtfm" in settings["enabledMcpjsonServers"]
        assert "other-tool" in settings["enabledMcpjsonServers"]

    def test_init_enables_mcp_no_settings(self, tmp_path):
        """init_project handles missing .claude/ gracefully."""
        (tmp_path / "README.md").write_text("# Test")

        summary = init_project(tmp_path, no_embeddings=True)

        assert summary["claude_settings"] == "no settings"

    def test_init_custom_db_path(self, tmp_path):
        """Custom DB path is respected."""
        summary = init_project(tmp_path, db_path="custom/my.db", no_embeddings=True)

        assert (tmp_path / "custom" / "my.db").exists()
        assert "custom/my.db" in summary["db_path"]
