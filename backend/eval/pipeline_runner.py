"""Runs a golden case through the real agent pipeline without touching MongoDB.

Reuses the exact node functions and routing predicates production uses
(backend/agents/*, backend/guardrails/*) so the harness evaluates real
behavior, not a re-implementation.
"""
from backend.agents.calorie_agent import calorie_agent_node
from backend.agents.food_agent import food_agent_node
from backend.agents.graph import (
    _route_after_calorie,
    _route_after_intent,
    _route_after_output_guardrail,
    _route_after_rag,
)
from backend.agents.intent_agent import intent_agent_node
from backend.agents.meal_plan_agent import meal_plan_agent_node
from backend.agents.profile_agent import _format_profile_context
from backend.agents.rag_agent import rag_agent_node
from backend.agents.state import NutriBotState
from backend.eval.models import GoldenCase
from backend.guardrails.nodes import MAX_OUTPUT_REGENERATIONS, input_guardrail_node, output_guardrail_node


async def run_case(case: GoldenCase) -> NutriBotState:
    profile = case.profile
    profile_context = _format_profile_context(profile, case.previous_plans)

    state: NutriBotState = {
        "user_id": f"eval-{case.id}",
        "session_id": f"eval-{case.id}",
        "user_message": case.user_message,
        "user_profile": profile,
        "profile_context": profile_context,
        "bot_name": profile.get("bot_name", "Nova"),
        "user_name": (profile.get("full_name") or "").split()[0] or "there",
        "chat_history": case.chat_history,
        "previous_plans": case.previous_plans,
    }

    state = await input_guardrail_node(state)
    if state.get("guardrail_blocked"):
        return state

    state = await intent_agent_node(state)

    next_node = _route_after_intent(state)
    if next_node == "calorie":
        state = await calorie_agent_node(state)
        next_node = _route_after_calorie(state)
    if next_node == "rag":
        state = await rag_agent_node(state)
        next_node = _route_after_rag(state)
    if next_node == "food":
        state = await food_agent_node(state)

    state = await meal_plan_agent_node(state)

    # Mirrors the real graph's meal_plan -> output_guardrail -> [regenerate?
    # meal_plan] cycle, bounded the same way (at most MAX_OUTPUT_REGENERATIONS
    # regenerations, i.e. MAX_OUTPUT_REGENERATIONS + 1 output_guardrail passes).
    for _ in range(MAX_OUTPUT_REGENERATIONS + 1):
        state = await output_guardrail_node(state)
        if _route_after_output_guardrail(state) != "regenerate":
            break
        state = await meal_plan_agent_node(state)

    return state
