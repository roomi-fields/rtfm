"""Configuration and auto-detection for RTFM projects."""

from __future__ import annotations

import json
import os
from pathlib import Path


def find_rtfm_root(start: str | Path = ".") -> Path | None:
    """Walk up directories looking for .rtfm/library.db (like git finds .git/).

    Args:
        start: Directory to start searching from.

    Returns:
        The project root containing .rtfm/, or None if not found.
    """
    current = Path(start).resolve()
    for parent in [current, *current.parents]:
        if (parent / ".rtfm" / "library.db").exists():
            return parent
    return None


def resolve_db(explicit_db: str | None = None) -> str:
    """Resolve the database path by priority.

    1. Explicit --db argument
    2. RTFM_DB environment variable
    3. Auto-detect .rtfm/library.db walking up from cwd
    4. Fallback: library.db (legacy compat)

    Args:
        explicit_db: Value from --db CLI argument (None if not provided).

    Returns:
        Path to the database file.
    """
    if explicit_db:
        return explicit_db

    env_db = os.environ.get("RTFM_DB")
    if env_db:
        return env_db

    root = find_rtfm_root()
    if root:
        return str(root / ".rtfm" / "library.db")

    return "library.db"


def load_config(project_root: Path) -> dict:
    """Load .rtfm/config.json from a project root.

    Args:
        project_root: Project root directory.

    Returns:
        Config dict (empty dict if file doesn't exist).
    """
    config_path = Path(project_root) / ".rtfm" / "config.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_config(project_root: Path, config: dict) -> None:
    """Write .rtfm/config.json with indent=2.

    Args:
        project_root: Project root directory.
        config: Config dict to save.
    """
    project_root = Path(project_root)
    rtfm_dir = project_root / ".rtfm"
    rtfm_dir.mkdir(parents=True, exist_ok=True)
    config_path = rtfm_dir / "config.json"
    config_path.write_text(
        json.dumps(config, indent=2) + "\n",
        encoding="utf-8",
    )


def add_source(
    project_root: Path,
    path: str,
    corpus: str,
    extensions: str | None = None,
) -> str:
    """Add a source to .rtfm/config.json.

    Resolves the path to absolute. Deduplicates by (resolved path, corpus).

    Args:
        project_root: Project root directory.
        path: Path to the source directory.
        corpus: Corpus name.
        extensions: Comma-separated extensions (e.g. ".md,.py").

    Returns:
        "added" or "already exists".
    """
    config = load_config(project_root)
    sources = config.get("sources", [])

    resolved = str(Path(path).resolve())

    # Check for duplicates
    for src in sources:
        if src.get("path") == resolved and src.get("corpus") == corpus:
            return "already exists"

    entry: dict = {"path": resolved, "corpus": corpus}
    if extensions:
        entry["extensions"] = extensions

    sources.append(entry)
    config["sources"] = sources
    save_config(project_root, config)
    return "added"


def list_sources(project_root: Path) -> list[dict]:
    """List registered sources from .rtfm/config.json.

    Args:
        project_root: Project root directory.

    Returns:
        List of source dicts with path, corpus, extensions.
    """
    config = load_config(project_root)
    return config.get("sources", [])


def remove_source(
    project_root: Path,
    path: str | None = None,
    corpus: str | None = None,
) -> int:
    """Remove matching sources from .rtfm/config.json. Returns how many were
    removed.

    The counterpart to :func:`add_source`. Matching:

    * ``path`` + ``corpus`` → entries matching **both**,
    * ``path`` only         → entries with that path, any corpus,
    * ``corpus`` only       → **every** entry in that corpus.

    At least one of ``path`` / ``corpus`` must be given. The path is matched
    both resolved and as-stored, so a source whose directory no longer exists
    (deleted upstream, or a mount that is down) can still be unregistered —
    the whole point of removal is often that the target is gone.
    """
    if path is None and corpus is None:
        raise ValueError("remove_source requires a path and/or a corpus")

    config = load_config(project_root)
    sources = config.get("sources", [])
    resolved = str(Path(path).resolve()) if path is not None else None

    def _matches(src: dict) -> bool:
        if corpus is not None and src.get("corpus") != corpus:
            return False
        if resolved is not None and src.get("path") not in (resolved, path):
            return False
        return True

    kept = [s for s in sources if not _matches(s)]
    removed = len(sources) - len(kept)
    if removed:
        config["sources"] = kept
        save_config(project_root, config)
    return removed
