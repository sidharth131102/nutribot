"""Semantic search over the Pinecone knowledge base (integrated embeddings)."""
import logging
from typing import Any

from backend.config import get_settings
from backend.db.vector_store import NAMESPACE, collection_is_populated, get_index

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
    """Run a Pinecone search, falling back to no filter if needed."""
    index = get_index()
    hits: list[dict] = []

    if primary_condition:
        try:
            response = index.search(
                namespace=NAMESPACE,
                inputs={"text": query_text},
                top_k=top_k,
                filter={"condition": {"$eq": primary_condition}},
                fields=["chunk_text", "source", "condition"],
            )
            hits = response["result"]["hits"]
        except Exception:
            hits = []

    if not hits:
        response = index.search(
            namespace=NAMESPACE,
            inputs={"text": query_text},
            top_k=top_k,
            fields=["chunk_text", "source", "condition"],
        )
        hits = response["result"]["hits"]

    return hits


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
        logger.warning("Pinecone index is empty — skipping RAG retrieval")
        return "No clinical guidelines available (vector store not yet populated)."

    condition_terms = " ".join(medical_conditions)
    composite_query = f"{query} {diet_type} {condition_terms}".strip()

    try:
        hits = _search(composite_query, top_k, _primary_condition(medical_conditions))

        if not hits:
            return "No relevant clinical guidelines found."

        chunks = [
            f"[Source: {h['fields'].get('source', 'unknown')} | Condition: {h['fields'].get('condition', 'general')}]\n{h['fields'].get('chunk_text', '')}"
            for h in hits
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
        hits = _search(composite_query, top_k, _primary_condition(medical_conditions))

        if not hits:
            return "No relevant clinical guidelines found.", []

        chunks: list[str] = []
        seen: set[str] = set()
        sources: list[dict] = []

        for h in hits:
            fields: dict[str, Any] = h["fields"]
            source = fields.get("source", "unknown")
            condition = fields.get("condition", "general")
            chunks.append(f"[Source: {source} | Condition: {condition}]\n{fields.get('chunk_text', '')}")
            key = f"{source}|{condition}"
            if key not in seen:
                seen.add(key)
                sources.append({"source": source, "condition": condition})

        context = "\n\n---\n\n".join(chunks)
        return context[:3000], sources

    except Exception as exc:
        logger.exception("RAG retrieval failed: %s", exc)
        return "Clinical guidelines temporarily unavailable.", []
