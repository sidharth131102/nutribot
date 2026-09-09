"""Input safety guardrail (Phase 6, runtime).

Classifies the incoming user message before any expensive downstream work
(profile load, intent, RAG, meal-plan generation). Fail-open by design: a
false positive blocking a real nutrition question is worse than an
occasional false negative here, since prompt-level mitigation in
meal_plan_agent.py's system prompt is still a second layer underneath this.
"""
import json
import logging
import re

from backend.guardrails.models import InputCategory, InputCheckResult
from backend.llm.base import GenerationConfig, Message
from backend.llm.factory import get_provider

logger = logging.getLogger("nutribot.guardrails.input")

INPUT_CHECK_SYSTEM_PROMPT = """Classify the user's message into exactly one category:

- MEDICAL_EMERGENCY: describes symptoms suggesting an acute medical emergency needing
  immediate real-world medical attention right now (e.g. severe dizziness from not
  eating for days, chest pain, fainting, signs of a diabetic crisis) -- not something
  nutrition advice alone should address.
- MEDICATION_MISUSE: asks about or describes taking a prescribed medication in a way
  that deviates from what a doctor prescribed (e.g. taking multiples of a prescribed dose).
- SELF_HARM: expresses intent, means, or a plan to harm themselves.
- NONE: none of the above -- a normal nutrition/diet/meal-plan question, even one that
  factually mentions a medical condition (e.g. "I have diabetes, what should I eat").

Reply with ONLY a JSON object, no other text: {"category": "NONE"|"MEDICAL_EMERGENCY"|"MEDICATION_MISUSE"|"SELF_HARM"}"""

# Fixed, vetted strings -- the user never sees LLM-authored text for a safety
# response, only whichever of these the classifier's category selects.
CATEGORY_RESPONSES: dict[InputCategory, str] = {
    "MEDICAL_EMERGENCY": (
        "This sounds like it could be a medical emergency. I'm not able to give guidance "
        "on this — please contact a doctor, urgent care, or emergency services right away. "
        "I'm here for nutrition questions once you've been seen."
    ),
    "MEDICATION_MISUSE": (
        "I can't advise on taking a different dose of a prescribed medication than what "
        "your doctor prescribed. Please contact your prescribing doctor or pharmacist "
        "before making any change — they can help you safely."
    ),
    "SELF_HARM": (
        "I'm really glad you reached out, and I want you to be safe. I'm not able to help "
        "with this, but please reach out to a crisis line right now — in the US you can call "
        "or text 988. If you're outside the US, please contact your local emergency services "
        "or a trusted person nearby."
    ),
}


def _extract_category(text: str) -> InputCategory | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    category = parsed.get("category")
    return category if category in CATEGORY_RESPONSES or category == "NONE" else None


async def check_input(user_message: str) -> InputCheckResult:
    """Never raises -- any failure fails open (blocked=False, category=NONE)."""
    try:
        result = await get_provider().generate(
            messages=[
                Message(role="system", content=INPUT_CHECK_SYSTEM_PROMPT),
                Message(role="user", content=user_message),
            ],
            config=GenerationConfig(profile="fast", temperature=0, max_tokens=150),
        )
        category = _extract_category(result.text)
        if not category or category == "NONE":
            return InputCheckResult(blocked=False)

        return InputCheckResult(blocked=True, category=category, canned_response=CATEGORY_RESPONSES[category])

    except Exception:
        logger.exception("Input guardrail check failed, failing open")
        return InputCheckResult(blocked=False)
