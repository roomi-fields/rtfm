"""Fast project scanner — builds a project map without indexation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# Extension → category mapping
_CATEGORY_MAP: dict[str, str] = {}

_CODE_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".rs", ".go", ".java", ".c", ".cpp",
    ".h", ".hpp", ".cs", ".rb", ".php", ".swift", ".kt", ".scala", ".lua",
    ".sh", ".bash", ".zsh", ".pl", ".r", ".m", ".mm", ".zig", ".nim",
    ".ex", ".exs", ".erl", ".hs", ".clj", ".cljs", ".vue", ".svelte",
}
_DOC_EXTS = {".md", ".markdown", ".rst", ".txt", ".adoc", ".org", ".tex"}
_CONFIG_EXTS = {
    ".toml", ".yaml", ".yml", ".json", ".ini", ".cfg", ".conf", ".env",
    ".xml", ".lock", ".editorconfig",
}
_STYLE_EXTS = {".css", ".scss", ".sass", ".less", ".styl"}
_DATA_EXTS = {".csv", ".tsv", ".sql", ".db", ".sqlite", ".parquet", ".ndjson"}

for _ext in _CODE_EXTS:
    _CATEGORY_MAP[_ext] = "code"
for _ext in _DOC_EXTS:
    _CATEGORY_MAP[_ext] = "docs"
for _ext in _CONFIG_EXTS:
    _CATEGORY_MAP[_ext] = "config"
for _ext in _STYLE_EXTS:
    _CATEGORY_MAP[_ext] = "style"
for _ext in _DATA_EXTS:
    _CATEGORY_MAP[_ext] = "data"

# Extension → language mapping (code only)
_LANG_MAP = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
    ".jsx": "JavaScript", ".tsx": "TypeScript", ".rs": "Rust",
    ".go": "Go", ".java": "Java", ".c": "C", ".cpp": "C++",
    ".cs": "C#", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift",
    ".kt": "Kotlin", ".scala": "Scala", ".lua": "Lua", ".sh": "Shell",
    ".bash": "Shell", ".r": "R", ".zig": "Zig", ".nim": "Nim",
    ".ex": "Elixir", ".exs": "Elixir", ".erl": "Erlang",
    ".hs": "Haskell", ".clj": "Clojure", ".vue": "Vue",
    ".svelte": "Svelte", ".html": "HTML", ".htm": "HTML",
}

# Known entry-point filenames
_ENTRY_POINTS = {
    "README.md", "README", "readme.md",
    "CLAUDE.md",
    "pyproject.toml", "setup.py", "setup.cfg",
    "package.json", "Cargo.toml", "go.mod",
    "Makefile", "Dockerfile", "docker-compose.yml",
    "main.py", "app.py", "index.js", "index.ts",
    ".mcp.json",
}

# Default directories to exclude
DEFAULT_EXCLUDE_DIRS = {
    ".git", ".hg", ".svn",
    "node_modules", ".venv", "venv", "__pycache__",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", ".eggs", "*.egg-info",
    ".rtfm", ".claude",
}


def discover(
    root: str | Path,
    exclude_dirs: Optional[set[str]] = None,
) -> dict:
    """Scan a project directory and return a structural map.

    Fast (~1 second even on large projects), does NOT index content.

    Args:
        root: Project root directory.
        exclude_dirs: Directory names to skip (default: common noise dirs).

    Returns:
        Dict with file_types, languages, entry_points, size_by_dir,
        total_files, total_size.
    """
    root = Path(root).resolve()
    excludes = exclude_dirs if exclude_dirs is not None else DEFAULT_EXCLUDE_DIRS

    file_types: dict[str, int] = {}
    languages: set[str] = set()
    entry_points: list[str] = []
    size_by_dir: dict[str, int] = {}
    total_files = 0
    total_size = 0

    for dirpath, dirnames, filenames in os.walk(root):
        # Filter out excluded directories (modifying dirnames in-place)
        dirnames[:] = [
            d for d in dirnames
            if d not in excludes and not d.endswith(".egg-info")
        ]

        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            rel_dir = "."

        dir_size = 0

        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            try:
                fsize = os.path.getsize(filepath)
            except OSError:
                continue

            total_files += 1
            total_size += fsize
            dir_size += fsize

            ext = os.path.splitext(filename)[1].lower()
            category = _CATEGORY_MAP.get(ext, "other")
            file_types[category] = file_types.get(category, 0) + 1

            lang = _LANG_MAP.get(ext)
            if lang:
                languages.add(lang)

            # Check entry points (only at root level)
            if rel_dir == "." and filename in _ENTRY_POINTS:
                entry_points.append(filename)

        if dir_size > 0:
            # Use first-level dir name for grouping
            top_dir = rel_dir.split(os.sep)[0] if rel_dir != "." else "."
            size_by_dir[top_dir] = size_by_dir.get(top_dir, 0) + dir_size

    return {
        "root": str(root),
        "file_types": file_types,
        "languages": sorted(languages),
        "entry_points": sorted(entry_points),
        "size_by_dir": dict(sorted(
            size_by_dir.items(), key=lambda x: -x[1]
        )),
        "total_files": total_files,
        "total_size": total_size,
    }


def format_discover(info: dict) -> str:
    """Format discover output as human-readable text."""
    lines = [
        f"Project: {info['root']}",
        f"Files: {info['total_files']:,} ({info['total_size']:,} bytes)",
    ]

    if info["languages"]:
        lines.append(f"Languages: {', '.join(info['languages'])}")

    if info["file_types"]:
        lines.append("\nFile types:")
        for cat, count in sorted(info["file_types"].items(), key=lambda x: -x[1]):
            lines.append(f"  {cat}: {count}")

    if info["entry_points"]:
        lines.append("\nEntry points:")
        for ep in info["entry_points"]:
            lines.append(f"  {ep}")

    if info["size_by_dir"]:
        lines.append("\nSize by directory:")
        for d, size in list(info["size_by_dir"].items())[:15]:
            if size >= 1_000_000:
                formatted = f"{size / 1_000_000:.1f} MB"
            elif size >= 1_000:
                formatted = f"{size / 1_000:.1f} KB"
            else:
                formatted = f"{size} B"
            lines.append(f"  {d}: {formatted}")

    return "\n".join(lines)
