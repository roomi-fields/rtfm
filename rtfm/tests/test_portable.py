"""RTFM has to run on the operating systems it says it runs on.

0.35.7 could not run one command on native Windows. ``rtfm/core/supervisor``
imported ``fcntl`` at the top level, the CLI imports the worker module for
every invocation, and so ``rtfm --help`` died in the import machinery before
argparse ever saw an argument — no indexing, no ``init``, nothing (issue #8).

The import was the visible half. Behind it sat four more calls that are
Unix-only or mean something else entirely on Windows, the worst being the
liveness probe: ``os.kill(pid, 0)`` asks a question on Unix and calls
``TerminateProcess`` on Windows, so checking whether the supervisor was alive
would have killed it.

These tests hold the line in both directions: the real lock semantics the
single-supervisor rule depends on (which can only be tested on the platform
running the suite), and the platform-independence of the import graph (which
can be tested anywhere, by taking ``fcntl`` away).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from rtfm.core import portable
from rtfm.core.portable import (
    open_lock_file,
    pid_alive,
    read_stamped_pid,
    stamp_pid,
    try_lock_exclusive,
    unlock,
)

#: Source files that are allowed to touch a platform-specific API.
_PORTABLE = "rtfm/core/portable.py"

#: Calls that are Unix-only, or that mean something different — and worse —
#: on Windows. Each maps to what it costs when it slips through.
_FORBIDDEN = {
    "import fcntl": "crashes every CLI command on Windows at import time",
    "import msvcrt": "the Windows half belongs in one module too",
    "os.pread": "does not exist on Windows",
    "os.pwrite": "does not exist on Windows",
    "signal.SIGKILL": "not defined on Windows — AttributeError, not a kill",
    "start_new_session": "accepted and ignored on Windows; nothing detaches",
}


def _source_files() -> list[Path]:
    root = Path(__file__).resolve().parents[2]
    return [p for p in (root / "rtfm").rglob("*.py")
            if "/tests/" not in p.as_posix()
            and not p.as_posix().endswith(_PORTABLE)]


class TestNothingElseReachesForAPlatform:
    """One module owns the differences, or they come back one import at a
    time — which is exactly how this shipped."""

    @pytest.mark.parametrize("call, cost", sorted(_FORBIDDEN.items()))
    def test_the_call_appears_nowhere_else(self, call, cost):
        offenders = [
            f"{p.name}:{n}"
            for p in _source_files()
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if call in line and not line.lstrip().startswith(("#", "*", '"'))
        ]
        assert not offenders, f"{call} in {offenders} — {cost}"

    def test_the_liveness_probe_is_never_written_by_hand(self):
        """``os.kill(pid, 0)`` probes on Unix and terminates on Windows."""
        import re
        pattern = re.compile(r"os\.kill\([^,)]+,\s*0\s*\)")
        offenders = [p.name for p in _source_files()
                     if pattern.search(p.read_text(encoding="utf-8"))]
        assert not offenders


class TestTheCLIRunsWithoutFcntl:
    """The reported failure, reproduced on this machine by taking ``fcntl``
    away, and then shown to be gone."""

    #: Hides both platform modules from the import system, the way a real
    #: Windows interpreter hides one of them.
    _BLOCK = """
import sys, importlib.abc
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ("fcntl", "msvcrt"):
            raise ModuleNotFoundError("No module named %r" % fullname,
                                      name=fullname)
        return None
for name in ("fcntl", "msvcrt"):
    sys.modules.pop(name, None)
