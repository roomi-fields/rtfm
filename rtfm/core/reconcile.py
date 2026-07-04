"""Database reconciliation — self-heal the index between live runs.

A live pipeline is never 100% consistent: interrupted syncs, re-ingests,
cross-corpus moves and the (historically FK-OFF) SQLite connection leave
three kinds of drift:

  1. **Orphan embeddings** — a chunk was deleted (re-ingest) but its
     ``chunk_embeddings`` row survived (no ON DELETE CASCADE). Wasted
     space; harmless to search (the JOIN excludes them) but worth GCing.
  2. **Un-embedded chunks** — a chunk exists with no embedding (an inline
     / --no-embeddings sync, or a move that didn't trigger a P2). This is
     the real problem: that content isn't semantically searchable.
  3. **Fossil chunks** — a chunk whose ``chunk_id`` prefix no longer
     matches its book's current ``slug``. Left over from an old
     cross-corpus move where the book row was updated but the chunk
     rows kept their computed-at-parse-time ``chunk_id``. Downstream
     symptom: every future ingest of a file whose slug collides with
     the fossil's ``chunk_id`` fails with ``UNIQUE constraint failed:
     chunks.chunk_id``. Purging them lets the sync re-parse the file
     with the correct slug.

``reconcile()`` fixes all three: purge orphans, purge fossils, re-queue
un-embedded chunks as P2 jobs. It is **safe to run only at rest** —
the worker calls it while idle (empty queue ⇒ no in-flight
re-ingest/move ⇒ no transient orphans), and the CLI refuses to run it
while the worker is busy.

Why an orphan is always safe to delete: a file *move* preserves chunk
ids (``move_file`` updates the book row, chunks follow by FK), so it
never produces an orphan. An orphan therefore only ever means "the
chunk is gone for good" — its embedding can't be reattached.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable, Optional


def count_orphan_embeddings(conn: sqlite3.Connection) -> int:
    return conn.execute(
        """SELECT COUNT(*) FROM chunk_embeddings e
           LEFT JOIN chunks c ON e.chunk_id = c.id
           WHERE c.id IS NULL"""
    ).fetchone()[0]


def purge_orphan_embeddings(conn: sqlite3.Connection) -> int:
    """Delete embeddings whose chunk no longer exists. Returns the count.
    Caller is responsible for only doing this at rest."""
    cur = conn.execute(
        """DELETE FROM chunk_embeddings
           WHERE chunk_id NOT IN (SELECT id FROM chunks)"""
    )
    conn.commit()
    return cur.rowcount


def count_fossil_chunks(conn: sqlite3.Connection) -> int:
    """Chunks whose ``chunk_id`` prefix no longer matches their book's
    current ``slug``. See module docstring, drift kind (3)."""
    return conn.execute(
        """SELECT COUNT(*) FROM chunks c
           JOIN books b ON b.id = c.book_id
           WHERE NOT (c.chunk_id LIKE b.slug || '%')"""
    ).fetchone()[0]


def purge_fossil_chunks(conn: sqlite3.Connection) -> int:
    """Delete fossil chunks and refresh ``books.chunk_count`` on the
    affected books so it stays consistent with the actual row count.
    Returns the number of chunks deleted."""
    cur = conn.execute(
        """DELETE FROM chunks
           WHERE id IN (
               SELECT c.id
               FROM chunks c
               JOIN books b ON b.id = c.book_id
               WHERE NOT (c.chunk_id LIKE b.slug || '%')
           )"""
    )
    deleted = cur.rowcount
    if deleted:
        # Recompute chunk_count for every book (cheap: one UPDATE with
        # a correlated subquery, no join fan-out).
        conn.execute(
            """UPDATE books SET chunk_count = (
                   SELECT COUNT(*) FROM chunks WHERE chunks.book_id = books.id
               )"""
        )
    conn.commit()
    return deleted


def count_unembedded_chunks(conn: sqlite3.Connection, model: str) -> int:
    return conn.execute(
        """SELECT COUNT(*) FROM chunks c
           LEFT JOIN chunk_embeddings e ON c.id = e.chunk_id AND e.model = ?
           WHERE e.id IS NULL""",
        (model,),
    ).fetchone()[0]


def reconcile(db_path: str | Path,
              embed_batch_size: int = 64,
              vacuum: bool = False,
              log: Optional[Callable[[str], None]] = None) -> dict:
    """Run one reconciliation pass. Returns a stats dict:
        {orphans_purged, fossils_purged, chunks_requeued, embed_jobs}

    - Purges orphan embeddings.
    - Purges fossil chunks (chunk_id prefix no longer matches book.slug).
    - Enqueues P2 embed jobs (batched) for every chunk missing an
      embedding for the active model.
    """
    from rtfm.core.library import Library
    from rtfm.core.queue import Queue
    from rtfm.core.embeddings import resolve_model, DEFAULT_MODEL

    _log = log or (lambda m: None)
    db_path = str(db_path)

    lib = Library(db_path)
    queue = Queue(db_path)
    try:
        conn = lib._get_conn()

        # 1. Purge orphan embeddings.
        n_orphans = count_orphan_embeddings(conn)
        purged = purge_orphan_embeddings(conn) if n_orphans else 0
        if purged:
            _log(f"reconcile: purged {purged} orphan embedding(s)")

        # 1b. Purge fossil chunks (mismatched chunk_id prefix). Also
        # cascade-updates books.chunk_count. Their books will be
        # re-populated on the next scan (empty books trigger a re-ingest).
        n_fossils = count_fossil_chunks(conn)
        fossils_purged = purge_fossil_chunks(conn) if n_fossils else 0
        if fossils_purged:
            _log(f"reconcile: purged {fossils_purged} fossil chunk(s) "
                 "(chunk_id / book.slug mismatch)")

        # 2. Re-queue un-embedded chunks.
        active = lib.get_active_embedding_model()
        model = resolve_model(active).hf_name if active else DEFAULT_MODEL
        missing = lib.chunk_ids_without_embedding()
        requeued = embed_jobs = 0
        if missing:
            batches = [missing[i:i + embed_batch_size]
                       for i in range(0, len(missing), embed_batch_size)]
            inserted, _ = queue.enqueue_many(
                "embed", [{"chunk_ids": b} for b in batches])
            embed_jobs = inserted
            requeued = len(missing)
            _log(f"reconcile: re-queued {requeued} un-embedded chunk(s) "
                 f"as {embed_jobs} P2 batch(es)")

        if vacuum and purged:
            # Reclaim the space freed by the purge. VACUUM needs no open
            # transaction; commit happened in purge.
            conn.execute("VACUUM")
            _log("reconcile: VACUUM done")

        return {"orphans_purged": purged,
                "fossils_purged": fossils_purged,
                "chunks_requeued": requeued,
                "embed_jobs": embed_jobs}
    finally:
        queue.close()
        lib.close()
