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


def find_tracked_binaries(conn: sqlite3.Connection,
                          roots_by_corpus: dict) -> list[tuple[str, str]]:
    """``(filepath, corpus)`` of tracked files nothing can read.

    A binary no parser claims used to be tracked — first with an identity,
    which made it look like a text file that went silent, then without one.
    Either way it cost a job on every change and sat in every check. It is
    no longer tracked at all; these are the ones recorded before.

    Only a file that is present and binary counts: a missing file proves
    nothing, and a mute *text* file is a genuine finding that stays.
    """
    from rtfm.core.sniff import unreadable_binary

    if not _table_exists(conn, "indexed_files"):
        return []
    found: list[tuple[str, str]] = []
    for corpus, rel, root, slug in conn.execute(
            """SELECT i.corpus, i.filepath, i.root_path, i.book_slug
               FROM indexed_files i
               WHERE i.book_slug IS NULL
                  OR NOT EXISTS (SELECT 1 FROM books b
                                 WHERE b.slug = i.book_slug
                                   AND b.corpus = i.corpus)""").fetchall():
        if not root:
            only = roots_by_corpus.get(corpus, set())
            root = next(iter(only)) if len(only) == 1 else None
        if not root:
            continue
        path = Path(root) / rel
        try:
            if path.is_file() and unreadable_binary(path):
                found.append((rel, corpus))
        except OSError:
            continue
    return found


def forget_tracked_binaries(
    db_path: Path,
    log: Callable[[str], None] | None = None,
) -> int:
    """Take out of the index the binaries tracked before. Idempotent."""
    say = log or (lambda m: None)
    try:
        conn = sqlite3.connect(str(db_path), timeout=60)
    except sqlite3.Error as exc:
        say(f"binary retirement: cannot open the index ({exc})")
        return 0
    try:
        roots: dict[str, set[str]] = {}
        if _table_exists(conn, "sync_roots"):
            for corpus, root in conn.execute(
                    "SELECT corpus, root_path FROM sync_roots").fetchall():
                if root:
                    roots.setdefault(corpus, set()).add(root)
        found = find_tracked_binaries(conn, roots)
    except sqlite3.Error as exc:
        say(f"binary retirement: {exc}")
        return 0
    finally:
        conn.close()
    if not found:
        return 0
    from rtfm.core.library import Library
    lib = Library(str(db_path))
    try:
        for rel, corpus in found:
            lib.remove_file(rel, corpus)
    finally:
        lib.close()
    say(f"binary retirement: {len(found)} binary file(s) nothing can read "
        f"taken out of the index")
    return len(found)


def _declared_roots(project_root: Path) -> dict[str, set[str]] | None:
    """Corpus → the roots the configuration declares for it, or ``None``
    when the configuration cannot be read with certainty.

    The same sources the scan uses: ``sources`` when present, else the
    project root under the configured corpus. Each root is kept both as
    written and resolved, since a scan records the resolved form.
    """
    import json
    import os

    config_path = project_root / ".rtfm" / "config.json"
    cfg: dict = {}
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(cfg, dict):
            return None
    sources = cfg.get("sources") or [
        {"path": str(project_root), "corpus": cfg.get("corpus", "default")}]
    declared: dict[str, set[str]] = {}
    for src in sources:
        if not isinstance(src, dict) or not src.get("path"):
            return None
        corpus = src.get("corpus") or cfg.get("corpus") or "default"
        path = os.path.expanduser(str(src["path"]))
        forms = {os.path.abspath(path)}
        try:
            forms.add(str(Path(path).resolve()))
        except (OSError, RuntimeError):
            pass
        declared.setdefault(corpus, set()).update(forms)
    return declared


