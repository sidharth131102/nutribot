"""LangGraph adapter nodes for the runtime guardrails (Phase 6)."""
import logging

from backend.agents.state import NutriBotState
from backend.guardrails.input_check import check_input
from backend.guardrails.output_check import check_output

logger = logging.getLogger("nutribot.guardrails.nodes")

# One retry: at most 2 full meal-plan generations per turn. Each already
# reserves max_tokens=16000 -- unbounded retries aren't viable in a
# serverless hot path, and one corrective pass is enough for the two
# realistic failure modes (an allergen slip, a stray diagnosis sentence)
# without materially slowing the common case (most turns pass on attempt 1).
MAX_OUTPUT_REGENERATIONS = 1

# Fixed fallback -- never LLM-generated, shown only when the cap is exceeded
# and no response can be verified safe.
OUTPUT_FALLBACK_RESPONSE = (
    "I wasn't able to put together a response I'm fully confident is safe and accurate for "
    "this request. Could you try rephrasing, or ask something more specific? I'm happy to "
    "help with general nutrition questions, meal planning, and diet guidance."
)


async def input_guardrail_node(state: NutriBotState) -> NutriBotState:
    result = await check_input(state.get("user_message", ""))
    if not result.blocked:
        return {**state, "guardrail_blocked": False}

    logger.warning("Input guardrail blocked message (category=%s)", result.category)
    return {
        **state,
        "guardrail_blocked": True,
        "response": result.canned_response or "",
        "plan_proposed": False,
        "proposed_plan": None,
    }


async def output_guardrail_node(state: NutriBotState) -> NutriBotState:
    profile = state.get("user_profile", {})
    result = await check_output(
        response=state.get("response", ""),
        proposed_plan=state.get("proposed_plan"),
        food_context=state.get("food_context") or [],
        allergies=profile.get("allergies", []),
        medical_conditions=profile.get("medical_conditions", []),
    )

    if result.safe:
        return {**state, "guardrail_output_ok": True, "guardrail_blocked": False}

    count = state.get("guardrail_regeneration_count", 0)
    if count < MAX_OUTPUT_REGENERATIONS:
        logger.warning("Output guardrail failed (issues=%s), regenerating (attempt %d)", result.issues, count + 1)
        return {
            **state,
            "guardrail_output_ok": False,
            "guardrail_blocked": False,
            "guardrail_regeneration_count": count + 1,
            "guardrail_feedback": result.feedback,
        }

    logger.warning(
        "Output guardrail failed after %d regeneration(s) (issues=%s), falling back to canned response",
        count, result.issues,
    )
    return {
        **state,
        "guardrail_output_ok": False,
        "guardrail_blocked": True,
        "response": OUTPUT_FALLBACK_RESPONSE,
        "plan_proposed": False,
        "proposed_plan": None,
    }
