"""Agent 1 — Profile Context Agent (CAG).

Loads the full user profile from MongoDB and injects it as a structured
context block into the state. Also loads chat history and previous plans.
"""
import logging
from typing import Any

from backend.agents.state import NutriBotState
from backend.config import get_settings
from backend.db.mongo import UserScopedRepo, get_db

logger = logging.getLogger("nutribot.agent.profile")


def _format_profile_context(profile: dict[str, Any], previous_plans: list[dict]) -> str:
    """Build the structured profile context block injected into every LLM call."""
    weight = profile.get("weight_kg", 0)
    height = profile.get("height_cm", 0)
    bmi = round(weight / ((height / 100) ** 2), 1) if height else "N/A"

    conditions = ", ".join(profile.get("medical_conditions", [])) or "None"
    allergies = ", ".join(profile.get("allergies", [])) or "None"
    medications = profile.get("medications") or "None"

    if previous_plans:
        plans_text = "\n".join(
            f"  • Plan {i+1} (accepted {p.get('accepted_at','')[:10]}): "
            f"{p.get('plan_summary','(no summary)')}"
            for i, p in enumerate(previous_plans[-2:])
        )
    else:
        plans_text = "  None yet"

    return (
        f"USER PROFILE:\n"
        f"- Name: {profile.get('full_name')} | Gender: {profile.get('gender')} "
        f"| Age: {profile.get('age')} | Height: {height} cm "
        f"| Weight: {weight} kg | BMI: {bmi}\n"
        f"- Medical Conditions: {conditions}\n"
        f"- Food Allergies: {allergies}\n"
        f"- Current Medications: {medications}\n"
        f"- Dietary Preference: {profile.get('diet_type')}\n"
        f"- Activity Level: {profile.get('activity_level')}\n"
        f"- Health Goal: {profile.get('goal')}\n"
        f"- Previous Accepted Meal Plans:\n{plans_text}"
    )


async def profile_agent_node(state: NutriBotState) -> NutriBotState:
    user_id = state["user_id"]
    session_id = state["session_id"]
    repo = UserScopedRepo(get_db(), user_id)

    profile = await repo.get_user()
    if not profile:
        logger.error("Profile not found for user_id=%s", user_id)
        profile = {}
    elif profile.get("medical_conditions") or profile.get("allergies"):
        await repo.log_access("medical_conditions_allergies", "read", state.get("trace_id", "-"))

    previous_plans = await repo.get_accepted_plans()
    chat_history = await repo.get_session_messages(
        session_id, limit=get_settings().chat_memory_window
    )

    profile_context = _format_profile_context(profile, previous_plans)

    return {
        **state,
        "user_profile": profile,
        "profile_context": profile_context,
        "bot_name": profile.get("bot_name", "Nova"),
        "user_name": (profile.get("full_name") or "").split()[0] or "there",
        "chat_history": chat_history,
        "previous_plans": previous_plans,
    }