def find_undeclared_files(conn: sqlite3.Connection,
                          declared: dict[str, set[str]]) -> list[tuple[str, str]]:
    """``(filepath, corpus)`` of tracked files no declared source covers.

    A tracked file only ever comes from scanning a declared source, so one
    whose corpus — or whose root within that corpus — is no longer declared
    belongs to a source that was removed. A file recorded without its root
    is judged on its corpus alone.
    """
    out: list[tuple[str, str]] = []
    for corpus, root, filepath in conn.execute(
            "SELECT corpus, root_path, filepath FROM indexed_files"):
        roots = declared.get(corpus)
        if roots is None or (root is not None and root not in roots):
            out.append((filepath, corpus))
    return out


def forget_undeclared_sources(
    db_path: Path,
    log: Callable[[str], None] | None = None,
) -> int:
    """Take out of the index what no declared source covers any more.

    Removing a source changed the configuration and nothing else: the scan
    stops looking at it, and what it had indexed stays — answering searches,
    duplicating files under an old corpus name, for good. One project kept
    four retired corpora, 597 files of which 359 a second time.

    Not run when the configuration cannot be read: an unreadable file says
    nothing about what is declared. Idempotent.
    """
    say = log or (lambda m: None)
    db_path = Path(db_path)
    declared = _declared_roots(db_path.parent.parent)
    if not declared:
        say("source retirement: configuration unreadable — left as it is")
        return 0
    try:
        conn = sqlite3.connect(str(db_path), timeout=60)
    except sqlite3.Error as exc:
        say(f"source retirement: cannot open the index ({exc})")
        return 0
    try:
        if not _table_exists(conn, "indexed_files"):
            return 0
        gone = find_undeclared_files(conn, declared)
        stale_roots = []
        if _table_exists(conn, "sync_roots"):
            stale_roots = [
                (corpus, root) for corpus, root in conn.execute(
                    "SELECT corpus, root_path FROM sync_roots").fetchall()
                if corpus not in declared or (root and root not in declared[corpus])]
            for corpus, root in stale_roots:
                conn.execute("DELETE FROM sync_roots WHERE corpus = ? "
                             "AND root_path IS ?", (corpus, root))
            conn.commit()
    finally:
        conn.close()
    if not gone:
        return 0

    from rtfm.core.library import Library
    lib = Library(str(db_path))
    try:
        for filepath, corpus in gone:
            lib.remove_file(filepath, corpus)
    finally:
        lib.close()
    corpora = sorted({c for _, c in gone})
    say(f"source retirement: {len(gone)} file(s) of sources no longer "
        f"declared taken out ({', '.join(corpora)})")
    return len(gone)


def requeue_unsplit_scans(
    db_path: Path,
    log: Callable[[str], None] | None = None,
) -> int:
    """Put back scanned books that timed out because they were read whole.

    A scan queued before its page count was known was read as one block,
    under the time budget of a single tranche, and long books failed — a
    failure that is never retried on its own. The reader now splits such a
    book before reading it, so these go back in the queue once and come out
    as tranches. Idempotent: a requeued row is no longer a failure.
    """
    import json

    say = log or (lambda m: None)
    try:
        conn = sqlite3.connect(str(db_path), timeout=60)
    except sqlite3.Error as exc:
        say(f"scan requeue: cannot open the index ({exc})")
        return 0
    try:
        if not _table_exists(conn, "work_queue"):
            return 0
        rows = conn.execute(
            "SELECT id, payload FROM work_queue WHERE type = 'ocr' "
            "AND status = 'failed' AND error LIKE '%timed out%'").fetchall()
        back = 0
        for job_id, payload in rows:
            try:
                if json.loads(payload).get("page_end") is not None:
                    continue  # a tranche: its own budget, a genuine timeout
            except ValueError:
                continue
            try:
                conn.execute(
                    "UPDATE work_queue SET status = 'pending', error = NULL, "
                    "started_at = NULL, finished_at = NULL, attempts = 0 "
                    "WHERE id = ?", (job_id,))
                back += 1
            except sqlite3.IntegrityError:
                conn.execute("DELETE FROM work_queue WHERE id = ?", (job_id,))
        conn.commit()
        if back:
            say(f"scan requeue: {back} scanned book(s) read whole and timed "
                f"out — queued again, to be read in tranches")
        return back
    finally:
        conn.close()
