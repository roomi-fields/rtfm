"""Tests for reranking: freshness and centrality boosts."""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

from rtfm import Library
from rtfm.core.models import Chunk, SearchResult, SearchResults
from rtfm.core.sync import sync


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def ranking_db():
    """Temporary DB for ranking tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    lib = Library(db_path)
    yield lib
    lib.close()
    db_path.unlink(missing_ok=True)


@pytest.fixture
def python_project(tmp_path):
    """Project with import relations for centrality testing."""
    (tmp_path / "main.py").write_text(
        "from utils import helper\n"
        "import config\n\n"
        "def main():\n    helper()\n"
    )
    (tmp_path / "utils.py").write_text(
        "import config\n\n"
        "def helper():\n    return config.VALUE\n"
    )
    (tmp_path / "config.py").write_text(
        "VALUE = 42\n\n"
        "def get_value():\n    return VALUE\n"
    )
    return tmp_path


def _make_search_results(chunks_data: list[dict]) -> SearchResults:
    """Create SearchResults from a list of dicts."""
    results = []
    for i, data in enumerate(chunks_data, 1):
        chunk = Chunk(
            id=f"chunk-{i}",
            content=data.get("content", f"content {i}"),
            book_title=data.get("title", f"Book {i}"),
            book_slug=data.get("slug", f"book-{i}"),
            page_start=1, page_end=1,
        )
        results.append(SearchResult(
            chunk=chunk,
            score=data.get("score", 1.0),
            rank=i,
        ))
    return SearchResults(results=results, query="test", total_found=len(results))


# ── Rerank tests ─────────────────────────────────────────────────────────

class TestRerank:
    def test_no_weights_returns_unchanged(self, ranking_db):
        sr = _make_search_results([
            {"slug": "a", "score": 2.0},
            {"slug": "b", "score": 1.0},
        ])
        result = ranking_db.rerank(sr, freshness_weight=0.0, centrality_weight=0.0)
        assert len(result) == 2
        assert result[0].score == 2.0
        assert result[1].score == 1.0

    def test_empty_results(self, ranking_db):
        sr = SearchResults(results=[], query="test", total_found=0)
        result = ranking_db.rerank(sr, freshness_weight=0.1, centrality_weight=0.1)
        assert len(result) == 0

    def test_freshness_boosts_recent(self, ranking_db):
        # Ingest two books with different indexed_at dates
        conn = ranking_db._get_conn()

        now = datetime.now()
        old_date = (now - timedelta(days=365)).isoformat()
        new_date = now.isoformat()

        # Create books manually with different indexed_at
        conn.execute(
            "INSERT INTO books (slug, title, corpus, indexed_at) VALUES (?, ?, ?, ?)",
            ("old-book", "Old Book", "test", old_date),
        )
        conn.execute(
            "INSERT INTO books (slug, title, corpus, indexed_at) VALUES (?, ?, ?, ?)",
            ("new-book", "New Book", "test", new_date),
        )
        conn.commit()

        sr = _make_search_results([
            {"slug": "old-book", "score": 1.0},
            {"slug": "new-book", "score": 1.0},
        ])

        result = ranking_db.rerank(sr, freshness_weight=0.5)
        # New book should rank higher
        assert result[0].chunk.book_slug == "new-book"
        assert result[0].score > result[1].score

    def test_centrality_boosts_popular(self, ranking_db, python_project):
        sync(ranking_db, python_project, corpus="test",
             generate_embeddings=False)

        # Create search results with equal scores
        sr = _make_search_results([
            {"slug": "test--main", "score": 1.0},    # 0 incoming
            {"slug": "test--config", "score": 1.0},   # 2 incoming (imported by main + utils)
        ])

        result = ranking_db.rerank(sr, centrality_weight=0.5)
        # config should rank higher (more incoming edges)
        assert result[0].chunk.book_slug == "test--config"
        assert result[0].score > result[1].score

    def test_combined_weights(self, ranking_db, python_project):
        sync(ranking_db, python_project, corpus="test",
             generate_embeddings=False)

        sr = _make_search_results([
            {"slug": "test--main", "score": 1.0},
            {"slug": "test--config", "score": 1.0},
            {"slug": "test--utils", "score": 1.0},
        ])

        result = ranking_db.rerank(sr, freshness_weight=0.1, centrality_weight=0.3)
        # All should have boosted scores
        assert all(r.score >= 1.0 for r in result)
        # Ranks should be reassigned
        assert [r.rank for r in result] == [1, 2, 3]

    def test_rerank_preserves_query(self, ranking_db):
        sr = _make_search_results([{"slug": "a", "score": 1.0}])
        sr.query = "my special query"
        result = ranking_db.rerank(sr, freshness_weight=0.1)
        assert result.query == "my special query"

    def test_rerank_preserves_total_found(self, ranking_db):
        sr = SearchResults(
            results=[SearchResult(
                chunk=Chunk(id="c1", content="x", book_title="T", book_slug="s",
                            page_start=1, page_end=1),
                score=1.0, rank=1,
            )],
            query="test",
            total_found=42,
        )
        result = ranking_db.rerank(sr, freshness_weight=0.1)
        assert result.total_found == 42
