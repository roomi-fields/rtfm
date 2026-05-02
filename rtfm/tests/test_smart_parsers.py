"""Tests for the smart parsers: Python, LaTeX, YAML, JSON, Shell."""

import json
import pytest
from pathlib import Path

from rtfm.parsers.python import PythonParser, _extract_blocks
from rtfm.parsers.latex import LaTeXParser, _split_sections
from rtfm.parsers.yaml_parser import YAMLParser, _split_top_level_keys
from rtfm.parsers.json_parser import JSONParser
from rtfm.parsers.shell import ShellParser, _extract_blocks as _extract_shell_blocks
from rtfm.parsers.base import ParserRegistry


# ── PythonParser ─────────────────────────────────────────────────────────

class TestPythonParser:
    def test_chunks_by_function(self, tmp_path):
        f = tmp_path / "example.py"
        f.write_text(
            "import os\nimport sys\n\n"
            "def hello():\n    '''Say hello.'''\n    print('hello world')\n\n"
            "def goodbye():\n    '''Say goodbye.'''\n    print('goodbye world')\n\n"
            "class Greeter:\n    def greet(self):\n        return 'hi'\n"
        )
        parser = PythonParser()
        chunks = list(parser.parse(f))

        labels = [c.chapter_title for c in chunks]
        assert any("def hello" in l for l in labels)
        assert any("def goodbye" in l for l in labels)
        assert any("class Greeter" in l for l in labels)

    def test_module_level_code(self, tmp_path):
        f = tmp_path / "constants.py"
        f.write_text(
            "# Configuration constants\n"
            "MAX_RETRIES = 3\n"
            "TIMEOUT = 30\n"
            "BASE_URL = 'https://example.com'\n"
            "DEBUG = False\n"
        )
        parser = PythonParser()
        chunks = list(parser.parse(f))
        assert len(chunks) >= 1
        labels = [c.chapter_title for c in chunks]
        assert any("module" in l for l in labels)

    def test_syntax_error_fallback(self, tmp_path):
        f = tmp_path / "broken.py"
        f.write_text(
            "def this is broken\n"
            "    not valid python at all\n"
            "    but should still be indexed\n"
        )
        parser = PythonParser()
        chunks = list(parser.parse(f))
        assert len(chunks) >= 1  # fallback to single block

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        parser = PythonParser()
        chunks = list(parser.parse(f))
        assert chunks == []

    def test_can_parse(self):
        parser = PythonParser()
        assert parser.can_parse(Path("test.py"))
        assert not parser.can_parse(Path("test.js"))

    def test_extract_blocks_preserves_functions(self):
        source = (
            "import os\n\n"
            "def foo():\n    return 1\n\n"
            "def bar():\n    return 2\n"
        )
        blocks = _extract_blocks(source)
        labels = [b["label"] for b in blocks]
        assert "def foo" in labels
        assert "def bar" in labels


# ── LaTeXParser ──────────────────────────────────────────────────────────

class TestLaTeXParser:
    def test_chunks_by_section(self, tmp_path):
        f = tmp_path / "thesis.tex"
        f.write_text(
            "\\documentclass{article}\n"
            "\\title{My Thesis}\n"
            "\\begin{document}\n\n"
            "\\section{Introduction}\n"
            "This is the introduction to my thesis. "
            "It covers the fundamental concepts and sets the stage for the research. "
            "The introduction provides context and motivation for the study.\n\n"
            "\\section{Methods}\n"
            "We used a combination of quantitative and qualitative methods. "
            "Data was collected through surveys and interviews. "
            "The analysis followed a mixed-methods approach with statistical testing.\n\n"
            "\\section{Results}\n"
            "The results show a significant correlation between variables. "
            "Statistical analysis confirms the hypothesis with p < 0.05. "
            "Further details are provided in the supplementary materials.\n\n"
            "\\end{document}\n"
        )
        parser = LaTeXParser()
        chunks = list(parser.parse(f))

        titles = [c.chapter_title for c in chunks]
        assert any("Introduction" in t for t in titles)
        assert any("Methods" in t for t in titles)
        assert any("Results" in t for t in titles)

    def test_extracts_title(self, tmp_path):
        f = tmp_path / "doc.tex"
        f.write_text(
            "\\title{Grammaires de Performance}\n"
            "\\section{Premier chapitre}\n"
            "Contenu du premier chapitre qui est assez long pour dépasser le minimum "
            "requis de caractères et former un chunk valide dans le système.\n"
        )
        parser = LaTeXParser()
        chunks = list(parser.parse(f))
        assert chunks[0].book_title == "Grammaires de Performance"

    def test_strip_comments(self, tmp_path):
        f = tmp_path / "commented.tex"
        f.write_text(
            "\\section{Real Content}\n"
            "This is real content. % this is a comment\n"
            "More content here that should be preserved for indexing purposes. "
            "We need enough text to meet the minimum chunk size requirement.\n"
        )
        parser = LaTeXParser()
        chunks = list(parser.parse(f))
        assert len(chunks) >= 1
        # Comment should be stripped
        for c in chunks:
            assert "this is a comment" not in c.content

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.tex"
        f.write_text("")
        parser = LaTeXParser()
        assert list(parser.parse(f)) == []

    def test_can_parse(self):
        parser = LaTeXParser()
        assert parser.can_parse(Path("thesis.tex"))
        assert parser.can_parse(Path("doc.latex"))
        assert not parser.can_parse(Path("doc.txt"))

    def test_subsection_and_chapter(self, tmp_path):
        f = tmp_path / "book.tex"
        f.write_text(
            "\\chapter{First Chapter}\n"
            "Chapter content that is long enough to be a valid chunk for indexing. "
            "We need several sentences here to ensure the text passes the minimum.\n\n"
            "\\subsection{Details}\n"
            "Detailed subsection content with enough text to also be indexed as its own chunk. "
            "This should be a separate chunk from the chapter.\n"
        )
        parser = LaTeXParser()
        chunks = list(parser.parse(f))
        titles = [c.chapter_title for c in chunks]
        assert any("First Chapter" in t for t in titles)
        assert any("Details" in t for t in titles)


