"""Agent 6 — Meal Plan Generator Agent (Core Agent).

Synthesises all upstream context — profile, calories, RAG knowledge,
approved foods, chat history — and produces the final response. For
meal plan requests it also extracts a structured plan dict.
"""
import json
import logging
import re
from typing import Any

import json_repair

from backend.agents.state import NutriBotState
from backend.context.builder import GenerationContext, build_context
from backend.llm.base import GenerationConfig, Message
from backend.llm.factory import get_provider
from backend.utils.food_filter import food_name_matches

logger = logging.getLogger("nutribot.agent.meal_plan")

MEAL_PLAN_INTENTS = {"MEAL_PLAN_REQUEST", "PLAN_MODIFICATION", "ROUTINE_REQUEST"}


def _build_system_prompt(context: GenerationContext, intent: str = "GENERAL_CONVERSATION") -> str:
    calorie_result = context.calorie_result

    calorie_block = ""
    if calorie_result:
        calorie_block = (
            f"\nCALORIE & MACRO TARGETS:\n"
            f"- Maintenance: {calorie_result.get('maintenance_calories', 'N/A')} kcal\n"
            f"- Goal Target: {calorie_result.get('goal_calories', 'N/A')} kcal\n"
            f"- Protein: {calorie_result.get('protein_g', 'N/A')}g | "
            f"Carbs: {calorie_result.get('carbs_g', 'N/A')}g | "
            f"Fat: {calorie_result.get('fat_g', 'N/A')}g | "
            f"Fiber: {calorie_result.get('fiber_g', 30)}g\n"
            f"(Goal Target already has any fat-loss deficit or muscle-gain surplus applied — "
            f"hit this number, don't apply a further reduction or increase on top of it.)"
        )

    rag_block = f"\nCLINICAL GUIDELINES (from knowledge base):\n{context.rag_context}" if context.rag_context else ""

    food_block = f"\n{context.food_context_str}" if context.food_context_str else ""

    prev_plans_block = ""
    if context.previous_plans:
        prev_plans_block = "\nPREVIOUS ACCEPTED MEAL PLANS (ensure variety):\n" + "\n".join(
            f"- {p.get('plan_summary', '')}" for p in context.previous_plans[-2:]
        )

    memory_block = f"\n{context.memory_context}" if context.memory_context else ""
    episodic_block = f"\n{context.episodic_context}" if context.episodic_context else ""

    return (
        f"You are {context.bot_name}, a compassionate, knowledgeable, and empathetic nutrition assistant.\n"
        f"Always address the user as {context.user_name}.\n"
        f"Always refer to yourself as {context.bot_name}.\n\n"
        f"{context.profile_context}\n"
        f"{calorie_block}\n"
        f"{rag_block}\n"
        f"{food_block}\n"
        f"{prev_plans_block}\n"
        f"{memory_block}\n"
        f"{episodic_block}\n\n"
        f"CORE INSTRUCTIONS:\n"
        f"1. Empathise first — acknowledge how the user feels before giving advice.\n"
        f"2. Every response must reflect the user's profile, goals, and medical context.\n"
        f"3. For meal plans: generate ONLY from the APPROVED FOOD OPTIONS list above — never invent foods. "
        f"You MAY use more than the listed default quantity of an approved food to help reach the calorie "
        f"target (e.g. 150g instead of 100g) — scale that item's calories/protein/carbs/fat proportionally "
        f"when you do, and use the food's exact name as listed.\n"
        f"4. For meal plans: structure must include 7 days with Breakfast, Mid-Morning Snack, Lunch, Evening Snack, Dinner.\n"
        f"5. Each meal item must list: food name, quantity (g), calories, protein, carbs, fat.\n"
        f"6. Daily totals must be within 10% of the calorie target.\n"
        f"7. Allergy enforcement is absolute — never include allergen foods.\n"
        f"8. For diabetic/PCOS users: only low-GI foods, avoid high-GI items.\n"
        f"9. For users with serious medical conditions, always add: 'Please review this plan with your doctor or dietitian.'\n"
        f"10. End meal plan responses with: 'Would you like to accept this plan, or would you like me to adjust anything?'\n"
        f"11. When generating a new plan, ensure meaningful variety from previous accepted plans.\n"
        f"12. For routine requests: include wake time, meal timings, exercise, hydration, and sleep schedule.\n"
        f"13. Tone: warm, motivating, personal. Use the user's name naturally.\n"
        + (
            f"14. This is a plan modification request. For the vast majority of modification requests "
            f"(swapping/disliking a specific food, an allergy or ingredient change, meal timing, adding "
            f"variety, etc.) just make the change directly — do not ask a clarifying question. The ONE "
            f"narrow exception: if the request is SPECIFICALLY about portion size or amount of food (e.g. "
            f"'reduce portions', 'too much food', 'smaller meals') and does NOT mention swapping/removing "
            f"a specific food or say 'lose weight'/'eat less overall', then it's genuinely ambiguous "
            f"between smaller portions at the same calorie target vs. an actual calorie reduction — ask a "
            f"short clarifying question instead (e.g. 'Do you want smaller portions spread across more "
            f"meals while keeping your {calorie_result.get('goal_calories', 'current')} kcal target, or "
            f"would you like to actually lower your daily calorie intake?'), and in that case only, do not "
            f"propose a new plan or emit the JSON block — just ask.\n\n"
            if intent == "PLAN_MODIFICATION"
            else "\n"
        )
        + (
            f"MANDATORY JSON OUTPUT (skip this entirely ONLY if you are instead asking a clarifying question "
            f"per instruction 14 above — that is the one and only exception):\n"
            f"Generate the full plan in THIS response. Do not ask clarifying questions about wake/sleep time, "
            f"workout timing, food preferences, or variety before producing it — make reasonable assumptions "
            f"from the profile above for anything unspecified (the user can ask for adjustments after seeing "
            f"the plan, which is exactly what instruction 10 above is for).\n"
            f"You MUST embed a machine-readable JSON block at the very end of your response. Do not skip it.\n\n"
            f"```meal_plan_json\n"
            f'{{"days":[{{"day":"Day 1","meals":[{{"name":"Breakfast","items":[{{"food":"Oats","quantity":"80g","calories":300,"protein":10,"carbs":54,"fat":6}}],"total_calories":300}},{{"name":"Mid-Morning Snack","items":[],"total_calories":0}},{{"name":"Lunch","items":[],"total_calories":0}},{{"name":"Evening Snack","items":[],"total_calories":0}},{{"name":"Dinner","items":[],"total_calories":0}}],"daily_totals":{{"calories":2100,"protein":158,"carbs":211,"fat":70}}}}],"calorie_target":2100,"macro_targets":{{"protein_g":158,"carbs_g":211,"fat_g":70}},"daily_routine":"Wake at 7AM, breakfast at 8AM, lunch at 1PM, dinner at 7PM, sleep at 10PM."}}\n'
            f"```\n\n"
            f"Fill ALL 7 days and ALL 5 meals per day with real foods and accurate numbers. The JSON must be valid and complete. "
            f"Every one of the 7 days must independently total within 10% of the calorie target — do not let "
            f"portions or accuracy drift for later days; use as many items per meal and scale quantities as "
            f"needed so each day, not just Day 1, lands on target."
            if intent in MEAL_PLAN_INTENTS
            else
            f"Answer the user's question clearly and thoroughly using the clinical guidelines provided above. "
            f"Do not generate a meal plan unless explicitly asked. "
            f"Cite relevant guidelines naturally in your response."
        )
    )


