"""Unit tests for the OCR daemon helpers.

Covers the on-disk contract (ocr_state.json), the PID liveness check,
and the human-readable status renderer. The actual subprocess fork in
``rtfm sync --ocr`` is exercised manually — too brittle as a unit test
(real fork, real `marker` install, real DB).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from rtfm.core.ocr_daemon import (
    OCRState,
    _now_iso,
    clear_state,
    daemon_running,
    format_progress,
    pid_alive,
    read_state,
    write_state,
)


def test_pid_alive_returns_true_for_self():
    assert pid_alive(os.getpid()) is True


def test_pid_alive_returns_false_for_garbage():
    # Pick a PID very unlikely to exist. Linux PID max is normally 4_194_303.
    assert pid_alive(7_777_777) is False


def test_pid_alive_handles_zero_and_negative():
    assert pid_alive(0) is False
    assert pid_alive(-1) is False


def test_read_state_returns_none_when_absent(tmp_path):
    assert read_state(tmp_path) is None


def test_write_then_read_state_roundtrip(tmp_path):
    s = OCRState(
        pid=12345,
        status="running",
        total=10,
        done=3,
        current_file="scan.pdf",
        started_at=_now_iso(),
        last_update=_now_iso(),
    )
    write_state(tmp_path, s)
    loaded = read_state(tmp_path)
    assert loaded is not None
    assert loaded.pid == 12345
    assert loaded.status == "running"
    assert loaded.done == 3
    assert loaded.current_file == "scan.pdf"


def test_write_state_is_atomic_via_rename(tmp_path):
    """The state file is written via a sibling .tmp and rename so concurrent
    readers never see a half-written JSON."""
    s = OCRState(
        pid=1, status="running", total=1, done=0,
        current_file="", started_at="", last_update="",
    )
    write_state(tmp_path, s)
    # Final file present, sibling .tmp gone after rename
    assert (tmp_path / "ocr_state.json").exists()
    assert not any(tmp_path.glob("ocr_state.json.tmp*"))


def test_clear_state_removes_file(tmp_path):
    s = OCRState(
        pid=1, status="running", total=1, done=0,
        current_file="", started_at="", last_update="",
    )
    write_state(tmp_path, s)
    assert (tmp_path / "ocr_state.json").exists()
    clear_state(tmp_path)
    assert not (tmp_path / "ocr_state.json").exists()


def test_clear_state_is_idempotent(tmp_path):
    # Should not raise even if no file is there.
    clear_state(tmp_path)


def test_daemon_running_detects_self_as_alive(tmp_path):
    s = OCRState(
        pid=os.getpid(),
        status="running",
        total=10,
        done=2,
        current_file="x.pdf",
        started_at=_now_iso(),
        last_update=_now_iso(),
    )
    write_state(tmp_path, s)
    live = daemon_running(tmp_path)
    assert live is not None
    assert live.pid == os.getpid()


def test_daemon_running_returns_none_when_pid_dead(tmp_path):
    s = OCRState(
        pid=7_777_777,  # garbage PID
        status="running",
        total=10, done=2, current_file="", started_at="", last_update="",
    )
    write_state(tmp_path, s)
    assert daemon_running(tmp_path) is None


def test_daemon_running_returns_none_when_status_finished(tmp_path):
    s = OCRState(
        pid=os.getpid(),
        status="finished",
        total=10, done=10, current_file="", started_at="", last_update="",
    )
    write_state(tmp_path, s)
    assert daemon_running(tmp_path) is None


def test_format_progress_running_includes_pct_and_pid():
    s = OCRState(
        pid=12345, status="running",
        total=10, done=3, current_file="scan.pdf",
        started_at=_now_iso(), last_update=_now_iso(),
    )
    line = format_progress(s)
    assert "PID 12345" in line
    assert "3/10" in line
    assert "30%" in line
    assert "scan.pdf" in line


def test_format_progress_crashed_suggests_resume():
    s = OCRState(
        pid=12345, status="crashed",
        total=10, done=3, current_file="",
        started_at=_now_iso(), last_update=_now_iso(),
    )
    line = format_progress(s)
    assert "interrupted" in line.lower()
    assert "rtfm sync --ocr" in line


def test_read_state_returns_none_on_malformed_json(tmp_path):
    (tmp_path / "ocr_state.json").write_text("{not json at all", encoding="utf-8")
    assert read_state(tmp_path) is None
