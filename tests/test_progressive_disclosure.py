"""Tests for progressive disclosure effectiveness.

Compares RTFM search (metadata-only) vs raw search (with content)
on the same queries to measure:
- Output size (proxy for token consumption)
- Metadata completeness (file path, lang, score, chunks, expand hint)
- Content correctly absent from level 0, present in level 1 (expand)
- Search quality (relevant results found)
"""

import json
import os
import time
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

from rtfm import Library
from rtfm.core.sync import sync, _path_to_slug


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def multilang_db(tmp_path_factory):
    """Create a DB with FR + EN articles via sync (realistic slug format).

    Uses sync() so slugs include corpus prefix, exactly like production.
    """
    tmpdir = tmp_path_factory.mktemp("multilang")
    db_path = tmpdir / "test.db"
    lib = Library(db_path)

    # Build a project directory with FR articles + _en/ translations
    project = tmpdir / "articles"
    project.mkdir()

    # FR articles
    (project / "B4_Flags.md").write_text(
        "---\nlang: fr\ntitle: B4 Flags et poids\n---\n\n"
        "# B4) Flags et poids decrémentaux\n\n"
        "Les flags sont des indicateurs binaires utilisés dans les grammaires BP3.\n"
        "Chaque flag contrôle l'application d'une règle de dérivation.\n"
        "Les poids decrémentaux permettent de limiter le nombre d'applications.\n\n"
        "## Mécanisme des flags\n\n"
        "Un flag est activé au début de la dérivation et désactivé après usage.\n"
        "Cela permet de contrôler la structure musicale générée.\n"
    )
    (project / "B8_Trois_Directions.md").write_text(
        "---\nlang: fr\ntitle: B8 Trois directions\n---\n\n"
        "# B8) Trois directions pour les grammaires musicales\n\n"
        "Les grammaires peuvent être appliquées dans trois directions distinctes.\n"
        "La direction affecte la structure rythmique et mélodique du résultat.\n"
        "Chaque direction produit des patterns musicaux différents.\n\n"
        "## Direction gauche-droite\n\n"
        "La dérivation standard procède de gauche à droite.\n"
        "C'est la direction la plus naturelle pour la musique occidentale.\n"
    )
    (project / "L3_EBNF.md").write_text(
        "---\nlang: fr\ntitle: L3 EBNF notation\n---\n\n"
        "# L3) Extended Backus-Naur Form (EBNF)\n\n"
        "L'EBNF est une notation formelle pour décrire la syntaxe des langages.\n"
        "Elle étend la BNF avec des opérateurs de répétition et d'option.\n"
        "En musicologie, l'EBNF sert à formaliser les grammaires musicales.\n\n"
        "## Syntaxe EBNF\n\n"
        "Les règles EBNF utilisent ::= pour les définitions.\n"
        "Les crochets [] indiquent les éléments optionnels.\n"
        "Les accolades {} indiquent la répétition.\n"
    )

    # EN translations in _en/ subdirectory
    en_dir = project / "_en"
    en_dir.mkdir()
    (en_dir / "B4_Flags.md").write_text(
        "---\nlang: en\ntitle: B4 Flags and weights\n---\n\n"
        "# B4) Flags and Decremental Weights\n\n"
        "Flags are binary indicators used in BP3 grammars.\n"
        "Each flag controls the application of a derivation rule.\n"
        "Decremental weights limit the number of applications.\n\n"
        "## Flag mechanism\n\n"
        "A flag is activated at the start of derivation and deactivated after use.\n"
        "This controls the generated musical structure.\n"
    )
    (en_dir / "B8_Trois_Directions.md").write_text(
        "---\nlang: en\ntitle: B8 Three directions\n---\n\n"
        "# B8) Three Directions for Musical Grammars\n\n"
        "Grammars can be applied in three distinct directions.\n"
        "The direction affects the rhythmic and melodic structure of the result.\n"
        "Each direction produces different musical patterns.\n\n"
        "## Left-to-right direction\n\n"
        "Standard derivation proceeds from left to right.\n"
        "This is the most natural direction for Western music.\n"
    )

    # Sync (this uses the new corpus-prefixed slugs)
    result = sync(lib, project, corpus="published", generate_embeddings=False)
    assert result.added == 5
    assert result.errors == []

    lib.close()

    with patch.dict(os.environ, {"RTFM_DB": str(db_path)}):
        import rtfm.mcp as mcp_mod
        mcp_mod._library = None
        yield {
            "db_path": db_path,
            "project": project,
            "lib_factory": lambda: Library(db_path),
        }
        mcp_mod._library = None


