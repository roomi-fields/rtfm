"""Every ``.gitignore`` of a source counts, and a file it leaves out leaves.

Only the root ``.gitignore`` used to be read. A ticket tracker that keeps
its own ``.gitignore`` beside its database had that database's internals
indexed anyway — rewritten at every ticket operation, re-indexed hundreds of
times a day. And a file indexed before a rule appeared stayed in the index:
a build cache ignored by git kept 1,678 files searchable, because the scan
only removed what had left the disk.
"""
from __future__ import annotations

import os
import sqlite3

import pytest

from rtfm.core.sync import IgnoreRules, confirm_removals, scan_directory


def _write(root, rel, text="# titre\n\ndu texte lisible\n"):
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")


def _found(root, **kw):
    return {p.relative_to(root).as_posix() for p in scan_directory(root, **kw)}


# ── the rules ────────────────────────────────────────────────────────────

def test_a_gitignore_in_a_subdirectory_counts(tmp_path):
    _write(tmp_path, "docs/guide.md")
    _write(tmp_path, ".beads/.gitignore", "embeddeddolt/\nlast-touched\n")
    _write(tmp_path, ".beads/embeddeddolt/noms/manifest")
    _write(tmp_path, ".beads/last-touched")
    _write(tmp_path, ".beads/issues.jsonl")
    assert _found(tmp_path) == {"docs/guide.md", ".beads/.gitignore",
                                ".beads/issues.jsonl"}


def test_its_patterns_are_relative_to_its_directory(tmp_path):
    _write(tmp_path, "a/.gitignore", "/out.md\n")
    _write(tmp_path, "a/out.md")
    _write(tmp_path, "out.md")
    _write(tmp_path, "a/b/out.md")
    assert _found(tmp_path) == {"a/.gitignore", "out.md", "a/b/out.md"}


def test_a_deeper_file_can_bring_one_back(tmp_path):
    _write(tmp_path, ".gitignore", "*.log\n")
    _write(tmp_path, "logs/.gitignore", "!garder.log\n")
    _write(tmp_path, "logs/garder.log")
    _write(tmp_path, "logs/jeter.log")
    assert _found(tmp_path) == {".gitignore", "logs/.gitignore", "logs/garder.log"}


def test_nothing_comes_back_from_inside_an_ignored_directory(tmp_path):
    """As in git: an ignored directory is not looked into."""
    _write(tmp_path, ".gitignore", "cache/\n")
    _write(tmp_path, "cache/.gitignore", "!*\n")
    _write(tmp_path, "cache/x.md")
    assert _found(tmp_path) == {".gitignore"}


def test_the_scan_does_not_enter_a_directory_a_nested_rule_leaves_out(
        tmp_path, monkeypatch):
    _write(tmp_path, "src/a.md")
    _write(tmp_path, "tool/.gitignore", "db/\n")
    _write(tmp_path, "tool/db/deep/x.md")
    entered = []
    real_walk = os.walk

    def spying_walk(top, *a, **k):
        for here, dirs, names in real_walk(top, *a, **k):
            entered.append(os.path.relpath(here, tmp_path))
            yield here, dirs, names

    monkeypatch.setattr(os, "walk", spying_walk)
    assert _found(tmp_path) == {"src/a.md", "tool/.gitignore"}
    assert not any(d.startswith("tool/db") for d in entered), entered


def test_honor_gitignore_off_reads_none_of_them(tmp_path):
    _write(tmp_path, "tool/.gitignore", "sortie/\n")
    _write(tmp_path, "tool/sortie/x.md")
    assert "tool/sortie/x.md" in _found(tmp_path, honor_gitignore=False)


def test_rtfmignore_still_applies_without_gitignore(tmp_path):
    _write(tmp_path, ".rtfmignore", "brouillons/\n")
    _write(tmp_path, "brouillons/x.md")
    assert IgnoreRules(tmp_path, honor_gitignore=False).ignored("brouillons/x.md")


# ── what was indexed before the rule ─────────────────────────────────────

