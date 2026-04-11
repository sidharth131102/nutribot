"""Semantic search over the ChromaDB knowledge base."""
import logging
from typing import Any

from backend.config import get_settings
from backend.db.vector_store import collection_is_populated, get_collection

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


def _embed_query(text: str) -> list[float]:
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
    embed_fn = DefaultEmbeddingFunction()
    return embed_fn([text])[0]


def _primary_condition(conditions: list[str]) -> str | None:
    for cond in conditions:
        normalized = cond.strip().lower()
        if normalized in CONDITION_MAP:
            return CONDITION_MAP[normalized]
    return None


def _query_collection(
    query_embedding: list[float],
    top_k: int,
    primary_condition: str | None,
) -> tuple[list[str], list[dict]]:
    """Run ChromaDB query, falling back to no filter if needed."""
    collection = get_collection()
    results: Any = None

    if primary_condition:
        try:
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where={"condition": primary_condition},
            )
        except Exception:
            results = None

    if not results or not results["documents"][0]:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
        )

    return results["documents"][0], results["metadatas"][0]


def retrieve(
    query: str,
    medical_conditions: list[str],
    diet_type: str,
    k: int | None = None,
) -> str:
    """Return a formatted string of the top-k most relevant knowledge chunks."""
    settings = get_settings()
    top_k = k or settings.rag_top_k

    if not collection_is_populated():
        logger.warning("ChromaDB collection is empty — skipping RAG retrieval")
        return "No clinical guidelines available (vector store not yet populated)."

    condition_terms = " ".join(medical_conditions)
    composite_query = f"{query} {diet_type} {condition_terms}".strip()

    try:
        query_embedding = _embed_query(composite_query)
        docs, metas = _query_collection(query_embedding, top_k, _primary_condition(medical_conditions))

        if not docs:
            return "No relevant clinical guidelines found."

        chunks = [
            f"[Source: {m.get('source', 'unknown')} | Condition: {m.get('condition', 'general')}]\n{d}"
            for d, m in zip(docs, metas)
        ]
        return "\n\n---\n\n".join(chunks)

    except Exception as exc:
        logger.exception("RAG retrieval failed: %s", exc)
        return "Clinical guidelines temporarily unavailable."


def retrieve_with_sources(
    query: str,
    medical_conditions: list[str],
    diet_type: str,
    k: int | None = None,
) -> tuple[str, list[dict]]:
    """Like retrieve() but also returns a deduplicated list of source metadata dicts."""
    settings = get_settings()
    top_k = k or settings.rag_top_k

    if not collection_is_populated():
        return "No clinical guidelines available (vector store not yet populated).", []

    condition_terms = " ".join(medical_conditions)
    composite_query = f"{query} {diet_type} {condition_terms}".strip()

    try:
        query_embedding = _embed_query(composite_query)
        docs, metas = _query_collection(query_embedding, top_k, _primary_condition(medical_conditions))

        if not docs:
            return "No relevant clinical guidelines found.", []

        chunks: list[str] = []
        seen: set[str] = set()
        sources: list[dict] = []

        for doc, meta in zip(docs, metas):
            source = meta.get("source", "unknown")
            condition = meta.get("condition", "general")
            chunks.append(f"[Source: {source} | Condition: {condition}]\n{doc}")
            key = f"{source}|{condition}"
            if key not in seen:
                seen.add(key)
                sources.append({"source": source, "condition": condition})

        context = "\n\n---\n\n".join(chunks)
        return context[:3000], sources

    except Exception as exc:
        logger.exception("RAG retrieval failed: %s", exc)
        return "Clinical guidelines temporarily unavailable.", []
