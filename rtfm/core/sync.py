"""Incremental sync: keep a rtfm Library in sync with a directory tree.

Usage::

    from rtfm.core.library import Library
    from rtfm.core.sync import sync

    lib = Library("project.db")
    result = sync(lib, root=".", corpus="my-project")
    print(result)  # SyncResult(added=3, modified=1, removed=0, moved=0, unchanged=42)
"""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Sequence

from rtfm.core.freshness import probably_unchanged
from rtfm.parsers.base import ParserRegistry

if TYPE_CHECKING:
    from rtfm.core.library import Library

# ── defaults ──────────────────────────────────────────────────────────────

# Fallback used only if the parser registry can't be queried (it always
# can in practice). The real default is every extension that has a
# registered parser — see ``default_extensions()``.
_FALLBACK_EXTENSIONS: set[str] = {
    ".md", ".txt", ".pdf", ".html", ".xml",
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".rs", ".go", ".java",
    ".sh", ".bash", ".zsh",
    ".css", ".toml", ".yaml", ".yml", ".cfg",
    ".c", ".cpp", ".h", ".rb", ".php",
    ".json", ".tex", ".latex",
}


def default_extensions() -> set[str]:
    """Every extension RTFM has a parser for.

    Derived from the parser registry so a newly-added parser is scanned
    automatically — no more silently-ignored formats. Previously this
    was a hand-maintained list of 27 extensions that omitted half the
    supported formats (csv, tsv, xlsx, sqlite, epub, docx, ipynb, …),
    so those files were never indexed unless a source declared them
    explicitly.
    """
    try:
        import rtfm.parsers  # noqa: F401 — ensure all parsers register
        from rtfm.parsers.base import ParserRegistry
        exts = {e.lower() for e in ParserRegistry.list_extensions()}
        return exts or set(_FALLBACK_EXTENSIONS)
    except Exception:
        return set(_FALLBACK_EXTENSIONS)


# Back-compat alias. Callers that imported the constant still work, but
# it's now the full registry-derived set computed at import time.
DEFAULT_EXTENSIONS: set[str] = default_extensions()

DEFAULT_EXCLUDE_DIRS: set[str] = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".tox", "dist", "build", ".egg-info", ".eggs",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "db",
    # RTFM's own state directory — indexing it creates a feedback loop
    # where library.db's content gets re-ingested as chunks every sync,
    # which grew some indexes to 8+ GB of pure recursion.
    ".rtfm",
    # Generic cache dirs are noise: import caches, browser caches, build
    # caches. Always many files, never load-bearing content.
    ".cache",
}


def _load_pathspec(path: Path):
    """Load a gitwildmatch PathSpec from *path*, or return None.

    Silent no-op when the file is missing, ``pathspec`` isn't installed,
    or the file is unreadable — the scan proceeds without that filter.
    """
    if not path.is_file():
        return None
    try:
        import pathspec  # type: ignore
    except ImportError:
        return None
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return pathspec.PathSpec.from_lines("gitwildmatch", f)
    except Exception:
        return None


def _load_gitignore_spec(root: Path):
    """Return a PathSpec matcher for the root-level .gitignore, or None.

    Honoring .gitignore means the user's already-declared "ignored
    artifacts" (build outputs, caches, generated files) don't need to be
    redeclared as RTFM excludes. Nested .gitignore files in subdirs are
    not walked — root-level only — which covers the vast majority of
    real-world setups while keeping the scan simple.
    """
    return _load_pathspec(root / ".gitignore")


def _load_rtfmignore_spec(root: Path):
    """Return a PathSpec matcher for the root-level .rtfmignore, or None.

    ``.rtfmignore`` is RTFM's own exclude list, always applied regardless
    of ``honor_gitignore``. Same syntax as ``.gitignore``
    (``gitwildmatch``). The intended use case is a project where a
    private corpus lives under a directory that ``.gitignore`` also
    covers: the user opts out of gitignore (``honor_gitignore: false``)
    to make the corpus visible, then declares a ``.rtfmignore`` to keep
    build outputs and caches out of the index. Also useful when a
    project should re-index files that git wants gone
    (e.g. generated docs) — leave ``.gitignore`` honored but override
    with ``.rtfmignore``.
    """
    return _load_pathspec(root / ".rtfmignore")

# ── mass-removal circuit breaker ────────────────────────────────────────────
# A full sync deletes every indexed file not seen on disk. That is only
# correct when the scan is trustworthy. On NTFS-via-WSL a mount hiccup, or an
# external process reorganising files mid-scan, can make scan_directory()
# return far fewer files than are indexed — and an unguarded sync then wipes
# books + chunks + the expensive embeddings for files that are merely
# temporarily absent (this destroyed ~500 PDFs once).
#
# The old guard was a blunt ratio circuit breaker: refuse the WHOLE removal
# batch when it was both large (>=25 files) and a big fraction (>=25%) of the
# corpus. It failed both ways — it refused genuine bulk deletions *forever*
# (repos that legitimately dropped 30-80% of a corpus had every removal
# refused on every scan, thousands of times, so the index diverged silently),
# yet it still could not tell a real deletion from a glitch. It is replaced by
# per-file confirmation (:func:`confirm_removals`): re-verify each removal
# against the live filesystem at removal time — remove a file only when it is
# genuinely absent AND a readable directory ancestor up to the scan root
# proves the location was really visited. A file that reappears on re-stat
# (transient scan miss) or whose mount went dark (root unreadable) is kept.
# Pass force_remove=True (or `rtfm sync --force-remove`) to skip the check for
# a deliberate bulk delete.


