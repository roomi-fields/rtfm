"""Three bad bytes should not cost a whole document.

One file in a workshop of sixteen repositories carried an emoji missing its
first three bytes. Markdown was the one format RTFM decoded strictly, so the
decode failed and took the file with it: 40 KB of perfectly good prose, out
of the index from the day it was written. Nothing recorded a failure —
``ingest_failures`` held zero rows — and the file was tracked as seen, so
nothing would ever retry it.

It cost more than its own absence. It carried a cross-reference that had
gone dead, and the project's own checks never saw it either: a file that
cannot be read escapes every check that reads files.
"""
from __future__ import annotations

import pytest

from rtfm.core.handlers import _undecodable_bytes
from rtfm.parsers._chunking import read_text_lossy


@pytest.fixture
def damaged(tmp_path):
    """A document whose emoji lost its first three bytes."""
    good = "# Corpus de reference\n\nUne phrase avant. "
    tail = " Une phrase apres, et un renvoi [mort](./parti.md).\n"
    emoji = "\N{ROCKET}".encode()          # four bytes
    raw = good.encode() + emoji[3:] + tail.encode()
    f = tmp_path / "baseline-corpus.md"
    f.write_bytes(raw)
    return f


class TestReadingIt:

    def test_the_text_survives(self, damaged):
        text, replaced = read_text_lossy(damaged)
        assert "Une phrase avant." in text
        assert "Une phrase apres" in text
        assert replaced == 1

    def test_a_healthy_file_reports_nothing(self, tmp_path):
        f = tmp_path / "sain.md"
        f.write_text("# Titre\n\nDu texte et un emoji \N{ROCKET}.\n")
        text, replaced = read_text_lossy(f)
        assert replaced == 0
        assert "\N{ROCKET}" in text

    def test_the_damage_is_countable(self, damaged, tmp_path):
        assert _undecodable_bytes(damaged) == 1
        healthy = tmp_path / "sain.md"
        healthy.write_text("Rien de casse.\n")
        assert _undecodable_bytes(healthy) == 0

    def test_an_unreadable_path_is_not_a_crash(self, tmp_path):
        assert _undecodable_bytes(tmp_path / "absent.md") == 0


class TestIndexingIt:

    def _ingest(self, tmp_path, rel):
        from rtfm.core.handlers import handle_ingest
        from rtfm.core.queue import Job

        class _W:
            db_path = tmp_path / ".rtfm" / "library.db"

            def __init__(self):
                self.lines = []

            def _log(self, msg):
                self.lines.append(msg)
        (tmp_path / ".rtfm").mkdir(exist_ok=True)
        w = _W()
        handle_ingest(Job(id=1, type="ingest", priority=10,
                          payload={"root": str(tmp_path), "corpus": "default",
                                   "filepath": rel},
                          status="running", created_at="", started_at=None,
                          finished_at=None, error=None, attempts=1), w)
        return w

    def test_the_document_enters_the_index(self, damaged, tmp_path):
        from rtfm.core.library import Library
        self._ingest(tmp_path, "baseline-corpus.md")
        lib = Library(tmp_path / ".rtfm" / "library.db", create=False)
        try:
            assert lib.search("reference", limit=3), (
                "40 KB of good prose was lost over three bytes")
        finally:
            lib.close()

    def test_the_damage_is_said_out_loud(self, damaged, tmp_path):
        """Indexed leniently is not indexed silently: whoever wonders why a
        passage reads oddly must have something to go on."""
        w = self._ingest(tmp_path, "baseline-corpus.md")
        assert any("not valid text" in ln for ln in w.lines)

    def test_a_healthy_file_says_nothing(self, tmp_path):
        (tmp_path / "sain.md").write_text("# Titre\n\nDu texte propre.\n" * 5)
        w = self._ingest(tmp_path, "sain.md")
        assert not any("not valid text" in ln for ln in w.lines)

    def test_its_links_become_visible_again(self, damaged, tmp_path):
        """The second cost of the failure: a file nothing can read is a file
        no check can check."""
        from rtfm.parsers.markdown import MarkdownParser
        edges = MarkdownParser().extract_edges(damaged)
        assert any(e.target_ref.endswith("parti.md") for e in edges)
