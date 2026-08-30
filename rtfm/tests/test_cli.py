"""Smoke tests for the queue-based CLI commands (0.16.x+).

Every mutating ``rtfm <cmd>`` becomes:

    1. Enqueue P0 (``P_USER``) jobs.
    2. ``ensure_worker_running``.
    3. Watch queue stats until drained.

These tests use ``--background`` so step 3 returns immediately, then
inspect ``work_queue`` directly to assert the right jobs landed at the
right priority. ``ensure_worker_running`` is mocked to avoid spawning a
real worker subprocess.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from rtfm.config import add_source
from rtfm.core.library import Library
from rtfm.core.queue import Queue, P_USER


@pytest.fixture
def rtfm_project(tmp_path, monkeypatch):
    """A minimal .rtfm/ project rooted at tmp_path, with the DB created."""
    rtfm_dir = tmp_path / ".rtfm"
    rtfm_dir.mkdir()
    db_path = rtfm_dir / "library.db"
    Library(str(db_path)).close()
    # Make sure nothing in the env points to a different DB.
    monkeypatch.delenv("RTFM_DB", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _run_cli(*argv):
    """Invoke ``rtfm.cli.main`` with the given argv. Returns the SystemExit
    code (or 0 if main() returned normally)."""
    from rtfm.cli import main

    # Patch at the source — each command imports ensure_worker_running
    # lazily inside the function body.
    with patch("rtfm.cli_worker.ensure_worker_running", return_value=42424):
        with patch("sys.argv", ["rtfm", *argv]):
            try:
                main()
            except SystemExit as exc:
                return int(exc.code) if exc.code is not None else 0
    return 0


def test_cmd_sync_enqueues_scan_jobs_at_p0(rtfm_project):
    """`rtfm sync --background` enqueues one P0 scan job per source."""
    docs = rtfm_project / "docs"
    docs.mkdir()
    (docs / "readme.md").write_text("# Hello")
    code = rtfm_project / "code"
    code.mkdir()
    (code / "main.py").write_text("def f(): pass\n")
    add_source(rtfm_project, str(docs), "docs", extensions=".md")
    add_source(rtfm_project, str(code), "code", extensions=".py")

    rc = _run_cli("sync", "--background")
    assert rc == 0

    q = Queue(str(rtfm_project / ".rtfm" / "library.db"))
    jobs = q.list_pending(limit=20)
    q.close()

    scans = [j for j in jobs if j.type == "scan"]
    assert len(scans) == 2, f"expected 2 scan jobs, got {[j.type for j in jobs]}"
    assert all(j.priority == P_USER for j in scans), \
        f"expected all P0 (={P_USER}), got priorities {[j.priority for j in scans]}"
    corpora = sorted(j.payload["corpus"] for j in scans)
    assert corpora == ["code", "docs"]


def test_cmd_sync_force_remove_propagates(rtfm_project):
    """`--force-remove` lands in every scan job's payload."""
    docs = rtfm_project / "docs"
    docs.mkdir()
    add_source(rtfm_project, str(docs), "docs")

    rc = _run_cli("sync", "--background", "--force-remove")
    assert rc == 0

    q = Queue(str(rtfm_project / ".rtfm" / "library.db"))
    jobs = q.list_pending(limit=10)
    q.close()
    scans = [j for j in jobs if j.type == "scan"]
    assert scans
    assert all(j.payload.get("force_remove") is True for j in scans)


def test_cmd_sync_dry_run_enqueues_nothing(rtfm_project, capsys):
    """`--dry-run` prints the plan but enqueues no jobs."""
    docs = rtfm_project / "docs"
    docs.mkdir()
    add_source(rtfm_project, str(docs), "docs")

    rc = _run_cli("sync", "--dry-run")
    assert rc == 0
    out = capsys.readouterr().out
    assert "dry-run" in out

    q = Queue(str(rtfm_project / ".rtfm" / "library.db"))
    jobs = q.list_pending(limit=10)
    q.close()
    assert not jobs, f"dry-run should enqueue nothing, got {jobs}"


