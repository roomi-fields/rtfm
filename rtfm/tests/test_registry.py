"""One list of projects, one path to it, and a test suite that stays out of it.

The supervisor serves the projects on this list and no others. Two defects
kept projects off it, or put the wrong ones on it, without a sound. The
path was defined twice, so a test redirecting one copy still wrote to the
developer's real list through the other: thirty-three temporary test
directories accumulated there. And enrolment lived in the worker's
command-line module, where the plugin's hooks never reached it: a monorepo
used by agents for a week was never scanned once.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from rtfm.core import registry

ROOT = Path(__file__).resolve().parents[2]


class TestOneHome:

    def test_the_old_copies_are_gone(self):
        import rtfm.cli_worker as cw
        import rtfm.core.supervisor as sup
        for name in ("_REGISTRY", "_load_registry", "_save_registry",
                     "_registry_lock", "_register_project"):
            assert not hasattr(cw, name), f"cli_worker.{name} still has a home"
        assert not hasattr(sup, "REGISTRY_PATH"), "a second path to the list"

    def test_no_other_module_builds_the_path(self):
        offenders = []
        sources = list((ROOT / "rtfm").rglob("*.py")) + list((ROOT / "hooks").glob("*.py"))
        for f in sources:
            if "tests" in f.parts or f.name == "registry.py":
                continue
            text = f.read_text(encoding="utf-8")
            if '/ "workers.json"' in text or "/ 'workers.json'" in text:
                offenders.append(str(f.relative_to(ROOT)))
        assert not offenders, f"the list's path is built outside its module: {offenders}"


class TestTheSuiteStaysOutOfTheRealList:

    def test_the_list_is_redirected(self):
        assert registry.REGISTRY_PATH != Path.home() / ".rtfm" / "workers.json"

    def test_a_command_that_enrols_writes_to_the_redirected_list(self, tmp_path):
        """The shape of the leak: the caller imports its own copy at call
        time, so patching a name on the caller's module changes nothing."""
        from rtfm.cli_worker import ensure_worker_running

        rtfm_dir = tmp_path / "projet" / ".rtfm"
        rtfm_dir.mkdir(parents=True)
        ensure_worker_running(rtfm_dir)

        assert registry.is_enrolled(rtfm_dir)
        real = Path.home() / ".rtfm" / "workers.json"
        if real.exists():
            assert str(rtfm_dir.resolve()) not in real.read_text(encoding="utf-8")


class TestEnrolment:

    def test_it_says_when_it_worked(self, tmp_path):
        rtfm_dir = tmp_path / "p" / ".rtfm"
        rtfm_dir.mkdir(parents=True)
        assert not registry.is_enrolled(rtfm_dir)
        assert registry.register(rtfm_dir) is True
        assert registry.is_enrolled(rtfm_dir)

    def test_enrolling_twice_is_still_success(self, tmp_path):
        rtfm_dir = tmp_path / "p" / ".rtfm"
        rtfm_dir.mkdir(parents=True)
        registry.register(rtfm_dir)
        assert registry.register(rtfm_dir) is True
        assert registry.load().count(str(rtfm_dir.resolve())) == 1

    def test_it_says_when_it_could_not(self, tmp_path, monkeypatch):
        """The old version returned nothing and swallowed everything — the
        silence that let a project go unserved for a week."""
        monkeypatch.setattr(registry, "try_lock_exclusive", lambda fd: False)
        rtfm_dir = tmp_path / "p" / ".rtfm"
        rtfm_dir.mkdir(parents=True)
        started = time.monotonic()
        assert registry.register(rtfm_dir) is False
        assert time.monotonic() - started < 5.0, "a hook must not be kept waiting"

    def test_a_missing_list_is_an_empty_one(self, tmp_path, monkeypatch):
        monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "absent.json")
        assert registry.load() == []

    def test_a_torn_list_is_an_empty_one(self, tmp_path, monkeypatch):
        torn = tmp_path / "workers.json"
        torn.write_text('{"projects": ["/a", ', encoding="utf-8")
        monkeypatch.setattr(registry, "REGISTRY_PATH", torn)
        assert registry.load() == []
