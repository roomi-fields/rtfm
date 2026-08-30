"""Tests for dependency graph: edge extraction, resolution, queries."""

import pytest
import tempfile
from pathlib import Path

from rtfm import Library
from rtfm.core.models import EdgeCandidate
from rtfm.core.sync import sync, _sync_edges, _resolve_wikilink_to_relpath
from rtfm.parsers.python import PythonParser
from rtfm.parsers.markdown import MarkdownParser
from rtfm.parsers.latex import LaTeXParser


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def graph_db():
    """Temporary DB for graph tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    lib = Library(db_path)
    yield lib
    lib.close()
    db_path.unlink(missing_ok=True)


@pytest.fixture
def python_project(tmp_path):
    """Mini Python project with import relations."""
    (tmp_path / "main.py").write_text(
        "from utils import helper\n"
        "import config\n\n"
        "def main():\n    helper()\n"
    )
    (tmp_path / "utils.py").write_text(
        "import config\n\n"
        "def helper():\n    return config.VALUE\n"
    )
    (tmp_path / "config.py").write_text(
        "VALUE = 42\n\n"
        "def get_value():\n    return VALUE\n"
    )
    return tmp_path


@pytest.fixture
def markdown_project(tmp_path):
    """Mini Markdown project with link relations."""
    (tmp_path / "index.md").write_text(
        "# Welcome\n\n"
        "See [getting started](./guide.md) for more info.\n"
        "Also check [the API](api/reference.md).\n"
        "External link: [Google](https://google.com) should be ignored.\n"
        "Anchor only: [section](#section) should be ignored.\n"
        "Some more content to ensure the file is long enough for parsing.\n"
        "We need at least 100 chars of content for the parser to index it.\n"
    )
    (tmp_path / "guide.md").write_text(
        "# Getting Started\n\n"
        "Read the [index](./index.md) for overview.\n"
        "And check [[api/reference]] for API docs.\n"
        "Some more content to ensure the file is long enough for parsing.\n"
        "We need at least 100 chars of content for the parser to index it.\n"
    )
    api_dir = tmp_path / "api"
    api_dir.mkdir()
    (api_dir / "reference.md").write_text(
        "# API Reference\n\n"
        "Back to [guide](../guide.md).\n"
        "Some more content to ensure the file is long enough for parsing.\n"
        "We need at least 100 chars of content for the parser to index it.\n"
    )
    return tmp_path


@pytest.fixture
def latex_project(tmp_path):
    """Mini LaTeX project with include/cite relations."""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\input{intro}\n"
        "\\include{methods}\n"
        "See \\cite{smith2024} and \\citep{jones2023,doe2022}.\n"
        "Some content to make this a valid LaTeX document with enough text.\n"
        "\\end{document}\n"
    )
    (tmp_path / "intro.tex").write_text(
        "\\section{Introduction}\n"
        "This is the introduction with enough content to be parsed properly.\n"
        "We need more text here to meet the minimum chunk size requirement.\n"
    )
    (tmp_path / "methods.tex").write_text(
        "\\section{Methods}\n"
        "This is the methods section with enough content to be parsed properly.\n"
        "We need more text here to meet the minimum chunk size requirement.\n"
    )
    return tmp_path


# ── Edge extraction tests ────────────────────────────────────────────────

class TestPythonEdgeExtraction:
    def test_import_statement(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("import os\nimport sys\n")
        parser = PythonParser()
        edges = parser.extract_edges(f, {"source_file": "test.py"})
        assert len(edges) == 2
        assert all(e.relation_type == "import" for e in edges)
        refs = {e.target_ref for e in edges}
        assert "os" in refs
        assert "sys" in refs

    def test_from_import(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("from foo.bar import baz, qux\n")
        parser = PythonParser()
        edges = parser.extract_edges(f, {"source_file": "test.py"})
        assert len(edges) == 1
        assert edges[0].target_ref == "foo.bar"
        assert "baz, qux" in edges[0].source_detail

    def test_syntax_error_returns_empty(self, tmp_path):
        f = tmp_path / "broken.py"
        f.write_text("def foo(:\n  pass\n")
        parser = PythonParser()
        edges = parser.extract_edges(f, {"source_file": "broken.py"})
        assert edges == []


class TestMarkdownEdgeExtraction:
    def test_relative_links(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("See [guide](./guide.md) and [api](api/ref.md).\n")
        parser = MarkdownParser()
        edges = parser.extract_edges(f, {"source_file": "test.md"})
        assert len(edges) == 2
        refs = {e.target_ref for e in edges}
        assert "./guide.md" in refs
        assert "api/ref.md" in refs

    def test_http_links_ignored(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("[Google](https://google.com)\n[mailto](mailto:a@b.com)\n")
        parser = MarkdownParser()
        edges = parser.extract_edges(f, {"source_file": "test.md"})
        assert edges == []

    def test_anchor_only_ignored(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("[section](#foo)\n")
        parser = MarkdownParser()
        edges = parser.extract_edges(f, {"source_file": "test.md"})
        assert edges == []

    def test_wikilinks(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("See [[other-doc]] and [[path/to/doc|Display Name]].\n")
        parser = MarkdownParser()
        edges = parser.extract_edges(f, {"source_file": "test.md"})
        assert len(edges) == 2
        refs = {e.target_ref for e in edges}
        assert "other-doc" in refs
        assert "path/to/doc" in refs


class TestLatexEdgeExtraction:
    def test_input_include(self, tmp_path):
        f = tmp_path / "main.tex"
        f.write_text("\\input{intro}\n\\include{methods}\n")
        parser = LaTeXParser()
        edges = parser.extract_edges(f, {"source_file": "main.tex"})
        assert len(edges) == 2
        assert all(e.relation_type == "include" for e in edges)
        refs = {e.target_ref for e in edges}
        assert "intro" in refs
        assert "methods" in refs

    def test_cite_commands(self, tmp_path):
        f = tmp_path / "main.tex"
        f.write_text("\\cite{smith2024}\n\\citep{jones2023,doe2022}\n")
        parser = LaTeXParser()
        edges = parser.extract_edges(f, {"source_file": "main.tex"})
        assert len(edges) == 3
        assert all(e.relation_type == "cite" for e in edges)
        refs = {e.target_ref for e in edges}
        assert "smith2024" in refs
        assert "jones2023" in refs
        assert "doe2022" in refs


# ── Sync integration tests ───────────────────────────────────────────────

class TestSyncEdges:
    def test_python_edges_created(self, graph_db, python_project):
        result = sync(graph_db, python_project, corpus="test",
                      generate_embeddings=False)
        assert result.added == 3

        # Check edges were created
        stats = graph_db.get_graph_stats()
        assert stats["total_edges"] > 0
        assert "import" in stats["relation_types"]

    def test_python_import_resolution(self, graph_db, python_project):
        sync(graph_db, python_project, corpus="test",
             generate_embeddings=False)

        # main.py imports utils and config
        neighbors = graph_db.get_neighbors("test--main-py", direction="outgoing")
        target_filenames = {n["filename"] for n in neighbors}
        assert "utils.py" in target_filenames
        assert "config.py" in target_filenames

    def test_config_has_incoming_edges(self, graph_db, python_project):
        sync(graph_db, python_project, corpus="test",
             generate_embeddings=False)

        # config.py is imported by both main.py and utils.py
        neighbors = graph_db.get_neighbors("test--config-py", direction="incoming")
        assert len(neighbors) == 2

    def test_markdown_edges_created(self, graph_db, markdown_project):
        sync(graph_db, markdown_project, corpus="test",
             generate_embeddings=False)

        stats = graph_db.get_graph_stats()
        assert stats["total_edges"] > 0
        assert "link" in stats["relation_types"]

    def test_edges_cleaned_on_resync(self, graph_db, python_project):
        sync(graph_db, python_project, corpus="test",
             generate_embeddings=False)
        stats1 = graph_db.get_graph_stats()

        # Modify main.py to remove one import
        (python_project / "main.py").write_text(
            "import config\n\n"
            "def main():\n    pass\n"
        )
        sync(graph_db, python_project, corpus="test",
             generate_embeddings=False)
        stats2 = graph_db.get_graph_stats()

        # Should have fewer edges now
        assert stats2["total_edges"] < stats1["total_edges"]

    def test_edges_cleaned_on_delete(self, graph_db, python_project):
        sync(graph_db, python_project, corpus="test",
             generate_embeddings=False)

        # Delete config.py → edges referencing it should be removed
        graph_db.delete_book("test--config-py")

        neighbors = graph_db.get_neighbors("test--main-py", direction="outgoing")
        target_slugs = {n["slug"] for n in neighbors}
        assert "test--config-py" not in target_slugs


# ── Library graph method tests ───────────────────────────────────────────

class TestLibraryGraphMethods:
    def test_get_neighbors_empty(self, graph_db):
        assert graph_db.get_neighbors("nonexistent") == []

    def test_get_neighbors_direction_filter(self, graph_db, python_project):
        sync(graph_db, python_project, corpus="test",
             generate_embeddings=False)

        outgoing = graph_db.get_neighbors("test--main-py", direction="outgoing")
        incoming = graph_db.get_neighbors("test--main-py", direction="incoming")
        both = graph_db.get_neighbors("test--main-py", direction="both")

        assert len(outgoing) > 0
        assert all(n["direction"] == "outgoing" for n in outgoing)
        # main.py is not imported by anyone
        assert len(incoming) == 0
        assert len(both) == len(outgoing) + len(incoming)

    def test_get_in_degree(self, graph_db, python_project):
        sync(graph_db, python_project, corpus="test",
             generate_embeddings=False)

        degrees = graph_db.get_in_degree()
        assert len(degrees) > 0

        # config.py should have the highest in-degree (imported by main + utils)
        config_row = graph_db._get_conn().execute(
            "SELECT id FROM books WHERE slug = ?", ("test--config-py",)
        ).fetchone()
        assert config_row
        assert degrees.get(config_row["id"], 0) == 2

    def test_get_graph_stats(self, graph_db, python_project):
        sync(graph_db, python_project, corpus="test",
             generate_embeddings=False)

        stats = graph_db.get_graph_stats()
        assert stats["total_edges"] > 0
        assert stats["books_with_edges"] > 0
        assert "import" in stats["relation_types"]

    def test_get_graph_stats_empty(self, graph_db):
        stats = graph_db.get_graph_stats()
        assert stats["total_edges"] == 0
        assert stats["books_with_edges"] == 0
        assert stats["relation_types"] == {}


class TestEdgeCandidate:
    def test_dataclass(self):
        edge = EdgeCandidate(
            source_file="main.py",
            target_ref="utils",
            relation_type="import",
            source_detail="import utils",
        )
        assert edge.source_file == "main.py"
        assert edge.target_ref == "utils"
        assert edge.relation_type == "import"
        assert edge.source_detail == "import utils"

    def test_default_source_detail(self):
        edge = EdgeCandidate(
            source_file="main.py",
            target_ref="utils",
            relation_type="import",
        )
        assert edge.source_detail == ""


# ── Wikilink Resolution ─────────────────────────────────────────────────

class TestWikilinkResolution:
    """Tests for _resolve_wikilink_to_relpath."""

    def _files(self, *paths):
        """Build a {rel_path: fake_book_id} dict."""
        return {p: i + 1 for i, p in enumerate(paths)}

    def test_exact_basename(self, tmp_path):
        files = self._files("guide.md", "api/reference.md")
        result = _resolve_wikilink_to_relpath("guide", "index.md", tmp_path, files)
        assert result == "guide.md"

    def test_case_insensitive(self, tmp_path):
        files = self._files("Guide.md", "api/reference.md")
        result = _resolve_wikilink_to_relpath("guide", "index.md", tmp_path, files)
        assert result == "Guide.md"

    def test_with_md_extension(self, tmp_path):
        files = self._files("guide.md")
        result = _resolve_wikilink_to_relpath("guide.md", "index.md", tmp_path, files)
        assert result == "guide.md"

    def test_with_anchor(self, tmp_path):
        files = self._files("guide.md")
        result = _resolve_wikilink_to_relpath("guide#section", "index.md", tmp_path, files)
        assert result == "guide.md"

    def test_path_suffix(self, tmp_path):
        files = self._files("docs/api/reference.md", "other.md")
        result = _resolve_wikilink_to_relpath("api/reference", "index.md", tmp_path, files)
        assert result == "docs/api/reference.md"

    def test_ambiguous_prefers_nearest(self, tmp_path):
        files = self._files("a/notes.md", "b/sub/notes.md")
        # Source is in "a/" → "a/notes.md" is closer
        result = _resolve_wikilink_to_relpath("notes", "a/index.md", tmp_path, files)
        assert result == "a/notes.md"

    def test_ambiguous_prefers_nearest_reverse(self, tmp_path):
        files = self._files("a/notes.md", "b/sub/notes.md")
        # Source is in "b/sub/" → "b/sub/notes.md" is closer
        result = _resolve_wikilink_to_relpath("notes", "b/sub/index.md", tmp_path, files)
        assert result == "b/sub/notes.md"

    def test_unresolved_returns_none(self, tmp_path):
        files = self._files("guide.md")
        result = _resolve_wikilink_to_relpath("nonexistent", "index.md", tmp_path, files)
        assert result is None

    def test_anchor_only_returns_none(self, tmp_path):
        files = self._files("guide.md")
        result = _resolve_wikilink_to_relpath("#section", "index.md", tmp_path, files)
        assert result is None

    def test_empty_returns_none(self, tmp_path):
        files = self._files("guide.md")
        result = _resolve_wikilink_to_relpath("", "index.md", tmp_path, files)
        assert result is None


class TestWikilinkSyncIntegration:
    """Test that wikilinks produce resolved edges during sync."""

    def test_wikilink_edges_resolved(self, graph_db, tmp_path):
        """Wikilinks in markdown should produce edges with resolved book_ids."""
        (tmp_path / "index.md").write_text(
            "# Index\n\n"
            "Check [[guide]] for getting started.\n"
            "Also see [[api/reference]] for the API.\n"
            "Enough content to pass minimum chunk size for indexing.\n"
            "We need at least 100 chars of content for the parser.\n"
        )
        (tmp_path / "guide.md").write_text(
            "# Guide\n\n"
            "Back to [[index]] for overview.\n"
            "Enough content to pass minimum chunk size for indexing.\n"
            "We need at least 100 chars of content for the parser.\n"
        )
        api_dir = tmp_path / "api"
        api_dir.mkdir()
        (api_dir / "reference.md").write_text(
            "# API Reference\n\n"
            "See [[guide]] for getting started.\n"
            "Enough content to pass minimum chunk size for indexing.\n"
            "We need at least 100 chars of content for the parser.\n"
        )

        sync(graph_db, tmp_path, corpus="test", generate_embeddings=False)

        # Check edges exist
        stats = graph_db.get_graph_stats()
        assert stats["total_edges"] > 0, "Wikilinks should produce edges"

        # index.md links to guide.md → outgoing edge
        neighbors = graph_db.get_neighbors("test--index-md", direction="outgoing")
        neighbor_files = [n["filename"] for n in neighbors]
        assert "guide.md" in neighbor_files, f"Expected guide.md in {neighbor_files}"

        # guide.md links back to index.md → index has incoming
        incoming = graph_db.get_neighbors("test--index-md", direction="incoming")
        incoming_files = [n["filename"] for n in incoming]
        assert "guide.md" in incoming_files, f"Expected guide.md in {incoming_files}"
