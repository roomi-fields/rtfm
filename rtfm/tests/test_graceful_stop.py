"""Stopping the supervisor means asking it, not killing it.

Each in-flight job is the only writer for its project's database. A
supervisor killed outright is killed mid-write, which is the one thing the
single-writer design exists to prevent — so "stop" has to mean *finish what
you are holding, then exit*.

``SIGTERM`` carried that on Unix and could not carry it anywhere else: on
Windows every signal but the two console events goes straight to
``TerminateProcess``, so asking politely and killing outright were the same
call and ``rtfm worker stop`` halted the supervisor where it stood. The
request is a file the supervisor reads for itself, so there is now one
mechanism on every platform instead of one that worked and one that lied.

The request names its target, which is the part that needs holding down: a
request left behind by a crash must never stop the supervisor that replaces
it, not even after the machine recycles that PID.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from rtfm.core import supervisor as sup_mod
from rtfm.core.library import Library
from rtfm.core.queue import Queue
from rtfm.core.supervisor import (
    STOP_POLL_SECONDS,
    Supervisor,
    clear_stop_request,
    request_stop,
    stop_requested,
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Point every ``~/.rtfm`` artefact at a scratch directory."""
    monkeypatch.setattr(sup_mod, "_RTFM_HOME", tmp_path)
    monkeypatch.setattr(sup_mod, "SUPERVISOR_STOP", tmp_path / "supervisor.stop")
    monkeypatch.setattr(sup_mod, "SUPERVISOR_STATE",
                        tmp_path / "supervisor_state.json")
    monkeypatch.setattr(sup_mod, "SUPERVISOR_LOCK", tmp_path / "supervisor.lock")
    return tmp_path


class TestTheRequestNamesItsTarget:
    def test_a_request_aimed_at_me_is_mine(self, home):
        request_stop(os.getpid())
        assert stop_requested(os.getpid()) is True

    def test_a_request_aimed_at_someone_else_is_left_for_them(self, home):
        """A live process that is not us: not ours to act on, and not ours
        to throw away either."""
        import subprocess
        import sys
        other = subprocess.Popen([sys.executable, "-c",
                                  "import time; time.sleep(30)"])
        try:
            request_stop(other.pid)
            assert stop_requested(os.getpid()) is False
            assert (home / "supervisor.stop").exists()
        finally:
            other.kill()
            other.wait(timeout=30)

    def test_a_request_for_a_process_that_is_gone_is_swept_up(self, home):
        """Nothing else would ever remove it, and left there it would stop
        every future supervisor the moment a PID came round again."""
        request_stop(7_777_777)
        assert stop_requested(os.getpid()) is False
        assert not (home / "supervisor.stop").exists()

    def test_something_we_did_not_write_is_swept_up_too(self, home):
        (home / "supervisor.stop").write_text("stop please\n", encoding="utf-8")
        assert stop_requested(os.getpid()) is False
        assert not (home / "supervisor.stop").exists()

    def test_no_request_at_all(self, home):
        assert stop_requested(os.getpid()) is False


class TestTheSupervisorNoticesWhileItSleeps:
    def _sup(self, home) -> Supervisor:
        registry = home / "workers.json"
        registry.write_text(json.dumps({"projects": []}), encoding="utf-8")
        return Supervisor(registry_path=registry, log=lambda m: None,
                          max_concurrent=1)

    def test_an_idle_sleep_ends_early(self, home):
        """Idle, the loop sleeps five seconds at a time. Waiting that long to
        begin a drain would make every deploy five seconds slower for no
        reason."""
        sup = self._sup(home)
        try:
            request_stop(os.getpid())
            started = time.monotonic()
            sup._sleep(5.0)
            elapsed = time.monotonic() - started

            assert sup._stop is True
            assert elapsed < 1.0, f"took {elapsed:.1f}s to notice"
        finally:
            sup._pool.shutdown(wait=False)

    def test_the_request_is_consumed_when_it_is_seen(self, home):
        """The drain that follows can take as long as the longest job in
        flight; a request still on disk by then would stop the next
        supervisor as well."""
        sup = self._sup(home)
        try:
            request_stop(os.getpid())
            sup._check_stop_request()
            assert sup._stop is True
            assert not (home / "supervisor.stop").exists()
        finally:
            sup._pool.shutdown(wait=False)

    def test_looking_is_throttled(self, home):
        """It is looked for on every pass of a loop that spins hot while work
        is in flight."""
        sup = self._sup(home)
        try:
            sup._check_stop_request()          # takes the time slot
            request_stop(os.getpid())
            assert sup._check_stop_request() is False   # too soon to look
            time.sleep(STOP_POLL_SECONDS + 0.05)
            assert sup._check_stop_request() is True
        finally:
            sup._pool.shutdown(wait=False)


