"""Read-time freshness verification.

RTFM's index is eventually consistent: a hook enqueues the file an agent
just wrote, a periodic scan catches everything else. Both are asynchronous,
so between the write and the re-ingest the index describes a file that no
longer exists in that form. An agent that searches in that window gets
answers about the past and has no way to know it — the failure mode this
module exists to remove.

The content RTFM serves is never stale (``rtfm_expand`` reads the real file
off disk). What lags is *findability* — a new symbol is not yet matchable,
a deleted one still matches — and *line ranges*, which drift as soon as
lines are inserted above a chunk.

So instead of racing to be fast, RTFM is **honest**: at read time it
compares each answered file against its disk state and says so when they
disagree, while queueing a top-priority re-ingest. Cost is one ``stat`` per
returned result (plus an MD5 for small files), i.e. nothing next to the
search itself.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

#: Above this size, trust size+mtime rather than reading the whole file.
#: Source files — the ones whose line ranges actually drift — are far below.
HASH_MAX_BYTES = 2 * 1024 * 1024

#: ``indexed_at`` is stamped *after* the file was read, so an untouched file
#: has ``mtime < indexed_at``. The margin below leans the *other* way from a
#: tolerance window: mtime is only believed when it is at least this far in
#: the past, so a file rewritten around the moment it was indexed — where
#: the two timestamps are indistinguishable — is re-read instead of trusted.
#: Erring this way costs a redundant MD5 on files touched in the last second
#: before indexing; erring the other way costs a wrong answer.
MTIME_CERTAINTY_MARGIN_SECONDS = 1.0

#: What a verdict means, in the words shown to the agent.
STALE = "modified since indexing"
GONE = "deleted since indexing"
NEW = "never indexed"


def _indexed_at_epoch(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        try:  # legacy "YYYY-MM-DD HH:MM:SS" rows
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            return None


def _mtime_is_older(st: os.stat_result, indexed_at: float) -> bool:
    """True when the file's mtime is safely older than the indexing stamp."""
    return st.st_mtime <= indexed_at - MTIME_CERTAINTY_MARGIN_SECONDS


def check_file(abs_path: str, tracked: Optional[dict]) -> Optional[str]:
    """Compare one file on disk with its ``indexed_files`` row.

    Returns :data:`STALE`, :data:`GONE`, :data:`NEW`, or ``None`` when the
    index is up to date for that file.
    """
    try:
        st = os.stat(abs_path)
    except OSError:
        return GONE if tracked else None
    if not tracked:
        return NEW

    size = tracked.get("file_size") or 0
    if size and st.st_size != size:
        return STALE

    indexed_at = _indexed_at_epoch(tracked.get("indexed_at"))
    if indexed_at is None or _mtime_is_older(st, indexed_at):
        return None

    # mtime moved: could be a touch/rewrite with identical bytes. For a file
    # small enough to read, the hash settles it exactly.
    tracked_hash = tracked.get("file_hash")
    if tracked_hash and st.st_size <= HASH_MAX_BYTES:
        from rtfm.core.sync import compute_file_hash
        try:
            if compute_file_hash(Path(abs_path)) == tracked_hash:
                return None
        except OSError:
            return None
    return STALE


def probably_unchanged(st: os.stat_result, tracked: Optional[dict]) -> bool:
    """True only when size *and* mtime both say the file was not touched.

    The conservative twin of :func:`check_file`, used by the scan to decide
    whether it can skip re-reading a file. Any doubt — no tracking row, a
    legacy row with no recorded size, an unparseable timestamp — answers
    ``False``, so the scan falls back to hashing. Skipping the hash for the
    (overwhelming) majority of untouched files is what makes a frequent scan
    affordable: without it every pass reads the entire corpus.
    """
    if not tracked:
        return False
    size = tracked.get("file_size") or 0
    if not size or st.st_size != size:
        return False
    indexed_at = _indexed_at_epoch(tracked.get("indexed_at"))
    if indexed_at is None:
        return False
    return _mtime_is_older(st, indexed_at)


def verify(lib, items: Iterable[tuple[str, str]]) -> dict[str, dict]:
    """Verify answered files against disk.

    *items* are ``(abs_path, indexed_filepath)`` pairs — the second being the
    path as stored in ``indexed_files`` (relative to its sync root). Returns
    ``{abs_path: {"verdict", "filepath", "corpus"}}`` for the files that
    disagree; a file that is up to date is simply absent from the result.
    """
    pairs = [(a, f) for a, f in items if a]
    if not pairs:
        return {}

    conn = lib._get_conn()
    tracked: dict[str, dict] = {}
    keys = sorted({f for _, f in pairs if f})
    for i in range(0, len(keys), 200):
        batch = keys[i:i + 200]
        rows = conn.execute(
            "SELECT filepath, file_hash, corpus, indexed_at, file_size "
            f"FROM indexed_files WHERE filepath IN ({','.join('?' * len(batch))})",
            batch,
        ).fetchall()
        for row in rows:
            tracked[row["filepath"]] = {
                "file_hash": row["file_hash"],
                "corpus": row["corpus"],
                "indexed_at": row["indexed_at"],
                "file_size": row["file_size"],
            }

    verdicts: dict[str, dict] = {}
    for abs_path, filepath in pairs:
        if abs_path in verdicts:
            continue
        row = tracked.get(filepath)
        verdict = check_file(abs_path, row)
        if verdict:
            verdicts[abs_path] = {
                "verdict": verdict,
                "filepath": filepath,
                "corpus": (row or {}).get("corpus"),
            }
    return verdicts


def requeue(db_path: str, stale: Iterable[tuple[str, str, str]]) -> int:
    """Queue a top-priority re-ingest for files found out of date.

    *stale* items are ``(root, corpus, relative_path)``. Best-effort: a
    queueing failure must never break the read that noticed the drift.
    Returns how many jobs were accepted (dedup drops the rest).
    """
    jobs = [t for t in stale if t[0] and t[2]]
    if not jobs:
        return 0
    try:
        from rtfm.core.queue import Queue, P_USER
        q = Queue(db_path)
        try:
            queued = 0
            for root, corpus, rel in jobs:
                if q.enqueue("ingest",
                             {"root": root, "corpus": corpus, "filepath": rel},
                             priority=P_USER):
                    queued += 1
            return queued
        finally:
            q.close()
    except Exception:
        return 0
