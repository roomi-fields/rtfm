"""Three things a real Windows machine found that this one could not.

0.37.0 was confirmed working on Windows 11 by the reporter of issue #8 — the
lock, a stale lock file, the graceful drain, all verified against `tasklist`
rather than against RTFM's own claims. Three defects came back with the
confirmation, and none of them is about locking:

* ``rtfm status`` died half-way through its own output. A redirected stream
  on Windows falls back to the legacy code page, which cannot encode the
  marks the "optional extras" table prints, so the command that was supposed
  to prove the fix crashed on a `UnicodeEncodeError` instead.
* ``worker status`` reported a supervisor running for seconds after the
  process had genuinely gone. Windows releases a byte-range lock when its
  holder exits, but not synchronously.
* ``rtfm sync`` indexed nothing and said "nothing to do", exit 0, because
  every configured source path pointed inside the Linux container the
  reporter had used to work around the original bug.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from rtfm.core import supervisor as sup_mod


class TestOutputSurvivesALegacyCodePage:
    """A console encoding must not be able to end a command."""

    def _run(self, argv: list[str], encoding: str):
        """Run the CLI with its output pipe forced to *encoding*, which is
        what a redirected stream does on Windows."""
        code = (
            "import sys\n"
            f"sys.stdout.reconfigure(encoding={encoding!r})\n"
            f"sys.argv = {argv!r}\n"
            "from rtfm.cli import main\n"
            "main()\n"
        )
        return subprocess.run([sys.executable, "-c", code],
                              capture_output=True, timeout=180,
                              cwd=str(Path(__file__).resolve().parents[2]))

    def test_status_no_longer_dies_on_its_own_output(self, tmp_path):
        """The exact failure: cp1252 cannot hold U+2717, and the traceback
        landed in the middle of a table the user was reading."""
        from rtfm.core.library import Library
        db = tmp_path / "library.db"
        Library(str(db)).close()

        r = self._run(["rtfm", "status", "--db", str(db)], "cp1252")
        assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
        assert b"Optional extras" in r.stdout

    def test_the_two_marks_stay_different(self, tmp_path):
        """A replacement character would answer "installed?" with the same
        glyph either way and turn the table into a lie."""
        from rtfm.core.library import Library
        db = tmp_path / "library.db"
        Library(str(db)).close()

        r = self._run(["rtfm", "status", "--db", str(db)], "cp1252")
        text = r.stdout.decode("utf-8", "replace")
        extras = text.split("Optional extras")[-1]
        assert "\u2713" in extras or "\u2717" in extras
        assert "\ufffd" not in extras and "?" not in extras.splitlines()[1]

    def test_a_stream_that_carries_everything_is_left_alone(self):
        """No reconfiguration where none is needed — a UTF-8 stream must
        keep the encoding it was given."""
        from rtfm.cli import _make_output_printable

        before = sys.stdout.encoding
        _make_output_printable()
        assert sys.stdout.encoding == before

    def test_a_stream_that_cannot_reconfigure_is_not_a_crash(self, monkeypatch):
        """Anything can be handed to us as stdout, including something with
        no reconfigure at all."""
        from rtfm.cli import _make_output_printable

        monkeypatch.setattr(sys, "stdout", io.StringIO())
        monkeypatch.setattr(sys, "stderr", io.StringIO())
        _make_output_printable()          # must simply not raise


class TestLivenessDoesNotOutliveTheHolder:
    """Liveness comes from the lock. On Windows that is true only *eventually*
    — the documented wording for releasing a byte-range lock at process exit
    is that how long it takes "depends upon available system resources"."""

    @pytest.fixture
    def home(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sup_mod, "_RTFM_HOME", tmp_path)
        monkeypatch.setattr(sup_mod, "SUPERVISOR_LOCK",
                            tmp_path / "supervisor.lock")
        monkeypatch.setattr(sup_mod, "SUPERVISOR_STATE",
                            tmp_path / "supervisor_state.json")
        monkeypatch.setattr(sup_mod, "SUPERVISOR_STOP",
                            tmp_path / "supervisor.stop")
        return tmp_path

    def test_a_lock_still_held_by_a_dead_holder_reads_as_free(
            self, home, monkeypatch):
        """The Windows lag window, reproduced by the only means available
        here: the lock genuinely held, its holder reported gone."""
        monkeypatch.setattr(sup_mod, "pid_alive", lambda pid: False)
        with sup_mod.SupervisorLock():
            assert sup_mod._lock_holder_pid() is None
            assert sup_mod.supervisor_running() is None

    def test_a_live_holder_still_reads_as_running(self, home):
        with sup_mod.SupervisorLock():
            assert sup_mod._lock_holder_pid() == os.getpid()
            assert sup_mod.supervisor_running() is not None

    def test_an_unstamped_lock_claims_nobody(self, home, monkeypatch):
        """No PID, no claim — never guess at one."""
        (home / "supervisor.lock").write_bytes(b"")
        assert sup_mod._lock_holder_pid() is None


class TestAConfiguredSourceThatIsNotThere:
    """Silence here cost the reporter a working install: every source path
    pointed inside a container, so `sync` skipped them all and exited 0."""

    def _project(self, tmp_path, sources: list[dict]) -> Path:
        from rtfm.core.library import Library
        rtfm_dir = tmp_path / ".rtfm"
        rtfm_dir.mkdir(parents=True)
        Library(str(rtfm_dir / "library.db")).close()
        (rtfm_dir / "config.json").write_text(
            json.dumps({"sources": sources}), encoding="utf-8")
        return tmp_path

    def _run(self, cwd: Path, argv: list[str]):
        # SystemExit is left to propagate: `sys.exit("message")` is how the
        # CLI reports a broken configuration, and catching it here would
        # swallow the very message under test.
        code = (f"import sys; sys.argv = {argv!r}\n"
                "from rtfm.cli import main\n"
                "main()\n")
        env = {**os.environ,
               "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
        return subprocess.run([sys.executable, "-c", code],
                              capture_output=True, text=True, timeout=180,
                              cwd=str(cwd), env=env)

    def test_sync_fails_loudly_when_no_source_exists(self, tmp_path):
        """Not "nothing to do": the configuration is broken and nothing was
        indexed. An automation reading the exit code has to learn that."""
        root = self._project(tmp_path, [{"path": "/repo", "corpus": "default"}])
        r = self._run(root, ["rtfm", "sync", "--dry-run"])

        assert r.returncode != 0, r.stdout
        assert "/repo" in r.stdout
        assert "not on disk" in r.stdout
        assert "config.json" in (r.stderr + r.stdout)

    def test_the_valid_sources_are_still_synced(self, tmp_path):
        """One bad path must not stop the others — but it must be said."""
        good = tmp_path / "docs"
        good.mkdir()
        root = self._project(tmp_path, [
            {"path": "/repo", "corpus": "ghost"},
            {"path": str(good), "corpus": "real"},
        ])
        r = self._run(root, ["rtfm", "sync", "--dry-run"])

        assert r.returncode == 0, r.stderr
        assert "not on disk" in r.stdout
        assert "1 source(s) skipped" in r.stdout
        assert "would enqueue 1 P0 scan job" in r.stdout

    def test_a_project_with_no_sources_is_not_an_error(self, tmp_path):
        """Nothing configured is nothing to do, and always has been."""
        root = self._project(tmp_path, [])
        # An empty source list falls back to the project root itself, which
        # exists — so this stays the quiet path.
        r = self._run(root, ["rtfm", "sync", "--dry-run"])
        assert r.returncode == 0, r.stderr
        assert "not on disk" not in r.stdout

    def test_the_listing_marks_what_is_missing(self, tmp_path):
        """`rtfm sources` is where someone looks to find out why."""
        root = self._project(tmp_path, [{"path": "/repo", "corpus": "default"}])
        r = self._run(root, ["rtfm", "sources"])

        assert "NOT ON DISK" in r.stdout
        assert "1 source(s) above are not on disk" in r.stdout
