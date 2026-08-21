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
