"""Where an index may be created.

An index belongs to one project, created where that project lives. Created
anywhere else it indexes other projects a second time, inside one file, and
the damage is proportional to how much sits below it. It has happened three
times on one machine, each time with nothing to stop it:

- 2026-07-29 — ``~/.rtfm`` indexed the whole home directory, and
  ``~/dev/.rtfm`` the whole development tree: a duplicate of every project,
  their dependencies included, 9.9 GB. The first also shared its directory
  with RTFM's own global state, so removing it removed the project list.
- earlier — a 27 GB index of twenty-six already-indexed projects, and three
  days of scanning.
- 2026-09-07 — ``~/dev/.rtfm`` again, created by the plugin at the start of a
  session opened at the root of the tree.

Each creator indexed wherever it was pointed, because the rule lived nowhere.
It lives here, and every path that creates a project index asks it first.
"""
from __future__ import annotations

from pathlib import Path

#: Directories never walked when looking for projects nested below: they
#: hold dependencies, builds and caches, not projects of the user's own.
NEVER_WALK = frozenset({
    "node_modules", ".git", ".venv", "venv", "__pycache__", ".rtfm",
    "dist", "build", ".cache", ".tox", ".mypy_cache", "target",
})
WALK_DEPTH = 3
WALK_BUDGET = 5000


def refusal_to_index(root: Path | str) -> str | None:
    """Why *root* must not get an index of its own, or ``None`` if it may.

    Refused: a filesystem root, a home directory or anything above one, a
    directory inside an index directory, and a directory that already holds
    an indexed project somewhere below it. The last is decided by a bounded
    walk; a tree too large to walk within budget is not refused on that
    alone, since size is not evidence.
    """
    root = Path(root).resolve()

    # The rule is about creating an index. A project that already has its
    # own gains nothing new from being initialised again, and refusing would
    # lock out real projects that happen to hold a copy of another one — a
    # snapshot directory with its index inside, found in three of them.
    if (root / ".rtfm" / "library.db").is_file():
        return None

    if root == Path(root.anchor):
        return "the root of the filesystem is not a project"
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        home = None
    if home is not None and (root == home or root in home.parents):
        return "a home directory, or one above it, is not a project"
    if ".rtfm" in root.parts:
        return "it is inside an index directory"

    budget = WALK_BUDGET
    stack = [(root, 0)]
    while stack and budget > 0:
        here, depth = stack.pop()
        try:
            children = [c for c in here.iterdir()
                        if c.is_dir() and not c.is_symlink()]
        except OSError:
            continue
        for child in children:
            budget -= 1
            if child.name in NEVER_WALK:
                continue
            if (child / ".rtfm" / "library.db").is_file():
                return (f"it already contains an indexed project ({child}) — "
                        f"index each project where it lives")
            if depth + 1 < WALK_DEPTH:
                stack.append((child, depth + 1))
    return None
