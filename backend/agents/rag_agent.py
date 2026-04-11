"""Agent 4 — RAG Retrieval Agent.

Performs semantic search over the ChromaDB knowledge base and returns
the top-k most relevant clinical guideline chunks.
"""
import logging

from backend.agents.state import NutriBotState
from backend.rag import retriever

logger = logging.getLogger("nutribot.agent.rag")


async def rag_agent_node(state: NutriBotState) -> NutriBotState:
    profile = state.get("user_profile", {})
    user_message = state.get("user_message", "")
    intent = state.get("intent", "")

    # Build composite query from user message + intent + conditions
    composite_query = f"{user_message} {intent}".strip()

    conditions = profile.get("medical_conditions", [])
    diet_type = profile.get("diet_type", "")

    try:
        rag_context = retriever.retrieve(
            query=composite_query,
            medical_conditions=conditions,
            diet_type=diet_type,
        )
        # Cap at 3000 chars to stay within Groq free-tier token limits
        rag_context = rag_context[:3000]
        logger.info("RAG retrieved context (%d chars) for intent=%s", len(rag_context), intent)
    except Exception as exc:
        logger.exception("RAG retrieval failed: %s", exc)
        rag_context = "Clinical guidelines temporarily unavailable."

    return {**state, "rag_context": rag_context}