class TestTheWholeLoop:
    """The real ``run()`` loop, asked to stop, on a real project queue."""

    def _project(self, home) -> Path:
        rtfm_dir = home / "proj" / ".rtfm"
        rtfm_dir.mkdir(parents=True)
        Library(str(rtfm_dir / "library.db")).close()
        (home / "workers.json").write_text(
            json.dumps({"projects": [str(rtfm_dir)]}), encoding="utf-8")
        return rtfm_dir

    @pytest.fixture
    def running(self, home, monkeypatch):
        """A supervisor in a thread, with the two things a test cannot have.

        Signal handlers can only be installed from the main thread, and the
        embedding model takes seconds to load and is not what is being
        tested here.
        """
        monkeypatch.setattr(Supervisor, "_install_signal_handlers",
                            lambda self: None)
        monkeypatch.setattr(Supervisor, "_preload_model", lambda self: None)
        respawns: list[object] = []
        monkeypatch.setattr(sup_mod, "_spawn_delayed_supervisor",
                            lambda log: respawns.append(log))

        started: list[Supervisor] = []

        def start():
            """Returns the supervisor and the thread running its loop."""
            sup = Supervisor(registry_path=home / "workers.json",
                             log=lambda m: None, max_concurrent=2)
            started.append(sup)
            thread = threading.Thread(target=sup.run, daemon=True,
                                      name="sup-under-test")
            thread.start()
            return sup, thread

        yield start, respawns

        for sup in started:
            sup._stop = True
            sup._pool.shutdown(wait=False)

    def test_the_job_in_flight_finishes_before_the_exit(
            self, home, monkeypatch, running):
        """The whole point. The handler holds the only write connection to
        that database; cutting it off mid-statement is what a hard kill
        does."""
        rtfm_dir = self._project(home)
        start, respawns = running

        phases: list[str] = []
        entered = threading.Event()

        def slow_handler(job, ctx):
            phases.append("start")
            entered.set()
            time.sleep(1.0)
            phases.append("finish")

        import rtfm.core.handlers as handlers_mod
        monkeypatch.setitem(handlers_mod.HANDLERS, "reconcile", slow_handler)

        q = Queue(rtfm_dir / "library.db")
        try:
            q.enqueue("reconcile", {"marker": "the one under test"})
        finally:
            q.close()

        sup, thread = start()
        assert entered.wait(timeout=60), "the job never started"

        request_stop(os.getpid())
        deadline = time.monotonic() + 60
        while not sup._stop and time.monotonic() < deadline:
            time.sleep(0.05)
        assert sup._stop, "the request was never noticed"

        # The loop leaves through _shutdown, which waits on the pool. Once
        # the thread is gone, every job that started has had its chance —
        # so counting is the whole assertion: a job cut off mid-run leaves
        # a "start" with no "finish". (The supervisor may have dispatched
        # more than one by then; it enqueues its own periodic work.)
        thread.join(timeout=120)
        assert not thread.is_alive(), "the supervisor never exited"
        assert phases[:2] == ["start", "finish"]
        assert phases.count("start") == phases.count("finish"), \
            f"a job was cut off mid-run: {phases}"

        q = Queue(rtfm_dir / "library.db")
        try:
            assert q.stats().get("reconcile", {}).get("done", 0) >= 1
        finally:
            q.close()

    def test_a_requested_stop_does_not_come_back_to_life(
            self, home, monkeypatch, running):
        """Version drift and the memory ceiling exit *to respawn*. Being
        asked to stop must not, or ``worker stop`` would be a restart."""
        self._project(home)
        start, respawns = running

        sup, thread = start()
        request_stop(os.getpid())
        deadline = time.monotonic() + 60
        while not sup._stop and time.monotonic() < deadline:
            time.sleep(0.05)
        assert sup._stop

        thread.join(timeout=120)
        assert not thread.is_alive(), "the supervisor never exited"
        assert respawns == [], "a requested stop scheduled a respawn"


class TestALeftoverRequestStopsNobody:
    """PID reuse makes this reachable: a request naming a supervisor that
    died, and a fresh one handed the same PID.

    The clearing happens as the lock is taken, not a few lines into the
    loop — between acquiring the lock and stamping the PID that makes a
    supervisor addressable. Anywhere later and a ``worker stop`` issued in
    that window would be swallowed instead of obeyed.
    """

    def test_taking_the_lock_clears_what_the_last_holder_left(self, home):
        request_stop(os.getpid())          # as if left behind, naming "us"
        with sup_mod.SupervisorLock():
            assert not (home / "supervisor.stop").exists()
            assert stop_requested(os.getpid()) is False

    def test_a_request_made_afterwards_is_still_obeyed(self, home):
        with sup_mod.SupervisorLock():
            request_stop(os.getpid())
            assert stop_requested(os.getpid()) is True
