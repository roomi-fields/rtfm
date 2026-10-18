"""The figures the docs state are the figures the code has.

``scripts/sync_facts.py --check`` fails when a claimed count of parsers or
MCP tools drifts from the source, or when a parser, an extension or a tool
is left undocumented. These tests run it, and break it on purpose to prove
it bites: a guard never seen failing guards nothing.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _facts():
    spec = importlib.util.spec_from_file_location(
        "_sync_facts", ROOT / "scripts" / "sync_facts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check(facts, monkeypatch) -> int:
    monkeypatch.setattr(sys, "argv", ["sync_facts.py", "--check"])
    return facts.main()


def test_the_docs_state_the_real_figures(monkeypatch):
    assert _check(_facts(), monkeypatch) == 0


def test_a_stale_figure_fails(tmp_path, monkeypatch):
    facts = _facts()
    readme = tmp_path / "README.md"
    readme.write_text((ROOT / "README.md").read_text(encoding="utf-8")
                      .replace(f"**{facts.P} parsers built-in**", "**15 parsers built-in**"),
                      encoding="utf-8")
    _redirect(facts, monkeypatch, tmp_path)
    assert _check(facts, monkeypatch) == 1
    monkeypatch.setattr(sys, "argv", ["sync_facts.py"])
    facts.main()
    assert f"**{facts.P} parsers built-in**" in readme.read_text(encoding="utf-8")
    assert _check(facts, monkeypatch) == 0


def test_a_reworded_claim_fails(tmp_path, monkeypatch):
    """A rule matching nothing no longer watches its claim."""
    facts = _facts()
    readme = tmp_path / "README.md"
    readme.write_text((ROOT / "README.md").read_text(encoding="utf-8")
                      .replace("parsers built-in**", "formats out of the box**"),
                      encoding="utf-8")
    _redirect(facts, monkeypatch, tmp_path)
    assert _check(facts, monkeypatch) == 1


def test_an_undocumented_parser_fails(monkeypatch):
    facts = _facts()
    monkeypatch.setattr(facts, "PARSERS", facts.PARSERS + [
        ("NewParser", "rtfm/parsers/new.py", [".new"])])
    gaps = facts.coverage_gaps()
    assert any("NewParser (rtfm/parsers/new.py)" in g for g in gaps)
    assert any("NewParser's .new" in g for g in gaps)


def test_an_undocumented_tool_fails(monkeypatch):
    facts = _facts()
    monkeypatch.setattr(facts, "TOOLS", facts.TOOLS + ["rtfm_new"])
    assert "README.md tool table lacks rtfm_new" in facts.coverage_gaps()


def test_counts_come_from_the_source_not_the_installed_extras():
    facts = _facts()
    modules = {m for _, m, _ in facts.PARSERS}
    assert "rtfm/parsers/xlsx.py" in modules      # registers only with openpyxl
    assert "rtfm/parsers/epub.py" in modules      # registers only with ebooklib
    assert "rtfm_coverage" in facts.TOOLS and "rtfm_sync" in facts.TOOLS
    assert "rtfm_sync" not in facts.RUNTIME_TOOLS


def _redirect(facts, monkeypatch, tmp_path):
    """Point the check at a copy holding only README.md."""
    monkeypatch.setattr(facts, "TARGETS", {"README.md": facts.TARGETS["README.md"]})
    monkeypatch.setattr(facts, "ROOT", tmp_path)
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "parsers.md").write_text(
        (ROOT / "docs" / "parsers.md").read_text(encoding="utf-8"), encoding="utf-8")
