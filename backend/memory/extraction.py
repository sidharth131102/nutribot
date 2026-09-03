"""Long-term semantic memory extraction (v2 roadmap Phase 3, write path).

Extraction is gated (should_attempt_extraction) rather than run on every chat
turn -- a real LLM call per message would add a 3rd Groq call on top of the
already-fragile 8000 TPM budget (see docs/CURRENT_STATE.md). Only fires for
PLAN_MODIFICATION or messages carrying an explicit preference/goal signal.
"""
import json
import logging
import re

from backend.llm.base import GenerationConfig, Message
from backend.llm.factory import get_provider
from backend.models.memory import ExtractedFact

logger = logging.getLogger("nutribot.memory.extraction")

_SIGNAL_PHRASES = [
    "i prefer", "i don't like", "i dont like", "i dislike", "i hate", "i love",
    "my goal is", "i want to switch", "from now on", "i'd rather", "id rather",
]

EXTRACTION_SYSTEM_PROMPT = """You extract durable facts worth remembering about a nutrition app user
from a single chat turn -- preferences, dislikes, lifestyle context, or a stated goal change.
Not every message has one. Only extract something genuinely worth persisting long-term,
not small talk or one-off requests.

Reply with ONLY a JSON object, no other text:
{"fact": "<short factual statement, third person, e.g. 'Dislikes oats for breakfast'>", "category": "preference"|"dislike"|"goal_context"|"lifestyle", "confidence": 0.0-1.0}
If there's nothing worth remembering, reply exactly: {"fact": null}"""


def should_attempt_extraction(intent: str, user_message: str) -> bool:
    """Pure, no LLM call. Gates whether extract_memory_fact() runs at all."""
    if intent == "PLAN_MODIFICATION":
        return True
    lowered = user_message.lower()
    return any(phrase in lowered for phrase in _SIGNAL_PHRASES)


def _extract_json(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


async def extract_memory_fact(user_message: str, response: str) -> ExtractedFact | None:
    """Only call this when should_attempt_extraction() returned True."""
    try:
        result = await get_provider().generate(
            messages=[
                Message(role="system", content=EXTRACTION_SYSTEM_PROMPT),
                Message(role="user", content=f"USER SAID: {user_message}\n\nASSISTANT REPLIED: {response}"),
            ],
            config=GenerationConfig(profile="fast", temperature=0, max_tokens=150),
        )
        parsed = _extract_json(result.text)
        if not parsed or not parsed.get("fact"):
            return None
        return ExtractedFact(**parsed)
    except Exception:
        logger.exception("Memory extraction failed")
        return None