# ── YAMLParser ───────────────────────────────────────────────────────────

class TestYAMLParser:
    def test_chunks_by_key(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text(
            "database:\n"
            "  host: localhost\n"
            "  port: 5432\n"
            "  name: mydb\n"
            "  pool_size: 10\n"
            "  timeout: 30\n\n"
            "server:\n"
            "  host: 0.0.0.0\n"
            "  port: 8080\n"
            "  workers: 4\n"
            "  debug: false\n"
            "  log_level: info\n\n"
            "redis:\n"
            "  host: localhost\n"
            "  port: 6379\n"
            "  db: 0\n"
            "  password: null\n"
        )
        parser = YAMLParser()
        chunks = list(parser.parse(f))
        assert len(chunks) >= 1
        all_text = " ".join(c.content for c in chunks)
        assert "database" in all_text
        assert "server" in all_text
        assert "redis" in all_text

    def test_split_top_level_keys(self):
        text = (
            "key1: value1\n"
            "key2:\n"
            "  nested: value\n"
            "key3: value3\n"
        )
        blocks = _split_top_level_keys(text)
        keys = [b["key"] for b in blocks]
        assert "key1" in keys
        assert "key2" in keys
        assert "key3" in keys

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.yaml"
        f.write_text("")
        parser = YAMLParser()
        assert list(parser.parse(f)) == []

    def test_can_parse(self):
        parser = YAMLParser()
        assert parser.can_parse(Path("config.yaml"))
        assert parser.can_parse(Path("config.yml"))
        assert not parser.can_parse(Path("config.toml"))

    def test_multi_document(self, tmp_path):
        f = tmp_path / "multi.yaml"
        f.write_text(
            "name: doc1\n"
            "value: hello world foo bar baz\n"
            "---\n"
            "name: doc2\n"
            "value: goodbye world foo bar baz\n"
        )
        parser = YAMLParser()
        chunks = list(parser.parse(f))
        assert len(chunks) >= 1
        all_text = " ".join(c.content for c in chunks)
        assert "doc1" in all_text
        assert "doc2" in all_text


# ── JSONParser ───────────────────────────────────────────────────────────

class TestJSONParser:
    def test_chunks_from_object(self, tmp_path):
        f = tmp_path / "package.json"
        data = {
            "name": "my-project",
            "version": "1.0.0",
            "dependencies": {
                "express": "^4.18.0",
                "lodash": "^4.17.21",
                "axios": "^1.6.0",
            },
            "devDependencies": {
                "jest": "^29.7.0",
                "eslint": "^8.56.0",
            },
            "scripts": {
                "start": "node index.js",
                "test": "jest",
                "lint": "eslint src/",
            },
        }
        f.write_text(json.dumps(data, indent=2))

        parser = JSONParser()
        chunks = list(parser.parse(f))
        assert len(chunks) >= 1
        all_text = " ".join(c.content for c in chunks)
        assert "express" in all_text
        assert "jest" in all_text

    def test_chunks_from_array(self, tmp_path):
        f = tmp_path / "data.json"
        data = [{"id": i, "name": f"item_{i}", "desc": f"Description for item {i}"} for i in range(20)]
        f.write_text(json.dumps(data, indent=2))

        parser = JSONParser()
        chunks = list(parser.parse(f))
        assert len(chunks) >= 1
        all_text = " ".join(c.content for c in chunks)
        assert "item_0" in all_text
        assert "item_19" in all_text

    def test_invalid_json(self, tmp_path):
        f = tmp_path / "broken.json"
        f.write_text("{this is not valid json")
        parser = JSONParser()
        chunks = list(parser.parse(f))
        assert chunks == []

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.json"
        f.write_text("")
        parser = JSONParser()
        assert list(parser.parse(f)) == []

    def test_can_parse(self):
        parser = JSONParser()
        assert parser.can_parse(Path("data.json"))
        assert not parser.can_parse(Path("data.yaml"))


# ── ShellParser ──────────────────────────────────────────────────────────

class TestShellParser:
    def test_chunks_by_function(self, tmp_path):
        f = tmp_path / "deploy.sh"
        f.write_text(
            "#!/bin/bash\n"
            "set -euo pipefail\n\n"
            "# Global vars\n"
            "DEPLOY_DIR=/opt/app\n"
            "LOG_FILE=/var/log/deploy.log\n\n"
            "build() {\n"
            "    echo 'Building...'\n"
            "    make clean\n"
            "    make all\n"
            "    echo 'Build complete'\n"
            "}\n\n"
            "deploy() {\n"
            "    echo 'Deploying...'\n"
            "    cp -r dist/* $DEPLOY_DIR/\n"
            "    systemctl restart app\n"
            "    echo 'Deploy complete'\n"
            "}\n\n"
            "# Main\n"
            "build\n"
            "deploy\n"
        )
        parser = ShellParser()
        chunks = list(parser.parse(f))

        labels = [c.chapter_title for c in chunks]
        assert any("build" in l for l in labels)
        assert any("deploy" in l for l in labels)

    def test_function_keyword_style(self, tmp_path):
        f = tmp_path / "utils.sh"
        f.write_text(
            "#!/bin/bash\n\n"
            "function cleanup {\n"
            "    rm -rf /tmp/work\n"
            "    echo 'Cleaned up'\n"
            "}\n\n"
            "function setup {\n"
            "    mkdir -p /tmp/work\n"
            "    echo 'Setup done'\n"
            "}\n"
        )
        parser = ShellParser()
        chunks = list(parser.parse(f))

        labels = [c.chapter_title for c in chunks]
        assert any("cleanup" in l for l in labels)
        assert any("setup" in l for l in labels)

    def test_no_functions(self, tmp_path):
        f = tmp_path / "simple.sh"
        f.write_text(
            "#!/bin/bash\n"
            "echo 'Hello'\n"
            "echo 'World'\n"
            "exit 0\n"
        )
        parser = ShellParser()
        chunks = list(parser.parse(f))
        assert len(chunks) >= 1
        assert "global" in chunks[0].chapter_title

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.sh"
        f.write_text("")
        parser = ShellParser()
        assert list(parser.parse(f)) == []

    def test_can_parse(self):
        parser = ShellParser()
        assert parser.can_parse(Path("script.sh"))
        assert parser.can_parse(Path("script.bash"))
        assert parser.can_parse(Path("script.zsh"))
        assert not parser.can_parse(Path("script.py"))


# ── Registry ─────────────────────────────────────────────────────────────

class TestRegistryPriority:
    """Verify that smart parsers take priority over PlainTextParser."""

    def test_python_has_priority(self):
        parser = ParserRegistry.get_parser(Path("test.py"))
        assert parser is not None
        assert parser.name == "python"

    def test_yaml_has_priority(self):
        parser = ParserRegistry.get_parser(Path("test.yaml"))
        assert parser is not None
        assert parser.name == "yaml"

    def test_yml_has_priority(self):
        parser = ParserRegistry.get_parser(Path("test.yml"))
        assert parser is not None
        assert parser.name == "yaml"

    def test_json_registered(self):
        parser = ParserRegistry.get_parser(Path("test.json"))
        assert parser is not None
        assert parser.name == "json"

    def test_shell_has_priority(self):
        parser = ParserRegistry.get_parser(Path("test.sh"))
        assert parser is not None
        assert parser.name == "shell"

    def test_latex_registered(self):
        parser = ParserRegistry.get_parser(Path("test.tex"))
        assert parser is not None
        assert parser.name == "latex"

    def test_plaintext_still_works(self):
        parser = ParserRegistry.get_parser(Path("test.js"))
        assert parser is not None
        assert parser.name == "plaintext"

    def test_markdown_still_works(self):
        parser = ParserRegistry.get_parser(Path("test.md"))
        assert parser is not None
        assert parser.name == "markdown"
