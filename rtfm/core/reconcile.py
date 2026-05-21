"""Database reconciliation — self-heal the index between live runs.

A live pipeline is never 100% consistent: interrupted syncs, re-ingests,
cross-corpus moves and the (historically FK-OFF) SQLite connection leave
two kinds of drift:

  1. **Orphan embeddings** — a chunk was deleted (re-ingest) but its
     ``chunk_embeddings`` row survived (no ON DELETE CASCADE). Wasted
     space; harmless to search (the JOIN excludes them) but worth GCing.
  2. **Un-embedded chunks** — a chunk exists with no embedding (an inline
     / --no-embeddings sync, or a move that didn't trigger a P2). This is
     the real problem: that content isn't semantically searchable.

``reconcile()`` fixes both: purge orphans, re-queue un-embedded chunks
as P2 jobs. It is **safe to run only at rest** — the worker calls it
while idle (empty queue ⇒ no in-flight re-ingest/move ⇒ no transient
orphans), and the CLI refuses to run it while the worker is busy.

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
        {orphans_purged, chunks_requeued, embed_jobs}

    - Purges orphan embeddings.
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
                "chunks_requeued": requeued,
                "embed_jobs": embed_jobs}
    finally:
        queue.close()
        lib.close()
