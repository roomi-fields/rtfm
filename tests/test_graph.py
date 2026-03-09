"""Tests for dependency graph: edge extraction, resolution, queries."""

import pytest
import tempfile
from pathlib import Path

from rtfm import Library
from rtfm.core.models import EdgeCandidate
from rtfm.core.sync import sync, _sync_edges
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
        neighbors = graph_db.get_neighbors("test--main", direction="outgoing")
        target_filenames = {n["filename"] for n in neighbors}
        assert "utils.py" in target_filenames
        assert "config.py" in target_filenames

    def test_config_has_incoming_edges(self, graph_db, python_project):
        sync(graph_db, python_project, corpus="test",
             generate_embeddings=False)

        # config.py is imported by both main.py and utils.py
        neighbors = graph_db.get_neighbors("test--config", direction="incoming")
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
        graph_db.delete_book("test--config")

        neighbors = graph_db.get_neighbors("test--main", direction="outgoing")
        target_slugs = {n["slug"] for n in neighbors}
        assert "test--config" not in target_slugs


# ── Library graph method tests ───────────────────────────────────────────

class TestLibraryGraphMethods:
    def test_get_neighbors_empty(self, graph_db):
        assert graph_db.get_neighbors("nonexistent") == []

    def test_get_neighbors_direction_filter(self, graph_db, python_project):
        sync(graph_db, python_project, corpus="test",
             generate_embeddings=False)

        outgoing = graph_db.get_neighbors("test--main", direction="outgoing")
        incoming = graph_db.get_neighbors("test--main", direction="incoming")
        both = graph_db.get_neighbors("test--main", direction="both")

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
            "SELECT id FROM books WHERE slug = ?", ("test--config",)
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
