"""Tests for rtfm.config — auto-detection and config management."""

import json
import os
from pathlib import Path

import pytest

from rtfm.config import (
    add_source,
    find_rtfm_root,
    list_sources,
    load_config,
    remove_source,
    resolve_db,
    save_config,
)


@pytest.fixture
def rtfm_project(tmp_path):
    """Create a minimal .rtfm/ project structure."""
    rtfm_dir = tmp_path / ".rtfm"
    rtfm_dir.mkdir()
    db_path = rtfm_dir / "library.db"
    db_path.touch()
    return tmp_path


class TestFindRtfmRoot:
    def test_finds_in_current_dir(self, rtfm_project):
        result = find_rtfm_root(rtfm_project)
        assert result == rtfm_project

    def test_finds_in_parent_dir(self, rtfm_project):
        child = rtfm_project / "src" / "deep"
        child.mkdir(parents=True)
        result = find_rtfm_root(child)
        assert result == rtfm_project

    def test_not_found(self, tmp_path):
        result = find_rtfm_root(tmp_path)
        assert result is None


class TestResolveDb:
    def test_explicit_has_priority(self, rtfm_project, monkeypatch):
        monkeypatch.setenv("RTFM_DB", "/env/path.db")
        monkeypatch.chdir(rtfm_project)
        assert resolve_db("/explicit/path.db") == "/explicit/path.db"

    def test_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RTFM_DB", "/env/path.db")
        monkeypatch.chdir(tmp_path)
        assert resolve_db(None) == "/env/path.db"

    def test_auto_detect(self, rtfm_project, monkeypatch):
        monkeypatch.delenv("RTFM_DB", raising=False)
        monkeypatch.chdir(rtfm_project)
        result = resolve_db(None)
        assert result == str(rtfm_project / ".rtfm" / "library.db")

    def test_fallback_legacy(self, tmp_path, monkeypatch):
        monkeypatch.delenv("RTFM_DB", raising=False)
        monkeypatch.chdir(tmp_path)
        assert resolve_db(None) == "library.db"


class TestConfig:
    def test_load_missing(self, tmp_path):
        config = load_config(tmp_path)
        assert config == {}

    def test_save_and_load(self, tmp_path):
        (tmp_path / ".rtfm").mkdir()
        data = {"corpus": "test", "sources": []}
        save_config(tmp_path, data)
        loaded = load_config(tmp_path)
        assert loaded == data

    def test_save_creates_rtfm_dir(self, tmp_path):
        save_config(tmp_path, {"corpus": "auto"})
        assert (tmp_path / ".rtfm" / "config.json").exists()


class TestAddSource:
    def test_add_source(self, tmp_path):
        (tmp_path / ".rtfm").mkdir()
        result = add_source(tmp_path, str(tmp_path / "docs"), "docs")
        assert result == "added"
        sources = list_sources(tmp_path)
        assert len(sources) == 1
        assert sources[0]["corpus"] == "docs"

    def test_add_source_with_extensions(self, tmp_path):
        (tmp_path / ".rtfm").mkdir()
        add_source(tmp_path, str(tmp_path), "code", extensions=".py,.js")
        sources = list_sources(tmp_path)
        assert sources[0]["extensions"] == ".py,.js"

    def test_deduplicate(self, tmp_path):
        (tmp_path / ".rtfm").mkdir()
        add_source(tmp_path, str(tmp_path / "docs"), "docs")
        result = add_source(tmp_path, str(tmp_path / "docs"), "docs")
        assert result == "already exists"
        sources = list_sources(tmp_path)
        assert len(sources) == 1

    def test_same_path_different_corpus(self, tmp_path):
        (tmp_path / ".rtfm").mkdir()
        add_source(tmp_path, str(tmp_path / "src"), "code")
        result = add_source(tmp_path, str(tmp_path / "src"), "tests")
        assert result == "added"
        sources = list_sources(tmp_path)
        assert len(sources) == 2

    def test_add_source_with_include_exclude(self, tmp_path):
        (tmp_path / ".rtfm").mkdir()
        add_source(tmp_path, str(tmp_path / "d"), "c",
                   include=["-gr.*", "*.bps"], exclude=["*.min.js"])
        src = list_sources(tmp_path)[0]
        assert src["include"] == ["-gr.*", "*.bps"]
        assert src["exclude"] == ["*.min.js"]
        # No extensions key when indexing all text.
        assert "extensions" not in src


