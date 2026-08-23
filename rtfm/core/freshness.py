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

#: How long a read may wait for its own repair before answering anyway.
#: A single-file re-ingest measured ~1.1 s end to end on a busy 25-project
#: machine, so a few seconds covers the ordinary case with room to spare;
#: anything slower (a large PDF, a saturated fleet) falls back to reporting
#: the drift rather than making the agent wait. ``0`` disables the wait and
#: restores report-only behaviour.
DEFAULT_REFRESH_WAIT_SECONDS = 3.0


def refresh_wait_seconds() -> float:
    """Read-repair budget, overridable with ``RTFM_FRESH_WAIT_SECONDS``."""
    raw = os.environ.get("RTFM_FRESH_WAIT_SECONDS")
    if raw is None:
        return DEFAULT_REFRESH_WAIT_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_REFRESH_WAIT_SECONDS


def indexer_is_running() -> bool:
    """Whether a supervisor exists to service the repair we are about to
    queue. Without one, waiting is pure latency for nothing."""
    try:
        from rtfm.core.supervisor import supervisor_running
        return supervisor_running() is not None
    except Exception:
        return False


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


def requeue(db_path: str, stale: Iterable[tuple[str, str, str]]) -> list[int]:
    """Queue a top-priority re-ingest for files found out of date.

    *stale* items are ``(root, corpus, relative_path)``. Best-effort: a
    queueing failure must never break the read that noticed the drift.

    Returns the ids of the jobs that will bring those files up to date —
    including a job already pending for the same file, which dedup refuses
    to duplicate but which the caller may still want to wait on.
    """
    jobs = [t for t in stale if t[0] and t[2]]
    if not jobs:
        return []
    try:
        import json

        from rtfm.core.queue import Queue, P_USER
        q = Queue(db_path)
        try:
            ids: list[int] = []
            for root, corpus, rel in jobs:
                payload = {"root": root, "corpus": corpus, "filepath": rel}
                job_id = q.enqueue("ingest", payload, priority=P_USER)
                if job_id is None:
                    # Dedup: an identical job is already waiting. Wait on it.
                    row = q._get_conn().execute(
                        "SELECT id FROM work_queue WHERE type='ingest' "
                        "AND payload = ? AND status IN ('pending','running')",
                        (json.dumps(payload, sort_keys=True),),
                    ).fetchone()
                    job_id = row[0] if row else None
                if job_id is not None:
                    ids.append(job_id)
            return ids
        finally:
            q.close()
    except Exception:
        return []


