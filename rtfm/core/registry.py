"""The list of projects the supervisor serves.

A project with an index but no line here is never scanned: whatever it held
the day it was created is all it will ever hold, apart from the files an
agent happens to edit. Nothing fails and nothing says so, which is why this
list has been at the bottom of more than one "the index stopped moving".

Two things kept projects off it. Enrolment used to live inside the worker's
command-line module, so the plugin's hooks — which create indexes at session
start and feed them at the end of every turn — never imported it and never
enrolled anything: a monorepo created on 2026-09-07 was used by agents for a
week and never scanned once. And the path to this file was defined twice, so
a test that redirected one copy still wrote to the developer's real list
through the other: thirty-three temporary test directories accumulated in it.

So the list has one module, light enough for a hook to import without
pulling in the supervisor, and one path, patched in one place.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from rtfm.core.portable import open_lock_file, try_lock_exclusive, unlock

#: Read at call time by every function below, so redirecting it redirects
#: all of them.
REGISTRY_PATH = Path.home() / ".rtfm" / "workers.json"


def load() -> list[str]:
    """Every enrolled ``.rtfm/`` directory, as recorded. Empty on any doubt."""
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        return list(data.get("projects", []))
    except (OSError, ValueError, AttributeError):
        return []


def save(projects: list[str]) -> None:
    """Replace the list. Written beside the file and renamed into place, so
    a reader never catches it half-written and concludes the fleet is empty."""
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    cleaned = sorted({p for p in projects if p})
    tmp = REGISTRY_PATH.with_suffix(f".json.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"projects": cleaned}, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, REGISTRY_PATH)


@contextmanager
def lock(timeout: float = 1.0):
    """Hold the list for a read-modify-write, or give up after *timeout*.

    Enrolling reads the whole list, appends one entry and writes it back.
    Unsynchronised, two enrolments that overlap end with the second one's
    list, which does not contain the first one's project: measured, eight
    projects of a sixteen-repository fleet dropped that way. Yields ``True``
    when held; ``False`` after the timeout, so a hook or an editor save is
    never kept waiting — the caller skips the write and the next one retries.
    """
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = open_lock_file(REGISTRY_PATH.with_suffix(".lock"))
    try:
        deadline = time.monotonic() + timeout
        while True:
            if try_lock_exclusive(fd):
                try:
                    yield True
                finally:
                    unlock(fd)
                return
            if time.monotonic() >= deadline:
                yield False
                return
            time.sleep(0.02)
    finally:
        os.close(fd)


def is_enrolled(rtfm_dir: Path | str) -> bool:
    """Whether the supervisor will ever look at this project."""
    try:
        return str(Path(rtfm_dir).resolve()) in load()
    except OSError:
        return False


def register(rtfm_dir: Path | str) -> bool:
    """Enrol a ``.rtfm/`` directory. Idempotent.

    Returns ``True`` when the project is on the list afterwards, ``False``
    when it could not be put there. It never raises — a hook must not fail
    over this — but it no longer hides the outcome either: the silence of
    the old version is exactly how a project went unserved for a week.
    """
    try:
        path = str(Path(rtfm_dir).resolve())
        if path in load():
            return True  # nothing to write, so no lock to take
        with lock() as held:
            if not held:
                return False
            current = load()
            if path not in current:
                current.append(path)
                save(current)
        return True
    except OSError:
        return False