def test_cmd_sync_files_enqueues_ingest_jobs(rtfm_project):
    """`--files` enqueues P0 ingest jobs instead of a scan."""
    docs = rtfm_project / "docs"
    docs.mkdir()
    f1 = docs / "a.md"
    f1.write_text("# A")
    add_source(rtfm_project, str(docs), "docs")

    rc = _run_cli("sync", "--background", "--files", str(f1))
    assert rc == 0

    q = Queue(str(rtfm_project / ".rtfm" / "library.db"))
    jobs = q.list_pending(limit=10)
    q.close()
    ingests = [j for j in jobs if j.type == "ingest"]
    assert len(ingests) == 1
    assert ingests[0].priority == P_USER
    assert ingests[0].payload["filepath"] == "a.md"


def test_cmd_gc_enqueues_reconcile_at_p0(rtfm_project):
    """`rtfm gc --background` enqueues exactly one P0 reconcile job."""
    rc = _run_cli("gc", "--background")
    assert rc == 0

    q = Queue(str(rtfm_project / ".rtfm" / "library.db"))
    jobs = q.list_pending(limit=10)
    q.close()
    reconciles = [j for j in jobs if j.type == "reconcile"]
    assert len(reconciles) == 1
    assert reconciles[0].priority == P_USER
    # Default --vacuum=False
    assert reconciles[0].payload.get("vacuum") is False


def test_cmd_gc_with_vacuum_flag(rtfm_project):
    """`rtfm gc --vacuum --background` propagates vacuum=True in payload."""
    rc = _run_cli("gc", "--vacuum", "--background")
    assert rc == 0

    q = Queue(str(rtfm_project / ".rtfm" / "library.db"))
    jobs = q.list_pending(limit=10)
    q.close()
    reconciles = [j for j in jobs if j.type == "reconcile"]
    assert len(reconciles) == 1
    assert reconciles[0].payload.get("vacuum") is True


def test_cmd_vacuum_enqueues_vacuum_at_p0(rtfm_project):
    """`rtfm vacuum --background` enqueues exactly one P0 vacuum job."""
    rc = _run_cli("vacuum", "--background")
    assert rc == 0

    q = Queue(str(rtfm_project / ".rtfm" / "library.db"))
    jobs = q.list_pending(limit=10)
    q.close()
    vacuums = [j for j in jobs if j.type == "vacuum"]
    assert len(vacuums) == 1
    assert vacuums[0].priority == P_USER


def test_cmd_doctor_enqueues_scan_and_reconcile_at_p0(rtfm_project):
    """`rtfm doctor --background` enqueues P0 scans + a P0 reconcile."""
    docs = rtfm_project / "docs"
    docs.mkdir()
    add_source(rtfm_project, str(docs), "docs")

    rc = _run_cli("doctor", "--background")
    assert rc == 0

    q = Queue(str(rtfm_project / ".rtfm" / "library.db"))
    jobs = q.list_pending(limit=20)
    q.close()
    types = sorted(j.type for j in jobs)
    assert "scan" in types
    assert "reconcile" in types
    assert all(j.priority == P_USER for j in jobs)


def test_cmd_queue_db_flag_and_truncation_notice(rtfm_project, capsys, monkeypatch):
    """`rtfm queue --db PATH list` inspects a queue addressed explicitly and,
    when truncated, honestly reports 'showing N of M' instead of stopping
    silently at the limit."""
    db = rtfm_project / ".rtfm" / "library.db"
    q = Queue(str(db))
    for i in range(25):
        q.enqueue("ingest", {"filepath": f"f{i:02d}.md", "corpus": "c"})
    q.close()

    # Address the DB from outside its tree via --db.
    monkeypatch.chdir(rtfm_project.parent)
    rc = _run_cli("queue", "--db", str(db), "list")
    assert rc == 0
    out = capsys.readouterr().out
    assert "showing 20 of 25 pending" in out

    # --limit 0 → all rows, no truncation notice.
    rc = _run_cli("queue", "--db", str(db), "--limit", "0", "list")
    out = capsys.readouterr().out
    assert "showing" not in out
    assert out.count("#") >= 25


