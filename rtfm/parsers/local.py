"""Load project-local Python parsers from ``.rtfm/parsers/*.py``.

This is the Python counterpart of the declarative ``.rtfm/mappings/``
system: drop a module that registers a parser (via
``@ParserRegistry.register``) into a project's ``.rtfm/parsers/``
directory and RTFM picks it up **for that project only** — no core
release needed. It is what keeps format-specific parsers (a single
dictionary, one company's export format, a bespoke log layout) out of
the shipped package.

Security posture: this ``exec``s Python found in the project's own
``.rtfm/`` directory — the same trust level as the repository's own
source that RTFM already imports and runs. Nothing is fetched or run
from outside the project root, and files whose name starts with ``_``
are skipped. A parser that raises at import time is silently skipped so
one bad drop-in never breaks a sync.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Callable, Optional

# Resolved paths already loaded in this process, so constructing several
# Library instances (the worker makes one per job) doesn't re-exec — and
# thus doesn't register duplicate parser classes.
_loaded: set[str] = set()


def load_local_parsers(
    directory: Path,
    log: Optional[Callable[[str], None]] = None,
) -> int:
    """Import every ``*.py`` under ``directory`` for its registration
    side-effects. Returns the number of modules newly loaded.

    Idempotent within a process (guards on the resolved path); missing
    or non-directory paths are a no-op.
    """
    if not directory.exists() or not directory.is_dir():
        return 0

    count = 0
    for f in sorted(directory.glob("*.py")):
        if f.name.startswith("_"):
            continue
        key = str(f.resolve())
        if key in _loaded:
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"rtfm_local_parser_{f.stem}", f)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # runs @ParserRegistry.register
            _loaded.add(key)
            count += 1
            if log:
                log(f"loaded local parser: {f.name}")
        except Exception as exc:  # noqa: BLE001 — one bad file must not break sync
            if log:
                log(f"skipped local parser {f.name}: {exc}")
            continue

    return count
