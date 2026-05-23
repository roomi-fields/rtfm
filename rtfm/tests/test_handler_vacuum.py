"""Tests for the P4 ``vacuum`` worker handler.

VACUUM reclaims free pages left by deleted rows. The handler must:
  * shrink the DB file when there are free pages to reclaim,
  * tolerate an empty payload (``{}``),
  * echo the optional ``"reason"`` payload field in its log line.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from rtfm.core.handlers import handle_ingest, handle_vacuum
from rtfm.core.library import Library
from rtfm.core.queue import Job


def _fake_worker(db_path: Path, logs: list[str] | None = None):
    """Minimal stand-in for ``rtfm.core.worker.Worker`` — handle_vacuum
    only touches ``worker.db_path`` and ``worker._log``."""
    log = logs.append if logs is not None else (lambda msg: None)
    return SimpleNamespace(db_path=db_path, _log=log)


def _make_md(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _ingest_job(root: Path, rel: str) -> Job:
    return Job(
        id=1, type="ingest", priority=1,
        payload={"root": str(root), "corpus": "test", "filepath": rel},
        status="running", created_at="", started_at=None,
        finished_at=None, error=None, attempts=1,
    )


def _vacuum_job(payload: dict | None = None) -> Job:
    return Job(
        id=99, type="vacuum", priority=4, payload=payload or {},
        status="running", created_at="", started_at=None,
        finished_at=None, error=None, attempts=1,
    )


def test_vacuum_reclaims_space_after_delete(tmp_path: Path):
    """Ingest a handful of files, wipe ``chunks`` to leave free pages,
    then VACUUM and confirm the file shrank."""
    root = tmp_path / "src"
    # A few non-trivial files so the DB actually grows before delete.
    body = "# Title\n\n" + ("Paragraph with some real content. " * 80) + "\n"
    for i in range(8):
        _make_md(root / f"doc{i}.md", body + f"\n\n## Section {i}\n\n" + body)

    db = tmp_path / "library.db"
    Library(str(db)).close()

    worker = _fake_worker(db)
    for i in range(8):
        handle_ingest(_ingest_job(root, f"doc{i}.md"), worker)

    # Force a writer checkpoint so WAL data lands in the main file —
    # otherwise the "before" size may not reflect what VACUUM rewrites.
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()

    size_before = db.stat().st_size

    # Leave a lot of free pages: nuke chunks + their embeddings + FTS.
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("DELETE FROM chunks")
        try:
            conn.execute("DELETE FROM chunks_fts")
        except sqlite3.OperationalError:
            pass  # FTS table may not exist on a minimal schema
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()

    size_after_delete = db.stat().st_size

    handle_vacuum(_vacuum_job(), worker)

    size_after_vacuum = db.stat().st_size
    assert size_after_vacuum < size_after_delete, (
        f"VACUUM should shrink the file: "
        f"before={size_before} after_delete={size_after_delete} "
        f"after_vacuum={size_after_vacuum}"
    )


def test_vacuum_handles_empty_payload(tmp_path: Path):
    """``Job(payload={})`` must run without error — vacuum is global,
    no payload fields are required."""
    db = tmp_path / "library.db"
    Library(str(db)).close()

    handle_vacuum(_vacuum_job({}), _fake_worker(db))  # must not raise


def test_vacuum_logs_reason_when_provided(tmp_path: Path):
    """An optional ``"reason"`` payload key is echoed in the log line —
    that's how operators know which trigger fired the vacuum."""
    db = tmp_path / "library.db"
    Library(str(db)).close()

    logs: list[str] = []
    worker = _fake_worker(db, logs)
    handle_vacuum(_vacuum_job({"reason": "after-big-remove"}), worker)

    assert any("after-big-remove" in line for line in logs), (
        f"reason should appear in the log line, got: {logs!r}"
    )
    assert any("vacuum done" in line for line in logs), (
        f"log line should announce vacuum, got: {logs!r}"
    )


def test_vacuum_default_reason_is_explicit(tmp_path: Path):
    """When no ``reason`` is provided, the log line says ``(explicit)``."""
    db = tmp_path / "library.db"
    Library(str(db)).close()

    logs: list[str] = []
    handle_vacuum(_vacuum_job({}), _fake_worker(db, logs))

    assert any("(explicit)" in line for line in logs), (
        f"default reason should be 'explicit', got: {logs!r}"
    )
