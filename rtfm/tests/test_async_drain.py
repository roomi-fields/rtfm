"""The end-of-turn and prompt hooks run in the background.

They held every session: measured on one machine over a day, the prompt hook
ran 25 times and hit its 10-second limit 25 times, the end-of-turn hook up to
34 seconds. They now run in the background, which brings three risks the
user accepted and that are held here:

1. the index lags a few seconds behind an edit;
2. two drains can overlap — the second must leave the first alone;
3. a drain can be cut when the session closes — what it took stays queued.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _hook(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_rtfm_hook_{name}", ROOT / "hooks" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def depot(tmp_path, monkeypatch):
    from rtfm.core.library import Library
    root = tmp_path / "depot"
    (root / ".rtfm").mkdir(parents=True)
    Library(str(root / ".rtfm" / "library.db")).close()
    for name in ("a.md", "b.md"):
        (root / name).write_text(f"# {name}\n\nDu texte.\n" * 5, encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "maison")
    return root


def _queue(depot, *names):
    with open(depot / ".rtfm" / "touched_files.tmp", "a", encoding="utf-8") as f:
        for n in names:
            f.write(str(depot / n) + "\n")


def _indexed(depot) -> set[str]:
    import sqlite3
    conn = sqlite3.connect(depot / ".rtfm" / "library.db")
    try:
        return {r[0] for r in conn.execute("SELECT filepath FROM indexed_files")}
    finally:
        conn.close()


def test_both_sync_hooks_run_in_the_background():
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    by_command = {h["command"].split()[-1]: h
                  for event in hooks.values() for m in event for h in m["hooks"]}
    assert by_command["rtfm_sync"].get("async") is True
    assert by_command["rtfm_stop_sync"].get("async") is True
    assert not by_command["rtfm_record_edit"].get("async"), "it only notes a path"


def test_a_drain_indexes_and_empties_the_queue(depot):
    _queue(depot, "a.md")
    _hook("rtfm_stop_sync").main()
    assert _indexed(depot) == {"a.md"}
    assert not (depot / ".rtfm" / "touched_files.tmp").exists()
    assert not list((depot / ".rtfm").glob("touched_files.*.draining"))


def test_a_second_drain_leaves_a_running_one_alone(depot):
    """Risk 2: the lock is held — the second drain leaves at once and takes
    nothing; the queue waits for the next one."""
    from rtfm.core.portable import open_lock_file, try_lock_exclusive, unlock
    import os
    _queue(depot, "a.md")
    fd = open_lock_file(depot / ".rtfm" / "drain.lock")
    assert try_lock_exclusive(fd)
    try:
        _hook("rtfm_stop_sync").main()
        assert _indexed(depot) == set()
        assert (depot / ".rtfm" / "touched_files.tmp").exists()
    finally:
        unlock(fd)
        os.close(fd)
    _hook("rtfm_stop_sync").main()
    assert _indexed(depot) == {"a.md"}


def test_an_edit_noted_during_a_drain_is_not_lost(depot, monkeypatch):
    """The drain takes the queue by renaming it, so a line appended meanwhile
    lands in a fresh queue rather than in a file about to be deleted."""
    hook = _hook("rtfm_stop_sync")
    _queue(depot, "a.md")
    real_claim = hook._claim

    def claim_then_edit(rtfm_dir):
        out = real_claim(rtfm_dir)
        _queue(depot, "b.md")            # the agent edits while we drain
        return out

    monkeypatch.setattr(hook, "_claim", claim_then_edit)
    hook.main()
    assert _indexed(depot) == {"a.md"}
    assert "b.md" in (depot / ".rtfm" / "touched_files.tmp").read_text()
    _hook("rtfm_stop_sync").main()
    assert _indexed(depot) == {"a.md", "b.md"}


def test_a_drain_cut_short_is_taken_up_by_the_next(depot, monkeypatch):
    """Risk 3: the session closes mid-drain; its claimed lines stay behind."""
    hook = _hook("rtfm_stop_sync")
    _queue(depot, "a.md")
    import rtfm.core.sync as sync_mod

    def cut(*a, **k):
        raise KeyboardInterrupt("session closed")

    monkeypatch.setattr(sync_mod, "sync", cut)
    with pytest.raises(KeyboardInterrupt):
        hook.main()
    assert list((depot / ".rtfm").glob("touched_files.*.draining"))
    monkeypatch.undo()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(depot))
    _hook("rtfm_stop_sync").main()
    assert _indexed(depot) == {"a.md"}
    assert not list((depot / ".rtfm").glob("touched_files.*.draining"))


def test_the_prompt_hook_takes_up_a_cut_drain_too(depot):
    (depot / ".rtfm" / "touched_files.4242.draining").write_text(
        str(depot / "a.md") + "\n", encoding="utf-8")
    _hook("rtfm_sync").main()
    assert _indexed(depot) == {"a.md"}


def test_nothing_queued_is_instant(depot):
    import time
    t0 = time.perf_counter()
    _hook("rtfm_sync").main()
    assert time.perf_counter() - t0 < 0.5
