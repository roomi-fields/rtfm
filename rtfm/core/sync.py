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

DEFAULT_EXTENSIONS: set[str] = {
    ".md", ".txt", ".pdf", ".html", ".xml",
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".rs", ".go", ".java",
    ".sh", ".bash", ".zsh",
    ".css", ".toml", ".yaml", ".yml", ".cfg",
    ".c", ".cpp", ".h", ".rb", ".php",
    ".json", ".tex", ".latex",
}

DEFAULT_EXCLUDE_DIRS: set[str] = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".tox", "dist", "build", ".egg-info", ".eggs",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "db",
}


# ── data classes ──────────────────────────────────────────────────────────

@dataclass
class SyncDiff:
    added: list[Path] = field(default_factory=list)
    modified: list[Path] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    moved: list[tuple[str, Path]] = field(default_factory=list)  # (old_rel, new_path)
    unchanged: int = 0


@dataclass
class SyncResult:
    added: int = 0
    modified: int = 0
    removed: int = 0
    moved: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "added": self.added,
            "modified": self.modified,
            "removed": self.removed,
            "moved": self.moved,
            "unchanged": self.unchanged,
            "errors": self.errors,
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


def compute_diff(
    files_on_disk: list[Path],
    indexed_files: dict[str, dict],
    root: Path,
) -> SyncDiff:
    """Compare the filesystem state against the DB tracking table.

    Detects moves via hash matching: if a tracked file disappears and a new
    file appears with the same MD5, it's a move (not a delete + add).
    """
    diff = SyncDiff()
    seen_paths: set[str] = set()
    added_by_hash: dict[str, list[Path]] = {}  # hash → [new paths]

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
        elif indexed_files[rel]["file_hash"] != current_hash:
            diff.modified.append(fpath)
        else:
            diff.unchanged += 1

    # Files in DB but no longer on disk — check for moves
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
        diff = compute_diff(files_on_disk, indexed, root)

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

    # 5. Process added + modified
    for fpath in diff.added + diff.modified:
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
                    library.save_file_version(snap_slug, old_hash)
                except Exception:
                    pass  # Non-critical — versioning is best-effort

            # Pass slug and relative path to parser so it doesn't generate its own
            stats = library.ingest(
                fpath, corpus=corpus,
                metadata={"book_slug": book_slug, "source_file": rel},
            )
            library.update_indexed_file(
                filepath=rel,
                file_hash=file_hash,
                corpus=corpus,
                book_slug=book_slug,
                file_size=fpath.stat().st_size,
            )
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

    # 6. Process removed
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