def build_disk_check(library, scanning_root: Path) -> "Callable[[str, str], bool]":
    """Return "is this tracked file still on disk *elsewhere* than here?".

    Used to gate cross-corpus moves. The directory currently being scanned is
    deliberately excluded: renaming a corpus keeps the same directory, so the
    old corpus's files are all still there, and counting them as present would
    turn a rename into a full re-ingestion — losing every embedding. Excluding
    it also gives the right answer for the case this gate exists for: content
    that lives under a *different* directory of another corpus has not moved,
    it is simply present in both.

    Errs on the side of *present*: an unreadable path (a mount that went dark)
    must never be read as "the file left this corpus", or the next scan hands
    its book, chunks and embeddings to whichever corpus holds the same bytes.
    """
    here = str(scanning_root)
    cache: dict[str, list[Path]] = {}

    def still_there(rel: str, corpus: str) -> bool:
        if corpus not in cache:
            try:
                cache[corpus] = [Path(r) for r in library.list_sync_roots(corpus)
                                 if r and r != here]
            except Exception:
                cache[corpus] = []
        for root in cache[corpus]:
            try:
                if (root / rel).exists():
                    return True
            except OSError:
                return True
        return False

    return still_there


def _sibling_roots(library, corpus: str, root: Path) -> list[Path]:
    """The other source directories of ``corpus`` — everything but ``root``.

    A corpus may gather several directories, and a stored path is relative to
    whichever one it came from. Scanning one of them must not read the others'
    files as deleted.
    """
    try:
        recorded = library.list_sync_roots(corpus)
    except Exception:
        return []
    here = str(root)
    return [Path(r) for r in recorded if r and r != here]


def _absence_is_proven(root: Path, rel: str) -> bool | None:
    """Under this one root: True if ``rel`` is genuinely gone, False if it is
    still there, None if the root proves nothing (unreadable, mount down).

    ``Path.exists``/``Path.is_dir`` swallow OSError and return ``False``, so a
    path on a mount that went dark reads as "absent" — hence the ancestor
    probe. If ``root`` itself is unreadable, absence is not evidence of
    deletion.
    """
    p = root / rel
    try:
        if p.exists():
            return False            # still present → transient scan miss, keep
    except OSError:
        return None                 # unreadable path → proves nothing
    anc = p.parent
    while True:
        try:
            if anc.is_dir():
                return True         # a readable ancestor exists → real deletion
        except OSError:
            return None
        if anc == root:
            return None             # root itself unreadable → mount down
        parent = anc.parent
        if parent == anc:
            return None             # reached filesystem root without hitting root
        anc = parent


def confirm_removals(
    root: Path, removed: list[str], force: bool = False,
    sibling_roots: "Sequence[Path] | None" = None,
) -> tuple[list[str], list[str]]:
    """Partition scan-detected removals into ``(confirmed, kept)``.

    ``confirmed`` are genuine deletions safe to apply; ``kept`` are held back
    (file reappeared, or its location is unreadable). ``force`` bypasses the
    check for a deliberate bulk delete.

    ``sibling_roots`` are the other source directories of the same corpus. A
    stored path is relative to whichever directory it came from, so scanning
    one directory sees every *other* directory's files as missing. Without
    this, two directories in one corpus deleted each other's index on every
    pass and re-indexed it on the next — a permanent churn that ran to half a
    million removal jobs on one project. A file that is present under any
    sibling is not deleted.
    """
    if force:
        return list(removed), []
    roots = [root, *(sibling_roots or ())]
    confirmed: list[str] = []
    kept: list[str] = []
    for rel in removed:
        verdicts = [_absence_is_proven(r, rel) for r in roots]
        # Gone only when every directory gave a definite answer and none of
        # them still holds the file. One unreadable directory (a mount that
        # went dark) is enough to hold the removal back — absence there is
        # not evidence, and this is the check that stands between a glitch
        # and deleting books, chunks and their embeddings.
        gone = bool(verdicts) and all(v is True for v in verdicts)
        (confirmed if gone else kept).append(rel)
    return confirmed, kept


# ── data classes ──────────────────────────────────────────────────────────

@dataclass
class SyncDiff:
    added: list[Path] = field(default_factory=list)
    modified: list[Path] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    moved: list[tuple[str, Path]] = field(default_factory=list)  # (old_rel, new_path)
    # Cross-corpus moves: (old_rel, old_corpus, new_path)
    # Same content_hash appears at a new location in a DIFFERENT corpus —
    # transferred without re-ingesting so embeddings/tags survive.
    cross_moved: list[tuple[str, str, Path]] = field(default_factory=list)
    unchanged: int = 0