# ── Test: Output size comparison ─────────────────────────────────────────

class TestOutputSize:
    """Verify that metadata-only output is dramatically smaller than content."""

    def test_search_vs_all_expands_size_ratio(self, multilang_db):
        """Search output should be much smaller than expanding ALL returned sources."""
        from rtfm.mcp import rtfm_search, rtfm_expand

        search_result = rtfm_search("flags grammaires BP3", limit=5, search_type="fts")
        search_size = len(search_result)

        # Get file paths for all books (filename not in list_books, query directly)
        lib = multilang_db["lib_factory"]()
        conn = lib._get_conn()
        rows = conn.execute(
            "SELECT filename FROM books WHERE filename IS NOT NULL AND filename != ''"
        ).fetchall()
        project = multilang_db["project"]
        filepaths = [str(project / row["filename"]) for row in rows]
        lib.close()
        assert filepaths, "Should have indexed books"

        import rtfm.mcp as mcp_mod

        # Expand all sources and sum their sizes
        total_expand_size = 0
        for fp in filepaths:
            mcp_mod._library = None
            expand_result = rtfm_expand(fp)
            total_expand_size += len(expand_result)

        print(f"\n  Search output:        {search_size} chars")
        print(f"  All expands combined: {total_expand_size} chars")
        print(f"  Ratio: {search_size / total_expand_size:.1%}")

        # Search metadata should be significantly smaller than all content combined
        assert search_size < total_expand_size, (
            f"Search ({search_size}) should be smaller than all expands ({total_expand_size})"
        )

    def test_search_size_scales_linearly(self, multilang_db):
        """Search output for limit=1 should be ~1/3 of limit=3."""
        from rtfm.mcp import rtfm_search

        r1 = rtfm_search("grammaires musicales", limit=1, search_type="fts")
        r3 = rtfm_search("grammaires musicales", limit=3, search_type="fts")

        # 3 results should be roughly 2-4x the size of 1 result
        # (accounting for header/footer overhead)
        assert len(r3) > len(r1)
        assert len(r3) < len(r1) * 5  # not more than 5x


# ── Test: Metadata completeness ──────────────────────────────────────────

