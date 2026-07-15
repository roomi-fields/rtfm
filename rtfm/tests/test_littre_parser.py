"""Tests for the XMLittré parser and content-based parser routing."""
from __future__ import annotations

from pathlib import Path

import pytest

from rtfm.parsers import ParserRegistry
from rtfm.parsers.littre import LittreParser, _preprocess
from rtfm.parsers.xml_legifrance import XMLLegiFranceParser


# A minimal Littré-shaped XML with the pathological structure that
# broke the standard parser: two <?xml ?> declarations, a nested
# <!DOCTYPE>, and two entries under two letter blocks.
SAMPLE_LITTRE = """<?xml version="1.0" encoding="utf-8"?>
<littre-consolide source="XMLittre par Francois Gannaz">
<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE xmlittre SYSTEM "xmlittre.dtd">
<xmlittre lettre="A">
<entree terme="ABEILLE" sens="1">
<entete><nature>s. f.</nature></entete>
<corps>Insecte hyménoptère qui produit le miel.</corps>
</entree>
</xmlittre>
<?xml version="1.0" encoding="utf-8"?>
<xmlittre lettre="B">
<entree terme="BLEU">
<corps>Couleur du ciel par temps clair.</corps>
</entree>
</xmlittre>
</littre-consolide>
""".encode("utf-8")


def _write(tmp_path: Path, name: str, body: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(body)
    return p


def test_preprocess_strips_inner_xml_declarations():
    """Only the outermost <?xml ?> survives; every inner one and every
    <!DOCTYPE> is scrubbed."""
    cleaned = _preprocess(SAMPLE_LITTRE)
    assert cleaned.count(b"<?xml") == 1
    assert b"<!DOCTYPE" not in cleaned
    # Content isn't otherwise altered.
    assert b"<entree terme=\"ABEILLE\"" in cleaned
    assert b"<entree terme=\"BLEU\"" in cleaned


def test_littre_matches_only_the_dictionary(tmp_path):
    """``LittreParser.matches`` must return True on the consolidated
    file and False on any other .xml (so Legifrance still handles them)."""
    littre = _write(tmp_path, "littre-dictionnaire.xml", SAMPLE_LITTRE)
    assert LittreParser.matches(littre) is True

    other = _write(tmp_path, "cgi.xml",
        b"<?xml version=\"1.0\"?>\n<TEXTE_VERSION><META/></TEXTE_VERSION>\n")
    assert LittreParser.matches(other) is False


def test_registry_routes_littre_before_legifrance(tmp_path):
    """Registry.get_parser must consult content-aware matchers before
    the extension map. Both .xml → different classes."""
    littre = _write(tmp_path, "littre-dictionnaire.xml", SAMPLE_LITTRE)
    other = _write(tmp_path, "some-code.xml",
        b"<?xml version=\"1.0\"?>\n<TEXTE_VERSION><META/></TEXTE_VERSION>\n")
    assert isinstance(ParserRegistry.get_parser(littre), LittreParser)
    assert isinstance(ParserRegistry.get_parser(other), XMLLegiFranceParser)


def test_parse_yields_one_chunk_per_entree(tmp_path):
    littre = _write(tmp_path, "littre-dictionnaire.xml", SAMPLE_LITTRE)
    chunks = list(LittreParser().parse(littre, metadata={"book_slug": "test-littre"}))
    assert len(chunks) == 2

    c0 = chunks[0]
    assert c0.metadata["terme"] == "ABEILLE"
    assert c0.metadata["lettre"] == "A"
    assert c0.metadata.get("sens") == "1"
    assert "hyménoptère" in c0.content
    # chunk_id follows the book_slug prefix so reconcile's fossil
    # detector doesn't sweep it after a re-ingest.
    assert c0.id.startswith("test-littre-")

    c1 = chunks[1]
    assert c1.metadata["terme"] == "BLEU"
    assert c1.metadata["lettre"] == "B"
    assert "sens" not in c1.metadata  # no @sens on this entry


def test_matches_survives_missing_file(tmp_path):
    """``matches`` must never raise — it runs during dispatch and a
    raised exception would poison get_parser for every subsequent call."""
    assert LittreParser.matches(tmp_path / "nope.xml") is False