@dataclass
class SyncResult:
    added: int = 0
    modified: int = 0
    removed: int = 0
    moved: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)
    # PDFs that produced 0 chunks — likely scanned images needing OCR.
    suspect_scans: list[str] = field(default_factory=list)
    # Other files that produced 0 chunks (empty, corrupt, parser quirks).
    empty_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "added": self.added,
            "modified": self.modified,
            "removed": self.removed,
            "moved": self.moved,
            "unchanged": self.unchanged,
            "errors": self.errors,
            "suspect_scans": self.suspect_scans,
            "empty_files": self.empty_files,
        }

    def __str__(self) -> str:
        parts = []
        if self.added:
            parts.append(f"+{self.added}")
        if self.modified:
            parts.append(f"~{self.modified}")
        if self.removed:
            parts.append(f"-{self.removed}")
        if self.moved:
            parts.append(f">{self.moved}")
        parts.append(f"={self.unchanged}")
        summary = " ".join(parts)
        if self.errors:
            summary += f" ({len(self.errors)} errors)"
        return f"SyncResult({summary})"


# ── helpers ───────────────────────────────────────────────────────────────

def _clean_part(s: str) -> str:
    """Normalise a path component for use in a slug."""
    s = s.lower().strip("_").replace(" ", "-")
    s = re.sub(r"[^\w\-]", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def _path_to_slug(rel_path: str, corpus: str = "") -> str:
    """Convert a relative file path + corpus to an identity for the file.

    The slug encodes ``corpus--dirs--filename`` so that:
    - same filename in different corpora → different slugs
    - same filename in different directories → different slugs
    - **same name, different extension → different slugs**

    That last one is the whole point of using the file name rather than its
    stem. ``bp3_timed_events.h`` and ``bp3_timed_events.c`` are two different
    files; so are ``+sc.Ruwet`` and ``+sc.tryMe``, where the stem stops at the
    first dot and leaves both called ``+sc``. They used to collapse onto one
    identity, the second one hit a UNIQUE violation, and it simply never
    entered the index — silently, for ever. 1 750 files across this fleet.

    Slugs are never recomputed for a file that is already indexed at the same
    path (see the ingest handler), so this scheme applies to newcomers without
    disturbing anything already in place.

    Examples (corpus="pub"):
        ``B4_Flags.md``      → ``pub--b4_flags-md``
        ``_en/B4_Flags.md``  → ``pub--en--b4_flags-md``

    Examples (no corpus):
        ``B4_Flags.md``      → ``b4_flags-md``
        ``notes.tar.gz``     → ``notes-tar-gz``
    """
    p = Path(rel_path)
    stem = _clean_part(p.name)

    prefix_parts: list[str] = []

    # 1. Corpus prefix (always, if provided)
    if corpus:
        clean_corpus = _clean_part(corpus)
        if clean_corpus:
            prefix_parts.append(clean_corpus)

    # 2. Directory components (all parents except '.')
    for part in p.parent.parts:
        if part != ".":
            clean = _clean_part(part)
            if clean:
                prefix_parts.append(clean)

    if prefix_parts:
        return "-".join(prefix_parts) + f"--{stem}"

    return stem


def compute_file_hash(path: Path) -> str:
    """Return the MD5 hex-digest of *path*."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _matches_pattern(name: str, rel: str, pattern: str) -> bool:
    """Match one include/exclude selection pattern against a file.

    * a bare extension (``.bps`` — leading dot, no wildcard) → **suffix** match;
    * a pattern containing ``/`` → glob against the path relative to the root
      (``fixtures/*``, ``**/demos/*``);
    * anything else → glob against the file name (``-gr.*`` prefix, ``*.bps``
      suffix, ``*test*`` infix).
    """
    import fnmatch
    if "/" in pattern:
        return (fnmatch.fnmatch(rel, pattern)
                or fnmatch.fnmatch(rel, f"*/{pattern}"))
    if pattern.startswith(".") and not any(c in pattern for c in "*?["):
        return name.lower().endswith(pattern.lower())
    return fnmatch.fnmatch(name, pattern)


def scan_directory(
    root: Path,
    extensions: set[str] | None = None,
    exclude_dirs: set[str] | None = None,
    honor_gitignore: bool = True,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> list[Path]:
    """Recursively scan *root* and return the files to index.

    RTFM indexes **all text by default**: with no positive restrictor set,
    every file is a candidate and binary content is filtered later, at ingest.
    A registered parser is a structuring *bonus*, never a gate — a file is not
    skipped just because its extension is unknown.

    Filters, in order:

    1. :data:`DEFAULT_EXCLUDE_DIRS` — always skipped (``.git``, ``.venv``,
       ``node_modules``, ``.rtfm``, …).
    2. **Type gate** — a file passes when *no* positive restrictor is set
       (index-all default) OR it matches the suffix allow-list *extensions*
       OR it matches an *include* pattern. ``*``/``**``/``.*`` in *extensions*
       forces index-all explicitly.
    3. *exclude* patterns (prefix/suffix/glob) — rejected when matched.
    4. ``.gitignore`` at *root* (when *honor_gitignore*) then ``.rtfmignore``
       (always) — same syntax as ``.gitignore``.

    *include* / *exclude* patterns follow :func:`_matches_pattern`
    (``*.bps`` suffix, ``-gr.*`` prefix, ``fixtures/*`` path glob).
    """
    exclude_dirs = exclude_dirs or DEFAULT_EXCLUDE_DIRS
    include = list(include or [])
    exclude = list(exclude or [])

    raw_exts = set(extensions or ())
    wildcard = any(e in ("*", ".*", "**") for e in raw_exts)
    exts = {
        (e if e.startswith(".") else f".{e}").lower()
        for e in raw_exts if e not in ("*", ".*", "**")
    }
    # No suffix allow-list and no include patterns → index every file.
    has_restrictor = bool(exts) or bool(include)

    gi_spec = _load_gitignore_spec(root) if honor_gitignore else None
    ri_spec = _load_rtfmignore_spec(root)  # always applied when present

    files: list[Path] = []
    for item in sorted(root.rglob("*")):
        if any(part in exclude_dirs for part in item.parts):
            continue
        if not item.is_file():
            continue
        try:
            rel = str(item.relative_to(root))
        except ValueError:
            rel = str(item)

        # Type gate.
        if not wildcard and has_restrictor:
            ok = item.suffix.lower() in exts or any(
                _matches_pattern(item.name, rel, p) for p in include)
            if not ok:
                continue
        # Explicit exclusions (prefix/suffix/glob).
        if exclude and any(_matches_pattern(item.name, rel, p) for p in exclude):
            continue
        # Ignore files.
        if gi_spec is not None and gi_spec.match_file(rel):
            continue
        if ri_spec is not None and ri_spec.match_file(rel):
            continue
        files.append(item)
    return files


def quick_diff(
    library: "Library",
    root: Path,
    corpus: str,
    extensions: set[str] | None = None,
    exclude_dirs: set[str] | None = None,
    honor_gitignore: bool = True,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> SyncDiff:
    """Cheap diff used for status reporting — no MD5, just path + stat.

    Trade-off vs :func:`compute_diff`: hash-free, so a file modified
    in place without changing size can be missed. That is acceptable
    for the "is the index up to date?" health signal because every
    real ``rtfm sync`` still uses the hash-based diff for correctness.

    Returns a :class:`SyncDiff` populated only with counts that are
    cheap to derive (file_size + path comparison against
    ``indexed_files``).
    """
    diff = SyncDiff()
    # Same selection rules as the real scan: a health check that ignored the
    # source's include/exclude would report every excluded file as "not yet
    # indexed" and send the user to a sync that will never index it.
    files_on_disk = scan_directory(root, extensions, exclude_dirs,
                                   honor_gitignore=honor_gitignore,
                                   include=include, exclude=exclude)
    indexed = library.list_indexed_files(corpus=corpus)

    seen_paths: set[str] = set()
    for fpath in files_on_disk:
        try:
            rel = str(fpath.relative_to(root))
        except ValueError:
            rel = str(fpath)
        seen_paths.add(rel)

        info = indexed.get(rel)
        if info is None:
            diff.added.append(fpath)
            continue
        try:
            current_size = fpath.stat().st_size
        except OSError:
            continue
        prev_size = info.get("file_size") or 0
        if prev_size and current_size != prev_size:
            diff.modified.append(fpath)
        else:
            diff.unchanged += 1

    for db_path in indexed:
        if db_path not in seen_paths:
            diff.removed.append(db_path)

    return diff


def compute_diff(
    files_on_disk: list[Path],
    indexed_files: dict[str, dict],
    root: Path,
    indexed_global: dict[str, dict] | None = None,
    current_corpus: str | None = None,
    known_failures: dict[str, dict] | None = None,
    still_on_disk: "Callable[[str, str], bool] | None" = None,
) -> SyncDiff:
    """Compare the filesystem state against the DB tracking table.

    Detects moves via hash matching:
    - Same corpus: if a tracked file disappears and a new file appears
      with the same MD5, it's a move (not a delete + add).
    - Cross-corpus (when *indexed_global* is provided): if a "new" file
      in the current corpus matches the hash of a file tracked in
      another corpus, it's a cross-corpus move. The book + chunks +
      embeddings + tags are transferred without re-ingestion.

    *known_failures* are files whose ingestion already failed on exactly this
    content. A failed ingest writes no tracking row, so without this every
    scan would offer the same broken file again — for ever. They are skipped
    while their content is unchanged, and picked up again the moment it is.

    *still_on_disk* answers "does this tracked file still exist in its own
    corpus?" and gates cross-corpus moves. Matching content alone does not
    make a move: the same file genuinely lives in two corpora often enough (a
    shared document, a copied README, one tree indexed under two names), and
    treating that as a move made each corpus steal the file back from the
    other on every scan. One project here logged 932 000 re-ingestions of a
    handful of such files, which is what kept the indexer at three cores
    around the clock. Without the callback the old behaviour stands, so the
    caller that knows where files live must supply it.
    """
    diff = SyncDiff()
    known_failures = known_failures or {}
    seen_paths: set[str] = set()
    added_by_hash: dict[str, list[Path]] = {}  # hash → [new paths]
    # Cache hashes computed during the added/modified pass so we don't
    # recompute MD5 when checking cross-corpus matches.
    new_path_hash: dict[Path, str] = {}

    for fpath in files_on_disk:
        try:
            rel = str(fpath.relative_to(root))
        except ValueError:
            rel = str(fpath)

        seen_paths.add(rel)

        # Fast path: an already-indexed file whose size and mtime both match
        # the tracking row cannot have changed in any way we would index, so
        # skip the MD5. Without this, every scan re-reads the entire corpus —
        # which is what forced the scan interval up to minutes and left agent
        # edits undiscovered for that long.
        tracked = indexed_files.get(rel) or known_failures.get(rel)
        if tracked is not None:
            try:
                if probably_unchanged(fpath.stat(), tracked):
                    diff.unchanged += 1
                    continue
            except OSError:
                pass

        current_hash = compute_file_hash(fpath)

        failed = known_failures.get(rel)
        if failed is not None and failed.get("file_hash") == current_hash:
            # Same bytes that failed to parse last time. Re-queueing it would
            # only fail again and crowd out real work.
            diff.unchanged += 1
            continue

        if rel not in indexed_files:
            diff.added.append(fpath)
            added_by_hash.setdefault(current_hash, []).append(fpath)
            new_path_hash[fpath] = current_hash
        elif indexed_files[rel]["file_hash"] != current_hash:
            diff.modified.append(fpath)
        else:
            diff.unchanged += 1

    # Files in DB but no longer on disk — check for moves (same corpus)
    for db_path, info in indexed_files.items():
        if db_path not in seen_paths:
            old_hash = info["file_hash"]
            candidates = added_by_hash.get(old_hash, [])
            if candidates:
                # Same hash at new location → move
                new_path = candidates.pop(0)
                diff.moved.append((db_path, new_path))
                diff.added.remove(new_path)
                if not candidates:
                    del added_by_hash[old_hash]
            else:
                diff.removed.append(db_path)

    # Cross-corpus moves: a file that looked "added" here may actually
    # exist in another corpus with the same hash. Transfer ownership
    # instead of re-ingesting. We only consume one cross-match per hash
    # to avoid silently colliding distinct corpora.
    if indexed_global:
        cross_by_hash: dict[str, list[tuple[str, dict]]] = {}
        for path, info in indexed_global.items():
            # skip entries that belong to the current corpus — handled above
            if current_corpus is not None and info.get("corpus") == current_corpus:
                continue
            cross_by_hash.setdefault(info["file_hash"], []).append((path, info))

        remaining_added: list[Path] = []
        for new_path in diff.added:
            h = new_path_hash.get(new_path)
            if h is None:
                remaining_added.append(new_path)
                continue
            candidates = cross_by_hash.get(h)
            if not candidates:
                remaining_added.append(new_path)
                continue
            # Take the first candidate that has genuinely left its corpus.
            # One that is still on disk there is not a move — the same
            # content simply lives in both places.
            match = None
            for i, (old_path, old_info) in enumerate(candidates):
                if still_on_disk is not None and still_on_disk(
                        old_path, old_info.get("corpus") or ""):
                    continue
                match = candidates.pop(i)
                break
            if match is None:
                remaining_added.append(new_path)
                continue
            old_path, old_info = match
            diff.cross_moved.append((old_path, old_info["corpus"], new_path))
            if not candidates:
                del cross_by_hash[h]
        diff.added = remaining_added

    return diff


# ── edge sync ─────────────────────────────────────────────────────────────

def _resolve_import_to_relpath(target_ref: str, root: Path) -> str | None:
    """Resolve a Python import reference to a relative file path within root."""
    parts = target_ref.replace(".", "/")
    # Try module.py first, then package/__init__.py
    for candidate in [f"{parts}.py", f"{parts}/__init__.py"]:
        if (root / candidate).is_file():
            return candidate
    return None


def _resolve_wikilink_to_relpath(
    target_ref: str,
    source_file: str,
    root: Path,
    all_files: dict[str, int],
) -> str | None:
    """Resolve an Obsidian-style wikilink to a relative file path.

    Follows Obsidian resolution rules:
    1. Strip anchor (``[[Note#Section]]`` → ``Note``)
    2. Exact path match (with or without ``.md``)
    3. Basename match (case-insensitive)
    4. Path-suffix match for qualified refs (``[[folder/Note]]``)
    5. Disambiguate by shortest path distance from source file
    """
    target = target_ref.split("#")[0].strip()
    if not target:
        return None

    target_lower = target.lower()
    target_md_lower = f"{target_lower}.md" if not target_lower.endswith(".md") else target_lower

    # Exact path match
    for rel_path in all_files:
        if rel_path == target or rel_path == f"{target}.md":
            return rel_path

    # Basename + path-suffix match
    candidates: list[str] = []
    target_stem = Path(target).stem.lower()
    for rel_path in all_files:
        p = Path(rel_path)
        # Basename match (case-insensitive, .md files)
        if p.stem.lower() == target_stem and p.suffix.lower() == ".md":
            candidates.append(rel_path)
        # Path-suffix match: [[folder/Note]] matches "some/folder/Note.md"
        elif rel_path.lower().endswith(target_md_lower) or rel_path.lower().endswith(target_lower):
            candidates.append(rel_path)

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # Disambiguate: prefer file closest to source in directory tree
    source_parts = Path(source_file).parent.parts

    def _distance(c: str) -> int:
        c_parts = Path(c).parent.parts
        common = 0
        for a, b in zip(source_parts, c_parts):
            if a == b:
                common += 1
            else:
                break
        return len(source_parts) + len(c_parts) - 2 * common

    candidates.sort(key=_distance)
    return candidates[0]


def _resolve_link_to_relpath(target_ref: str, source_file: str, root: Path) -> str | None:
    """Resolve a relative link/include to a relative file path within root."""
    source_dir = (root / source_file).parent
    candidate = (source_dir / target_ref).resolve()
    try:
        rel = str(candidate.relative_to(root))
        if candidate.is_file():
            return rel
        # LaTeX \input may omit .tex extension
        if not candidate.suffix:
            for ext in [".tex", ".latex"]:
                with_ext = candidate.with_suffix(ext)
                if with_ext.is_file():
                    return str(with_ext.relative_to(root))
    except ValueError:
        pass
    return None


def _sync_edges(
    library: "Library",
    root: Path,
    corpus: str,
    files: list[Path],
) -> None:
    """Extract edges from files and write them to the edges table."""
    conn = library._get_conn()

    # Build lookup: relative_path → book_id
    rows = conn.execute(
        "SELECT id, filename FROM books WHERE corpus = ?", (corpus,)
    ).fetchall()
    path_to_book_id: dict[str, int] = {}
    for row in rows:
        if row["filename"]:
            path_to_book_id[row["filename"]] = row["id"]

    for fpath in files:
        try:
            rel = str(fpath.relative_to(root))
        except ValueError:
            rel = str(fpath)

        source_book_id = path_to_book_id.get(rel)
        if not source_book_id:
            continue

        parser = ParserRegistry.get_parser(fpath)
        if not parser:
            continue

        try:
            candidates = parser.extract_edges(fpath, metadata={"source_file": rel})
        except Exception:
            continue

        if not candidates:
            continue

        # Clear old edges for this source
        conn.execute("DELETE FROM edges WHERE source_book_id = ?", (source_book_id,))

        for edge in candidates:
            # Resolve target_ref to a relative file path
            if edge.relation_type == "import":
                target_rel = _resolve_import_to_relpath(edge.target_ref, root)
            elif edge.relation_type in ("link", "include"):
                if edge.source_detail.startswith("[["):
                    # Wikilink: basename-based resolution (Obsidian style)
                    target_rel = _resolve_wikilink_to_relpath(
                        edge.target_ref, rel, root, path_to_book_id
                    )
                else:
                    target_rel = _resolve_link_to_relpath(edge.target_ref, rel, root)
            else:
                # cite: skip resolution for now
                continue

            if not target_rel:
                continue

            target_book_id = path_to_book_id.get(target_rel)
            if not target_book_id or target_book_id == source_book_id:
                continue

            conn.execute(
                """INSERT OR IGNORE INTO edges
                   (source_book_id, target_book_id, relation_type, source_detail)
                   VALUES (?, ?, ?, ?)""",
                (source_book_id, target_book_id, edge.relation_type, edge.source_detail),
            )

    conn.commit()


# ── main sync ─────────────────────────────────────────────────────────────

def sync(
    library: "Library",
    root: Path,
    corpus: str = "default",
    extensions: set[str] | None = None,
    exclude_dirs: set[str] | None = None,
    dry_run: bool = False,
    generate_embeddings: bool = True,
    files: list[str] | None = None,
    on_progress: "Callable[[str, str, str], None] | None" = None,
    force: bool = False,
    retain_history: int | None = 50,
    ocr_fallback: bool = False,
    progress_interval: float | None = None,
    force_remove: bool = False,
    honor_gitignore: bool = True,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> SyncResult:
    """Orchestrate a full incremental sync.

    Parameters
    ----------
    library : Library
        Target library.
    root : Path
        Root directory to scan.
    corpus : str
        Corpus name for ingested documents.
    extensions / exclude_dirs : set[str] | None
        Override default file filters.
    dry_run : bool
        If *True*, compute the diff but do not touch the DB.
    generate_embeddings : bool
        Generate embeddings for new/modified chunks after sync.
    files : list[str] | None
        If given, only sync these specific files (for git-hook mode).
        Paths are relative to *root*.
    on_progress : callable | None
        Optional callback ``(action, filepath, detail)`` called for each
        file processed.  *action* is ``"add"``, ``"update"``, ``"remove"``,
        ``"move"``, ``"skip"``, ``"embed"``, or ``"error"``.
    force : bool
        If *True*, re-index all files even if their hash hasn't changed.
        Useful after adding new parsers.

    Returns
    -------
    SyncResult
    """
    root = root.resolve()
    result = SyncResult()

    # Store sync root for absolute path resolution in MCP
    library.set_sync_root(corpus, str(root))

    # 1. Discover files
    if files:
        # Git-hook mode: explicit file list
        files_on_disk = []
        for f in files:
            p = root / f
            if p.is_file():
                files_on_disk.append(p)
    else:
        files_on_disk = scan_directory(root, extensions, exclude_dirs,
                                       honor_gitignore=honor_gitignore,
                                       include=include, exclude=exclude)

    # 2. Get DB state (scoped to corpus to support multi-directory sync)
    indexed = library.list_indexed_files(corpus=corpus)
    # Full DB state (all corpora) — fuel for cross-corpus move detection.
    # Cheap query, just a SELECT without parsing files.
    indexed_global = library.list_indexed_files()

    # 3. Compute diff
    if force:
        # Force mode: treat all files as modified (re-index everything)
        diff = SyncDiff()
        for fpath in files_on_disk:
            try:
                rel = str(fpath.relative_to(root))
            except ValueError:
                rel = str(fpath)
            if rel in indexed:
                diff.modified.append(fpath)
            else:
                diff.added.append(fpath)
        # Still detect removed files
        seen = {str(f.relative_to(root)) if f.is_relative_to(root) else str(f)
                for f in files_on_disk}
        for db_path in indexed:
            if db_path not in seen:
                diff.removed.append(db_path)
    else:
        diff = compute_diff(files_on_disk, indexed, root,
                            indexed_global=indexed_global,
                            current_corpus=corpus,
                            still_on_disk=build_disk_check(library, root))

    result.unchanged = diff.unchanged

    if dry_run:
        result.added = len(diff.added)
        result.modified = len(diff.modified)
        result.removed = len(diff.removed)
        result.moved = len(diff.moved)
        return result

    # 4. Process moves (update tracking without re-ingesting)
    for old_rel, new_path in diff.moved:
        try:
            new_rel = str(new_path.relative_to(root))
        except ValueError:
            new_rel = str(new_path)

        try:
            new_slug = _path_to_slug(new_rel, corpus)
            library.move_file(old_rel, new_rel, new_slug, corpus=corpus)
            result.moved += 1
            if on_progress:
                on_progress("move", f"{old_rel} -> {new_rel}", "renamed")
        except Exception as exc:
            result.errors.append(f"move {old_rel}: {exc}")
            if on_progress:
                on_progress("error", old_rel, str(exc))
            print(f"[sync] error moving {old_rel}: {exc}", file=sys.stderr)

    # 4b. Cross-corpus moves: same content, new corpus. Embeddings + tags
    # follow via FK on chunk_id; only tracking + book row need updating.
    for old_rel, old_corpus, new_path in diff.cross_moved:
        try:
            new_rel = str(new_path.relative_to(root))
        except ValueError:
            new_rel = str(new_path)

        try:
            new_slug = _path_to_slug(new_rel, corpus)
            library.move_file(old_rel, new_rel, new_slug,
                              corpus=old_corpus, new_corpus=corpus)
            result.moved += 1
            if on_progress:
                on_progress(
                    "move",
                    f"[{old_corpus}] {old_rel} -> [{corpus}] {new_rel}",
                    "cross-corpus (embeddings/tags preserved)",
                )
        except Exception as exc:
            result.errors.append(f"cross-move {old_rel}: {exc}")
            if on_progress:
                on_progress("error", old_rel, str(exc))
            print(f"[sync] error cross-moving {old_rel}: {exc}", file=sys.stderr)

    # 5. Process added + modified
    # When ocr_fallback is on, we build a single auto-backend PDFParser and
    # reuse it for every PDF instead of letting the registry instantiate
    # the default pdftext-only one.
    pdf_parser = None
    if ocr_fallback:
        try:
            from rtfm.parsers.pdf import PDFParser
            pdf_parser = PDFParser(backend="auto")
        except Exception as exc:
            print(f"[sync] could not enable OCR fallback: {exc}", file=sys.stderr)

    # Periodic progress reporting. Long syncs (OCR, large corpora) benefit
    # from a heartbeat line so the user knows it is still alive.
    import time as _time
    total_to_process = len(diff.added) + len(diff.modified)
    progress_t0 = _time.time()
    last_progress_emit = progress_t0

    for idx, fpath in enumerate(diff.added + diff.modified, start=1):
        try:
            rel = str(fpath.relative_to(root))
        except ValueError:
            rel = str(fpath)

        try:
            file_hash = compute_file_hash(fpath)
            # A file that has not moved keeps the identity it was indexed
            # under; only a newcomer is given one.
            book_slug = library.book_slug_for(rel, corpus)
            if book_slug is None:
                book_slug = library.allocate_book_slug(
                    _path_to_slug(rel, corpus), rel, corpus)

            if fpath in diff.modified:
                old_info = indexed.get(rel)

                # Save version snapshot before re-ingest
                snap_slug = old_info["book_slug"] if old_info and old_info.get("book_slug") else book_slug
                old_hash = old_info["file_hash"] if old_info else ""
                try:
                    library.save_file_version(snap_slug, old_hash, prune_limit=retain_history)
                except Exception:
                    pass  # Non-critical — versioning is best-effort

            # Inject the auto-backend PDFParser only for PDFs; other formats
            # keep registry-default behaviour.
            ingest_parser = None
            if pdf_parser is not None and fpath.suffix.lower() == ".pdf":
                ingest_parser = pdf_parser

            # Pass slug and relative path to parser so it doesn't generate its own
            stats = library.ingest(
                fpath, corpus=corpus, parser=ingest_parser,
                metadata={"book_slug": book_slug, "source_file": rel},
            )
            library.update_indexed_file(
                filepath=rel,
                file_hash=file_hash,
                corpus=corpus,
                book_slug=book_slug,
                file_size=fpath.stat().st_size,
            )
            # Health signal: a file that produces 0 chunks is suspicious.
            # PDFs are almost always scans needing OCR; other formats may
            # just be empty or corrupt. We surface both separately so the
            # CLI/MCP can suggest the right fix.
            if stats.get("chunks", 0) == 0:
                if fpath.suffix.lower() == ".pdf":
                    result.suspect_scans.append(rel)
                else:
                    result.empty_files.append(rel)
            if fpath in diff.added:
                result.added += 1
                if on_progress:
                    on_progress("add", rel, f"{stats.get('chunks', '?')} chunks")
            else:
                result.modified += 1
                if on_progress:
                    on_progress("update", rel, f"{stats.get('chunks', '?')} chunks")
        except Exception as exc:
            result.errors.append(f"{rel}: {exc}")
            if on_progress:
                on_progress("error", rel, str(exc))
            print(f"[sync] error processing {rel}: {exc}", file=sys.stderr)

        # Periodic progress heartbeat (e.g. every 10 min during OCR).
        # Disabled by default (progress_interval=None) so short syncs
        # stay quiet.
        if progress_interval and progress_interval > 0:
            now = _time.time()
            if now - last_progress_emit >= progress_interval:
                elapsed = now - progress_t0
                rate = idx / elapsed if elapsed > 0 else 0
                remaining = max(0, total_to_process - idx)
                eta_sec = remaining / rate if rate > 0 else 0
                detail = (
                    f"{idx}/{total_to_process} files, "
                    f"{elapsed/60:.1f}min elapsed, "
                    f"~{eta_sec/60:.1f}min remaining"
                )
                if on_progress:
                    on_progress("progress", "", detail)
                else:
                    print(f"[sync] progress: {detail}", file=sys.stderr)
                last_progress_emit = now

    # 6. Process removed — guarded against transient scan misses.
    #
    # Deleting an indexed file destroys its book, chunks and (expensive)
    # embeddings. We only do that when the scan is trustworthy. Three gates,
    # in order of precedence:
    #   (a) retain_history is None → never delete (memory-snapshot corpora:
    #       nothing is ever lost, even if the source file disappears).
    #   (b) file-list mode (files=) → never delete: a caller-supplied partial
    #       list says nothing about files it didn't mention, so their absence
    #       from `files` is not evidence of deletion.
    #   (c) per-file confirmation → re-verify each removal against the live
    #       filesystem; keep any file that reappeared (transient scan miss) or
    #       whose location is unreadable (mount down). force_remove skips the
    #       check for a deliberate bulk delete.
    if retain_history is None:
        for rel in diff.removed:
            if on_progress:
                on_progress("remove", rel, "skipped (retain_history=None)")
    elif files is not None:
        for rel in diff.removed:
            if on_progress:
                on_progress("remove", rel, "skipped (file-list mode)")
    else:
        confirmed, kept = confirm_removals(
            root, list(diff.removed), force=force_remove,
            sibling_roots=_sibling_roots(library, corpus, root))
        if kept:
            msg = (f"kept {len(kept)} unconfirmed removal(s) in corpus "
                   f"'{corpus}' (file present or location unreadable)")
            print(f"[sync] {msg}", file=sys.stderr)
            for rel in kept:
                if on_progress:
                    on_progress("remove", rel, "kept (unconfirmed)")
        for rel in confirmed:
            try:
                library.remove_file(rel, corpus)
                result.removed += 1
                if on_progress:
                    on_progress("remove", rel, "removed")
            except Exception as exc:
                result.errors.append(f"{rel}: {exc}")
                if on_progress:
                    on_progress("error", rel, str(exc))
                print(f"[sync] error removing {rel}: {exc}", file=sys.stderr)

    # 6b. Extract and resolve edges
    if result.added or result.modified:
        try:
            _sync_edges(library, root, corpus, diff.added + diff.modified)
        except Exception as exc:
            result.errors.append(f"edges: {exc}")
            print(f"[sync] edge extraction error: {exc}", file=sys.stderr)

    # 6c. Update vault output (lightweight: recent page only)
    if result.added or result.modified:
        try:
            from rtfm.config import load_config
            cfg = load_config(root)
            if cfg.get("vault_type") == "obsidian":
                from rtfm.plugin.vault_output import update_recent_page
                update_recent_page(library, root)
        except Exception:
            pass  # Non-critical

    # 7. Embeddings (optional, may be slow)
    if generate_embeddings and (result.added or result.modified):
        if on_progress:
            on_progress("embed", "", "generating embeddings (this may take a while)...")
        try:
            stats = library.generate_embeddings(corpus=corpus, show_progress=True)
            if on_progress:
                count = stats.get("embedded", 0)
                on_progress("embed", "", f"done — {count} chunks embedded")
        except Exception as exc:
            result.errors.append(f"embeddings: {exc}")
            if on_progress:
                on_progress("error", "embeddings", str(exc))
            print(f"[sync] embedding error: {exc}", file=sys.stderr)

    return result
