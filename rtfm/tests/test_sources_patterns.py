"""Editing a source's include/exclude patterns from the CLI.

Changing what a corpus indexes used to mean hand-editing config.json — the
one thing the project rules forbid, and the only way to do it. These tests
pin the sanctioned path: `rtfm sources exclude add/remove <corpus> <pattern>`
writes through the config helpers and leaves the rest of the source intact.
"""
from __future__ import annotations

import json
from argparse import Namespace

import pytest

from rtfm.config import edit_source_patterns, save_config


@pytest.fixture
def project(tmp_path):
    (tmp_path / ".rtfm").mkdir()
    save_config(tmp_path, {"sources": [{
        "path": str(tmp_path / "corpus/ifs"),
        "corpus": "ifs",
        "extensions": "pdf,epub",
        "honor_gitignore": False,
        "exclude": ["*Mosaic Mind*", "*keep*"],
    }]})
    return tmp_path


def _source(root):
    return json.loads((root / ".rtfm" / "config.json").read_text())["sources"][0]


def test_removing_a_pattern_leaves_the_rest_of_the_source(project):
    before, after = edit_source_patterns(project, "ifs", "exclude",
                                         remove=["*Mosaic Mind*"])
    assert before == ["*Mosaic Mind*", "*keep*"]
    assert after == ["*keep*"]
    src = _source(project)
    # The point of the helper: the other fields survive the write.
    assert src["honor_gitignore"] is False
    assert src["extensions"] == "pdf,epub"


def test_adding_is_idempotent(project):
    edit_source_patterns(project, "ifs", "exclude", add=["*draft*"])
    before, after = edit_source_patterns(project, "ifs", "exclude",
                                         add=["*draft*"])
    assert before == after  # already present, no duplicate
    assert after.count("*draft*") == 1


def test_emptying_the_list_drops_the_key(project):
    edit_source_patterns(project, "ifs", "exclude",
                         remove=["*Mosaic Mind*", "*keep*"])
    assert "exclude" not in _source(project)


def test_an_unknown_corpus_raises(project):
    with pytest.raises(KeyError):
        edit_source_patterns(project, "nope", "exclude", add=["*x*"])


def test_an_unknown_field_raises(project):
    with pytest.raises(ValueError):
        edit_source_patterns(project, "ifs", "banana", add=["*x*"])


# --- through the CLI command ------------------------------------------------

def _run(root, field, op, corpus, *patterns):
    from rtfm.cli import cmd_sources_patterns
    from rtfm.core.library import Library
    # find_rtfm_root needs the db to exist.
    db = root / ".rtfm" / "library.db"
    if not db.exists():
        Library(str(db))
    import os
    cwd = os.getcwd()
    os.chdir(root)
    try:
        args = Namespace(field=field, op=op, corpus=corpus,
                         patterns=list(patterns))
        try:
            cmd_sources_patterns(args)
            return 0
        except SystemExit as exc:
            # sys.exit("msg") carries the message as .code; the interpreter
            # only prints it on an *uncaught* exit, so read it here.
            return exc.code if exc.code is not None else 0
    finally:
        os.chdir(cwd)


def test_cli_exclude_remove_then_add(project, capsys):
    assert _run(project, "exclude", "remove", "ifs", "*Mosaic Mind*") == 0
    assert "*Mosaic Mind*" not in _source(project).get("exclude", [])
    out = capsys.readouterr().out
    assert "next `rtfm sync`" in out

    assert _run(project, "exclude", "add", "ifs", "*new*") == 0
    assert "*new*" in _source(project)["exclude"]


def test_cli_unknown_corpus_exits_nonzero(project):
    code = _run(project, "exclude", "add", "ghost", "*x*")
    assert code != 0
    # The message names the bad corpus and lists the known ones.
    assert "ghost" in str(code) and "ifs" in str(code)