def test_cmd_remove_source_exit_codes(rtfm_project, capsys):
    """`rtfm remove` exits non-zero when nothing matched, zero when it removed
    something — so a script can tell the two apart."""
    from rtfm.config import add_source, list_sources
    add_source(rtfm_project, "/some/where", "projets")

    # No match → non-zero.
    rc = _run_cli("remove", "--corpus", "ghost")
    assert rc != 0
    capsys.readouterr()

    # Real removal → zero, and the source is gone.
    rc = _run_cli("remove", "--corpus", "projets")
    assert rc == 0
    assert list_sources(rtfm_project) == []


class TestSearchFreshness:
    """`rtfm search` reads the same eventually-consistent index the MCP
    tools do — an agent shelling out to it must get the same guarantee."""

    def _project(self, tmp_path):
        from rtfm.core.library import Library
        from rtfm.core.sync import sync

        src = tmp_path / "src"
        src.mkdir()
        (src / "notes.md").write_text("# Notes\n\nconsciousness and attention.\n")
        lib = Library(tmp_path / "lib.db")
        sync(lib, src, corpus="default", generate_embeddings=False)
        lib.close()
        return src, str(tmp_path / "lib.db")

    def test_reports_a_source_that_drifted(self, tmp_path, capsys, monkeypatch):
        from rtfm.core import freshness

        src, db = self._project(tmp_path)
        monkeypatch.setattr(freshness, "indexer_is_running", lambda: False)
        (src / "notes.md").write_text("# Notes\n\nconsciousness, rewritten.\n")

        _run_cli("search", "consciousness", "--db", db)
        assert "modified since indexing" in capsys.readouterr().out

    def test_silent_when_the_index_is_current(self, tmp_path, capsys, monkeypatch):
        from rtfm.core import freshness

        src, db = self._project(tmp_path)
        monkeypatch.setattr(freshness, "indexer_is_running", lambda: False)

        _run_cli("search", "consciousness", "--db", db)
        out = capsys.readouterr().out
        assert "notes" in out
        assert "⚠" not in out


class TestFailedRetry:
    """Skipping a broken file must never mean forgetting it: once the cause
    is fixed (OCR installed, mount repaired), one command re-opens them."""

    def _db(self, tmp_path):
        from rtfm.core.library import Library

        db = tmp_path / "lib.db"
        lib = Library(db)
        lib.record_ingest_failure("a.pdf", "docs", "h1", 10, "boom")
        lib.record_ingest_failure("b.pdf", "docs", "h2", 10, "boom")
        lib.record_ingest_failure("c.md", "notes", "h3", 10, "boom")
        lib.close()
        return str(db)

    def test_retry_clears_everything(self, tmp_path, capsys):
        from rtfm.core.library import Library

        db = self._db(tmp_path)
        _run_cli("failed", "--retry", "--db", db)
        assert "cleared 3" in capsys.readouterr().out
        lib = Library(db)
        assert lib.list_ingest_failures() == {}
        lib.close()

    def test_retry_can_be_scoped_to_a_corpus(self, tmp_path, capsys):
        from rtfm.core.library import Library

        db = self._db(tmp_path)
        _run_cli("failed", "--retry", "--corpus", "docs", "--db", db)
        assert "cleared 2" in capsys.readouterr().out
        lib = Library(db)
        assert list(lib.list_ingest_failures()) == ["c.md"]
        lib.close()


