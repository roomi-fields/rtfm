"""What an indexed file needs before it can be quoted.

Three sites kept the same kind of list in three shapes, and an engine read
all of them to attribute a quotation. Lists describing the same corpus drift,
and the one that drifts is the one nobody is looking at — so the description
lives next to the index it describes.

Not on the document's own row: that row is deleted and rewritten on every
re-index, which would erase the description on each pass. That is the
property the first test here is about.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from rtfm.core import citation


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "library.db")
    c.row_factory = sqlite3.Row
    citation.ensure_schema(c)
    return c


CARD = {
    "file": "Les mots sont des fenêtres.pdf",
    "author": "Marshall B. Rosenberg",
    "title": "Les mots sont des fenêtres (ou bien ce sont des murs)",
    "nature": "livre",
    "language": "fr",
    "translator": "Annette Cesotti",
    "range": [26, 315],
    "note": "préfaces d'autres auteurs exclues",
}


class TestRecordingWhatIsKnown:

    def test_a_card_comes_back_as_it_went_in(self, conn):
        citation.put(conn, CARD, corpus="cnv")
        got = citation.get(conn, CARD["file"], "cnv")
        assert got["author"] == CARD["author"]
        assert got["range"] == [26, 315]
        assert got["corpus"] == "cnv"

    def test_recording_twice_replaces_rather_than_duplicates(self, conn):
        citation.put(conn, CARD, corpus="cnv")
        citation.put(conn, {**CARD, "title": "Titre corrigé"}, corpus="cnv")
        cards = citation.list_cards(conn, "cnv")
        assert len(cards) == 1 and cards[0]["title"] == "Titre corrigé"

    def test_a_sites_own_fields_are_kept_as_they_are(self, conn):
        citation.put(conn, {"file": "a.pdf", "author": "Averroès",
                            "title": "Discours décisif",
                            "extra": {"tradition": "falsafa",
                                      "type": "primaire"}})
        assert citation.get(conn, "a.pdf")["extra"]["tradition"] == "falsafa"

    def test_a_named_author_and_title_make_it_quotable(self, conn):
        """The whole rule: no flag to set, nothing to remember."""
        citation.put(conn, CARD, corpus="cnv")
        assert citation.get(conn, CARD["file"], "cnv")["attributed"] is True

    def test_without_an_author_it_is_background_reading(self, conn):
        citation.put(conn, {"file": "graphe/note-42.md", "title": "Note 42"})
        assert citation.get(conn, "graphe/note-42.md")["attributed"] is False

    def test_without_a_title_it_is_background_reading_too(self, conn):
        citation.put(conn, {"file": "c.pdf", "author": "Anonyme"})
        assert citation.get(conn, "c.pdf")["attributed"] is False

    def test_attribution_follows_the_card_being_corrected(self, conn):
        citation.put(conn, {"file": "d.pdf", "title": "Sans auteur"})
        assert citation.get(conn, "d.pdf")["attributed"] is False
        citation.put(conn, {"file": "d.pdf", "title": "Sans auteur",
                            "author": "Retrouvé"})
        assert citation.get(conn, "d.pdf")["attributed"] is True

    def test_the_same_path_in_two_corpora_must_be_disambiguated(self, conn):
        citation.put(conn, {"file": "README.md", "title": "un"}, corpus="cnv")
        citation.put(conn, {"file": "README.md", "title": "deux"}, corpus="ifs")
        assert citation.get(conn, "README.md", "ifs")["title"] == "deux"
        with pytest.raises(citation.InvalidCard, match="several corpora"):
            citation.get(conn, "README.md")

    def test_a_card_survives_the_file_being_re_indexed(self, tmp_path):
        """The reason it is not stored on the document's own row."""
        from rtfm.core.library import Library

        db = tmp_path / "library.db"
        doc = tmp_path / "guide.md"
        doc.write_text("# Guide\n\nDu texte.\n" * 10, encoding="utf-8")
        lib = Library(db)
        lib.ingest(doc, corpus="default",
                   metadata={"book_slug": "guide", "source_file": "guide.md"})
        citation.put(lib._get_conn(), {"file": "guide.md", "author": "Romain",
                                       "title": "Guide", "nature": "fiche"})
        lib.remove_file("guide.md", "default")   # what a re-index does first
        lib.ingest(doc, corpus="default",
                   metadata={"book_slug": "guide", "source_file": "guide.md"})
        assert citation.get(lib._get_conn(), "guide.md")["author"] == "Romain"
        lib.close()


