"""Nothing RTFM starts may open a window.

Reported from Windows 11 (issue #9): every spawn flashed a console, and 32
orphaned ``conhost.exe`` processes were left behind over one session. The
report blamed the supervisor's own creation flags and proposed adding
``CREATE_NO_WINDOW`` to them, which the ``CreateProcess`` documentation says
is ignored when it accompanies ``DETACHED_PROCESS``.

The cause was one level down, and worse than the report assumed. Detached
means the supervisor has *no console at all* — and a console program started
by a parent without one is given a brand new console by Windows, window and
``conhost.exe`` and all. The supervisor spawns a child interpreter for every
PDF it reads, to keep pdfium's crashes out of its thread pool. So the flashes
were not three, one per ``worker start``: they were one per document.

Two rules follow, and these tests hold both:

* a **detached background process** runs under the windowed interpreter,
  which never gets a console in the first place;
* a **short-lived helper** carries ``CREATE_NO_WINDOW``, where the flag is
  not ignored because nothing detaches it.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from rtfm.core import portable
from rtfm.core.portable import (
    background_python,
    detached_popen_kwargs,
    no_window_popen_kwargs,
)

_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_NO_WINDOW = 0x08000000


@pytest.fixture
def on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")


class TestTheDetachedSupervisor:
    def test_unix_detaches_with_a_new_session(self):
        assert detached_popen_kwargs() == {"start_new_session": True}

    def test_windows_detaches_with_the_creation_flags(self, on_windows):
        assert detached_popen_kwargs() == {
            "creationflags": _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP}

    def test_no_window_is_not_added_there(self, on_windows):
        """It reads like it belongs and it does nothing: ``CreateProcess``
        ignores it alongside ``DETACHED_PROCESS``. Carrying a flag that has
        no effect would only make the next reader believe the problem was
        handled here."""
        flags = detached_popen_kwargs()["creationflags"]
        assert not flags & _CREATE_NO_WINDOW

    def test_the_windowed_interpreter_is_preferred(self, tmp_path, monkeypatch):
        """``python.exe`` is a console program: Windows gives it a console
        whenever its parent has none, which is every spawn from a hook, an
        agent's tool call, or another detached process."""
        exe = tmp_path / "python.exe"
        exe.write_text("")
        (tmp_path / "pythonw.exe").write_text("")
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(sys, "executable", str(exe))

        assert background_python() == str(tmp_path / "pythonw.exe")

    def test_without_it_the_ordinary_interpreter_still_runs(
            self, tmp_path, monkeypatch):
        """A layout that ships no ``pythonw.exe`` must still start a worker —
        a console flash is a nuisance, no indexing at all is not."""
        exe = tmp_path / "python.exe"
        exe.write_text("")
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(sys, "executable", str(exe))

        assert background_python() == str(exe)

    def test_unix_uses_the_interpreter_it_is_running(self):
        assert background_python() == sys.executable


class TestTheShortLivedHelpers:
    def test_unix_needs_nothing(self):
        assert no_window_popen_kwargs() == {}

    def test_windows_suppresses_the_console(self, on_windows):
        assert no_window_popen_kwargs() == {
            "creationflags": _CREATE_NO_WINDOW}


class TestEveryChildIsAccountedFor:
    """The flags are useless if the next spawn site forgets them, and this
    is a package that spawns children as a matter of course: one per PDF, one
    per marker run, one per DJVU, one per supervisor restart."""

    #: Interactive by definition — it attaches to the user's own terminal.
    _INTERACTIVE = {"tail"}

    def _sources(self):
        root = Path(__file__).resolve().parents[2]
        return [p for p in (root / "rtfm").rglob("*.py")
                if "/tests/" not in p.as_posix()
                and not p.as_posix().endswith("rtfm/core/portable.py")]

    def test_no_spawn_is_left_bare(self):
        """Every ``subprocess`` call either detaches or suppresses its
        console — or is one of the few that is meant to be seen."""
        call = re.compile(r"subprocess\.(?:run|Popen)\(")
        bare: list[str] = []
        for path in self._sources():
            text = path.read_text(encoding="utf-8")
            for match in call.finditer(text):
                chunk = text[match.end():match.end() + 700]
                call_args = chunk.split("\n    )")[0]
                if any(k in call_args for k in ("detached_popen_kwargs",
                                                "no_window_popen_kwargs")):
                    continue
                if any(f'"{name}"' in call_args.split("]")[0]
                       for name in self._INTERACTIVE):
                    continue
                line = text[:match.start()].count("\n") + 1
                bare.append(f"{path.name}:{line}")
        assert not bare, (
            f"these spawn a child with no console policy: {bare} — on "
            f"Windows each one is a console window and a conhost.exe")

    def test_the_helper_reaches_the_pdf_children(self):
        """The volume case: one child per document, and PDFs are what this
        index is mostly made of."""
        text = (Path(__file__).resolve().parents[1]
                / "parsers" / "pdf.py").read_text(encoding="utf-8")
        assert text.count("no_window_popen_kwargs()") == 2
