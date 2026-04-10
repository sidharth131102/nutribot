from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings

from backend.config import get_settings
from backend.schemas import UserProfile
from rag.knowledge_base import DEFAULT_DOCUMENTS


class NutritionRetriever:
    """PDF RAG retriever with metadata filtering and deterministic fallback corpus."""

    def __init__(self, vector_store_path: str | None = None) -> None:
        self.vector_store_path = vector_store_path or get_settings().vector_store_path

    def _load_vector_store(self) -> FAISS | None:
        path = Path(self.vector_store_path)
        if not path.exists():
            return None
        return FAISS.load_local(
            str(path),
            OpenAIEmbeddings(),
            allow_dangerous_deserialization=True,
        )

    def _metadata_filter(self, profile: UserProfile) -> dict[str, str] | None:
        supported_conditions = {"diabetes", "pcos", "thyroid", "hypertension", "kidney"}
        for condition in profile.medical_conditions:
            normalized = condition.lower().replace("_", " ")
            if normalized in supported_conditions:
                return {"condition": normalized}
            if normalized == "kidney disease":
                return {"condition": "kidney"}
        return None

    def _semantic_retrieve(self, query: str, profile: UserProfile, k: int) -> list[str]:
        vector_store = self._load_vector_store()
        if vector_store is None:
            return []

        search_query = " ".join([query, profile.goal.value, *profile.medical_conditions])
        metadata_filter = self._metadata_filter(profile)
        docs = vector_store.similarity_search(search_query, k=k, filter=metadata_filter)
        if len(docs) < k and metadata_filter:
            docs.extend(vector_store.similarity_search(search_query, k=k - len(docs)))

        return [
            f"[source={doc.metadata.get('source', 'unknown')} type={doc.metadata.get('type', 'general')} "
            f"condition={doc.metadata.get('condition', 'general')}] {doc.page_content}"
            for doc in docs[:k]
        ]

    def retrieve(self, query: str, profile: UserProfile, k: int = 4) -> list[str]:
        semantic_docs = self._semantic_retrieve(query, profile, k)
        if semantic_docs:
            return semantic_docs

        tokens = set(query.lower().split())
        tokens.update(condition.lower() for condition in profile.medical_conditions)
        tokens.add(profile.goal.value)

        scored: list[tuple[int, str]] = []
        for document in DEFAULT_DOCUMENTS:
            text = document["text"].lower()
            score = sum(1 for token in tokens if token and token in text)
            if document["id"] in tokens:
                score += 3
            scored.append((score, document["text"]))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [text for score, text in scored[:k] if score > 0] or [
            DEFAULT_DOCUMENTS[-1]["text"]
        ]
