"""Claude Code agents work in full copies of the repository.

They live under ``.claude/worktrees/``, one per agent, created when it starts
and deleted when it finishes. Indexed, every copy was read, embedded and then
removed again: on one project 11,064 of the day's 11,111 ingests came from
there, and the indexer kept two cores busy for ten days on content the index
already held under its real path.
"""
from __future__ import annotations

from rtfm.core.sync import confirm_removals, is_excluded_by_rule, scan_directory


def _write(root, rel, text="# titre\n\ndu texte\n"):
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")


def test_an_agent_copy_is_never_scanned(tmp_path):
    _write(tmp_path, "docs/guide.md")
    _write(tmp_path, ".claude/worktrees/agent-af58/docs/guide.md")
    found = {p.relative_to(tmp_path).as_posix() for p in scan_directory(tmp_path)}
    assert found == {"docs/guide.md"}


def test_the_rest_of_claude_stays_indexed(tmp_path):
    """Notes and agent definitions under ``.claude`` are real content."""
    _write(tmp_path, ".claude/napkin.md")
    _write(tmp_path, ".claude/agents/revue.md")
    found = {p.relative_to(tmp_path).as_posix() for p in scan_directory(tmp_path)}
    assert found == {".claude/napkin.md", ".claude/agents/revue.md"}


def test_a_worktrees_directory_elsewhere_is_not_touched(tmp_path):
    """The rule is the path, not the name."""
    _write(tmp_path, "docs/worktrees/usage.md")
    found = {p.relative_to(tmp_path).as_posix() for p in scan_directory(tmp_path)}
    assert found == {"docs/worktrees/usage.md"}


def test_copies_already_indexed_are_removed_even_while_present(tmp_path):
    """A path the rules exclude is a decision, not an absence: the copy still
    on disk must not hold its entry in the index."""
    rel = ".claude/worktrees/agent-af58/docs/guide.md"
    _write(tmp_path, rel)
    assert is_excluded_by_rule(rel)
    confirmed, kept = confirm_removals(tmp_path, [rel])
    assert confirmed == [rel] and kept == []