sys.meta_path.insert(0, Blocker())
"""

    def _run(self, tail: str):
        return subprocess.run(
            [sys.executable, "-c", self._BLOCK + tail],
            capture_output=True, text=True, timeout=120)

    def test_importing_the_cli_no_longer_raises(self):
        r = self._run("import rtfm.cli, rtfm.cli_worker;"
                      " print('imported')")
        assert r.returncode == 0, r.stderr
        assert "imported" in r.stdout

    def test_help_reaches_argparse(self):
        """Before the fix the traceback happened at import, so no argument —
        not even ``--help`` — was ever parsed."""
        r = self._run("import sys; sys.argv = ['rtfm', '--help'];"
                      " from rtfm.cli import main;"
                      " sys.exit(0 if main() in (0, None) else 1)")
        assert r.returncode == 0, r.stderr
        assert "usage: rtfm" in r.stdout

    def test_a_read_only_command_still_works(self):
        r = self._run("import sys; sys.argv = ['rtfm', 'schema'];"
                      " from rtfm.cli import main; main()")
        assert r.returncode == 0, r.stderr

    def test_only_locking_itself_refuses_and_it_says_why(self):
        """A platform with neither call cannot keep the supervisor unique.
        It must fail at the lock, loudly, not at import."""
        r = self._run(
            "from rtfm.core.portable import try_lock_exclusive,"
            " LockUnavailable, open_lock_file\n"
            "import tempfile, os\n"
            "fd = open_lock_file(os.path.join(tempfile.mkdtemp(), 'l'))\n"
            "try:\n"
            "    try_lock_exclusive(fd)\n"
            "except LockUnavailable as e:\n"
            "    print('refused:', e)\n")
        assert r.returncode == 0, r.stderr
        assert "refused:" in r.stdout
        assert "unique" in r.stdout


class TestTheLockIsExclusive:
    """What the single-supervisor rule rests on."""

    def test_a_second_holder_is_refused_and_the_first_keeps_it(self, tmp_path):
        path = tmp_path / "supervisor.lock"
        first = open_lock_file(path)
        second = open_lock_file(path)
        try:
            assert try_lock_exclusive(first) is True
            assert try_lock_exclusive(second) is False
            unlock(first)
            assert try_lock_exclusive(second) is True
            unlock(second)
        finally:
            os.close(first)
            os.close(second)

    def test_the_kernel_releases_it_when_the_holder_dies(self, tmp_path):
        """Not politeness — the whole design. A supervisor killed outright
        must not leave a lock that makes the fleet look busy for ever."""
        path = tmp_path / "supervisor.lock"
        child = subprocess.Popen(
            [sys.executable, "-c",
             "import sys, time;"
             f"sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r});"
             "from rtfm.core.portable import open_lock_file,"
             " try_lock_exclusive, stamp_pid;"
             f"fd = open_lock_file({str(path)!r});"
             "assert try_lock_exclusive(fd);"
             "stamp_pid(fd); print('held', flush=True); time.sleep(60)"],
            stdout=subprocess.PIPE, text=True)
        try:
            assert child.stdout.readline().strip() == "held"
            probe = open_lock_file(path)
            try:
                assert try_lock_exclusive(probe) is False
                assert read_stamped_pid(probe) == child.pid
            finally:
                os.close(probe)

            child.kill()
            child.wait(timeout=30)

            probe = open_lock_file(path)
            try:
                deadline = time.monotonic() + 10
                while not try_lock_exclusive(probe):
                    assert time.monotonic() < deadline, "lock never released"
                    time.sleep(0.1)
                unlock(probe)
            finally:
                os.close(probe)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=30)


class TestTheStampedPID:
    """Observability, not liveness — but a wrong PID here would be read by
    ``worker stop``, which signals it."""

    def test_it_round_trips(self, tmp_path):
        fd = open_lock_file(tmp_path / "l")
        try:
            stamp_pid(fd)
            assert read_stamped_pid(fd) == os.getpid()
        finally:
            os.close(fd)

    def test_an_unstamped_file_reads_as_nothing(self, tmp_path):
        fd = open_lock_file(tmp_path / "l")
        try:
            assert read_stamped_pid(fd) is None
        finally:
            os.close(fd)

    def test_garbage_reads_as_nothing_rather_than_a_number(self, tmp_path):
        path = tmp_path / "l"
        path.write_bytes(b"\x00" * 8 + b"not a pid\n")
        fd = open_lock_file(path)
        try:
            assert read_stamped_pid(fd) is None
        finally:
            os.close(fd)

    def test_re_stamping_leaves_the_lock_held(self, tmp_path):
        """On Windows the stamp is written next to a byte that is locked at
        the time. Truncating that byte away would drop the lock."""
        path = tmp_path / "l"
        fd = open_lock_file(path)
        other = open_lock_file(path)
        try:
            assert try_lock_exclusive(fd) is True
            stamp_pid(fd)
            stamp_pid(fd, pid=4242)
            assert read_stamped_pid(fd) == 4242
            assert try_lock_exclusive(other) is False
        finally:
            unlock(fd)
            os.close(fd)
            os.close(other)

    def test_the_position_of_the_descriptor_survives(self, tmp_path):
        """The callers own the descriptor and write to it around these
        calls; ``pread``/``pwrite`` would not exist on Windows to do it in
        one step, so the seek has to be put back."""
        fd = open_lock_file(tmp_path / "l")
        try:
            stamp_pid(fd)
            os.lseek(fd, 0, os.SEEK_END)
            before = os.lseek(fd, 0, os.SEEK_CUR)
            read_stamped_pid(fd)
            assert os.lseek(fd, 0, os.SEEK_CUR) == before
        finally:
            os.close(fd)

    def test_the_payload_never_overlaps_the_locked_byte(self):
        """Unix keeps the format it always had; Windows reserves byte 0
        because a byte-range lock there would refuse a reader those bytes."""
        assert portable.PAYLOAD_OFFSET == (1 if sys.platform == "win32" else 0)


class TestLiveness:
    def test_this_process_is_alive(self):
        assert pid_alive(os.getpid()) is True

    def test_a_pid_nobody_has_is_not(self):
        assert pid_alive(7_777_777) is False

    def test_zero_and_negative_are_not_processes(self):
        assert pid_alive(0) is False
        assert pid_alive(-1) is False

    def test_a_process_that_just_died_reads_as_dead(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait(timeout=30)
        assert pid_alive(child.pid) is False
