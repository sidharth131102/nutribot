"""Agent 2 — Intent Classifier Agent.

Classifies every incoming user message into one of six intents and writes
it to state so the LangGraph router can direct flow to the right node.
"""
import logging

from backend.agents.state import NutriBotState
from backend.config import get_settings
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
- NUTRITION_QUESTION     — a substantive question about nutrition, diet, food, or health
  itself (macros, food facts, supplements, a medical condition's dietary guidance, etc.)
  — the kind of question a real answer would need to cite clinical/nutrition knowledge for.
- ROUTINE_REQUEST        — user wants a daily lifestyle/exercise/health routine
- PLAN_MODIFICATION      — user wants to modify or adjust a previously suggested plan
- GENERAL_CONVERSATION   — casual chat, greetings, motivation, reminders, small talk, and
  ANY question about the assistant/app itself rather than about nutrition — what it is,
  what it can do, how it works, who built it, capability questions, thanks/feedback, etc.
  If the word "nutrition" only appears because the user is asking about the PRODUCT
  ("what is a nutrition companion/app/assistant", "what can you help with"), that is
  GENERAL_CONVERSATION, not NUTRITION_QUESTION — nothing here needs a clinical answer.

Examples (message -> intent):
"What is a personal nutrition companion?" -> GENERAL_CONVERSATION
"What can you help me with?" -> GENERAL_CONVERSATION
"How does this app work?" -> GENERAL_CONVERSATION
"How much protein should I eat daily?" -> NUTRITION_QUESTION
"What foods should I avoid with diabetes?" -> NUTRITION_QUESTION

Reply with ONLY the intent label — no explanation, no punctuation."""


async def intent_agent_node(state: NutriBotState) -> NutriBotState:
    user_message = state.get("user_message", "")

    try:
        # A single-label classification call gains nothing from a reasoning
        # model's "thinking" tax; fast_call_provider (empty by default) lets
        # it be pinned to a faster classic model instead. See config.py.
        result = await get_provider(get_settings().fast_call_provider or None).generate(
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
