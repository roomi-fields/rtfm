"""Reaching another project's index by name.

RTFM resolves its database from the working directory, which is right for
the ordinary case and wrong for the one that matters most in a workshop of
several repositories: the knowledge that binds them together does not live
in any of them. A rule that decides how sixteen repositories work is kept
once, somewhere shared, and an agent working inside one of them cannot see
it — its search resolves to its own index, the shared one is not in it, and
the query comes back empty.

An empty answer reads as "there is no such rule". Measured on 2026-09-06: an
agent asked whether a project rule settled a technical question, found
nothing, concluded that nothing settled it, and came within one step of
deciding alone what had already been decided a week earlier — the rule
existed, dated, and even prescribed the order of the steps to take.

So the registry the supervisor already keeps is used for a second purpose:
naming. Every enrolled project has a directory, its directory has a name,
and that name is enough to say which index a question is about.
"""
from __future__ import annotations

import json
from pathlib import Path


class UnknownProject(Exception):
    """Raised with the names that *are* reachable — an error that lists the
    alternatives turns a dead end into the next query."""


def _registry_path() -> Path:
    from rtfm.core.supervisor import REGISTRY_PATH
    return REGISTRY_PATH


def known_projects() -> dict[str, Path]:
    """Every enrolled project, by name, that still has an index on disk.

    A name is a directory name, so two projects can want the same one — a
    working tree and its published copy, most often. The registry order is
    stable, so the answer is too; :func:`resolve_project_db` is the one that
    refuses to guess between them.
    """
    try:
        entries = json.loads(
            _registry_path().read_text(encoding="utf-8"))["projects"]
    except (OSError, ValueError, KeyError):
        return {}
    found: dict[str, Path] = {}
    for entry in entries:
        rtfm_dir = Path(entry)
        db = rtfm_dir / "library.db"
        if not db.is_file():
            continue
        found.setdefault(rtfm_dir.parent.name, db)
    return found


def candidates(name: str) -> list[Path]:
    """Every index enrolled under *name*, in registry order."""
    try:
        entries = json.loads(
            _registry_path().read_text(encoding="utf-8"))["projects"]
    except (OSError, ValueError, KeyError):
        return []
    return [Path(e) / "library.db" for e in entries
            if Path(e).parent.name == name and (Path(e) / "library.db").is_file()]


def resolve_project_db(name: str) -> Path:
    """The index to answer a question about the project called *name*.

    Two projects sharing a name is not an error to resolve by picking one:
    a working tree and its published copy hold different content, and
    answering from the wrong one is worse than saying so. The exception
    carries both paths.
    """
    name = (name or "").strip()
    if not name:
        raise UnknownProject("no project named")

    # A path settles what a name cannot. Two projects share a name whenever
    # a working tree is published alongside itself, and they hold different
    # content — so the way out of that ambiguity has to be sayable in the
    # same argument that caused it.
    if "/" in name or "\\" in name or name.startswith("~"):
        root = Path(name).expanduser()
        for db in (root, root / "library.db", root / ".rtfm" / "library.db"):
            if db.is_file():
                return db
        raise UnknownProject(f"No index under {name!r}.")

    matches = candidates(name)
    if not matches:
        known = sorted(known_projects())
        listed = ", ".join(known) if known else "none"
        raise UnknownProject(
            f"No index for a project called {name!r}. Reachable: {listed}.")
    if len(matches) > 1:
        paths = "\n  ".join(str(p.parent) for p in matches)
        raise UnknownProject(
            f"{len(matches)} projects are called {name!r}; say which one by "
            f"its path instead:\n  {paths}")
    return matches[0]
