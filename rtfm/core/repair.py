"""Repairs an index cannot perform on itself during ordinary work.

A scan compares what is on disk against what it has recorded, and acts on
the difference. That is the right loop, and it is exactly why some defects
survive their own fix: a file whose recorded state is wrong but *stable*
never shows up as a difference, so the scan skips it for ever. Correcting
the code that produced the bad record changes nothing for the files that
already carry it.

What lives here is the other half of such a fix — a pass that goes back over
records already written and clears the ones a later version of the code can
no longer produce. Each is written to be safe to run on every start: it
finds nothing on an index that has already been repaired, and nothing on an
index that was never affected.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone() is not None


def find_shared_identities(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Files that answer to an identity another file also answers to.

    A file's identity comes from its path, and it used to stop at the first
    dot: ``-se.Alan``, ``-se.Alarm`` and ``-se.Ames`` all became ``-se``.
    Each one indexed overwrote the last, so all three were tracked, all
    three looked done, and only the third was readable.

    The derivation was fixed, but an identity is never recomputed for a path
    already tracked — that rule is what keeps a working index stable across
    upgrades — so every file indexed before the fix keeps its colliding one.
    Measured on a fleet weeks after the fix had shipped: 910 files in two
    projects, in groups of up to 126 files readable as a single document.

    Returns ``(corpus, filepath)`` for every file in a colliding group,
    including the one currently readable: its identity is wrong too, and
    re-deriving all of them together is what makes the group consistent.
    """
    if not _table_exists(conn, "indexed_files"):
        return []
    return [(r[0], r[1]) for r in conn.execute(
        """SELECT corpus, filepath FROM indexed_files
           WHERE book_slug IS NOT NULL
             AND (corpus, book_slug) IN (
                 SELECT corpus, book_slug FROM indexed_files
                 WHERE book_slug IS NOT NULL
                 GROUP BY corpus, book_slug HAVING COUNT(*) > 1)
           ORDER BY corpus, filepath""")]


def repair_shared_identities(
    db_path: Path,
    log: Callable[[str], None] | None = None,
) -> int:
    """Forget the affected files so the next scan re-derives their identities.

    Dropping the tracking rows is the whole repair: the files are still on
    disk, so the next scan sees them as newcomers and indexes them under the
    identity the current code derives, one each. The shared catalogue entry
    goes with them — keeping it would leave an entry no scan tracks, which
    the reconcile pass deletes anyway, at a moment of its choosing.

    Returns the number of files handed back to the scan. Zero on an index
    that has already been repaired, and on one that was never affected.
    """
    say = log or (lambda m: None)
    try:
        conn = sqlite3.connect(str(db_path), timeout=60)
    except sqlite3.Error as exc:
        say(f"identity repair: cannot open the index ({exc})")
        return 0
    try:
        affected = find_shared_identities(conn)
    except sqlite3.Error as exc:
        say(f"identity repair: cannot read the tracking ({exc})")
        conn.close()
        return 0
    conn.close()
    if not affected:
        return 0

    # The removal goes through the library rather than raw SQL: a catalogue
    # entry owns chunks, chapters, edges and a search index, and only one
    # place knows all of them.
    from rtfm.core.library import Library
    lib = Library(db_path)
    done = 0
    try:
        for corpus, filepath in affected:
            try:
                lib.remove_file(filepath, corpus)
                done += 1
            except Exception as exc:  # one bad row must not stop the pass
                say(f"identity repair: {filepath}: {exc}")
    finally:
        lib.close()

    say(f"identity repair: {done} file(s) shared an identity with another "
        f"and were readable as one document. Their tracking is cleared; the "
        f"next scan indexes each of them separately.")
    return done
