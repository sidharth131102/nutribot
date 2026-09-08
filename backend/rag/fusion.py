"""Reciprocal Rank Fusion for hybrid (dense + sparse) retrieval (Phase 5: RAG 2.0).

Pure, no I/O -- combines two independently-ranked result lists (Pinecone
dense search, BM25 sparse search) into one fused ranking without needing to
compare cosine-similarity and BM25 scores directly (they're on different,
incomparable scales; RRF only uses rank position, not raw score).
"""
from typing import Any

RRF_K = 60  # standard default from the original RRF paper -- no tuning needed


def reciprocal_rank_fusion(rank_lists: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Each inner list is doc ids in rank order (best first). Returns doc ids
    sorted by fused RRF score, descending. A doc appearing near the top of
    multiple lists outranks one appearing in only one -- and one empty list
    degrades gracefully to just the other list's order (no special-casing
    needed by callers)."""
    scores: dict[str, float] = {}
    for ranked_ids in rank_lists:
        for rank, doc_id in enumerate(ranked_ids, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def hydrate_fused_results(
    fused_ids: list[str],
    pinecone_hits_by_id: dict[str, dict[str, Any]],
    corpus_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve fused ids back to full chunk dicts, in fused order. Prefers the
    BM25 corpus copy (always has complete chunk_text/metadata) over a
    Pinecone hit's fields (only has whatever fields were requested); a
    Pinecone-only hit (not in the local corpus, e.g. a stale/out-of-sync
    corpus file) still falls back to its own fields rather than being
    dropped."""
    hydrated: list[dict[str, Any]] = []
    for doc_id in fused_ids:
        record = corpus_by_id.get(doc_id) or pinecone_hits_by_id.get(doc_id)
        if record:
            hydrated.append(record)
    return hydrated