def _find_balanced_json(text: str, start_marker: str = "meal_plan_json") -> tuple[int, int] | None:
    """Locate a JSON object's [start, end) span via balanced-brace scanning,
    independent of markdown fence formatting. Fallback for models that don't
    reliably emit the ```meal_plan_json fence even when instructed to (seen
    with GPT-5-mini on Azure -- the JSON itself was valid, just unfenced)."""
    marker_idx = text.find(start_marker)
    start = text.find("{", marker_idx if marker_idx != -1 else 0)
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return (start, i + 1)
    return None


def _extract_plan_json_and_clean(response_text: str) -> tuple[dict[str, Any] | None, str]:
    """Extract the embedded meal_plan_json block, returning
    (parsed_plan_or_None, response_text_with_the_json_block_stripped).

    Tries the fenced ```meal_plan_json ... ``` format first (matches
    Groq/most models), falls back to balanced-brace scanning for models that
    include the JSON without the fence.
    """
    fence_pattern = r"```meal_plan_json\s*(\{.*?\})\s*```"
    match = re.search(fence_pattern, response_text, re.DOTALL)
    if match:
        candidate, cut_start, cut_end = match.group(1), match.start(), match.end()
    else:
        span = _find_balanced_json(response_text)
        if not span:
            return None, response_text.strip()
        candidate, cut_start, cut_end = response_text[span[0]:span[1]], span[0], span[1]

    try:
        plan = json.loads(candidate)
    except json.JSONDecodeError as exc:
        # LLM output occasionally has minor JSON syntax errors (trailing
        # commas, stray characters) despite being structurally intact --
        # try a repair pass before giving up entirely.
        logger.warning("Strict JSON parse failed (%s), attempting repair", exc)
        try:
            plan = json_repair.loads(candidate)
            if not isinstance(plan, dict) or "days" not in plan:
                logger.warning("Repaired JSON doesn't look like a meal plan, discarding")
                return None, response_text.strip()
            logger.info("JSON repair succeeded")
        except Exception:
            logger.exception("JSON repair also failed")
            return None, response_text.strip()

    cleaned = (response_text[:cut_start] + response_text[cut_end:]).strip()
    # Strip any leftover fence/label remnants -- e.g. a bare "meal_plan_json"
    # marker with no braces after it, left behind when the JSON was found via
    # balanced-brace scanning rather than a full fence match.
    cleaned = re.sub(r"`{0,3}\s*meal_plan_json\s*`{0,3}", "", cleaned).strip()
    return plan, cleaned


