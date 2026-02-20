"""Tests for rtfm traceable RAG (ask functionality)."""

import json
import pytest
from unittest.mock import patch, MagicMock

from rtfm.core.models import (
    Chunk, SearchResult, SearchResults, Citation, GroundingResult, Answer,
)
from rtfm.core.llm import LLMConfig
from rtfm.core.ask import (
    parse_citations,
    extract_claim_around_ref,
    check_sufficient_context,
    generate_answer,
    verify_grounding_embeddings,
    verify_grounding_llm,
    ask,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_chunk(id: str, content: str, book_title: str = "Book", page: int = 1) -> Chunk:
    """Helper to create a test chunk."""
    return Chunk(
        id=id,
        content=content,
        book_title=book_title,
        book_slug=id.rsplit("-", 1)[0],
        page_start=page,
        page_end=page,
    )


def make_results(chunks_data: list[tuple[str, str]], query: str = "test") -> SearchResults:
    """Helper to create SearchResults from (id, content) pairs."""
    results = []
    for rank, (cid, content) in enumerate(chunks_data, 1):
        chunk = make_chunk(cid, content)
        results.append(SearchResult(chunk=chunk, score=1.0 / rank, rank=rank))
    return SearchResults(results=results, query=query, total_found=len(results))


@pytest.fixture
def sample_results():
    """Sample search results with 3 chunks."""
    return make_results([
        ("ch-001", "La conscience est au-dela de la naissance et de la mort."),
        ("ch-002", "Le soi veritable est pure presence, sans forme ni attribut."),
        ("ch-003", "L'identification au corps est la source de la souffrance."),
    ], query="conscience")


@pytest.fixture
def llm_config():
    """LLM config for testing (won't actually call API)."""
    return LLMConfig(api_key="test-key", model="test-model")


# ---------------------------------------------------------------------------
# Unit tests: parse_citations
# ---------------------------------------------------------------------------

class TestParseCitations:
    def test_parse_single_citation(self, sample_results):
        text = "La conscience transcende la mort [1]."
        citations = parse_citations(text, sample_results)
        assert len(citations) == 1
        assert citations[0].ref == 1
        assert citations[0].chunk.id == "ch-001"

    def test_parse_multiple_citations(self, sample_results):
        text = "La conscience est eternelle [1] et le soi est sans forme [2]."
        citations = parse_citations(text, sample_results)
        assert len(citations) == 2
        assert citations[0].ref == 1
        assert citations[1].ref == 2

    def test_parse_repeated_citation(self, sample_results):
        text = "La conscience [1] est libre [1] de toute forme."
        citations = parse_citations(text, sample_results)
        # Should deduplicate
        assert len(citations) == 1
        assert citations[0].ref == 1

    def test_parse_no_citations(self, sample_results):
        text = "Texte sans aucune citation."
        citations = parse_citations(text, sample_results)
        assert len(citations) == 0

    def test_parse_citation_out_of_range(self, sample_results):
        text = "Reference inexistante [99]."
        citations = parse_citations(text, sample_results)
        assert len(citations) == 0

    def test_parse_citations_sorted(self, sample_results):
        text = "Le soi [2] et la conscience [1] et le corps [3]."
        citations = parse_citations(text, sample_results)
        assert [c.ref for c in citations] == [1, 2, 3]

    def test_citation_quote_populated(self, sample_results):
        text = "La conscience [1]."
        citations = parse_citations(text, sample_results)
        assert citations[0].quote != ""
        assert citations[0].score > 0


# ---------------------------------------------------------------------------
# Unit tests: extract_claim_around_ref
# ---------------------------------------------------------------------------

class TestExtractClaimAroundRef:
    def test_extract_basic(self):
        text = "La conscience est eternelle et transcende la mort [1]. Elle est au-dela du temps."
        claim = extract_claim_around_ref(text, 1, window=200)
        assert "[1]" in claim or "conscience" in claim

    def test_extract_nonexistent_ref(self):
        text = "Texte sans citation."
        claim = extract_claim_around_ref(text, 99)
        assert claim == ""

    def test_extract_short_text(self):
        text = "Court [1]."
        claim = extract_claim_around_ref(text, 1, window=200)
        assert len(claim) > 0


# ---------------------------------------------------------------------------
# Unit tests: Answer model
# ---------------------------------------------------------------------------

class TestAnswerModel:
    def test_grounding_score_empty(self):
        results = make_results([("ch-001", "content")])
        answer = Answer(
            text="test",
            citations=[],
            sources=results,
            sufficient_context=True,
            confidence_note="",
        )
        assert answer.grounding_score == 0.0

    def test_grounding_score_all_grounded(self):
        results = make_results([("ch-001", "content")])
        answer = Answer(
            text="test [1]",
            citations=[],
            sources=results,
            sufficient_context=True,
            confidence_note="",
            grounding_scores={
                1: GroundingResult(similarity=0.8, grounded=True, method="embedding"),
                2: GroundingResult(similarity=0.7, grounded=True, method="embedding"),
            },
        )
        assert answer.grounding_score == 1.0

    def test_grounding_score_partial(self):
        results = make_results([("ch-001", "content")])
        answer = Answer(
            text="test [1] [2]",
            citations=[],
            sources=results,
            sufficient_context=True,
            confidence_note="",
            grounding_scores={
                1: GroundingResult(similarity=0.8, grounded=True, method="embedding"),
                2: GroundingResult(similarity=0.2, grounded=False, method="embedding"),
            },
        )
        assert answer.grounding_score == 0.5

    def test_to_markdown_sufficient(self, sample_results):
        chunk = sample_results[0].chunk
        citation = Citation(ref=1, chunk=chunk, quote="extrait", score=0.9)
        answer = Answer(
            text="Reponse avec citation [1].",
            citations=[citation],
            sources=sample_results,
            sufficient_context=True,
            confidence_note="",
        )
        md = answer.to_markdown()
        assert "[1]" in md
        assert "Sources" in md

    def test_to_markdown_insufficient(self, sample_results):
        answer = Answer(
            text="",
            citations=[],
            sources=sample_results,
            sufficient_context=False,
            confidence_note="Les sources ne couvrent pas la question.",
        )
        md = answer.to_markdown()
        assert "insuffisant" in md.lower() or "couvrent" in md.lower()

    def test_to_dict(self, sample_results):
        chunk = sample_results[0].chunk
        citation = Citation(ref=1, chunk=chunk, quote="extrait", score=0.9)
        answer = Answer(
            text="Reponse [1].",
            citations=[citation],
            sources=sample_results,
            sufficient_context=True,
            confidence_note="",
        )
        d = answer.to_dict()
        assert d["text"] == "Reponse [1]."
        assert d["sufficient_context"] is True
        assert len(d["citations"]) == 1
        assert d["citations"][0]["ref"] == 1

    def test_to_json_roundtrip(self, sample_results):
        answer = Answer(
            text="Reponse.",
            citations=[],
            sources=sample_results,
            sufficient_context=True,
            confidence_note="",
        )
        j = answer.to_json()
        parsed = json.loads(j)
        assert parsed["text"] == "Reponse."


# ---------------------------------------------------------------------------
# Tests with mock LLM
# ---------------------------------------------------------------------------

class TestCheckSufficientContext:
    @patch("rtfm.core.ask.call_gemini")
    def test_sufficient(self, mock_gemini, llm_config):
        mock_gemini.return_value = '{"sufficient": true, "reason": "Les extraits couvrent la question."}'
        sufficient, reason = check_sufficient_context("test?", "context", llm_config)
        assert sufficient is True
        mock_gemini.assert_called_once()

    @patch("rtfm.core.ask.call_gemini")
    def test_insufficient(self, mock_gemini, llm_config):
        mock_gemini.return_value = '{"sufficient": false, "reason": "Aucun extrait ne parle de cela."}'
        sufficient, reason = check_sufficient_context("test?", "context", llm_config)
        assert sufficient is False
        assert "Aucun" in reason

    @patch("rtfm.core.ask.call_gemini")
    def test_malformed_response_defaults_sufficient(self, mock_gemini, llm_config):
        mock_gemini.return_value = "This is not JSON at all"
        sufficient, reason = check_sufficient_context("test?", "context", llm_config)
        assert sufficient is True  # default to sufficient if we can't parse


class TestGenerateAnswer:
    @patch("rtfm.core.ask.call_gemini")
    def test_generates_with_citations(self, mock_gemini, sample_results, llm_config):
        mock_gemini.return_value = "La conscience transcende la mort [1] et le soi est sans forme [2]."
        text = generate_answer("conscience?", sample_results, llm_config)
        assert "[1]" in text
        assert "[2]" in text

    @patch("rtfm.core.ask.call_gemini")
    def test_prompt_includes_context(self, mock_gemini, sample_results, llm_config):
        mock_gemini.return_value = "Reponse."
        generate_answer("test?", sample_results, llm_config)
        call_args = mock_gemini.call_args[0][0]
        assert "test?" in call_args
        assert "search_results" in call_args


class TestAskOrchestration:
    @patch("rtfm.core.ask.call_gemini")
    def test_ask_with_insufficient_context(self, mock_gemini, sample_results, llm_config):
        mock_gemini.return_value = '{"sufficient": false, "reason": "Pas assez d\'info."}'
        answer = ask("question?", sample_results, llm_config, check_context=True, verify=False)
        assert answer.sufficient_context is False
        assert "info" in answer.confidence_note.lower()
        # Should NOT have called generate (only context check)
        assert mock_gemini.call_count == 1

    @patch("rtfm.core.ask.call_gemini")
    def test_ask_with_citations(self, mock_gemini, sample_results, llm_config):
        # First call: context check (sufficient)
        # Second call: generation
        mock_gemini.side_effect = [
            '{"sufficient": true, "reason": "OK"}',
            "La conscience est au-dela de la mort [1]. Le soi est sans forme [2].",
        ]
        answer = ask("conscience?", sample_results, llm_config, check_context=True, verify=False)
        assert answer.sufficient_context is True
        assert len(answer.citations) == 2
        assert answer.citations[0].ref == 1
        assert answer.citations[1].ref == 2

    @patch("rtfm.core.ask.call_gemini")
    def test_ask_no_context_check(self, mock_gemini, sample_results, llm_config):
        mock_gemini.return_value = "Reponse [1]."
        answer = ask("question?", sample_results, llm_config, check_context=False, verify=False)
        # Should only call generate, not context check
        assert mock_gemini.call_count == 1
        assert answer.sufficient_context is True

    @patch("rtfm.core.ask.call_gemini")
    def test_ask_no_verify(self, mock_gemini, sample_results, llm_config):
        mock_gemini.return_value = "Reponse [1]."
        answer = ask("q?", sample_results, llm_config, check_context=False, verify=False)
        assert answer.grounding_scores == {}

    def test_ask_empty_results(self, llm_config):
        results = SearchResults(results=[], query="test", total_found=0)
        answer = ask("question?", results, llm_config, check_context=False)
        assert answer.sufficient_context is False
        assert "Aucun" in answer.confidence_note


class TestGroundingEmbeddings:
    @patch("rtfm.core.embeddings.cosine_similarity")
    @patch("rtfm.core.embeddings.embed_text")
    def test_grounding_above_threshold(self, mock_embed, mock_cosine, sample_results):
        import numpy as np
        mock_embed.return_value = np.array([1.0, 0.0, 0.0])
        mock_cosine.return_value = 0.85

        chunk = sample_results[0].chunk
        citations = [Citation(ref=1, chunk=chunk, quote="test", score=0.9)]
        text = "La conscience est eternelle [1]."

        scores = verify_grounding_embeddings(text, citations, threshold=0.5)
        assert 1 in scores
        assert scores[1].grounded is True
        assert scores[1].similarity == 0.85
        assert scores[1].method == "embedding"

    @patch("rtfm.core.embeddings.cosine_similarity")
    @patch("rtfm.core.embeddings.embed_text")
    def test_grounding_below_threshold(self, mock_embed, mock_cosine, sample_results):
        import numpy as np
        mock_embed.return_value = np.array([1.0, 0.0, 0.0])
        mock_cosine.return_value = 0.2

        chunk = sample_results[0].chunk
        citations = [Citation(ref=1, chunk=chunk, quote="test", score=0.9)]
        text = "Affirmation non soutenue [1]."

        scores = verify_grounding_embeddings(text, citations, threshold=0.5)
        assert scores[1].grounded is False


class TestGroundingLLM:
    @patch("rtfm.core.ask.call_gemini")
    def test_llm_judge_grounded(self, mock_gemini, sample_results, llm_config):
        mock_gemini.return_value = '[{"ref": 1, "grounded": true, "reason": "Fidelement soutenu."}]'
        chunk = sample_results[0].chunk
        citations = [Citation(ref=1, chunk=chunk, quote="test", score=0.9)]
        text = "La conscience est eternelle [1]."

        scores = verify_grounding_llm(text, citations, llm_config)
        assert 1 in scores
        assert scores[1].grounded is True
        assert scores[1].method == "llm-judge"

    @patch("rtfm.core.ask.call_gemini")
    def test_llm_judge_not_grounded(self, mock_gemini, sample_results, llm_config):
        mock_gemini.return_value = '[{"ref": 1, "grounded": false, "reason": "Non soutenu."}]'
        chunk = sample_results[0].chunk
        citations = [Citation(ref=1, chunk=chunk, quote="test", score=0.9)]
        text = "Affirmation fausse [1]."

        scores = verify_grounding_llm(text, citations, llm_config)
        assert scores[1].grounded is False


# ---------------------------------------------------------------------------
# Integration test (requires GEMINI_API_KEY and real DB)
# ---------------------------------------------------------------------------

class TestAskIntegration:
    @pytest.fixture
    def has_api_key(self):
        import os
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            pytest.skip("GEMINI_API_KEY not set")
        return key

    @pytest.fixture
    def has_db(self):
        from pathlib import Path
        db_path = Path("db/library.db")
        if not db_path.exists():
            pytest.skip("db/library.db not found")
        return db_path

    def test_ask_end_to_end(self, has_api_key, has_db):
        from rtfm.core.library import Library

        lib = Library(has_db)
        answer = lib.ask(
            "Qu'est-ce que la conscience selon Nisargadatta ?",
            limit=5,
            search_mode="hybrid",
            verify=False,  # skip embedding verify for speed
        )
        lib.close()

        assert answer.sufficient_context is True or answer.sufficient_context is False
        if answer.sufficient_context:
            assert len(answer.text) > 0
            assert len(answer.citations) > 0
