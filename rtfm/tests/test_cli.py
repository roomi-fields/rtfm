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
