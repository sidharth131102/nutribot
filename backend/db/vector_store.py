"""ChromaDB interface for RAG retrieval."""
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from backend.config import get_settings

_chroma_client: Optional[chromadb.ClientAPI] = None
COLLECTION_NAME = "nutribot_knowledge"


def get_chroma_client() -> chromadb.ClientAPI:
    global _chroma_client
    if _chroma_client is None:
        settings = get_settings()
        _chroma_client = chromadb.PersistentClient(
            path=settings.chroma_persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _chroma_client


def get_collection() -> chromadb.Collection:
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def collection_is_populated() -> bool:
    try:
        return get_collection().count() > 0
    except Exception:
        return False
