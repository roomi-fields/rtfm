"""The end-of-session pass that indexes Claude memory files.

It ran in every session, agents' sandboxes included, where RTFM's Python is
out of sight: each of those session ends reported "not found". It held the
end of the session while it read every project's memory. And a project
whose memory directory is a link to another's had the same files indexed
under two names, which fought over one entry on every pass.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess

import pytest

from rtfm.plugin.memory_hook import memory_sources, run_hook


def _memory(projects, slug, files=None):
    d = projects / slug / "memory"
    d.mkdir(parents=True)
    for name, text in (files or {"MEMORY.md": "# Mémoire\n\n- une règle\n"}).items():
        (d / name).write_text(text, encoding="utf-8")
    return d


def _tracked(db):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return sorted(conn.execute("SELECT corpus, filepath FROM indexed_files"))
    finally:
        conn.close()


def test_every_project_is_indexed_under_its_own_name(tmp_path):
    projects = tmp_path / "projects"
    _memory(projects, "-home-a")
    _memory(projects, "-home-b")
    run_hook(tmp_path / "memory.db", projects)
    assert _tracked(tmp_path / "memory.db") == [
        ("claude-memory/home-a", "MEMORY.md"), ("claude-memory/home-b", "MEMORY.md")]


def test_a_memory_shared_by_a_link_is_indexed_once(tmp_path):
    projects = tmp_path / "projects"
    _memory(projects, "-home-zz-real")
    (projects / "-home-aa-link").mkdir()
    (projects / "-home-aa-link" / "memory").symlink_to(projects / "-home-zz-real" / "memory")
    keep, dupes = memory_sources(projects)
    assert [c for c, _ in keep] == ["claude-memory/home-zz-real"]
    assert dupes == ["claude-memory/home-aa-link"]


def test_a_duplicate_indexed_before_is_taken_out(tmp_path):
    """The state found on one machine: both names indexed, the link's entry
    pointing at the real directory. Every pass ended in a UNIQUE error."""
    from rtfm.core.library import Library
    from rtfm.core.sync import sync
    projects = tmp_path / "projects"
    real = _memory(projects, "-home-real")
    (projects / "-home-link").mkdir()
    (projects / "-home-link" / "memory").symlink_to(real)
    db = tmp_path / "memory.db"
    lib = Library(str(db))
    sync(library=lib, root=projects / "-home-link" / "memory",
         corpus="claude-memory/home-link", extensions={".md"},
         generate_embeddings=False, retain_history=None)
    lib.close()
    run_hook(db, projects)
    assert _tracked(db) == [("claude-memory/home-real", "MEMORY.md")]


def test_a_second_pass_leaves_while_one_runs(tmp_path):
    from rtfm.core.portable import open_lock_file, try_lock_exclusive, unlock
    projects = tmp_path / "projects"
    _memory(projects, "-home-a")
    fd = open_lock_file(tmp_path / "memory.lock")
    assert try_lock_exclusive(fd)
    try:
        run_hook(tmp_path / "memory.db", projects)
        assert not (tmp_path / "memory.db").exists()
    finally:
        unlock(fd)
        os.close(fd)


def test_an_index_that_cannot_be_written_is_left_quietly(tmp_path):
    projects = tmp_path / "projects"
    _memory(projects, "-home-a")
    ro = tmp_path / "lecture-seule"
    ro.mkdir()
    os.chmod(ro, 0o555)
    try:
        if os.access(ro, os.W_OK):
            pytest.skip("running with rights that write anywhere")
        run_hook(ro / "memory.db", projects)          # must not raise
    finally:
        os.chmod(ro, 0o755)


@pytest.fixture
def installed(tmp_path, monkeypatch):
    from pathlib import Path
    from rtfm.plugin.hooks import install_memory_hook
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    install_memory_hook()
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    return settings["hooks"]["SessionEnd"][0]["hooks"][0]


def test_the_hook_runs_in_the_background(installed):
    assert installed["async"] is True


def test_a_missing_python_ends_quietly(installed, tmp_path):
    """An agent's sandbox does not see RTFM's Python."""
    command = installed["command"].replace(
        installed["command"].split('"')[1], str(tmp_path / "absent" / "python"))
    run = subprocess.run(["sh", "-c", command], capture_output=True, text=True)
    assert run.returncode == 0 and run.stderr == ""
