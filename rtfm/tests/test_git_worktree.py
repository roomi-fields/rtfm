"""An agent's git worktree is served from the main tree's index, read-only.

Agents work in their own copy of a repository (``git worktree add``), often
in a sandbox where everything outside the copy is read-only. Started there,
RTFM took the copy for a new project: it built a full second index inside
it (about 200 MB on one repository), added its section to the copy's
CLAUDE.md, wrote its settings, and enrolled the copy with the shared
indexer — dirtying a tree that must hold only the agent's work, and
blocking the fast-forward that brings that work back.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture
def repo(tmp_path):
    """A main tree, indexed, with an agent's worktree inside it."""
    from rtfm.core.library import Library
    from rtfm.core.sync import sync

    main = tmp_path / "depot"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    (main / "moteur.md").write_text("# Moteur\n\nLe planificateur de scenes.\n" * 10)
    (main / "CLAUDE.md").write_text("# Projet\n\nConsignes.\n")
    (main / ".gitignore").write_text(".rtfm/\n.claude/\n")
    _git(main, "add", ".")
    _git(main, "commit", "-q", "-m", "init")
    lib = Library(str(main / ".rtfm" / "library.db"))
    try:
        sync(library=lib, root=main, corpus="default", generate_embeddings=False)
    finally:
        lib.close()
    copy = main / ".claude" / "worktrees" / "ticket-12"
    _git(main, "worktree", "add", "-q", str(copy))
    return main, copy


# ── recognising a copy ───────────────────────────────────────────────────

def test_a_worktree_leads_back_to_its_main_tree(repo):
    from rtfm.core.placement import worktree_copy_root, worktree_main_root
    main, copy = repo
    assert worktree_main_root(copy) == main.resolve()
    assert worktree_main_root(copy / "un" / "sous-dossier") == main.resolve()
    assert worktree_copy_root(copy) == copy.resolve()


def test_the_main_tree_and_plain_directories_are_not_copies(repo, tmp_path):
    from rtfm.core.placement import worktree_main_root
    main, _ = repo
    assert worktree_main_root(main) is None
    plain = tmp_path / "ailleurs"
    plain.mkdir()
    assert worktree_main_root(plain) is None


def test_a_submodule_is_not_a_copy(tmp_path):
    """A submodule has a ``.git`` file too, but it leads to no commondir."""
    from rtfm.core.placement import worktree_main_root
    sub = tmp_path / "sous-module"
    sub.mkdir()
    modules = tmp_path / ".git" / "modules" / "sous-module"
    modules.mkdir(parents=True)
    (sub / ".git").write_text(f"gitdir: {modules}\n")
    assert worktree_main_root(sub) is None


# ── starting a session there writes nothing ──────────────────────────────

def test_the_session_start_leaves_the_copy_clean(repo, monkeypatch):
    import hooks.rtfm_bootstrap as bootstrap
    from rtfm.core import registry
    main, copy = repo
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(copy))
    monkeypatch.setattr(bootstrap, "_init_project",
                        lambda root: pytest.fail("a copy must not be indexed"))
    bootstrap.main()
    assert not (copy / ".rtfm").exists()
    assert not (copy / ".claude").exists()
    assert (copy / "CLAUDE.md").read_text() == "# Projet\n\nConsignes.\n"
    status = subprocess.run(["git", "status", "--porcelain"], cwd=copy,
                            capture_output=True, text=True).stdout
    assert status == ""
    assert not registry.is_enrolled(copy / ".rtfm")


def test_an_edit_in_the_copy_queues_nothing(repo, monkeypatch):
    """Even where a .rtfm/ exists in the copy — left behind by an older
    version — the edit hooks leave it alone."""
    import io
    import json
    import hooks.rtfm_record_edit as record
    main, copy = repo
    (copy / ".rtfm").mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(copy))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"tool_input": {"file_path": str(copy / "moteur.md")}})))
    record.main()
    assert not (copy / ".rtfm" / "touched_files.tmp").exists()


