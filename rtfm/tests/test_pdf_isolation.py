"""pdfium never runs in the daemon's own process.

The library carries process-global, unsynchronised state. Twelve worker
lanes paging through documents at once corrupted it: healthy files came
back as "Failed to load document (PDFium: Data format error)", and often
enough the process segfaulted outright — taking the supervisor down and
stranding every claim its lanes were holding.

These tests pin the two halves of the fix: every document goes through a
one-shot child process, and a child that dies costs exactly one file.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from rtfm.parsers.pdf import (
    PDFExtractionError,
    _call_pdfium_child,
    extract_with_pdftext,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


class TestTheChildDoesTheWork:
    def test_the_child_runs_and_reports_back(self):
        """End-to-end through a real subprocess: it starts, imports rtfm,
        and its refusal comes back as an exception here."""
        with pytest.raises(PDFExtractionError) as exc:
            _call_pdfium_child(
                {"op": "no-such-op", "path": "/nowhere.pdf"}, 60, "probe")
        assert "no-such-op" in str(exc.value)

    def test_a_crash_costs_one_file_not_the_worker(self, monkeypatch):
        """A segfault in the child surfaces as a normal failure naming the
        signal. In-process, this same crash was uncatchable."""
        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(args, -11, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(PDFExtractionError) as exc:
            extract_with_pdftext(Path("/tmp/whatever.pdf"))
        message = str(exc.value)
        assert "signal 11" in message
        assert "worker is unaffected" in message

    def test_a_wedged_child_is_given_up_on(self, monkeypatch):
        """A pdfium stuck on a dead mount must free its lane, not hold it."""
        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="python", timeout=1)

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(PDFExtractionError, match="timed out"):
            extract_with_pdftext(Path("/tmp/whatever.pdf"))

    def test_unparseable_child_output_is_a_failure_not_a_crash(self, monkeypatch):
        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(
                args, 0, stdout="not json at all\n", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(PDFExtractionError):
            extract_with_pdftext(Path("/tmp/whatever.pdf"))

    def test_a_successful_result_comes_straight_back(self, monkeypatch):
        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(
                args, 0,
                stdout='{"result": [{"page": 1, "text": "hello"}]}\n',
                stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert extract_with_pdftext(Path("/tmp/whatever.pdf")) == [
            {"page": 1, "text": "hello"}
        ]

    def test_a_failure_reads_as_one_sentence(self, monkeypatch):
        """The child already says what went wrong with this file; saying it
        twice ("extraction failed: extraction failed: ...") helps nobody."""
        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(
                args, 3,
                stdout='{"error": "pdftext extraction failed: /a/b.pdf",'
                       ' "kind": "PDFExtractionError"}\n',
                stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(PDFExtractionError) as exc:
            extract_with_pdftext(Path("/a/b.pdf"))
        assert str(exc.value) == "pdftext extraction failed: /a/b.pdf"

    def test_an_unexpected_failure_keeps_its_context(self, monkeypatch):
        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(
                args, 3,
                stdout='{"error": "disk on fire", "kind": "OSError"}\n',
                stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(PDFExtractionError) as exc:
            extract_with_pdftext(Path("/a/b.pdf"))
        assert str(exc.value) == "pdftext extraction failed: disk on fire"


class TestNothingCallsPdfiumInProcess:
    """Guard: the in-process bodies have exactly one live caller.

    They are kept only as the child's implementation. The moment any other
    module starts calling one directly, pdfium is back in the daemon's
    address space and the whole class of failure returns — silently, until
    a corpus of PDFs is next indexed. So fail here instead.
    """

    IN_PROCESS = {"_pdftext_inprocess", "_tesseract_inprocess",
                  "_pdfmeta_inprocess"}
    ONLY_LEGITIMATE_CALLER = "run_pdfium_op"

    def test_the_in_process_bodies_are_called_only_from_the_child_entry(self):
        offenders = []
        for path in sorted(PACKAGE_ROOT.rglob("*.py")):
            if "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            # Map every call site to the function that encloses it.
            enclosing: dict[int, str] = {}
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for child in ast.walk(node):
                        enclosing.setdefault(id(child), node.name)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "id", None) or getattr(
                    node.func, "attr", None)
                if name in self.IN_PROCESS:
                    if enclosing.get(id(node)) != self.ONLY_LEGITIMATE_CALLER:
                        offenders.append(
                            f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno} "
                            f"calls {name} from "
                            f"{enclosing.get(id(node)) or '<module>'}")
        assert not offenders, (
            "pdfium must never run in the daemon's process — route these "
            "through _call_pdfium_child:\n  " + "\n  ".join(offenders))
