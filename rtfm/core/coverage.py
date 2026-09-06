"""How much of a project the index actually holds.

An agent that reads a partial index and answers as if it were complete is
the failure this measure exists to prevent, so people build one themselves:
count the books, count the files in the tree, divide. That denominator is
wrong in the alarming direction — it counts logs, lock files, state files,
build output, everything the scan is deliberately not looking at — and a
workshop of agents ends up shown a number saying they are far more full of
holes than they are.

The scan already knows the right denominator: it is the list it builds. So
coverage is measured with the same walk, the same exclusions and the same
configuration a real scan uses. What it reports is a fact about this index,
not an estimate: *of the files RTFM considers its business here, this many
are readable in it.*
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SourceCoverage:
    """One configured source directory."""
    corpus: str
    root: str
    indexable: int = 0          # files a scan of this root would list
    readable: int = 0           # of those, files with content in the index
    tracked_not_readable: int = 0   # seen, recorded, nothing behind them
    missing: int = 0            # indexable, never seen by any scan
    error: str = ""

    @property
    def ratio(self) -> float:
        return (self.readable / self.indexable) if self.indexable else 1.0


@dataclass
class Coverage:
    sources: list[SourceCoverage] = field(default_factory=list)
    #: Entries in the catalogue whose file no scan of these roots would list
    #: — typically indexed from a directory no longer configured.
    unaccounted: int = 0

    @property
    def indexable(self) -> int:
        return sum(s.indexable for s in self.sources)

    @property
    def readable(self) -> int:
        return sum(s.readable for s in self.sources)

    @property
    def ratio(self) -> float:
        return (self.readable / self.indexable) if self.indexable else 1.0

    def one_line(self) -> str:
        """The sentence to show above an answer built on this index."""
        if not self.sources:
            return "coverage: no source directory configured"
        pct = 100.0 * self.ratio
        text = (f"coverage: {self.readable}/{self.indexable} indexable "
                f"file(s) readable ({pct:.1f}%)")
        gaps = []
        blind = sum(s.tracked_not_readable for s in self.sources)
        late = sum(s.missing for s in self.sources)
        if late:
            gaps.append(f"{late} not indexed yet")
        if blind:
            gaps.append(f"{blind} indexed with nothing readable")
        return text + (f" — {', '.join(gaps)}" if gaps else "")


def measure(root: Path, db_path: Optional[Path] = None) -> Coverage:
    """Measure coverage of the project rooted at *root*.

    Walks each configured source exactly the way a scan does, then asks the
    index what it holds for the files that walk produced.
    """
    from rtfm.config import load_config
    from rtfm.core.library import Library
    from rtfm.core.sync import scan_directory

    db_path = db_path or (root / ".rtfm" / "library.db")
    cov = Coverage()
    lib = Library(db_path, create=False)
    try:
        conn = lib._get_conn()
        cfg = load_config(root)
        sources = cfg.get("sources") or [
            {"path": str(root), "corpus": cfg.get("corpus", "default")}]

        seen_paths: set[tuple[str, str]] = set()
        for src in sources:
            corpus = src.get("corpus") or "default"
            src_root = Path(src.get("path") or root).expanduser()
            entry = SourceCoverage(corpus=corpus, root=str(src_root))
            cov.sources.append(entry)
            try:
                exts = src.get("extensions") or cfg.get("extensions")
                ext_set = None
                if exts:
                    ext_set = {e if e.startswith(".") else f".{e}"
                               for e in (exts.split(",") if isinstance(exts, str)
                                         else exts)}
                files = scan_directory(
                    src_root,
                    extensions=ext_set,
                    honor_gitignore=src.get("honor_gitignore",
                                            cfg.get("honor_gitignore", True)),
                    include=src.get("include") or cfg.get("include"),
                    exclude=src.get("exclude") or cfg.get("exclude"),
                )
            except OSError as exc:
                entry.error = str(exc)
                continue

            rels = []
            for f in files:
                try:
                    rels.append(str(f.relative_to(src_root)))
                except ValueError:
                    rels.append(str(f))
            entry.indexable = len(rels)

            # One question per batch rather than one per file: a source of
            # 30 000 files must not cost 30 000 round trips.
            readable = tracked = 0
            for i in range(0, len(rels), 400):
                batch = rels[i:i + 400]
                marks = ",".join("?" * len(batch))
                rows = conn.execute(
                    f"""SELECT i.filepath,
                               (SELECT 1 FROM books b
                                 WHERE b.slug = i.book_slug
                                   AND b.corpus = i.corpus) AS has_content
                        FROM indexed_files i
                        WHERE i.corpus = ? AND i.filepath IN ({marks})""",
                    (corpus, *batch)).fetchall()
                for row in rows:
                    tracked += 1
                    if row["has_content"]:
                        readable += 1
                    seen_paths.add((corpus, row["filepath"]))
            entry.readable = readable
            entry.tracked_not_readable = tracked - readable
            entry.missing = entry.indexable - tracked

        total_tracked = conn.execute(
            "SELECT COUNT(*) FROM indexed_files").fetchone()[0]
        cov.unaccounted = max(0, total_tracked - len(seen_paths))
    finally:
        lib.close()
    return cov
