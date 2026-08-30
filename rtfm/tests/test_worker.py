"""Tests for the surviving worker-module helpers.

The per-project ``Worker`` loop was retired at 0.25 in favour of the
mutualised :mod:`rtfm.core.supervisor` (see ``test_supervisor.py``). What
stays in :mod:`rtfm.core.worker` is a set of shared primitives — here we
cover the memory-limit resolver the supervisor relies on.
"""
from __future__ import annotations


def test_memory_limit_resolver_reads_env(monkeypatch):
    """RTFM_WORKER_MEMORY_LIMIT_GB overrides the default; an empty or
    non-positive value falls back / disables the cap."""
    from rtfm.core import worker as _wm
    monkeypatch.delenv("RTFM_WORKER_MEMORY_LIMIT_GB", raising=False)
    assert _wm._resolve_memory_limit_gb() == _wm.WORKER_MEMORY_LIMIT_GB
    monkeypatch.setenv("RTFM_WORKER_MEMORY_LIMIT_GB", "12")
    assert _wm._resolve_memory_limit_gb() == 12.0
    monkeypatch.setenv("RTFM_WORKER_MEMORY_LIMIT_GB", "0")
    assert _wm._resolve_memory_limit_gb() == 0.0  # opt-out
    monkeypatch.setenv("RTFM_WORKER_MEMORY_LIMIT_GB", "garbage")
    assert _wm._resolve_memory_limit_gb() == _wm.WORKER_MEMORY_LIMIT_GB


class TestADeadSupervisorSaysWhatIsWaiting:
    """"supervisor not running" on its own explains nothing.

    When it dies the queue simply stops moving, and the person watching an
    index that no longer advances has to work out for themselves that the two
    facts are one fact. Status now says how much work is stranded.
    """

    def _project_with_jobs(self, tmp_path, name, pending):
        from rtfm.core.library import Library
        from rtfm.core.queue import Queue

        rtfm_dir = tmp_path / name / ".rtfm"
        rtfm_dir.mkdir(parents=True)
        db = rtfm_dir / "library.db"
        Library(str(db)).close()
        q = Queue(str(db))
        for i in range(pending):
            q.enqueue("ingest", {"filepath": f"f{i}.md", "corpus": "c"})
        q.close()
        return str(rtfm_dir)

    def test_it_counts_the_stranded_jobs(self, tmp_path, monkeypatch, capsys):
        import rtfm.cli_worker as cw

        entries = [self._project_with_jobs(tmp_path, "alpha", 3),
                   self._project_with_jobs(tmp_path, "beta", 1)]
        monkeypatch.setattr(cw, "_load_registry", lambda: entries)

        cw._report_stalled_work()
        out = capsys.readouterr().out
        assert "4 job(s) waiting in 2 project(s)" in out
        assert "alpha (3)" in out
        assert "rtfm worker start" in out

    def test_it_stays_quiet_when_nothing_is_waiting(
            self, tmp_path, monkeypatch, capsys):
        import rtfm.cli_worker as cw

        entries = [self._project_with_jobs(tmp_path, "idle", 0)]
        monkeypatch.setattr(cw, "_load_registry", lambda: entries)

        cw._report_stalled_work()
        assert capsys.readouterr().out == ""
