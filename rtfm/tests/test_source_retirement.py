"""A source taken out of the configuration leaves the index with it.

Removing a source changed the configuration and nothing else: the scan
stopped looking at it, and what it had indexed stayed — answering searches,
duplicating files under an old corpus name. One project kept four retired
corpora, 597 files, 359 of them indexed a second time.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from rtfm.core.library import Library
from rtfm.core.repair import forget_undeclared_sources


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "projet"
    (root / ".rtfm").mkdir(parents=True)
    (root / "notes").mkdir()
    (root / "code").mkdir()
    return root


def _config(project, sources):
    (project / ".rtfm" / "config.json").write_text(
        json.dumps({"sources": sources}), encoding="utf-8")


def _track(project, filepath, corpus, root):
    lib = Library(str(project / ".rtfm" / "library.db"))
    lib.update_indexed_file(filepath, "h", corpus, filepath.replace("/", "-"),
                            root_path=str(root) if root else None)
    lib.close()


def _tracked(project):
    conn = sqlite3.connect(project / ".rtfm" / "library.db")
    rows = sorted(conn.execute("SELECT corpus, filepath FROM indexed_files"))
    conn.close()
    return rows


def test_a_retired_corpus_leaves_the_index(project):
    _config(project, [{"path": str(project / "notes"), "corpus": "notes"}])
    _track(project, "a.md", "notes", project / "notes")
    _track(project, "a.md", "ancien", project / "notes")
    assert forget_undeclared_sources(project / ".rtfm" / "library.db") == 1
    assert _tracked(project) == [("notes", "a.md")]


def test_a_directory_no_longer_declared_in_a_kept_corpus_leaves(project):
    _config(project, [{"path": str(project / "notes"), "corpus": "notes"}])
    _track(project, "a.md", "notes", project / "notes")
    _track(project, "b.py", "notes", project / "code")
    forget_undeclared_sources(project / ".rtfm" / "library.db")
    assert _tracked(project) == [("notes", "a.md")]


def test_a_file_recorded_without_its_root_is_judged_on_its_corpus(project):
    _config(project, [{"path": str(project / "notes"), "corpus": "notes"}])
    _track(project, "ancien.md", "notes", None)
    _track(project, "perdu.md", "retire", None)
    forget_undeclared_sources(project / ".rtfm" / "library.db")
    assert _tracked(project) == [("notes", "ancien.md")]


def test_a_declared_path_through_a_link_is_kept(project, tmp_path):
    """The scan records the resolved directory; the configuration may name
    it through a link."""
    link = tmp_path / "raccourci"
    link.symlink_to(project / "notes")
    _config(project, [{"path": str(link), "corpus": "notes"}])
    _track(project, "a.md", "notes", project / "notes")
    assert forget_undeclared_sources(project / ".rtfm" / "library.db") == 0


def test_without_a_configuration_the_project_itself_is_the_source(project):
    _track(project, "README.md", "default", project)
    _track(project, "vieux.md", "docs", project / "docs")
    forget_undeclared_sources(project / ".rtfm" / "library.db")
    assert _tracked(project) == [("default", "README.md")]


def test_an_unreadable_configuration_removes_nothing(project):
    (project / ".rtfm" / "config.json").write_text("{ pas du json", encoding="utf-8")
    _track(project, "a.md", "notes", project / "notes")
    assert forget_undeclared_sources(project / ".rtfm" / "library.db") == 0
    assert _tracked(project) == [("notes", "a.md")]


def test_the_retired_source_is_forgotten_as_a_root_too(project):
    _config(project, [{"path": str(project / "notes"), "corpus": "notes"}])
    lib = Library(str(project / ".rtfm" / "library.db"))
    lib.set_sync_root("notes", str(project / "notes"))
    lib.set_sync_root("ancien", str(project / "vieux"))
    lib.close()
    forget_undeclared_sources(project / ".rtfm" / "library.db")
    conn = sqlite3.connect(project / ".rtfm" / "library.db")
    assert [r[0] for r in conn.execute("SELECT corpus FROM sync_roots")] == ["notes"]
    conn.close()


def test_every_start_and_every_reconcile_run_it():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "core"
    for name in ("supervisor.py", "handlers.py"):
        assert "forget_undeclared_sources" in (root / name).read_text(encoding="utf-8"), name
