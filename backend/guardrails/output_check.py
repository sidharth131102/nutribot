"""Output safety/quality guardrail (Phase 6, runtime).

Two-part check: a deterministic allergen-in-prose scan (no LLM cost) plus
one LLM call for diagnosis-language/unsupported-claims/off-allow-list-food
checks. Runs after every meal_plan_agent_node call, for every intent --
diagnosis-language and fabricated-claim risk exist in plain nutrition
answers too, not just meal plans.

_sanitize_plan() in meal_plan_agent.py already enforces the food allow-list
on the *structured* plan JSON; this closes the gap that leaves free-text
prose unchecked.
"""
import json
import logging
import re
from typing import Any

from backend.guardrails.models import OutputCheckResult
from backend.llm.base import GenerationConfig, Message
from backend.llm.factory import get_provider

logger = logging.getLogger("nutribot.guardrails.output")

# Negation words within this many characters before a match don't count as a
# hit -- "avoid peanuts" is correct safety language, not an allergen leak.
_NEGATION_LOOKBACK_CHARS = 20
_NEGATION_RE = re.compile(r"\b(avoid|avoiding|no|not|without|skip|skipping|exclude|excluding|free of)\b")

OUTPUT_CHECK_SYSTEM_PROMPT = """You are a safety reviewer checking a nutrition assistant's response
before it is shown to a user. Check for:

1. Diagnosis language -- the response must never diagnose a medical condition, claim
   certainty about what a symptom means, or prescribe/adjust medication. It's fine to
   discuss diet approaches for a condition the user already told us they have.
2. Fabricated medical/clinical claims -- specific statistics, studies, or mechanisms
   presented as fact with no basis in general nutrition knowledge.
3. Foods mentioned in the text that are NOT in the approved food list below, if one is
   provided (an empty list means no plan was generated this turn -- skip this check).

Do NOT flag precise calorie, macro, or nutrient numbers just for being specific or
numeric -- those come from a verified calculation elsewhere in the system, not from
this response's own reasoning, and stating them plainly is expected and safe. Do NOT
flag ordinary, well-established nutrition guidance (e.g. "high-GI foods raise blood
sugar faster", "fiber slows digestion") as a clinical claim -- only flag something a
reasonable clinician would consider actually unsupported, invented, or medically risky.

Reply with ONLY a JSON object, no other text:
{"safe": true|false, "issues": ["short issue description", ...], "feedback": "one short corrective instruction if unsafe, empty string if safe"}"""


def _scan_allergens_in_prose(response: str, allergies: list[str]) -> list[str]:
    lowered = response.lower()
    hits = []
    for allergy in allergies:
        allergy_lower = allergy.strip().lower()
        if not allergy_lower:
            continue
        # Word-boundary match, not a bare substring -- "nut" as a plain
        # substring false-positives on "nutrition"/"nutrient"/"nutritious"
        # (this IS a nutrition assistant, so those words appear constantly),
        # and "egg" false-positives on "eggplant". \b prevents both.
        pattern = re.compile(r"\b" + re.escape(allergy_lower) + r"\b")
        for match in pattern.finditer(lowered):
            window_start = max(0, match.start() - _NEGATION_LOOKBACK_CHARS)
            window = lowered[window_start:match.start()]
            if _NEGATION_RE.search(window):
                continue
            hits.append(allergy)
            break
    return hits


def _extract_result(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


async def check_output(
    response: str,
    proposed_plan: dict[str, Any] | None,
    food_context: list[dict[str, Any]],
    allergies: list[str],
    medical_conditions: list[str],
) -> OutputCheckResult:
    """Never raises -- any failure fails open (safe=True). The deterministic
    allergen scan still runs even if the LLM call fails, so the highest-
    severity check doesn't depend on the LLM being available."""
    allergen_hits = _scan_allergens_in_prose(response, allergies)

    food_names = [f.get("food", "") for f in food_context] if food_context else []
    user_message = (
        f"MEDICAL CONDITIONS: {', '.join(medical_conditions) or 'none stated'}\n"
        f"APPROVED FOODS: {', '.join(food_names) or '(no plan generated this turn)'}\n\n"
        f"RESPONSE TO REVIEW:\n{response}"
    )

    try:
        result = await get_provider().generate(
            messages=[
                Message(role="system", content=OUTPUT_CHECK_SYSTEM_PROMPT),
                Message(role="user", content=user_message),
            ],
            config=GenerationConfig(profile="fast", temperature=0, max_tokens=250),
        )
        parsed = _extract_result(result.text)
        llm_safe = bool(parsed.get("safe", True)) if parsed else True
        # Guard against a malformed response (e.g. "issues" coming back as a
        # bare string) -- list("some string") would silently explode into
        # individual characters instead of failing loudly.
        raw_issues = parsed.get("issues") if parsed else None
        issues = [str(i) for i in raw_issues] if isinstance(raw_issues, list) else []
        raw_feedback = parsed.get("feedback") if parsed else ""
        feedback = raw_feedback if isinstance(raw_feedback, str) else ""
    except Exception:
        logger.exception("Output guardrail LLM check failed, failing open on this half")
        llm_safe, issues, feedback = True, [], ""

    if allergen_hits:
        issues = [f"mentions allergen(s) in text: {', '.join(allergen_hits)}", *issues]
        feedback = f"Remove any mention of these allergens from your response: {', '.join(allergen_hits)}. {feedback}".strip()

    return OutputCheckResult(safe=llm_safe and not allergen_hits, issues=issues, feedback=feedback)
