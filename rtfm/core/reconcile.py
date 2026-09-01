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
  3. **Empty passages** — a passage with no text at all. Search matches
     the document and the reader is handed nothing; the HTML parser
     produced them on markup that contained no text.
  4. **Untracked books** — a catalogue entry no scan follows. Indexing
     writes the book and its passages first, then the tracking row that
     says "this file is indexed": a worker that dies between the two —
     and this one died often, on a library that segfaults — leaves the
     book behind. From then on nothing refreshes it and nothing removes
     it, and it keeps answering searches with content that may have left
     the disk months ago. 6 283 of them across this fleet.
  5. **Fossil chunks** — a chunk whose ``chunk_id`` prefix no longer
     matches its book's current ``slug``. Left over from an old
     cross-corpus move where the book row was updated but the chunk
     rows kept their computed-at-parse-time ``chunk_id``. Downstream
     symptom: every future ingest of a file whose slug collides with
     the fossil's ``chunk_id`` fails with ``UNIQUE constraint failed:
     chunks.chunk_id``. Purging them lets the sync re-parse the file
     with the correct slug.

``reconcile()`` fixes all of them: purge orphans, purge fossils, re-queue
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

import errno
import sqlite3
from pathlib import Path
from typing import Callable, Optional


def purge_empty_chunks(conn: sqlite3.Connection) -> int:
    """Delete passages with no text at all.

    Search can match the document they belong to and then hand the reader
    nothing — the shape of "found it, cannot read it". They are written by a
    parser that produced noise; new ones are refused at the door now, and
    these are the ones already stored.
    """
    n = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE content IS NULL OR TRIM(content) = ''"
    ).fetchone()[0]
    if not n:
        return 0
    conn.execute(
        "DELETE FROM chunks WHERE content IS NULL OR TRIM(content) = ''")
    conn.execute(
        """UPDATE books SET chunk_count =
           (SELECT COUNT(*) FROM chunks WHERE chunks.book_id = books.id)""")
    conn.commit()
    return n


# Errors that say "no such file could exist here", as opposed to "this
# location cannot be read right now". The first is evidence of absence; the
# second never is, and mistaking one for the other is how an index gets
# deleted because a network share blinked.
_ABSENCE_ERRNOS = {errno.ENAMETOOLONG, errno.EINVAL, errno.ENOTDIR,
                   errno.ELOOP, errno.ENOENT}


def _find_under(roots, filename: str):
    """Return ``(root_holding_the_file, any_location_unreadable)``."""
    unreadable = False
    for root in roots:
        try:
            if (root / filename).exists():
                return root, unreadable
        except OSError as exc:
            if exc.errno not in _ABSENCE_ERRNOS:
                unreadable = True
    return None, unreadable


def untracked_books(conn: sqlite3.Connection) -> list:
    """Catalogue entries that no scan follows.

    A temporary index on the tracking table makes this a join instead of a
    correlated scan — on a 38 000-file index the naive form takes minutes,
    which is not something a periodic pass can afford.
    """
    conn.execute("DROP TABLE IF EXISTS temp.tracked_slugs")
    conn.execute("CREATE TEMP TABLE tracked_slugs AS "
                 "SELECT DISTINCT book_slug FROM indexed_files "
                 "WHERE book_slug IS NOT NULL")
    conn.execute("CREATE INDEX temp.tracked_slugs_i ON tracked_slugs(book_slug)")
    rows = conn.execute(
        """SELECT b.slug, b.filename, b.corpus FROM books b
           LEFT JOIN tracked_slugs t ON t.book_slug = b.slug
           WHERE t.book_slug IS NULL"""
    ).fetchall()
    conn.execute("DROP TABLE IF EXISTS temp.tracked_slugs")
    return rows


def repair_untracked_books(lib, queue, log) -> dict:
    """Re-attach or drop every catalogue entry no scan follows.

    Two outcomes, decided by the disk and nothing else:

    * the file is **there** — the entry is real but unfollowed, so an
      indexing job is queued; it rewrites the tracking row and the entry
      rejoins the fold;
    * the file is **gone** — the entry describes something that no longer
      exists and answers searches with it, so it goes, passages and all.

    A corpus whose source directories are unknown is left alone: absence
    cannot be established there, and this function never guesses. Those are
    reported by ``rtfm audit`` instead.
    """
    conn = lib._get_conn()
    rows = untracked_books(conn)
    if not rows:
        return {"reattached": 0, "dropped": 0, "undecidable": 0}

    roots: dict[str, list] = {}
    every_root: list[Path] = []
    for corpus, root_path in conn.execute(
            "SELECT corpus, root_path FROM sync_roots"):
        roots.setdefault(corpus, []).append(Path(root_path))
        every_root.append(Path(root_path))

    reattached = dropped = undecidable = 0
    to_index: list[dict] = []
    for row in rows:
        slug, filename, corpus = row[0], row[1] or "", row[2] or ""
        if not filename:
            undecidable += 1
            continue

        # A corpus renamed in the config leaves its old name behind with no
        # source directory. Those entries are not undecidable — they are
        # simply somewhere, or nowhere: look under every directory the
        # project knows before concluding anything.
        corpus_roots = roots.get(corpus) or every_root
        if not corpus_roots:
            undecidable += 1
            continue

        home, unreadable = _find_under(corpus_roots, filename)
        if unreadable and home is None:
            # A mount that went dark is not evidence that a file is gone.
            undecidable += 1
            continue

        if home is not None:
            # Re-attach *now*, in place: write the tracking row the crash
            # never wrote, pointing at the identity this document already
            # has. Queueing an indexing job alone was not enough — an
            # untracked file is given a fresh identity, so the job created a
            # second document and left this one orphaned exactly as before.
            # The empty hash guarantees the content is re-read.
            lib.update_indexed_file(
                filepath=filename, file_hash="", corpus=corpus,
                book_slug=slug, root_path=str(home))
            to_index.append({"root": str(home), "corpus": corpus,
                             "filepath": filename})
            reattached += 1
        else:
            lib.delete_book(slug)
            dropped += 1

    if to_index:
        queue.enqueue_many("ingest", to_index)

    if reattached or dropped or undecidable:
        log(f"reconcile: {len(rows)} book(s) no scan was following — "
            f"{reattached} re-indexed, {dropped} dropped (file gone), "
            f"{undecidable} left alone (source directory unknown)")
    return {"reattached": reattached, "dropped": dropped,
            "undecidable": undecidable}


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

        # 1bb. Purge passages with no text.
        empties = purge_empty_chunks(conn)
        if empties:
            _log(f"reconcile: purged {empties} empty passage(s) — findable "
                 f"and unreadable")

        # 1c. Re-attach or drop catalogue entries no scan follows.
        book_repair = repair_untracked_books(lib, queue, _log)

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
                "embed_jobs": embed_jobs,
                "books_reattached": book_repair["reattached"],
                "books_dropped": book_repair["dropped"],
                "books_undecidable": book_repair["undecidable"],
                "empty_chunks_purged": empties}
    finally:
        queue.close()
        lib.close()