class TestRemoveSource:
    def test_remove_by_path_and_corpus(self, tmp_path):
        (tmp_path / ".rtfm").mkdir()
        add_source(tmp_path, str(tmp_path / "src"), "code")
        add_source(tmp_path, str(tmp_path / "src"), "tests")
        n = remove_source(tmp_path, path=str(tmp_path / "src"), corpus="code")
        assert n == 1
        remaining = list_sources(tmp_path)
        assert [s["corpus"] for s in remaining] == ["tests"]

    def test_remove_whole_corpus(self, tmp_path):
        (tmp_path / ".rtfm").mkdir()
        add_source(tmp_path, "/a", "projets")
        add_source(tmp_path, "/b", "projets")
        add_source(tmp_path, "/c", "default")
        n = remove_source(tmp_path, corpus="projets")
        assert n == 2
        assert [s["corpus"] for s in list_sources(tmp_path)] == ["default"]

    def test_remove_by_path_any_corpus(self, tmp_path):
        (tmp_path / ".rtfm").mkdir()
        add_source(tmp_path, str(tmp_path / "src"), "code")
        add_source(tmp_path, str(tmp_path / "src"), "tests")
        n = remove_source(tmp_path, path=str(tmp_path / "src"))
        assert n == 2
        assert list_sources(tmp_path) == []

    def test_remove_missing_directory_still_works(self, tmp_path):
        """A source whose directory no longer exists must still be removable
        — deletion is often *why* you remove it."""
        (tmp_path / ".rtfm").mkdir()
        gone = str(tmp_path / "was-here")
        add_source(tmp_path, gone, "socle")
        n = remove_source(tmp_path, path=gone)
        assert n == 1
        assert list_sources(tmp_path) == []

    def test_remove_no_match_is_zero(self, tmp_path):
        (tmp_path / ".rtfm").mkdir()
        add_source(tmp_path, "/a", "x")
        assert remove_source(tmp_path, corpus="nope") == 0
        assert len(list_sources(tmp_path)) == 1

    def test_remove_requires_a_criterion(self, tmp_path):
        (tmp_path / ".rtfm").mkdir()
        with pytest.raises(ValueError):
            remove_source(tmp_path)


class TestListSources:
    def test_empty(self, tmp_path):
        sources = list_sources(tmp_path)
        assert sources == []

    def test_with_sources(self, tmp_path):
        (tmp_path / ".rtfm").mkdir()
        add_source(tmp_path, "/path/a", "a")
        add_source(tmp_path, "/path/b", "b")
        sources = list_sources(tmp_path)
        assert len(sources) == 2


class TestScanPayloadHasOneAuthor:
    """Issue #6 came from four modules describing a source by hand and
    drifting apart: ``rtfm sync`` silently dropped the user's include/exclude
    patterns while the periodic scan honoured them. These guards fail if a
    caller starts hand-rolling a scan payload again."""

    def test_no_module_hand_builds_a_scan_payload(self):
        """Every ``enqueue("scan", ...)`` must pass a payload that came from
        :func:`build_scan_payload`."""
        import ast

        import rtfm

        pkg_root = Path(rtfm.__file__).parent
        offenders = []
        for path in sorted(pkg_root.rglob("*.py")):
            if "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            blessed = {
                target.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and getattr(node.value.func, "id", None) == "build_scan_payload"
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            # Follow one hop of collection: payloads are often gathered in a
            # list (to be printed, counted, dry-run) before being enqueued.
            collections = {
                node.func.value.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and getattr(node.func, "attr", None) == "append"
                and isinstance(getattr(node.func, "value", None), ast.Name)
                and node.args
                and ((isinstance(node.args[0], ast.Name)
                      and node.args[0].id in blessed)
                     or (isinstance(node.args[0], ast.Call)
                         and getattr(node.args[0].func, "id", None)
                         == "build_scan_payload"))
            }
            blessed |= {
                node.target.id
                for node in ast.walk(tree)
                if isinstance(node, ast.For)
                and isinstance(node.target, ast.Name)
                and isinstance(node.iter, ast.Name)
                and node.iter.id in collections
            }
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if getattr(node.func, "attr", None) != "enqueue":
                    continue
                if not node.args or not isinstance(node.args[0], ast.Constant):
                    continue
                if node.args[0].value != "scan" or len(node.args) < 2:
                    continue
                payload = node.args[1]
                built = (
                    isinstance(payload, ast.Call)
                    and getattr(payload.func, "id", None) == "build_scan_payload"
                ) or (
                    isinstance(payload, ast.Name) and payload.id in blessed
                )
                if not built:
                    offenders.append(
                        f"{path.relative_to(pkg_root)}:{node.lineno}")
        assert not offenders, (
            "scan payload built by hand instead of build_scan_payload: "
            + ", ".join(offenders))

    def test_every_enqueue_site_describes_a_source_identically(self, tmp_path):
        """The supervisor, the read-repair path and ``rtfm sync`` must send
        byte-identical payloads for the same source — the queue deduplicates
        on the payload JSON, so a field that only one of them spells out also
        costs a redundant scan."""
        from unittest.mock import patch

        from rtfm.config import build_scan_payload
        from rtfm.core import freshness
        from rtfm.core.library import Library
        from rtfm.core.queue import Queue

        root = tmp_path / "proj"
        docs = root / "docs"
        docs.mkdir(parents=True)
        (root / ".rtfm").mkdir()
        db = root / ".rtfm" / "library.db"
        Library(str(db)).close()
        add_source(root, str(docs), "docs", extensions="md",
                   exclude=["data/*"], include=["*.md"])

        cfg = load_config(root)
        src = cfg["sources"][0]
        reference = build_scan_payload(src, cfg)
        assert reference["exclude"] == ["data/*"]

        # The read-repair path, for real.
        freshness._enqueue_scans(str(db), str(root))
        q = Queue(str(db))
        try:
            queued = [j.payload for j in q.list_pending(limit=10)
                      if j.type == "scan"]
        finally:
            q.close()
        assert queued == [reference]

        # And the CLI, whose divergence was the reported bug.
        cwd = os.getcwd()
        os.chdir(root)
        try:
            from rtfm.cli import main
            with patch("rtfm.cli_worker.ensure_worker_running",
                       return_value=42424), \
                 patch("sys.argv", ["rtfm", "sync", "--background"]):
                try:
                    main()
                except SystemExit:
                    pass
        finally:
            os.chdir(cwd)

        q = Queue(str(db))
        try:
            scans = [j.payload for j in q.list_pending(limit=10)
                     if j.type == "scan"]
        finally:
            q.close()
        # Identical payload → the queue deduplicated it, one job still.
        assert scans == [reference]


