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
from typing import TYPE_CHECKING, Callable

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
}

# ── mass-removal circuit breaker ────────────────────────────────────────────
# A full sync deletes every indexed file not seen on disk. That is only
# correct when the scan is trustworthy. On NTFS-via-WSL a mount hiccup, or an
# external process reorganising files mid-scan, can make scan_directory()
# return far fewer files than are indexed — and an unguarded sync then wipes
# books + chunks + the expensive embeddings for files that are merely
# temporarily absent (this destroyed ~500 PDFs once). The breaker refuses a
# removal batch when it is both large in absolute terms AND a big fraction of
# the corpus — the signature of a bad scan, not real deletions. Pass
# force_remove=True (or `rtfm sync --force-remove`) to override deliberately.
REMOVE_CIRCUIT_MIN_FILES = 25
REMOVE_CIRCUIT_RATIO = 0.25


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
    """Convert a relative file path + corpus to a globally unique slug.

    The slug always encodes ``corpus--dirs--stem`` so that:
    - same filename in different corpora → different slugs
    - same filename in different directories → different slugs

    Examples (corpus="pub"):
        ``B4_Flags.md``      → ``pub--b4_flags``
        ``_en/B4_Flags.md``  → ``pub--en--b4_flags``

    Examples (no corpus):
        ``B4_Flags.md``      → ``b4_flags``
        ``_en/B4_Flags.md``  → ``en--b4_flags``
    """
    p = Path(rel_path)
    stem = _clean_part(p.stem)

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


def scan_directory(
    root: Path,
    extensions: set[str] | None = None,
    exclude_dirs: set[str] | None = None,
) -> list[Path]:
    """Recursively scan *root* and return files matching *extensions*."""
    extensions = extensions or DEFAULT_EXTENSIONS
    exclude_dirs = exclude_dirs or DEFAULT_EXCLUDE_DIRS

    # Normalise extensions to lower-case with leading dot
    extensions = {e if e.startswith(".") else f".{e}" for e in extensions}

    files: list[Path] = []
    for item in sorted(root.rglob("*")):
        # Skip excluded directories
        if any(part in exclude_dirs for part in item.parts):
            continue
        if item.is_file() and item.suffix.lower() in extensions:
            files.append(item)
    return files


def quick_diff(
    library: "Library",
    root: Path,
    corpus: str,
    extensions: set[str] | None = None,
    exclude_dirs: set[str] | None = None,
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
    files_on_disk = scan_directory(root, extensions, exclude_dirs)
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
) -> SyncDiff:
    """Compare the filesystem state against the DB tracking table.

    Detects moves via hash matching:
    - Same corpus: if a tracked file disappears and a new file appears
      with the same MD5, it's a move (not a delete + add).
    - Cross-corpus (when *indexed_global* is provided): if a "new" file
      in the current corpus matches the hash of a file tracked in
      another corpus, it's a cross-corpus move. The book + chunks +
      embeddings + tags are transferred without re-ingestion.
    """
    diff = SyncDiff()
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
        current_hash = compute_file_hash(fpath)

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
            old_path, old_info = candidates.pop(0)
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
        files_on_disk = scan_directory(root, extensions, exclude_dirs)

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
                             current_corpus=corpus)

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
            library.move_file(old_rel, new_rel, new_slug)
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
            library.move_file(old_rel, new_rel, new_slug, new_corpus=corpus)
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
            book_slug = _path_to_slug(rel, corpus)

            # If file was modified and slug format changed, clean up old book
            if fpath in diff.modified:
                old_info = indexed.get(rel)
                if old_info and old_info.get("book_slug") and old_info["book_slug"] != book_slug:
                    library.delete_book(old_info["book_slug"])

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
    #   (c) mass-removal circuit breaker → if a removal batch is both large
    #       and a big fraction of the corpus, the scan is almost certainly
    #       incomplete (mount hiccup, external reorg mid-scan); skip it and
    #       surface a warning instead of wiping the index. force_remove
    #       overrides for deliberate bulk deletes.
    if retain_history is None:
        for rel in diff.removed:
            if on_progress:
                on_progress("remove", rel, "skipped (retain_history=None)")
    elif files is not None:
        for rel in diff.removed:
            if on_progress:
                on_progress("remove", rel, "skipped (file-list mode)")
    elif (not force_remove and diff.removed
          and len(diff.removed) >= REMOVE_CIRCUIT_MIN_FILES
          and len(diff.removed) >= REMOVE_CIRCUIT_RATIO * (len(indexed) or 1)):
        n, total = len(diff.removed), len(indexed)
        msg = (
            f"refused to remove {n}/{total} files "
            f"({n / (total or 1):.0%} of corpus '{corpus}') — scan looks "
            f"incomplete (mount hiccup or reorg in progress?). Index left "
            f"intact. Re-run with force_remove=True to override."
        )
        result.errors.append(msg)
        print(f"[sync] {msg}", file=sys.stderr)
        if on_progress:
            on_progress("error", "", msg)
    else:
        for rel in diff.removed:
            try:
                library.remove_file(rel)
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
