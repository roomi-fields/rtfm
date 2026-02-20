"""Incremental sync: keep a rtfm Library in sync with a directory tree.

Usage::

    from rtfm.core.library import Library
    from rtfm.core.sync import sync

    lib = Library("project.db")
    result = sync(lib, root=".", corpus="my-project")
    print(result)  # SyncResult(added=3, modified=1, removed=0, unchanged=42)
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

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
    unchanged: int = 0


@dataclass
class SyncResult:
    added: int = 0
    modified: int = 0
    removed: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "added": self.added,
            "modified": self.modified,
            "removed": self.removed,
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
        parts.append(f"={self.unchanged}")
        summary = " ".join(parts)
        if self.errors:
            summary += f" ({len(self.errors)} errors)"
        return f"SyncResult({summary})"


# ── helpers ───────────────────────────────────────────────────────────────

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
    """Compare the filesystem state against the DB tracking table."""
    diff = SyncDiff()
    seen_paths: set[str] = set()

    for fpath in files_on_disk:
        try:
            rel = str(fpath.relative_to(root))
        except ValueError:
            rel = str(fpath)

        seen_paths.add(rel)
        current_hash = compute_file_hash(fpath)

        if rel not in indexed_files:
            diff.added.append(fpath)
        elif indexed_files[rel]["file_hash"] != current_hash:
            diff.modified.append(fpath)
        else:
            diff.unchanged += 1

    # Files in DB but no longer on disk
    for db_path in indexed_files:
        if db_path not in seen_paths:
            diff.removed.append(db_path)

    return diff


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
        ``"skip"``, ``"embed"``, or ``"error"``.
    force : bool
        If *True*, re-index all files even if their hash hasn't changed.
        Useful after adding new parsers.

    Returns
    -------
    SyncResult
    """
    root = root.resolve()
    result = SyncResult()

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
        return result

    # 4. Process added + modified
    for fpath in diff.added + diff.modified:
        try:
            rel = str(fpath.relative_to(root))
        except ValueError:
            rel = str(fpath)

        try:
            stats = library.ingest(fpath, corpus=corpus)
            file_hash = compute_file_hash(fpath)
            book_slug = rel.replace("/", "-").replace("\\", "-").lstrip("-")
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

    # 5. Process removed
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

    # 6. Embeddings (optional, may be slow)
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
