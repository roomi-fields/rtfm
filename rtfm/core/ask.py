"""Traceable RAG: retrieval + generation + grounding verification.

Levels:
  0 - Insufficient context detection (refuse if sources don't cover the question)
  1 - Answer with inline citations [1], [2]
  2 - Post-generation grounding verification (embeddings + optional LLM-as-judge)
"""

import json
import re
from typing import Optional

from rtfm.core.llm import LLMConfig, call_gemini
from rtfm.core.models import (
    Answer, Citation, GroundingResult, SearchResults,
)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SUFFICIENT_CONTEXT_PROMPT = """Tu recois une question et des extraits de documents.
Evalue si les extraits contiennent suffisamment d'information pour repondre a la question.
Reponds UNIQUEMENT par un JSON : {{"sufficient": true/false, "reason": "..."}}

Question : {question}

Extraits :
{context}"""

GENERATION_PROMPT = """Tu es un assistant de recherche. Reponds a la question en te basant UNIQUEMENT
sur les extraits fournis. Cite tes sources avec [1], [2], etc. correspondant au
rang de l'extrait.

REGLES :
- Ne dis RIEN qui ne soit pas dans les extraits
- Chaque affirmation doit avoir une citation [n]
- Si tu ne peux pas repondre avec les extraits, dis-le explicitement
- Reponds en francais

Question : {question}

{context}"""

JUDGE_PROMPT = """Tu es un verificateur de sources. Pour chaque affirmation ci-dessous,
verifie si elle est fidelement soutenue par l'extrait source correspondant.

Reponds en JSON : [{{"ref": n, "grounded": true/false, "reason": "..."}}]

Affirmations et sources :
{claims_and_sources}"""


# ---------------------------------------------------------------------------
# Level 0: Sufficient context check
# ---------------------------------------------------------------------------

def check_sufficient_context(
    question: str, context: str, config: LLMConfig
) -> tuple[bool, str]:
    """Check if the retrieved context is sufficient to answer the question.

    Returns:
        (is_sufficient, reason)
    """
    prompt = SUFFICIENT_CONTEXT_PROMPT.format(question=question, context=context)
    raw = call_gemini(prompt, config)

    # Parse JSON response
    try:
        # Find JSON in response
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw[start:end])
            return bool(data.get("sufficient", False)), data.get("reason", "")
    except (json.JSONDecodeError, KeyError):
        pass

    # Default: assume sufficient if we can't parse
    return True, ""


# ---------------------------------------------------------------------------
# Level 1: Generation with citations
# ---------------------------------------------------------------------------

def generate_answer(
    question: str, results: SearchResults, config: LLMConfig,
    max_context_chars: int = 6000,
) -> str:
    """Generate an answer with inline citations [n]."""
    context = results.to_prompt(max_chars=max_context_chars)
    prompt = GENERATION_PROMPT.format(question=question, context=context)
    return call_gemini(prompt, config)


def parse_citations(text: str, results: SearchResults) -> list[Citation]:
    """Extract [n] references from generated text and map them to source chunks."""
    refs = sorted(set(int(m) for m in re.findall(r"\[(\d+)\]", text)))
    citations = []
    for ref in refs:
        for r in results:
            if r.rank == ref:
                citations.append(Citation(
                    ref=ref,
                    chunk=r.chunk,
                    quote=r.content[:200],
                    score=r.score,
                ))
                break
    return citations


# ---------------------------------------------------------------------------
# Level 2: Grounding verification
# ---------------------------------------------------------------------------

def extract_claim_around_ref(text: str, ref: int, window: int = 200) -> str:
    """Extract the text surrounding a [ref] citation in the generated answer."""
    pattern = re.compile(re.escape(f"[{ref}]"))
    match = pattern.search(text)
    if not match:
        return ""
    start = max(0, match.start() - window)
    end = min(len(text), match.end() + window)
    # Extend to sentence boundaries
    snippet = text[start:end]
    # Trim to sentence start/end
    first_dot = snippet.find(". ")
    if first_dot > 0 and start > 0:
        snippet = snippet[first_dot + 2:]
    last_dot = snippet.rfind(".")
    if last_dot > 0 and end < len(text):
        snippet = snippet[:last_dot + 1]
    return snippet.strip()


