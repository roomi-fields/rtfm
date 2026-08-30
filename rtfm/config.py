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


def normalize_patterns(value) -> list[str] | None:
    """Coerce a hand-written ``include``/``exclude`` value into a pattern list.

    ``config.json`` is edited by hand at least as often as it is written by
    ``rtfm add``, and the natural thing to type is the same comma-separated
    string the CLI flag takes: ``"exclude": "data/*,build/*"``. A bare string
    is iterable, so every pattern matcher downstream then walked it character
    by character — ``d``, ``a``, ``t``, ``a``, ``/``, ``*`` — and the scan
    silently selected nothing. The only visible trace was ``rtfm sources``
    printing the rule one letter per line.

    Accepting the string and splitting it on commas costs nothing and makes
    the two spellings mean the same thing.

    Args:
        value: A list of patterns, a comma-separated string, or None.

    Returns:
        A list of non-empty patterns, or None when nothing was configured.
    """
    if value is None:
        return None
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        # A number, a dict, anything else: no sane reading. Treat it as
        # unset rather than letting it match nothing in silence.
        return None
    out = [str(p).strip() for p in items]
    out = [p for p in out if p]
    return out or None


def normalize_source(src: dict) -> dict:
    """Return a ``sources`` entry with its selection rules in canonical form."""
    out = dict(src)
    for key in ("include", "exclude"):
        patterns = normalize_patterns(out.get(key))
        if patterns is None:
            out.pop(key, None)
        else:
            out[key] = patterns
    return out


def load_config(project_root: Path) -> dict:
    """Load .rtfm/config.json from a project root.

    Selection rules are normalised on the way out (see
    :func:`normalize_patterns`), so every consumer — scan, sync, doctor,
    ``rtfm sources`` — sees the same canonical lists whether the entry was
    written by ``rtfm add`` or typed by hand.

    Args:
        project_root: Project root directory.

    Returns:
        Config dict (empty dict if file doesn't exist).
    """
    config_path = Path(project_root) / ".rtfm" / "config.json"
    if not config_path.exists():
        return {}
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(config, dict) and isinstance(config.get("sources"), list):
        config["sources"] = [
            normalize_source(s) if isinstance(s, dict) else s
            for s in config["sources"]
        ]
    return config


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


def build_scan_payload(
    src: dict,
    cfg: dict | None = None,
    *,
    force_remove: bool = False,
    honor_gitignore: bool | None = None,
) -> dict:
    """Describe a configured source the way a ``scan`` job needs it.

    The single place that turns a ``sources`` entry into a scan payload.
    Four callers used to build this dict by hand and had drifted apart:
    ``rtfm sync`` dropped ``include``/``exclude`` entirely, so patterns the
    user had registered were silently ignored and excluded files got indexed
    anyway (issue #6). Every enqueue site now goes through here, and a guard
    test fails if a new one starts hand-rolling its own.

    Two conventions matter beyond the field list:

    * **Lexical paths only.** ``os.path.abspath``, never ``Path.resolve()``:
      resolving stats every component, and one source on a dead network
      mount then blocks the caller in uninterruptible I/O. The scan handler
      resolves for real, in a worker thread, where blocking costs one lane.
    * **Defaults are omitted, not written.** The queue deduplicates pending
      jobs on the exact payload JSON, so a payload that spells out
      ``extensions: null`` or ``honor_gitignore: true`` would fail to match
      an identical job enqueued elsewhere. Emitting only what departs from
      the handler's defaults makes the same source produce the same payload
      from every caller.

    Args:
        src: A ``sources`` entry (``path``, ``corpus``, ``extensions``,
            ``include``, ``exclude``, ``honor_gitignore``).
        cfg: The project config, used only for the fallback corpus.
        force_remove: Authorise a bulk delete for this run.
        honor_gitignore: CLI-level override, applied only to sources that
            do not state their own preference.

    Returns:
        The payload dict for a ``scan`` job.
    """
    cfg = cfg or {}
    payload: dict = {
        "root": os.path.abspath(src.get("path", ".")),
        "corpus": src.get("corpus") or cfg.get("corpus") or "default",
    }
    if src.get("extensions"):
        payload["extensions"] = src["extensions"]
    # normalize_patterns again, not only in load_config: `rtfm sync` builds
    # ad-hoc source dicts from CLI flags, and they deserve the same reading.
    include = normalize_patterns(src.get("include"))
    if include:
        payload["include"] = include
    exclude = normalize_patterns(src.get("exclude"))
    if exclude:
        payload["exclude"] = exclude

    effective_gitignore = src.get("honor_gitignore")
    if effective_gitignore is None:
        effective_gitignore = honor_gitignore
    if effective_gitignore is False:
        payload["honor_gitignore"] = False

    if force_remove:
        payload["force_remove"] = True
    return payload


def describe_selection(payload: dict) -> str:
    """One-line summary of the selection rules a scan payload applies.

    An over-broad index used to look exactly like a successful sync: nothing
    in the output said which rules had been applied, so a dropped pattern was
    invisible until you queried the database for paths you thought you had
    excluded. Printing the rules makes that class of failure self-reporting.

    Returns:
        A summary such as ``ext=md exclude=data/*,.agents/*``, or ``"all
        text"`` when the source restricts nothing.
    """
    bits = []
    if payload.get("extensions"):
        bits.append(f"ext={payload['extensions']}")
    if payload.get("include"):
        bits.append("include=" + ",".join(payload["include"]))
    if payload.get("exclude"):
        bits.append("exclude=" + ",".join(payload["exclude"]))
    if payload.get("honor_gitignore") is False:
        bits.append("gitignore off")
    return " ".join(bits) if bits else "all text"


def add_source(
    project_root: Path,
    path: str,
    corpus: str,
    extensions: str | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    honor_gitignore: bool | None = None,
) -> str:
    """Add a source to .rtfm/config.json.

    Resolves the path to absolute. Deduplicates by (resolved path, corpus).

    Args:
        project_root: Project root directory.
        path: Path to the source directory.
        corpus: Corpus name.
        extensions: Comma-separated suffix allow-list (e.g. ".md,.py"). Omit to
            index all text (the default) — a parser is used when one matches,
            else plain text; binary files are skipped.
        include: Selection patterns (prefix/suffix/glob: ``-gr.*``, ``*.bps``,
            ``fixtures/*``). When set, only matching files are indexed.
        exclude: Rejection patterns, same syntax — matched files are skipped.
        honor_gitignore: Pass False to index a directory the project
            deliberately keeps out of version control — heavy PDFs, datasets,
            downloaded corpora. Omit to keep the default (gitignore obeyed).

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
    inc = normalize_patterns(include)
    if inc:
        entry["include"] = inc
    exc = normalize_patterns(exclude)
    if exc:
        entry["exclude"] = exc
    if honor_gitignore is False:
        entry["honor_gitignore"] = False

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
