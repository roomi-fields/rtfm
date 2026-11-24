"""A temporary directory is never a project.

A session started in an agent's scratch directory (under /tmp) got it
indexed and enrolled: 494 scratch files, 59 488 passages to embed, and the
burst slowed every project on the machine for an hour. Nothing durable lives
in a temporary directory, so RTFM neither creates an index there, nor enrols
one, nor serves one an older version enrolled.
"""
from __future__ import annotations

import json

import pytest

from rtfm.core import placement, registry


@pytest.fixture
def temp_root(tmp_path, monkeypatch):
    """Make *tmp_path/temp* the system's temporary directory."""
    root = tmp_path / "temp"
    root.mkdir()
    monkeypatch.setattr(placement, "temp_roots", lambda: (root.resolve(),))
    return root


def test_a_directory_under_the_temporary_root_is_temporary(temp_root, tmp_path):
    scratch = temp_root / "claude-1000" / "session" / "scratchpad"
    scratch.mkdir(parents=True)
    assert placement.is_temporary(scratch)
    assert placement.is_temporary(temp_root)
    elsewhere = tmp_path / "dev" / "projet"
    elsewhere.mkdir(parents=True)
    assert not placement.is_temporary(elsewhere)


def test_no_index_is_created_in_a_temporary_directory(temp_root):
    scratch = temp_root / "scratchpad"
    scratch.mkdir()
    assert placement.refusal_to_index(scratch) == \
        "a temporary directory is not a project"


def test_a_temporary_directory_is_never_enrolled(temp_root):
    rtfm_dir = temp_root / "scratchpad" / ".rtfm"
    rtfm_dir.mkdir(parents=True)
    (rtfm_dir / "library.db").touch()
    assert registry.register(rtfm_dir) is False
    assert str(rtfm_dir.resolve()) not in registry.load()


def test_the_supervisor_lets_go_of_one_enrolled_before(temp_root, tmp_path):
    from rtfm.core.supervisor import Supervisor

    kept = tmp_path / "dev" / "projet" / ".rtfm"
    kept.mkdir(parents=True)
    old = temp_root / "scratchpad" / ".rtfm"
    old.mkdir(parents=True)
    reg = tmp_path / "workers.json"
    reg.write_text(json.dumps({"projects": [str(kept), str(old)]}),
                   encoding="utf-8")

    sup = Supervisor(registry_path=reg, max_concurrent=1)
    try:
        sup._sync_registry()
        assert sup._wanted == {str(kept)}
    finally:
        sup._opener.shutdown(wait=True)
