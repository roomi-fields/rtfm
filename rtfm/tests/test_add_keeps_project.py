"""Adding a source never takes the project out of what is indexed.

Without declared sources the project directory is the source. Declaring a
first one used to replace it, and the next start took the whole project out
of the index: it nearly happened to a project given a shared folder of
reference norms.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from rtfm.cli import cmd_add


def _args(path):
    return SimpleNamespace(path=str(path), corpus="normes", extensions=None,
                           include=None, exclude=None, no_gitignore=False)


def _sources(project):
    cfg = json.loads((project / ".rtfm" / "config.json").read_text())
    return [(s["corpus"], s["path"]) for s in cfg["sources"]]


def _project(tmp_path, config):
    project = tmp_path / "projet"
    (project / ".rtfm").mkdir(parents=True)
    (project / ".rtfm" / "library.db").touch()
    (project / ".rtfm" / "config.json").write_text(json.dumps(config))
    return project


def test_a_first_added_source_keeps_the_project(tmp_path, monkeypatch):
    project = _project(tmp_path, {"corpus": "default"})
    shared = tmp_path / "normes"
    shared.mkdir()
    monkeypatch.chdir(project)
    cmd_add(_args(shared))
    assert _sources(project) == [("default", str(project.resolve())),
                                 ("normes", str(shared.resolve()))]


def test_declared_sources_are_left_as_they_are(tmp_path, monkeypatch):
    project = tmp_path / "projet"
    only = tmp_path / "choisi"
    only.mkdir()
    project = _project(tmp_path, {"sources": [{"path": str(only.resolve()),
                                               "corpus": "choisi"}]})
    shared = tmp_path / "normes"
    shared.mkdir()
    monkeypatch.chdir(project)
    cmd_add(_args(shared))
    assert _sources(project) == [("choisi", str(only.resolve())),
                                 ("normes", str(shared.resolve()))]
