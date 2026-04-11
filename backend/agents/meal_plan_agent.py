"""Agent 6 — Meal Plan Generator Agent (Core Agent).

Synthesises all upstream context — profile, calories, RAG knowledge,
approved foods, chat history — and produces the final response. For
meal plan requests it also extracts a structured plan dict.
"""
import json
import logging
import re
from typing import Any

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.state import NutriBotState
from backend.config import get_settings

logger = logging.getLogger("nutribot.agent.meal_plan")

MEAL_PLAN_INTENTS = {"MEAL_PLAN_REQUEST", "PLAN_MODIFICATION", "ROUTINE_REQUEST"}


def _build_system_prompt(state: NutriBotState) -> str:
    bot_name = state.get("bot_name", "Nova")
    user_name = state.get("user_name", "there")
    profile_context = state.get("profile_context", "")
    calorie_result = state.get("calorie_result", {})
    rag_context = state.get("rag_context", "")
    food_context_str = state.get("food_context_str", "")
    previous_plans = state.get("previous_plans", [])

    calorie_block = ""
    if calorie_result:
        calorie_block = (
            f"\nCALORIE & MACRO TARGETS:\n"
            f"- Maintenance: {calorie_result.get('maintenance_calories', 'N/A')} kcal\n"
            f"- Goal Target: {calorie_result.get('goal_calories', 'N/A')} kcal\n"
            f"- Protein: {calorie_result.get('protein_g', 'N/A')}g | "
            f"Carbs: {calorie_result.get('carbs_g', 'N/A')}g | "
            f"Fat: {calorie_result.get('fat_g', 'N/A')}g | "
            f"Fiber: {calorie_result.get('fiber_g', 30)}g"
        )

    rag_block = f"\nCLINICAL GUIDELINES (from knowledge base):\n{rag_context}" if rag_context else ""

    food_block = f"\n{food_context_str}" if food_context_str else ""

    prev_plans_block = ""
    if previous_plans:
        prev_plans_block = "\nPREVIOUS ACCEPTED MEAL PLANS (ensure variety):\n" + "\n".join(
            f"- {p.get('plan_summary', '')}" for p in previous_plans[-2:]
        )

    return (
        f"You are {bot_name}, a compassionate, knowledgeable, and empathetic nutrition assistant.\n"
        f"Always address the user as {user_name}.\n"
        f"Always refer to yourself as {bot_name}.\n\n"
        f"{profile_context}\n"
        f"{calorie_block}\n"
        f"{rag_block}\n"
        f"{food_block}\n"
        f"{prev_plans_block}\n\n"
        f"CORE INSTRUCTIONS:\n"
        f"1. Empathise first — acknowledge how the user feels before giving advice.\n"
        f"2. Every response must reflect the user's profile, goals, and medical context.\n"
        f"3. For meal plans: generate ONLY from the APPROVED FOOD OPTIONS list above — never invent foods.\n"
        f"4. For meal plans: structure must include 7 days with Breakfast, Mid-Morning Snack, Lunch, Evening Snack, Dinner.\n"
        f"5. Each meal item must list: food name, quantity (g), calories, protein, carbs, fat.\n"
        f"6. Daily totals must match calorie target ±50 kcal.\n"
        f"7. Allergy enforcement is absolute — never include allergen foods.\n"
        f"8. For diabetic/PCOS users: only low-GI foods, avoid high-GI items.\n"
        f"9. For users with serious medical conditions, always add: 'Please review this plan with your doctor or dietitian.'\n"
        f"10. End meal plan responses with: 'Would you like to accept this plan, or would you like me to adjust anything?'\n"
        f"11. When generating a new plan, ensure meaningful variety from previous accepted plans.\n"
        f"12. For routine requests: include wake time, meal timings, exercise, hydration, and sleep schedule.\n"
        f"13. Tone: warm, motivating, personal. Use the user's name naturally.\n\n"
        f"MANDATORY JSON OUTPUT FOR MEAL PLANS:\n"
        f"You MUST embed a machine-readable JSON block in EVERY meal plan response. This is required — do not skip it.\n"
        f"Place it at the very end of your response using this exact format (no extra text after it):\n\n"
        f"```meal_plan_json\n"
        f'{{"days":[{{"day":"Day 1","meals":[{{"name":"Breakfast","items":[{{"food":"Oats","quantity":"80g","calories":300,"protein":10,"carbs":54,"fat":6}}],"total_calories":300}},{{"name":"Mid-Morning Snack","items":[],"total_calories":0}},{{"name":"Lunch","items":[],"total_calories":0}},{{"name":"Evening Snack","items":[],"total_calories":0}},{{"name":"Dinner","items":[],"total_calories":0}}],"daily_totals":{{"calories":2100,"protein":158,"carbs":211,"fat":70}}}}],"calorie_target":2100,"macro_targets":{{"protein_g":158,"carbs_g":211,"fat_g":70}},"daily_routine":"Wake at 7AM, breakfast at 8AM, lunch at 1PM, dinner at 7PM, sleep at 10PM."}}\n'
        f"```\n\n"
        f"Fill ALL 7 days and ALL 5 meals per day with real foods and accurate numbers. The JSON must be valid and complete."
    )


def _extract_plan_json(response_text: str) -> dict[str, Any] | None:
    """Extract the embedded meal_plan_json block from the LLM response."""
    pattern = r"```meal_plan_json\s*(\{.*?\})\s*```"
    match = re.search(pattern, response_text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse embedded meal plan JSON: %s", exc)
        return None


def _clean_response(text: str) -> str:
    """Remove the raw JSON block from the user-visible response."""
    return re.sub(r"```meal_plan_json.*?```", "", text, flags=re.DOTALL).strip()


def _format_history(messages: list[dict]) -> list:
    """Convert stored messages to LangChain message objects."""
    from langchain_core.messages import AIMessage
    formatted = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            formatted.append(HumanMessage(content=content))
        else:
            formatted.append(AIMessage(content=content))
    return formatted


def _llm() -> ChatGroq:
    settings = get_settings()
    return ChatGroq(
        model=settings.llm_model,
        api_key=settings.groq_api_key,
        temperature=0.7,
        max_tokens=8192,
    )


async def meal_plan_agent_node(state: NutriBotState) -> NutriBotState:
    intent = state.get("intent", "GENERAL_CONVERSATION")
    user_message = state.get("user_message", "")
    chat_history = state.get("chat_history", [])

    system_prompt = _build_system_prompt(state)
    history_messages = _format_history(chat_history)
    current_message = HumanMessage(content=user_message)

    all_messages = [SystemMessage(content=system_prompt)] + history_messages + [current_message]

    try:
        response = await _llm().ainvoke(all_messages)
        raw_text = response.content if isinstance(response.content, str) else str(response.content)
    except Exception as exc:
        logger.exception("Meal plan generation failed: %s", exc)
        raw_text = (
            f"I'm sorry, {state.get('user_name', 'there')}, I ran into a technical issue. "
            f"Please try again in a moment."
        )

    # Extract structured plan if this is a meal plan response
    proposed_plan = None
    plan_proposed = False

    if intent in MEAL_PLAN_INTENTS:
        proposed_plan = _extract_plan_json(raw_text)
        plan_proposed = proposed_plan is not None

    clean_response = _clean_response(raw_text)

    return {
        **state,
        "response": clean_response,
        "plan_proposed": plan_proposed,
        "proposed_plan": proposed_plan,
    }
