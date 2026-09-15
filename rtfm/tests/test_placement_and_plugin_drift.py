"""Two things that went wrong more than once, because nothing checked them.

An index created where no index belongs — a home directory, the root of a
development tree — indexes every project below it a second time. It happened
on 2026-07-29 (9.9 GB), earlier (27 GB), and again on 2026-09-07, each time
through a different creator, because the rule lived in none of them.

And the Claude Code plugin carries its own copy of RTFM. It stayed eight days
behind the installed package, so every fix in between reached no agent, and
nothing said so.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rtfm.core.placement import refusal_to_index


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "maison"
    h.mkdir()
    monkeypatch.setattr(Path, "home", lambda: h)
    return h


def _indexed(project: Path) -> Path:
    (project / ".rtfm").mkdir(parents=True)
    (project / ".rtfm" / "library.db").write_bytes(b"")
    return project


class TestWhereAnIndexMayGo:

    def test_an_ordinary_project_is_accepted(self, home):
        project = home / "dev" / "projet"
        project.mkdir(parents=True)
        assert refusal_to_index(project) is None

    def test_the_home_directory_is_refused(self, home):
        assert "home" in refusal_to_index(home)

    def test_anything_above_home_is_refused(self, home):
        assert refusal_to_index(home.parent) is not None

    def test_a_tree_holding_an_indexed_project_is_refused(self, home):
        """The ~/dev shape: thirty projects below, each with its own index."""
        tree = home / "dev"
        _indexed(tree / "musique" / "synthe")
        reason = refusal_to_index(tree)
        assert reason and "synthe" in reason

    def test_a_directory_inside_an_index_is_refused(self, home):
        """Found on disk: an index created inside another index's directory."""
        inner = home / "dev" / "projet" / ".rtfm"
        inner.mkdir(parents=True)
        assert "inside an index" in refusal_to_index(inner)

    def test_dependencies_do_not_count_as_projects(self, home):
        project = home / "dev" / "app"
        _indexed(project / "node_modules" / "paquet")
        assert refusal_to_index(project) is None

    def test_a_project_deeper_than_the_walk_is_not_evidence(self, home):
        project = home / "dev" / "app"
        _indexed(project / "a" / "b" / "c" / "d")
        assert refusal_to_index(project) is None

    def test_a_project_that_already_has_its_index_may_be_initialised_again(
            self, home):
        """Three real projects hold a copy of another with its index inside;
        re-initialising them creates nothing new."""
        project = _indexed(home / "dev" / "hub")
        _indexed(project / ".last" / "BPx")
        assert refusal_to_index(project) is None

    def test_the_filesystem_root_is_refused(self):
        assert refusal_to_index(Path("/")) is not None


class TestEveryCreatorAsks:

    def test_init_refuses(self, home):
        from rtfm.plugin.install import init_project
        tree = home / "dev"
        _indexed(tree / "projet")
        with pytest.raises(ValueError, match="already contains"):
            init_project(tree, install_hook=False, no_embeddings=True)
        assert not (tree / ".rtfm").exists()

    def test_the_init_command_refuses(self, home, monkeypatch):
        import argparse
        from rtfm.cli import cmd_init
        tree = home / "dev"
        _indexed(tree / "projet")
        monkeypatch.chdir(tree)
        with pytest.raises(SystemExit) as exc:
            cmd_init(argparse.Namespace(db=".rtfm/library.db", corpus="default",
                                        no_hook=True, no_embeddings=True))
        assert "not initialising" in str(exc.value)
        assert not (tree / ".rtfm").exists()

    def test_the_plugin_bootstrap_uses_the_same_rule(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "hooks" / "rtfm_bootstrap.py").read_text(encoding="utf-8")
        assert "refusal_to_index" in text
        assert "def _refusal" not in text, "a second copy of the rule"


class TestPluginDrift:

    def _installed(self, tmp_path, *entries):
        f = tmp_path / "installed_plugins.json"
        f.write_text(json.dumps({"version": 2, "plugins": {
            "rtfm@roomi-fields": list(entries)}}), encoding="utf-8")
        return f

    def test_an_older_plugin_is_reported(self, tmp_path, monkeypatch):
        from rtfm.plugin import drift
        monkeypatch.setattr(drift, "installed_version", lambda: "0.45.0")
        reg = self._installed(tmp_path, {"scope": "user", "version": "0.39.4"})
        assert drift.plugin_behind(registry=reg) == ("0.39.4", "0.45.0")

    def test_a_current_plugin_is_not(self, tmp_path, monkeypatch):
        from rtfm.plugin import drift
        monkeypatch.setattr(drift, "installed_version", lambda: "0.46.0")
        reg = self._installed(tmp_path, {"scope": "user", "version": "0.46.0"})
        assert drift.plugin_behind(registry=reg) is None

    def test_versions_compare_as_numbers(self, tmp_path, monkeypatch):
        from rtfm.plugin import drift
        monkeypatch.setattr(drift, "installed_version", lambda: "0.10.0")
        reg = self._installed(tmp_path, {"scope": "user", "version": "0.9.9"})
        assert drift.plugin_behind(registry=reg) == ("0.9.9", "0.10.0")

    def test_a_project_install_overrides_the_user_one(self, tmp_path, monkeypatch):
        from rtfm.plugin import drift
        monkeypatch.setattr(drift, "installed_version", lambda: "0.46.0")
        project = tmp_path / "icm"
        project.mkdir()
        reg = self._installed(
            tmp_path,
            {"scope": "local", "version": "0.7.2", "projectPath": str(project)},
            {"scope": "user", "version": "0.46.0"})
        assert drift.plugin_behind(project, registry=reg) == ("0.7.2", "0.46.0")
        assert drift.plugin_behind(tmp_path / "ailleurs", registry=reg) is None

    def test_no_plugin_is_not_a_warning(self, tmp_path, monkeypatch):
        from rtfm.plugin import drift
        monkeypatch.setattr(drift, "installed_version", lambda: "0.46.0")
        assert drift.plugin_behind(registry=tmp_path / "absent.json") is None

    def test_the_warning_names_the_command(self, monkeypatch):
        from rtfm.plugin import drift
        monkeypatch.setattr(drift, "plugin_behind", lambda *a, **k: ("0.39.4", "0.46.0"))
        text = drift.warning()
        assert "0.39.4" in text and "claude plugin update rtfm@roomi-fields" in text
