"""Agent 2 — Intent Classifier Agent.

Classifies every incoming user message into one of six intents and writes
it to state so the LangGraph router can direct flow to the right node.
"""
import logging

from backend.agents.state import NutriBotState
from backend.llm.base import GenerationConfig, Message
from backend.llm.factory import get_provider

logger = logging.getLogger("nutribot.agent.intent")

VALID_INTENTS = {
    "CALORIE_CALCULATION",
    "MEAL_PLAN_REQUEST",
    "NUTRITION_QUESTION",
    "ROUTINE_REQUEST",
    "PLAN_MODIFICATION",
    "GENERAL_CONVERSATION",
}

SYSTEM_PROMPT = """You are a precise intent classifier for a nutrition assistant chatbot.
Classify the user message into EXACTLY ONE of these intents:

- CALORIE_CALCULATION    — user wants their maintenance or goal calories computed
- MEAL_PLAN_REQUEST      — user wants a full meal plan generated (7-day or otherwise)
- NUTRITION_QUESTION     — general nutrition query (macros, food facts, supplements, etc.)
- ROUTINE_REQUEST        — user wants a daily lifestyle/exercise/health routine
- PLAN_MODIFICATION      — user wants to modify or adjust a previously suggested plan
- GENERAL_CONVERSATION   — casual chat, greetings, motivation, reminders, anything else

Reply with ONLY the intent label — no explanation, no punctuation."""


async def intent_agent_node(state: NutriBotState) -> NutriBotState:
    user_message = state.get("user_message", "")

    try:
        result = await get_provider().generate(
            messages=[
                Message(role="system", content=SYSTEM_PROMPT),
                Message(role="user", content=user_message),
            ],
            config=GenerationConfig(profile="fast", temperature=0, max_tokens=100),
        )
        intent = result.text.strip().upper()

        if intent not in VALID_INTENTS:
            logger.warning("LLM returned invalid intent %r — defaulting to GENERAL_CONVERSATION", intent)
            intent = "GENERAL_CONVERSATION"
    except Exception as exc:
        logger.exception("Intent classification failed: %s", exc)
        intent = "GENERAL_CONVERSATION"

    logger.info("Intent: %s for message: %.60s", intent, user_message)
    return {**state, "intent": intent}
