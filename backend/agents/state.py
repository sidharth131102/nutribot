"""LangGraph shared state definition for the NutriBot pipeline."""
from typing import Any, Optional, TypedDict


class NutriBotState(TypedDict, total=False):
    # ── Input ──────────────────────────────────────────────────────────────────
    user_id: str
    session_id: str
    user_message: str

    # ── Agent 1 — Profile Context (CAG) ───────────────────────────────────────
    user_profile: dict[str, Any]          # Raw profile dict from MongoDB
    profile_context: str                  # Formatted context block for LLM
    bot_name: str
    user_name: str
    chat_history: list[dict[str, Any]]    # Last N messages
    previous_plans: list[dict[str, Any]]  # Last 2 accepted plans

    # ── Agent 2 — Intent Classifier ───────────────────────────────────────────
    intent: str  # CALORIE_CALCULATION | MEAL_PLAN_REQUEST | NUTRITION_QUESTION
                 # | ROUTINE_REQUEST | PLAN_MODIFICATION | GENERAL_CONVERSATION

    # ── Agent 3 — Calorie Calculator ──────────────────────────────────────────
    calorie_result: dict[str, float]

    # ── Agent 4 — RAG Retrieval ───────────────────────────────────────────────
    rag_context: str
    rag_sources: list[dict]  # [{source: str, condition: str}, ...]

    # ── Agent 5 — Food DB Context ─────────────────────────────────────────────
    food_context: list[dict[str, Any]]
    food_context_str: str

    # ── Agent 6 — Meal Plan Generator ─────────────────────────────────────────
    response: str
    plan_proposed: bool
    proposed_plan: Optional[dict[str, Any]]
