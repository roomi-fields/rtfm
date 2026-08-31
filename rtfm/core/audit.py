"""Invariants RTFM checks about itself, across every registered project.

Every serious defect this index has had was invisible to the test suite and
visible in the data: 819 tests passed while one project re-ingested a single
README 82 000 times, while 1 750 files silently never entered any index, and
while a corpus of PDFs was searchable but unreadable. They were all found the
same way — by someone noticing a symptom weeks later and then querying the
live databases.

That gap is what this module closes. Each check is a property that must hold
of a healthy index, expressed as SQL over the queue and the catalogue so it
costs milliseconds and can run on a schedule. A check that fires does not
prove a bug; it says "this cannot be right, look here".

Used by ``rtfm audit`` and by the supervisor, which runs the same checks
hourly and writes what they find into its log.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

# Telling a busy file from a loop.
#
# A file an agent appends to every few minutes is re-indexed dozens of times a
# day, and that is simply true — a check that flags it is a check nobody will
# read for long. Two signals separate the two cases:
#
#  * **Alternation.** A file being edited is only ever indexed. A file caught
#    between two scans is indexed *and removed*, over and over: that is the
#    delete/re-index loop, and nothing else produces it.
#  * **Sheer volume.** Cross-corpus theft produced no removals at all, only
#    indexing — 82 000 passes over one README. Above a hundred in a day,
#    whatever the reason, it is worth a line.
CHURN_ALTERNATION = 3
CHURN_THRESHOLD = 100
CHURN_WINDOW_HOURS = 24

# A claim held this long by nobody is stranded work, not slow work.
STRANDED_HOURS = 6


@dataclass
class Finding:
    project: str
    check: str
    count: int
    detail: str

    def __str__(self) -> str:
        return f"[{self.project}] {self.check}: {self.detail}"


@dataclass
class AuditReport:
    findings: list[Finding] = field(default_factory=list)
    projects: int = 0

    @property
    def clean(self) -> bool:
        return not self.findings

    def by_check(self) -> dict[str, list[Finding]]:
        out: dict[str, list[Finding]] = {}
        for f in self.findings:
            out.setdefault(f.check, []).append(f)
        return out


def _table_exists(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


# ── the checks ────────────────────────────────────────────────────────────
# Each takes an open read-only connection and returns (count, detail) or None.

def check_churn(conn) -> tuple[int, str] | None:
    """No file should be indexed over and over.

    Two scans that disagree about who owns a file will each undo the other,
    for ever, and nothing in the ordinary output says so — the queue simply
    never empties. This is the check that would have caught the delete/
    re-index loop in an hour instead of three weeks.
    """
    if not _table_exists(conn, "work_queue"):
        return None
    # Grouped in SQL, not in Python: a queue that has been churning holds
    # millions of rows, and the check has to stay cheap enough to run hourly.
    rows = conn.execute(
        """SELECT json_extract(payload, '$.corpus'),
                  json_extract(payload, '$.filepath'),
                  SUM(type = 'ingest') AS indexed,
                  SUM(type = 'remove') AS removed
           FROM work_queue
           WHERE type IN ('ingest', 'remove')
             AND created_at > datetime('now', ?)
           GROUP BY 1, 2
           HAVING (indexed >= ? AND removed >= ?) OR indexed >= ?
           ORDER BY indexed + removed DESC""",
        (f"-{CHURN_WINDOW_HOURS} hours",
         CHURN_ALTERNATION, CHURN_ALTERNATION, CHURN_THRESHOLD),
    ).fetchall()
    if not rows:
        return None
    corpus, filepath, indexed, removed = rows[0]
    how = (f"{indexed} indexings and {removed} removals" if removed
           else f"{indexed} indexings")
    return (len(rows),
            f"{len(rows)} file(s) churning in {CHURN_WINDOW_HOURS}h — "
            f"worst: [{corpus}] {filepath} ({how})")


def check_silent_drops(conn) -> tuple[int, str] | None:
    """A file RTFM refuses to index must be visible somewhere.

    Files that could not be parsed are remembered so scans stop re-proposing
    them — which also means nobody is told. When the reason is a defect in
    RTFM rather than in the file, they stay out of every index indefinitely.
    """
    if not _table_exists(conn, "ingest_failures"):
        return None
    n = conn.execute("SELECT COUNT(*) FROM ingest_failures").fetchone()[0]
    if not n:
        return None
    sample = conn.execute(
        "SELECT filepath, error FROM ingest_failures ORDER BY failed_at DESC "
        "LIMIT 1").fetchone()
    reason = (sample[1] or "").splitlines()[0][:70] if sample else ""
    return (n, f"{n} file(s) held out of the index — e.g. {sample[0]}: {reason}"
            if sample else f"{n} file(s) held out of the index")


def check_unreadable(conn) -> tuple[int, str] | None:
    """Every indexed passage must be readable back.

    A passage with neither line information nor stored text can be found by
    search and then not shown — which is what made a whole corpus of PDFs
    searchable but unreadable.
    """
    n = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE line_start IS NULL "
        "AND (content IS NULL OR content = '')").fetchone()[0]
    if not n:
        return None
    return (n, f"{n} passage(s) can be found but not read")


# One page holds about 3 000 characters — that is the median across 1 388
# correctly-paginated PDFs here, and the physics of a sheet of paper. Past
# 20 000, seven times that, the document is certainly not one page: it is a
# whole book flattened onto page 1 by the extraction bug fixed in 0.30.0.
#
# Counting passages instead would be wrong: a real one-page paper splits into
# two or three, and flagging those means crying wolf for ever on documents
# that are perfectly indexed.
PAGE_CHARS_IMPOSSIBLE = 20000


def check_pagination(conn) -> tuple[int, str] | None:
    """One page cannot hold a book."""
    n = conn.execute(
        "SELECT COUNT(*) FROM books WHERE page_count = 1 AND total_chars > ? "
        "AND (filename LIKE '%.pdf' OR filename LIKE '%.PDF')",
        (PAGE_CHARS_IMPOSSIBLE,)).fetchone()[0]
    if not n:
        return None
    return (n, f"{n} PDF(s) recorded as one page holding more text than a "
               f"page can — run `rtfm backfill-pages`")


def check_stranded(conn) -> tuple[int, str] | None:
    """A claimed job owes a closing write.

    A job left 'running' by a worker that died holds its slot for ever and
    nothing retries it.
    """
    if not _table_exists(conn, "work_queue"):
        return None
    n = conn.execute(
        "SELECT COUNT(*) FROM work_queue WHERE status = 'running' "
        f"AND started_at < datetime('now', '-{STRANDED_HOURS} hours')"
    ).fetchone()[0]
    if not n:
        return None
    return (n, f"{n} job(s) claimed over {STRANDED_HOURS}h ago and never "
               f"finished")


def check_orphan_books(conn) -> tuple[int, str] | None:
    """Catalogue and tracking must agree on what is indexed.

    A book with no tracking row is invisible to every scan: it is never
    refreshed and never removed, and it keeps answering searches with content
    that may no longer exist on disk.
    """
    if not _table_exists(conn, "indexed_files"):
        return None
    n = conn.execute(
        """SELECT COUNT(*) FROM books b
           WHERE NOT EXISTS (SELECT 1 FROM indexed_files i
                             WHERE i.book_slug = b.slug)"""
    ).fetchone()[0]
    if not n:
        return None
    return (n, f"{n} book(s) in the catalogue that no scan tracks")


def check_untracked_roots(conn, project_root: Path) -> tuple[int, str] | None:
    """Every configured source directory must be known to the index.

    A directory the index has never recorded is one whose files cannot be
    told apart from deleted ones — the shape of the loop that destroyed
    half a million rows.
    """
    if not _table_exists(conn, "sync_roots"):
        return None
    config = project_root / ".rtfm" / "config.json"
    if not config.exists():
        return None
    try:
        sources = json.loads(config.read_text(encoding="utf-8")).get("sources") or []
    except (ValueError, OSError):
        return None
    recorded = {(r[0], r[1]) for r in
                conn.execute("SELECT corpus, root_path FROM sync_roots")}
    missing = [s for s in sources
               if (s.get("corpus") or "default", s.get("path")) not in recorded]
    # A directory registered minutes ago has simply not been scanned yet.
    if not missing or not recorded:
        return None
    return (len(missing),
            f"{len(missing)} configured source(s) the index has never "
            f"recorded — e.g. {missing[0].get('path')}")


CHECKS = {
    "churn": check_churn,
    "silent-drops": check_silent_drops,
    "unreadable": check_unreadable,
    "pagination": check_pagination,
    "stranded": check_stranded,
    "orphan-books": check_orphan_books,
}


def audit_project(db_path: Path, project_root: Path | None = None) -> list[Finding]:
    """Run every check against one index. Read-only, milliseconds."""
    name = (project_root or db_path.parent.parent).name
    findings: list[Finding] = []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as exc:
        return [Finding(name, "unreadable-index", 1, f"cannot open: {exc}")]
    try:
        for check_name, fn in CHECKS.items():
            try:
                result = fn(conn)
            except sqlite3.Error as exc:
                findings.append(Finding(name, check_name, 1, f"check failed: {exc}"))
                continue
            if result:
                findings.append(Finding(name, check_name, result[0], result[1]))
        if project_root is not None:
            try:
                result = check_untracked_roots(conn, project_root)
            except sqlite3.Error:
                result = None
            if result:
                findings.append(
                    Finding(name, "untracked-roots", result[0], result[1]))
    finally:
        conn.close()
    return findings


def audit_fleet(registry: list[str] | None = None) -> AuditReport:
    """Run every check against every registered project."""
    if registry is None:
        from rtfm.core.supervisor import REGISTRY_PATH
        try:
            registry = json.loads(
                REGISTRY_PATH.read_text(encoding="utf-8"))["projects"]
        except (OSError, ValueError, KeyError):
            registry = []

    report = AuditReport()
    for entry in registry:
        rtfm_dir = Path(entry)
        db = rtfm_dir / "library.db"
        if not db.exists():
            continue
        report.projects += 1
        report.findings.extend(audit_project(db, rtfm_dir.parent))
    return report
