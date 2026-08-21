"""Tests for rtfm.plugin.hook_runtime — the edit hook's actual logic."""

import json

import pytest

from rtfm.config import add_source, save_config
from rtfm.core.library import Library
from rtfm.core.queue import P_USER, Queue
from rtfm.plugin.hook_runtime import _source_admits, match_source, on_file_edited


@pytest.fixture(autouse=True)
def no_supervisor(monkeypatch):
    """Keep the hook away from the real ~/.rtfm registry and supervisor —
    a test project must never end up being served for real."""
    import rtfm.cli_worker
    monkeypatch.setattr(rtfm.cli_worker, "ensure_worker_running", lambda d: None)


@pytest.fixture
def project(tmp_path):
    """A project with a real .rtfm/library.db so the hook engages."""
    (tmp_path / ".rtfm").mkdir()
    lib = Library(tmp_path / ".rtfm" / "library.db")
    lib.close()
    save_config(tmp_path, {"corpus": "default"})
    return tmp_path


def _pending(project):
    q = Queue(str(project / ".rtfm" / "library.db"))
    try:
        conn = q._get_conn()
        return [
            (row[0], row[1], json.loads(row[2]))
            for row in conn.execute(
                "SELECT type, priority, payload FROM work_queue WHERE status='pending'")
        ]
    finally:
        q.close()


def _edit(project, path, content="hello\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content) if isinstance(content, str) else path.write_bytes(content)
    on_file_edited(project, {"tool_input": {"file_path": str(path)}})


class TestSourceAdmits:
    def test_no_restrictor_takes_everything(self):
        assert _source_admits({}, "weird-file", "weird-file")

    def test_extensions_allow_list(self):
        src = {"extensions": ".py,.md"}
        assert _source_admits(src, "a.py", "a.py")
        assert not _source_admits(src, "a.bps", "a.bps")

    def test_include_pattern_admits_prefix_named_file(self):
        src = {"extensions": ".py", "include": ["-gr.*"]}
        assert _source_admits(src, "-gr.dhati", "data/-gr.dhati")

    def test_exclude_wins(self):
        src = {"exclude": ["*.min.js"]}
        assert not _source_admits(src, "app.min.js", "dist/app.min.js")

    def test_wildcard_extensions(self):
        assert _source_admits({"extensions": "*"}, "anything", "anything")


class TestMatchSource:
    def test_picks_deepest_matching_source(self, project):
        add_source(project, str(project), "root")
        add_source(project, str(project / "docs"), "docs")
        (project / "docs").mkdir()
        f = project / "docs" / "a.md"
        f.write_text("x")
        root, corpus = match_source(project, f)
        assert (root, corpus) == (project / "docs", "docs")

    def test_file_outside_every_source(self, project, tmp_path):
        add_source(project, str(project / "docs"), "docs")
        other = tmp_path / "elsewhere.md"
        other.write_text("x")
        assert match_source(project, other) is None


class TestOnFileEdited:
    def test_enqueues_at_user_priority(self, project):
        """An agent is about to read this back — it must not queue behind a
        background re-index wave."""
        _edit(project, project / "notes.md")
        jobs = _pending(project)
        assert len(jobs) == 1
        kind, priority, payload = jobs[0]
        assert kind == "ingest"
        assert priority == P_USER
        assert payload["filepath"] == "notes.md"

    def test_indexes_file_with_no_registered_parser(self, project):
        """0.27.0 indexes all text; the hook must not re-impose a parser
        allow-list, or exotic files stay invisible until the next scan."""
        _edit(project, project / "data" / "-gr.dhati", "grammar text\n")
        assert [p["filepath"] for _, _, p in _pending(project)] == ["data/-gr.dhati"]

    def test_skips_binary(self, project):
        _edit(project, project / "blob.dat", b"\x00\x01\x02binary")
        assert _pending(project) == []

    def test_skips_file_excluded_by_source_rules(self, project):
        save_config(project, {"corpus": "default", "sources": [
            {"path": str(project), "corpus": "default", "exclude": ["*.min.js"]}]})
        _edit(project, project / "app.min.js", "var a=1\n")
        assert _pending(project) == []

    def test_no_payload_path_is_a_noop(self, project):
        on_file_edited(project, {"tool_input": {}})
        assert _pending(project) == []

    def test_missing_db_is_a_noop(self, tmp_path):
        f = tmp_path / "x.md"
        f.write_text("x")
        on_file_edited(tmp_path, {"tool_input": {"file_path": str(f)}})  # no raise
