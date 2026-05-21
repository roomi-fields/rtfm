"""Tests for the DB reconciliation (self-heal) routine."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rtfm.core.library import Library
from rtfm.core.queue import Queue
from rtfm.core.reconcile import (
    count_orphan_embeddings, purge_orphan_embeddings,
    count_unembedded_chunks, reconcile,
)


def _seed(db: Path):
    """Create a tiny DB with 3 chunks; chunk 1 has an embedding, chunk 2
    has an embedding whose chunk we then delete (orphan), chunk 3 has no
    embedding."""
    lib = Library(str(db))
    conn = lib._get_conn()
    conn.execute("INSERT INTO books (slug, title, corpus) VALUES ('b','B','c')")
    bid = conn.execute("SELECT id FROM books WHERE slug='b'").fetchone()["id"]
    for cid in (1, 2, 3):
        conn.execute(
            "INSERT INTO chunks (chunk_id, book_id, content, content_chars) "
            "VALUES (?, ?, ?, ?)", (f"ck{cid}", bid, f"content {cid}", 9))
    rows = conn.execute("SELECT id FROM chunks ORDER BY id").fetchall()
    ids = [r["id"] for r in rows]
    # embeddings for chunk ids[0] and ids[1]
    for cid in ids[:2]:
        conn.execute(
            "INSERT INTO chunk_embeddings (chunk_id, model, embedding) "
            "VALUES (?, 'm', ?)", (cid, b"\x00\x00\x00\x00"))
    conn.commit()
    return lib, ids


def test_orphan_created_when_chunk_deleted_without_fk(tmp_path):
    """With FK enforcement, deleting a chunk cascades. Simulate the
    historical orphan by deleting a chunk with FKs off."""
    db = tmp_path / "library.db"
    lib, ids = _seed(db)
    conn = lib._get_conn()
    # Force FK off to recreate the legacy orphan condition.
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM chunks WHERE id = ?", (ids[1],))
    conn.commit()
    assert count_orphan_embeddings(conn) == 1
    lib.close()


def test_purge_removes_only_orphans(tmp_path):
    db = tmp_path / "library.db"
    lib, ids = _seed(db)
    conn = lib._get_conn()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM chunks WHERE id = ?", (ids[1],))
    conn.commit()
    assert count_orphan_embeddings(conn) == 1
    purged = purge_orphan_embeddings(conn)
    assert purged == 1
    assert count_orphan_embeddings(conn) == 0
    # The live embedding (chunk ids[0]) survives.
    remaining = conn.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
    assert remaining == 1
    lib.close()


def test_fk_on_cascades_delete(tmp_path):
    """Regression for the fix: with PRAGMA foreign_keys=ON (the new
    default in _get_conn), deleting a chunk removes its embedding — no
    orphan is created in the first place."""
    db = tmp_path / "library.db"
    lib, ids = _seed(db)
    conn = lib._get_conn()  # FK ON by default now
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.execute("DELETE FROM chunks WHERE id = ?", (ids[0],))
    conn.commit()
    # The embedding for ids[0] was cascade-deleted → no orphan.
    assert count_orphan_embeddings(conn) == 0
    lib.close()


def test_count_unembedded_chunks(tmp_path):
    db = tmp_path / "library.db"
    lib, ids = _seed(db)
    conn = lib._get_conn()
    # chunk ids[2] has no embedding for model 'm'.
    assert count_unembedded_chunks(conn, "m") == 1
    lib.close()


def test_reconcile_purges_and_requeues(tmp_path):
    db = tmp_path / "library.db"
    lib, ids = _seed(db)
    conn = lib._get_conn()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM chunks WHERE id = ?", (ids[1],))  # make orphan
    conn.commit()
    lib.close()  # release before reconcile opens its own handles

    stats = reconcile(db)
    assert stats["orphans_purged"] == 1
    # chunk ids[2] (no embedding) re-queued; the deleted chunk doesn't count
    assert stats["chunks_requeued"] >= 1
    assert stats["embed_jobs"] >= 1

    # The embed jobs are really in the queue.
    q = Queue(str(db))
    try:
        pending = q.list_pending()
        assert any(j.type == "embed" for j in pending)
    finally:
        q.close()
