"""Pytest fixtures for rtfm tests."""

import pytest
import tempfile
from pathlib import Path
from rtfm import Library


@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        yield Path(f.name)
    # Cleanup
    Path(f.name).unlink(missing_ok=True)


@pytest.fixture
def library(temp_db):
    """Create a Library instance with temporary database."""
    return Library(temp_db)


@pytest.fixture
def sample_cgi_xml(tmp_path):
    """Create a sample CGI XML file."""
    xml_content = '''<?xml version="1.0" encoding="UTF-8"?>
<CODE>
    <META>
        <META_SPEC>
            <META_TEXTE_VERSION>
                <TITRE>Code général des impôts</TITRE>
                <TITREFULL>Code général des impôts</TITREFULL>
            </META_TEXTE_VERSION>
        </META_SPEC>
    </META>
    <ARTICLE>
        <META>
            <META_SPEC>
                <META_ARTICLE>
                    <NUM>1 A</NUM>
                    <ETAT>VIGUEUR</ETAT>
                    <DATE_DEBUT>1979-07-01</DATE_DEBUT>
                    <DATE_FIN>2999-01-01</DATE_FIN>
                </META_ARTICLE>
            </META_SPEC>
        </META>
        <BLOC_TEXTUEL>
            <CONTENU>
                <p>Il est établi un impôt annuel unique sur le revenu des personnes physiques.</p>
            </CONTENU>
        </BLOC_TEXTUEL>
    </ARTICLE>
    <ARTICLE>
        <META>
            <META_SPEC>
                <META_ARTICLE>
                    <NUM>44 quinquies</NUM>
                    <ETAT>VIGUEUR</ETAT>
                    <DATE_DEBUT>2020-01-01</DATE_DEBUT>
                    <DATE_FIN>2999-01-01</DATE_FIN>
                </META_ARTICLE>
            </META_SPEC>
        </META>
        <BLOC_TEXTUEL>
            <CONTENU>
                <p>Les entreprises créées dans les zones d'aide à finalité régionale peuvent bénéficier d'une exonération d'impôt sur les bénéfices.</p>
            </CONTENU>
        </BLOC_TEXTUEL>
    </ARTICLE>
</CODE>'''

    xml_file = tmp_path / "CGI.xml"  # Use CGI.xml as name so it gets recognized
    xml_file.write_text(xml_content, encoding='utf-8')
    return xml_file


@pytest.fixture
def sample_bofip_html(tmp_path):
    """Create a sample BOFiP HTML file."""
    # Make content longer to exceed MIN_CHARS (200)
    html_content = '''<!DOCTYPE html>
<html>
<head>
    <title>BOI-TVA-CHAMP-30-10 - TVA - Champ d'application</title>
</head>
<body>
    <h1>TVA - Champ d'application et territorialité - Guide complet</h1>
    <p>Le présent chapitre expose les règles relatives au champ d'application de la TVA en France.
    La taxe sur la valeur ajoutée est un impôt indirect sur la consommation qui s'applique
    à la plupart des biens et services. Ce document détaille les conditions d'application
    et les différents cas d'imposition selon la nature des opérations réalisées.</p>

    <h2>I. Opérations imposables par nature</h2>
    <p>Conformément à l'article 256 du CGI, sont soumises à la TVA les livraisons de biens
    et les prestations de services effectuées à titre onéreux par un assujetti agissant
    en tant que tel. Ces dispositions concernent l'ensemble des activités économiques
    exercées sur le territoire français par des personnes physiques ou morales.
    L'assujettissement à la TVA résulte de la réalisation d'opérations entrant dans
    le champ d'application de cette taxe.</p>

    <h2>II. Opérations imposables par disposition de la loi</h2>
    <p>L'article 257 bis du CGI prévoit que certaines opérations sont également imposables.
    Il s'agit notamment des acquisitions intracommunautaires de biens, des importations
    de biens en provenance de pays tiers, et de certaines opérations portant sur les
    immeubles. En application de l'article 261 du CGI, sont exonérées de TVA les
    opérations suivantes selon les conditions prévues par la réglementation en vigueur.</p>
</body>
</html>'''

    html_file = tmp_path / "sample_bofip.html"
    html_file.write_text(html_content, encoding='utf-8')
    return html_file


@pytest.fixture
def sample_markdown(tmp_path):
    """Create a sample markdown file."""
    md_content = '''# Chapter 1 - Introduction

This is the introduction to the document.

## Section 1.1

First section content with some details about the topic.

## Section 1.2

Second section with more information.

# Chapter 2 - Main Content

The main content of the document goes here.

## Section 2.1

Detailed explanation of key concepts.
'''

    md_file = tmp_path / "sample.md"
    md_file.write_text(md_content, encoding='utf-8')
    return md_file