def _sanitize_plan(plan: dict[str, Any], food_context: list[dict[str, Any]]) -> dict[str, Any]:
    """Enforce the food allow-list deterministically: drop any item that doesn't
    match an approved food, then recompute totals for affected meals/days.

    This is the actual enforcement for "the model may only select from the
    approved list" — the prompt instruction alone (see CORE INSTRUCTIONS #3)
    is not a guarantee, this is. No extra LLM call, so no added rate-limit risk.
    """
    if not food_context:
        return plan

    for day in plan.get("days", []):
        for meal in day.get("meals", []):
            kept = [
                item for item in meal.get("items", [])
                if food_name_matches(item.get("food", ""), food_context)
            ]
            dropped = len(meal.get("items", [])) - len(kept)
            if dropped:
                logger.warning(
                    "Dropped %d plan item(s) not in the approved food list: %s",
                    dropped,
                    [i.get("food") for i in meal.get("items", []) if i not in kept],
                )
            meal["items"] = kept
            meal["total_calories"] = sum(float(i.get("calories", 0)) for i in kept)

        day["daily_totals"] = {
            "calories": sum(m["total_calories"] for m in day.get("meals", [])),
            "protein": sum(float(i.get("protein", 0)) for m in day.get("meals", []) for i in m.get("items", [])),
            "carbs": sum(float(i.get("carbs", 0)) for m in day.get("meals", []) for i in m.get("items", [])),
            "fat": sum(float(i.get("fat", 0)) for m in day.get("meals", []) for i in m.get("items", [])),
        }

    return plan


async def meal_plan_agent_node(state: NutriBotState) -> NutriBotState:
    intent = state.get("intent", "GENERAL_CONVERSATION")
    user_message = state.get("user_message", "")
    context = build_context(state)

    system_prompt = _build_system_prompt(context, intent)
    current_message = Message(role="user", content=user_message)

    all_messages = [Message(role="system", content=system_prompt)] + context.chat_history + [current_message]

    try:
        result = await get_provider().generate(
            messages=all_messages,
            # max_tokens=6000 was carefully tuned for Groq's 8000 TPM ceiling;
            # Azure OpenAI's real quota (100K+ TPM) has vastly more headroom.
            # If LLM_PROVIDER=groq is ever active again, this needs lowering
            # back toward 6000 or the old rate-limit truncation returns.
            config=GenerationConfig(profile="full", temperature=0.5, max_tokens=16000),
        )
        raw_text = result.text
    except Exception as exc:
        logger.exception("Meal plan generation failed: %s", exc)
        raw_text = (
            f"I'm sorry, {state.get('user_name', 'there')}, I ran into a technical issue. "
            f"Please try again in a moment."
        )

    # Extract structured plan if this is a meal plan response
    proposed_plan = None
    plan_proposed = False
    clean_response = raw_text.strip()

    if intent in MEAL_PLAN_INTENTS:
        proposed_plan, clean_response = _extract_plan_json_and_clean(raw_text)
        if proposed_plan is not None:
            proposed_plan = _sanitize_plan(proposed_plan, state.get("food_context") or [])
        plan_proposed = proposed_plan is not None

    return {
        **state,
        "response": clean_response,
        "plan_proposed": plan_proposed,
        "proposed_plan": proposed_plan,
    }
