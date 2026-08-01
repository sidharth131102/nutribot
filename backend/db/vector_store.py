"""Pinecone interface for RAG retrieval (hosted vector store, integrated embeddings)."""
from typing import Optional

from pinecone import Index, Pinecone

from backend.config import get_settings

NAMESPACE = "knowledge"

_pc: Optional[Pinecone] = None
_index: Optional[Index] = None


def get_pinecone_client() -> Pinecone:
    global _pc
    if _pc is None:
        _pc = Pinecone(api_key=get_settings().pinecone_api_key)
    return _pc


def get_index() -> Index:
    global _index
    if _index is None:
        _index = get_pinecone_client().Index(get_settings().pinecone_index_name)
    return _index


def collection_is_populated() -> bool:
    try:
        stats = get_index().describe_index_stats()
        namespaces = stats.get("namespaces", {})
        return namespaces.get(NAMESPACE, {}).get("vector_count", 0) > 0
    except Exception:
        return False