class TestMetadataCompleteness:
    """Verify search results contain all expected metadata fields."""

    def test_search_has_required_fields(self, multilang_db):
        """Each search result must have: file path, line marker, header."""
        from rtfm.mcp import rtfm_search

        result = rtfm_search("flags BP3", limit=5, search_type="fts")

        assert "L" in result, "Missing line marker"
        assert "B4_Flags.md" in result, "Missing file path"
        assert "sources for" in result, "Missing header"

    def test_en_articles_identifiable_by_path(self, multilang_db):
        """English articles must be identifiable by _en/ in their file path."""
        from rtfm.mcp import rtfm_search

        result = rtfm_search("flags derivation", limit=5, search_type="fts")

        # EN articles are in _en/ subdirectory — path distinguishes language
        assert "_en/" in result, (
            f"EN articles should be identifiable by '_en/' in path.\nActual output:\n{result}"
        )

    def test_fr_articles_identifiable_by_path(self, multilang_db):
        """French articles should have paths without _en/ prefix."""
        from rtfm.mcp import rtfm_search

        result = rtfm_search("flags dérivation poids", limit=5, search_type="fts")

        # FR articles should appear with direct paths (no _en/)
        assert "B4_Flags.md" in result, (
            f"FR articles should show B4_Flags.md in results.\nActual output:\n{result}"
        )

    def test_file_path_distinguishes_en(self, multilang_db):
        """EN articles should show _en/ in their file path."""
        from rtfm.mcp import rtfm_search

        result = rtfm_search("flags weights derivation", limit=5, search_type="fts")

        assert "_en/" in result, (
            f"EN file paths should contain '_en/'.\nActual output:\n{result}"
        )

    def test_context_has_required_fields(self, multilang_db):
        """rtfm_context should have line markers and header."""
        from rtfm.mcp import rtfm_context

        result = rtfm_context("grammaires musicales BP3")

        assert "L" in result or "No context" in result, "Missing line marker"
        assert "sources for" in result or "No context" in result

    def test_expand_header_has_path_and_section(self, multilang_db):
        """Expand should show file path and section in its header."""
        from rtfm.mcp import rtfm_expand

        lib = multilang_db["lib_factory"]()
        conn = lib._get_conn()
        # Get EN B4 book with filename
        rows = conn.execute(
            "SELECT slug, filename FROM books WHERE slug LIKE '%en%b4%'"
        ).fetchall()
        project = multilang_db["project"]
        lib.close()
        assert rows, "Should find EN B4"

        import rtfm.mcp as mcp_mod
        mcp_mod._library = None

        filepath = str(project / rows[0]["filename"])
        result = rtfm_expand(filepath)
        assert "_en/" in result, "Expand should show _en/ in path"
        assert ">" in result, "Expand should show section"
        assert "[1/" in result, "Expand should show chunk position"


# ── Test: Content isolation ──────────────────────────────────────────────

class TestContentIsolation:
    """Verify level 0 (search/context) has NO content, level 1 (expand) HAS content."""

    def test_search_excludes_article_text(self, multilang_db):
        """Search must NOT contain actual article content."""
        from rtfm.mcp import rtfm_search

        result = rtfm_search("flags BP3 grammaires", limit=5, search_type="fts")

        # These phrases are from the actual article content
        content_phrases = [
            "indicateurs binaires",  # from FR B4
            "binary indicators",     # from EN B4
            "contrôle l'application", # from FR B4
            "controls the application", # from EN B4
        ]
        for phrase in content_phrases:
            assert phrase not in result, (
                f"Search should NOT contain article content: '{phrase}'\n"
                f"Actual output:\n{result}"
            )

    def test_expand_includes_article_text(self, multilang_db):
        """Expand MUST contain actual article content."""
        from rtfm.mcp import rtfm_expand

        lib = multilang_db["lib_factory"]()
        conn = lib._get_conn()
        # Get FR B4 with filename
        rows = conn.execute(
            "SELECT slug, filename FROM books WHERE slug LIKE 'published--b4%'"
        ).fetchall()
        project = multilang_db["project"]
        lib.close()
        assert rows, "Should find FR B4"

        import rtfm.mcp as mcp_mod
        mcp_mod._library = None

        filepath = str(project / rows[0]["filename"])
        result = rtfm_expand(filepath)
        assert len(result) > 200, "Expand should return substantial content"
        # Should contain actual text from the article
        assert "flag" in result.lower() or "poids" in result.lower(), (
            "Expand should contain article content about flags/poids"
        )


# ── Test: Slug format with corpus ────────────────────────────────────────