def test_a_file_a_rule_now_leaves_out_is_removed_though_present(tmp_path):
    _write(tmp_path, ".gitignore", ".turbo/\n")
    _write(tmp_path, ".turbo/cache/a.json", "{}")
    confirmed, kept = confirm_removals(
        tmp_path, [".turbo/cache/a.json"], rules=IgnoreRules(tmp_path))
    assert confirmed == [".turbo/cache/a.json"] and kept == []


def test_without_a_rule_a_present_file_is_still_kept(tmp_path):
    """The guard against a glitchy scan stays: presence keeps a file."""
    _write(tmp_path, "notes.md")
    confirmed, kept = confirm_removals(
        tmp_path, ["notes.md"], rules=IgnoreRules(tmp_path))
    assert confirmed == [] and kept == ["notes.md"]


def test_an_unreadable_ignore_file_removes_nothing(tmp_path):
    _write(tmp_path, ".gitignore", "*.md\n")
    _write(tmp_path, "notes.md")
    os.chmod(tmp_path / ".gitignore", 0)
    try:
        if os.access(tmp_path / ".gitignore", os.R_OK):
            pytest.skip("running with rights that read anything")
        confirmed, kept = confirm_removals(
            tmp_path, ["notes.md"], rules=IgnoreRules(tmp_path))
        assert confirmed == [] and kept == ["notes.md"]
    finally:
        os.chmod(tmp_path / ".gitignore", 0o644)


@pytest.fixture
def project(tmp_path):
    from rtfm.core.library import Library
    from rtfm.core.sync import sync
    root = tmp_path / "projet"
    _write(root, "notes.md")
    _write(root, ".turbo/cache/manifest.md")
    db = root / ".rtfm" / "library.db"
    db.parent.mkdir(parents=True)
    lib = Library(str(db))
    try:
        sync(library=lib, root=root, corpus="default", generate_embeddings=False)
    finally:
        lib.close()
    assert _tracked(db) == {"notes.md", ".turbo/cache/manifest.md"}
    _write(root, ".gitignore", ".turbo/\n")
    return root, db


def _tracked(db):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return {r[0] for r in conn.execute("SELECT filepath FROM indexed_files")}
    finally:
        conn.close()


def test_the_direct_sync_takes_it_out(project):
    from rtfm.core.library import Library
    from rtfm.core.sync import sync
    root, db = project
    lib = Library(str(db))
    try:
        result = sync(library=lib, root=root, corpus="default",
                      generate_embeddings=False)
    finally:
        lib.close()
    assert result.removed == 1
    assert ".turbo/cache/manifest.md" not in _tracked(db)


class _Worker:
    def __init__(self, db_path):
        self.db_path = db_path
        self.lines: list[str] = []

    def _log(self, msg):
        self.lines.append(msg)


def _job(kind, payload):
    from rtfm.core.queue import Job
    return Job(id=1, type=kind, priority=10, payload=payload, status="running",
               created_at="", started_at=None, finished_at=None, error=None,
               attempts=1)


def _pending(db):
    from rtfm.core.queue import Queue
    q = Queue(str(db))
    try:
        return [j for j in q.list_pending(limit=1000)]
    finally:
        q.close()


def test_the_indexer_takes_it_out(project):
    from rtfm.core.handlers import handle_remove, handle_scan
    root, db = project
    worker = _Worker(db)
    handle_scan(_job("scan", {"root": str(root), "corpus": "default"}), worker)
    removes = [j for j in _pending(db) if j.type == "remove"]
    assert [j.payload["filepath"] for j in removes] == [".turbo/cache/manifest.md"]
    handle_remove(removes[0], worker)
    assert _tracked(db) == {"notes.md"}
    assert any("now ignored" in ln for ln in worker.lines)


def test_a_rule_taken_back_before_the_removal_keeps_the_file(project):
    from rtfm.core.handlers import handle_remove, handle_scan
    root, db = project
    worker = _Worker(db)
    handle_scan(_job("scan", {"root": str(root), "corpus": "default"}), worker)
    (root / ".gitignore").write_text("", encoding="utf-8")
    remove = next(j for j in _pending(db) if j.type == "remove")
    handle_remove(remove, worker)
    assert ".turbo/cache/manifest.md" in _tracked(db)
    assert any("still on disk, kept" in ln for ln in worker.lines)