class TestWhatIsRefused:

    def test_a_card_without_a_file_is_refused(self, conn):
        with pytest.raises(citation.InvalidCard, match="needs the file"):
            citation.put(conn, {"author": "X", "title": "Y"})

    def test_an_unknown_nature_is_refused(self, conn):
        """Almost always a typo, and a typo changes how a citation reads."""
        with pytest.raises(citation.InvalidCard, match="nature"):
            citation.put(conn, {"file": "a.pdf", "nature": "bouquin"})

    @pytest.mark.parametrize("bad", [[0, 10], [10, 5], [1], ["a", "b"], 12])
    def test_an_impossible_range_is_refused(self, conn, bad):
        with pytest.raises(citation.InvalidCard, match="range"):
            citation.put(conn, {"file": "a.pdf", "range": bad})

    def test_a_batch_writes_nothing_when_one_card_is_wrong(self, conn):
        with pytest.raises(citation.InvalidCard):
            citation.put_many(conn, [
                {"file": "bon.pdf", "title": "Bon"},
                {"file": "mauvais.pdf", "nature": "bouquin"},
            ])
        assert citation.list_cards(conn) == []


class TestReadingThem:

    def test_a_corpus_can_be_listed(self, conn):
        citation.put(conn, {"file": "a.pdf", "title": "A"}, corpus="cnv")
        citation.put(conn, {"file": "b.pdf", "title": "B"}, corpus="cnv")
        citation.put(conn, {"file": "c.pdf", "title": "C"}, corpus="ifs")
        assert [c["file"] for c in citation.list_cards(conn, "cnv")] == ["a.pdf", "b.pdf"]
        assert len(citation.list_cards(conn)) == 3

    def test_an_undescribed_file_is_absent_not_wrong(self, conn):
        assert citation.get(conn, "jamais-decrit.pdf") is None

    def test_a_card_naming_an_unindexed_file_is_reported(self, tmp_path):
        """A card is written by hand; the file it names can be renamed or
        never indexed, and the description then silently never applies."""
        from rtfm.core.library import Library

        lib = Library(tmp_path / "library.db")
        conn = lib._get_conn()
        lib.update_indexed_file("present.pdf", "h", "cnv", "present-pdf")
        citation.put(conn, {"file": "present.pdf", "title": "Là"}, corpus="cnv")
        citation.put(conn, {"file": "parti.pdf", "title": "Plus là"}, corpus="cnv")
        assert [c["file"] for c in citation.unknown_files(conn)] == ["parti.pdf"]
        lib.close()

    def test_a_card_can_be_forgotten(self, conn):
        citation.put(conn, {"file": "a.pdf", "title": "A"}, corpus="cnv")
        assert citation.delete(conn, "a.pdf", "cnv") is True
        assert citation.get(conn, "a.pdf", "cnv") is None
        assert citation.delete(conn, "a.pdf", "cnv") is False


class TestTheCommand:

    def _run(self, tmp_path, **kwargs):
        import argparse
        import io
        from contextlib import redirect_stdout
        from rtfm.cli import cmd_cite
        args = argparse.Namespace(
            db=str(tmp_path / "library.db"), path=None, corpus=None,
            format="json", set=None, from_file=None, delete=False,
            unknown=False)
        for k, v in kwargs.items():
            setattr(args, k, v)
        out = io.StringIO()
        with redirect_stdout(out):
            cmd_cite(args)
        return out.getvalue()

    def test_a_file_of_cards_is_recorded_in_one_call(self, tmp_path):
        cards = tmp_path / "cartes.json"
        cards.write_text(json.dumps([
            {"file": "a.pdf", "author": "A", "title": "Un", "nature": "livre",
             "range": [10, 200]},
            {"file": "b.pdf", "author": "B", "title": "Deux"},
        ]), encoding="utf-8")
        assert "2 card(s) recorded" in self._run(tmp_path, from_file=str(cards),
                                                corpus="cnv")
        listed = json.loads(self._run(tmp_path, corpus="cnv"))
        assert [c["file"] for c in listed] == ["a.pdf", "b.pdf"]

    def test_one_card_reads_back_as_an_object(self, tmp_path):
        self._run(tmp_path, path="a.pdf", corpus="cnv",
                  set=json.dumps({"author": "A", "title": "Un",
                                  "nature": "livre", "range": [10, 200]}))
        card = json.loads(self._run(tmp_path, path="a.pdf", corpus="cnv"))
        assert card["author"] == "A" and card["range"] == [10, 200]

    def test_an_undescribed_file_answers_nothing_not_an_error(self, tmp_path):
        assert json.loads(self._run(tmp_path, path="inconnu.pdf")) is None

    def test_a_bad_card_is_refused_with_its_reason(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            self._run(tmp_path, path="a.pdf",
                      set=json.dumps({"nature": "bouquin"}))
        assert "nature" in str(exc.value)