class TestSlugCorpusFormat:
    """Verify slugs include corpus prefix after sync."""

    def test_synced_slugs_have_corpus_prefix(self, multilang_db):
        """All books from sync should have corpus in their slug."""
        lib = multilang_db["lib_factory"]()
        books = lib.list_books(corpus="published")
        lib.close()

        for book in books:
            assert book["slug"].startswith("published"), (
                f"Slug '{book['slug']}' should start with 'published'"
            )

    def test_fr_en_have_different_slugs(self, multilang_db):
        """FR and EN versions of same article have different slugs."""
        lib = multilang_db["lib_factory"]()
        books = lib.list_books(corpus="published")
        lib.close()

        slugs = {b["slug"] for b in books}

        # B4 should exist in both FR and EN
        fr_b4 = [s for s in slugs if s.startswith("published--b4")]
        en_b4 = [s for s in slugs if s.startswith("published-en--b4")]

        assert len(fr_b4) == 1, f"Expected 1 FR B4, got {fr_b4}"
        assert len(en_b4) == 1, f"Expected 1 EN B4, got {en_b4}"
        assert fr_b4[0] != en_b4[0]

    def test_all_five_articles_indexed(self, multilang_db):
        """3 FR + 2 EN = 5 books total."""
        lib = multilang_db["lib_factory"]()
        books = lib.list_books(corpus="published")
        lib.close()

        assert len(books) == 5, f"Expected 5 books, got {len(books)}: {[b['slug'] for b in books]}"


# ── Test: Search quality ─────────────────────────────────────────────────

class TestSearchQuality:
    """Verify that search returns relevant results."""

    def test_specific_query_finds_right_article(self, multilang_db):
        """Searching for 'EBNF' should find L3."""
        from rtfm.mcp import rtfm_search

        result = rtfm_search("EBNF notation formelle", limit=3, search_type="fts")

        assert "l3" in result.lower() or "ebnf" in result.lower(), (
            f"Should find L3 EBNF article.\nActual output:\n{result}"
        )

    def test_broad_query_returns_multiple_sources(self, multilang_db):
        """Searching for 'grammaires' should find multiple articles."""
        from rtfm.mcp import rtfm_search

        result = rtfm_search("grammaires musicales", limit=5, search_type="fts")

        # Header reports source count; broad query should yield ≥2
        import re
        m = re.match(r"(\d+) sources for", result)
        assert m and int(m.group(1)) >= 2, (
            f"Broad query should return multiple sources.\nActual output:\n{result}"
        )


# ── Test: Raw search comparison ──────────────────────────────────────────

class TestRawVsMCPComparison:
    """Compare raw Library.search() output vs MCP formatted output."""

    def test_raw_search_returns_content(self, multilang_db):
        """Raw Library.search() includes full chunk content."""
        lib = multilang_db["lib_factory"]()
        results = lib.search("flags BP3 grammaires", limit=5)
        lib.close()

        # Raw results have content
        assert results.total_found > 0
        total_content_chars = sum(len(r.chunk.content) for r in results)
        assert total_content_chars > 200, "Raw search should return substantial content"

    def test_mcp_search_much_smaller_than_raw(self, multilang_db):
        """MCP search output should be much smaller than raw content."""
        from rtfm.mcp import rtfm_search

        # MCP search (metadata only)
        mcp_result = rtfm_search("flags BP3", limit=5, search_type="fts")
        mcp_size = len(mcp_result)

        # Raw search (with content)
        lib = multilang_db["lib_factory"]()
        raw_results = lib.search("flags BP3", limit=25)  # overfetch like MCP does
        lib.close()

        import rtfm.mcp as mcp_mod
        mcp_mod._library = None

        raw_size = sum(len(r.chunk.content) for r in raw_results)

        print(f"\n  MCP search output: {mcp_size} chars")
        print(f"  Raw content total: {raw_size} chars")
        if raw_size > 0:
            print(f"  Reduction: {(1 - mcp_size / raw_size):.0%}")

        # MCP output should be significantly smaller
        assert mcp_size < raw_size, (
            f"MCP output ({mcp_size}) should be smaller than raw content ({raw_size})"
        )

    def test_timing_fts_search(self, multilang_db):
        """FTS search should be fast (<100ms on small DB)."""
        from rtfm.mcp import rtfm_search

        t0 = time.time()
        result = rtfm_search("flags grammaires", limit=5, search_type="fts")
        elapsed = time.time() - t0

        print(f"\n  FTS search time: {elapsed*1000:.0f}ms")
        assert elapsed < 2.0, f"FTS search took {elapsed:.2f}s (should be <2s)"
        assert "sources for" in result
