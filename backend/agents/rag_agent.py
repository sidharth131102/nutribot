"""Agent 4 — RAG Retrieval Agent.

Performs semantic search over the Pinecone knowledge base and returns
the top-k most relevant clinical guideline chunks plus source metadata.
"""
import logging

from backend.agents.state import NutriBotState
from backend.rag.retriever import retrieve_with_sources

logger = logging.getLogger("nutribot.agent.rag")


async def rag_agent_node(state: NutriBotState) -> NutriBotState:
    profile = state.get("user_profile", {})
    user_message = state.get("user_message", "")
    intent = state.get("intent", "")

    composite_query = f"{user_message} {intent}".strip()
    conditions = profile.get("medical_conditions", [])
    diet_type = profile.get("diet_type", "")

    try:
        rag_context, rag_sources = retrieve_with_sources(
            query=composite_query,
            medical_conditions=conditions,
            diet_type=diet_type,
        )
        logger.info("RAG retrieved context (%d chars, %d sources) for intent=%s",
                    len(rag_context), len(rag_sources), intent)
    except Exception as exc:
        logger.exception("RAG retrieval failed: %s", exc)
        rag_context = "Clinical guidelines temporarily unavailable."
        rag_sources = []

    return {**state, "rag_context": rag_context, "rag_sources": rag_sources}
