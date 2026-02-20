"""Tests for article versioning."""

import pytest
from datetime import date
from rtfm import Library


class TestArticleVersioning:
    """Tests for article version management."""

    def test_add_article_version(self, library, sample_cgi_xml):
        """Test adding an article version."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        # Get a chunk to link
        results = library.search("impôt")
        chunk_id = results[0].chunk.id

        # Add a version
        version_id = library.add_article_version(
            article_ref="CGI-1",
            chunk_id=chunk_id,
            version_num=1,
            date_debut="2020-01-01",
            date_fin=None,
            etat="VIGUEUR",
        )

        assert version_id is not None
        assert version_id > 0

    def test_add_multiple_versions(self, library, sample_cgi_xml):
        """Test adding multiple versions of an article."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        results = library.search("impôt")
        chunk_id = results[0].chunk.id

        # Add version 1 (old, ended)
        v1_id = library.add_article_version(
            article_ref="CGI-39",
            chunk_id=chunk_id,
            version_num=1,
            date_debut="2018-01-01",
            date_fin="2019-12-31",
            etat="MODIFIE",
            texte_modificateur="Loi 2018-123",
        )

        # Add version 2 (current)
        v2_id = library.add_article_version(
            article_ref="CGI-39",
            chunk_id=chunk_id,
            version_num=2,
            date_debut="2020-01-01",
            date_fin=None,
            etat="VIGUEUR",
            texte_modificateur="Loi 2019-456",
            previous_id=v1_id,
        )

        assert v1_id is not None
        assert v2_id is not None
        assert v2_id > v1_id

    def test_get_article_history(self, library, sample_cgi_xml):
        """Test retrieving article version history."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        results = library.search("impôt")
        chunk_id = results[0].chunk.id

        # Add multiple versions
        library.add_article_version(
            article_ref="CGI-TEST",
            chunk_id=chunk_id,
            version_num=1,
            date_debut="2015-01-01",
            date_fin="2017-12-31",
            etat="MODIFIE",
        )
        library.add_article_version(
            article_ref="CGI-TEST",
            chunk_id=chunk_id,
            version_num=2,
            date_debut="2018-01-01",
            date_fin="2020-12-31",
            etat="MODIFIE",
        )
        library.add_article_version(
            article_ref="CGI-TEST",
            chunk_id=chunk_id,
            version_num=3,
            date_debut="2021-01-01",
            date_fin=None,
            etat="VIGUEUR",
        )

        # Get history
        history = library.get_article_history("CGI-TEST")

        assert len(history) == 3
        assert history[0]["version_num"] == 1
        assert history[1]["version_num"] == 2
        assert history[2]["version_num"] == 3
        assert history[2]["date_fin"] is None  # Current version

    def test_get_article_at_date(self, library, sample_cgi_xml):
        """Test getting article at a specific date."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        results = library.search("impôt")
        chunk_id = results[0].chunk.id

        # Add versions with different periods
        library.add_article_version(
            article_ref="CGI-DATE-TEST",
            chunk_id=chunk_id,
            version_num=1,
            date_debut="2015-01-01",
            date_fin="2019-12-31",
            etat="MODIFIE",
        )
        library.add_article_version(
            article_ref="CGI-DATE-TEST",
            chunk_id=chunk_id,
            version_num=2,
            date_debut="2020-01-01",
            date_fin=None,
            etat="VIGUEUR",
        )

        # Query at different dates
        v_2018 = library.get_article_at_date("CGI-DATE-TEST", "2018-06-15")
        v_2022 = library.get_article_at_date("CGI-DATE-TEST", "2022-03-01")

        assert v_2018["version_num"] == 1
        assert v_2022["version_num"] == 2

    def test_get_article_at_date_not_found(self, library, sample_cgi_xml):
        """Test querying date outside any version period."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        results = library.search("impôt")
        chunk_id = results[0].chunk.id

        library.add_article_version(
            article_ref="CGI-FUTURE",
            chunk_id=chunk_id,
            version_num=1,
            date_debut="2025-01-01",
            date_fin=None,
            etat="VIGUEUR",
        )

        # Query before the article exists
        result = library.get_article_at_date("CGI-FUTURE", "2020-01-01")
        assert result is None

    def test_list_versioned_articles(self, library, sample_cgi_xml):
        """Test listing all versioned articles."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        results = library.search("impôt")
        chunk_id = results[0].chunk.id

        # Add versions for multiple articles
        library.add_article_version(
            article_ref="CGI-A",
            chunk_id=chunk_id,
            version_num=1,
            date_debut="2020-01-01",
            etat="VIGUEUR",
        )
        library.add_article_version(
            article_ref="CGI-A",
            chunk_id=chunk_id,
            version_num=2,
            date_debut="2021-01-01",
            etat="VIGUEUR",
        )
        library.add_article_version(
            article_ref="CGI-B",
            chunk_id=chunk_id,
            version_num=1,
            date_debut="2020-01-01",
            etat="VIGUEUR",
        )

        articles = library.list_versioned_articles()

        assert len(articles) == 2
        refs = {a["article_ref"] for a in articles}
        assert "CGI-A" in refs
        assert "CGI-B" in refs

        # CGI-A should have 2 versions
        cgi_a = next(a for a in articles if a["article_ref"] == "CGI-A")
        assert cgi_a["version_count"] == 2

    def test_compare_versions(self, library, sample_cgi_xml):
        """Test comparing two article versions."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        results = library.search("impôt")
        chunk_id_1 = results[0].chunk.id

        # Get second chunk if available
        if len(results) > 1:
            chunk_id_2 = results[1].chunk.id
        else:
            chunk_id_2 = chunk_id_1

        # Add two versions
        library.add_article_version(
            article_ref="CGI-COMPARE",
            chunk_id=chunk_id_1,
            version_num=1,
            date_debut="2020-01-01",
            date_fin="2020-12-31",
            etat="MODIFIE",
        )
        library.add_article_version(
            article_ref="CGI-COMPARE",
            chunk_id=chunk_id_2,
            version_num=2,
            date_debut="2021-01-01",
            etat="VIGUEUR",
        )

        result = library.compare_versions("CGI-COMPARE", 1, 2)

        assert "v1" in result
        assert "v2" in result
        assert "chars_diff" in result
        assert "content_changed" in result

    def test_compare_versions_not_found(self, library):
        """Test comparing versions when article doesn't exist."""
        result = library.compare_versions("NONEXISTENT", 1, 2)
        assert "error" in result

    def test_get_history_empty(self, library):
        """Test getting history for nonexistent article."""
        history = library.get_article_history("NONEXISTENT")
        assert history == []


class TestVersionMetadataFromParser:
    """Tests for version metadata extraction from XML parser."""

    def test_article_ref_in_metadata(self, library, sample_cgi_xml):
        """Test that article_ref is extracted from parsed XML."""
        library.ingest(sample_cgi_xml, corpus="cgi", metadata={"code": "cgi"})

        results = library.search("impôt")
        assert len(results) > 0

        chunk = results[0].chunk
        legal_fr = chunk.metadata.get("legal_fr", {})

        # article_ref should be generated from code + article number
        if legal_fr.get("code") and legal_fr.get("numero_article"):
            assert legal_fr.get("article_ref") is not None

    def test_version_dates_in_metadata(self, library, sample_cgi_xml):
        """Test that version dates are extracted."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        results = library.search("impôt")
        chunk = results[0].chunk
        legal_fr = chunk.metadata.get("legal_fr", {})

        # These fields should exist (even if empty)
        assert "date_debut" in legal_fr
        assert "date_fin" in legal_fr
        assert "etat" in legal_fr
