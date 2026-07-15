"""Tests for content-based parser routing and project-local parser
drop-ins — the two generic mechanisms that let a format-specific parser
live with its project instead of the shipped package."""
from __future__ import annotations

from pathlib import Path

import pytest

from rtfm.parsers import ParserRegistry
from rtfm.parsers.base import BaseParser
from rtfm.parsers.local import load_local_parsers, _loaded


# ── Content-based routing (BaseParser.matches) ──────────────────────────


def test_matches_default_is_false():
    """A parser that doesn't override matches() stays out of the
    content-check pass."""
    class Plain(BaseParser):
        extensions = [".zzz"]
        def parse(self, path, metadata=None):
            return iter(())
    assert Plain.matches(Path("whatever.zzz")) is False


def test_content_parser_wins_over_extension(tmp_path, monkeypatch):
    """A parser overriding matches() is consulted before the extension
    map, so it can claim a subset of files another parser also handles."""
    # Isolate the registry so we don't pollute the global one.
    monkeypatch.setattr(ParserRegistry, "_parsers", dict(ParserRegistry._parsers))
    monkeypatch.setattr(ParserRegistry, "_content_parsers",
                        list(ParserRegistry._content_parsers))

    class GenericQux(BaseParser):
        extensions = [".qux"]
        name = "generic-qux"
        def parse(self, path, metadata=None):
            return iter(())

    class SpecialQux(BaseParser):
        # Content-routed only (empty extensions) so it never clobbers
        # the generic parser's .qux fallback — the real Littré pattern.
        extensions: list = []
        name = "special-qux"
        @classmethod
        def matches(cls, path):
            return path.name.startswith("special")
        def parse(self, path, metadata=None):
            return iter(())

    ParserRegistry.register(GenericQux)
    ParserRegistry.register(SpecialQux)

    special = ParserRegistry.get_parser(tmp_path / "special-thing.qux")
    generic = ParserRegistry.get_parser(tmp_path / "ordinary.qux")
    assert isinstance(special, SpecialQux)
    assert isinstance(generic, GenericQux)


def test_matches_exception_does_not_block_fallback(tmp_path, monkeypatch):
    """A matches() that raises must not poison get_parser for other files."""
    monkeypatch.setattr(ParserRegistry, "_parsers", dict(ParserRegistry._parsers))
    monkeypatch.setattr(ParserRegistry, "_content_parsers",
                        list(ParserRegistry._content_parsers))

    class Exploder(BaseParser):
        extensions = [".boom"]
        @classmethod
        def matches(cls, path):
            raise RuntimeError("boom")
        def parse(self, path, metadata=None):
            return iter(())

    class Fallback(BaseParser):
        extensions = [".boom"]
        name = "fallback-boom"
        def parse(self, path, metadata=None):
            return iter(())

    ParserRegistry.register(Exploder)
    ParserRegistry.register(Fallback)
    # Exploder.matches raises → registry swallows it and falls back.
    assert isinstance(ParserRegistry.get_parser(tmp_path / "x.boom"), Fallback)


# ── Project-local Python parser drop-ins (.rtfm/parsers/*.py) ────────────


LOCAL_PARSER_SRC = '''
from rtfm.parsers.base import BaseParser, ParserRegistry

@ParserRegistry.register
class DropInParser(BaseParser):
    extensions = [".dropin"]
    name = "dropin-test"
    def parse(self, path, metadata=None):
        return iter(())
'''


def test_load_local_parsers_registers_dropins(tmp_path, monkeypatch):
    monkeypatch.setattr(ParserRegistry, "_parsers", dict(ParserRegistry._parsers))
    monkeypatch.setattr(ParserRegistry, "_content_parsers",
                        list(ParserRegistry._content_parsers))
    _loaded.clear()

    pdir = tmp_path / "parsers"
    pdir.mkdir()
    (pdir / "my_parser.py").write_text(LOCAL_PARSER_SRC)
    # Underscore-prefixed files are ignored.
    (pdir / "_helper.py").write_text("x = 1\n")

    n = load_local_parsers(pdir)
    assert n == 1
    parser = ParserRegistry.get_parser(tmp_path / "doc.dropin")
    assert parser is not None
    assert parser.name == "dropin-test"


def test_load_local_parsers_missing_dir_is_noop(tmp_path):
    assert load_local_parsers(tmp_path / "does-not-exist") == 0


def test_load_local_parsers_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(ParserRegistry, "_parsers", dict(ParserRegistry._parsers))
    monkeypatch.setattr(ParserRegistry, "_content_parsers",
                        list(ParserRegistry._content_parsers))
    _loaded.clear()

    pdir = tmp_path / "parsers"
    pdir.mkdir()
    (pdir / "p.py").write_text(LOCAL_PARSER_SRC)

    assert load_local_parsers(pdir) == 1
    # Second call sees the path already loaded → no re-exec, no double-register.
    assert load_local_parsers(pdir) == 0


def test_load_local_parsers_bad_file_skipped(tmp_path):
    _loaded.clear()
    pdir = tmp_path / "parsers"
    pdir.mkdir()
    (pdir / "broken.py").write_text("this is not valid python !!!\n")
    (pdir / "ok.py").write_text(LOCAL_PARSER_SRC)
    # broken.py raises on exec → skipped; ok.py still loads.
    assert load_local_parsers(pdir) == 1
