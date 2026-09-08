"""LLM-based reranking of fused RAG candidates (Phase 5: RAG 2.0).

Reuses the existing LLMProvider abstraction (get_provider()) -- no new
vendor SDK, no local cross-encoder model. The only file in Phase 5's new
code that calls get_provider() (invariant 6: generation stays behind one
provider interface).
"""
import json
import logging
import re
from typing import Any

from backend.llm.base import GenerationConfig, Message
from backend.llm.factory import get_provider

logger = logging.getLogger("nutribot.rag.reranker")

CANDIDATE_TEXT_CHARS = 400  # per-candidate truncation shown to the reranker -- a
# ranking judgment doesn't need the full chunk, keeps the prompt cheap across ~20 candidates

RERANK_SYSTEM_PROMPT = """You are ranking pre-vetted clinical/dietary guideline excerpts by
relevance to a user's query. These excerpts are already-approved content -- your job is
ONLY to reorder and select the most relevant ones. Never add, infer, rewrite, or summarize
content; just judge topical relevance of what's shown.

Reply with ONLY a JSON array of the candidate index numbers (0-based, as shown), in
descending relevance order. Include at most {top_k} indices. If none are relevant, reply
exactly: []"""


def _extract_index_array(text: str) -> list[int] | None:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list) or not all(isinstance(i, int) for i in parsed):
        return None
    return parsed


def _format_candidates(candidates: list[dict[str, Any]]) -> str:
    lines = []
    for i, c in enumerate(candidates):
        text = c.get("chunk_text", "")[:CANDIDATE_TEXT_CHARS]
        lines.append(f"[{i}] Source: {c.get('source', 'unknown')} | Condition: {c.get('condition', 'general')}\n{text}")
    return "\n\n".join(lines)


async def rerank(query: str, candidates: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    """Reorders/selects the top_k most relevant candidates. Never raises --
    on any failure (LLM error, unparseable response, empty result), falls
    back to candidates[:top_k] unchanged (the pre-rerank fused order)."""
    if not candidates:
        return []

    fallback = candidates[:top_k]

    try:
        result = await get_provider().generate(
            messages=[
                Message(role="system", content=RERANK_SYSTEM_PROMPT.format(top_k=top_k)),
                Message(role="user", content=f"Query: {query}\n\n{_format_candidates(candidates)}"),
            ],
            config=GenerationConfig(profile="fast", temperature=0, max_tokens=200),
        )
        indices = _extract_index_array(result.text)
        if not indices:
            return fallback

        seen: set[int] = set()
        selected: list[dict[str, Any]] = []
        for i in indices:
            if 0 <= i < len(candidates) and i not in seen:
                seen.add(i)
                selected.append(candidates[i])

        if not selected:
            return fallback

        # Pad with the next-best candidates from the original fused order
        # (not the LLM's set) if the model returned fewer than top_k.
        if len(selected) < top_k:
            for i, c in enumerate(candidates):
                if i not in seen and len(selected) < top_k:
                    selected.append(c)

        return selected[:top_k]

    except Exception:
        logger.exception("RAG reranking failed, falling back to fused order")
        return fallback
