"""The plugin's hooks create indexes; they must also put them to work.

At session start the plugin indexes the project it is opened in, and at the
end of every turn it indexes what the agent edited. Neither ever enrolled
the project with the supervisor, so the supervisor never scanned it: a
monorepo opened on 2026-09-07 was used by agents for a week and held only
the files they had happened to touch.

The same hook indexed wherever a session was opened — including the root of
a development tree holding thirty projects, each already indexed. Once
before, that shape produced a 27 GB index and three days of scanning.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from rtfm.core import registry

ROOT = Path(__file__).resolve().parents[2]


def _hook(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_rtfm_hook_{name}", ROOT / "hooks" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def elsewhere_home(tmp_path, monkeypatch):
    home = tmp_path / "maison"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


@pytest.fixture
def depot(tmp_path, monkeypatch, elsewhere_home):
    root = tmp_path / "depot"
    root.mkdir()
    (root / "README.md").write_text("# Depot\n\nDu texte a indexer.\n" * 5,
                                    encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    return root


class TestSessionStart:

    def test_a_new_project_is_indexed_and_enrolled(self, depot):
        _hook("rtfm_bootstrap").main()
        assert (depot / ".rtfm" / "library.db").exists()
        assert registry.is_enrolled(depot / ".rtfm"), (
            "indexed but never scanned again — the week-long silence")

    def test_an_existing_unenrolled_index_is_enrolled(self, depot):
        """The projects already stranded: they recover at the next session."""
        from rtfm.core.library import Library
        (depot / ".rtfm").mkdir()
        Library(str(depot / ".rtfm" / "library.db")).close()
        assert not registry.is_enrolled(depot / ".rtfm")

        _hook("rtfm_bootstrap").main()
        assert registry.is_enrolled(depot / ".rtfm")

    def test_it_says_when_it_enrolled(self, depot):
        _hook("rtfm_bootstrap").main()
        log = (depot / ".rtfm" / "rtfm.log").read_text(encoding="utf-8")
        assert "enrolled" in log

    def test_a_home_directory_is_not_indexed(self, elsewhere_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(elsewhere_home))
        _hook("rtfm_bootstrap").main()
        assert not (elsewhere_home / ".rtfm").exists()
        assert registry.load() == []

    def test_a_directory_holding_indexed_projects_is_not_indexed(
            self, tmp_path, monkeypatch, elsewhere_home):
        """Opened at the root of a development tree, the hook indexed the
        tree itself beside the projects it held."""
        from rtfm.core.library import Library
        tree = tmp_path / "dev"
        inner = tree / "musique" / "projet"
        (inner / ".rtfm").mkdir(parents=True)
        Library(str(inner / ".rtfm" / "library.db")).close()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tree))

        _hook("rtfm_bootstrap").main()
        assert not (tree / ".rtfm").exists()

    def test_a_project_vendored_under_dependencies_does_not_count(
            self, depot):
        from rtfm.core.library import Library
        vendored = depot / "node_modules" / "paquet"
        (vendored / ".rtfm").mkdir(parents=True)
        Library(str(vendored / ".rtfm" / "library.db")).close()

        _hook("rtfm_bootstrap").main()
        assert (depot / ".rtfm" / "library.db").exists()


class TestEndOfTurn:

    def test_a_project_fed_only_by_edits_gets_enrolled(self, depot):
        from rtfm.core.library import Library
        (depot / ".rtfm").mkdir()
        Library(str(depot / ".rtfm" / "library.db")).close()
        (depot / ".rtfm" / "touched_files.tmp").write_text(
            str(depot / "README.md") + "\n", encoding="utf-8")

        _hook("rtfm_stop_sync").main()
        assert registry.is_enrolled(depot / ".rtfm")
        log = (depot / ".rtfm" / "rtfm.log").read_text(encoding="utf-8")
        assert "stop-sync done" in log and "enrolled" in log

    def test_an_enrolled_project_is_not_rewritten(self, depot):
        from rtfm.core.library import Library
        (depot / ".rtfm").mkdir()
        Library(str(depot / ".rtfm" / "library.db")).close()
        registry.register(depot / ".rtfm")
        before = registry.REGISTRY_PATH.stat().st_mtime_ns
        (depot / ".rtfm" / "touched_files.tmp").write_text(
            str(depot / "README.md") + "\n", encoding="utf-8")

        _hook("rtfm_stop_sync").main()
        assert registry.REGISTRY_PATH.stat().st_mtime_ns == before
