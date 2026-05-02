"""Tests for Obsidian vault integration."""

import json
import tempfile
import pytest
from pathlib import Path

from rtfm import Library
from rtfm.plugin.vault import detect_obsidian_vault, propose_corpus_mapping, init_vault
from rtfm.plugin.vault_output import (
    generate_vault_output,
    _vault_path_to_wikilink,
    update_recent_page,
)
from rtfm.plugin.claude_md import inject_claude_md


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def vault(tmp_path):
    """Create a minimal Obsidian vault structure."""
    (tmp_path / ".obsidian").mkdir()

    # Root-level notes
    for i in range(3):
        (tmp_path / f"note_{i}.md").write_text(
            f"# Note {i}\n\nSome content for note {i}. " * 5
        )

    # Folder with enough files for corpus
    research = tmp_path / "Research"
    research.mkdir()
    for i in range(8):
        (research / f"paper_{i}.md").write_text(
            f"# Paper {i}\n\nResearch content for paper {i}. "
            f"This references [[paper_{(i+1) % 8}]] and [[note_0]]. " * 3
        )

    # Folder with too few files (should not become corpus)
    archive = tmp_path / "Archive"
    archive.mkdir()
    (archive / "old.md").write_text("# Old note\n\nArchived. " * 5)

    # Excluded folder
    templates = tmp_path / "Templates"
    templates.mkdir()
    for i in range(10):
        (templates / f"tpl_{i}.md").write_text(f"# Template {i}\n\nTemplate content. " * 5)

    return tmp_path


@pytest.fixture
def vault_db():
    """Temporary DB for vault tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    lib = Library(db_path)
    yield lib
    lib.close()
    db_path.unlink(missing_ok=True)


# ── Detection ────────────────────────────────────────────────────────────

class TestDetectObsidianVault:

    def test_detects_vault(self, vault):
        result = detect_obsidian_vault(vault)
        assert result is not None
        assert result["root"] == vault.resolve()

    def test_not_a_vault(self, tmp_path):
        result = detect_obsidian_vault(tmp_path)
        assert result is None


# ── Corpus Mapping ───────────────────────────────────────────────────────

class TestCorpusMapping:

    def test_proposes_corpora(self, vault):
        mapping = propose_corpus_mapping(vault)
        corpus_names = [m["corpus"] for m in mapping]
        assert "research" in corpus_names
        # Root notes present
        assert "root" in corpus_names

    def test_excludes_small_folders(self, vault):
        mapping = propose_corpus_mapping(vault)
        corpus_names = [m["corpus"] for m in mapping]
        assert "archive" not in corpus_names

    def test_excludes_templates(self, vault):
        mapping = propose_corpus_mapping(vault)
        corpus_names = [m["corpus"] for m in mapping]
        assert "templates" not in corpus_names

    def test_file_counts(self, vault):
        mapping = propose_corpus_mapping(vault)
        research = next(m for m in mapping if m["corpus"] == "research")
        assert research["file_count"] == 8


# ── Init Vault ───────────────────────────────────────────────────────────

class TestInitVault:

    def test_creates_rtfm_dir(self, vault):
        init_vault(vault, no_embeddings=True, generate_output=False)
        assert (vault / ".rtfm" / "library.db").exists()
        assert (vault / ".rtfm" / "config.json").exists()

    def test_sets_vault_type(self, vault):
        init_vault(vault, no_embeddings=True, generate_output=False)
        config = json.loads((vault / ".rtfm" / "config.json").read_text())
        assert config.get("vault_type") == "obsidian"

    def test_creates_mcp_json(self, vault):
        init_vault(vault, no_embeddings=True, generate_output=False)
        assert (vault / ".mcp.json").exists()
        mcp = json.loads((vault / ".mcp.json").read_text())
        assert "rtfm" in mcp.get("mcpServers", {})

    def test_injects_claude_md(self, vault):
        init_vault(vault, no_embeddings=True, generate_output=False)
        claude_md = (vault / "CLAUDE.md").read_text()
        assert "[[_rtfm/index]]" in claude_md  # Vault mode uses wikilinks

    def test_syncs_files(self, vault):
        summary = init_vault(vault, no_embeddings=True, generate_output=False)
        sync_info = summary.get("sync", {})
        # At least the research corpus should have synced files
        assert any(info.get("added", 0) > 0 for info in sync_info.values())

    def test_generates_output(self, vault):
        init_vault(vault, no_embeddings=True, generate_output=True)
        assert (vault / "_rtfm" / "index.md").exists()
        assert (vault / "_rtfm" / "graph.md").exists()
        assert (vault / "_rtfm" / "recent.md").exists()

    def test_not_a_vault_returns_error(self, tmp_path):
        summary = init_vault(tmp_path, no_embeddings=True)
        assert "error" in summary


# ── Vault Output ─────────────────────────────────────────────────────────

class TestVaultOutput:

    def test_wikilink_conversion(self):
        assert _vault_path_to_wikilink("notes/My Note.md") == "[[notes/My Note]]"
        assert _vault_path_to_wikilink("guide.md") == "[[guide]]"
        assert _vault_path_to_wikilink("data.json") == "[[data.json]]"

    def test_index_contains_corpora(self, vault):
        init_vault(vault, no_embeddings=True, generate_output=True)
        index = (vault / "_rtfm" / "index.md").read_text()
        assert "## Corpora" in index
        assert "research" in index

    def test_index_has_frontmatter(self, vault):
        init_vault(vault, no_embeddings=True, generate_output=True)
        index = (vault / "_rtfm" / "index.md").read_text()
        assert index.startswith("---")
        assert "tags:" in index
        assert "rtfm/index" in index

    def test_graph_has_mermaid(self, vault):
        init_vault(vault, no_embeddings=True, generate_output=True)
        graph = (vault / "_rtfm" / "graph.md").read_text()
        assert "Knowledge Graph" in graph

    def test_corpus_page_created(self, vault):
        init_vault(vault, no_embeddings=True, generate_output=True)
        assert (vault / "_rtfm" / "corpus" / "research.md").exists()
        content = (vault / "_rtfm" / "corpus" / "research.md").read_text()
        assert "Corpus: research" in content

    def test_recent_page(self, vault):
        init_vault(vault, no_embeddings=True, generate_output=True)
        recent = (vault / "_rtfm" / "recent.md").read_text()
        assert "Recently Modified" in recent


# ── CLAUDE.md Vault Mode ────────────────────────────────────────────────

class TestClaudeMdVaultMode:

    def test_vault_mode_uses_wikilinks(self, tmp_path):
        result = inject_claude_md(tmp_path, vault_mode=True)
        assert result == "created"
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "[[_rtfm/index]]" in content
        assert "[[_rtfm/graph]]" in content

    def test_normal_mode_no_wikilinks(self, tmp_path):
        result = inject_claude_md(tmp_path, vault_mode=False)
        assert result == "created"
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "[[" not in content