def test_the_server_log_creates_no_directory(tmp_path, monkeypatch):
    import rtfm.log as logmod
    monkeypatch.setattr(logmod, "_log_file", None)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RTFM_DB", ".rtfm/library.db")
    logmod.log("server", "starting")
    assert not (tmp_path / ".rtfm").exists()


# ── searching from the copy ──────────────────────────────────────────────

@pytest.fixture
def server_in_copy(repo, monkeypatch):
    import rtfm.mcp as mcp_mod
    main, copy = repo
    monkeypatch.chdir(copy)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(copy))
    monkeypatch.setenv("RTFM_DB", ".rtfm/library.db")     # what the plugin sets
    monkeypatch.setattr(mcp_mod, "_library", None)
    monkeypatch.setattr(mcp_mod, "_foreign", {})
    yield mcp_mod
    if mcp_mod._library is not None:
        mcp_mod._library.close()
    mcp_mod._library = None


def _tool(mcp_mod, name):
    tool = getattr(mcp_mod, name)
    return getattr(tool, "fn", tool)


def test_search_answers_from_the_main_index_read_only(server_in_copy, repo):
    main, copy = repo
    lib = server_in_copy._get_library()
    assert lib.read_only
    assert lib.db_path.resolve() == (main / ".rtfm" / "library.db").resolve()
    found = _tool(server_in_copy, "rtfm_search")("planificateur scenes", limit=3)
    assert "moteur.md" in found
    assert not (copy / ".rtfm").exists()


def test_results_point_into_the_copy(server_in_copy, repo):
    """Paths under the main tree would send the agent to edit files that
    are not its own — read-only in the sandbox, someone else's outside it."""
    main, copy = repo
    found = _tool(server_in_copy, "rtfm_search")("planificateur scenes", limit=3)
    assert str(copy.resolve() / "moteur.md") in found
    assert str(main.resolve() / "moteur.md") not in found


def test_reading_a_file_by_its_path_in_the_copy_works(server_in_copy, repo):
    main, copy = repo
    text = _tool(server_in_copy, "rtfm_expand")(str(copy.resolve() / "moteur.md"))
    assert "planificateur" in text


def test_a_file_the_agent_changed_reads_as_its_own_version(server_in_copy, repo):
    """The main index does not know the agent's edits; reading goes to the
    copy's file, so the agent sees what it wrote."""
    main, copy = repo
    (copy / "moteur.md").write_text("# Moteur\n\nLe planificateur reecrit par l'agent.\n" * 10)
    text = _tool(server_in_copy, "rtfm_expand")(str(copy.resolve() / "moteur.md"))
    assert "reecrit par l'agent" in text


def test_nothing_is_queued_into_the_main_index(server_in_copy, repo):
    from rtfm.core.queue import Queue
    main, copy = repo
    _tool(server_in_copy, "rtfm_search")("rien ne correspond zzzz", limit=3)
    q = Queue(str(main / ".rtfm" / "library.db"))
    try:
        assert q.list_pending(limit=100) == []
    finally:
        q.close()


def test_a_read_only_main_tree_is_still_searchable(server_in_copy, repo):
    """The sandbox: everything outside the copy is read-only."""
    main, copy = repo
    rtfm_dir = main / ".rtfm"
    os.chmod(rtfm_dir, 0o555)
    try:
        found = _tool(server_in_copy, "rtfm_search")("planificateur scenes", limit=3)
        assert "moteur.md" in found
    finally:
        os.chmod(rtfm_dir, 0o755)


def test_an_unindexed_main_tree_is_said_plainly(tmp_path, monkeypatch):
    import rtfm.mcp as mcp_mod
    main = tmp_path / "depot"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    (main / "a.md").write_text("a\n")
    _git(main, "add", ".")
    _git(main, "commit", "-q", "-m", "init")
    copy = tmp_path / "copie"
    _git(main, "worktree", "add", "-q", str(copy))
    monkeypatch.chdir(copy)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(copy))
    monkeypatch.setenv("RTFM_DB", ".rtfm/library.db")
    monkeypatch.setattr(mcp_mod, "_library", None)
    with pytest.raises(mcp_mod.NoIndexHere, match="worktree"):
        mcp_mod._get_library()
    assert not (copy / ".rtfm").exists()