class TestHandWrittenSelectionRules:
    """A rule typed into config.json means what it looks like it means.

    `"exclude": "data/*,build/*"` is the natural thing to write — it is
    exactly what the CLI flag takes. A bare string is iterable, so every
    matcher downstream used to walk it letter by letter and the scan
    silently selected nothing; the only visible trace was `rtfm sources`
    printing the rule one character per line.
    """

    def _write(self, root, source):
        (root / ".rtfm").mkdir(exist_ok=True)
        save_config(root, {"sources": [source]})

    def test_a_comma_separated_string_is_read_as_the_patterns_it_lists(
            self, tmp_path):
        self._write(tmp_path, {"path": "/x", "corpus": "c",
                               "exclude": "data/*,build/*"})
        src = load_config(tmp_path)["sources"][0]
        assert src["exclude"] == ["data/*", "build/*"]

    def test_include_gets_the_same_reading(self, tmp_path):
        self._write(tmp_path, {"path": "/x", "corpus": "c",
                               "include": " *.md , docs/* "})
        assert load_config(tmp_path)["sources"][0]["include"] == [
            "*.md", "docs/*"]

    def test_a_single_pattern_string_stays_one_pattern(self, tmp_path):
        self._write(tmp_path, {"path": "/x", "corpus": "c",
                               "exclude": "node_modules/*"})
        assert load_config(tmp_path)["sources"][0]["exclude"] == [
            "node_modules/*"]

    def test_a_list_is_left_alone(self, tmp_path):
        self._write(tmp_path, {"path": "/x", "corpus": "c",
                               "exclude": ["a/*", "b/*"]})
        assert load_config(tmp_path)["sources"][0]["exclude"] == ["a/*", "b/*"]

    def test_an_empty_rule_is_no_rule_at_all(self, tmp_path):
        """Better absent than present-and-matching-nothing: an empty string
        used to survive as a pattern and could reject every file."""
        self._write(tmp_path, {"path": "/x", "corpus": "c", "exclude": " , "})
        assert "exclude" not in load_config(tmp_path)["sources"][0]

    def test_the_rules_reach_the_scan(self, tmp_path):
        from rtfm.config import build_scan_payload

        self._write(tmp_path, {"path": "/x", "corpus": "c",
                               "exclude": "data/*,build/*"})
        src = load_config(tmp_path)["sources"][0]
        assert build_scan_payload(src)["exclude"] == ["data/*", "build/*"]


class TestIndexingWhatGitIgnores:
    """A corpus of heavy files is routinely kept out of version control.
    Registering it must not require hand-editing config.json afterwards."""

    def test_add_source_records_the_choice(self, tmp_path):
        (tmp_path / ".rtfm").mkdir()
        add_source(tmp_path, str(tmp_path / "pdfs"), "papers",
                   honor_gitignore=False)
        assert list_sources(tmp_path)[0]["honor_gitignore"] is False

    def test_the_default_stays_unwritten(self, tmp_path):
        """Omitted, not spelled out: the queue deduplicates pending jobs on
        the exact payload, so a default written out would fail to match."""
        (tmp_path / ".rtfm").mkdir()
        add_source(tmp_path, str(tmp_path / "docs"), "docs")
        assert "honor_gitignore" not in list_sources(tmp_path)[0]

    def test_the_choice_reaches_the_scan(self, tmp_path):
        from rtfm.config import build_scan_payload

        (tmp_path / ".rtfm").mkdir()
        add_source(tmp_path, str(tmp_path / "pdfs"), "papers",
                   honor_gitignore=False)
        src = list_sources(tmp_path)[0]
        assert build_scan_payload(src)["honor_gitignore"] is False