class TestSourceSelectionRulesReachTheScan:
    """Regression cover for issue #6 — ``rtfm sync`` stored the user's
    ``--exclude`` patterns and then scanned without them, so every excluded
    file was indexed anyway, with no warning. The reporter lost 312 files to
    it on a 685-book index."""

    def _scan_payloads(self, project):
        q = Queue(str(project / ".rtfm" / "library.db"))
        jobs = q.list_pending(limit=20)
        q.close()
        return [j.payload for j in jobs if j.type == "scan"]

    def test_exclude_patterns_reach_the_scan_job(self, rtfm_project):
        docs = rtfm_project / "docs"
        docs.mkdir()
        add_source(rtfm_project, str(docs), "docs", extensions="md",
                   exclude=["data/*", ".agents/*"])

        assert _run_cli("sync", "--background") == 0

        payloads = self._scan_payloads(rtfm_project)
        assert payloads, "no scan job enqueued"
        assert payloads[0]["exclude"] == ["data/*", ".agents/*"]

    def test_include_patterns_reach_the_scan_job(self, rtfm_project):
        docs = rtfm_project / "docs"
        docs.mkdir()
        add_source(rtfm_project, str(docs), "docs", include=["*.bps", "-gr.*"])

        assert _run_cli("sync", "--background") == 0

        payloads = self._scan_payloads(rtfm_project)
        assert payloads[0]["include"] == ["*.bps", "-gr.*"]

    def test_narrowing_to_one_corpus_keeps_its_patterns(self, rtfm_project):
        """`rtfm sync --corpus docs` narrows *which* source runs, never
        which rules it runs with."""
        docs = rtfm_project / "docs"
        code = rtfm_project / "code"
        docs.mkdir()
        code.mkdir()
        add_source(rtfm_project, str(docs), "docs", exclude=["data/*"])
        add_source(rtfm_project, str(code), "code")

        assert _run_cli("sync", "--background", "--corpus", "docs") == 0

        payloads = self._scan_payloads(rtfm_project)
        assert len(payloads) == 1
        assert payloads[0]["corpus"] == "docs"
        assert payloads[0]["exclude"] == ["data/*"]

    def test_an_extension_override_still_honours_the_exclusions(
            self, rtfm_project):
        docs = rtfm_project / "docs"
        docs.mkdir()
        add_source(rtfm_project, str(docs), "docs", exclude=["data/*"])

        assert _run_cli("sync", "--background", "--corpus", "docs",
                        "--extensions", "md") == 0

        payloads = self._scan_payloads(rtfm_project)
        assert payloads[0]["extensions"] == "md"
        assert payloads[0]["exclude"] == ["data/*"]

    def test_the_sync_output_states_the_rules_it_applies(
            self, rtfm_project, capsys):
        """The failure was silent: an over-broad index looked exactly like a
        successful sync. The applied rules are now on screen."""
        docs = rtfm_project / "docs"
        docs.mkdir()
        add_source(rtfm_project, str(docs), "docs", extensions="md",
                   exclude=["data/*"])

        assert _run_cli("sync", "--background") == 0

        out = capsys.readouterr().out
        assert "ext=md" in out
        assert "exclude=data/*" in out


class TestRegisteringASourceGitIgnores:
    """`rtfm add --no-gitignore` — the option existed on `sync` only, so a
    corpus living in a git-ignored directory could not be registered
    without hand-editing config.json."""

    def test_the_flag_is_recorded_on_the_source(self, rtfm_project):
        from rtfm.config import list_sources

        pdfs = rtfm_project / "papers"
        pdfs.mkdir()
        assert _run_cli("add", str(pdfs), "--corpus", "papers",
                        "--no-gitignore") == 0
        assert list_sources(rtfm_project)[0]["honor_gitignore"] is False

    def test_without_the_flag_the_default_is_left_alone(self, rtfm_project):
        from rtfm.config import list_sources

        pdfs = rtfm_project / "papers"
        pdfs.mkdir()
        assert _run_cli("add", str(pdfs), "--corpus", "papers") == 0
        assert "honor_gitignore" not in list_sources(rtfm_project)[0]

    def test_the_rules_are_stored_as_patterns_not_as_one_string(
            self, rtfm_project):
        from rtfm.config import list_sources

        d = rtfm_project / "src"
        d.mkdir()
        assert _run_cli("add", str(d), "--corpus", "code",
                        "--exclude", "*.min.js,vendor/*") == 0
        assert list_sources(rtfm_project)[0]["exclude"] == [
            "*.min.js", "vendor/*"]
