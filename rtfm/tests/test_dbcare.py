"""Tests for the DB self-care primitives (:mod:`rtfm.core.dbcare`).

Covers the two hardening behaviours that turn silent runaways into bounded,
self-healing ones: corruption detection + quarantine, and log rotation.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from rtfm.core.dbcare import (
    check_integrity, quarantine_db, ensure_healthy_db,
    rotate_log_if_large, make_rotating_logger,
)


def _make_valid_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()


def test_check_integrity_healthy_and_missing(tmp_path: Path):
    db = tmp_path / "lib.db"
    _make_valid_db(db)
    assert check_integrity(db) is True
    # A missing DB is "healthy" — a fresh one will be created on first write.
    assert check_integrity(tmp_path / "nope.db") is True


def test_check_integrity_detects_corruption(tmp_path: Path):
    db = tmp_path / "lib.db"
    # A file that is not a SQLite database at all.
    db.write_bytes(b"this is definitely not a sqlite file" * 100)
    assert check_integrity(db) is False


def test_quarantine_moves_db_and_sidecars(tmp_path: Path):
    db = tmp_path / "lib.db"
    db.write_bytes(b"corrupt")
    (tmp_path / "lib.db-wal").write_bytes(b"wal")
    (tmp_path / "lib.db-shm").write_bytes(b"shm")

    dest = quarantine_db(db)
    assert dest is not None
    assert dest.exists()
    assert dest.name.startswith("lib.db.corrupt-")
    # Original path is now free for a fresh DB.
    assert not db.exists()
    # Sidecars followed the main file.
    assert (dest.with_name(dest.name + "-wal")).exists()
    assert (dest.with_name(dest.name + "-shm")).exists()
    assert not (tmp_path / "lib.db-wal").exists()


def test_quarantine_missing_is_noop(tmp_path: Path):
    assert quarantine_db(tmp_path / "absent.db") is None


def test_ensure_healthy_db_quarantines_and_signals_rebuild(tmp_path: Path):
    db = tmp_path / "lib.db"
    db.write_bytes(b"not a database" * 50)
    logs: list[str] = []
    rebuilt = ensure_healthy_db(db, log=logs.append)
    assert rebuilt is True                     # caller must re-index
    assert not db.exists()                     # corrupt file moved aside
    assert any("quarantined" in m for m in logs)
    # A fresh DB now opens cleanly in its place.
    _make_valid_db(db)
    assert check_integrity(db) is True


def test_ensure_healthy_db_noop_on_healthy(tmp_path: Path):
    db = tmp_path / "lib.db"
    _make_valid_db(db)
    assert ensure_healthy_db(db) is False
    assert db.exists()


def test_rotate_log_if_large(tmp_path: Path):
    log = tmp_path / "rtfm.log"
    log.write_text("x" * 100, encoding="utf-8")
    # Under the cap → no rotation.
    assert rotate_log_if_large(log, max_bytes=1000) is False
    assert log.exists()
    # Over the cap → rotate to .1 and free the main path.
    assert rotate_log_if_large(log, max_bytes=50) is True
    assert (tmp_path / "rtfm.log.1").exists()
    assert not log.exists()


def test_make_rotating_logger_appends_and_rotates(tmp_path: Path):
    log = tmp_path / "rtfm.log"
    write = make_rotating_logger(log, prefix="test", max_bytes=200)
    write("first message")
    assert log.exists()
    assert "first message" in log.read_text(encoding="utf-8")
    # Push it over the cap, then one more write triggers a rotation.
    write("y" * 300)
    write("after rotation")
    assert (tmp_path / "rtfm.log.1").exists()
    assert "after rotation" in log.read_text(encoding="utf-8")
