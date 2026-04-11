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


def retrieve(
    query: str,
    medical_conditions: list[str],
    diet_type: str,
    k: int | None = None,
) -> str:
    """Retrieve the top-k most relevant knowledge chunks.

    Args:
        query: The user's current message / intent description.
        medical_conditions: List of the user's medical conditions.
        diet_type: User's dietary preference (used to enrich query).
        k: Number of chunks to retrieve (defaults to settings.rag_top_k).

    Returns:
        A formatted string of retrieved knowledge chunks.
    """
    settings = get_settings()
    top_k = k or settings.rag_top_k

    if not collection_is_populated():
        logger.warning("ChromaDB collection is empty — skipping RAG retrieval")
        return "No clinical guidelines available (vector store not yet populated)."

    # Build composite search query
    condition_terms = " ".join(medical_conditions)
    composite_query = f"{query} {diet_type} {condition_terms}".strip()

    try:
        query_embedding = _embed_query(composite_query)
        collection = get_collection()

        # Try condition-filtered search first
        primary = _primary_condition(medical_conditions)
        results: Any = None

        if primary:
            try:
                results = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=top_k,
                    where={"condition": primary},
                )
            except Exception:
                results = None

        # Fallback: no filter
        if not results or not results["documents"][0]:
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
            )

        docs = results["documents"][0]
        metas = results["metadatas"][0]

        if not docs:
            return "No relevant clinical guidelines found."

        chunks: list[str] = []
        for doc, meta in zip(docs, metas):
            source = meta.get("source", "unknown")
            condition = meta.get("condition", "general")
            chunks.append(f"[Source: {source} | Condition: {condition}]\n{doc}")

        return "\n\n---\n\n".join(chunks)

    except Exception as exc:
        logger.exception("RAG retrieval failed: %s", exc)
        return "Clinical guidelines temporarily unavailable."