def verify_grounding_embeddings(
    text: str,
    citations: list[Citation],
    threshold: float = 0.5,
) -> dict[int, GroundingResult]:
    """Verify each citation via cosine similarity (local, free).

    Compares the claim text around each [n] with the cited chunk's content.
    """
    from rtfm.core.embeddings import embed_text, cosine_similarity

    results = {}
    for citation in citations:
        claim_text = extract_claim_around_ref(text, citation.ref)
        if not claim_text:
            results[citation.ref] = GroundingResult(
                similarity=0.0, grounded=False, method="embedding"
            )
            continue

        claim_emb = embed_text(claim_text)
        chunk_emb = embed_text(citation.chunk.content)
        sim = cosine_similarity(claim_emb, chunk_emb)

        results[citation.ref] = GroundingResult(
            similarity=sim,
            grounded=sim >= threshold,
            method="embedding",
        )
    return results


def verify_grounding_llm(
    text: str,
    citations: list[Citation],
    config: LLMConfig,
) -> dict[int, GroundingResult]:
    """Verify grounding via LLM-as-judge (more precise, costs an API call)."""
    claims_and_sources = []
    for citation in citations:
        claim = extract_claim_around_ref(text, citation.ref)
        if claim:
            claims_and_sources.append(
                f"--- Affirmation [ref={citation.ref}] ---\n{claim}\n"
                f"--- Source [ref={citation.ref}] ---\n{citation.chunk.content[:500]}\n"
            )

    if not claims_and_sources:
        return {}

    prompt = JUDGE_PROMPT.format(claims_and_sources="\n".join(claims_and_sources))
    raw = call_gemini(prompt, config)

    results = {}
    try:
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start >= 0 and end > start:
            verdicts = json.loads(raw[start:end])
            for v in verdicts:
                ref = int(v["ref"])
                results[ref] = GroundingResult(
                    similarity=1.0 if v.get("grounded") else 0.0,
                    grounded=bool(v.get("grounded", False)),
                    method="llm-judge",
                )
    except (json.JSONDecodeError, KeyError, ValueError):
        # Fallback: mark all as unverified
        for citation in citations:
            if citation.ref not in results:
                results[citation.ref] = GroundingResult(
                    similarity=0.0, grounded=False, method="llm-judge"
                )

    return results


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def ask(
    question: str,
    results: SearchResults,
    config: LLMConfig,
    check_context: bool = True,
    verify: bool = True,
    deep_verify: bool = False,
    grounding_threshold: float = 0.5,
    max_context_chars: int = 6000,
) -> Answer:
    """Full orchestration: retrieval -> context check -> generation -> grounding.

    Args:
        question: User question.
        results: Pre-retrieved search results.
        config: LLM configuration.
        check_context: Enable level 0 (sufficient context check).
        verify: Enable level 2 embedding-based grounding.
        deep_verify: Enable level 2 LLM-as-judge grounding.
        grounding_threshold: Cosine similarity threshold for embedding grounding.
        max_context_chars: Max chars to send as context.

    Returns:
        Answer with citations and grounding info.
    """
    empty_answer = Answer(
        text="",
        citations=[],
        sources=results,
        sufficient_context=False,
        confidence_note="",
    )

    if not results or len(results) == 0:
        empty_answer.confidence_note = "Aucun resultat trouve pour cette question."
        return empty_answer

    context = results.to_prompt(max_chars=max_context_chars)

    # Level 0: sufficient context check
    if check_context:
        sufficient, reason = check_sufficient_context(question, context, config)
        if not sufficient:
            empty_answer.confidence_note = reason
            return empty_answer

    # Level 1: generation with citations
    raw_text = generate_answer(question, results, config, max_context_chars)
    citations = parse_citations(raw_text, results)

    # Level 2: grounding verification
    grounding_scores: dict[int, GroundingResult] = {}
    ungrounded: list[str] = []

    if deep_verify:
        grounding_scores = verify_grounding_llm(raw_text, citations, config)
        ungrounded = [
            extract_claim_around_ref(raw_text, ref)
            for ref, g in grounding_scores.items()
            if not g.grounded
        ]
    elif verify:
        grounding_scores = verify_grounding_embeddings(
            raw_text, citations, grounding_threshold
        )
        ungrounded = [
            extract_claim_around_ref(raw_text, ref)
            for ref, g in grounding_scores.items()
            if not g.grounded
        ]

    return Answer(
        text=raw_text,
        citations=citations,
        sources=results,
        sufficient_context=True,
        confidence_note="",
        grounding_scores=grounding_scores,
        ungrounded_claims=[c for c in ungrounded if c],
    )
