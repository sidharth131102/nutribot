"""Hybrid search over the knowledge base (Phase 5: RAG 2.0).

Pipeline: Pinecone dense search + local BM25 sparse search, fused via
Reciprocal Rank Fusion, then LLM-reranked down to the final top_k. Falls
back gracefully at every stage -- a missing BM25 corpus degrades to
dense-only, a failed rerank falls back to the fused order -- so hybrid
retrieval never raises where the old pure-semantic search wouldn't have.
"""
import logging
from typing import Any

from backend.config import get_settings
from backend.db.vector_store import NAMESPACE, collection_is_populated, get_index
from backend.rag.bm25_index import bm25_search
from backend.rag.fusion import hydrate_fused_results, reciprocal_rank_fusion
from backend.rag.reranker import rerank

logger = logging.getLogger("nutribot.rag.retriever")

# Map user-facing condition strings → metadata filter values
CONDITION_MAP: dict[str, str] = {
    "diabetes": "diabetes",
    "type 2 diabetes": "diabetes",
    "type2 diabetes": "diabetes",
    "pcos": "pcos",
    "polycystic ovary syndrome": "pcos",
    "hypothyroidism": "thyroid",
    "hyperthyroidism": "thyroid",
    "thyroid": "thyroid",
    "hypertension": "hypertension",
    "high blood pressure": "hypertension",
    "ckd": "kidney",
    "kidney disease": "kidney",
    "chronic kidney disease": "kidney",
}


def _primary_condition(conditions: list[str]) -> str | None:
    for cond in conditions:
        normalized = cond.strip().lower()
        if normalized in CONDITION_MAP:
            return CONDITION_MAP[normalized]
    return None


def _search(
    query_text: str,
    top_k: int,
    primary_condition: str | None,
) -> list[dict]:
    """Run a Pinecone dense search, falling back to no filter if needed."""
    index = get_index()
    hits: list[dict] = []
    fields = ["chunk_text", "source", "condition", "chunk_index"]

    if primary_condition:
        try:
            response = index.search(
                namespace=NAMESPACE,
                inputs={"text": query_text},
                top_k=top_k,
                filter={"condition": {"$eq": primary_condition}},
                fields=fields,
            )
            hits = response["result"]["hits"]
        except Exception:
            hits = []

    if not hits:
        response = index.search(
            namespace=NAMESPACE,
            inputs={"text": query_text},
            top_k=top_k,
            fields=fields,
        )
        hits = response["result"]["hits"]

    return hits


def _hit_id(hit: dict) -> str | None:
    fields = hit.get("fields", {})
    source = fields.get("source")
    chunk_index = fields.get("chunk_index")
    if source is None or chunk_index is None:
        return None
    return f"{source}::{chunk_index}"


def _hit_to_record(hit: dict) -> dict[str, Any]:
    fields = hit.get("fields", {})
    return {
        "chunk_text": fields.get("chunk_text", ""),
        "source": fields.get("source", "unknown"),
        "condition": fields.get("condition", "general"),
    }


async def _hybrid_candidates(
    composite_query: str,
    pool_size: int,
    primary_condition: str | None,
) -> list[dict[str, Any]]:
    """Dense + sparse search, fused via RRF -- the shared pipeline core for
    both retrieve() and retrieve_with_sources()."""
    dense_hits = _search(composite_query, pool_size, primary_condition)
    sparse_hits = bm25_search(composite_query, pool_size)

    dense_ids: list[str] = []
    pinecone_hits_by_id: dict[str, dict[str, Any]] = {}
    for h in dense_hits:
        hid = _hit_id(h)
        if hid:
            dense_ids.append(hid)
            pinecone_hits_by_id[hid] = _hit_to_record(h)

    sparse_ids = [c["id"] for c in sparse_hits]
    corpus_by_id = {c["id"]: c for c in sparse_hits}

    fused = reciprocal_rank_fusion([dense_ids, sparse_ids])
    fused_ids = [doc_id for doc_id, _ in fused][:pool_size]

    return hydrate_fused_results(fused_ids, pinecone_hits_by_id, corpus_by_id)


def _format_chunks(records: list[dict[str, Any]]) -> tuple[str, list[dict]]:
    chunks: list[str] = []
    seen: set[str] = set()
    sources: list[dict] = []

    for r in records:
        source = r.get("source", "unknown")
        condition = r.get("condition", "general")
        chunks.append(f"[Source: {source} | Condition: {condition}]\n{r.get('chunk_text', '')}")
        key = f"{source}|{condition}"
        if key not in seen:
            seen.add(key)
            sources.append({"source": source, "condition": condition})

    return "\n\n---\n\n".join(chunks), sources


async def retrieve(
    query: str,
    medical_conditions: list[str],
    diet_type: str,
    k: int | None = None,
) -> str:
    """Return a formatted string of the top-k most relevant knowledge chunks."""
    context, _ = await retrieve_with_sources(query, medical_conditions, diet_type, k)
    return context


async def retrieve_with_sources(
    query: str,
    medical_conditions: list[str],
    diet_type: str,
    k: int | None = None,
) -> tuple[str, list[dict]]:
    """Hybrid search (dense + BM25, RRF-fused, LLM-reranked) -- returns the
    formatted context string plus a deduplicated list of source metadata."""
    settings = get_settings()
    top_k = k or settings.rag_top_k
    pool_size = settings.rag_fusion_pool_size

    if not collection_is_populated():
        return "No clinical guidelines available (vector store not yet populated).", []

    condition_terms = " ".join(medical_conditions)
    composite_query = f"{query} {diet_type} {condition_terms}".strip()

    try:
        candidates = await _hybrid_candidates(composite_query, pool_size, _primary_condition(medical_conditions))

        if not candidates:
            return "No relevant clinical guidelines found.", []

        reranked = await rerank(composite_query, candidates, top_k)
        context, sources = _format_chunks(reranked)

        # 2000 was tuned to stay under Groq's 8000 TPM ceiling; Azure OpenAI's
        # real quota (100K+ TPM) has room for more grounding context, and
        # reranking now front-loads the most relevant chunks first, so a
        # larger cap captures more useful grounding instead of more noise.
        return context[:4000], sources

    except Exception as exc:
        logger.exception("RAG retrieval failed: %s", exc)
        return "Clinical guidelines temporarily unavailable.", []