def pending_content_jobs(db_path: str) -> list[int]:
    """Ids of queued jobs that would change what a search can find.

    Read-time verification only sees files a search *returned*, so it cannot
    rescue the one case where the index is most obviously wrong: a query that
    finds nothing because the file that answers it has not been ingested yet.
    What it can do is notice that such work is already queued — the edit hook
    files it the moment an agent writes — and wait for it before concluding
    that nothing matches.

    Only ``ingest`` and ``remove``: those decide what exists in the index.
    Scans are excluded on purpose — a scan of a large corpus can run for
    minutes and is not something a reader should ever wait on.
    """
    import sqlite3
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        rows = conn.execute(
            "SELECT id FROM work_queue WHERE type IN ('ingest','remove') "
            "AND status IN ('pending','running')").fetchall()
        return [r[0] for r in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def catch_up(db_path: str, project_root: str, budget: float) -> bool:
    """Bring the index level with the disk before reporting an empty answer.

    The last gap read-time verification cannot see. A file changed by a shell
    command, a build step or a ``git checkout`` is not in any result to be
    checked, and no hook filed an ingest for it — so a query about its new
    contents finds nothing, and "nothing" reads as "this does not exist".

    Closing it needs an actual look at the disk, which used to be far too
    expensive to do on a read. It no longer is: since a scan skips untouched
    files by size and mtime, a pass over a source tree costs milliseconds
    (measured 0.04 s over 431 files, 0.15 s over 1 708). So an empty answer
    now buys one: scan at top priority, wait for it and for whatever it finds
    to be ingested, all inside *budget*.

    Returns ``True`` if the index moved and the query deserves a second look.
    """
    import time as _time

    deadline = _time.monotonic() + budget
    ids = pending_content_jobs(db_path)
    if ids:
        # Work is already queued — the edit hook files it the instant an
        # agent writes. Wait for that before doing anything more expensive.
        if wait_for(db_path, ids, deadline - _time.monotonic()):
            return True
        return False

    scan_ids = _enqueue_scans(db_path, project_root)
    if not scan_ids:
        return False
    if not wait_for(db_path, scan_ids, deadline - _time.monotonic()):
        return False
    # The scan only *discovers*; what it found still has to be ingested.
    # Finding nothing to wait for here does **not** mean nothing happened —
    # the ingest may simply have finished between the scan completing and
    # this poll. A completed scan is reason enough to ask the question
    # again; the query costs milliseconds, and treating the race as "no
    # change" is how a correct index still answers "nothing found".
    found = pending_content_jobs(db_path)
    if found:
        wait_for(db_path, found, deadline - _time.monotonic())
    return True


def _enqueue_scans(db_path: str, project_root: str) -> list[int]:
    """Queue a top-priority scan of every source of *project_root*.

    Deliberately refuses to guess. A scan carries the source's selection
    rules, and running one with the wrong rules — or against the wrong tree —
    would pull a whole unrelated directory into the index. So this only acts
    on a project whose configuration says what its sources are; anything
    else is left to the periodic scan, which has the same information.
    """
    try:
        import json

        from rtfm.config import build_scan_payload, load_config
        from rtfm.core.queue import Queue, P_USER

        if Path(db_path).parent.name != ".rtfm":
            return []
        cfg = load_config(project_root)
        sources = cfg.get("sources")
        if not sources:
            if not cfg.get("corpus"):
                return []
            sources = [{"path": str(project_root), "corpus": cfg["corpus"]}]

        q = Queue(db_path)
        try:
            ids = []
            for src in sources:
                payload = build_scan_payload(src, cfg)
                job_id = q.enqueue("scan", payload, priority=P_USER)
                if job_id is None:
                    row = q._get_conn().execute(
                        "SELECT id FROM work_queue WHERE type='scan' AND payload = ? "
                        "AND status IN ('pending','running')",
                        (json.dumps(payload, sort_keys=True),)).fetchone()
                    job_id = row[0] if row else None
                if job_id is not None:
                    ids.append(job_id)
            return ids
        finally:
            q.close()
    except Exception:
        return []


def wait_for(db_path: str, job_ids: Iterable[int], timeout: float,
             poll: float = 0.05) -> bool:
    """Block until *job_ids* leave the queue, or *timeout* elapses.

    This is how a read repairs itself instead of merely complaining: the
    reader queues the re-ingest at top priority and waits the second or so
    it takes, then answers from a correct index. The write still happens in
    the supervisor — the single-writer rule that keeps these databases from
    corrupting is not negotiable, and a reader must never take that role.

    Returns ``True`` if every job finished in time. ``False`` means the
    caller should answer with what it has, and say the file has drifted.
    """
    ids = [int(i) for i in job_ids]
    if not ids:
        return True
    import sqlite3
    import time as _time

    deadline = _time.monotonic() + timeout
    placeholders = ",".join("?" * len(ids))
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        while True:
            try:
                left = conn.execute(
                    f"SELECT COUNT(*) FROM work_queue WHERE id IN ({placeholders}) "
                    "AND status IN ('pending','running')", ids).fetchone()[0]
            except sqlite3.Error:
                return False
            if left == 0:
                return True
            if _time.monotonic() >= deadline:
                return False
            _time.sleep(poll)
    finally:
        conn.close()
