"""Output safety/quality guardrail (Phase 6, runtime).

Two-part check: a deterministic allergen-in-prose scan (no LLM cost) plus
one LLM call for diagnosis-language/unsupported-claims/off-allow-list-food
checks. Runs after every meal_plan_agent_node call, for every intent --
diagnosis-language and fabricated-claim risk exist in plain nutrition
answers too, not just meal plans.

plan_builder.build_plan() already enforces the food allow-list on the
*structured* plan (anything off-list is dropped before nutrients are
computed); this closes the gap that leaves free-text prose unchecked.
"""
import json
import logging
import re
from typing import Any

from backend.config import get_settings
from backend.guardrails.models import OutputCheckResult
from backend.llm.base import GenerationConfig, Message
from backend.llm.factory import get_provider

logger = logging.getLogger("nutribot.guardrails.output")

# Negation words within this many characters before a match don't count as a
# hit -- "avoid peanuts" is correct safety language, not an allergen leak.
# Also covers explaining *why* something is avoided ("allergic to milk",
# "your soy sensitivity") -- caught live in production: a real milk-allergic
# user asking a plain protein question got the model correctly steering them
# away from dairy, and the scan blocked its own correct answer because
# "allergic"/"allergy" weren't recognised as negation language, only
# "avoid"/"without"/etc were.
#
# 20 chars was too narrow for a second, related live case: "avoid whey/casein
# because those are milk proteins" -- a causal explanation clause pushes the
# negation word ("avoid", attached to "whey/casein") 36 characters before the
# allergen it's actually about ("milk"), naming the food it's explaining
# rather than the allergen itself. Widened with margin for this shape of
# sentence; the trade-off is a same-length window before a *genuine*
# violation now also gets forgiven if a negation word happens to appear
# earlier in a long sentence -- accepted for now, revisit if that fires.
_NEGATION_LOOKBACK_CHARS = 45
_NEGATION_RE = re.compile(
    r"\b(avoid|avoiding|no|not|without|skip|skipping|exclude|excluding|free of|"
    r"allergic|allergy|allergies|sensitive|sensitivity|intolerant|intolerance|"
    r"steer clear|stay away|instead of|rather than|in place of)\b"
)
# The same negation words right AFTER the allergen ("soy-free", "nut free
# snacks", "milk allergy", "dairy sensitivity") are the same safety language
# with the negation on the other side; the lookback above can't see it, and
# it fired both on a soy-allergy plan whose prose said "soy-free" (caught in
# the eval harness) and on the live "milk allergy" case above.
#
# The character class includes Unicode hyphen variants, not just ASCII "-":
# live generations wrote "milk‑free" with U+2011 (non-breaking hyphen) far
# more often than a plain hyphen, and that alone accounted for most of the
# remaining false positives after the negation-word fixes above.
_TRAILING_AVOID_RE = re.compile(
    r"^[\s\-‐‑‒–—]*(free|allergy|allergies|allergic|sensitivity|intolerance)\b"
)

OUTPUT_CHECK_SYSTEM_PROMPT = """You are a safety reviewer checking a nutrition assistant's response
before it is shown to a user. Check for:

1. Diagnosis language -- the response must never diagnose a medical condition, claim
   certainty about what a symptom means, or prescribe/adjust medication. It's fine to
   discuss diet approaches for a condition the user already told us they have.
2. Fabricated medical/clinical claims -- specific statistics, studies, or mechanisms
   presented as fact with no basis in general nutrition knowledge.
3. Foods mentioned in the text that are NOT in the approved food list below, if one is
   provided (an empty list means no plan was generated this turn -- skip this check).
4. Allergen recommendations -- the response must never suggest, recommend, or imply the
   user should eat, drink, or use a food they are allergic to (see ALLERGIES below).
   Mentioning the allergen to explain what to avoid, to warn about hidden/derived sources
   ("check labels for milk-derived ingredients"), to name a safe substitute ("use plant milk
   instead"), or to describe what an ingredient is made of ("whey is a milk protein") is SAFE
   and expected -- flag this only if the response is actually telling the user to consume the
   allergen itself. If a note below says a deterministic scan flagged certain allergen word(s)
   in the text, read the actual sentence each one appears in and judge for yourself whether
   it's a genuine recommendation or one of the safe cases above -- the scan cannot tell the
   difference, you can.

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
            if _TRAILING_AVOID_RE.match(lowered[match.end():match.end() + 12]):
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
    severity check doesn't depend on the LLM being available.

    The deterministic scan is a blunt word-proximity heuristic -- it flags
    every mention of an allergen word, genuine recommendation or not. Live
    testing on a real milk-allergic user found it blocking its own safe,
    correct answers on nearly every turn (explaining what to avoid, warning
    about hidden/derived sources, naming substitutes -- every one of those
    legitimately mentions the allergen word). Rather than chase an
    ever-growing keyword list, the LLM check is now given the allergy list
    and an explicit rubric item to *adjudicate* the scan's findings with
    real reading comprehension. The scan still runs and its hits are always
    passed to the LLM as a hint; the LLM's verdict is trusted only when its
    call actually succeeded -- if it fails, the scan alone is the fail-closed
    fallback, same as before this change."""
    allergen_hits = _scan_allergens_in_prose(response, allergies)

    food_names = [f.get("food", "") for f in food_context] if food_context else []
    user_message = (
        f"ALLERGIES: {', '.join(allergies) or 'none stated'}\n"
        f"MEDICAL CONDITIONS: {', '.join(medical_conditions) or 'none stated'}\n"
        f"APPROVED FOODS: {', '.join(food_names) or '(no plan generated this turn)'}\n"
    )
    if allergen_hits:
        user_message += (
            f"DETERMINISTIC SCAN FLAGGED: {', '.join(allergen_hits)} -- verify per rubric "
            f"item 4 whether this is a genuine recommendation or a safe mention.\n"
        )
    user_message += f"\nRESPONSE TO REVIEW:\n{response}"

    llm_call_succeeded = False
    try:
        # A pass/fail safety judgment gains nothing from a reasoning model's
        # "thinking" tax; fast_call_provider (empty by default) lets it be
        # pinned to a faster classic model instead. See config.py.
        result = await get_provider(get_settings().fast_call_provider or None).generate(
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
        llm_call_succeeded = True
    except Exception:
        logger.exception("Output guardrail LLM check failed, failing open on this half")
        llm_safe, issues, feedback = True, [], ""

    # A deterministic hit only forces unsafe when the LLM couldn't weigh in
    # (call failed -- the scan is the sole fail-closed signal, as before) or
    # when the LLM, having actually read the flagged sentences with full
    # allergy context, agreed it's a real problem (llm_safe is False for some
    # reason -- possibly this one, possibly something else in the rubric).
    # When the LLM succeeded and judged the response safe, that verdict
    # already covered the allergen-recommendation rubric item, so a scan hit
    # on a safe mention (explaining what to avoid, a substitute, what an
    # ingredient is made of) no longer blocks a response it correctly
    # produced.
    if allergen_hits and not (llm_call_succeeded and llm_safe):
        issues = [f"mentions allergen(s) in text: {', '.join(allergen_hits)}", *issues]
        feedback = f"Remove any mention of these allergens from your response: {', '.join(allergen_hits)}. {feedback}".strip()
        llm_safe = False

    return OutputCheckResult(safe=llm_safe, issues=issues, feedback=feedback)
