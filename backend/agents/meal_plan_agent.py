"""Agent 6 — Meal Plan Generator Agent (Core Agent).

Synthesises all upstream context — profile, calories, RAG knowledge,
approved foods, chat history — and produces the final response.

Meal-plan intents run as TWO generation calls with deterministic code in
between (see backend/agents/plan_builder.py for why):

  1. SELECTION  -- the model returns only JSON: which approved foods go in
     each meal, and roughly how many grams. No calorie arithmetic.
  2. plan_builder.build_plan() computes every nutrient from food_db.json,
     rebalances any day that misses the target, and renders the plan text.
  3. PROSE      -- the model writes the warm, personalised message *around*
     the finished plan. It's told not to restate the table; the rendered
     plan and the accept prompt are appended by code.

So no number the user reads was produced by the model. Non-plan intents
(questions, calorie results, general conversation) stay a single call.
"""
import json
import logging
import re
from typing import Any

import json_repair

from backend.agents.plan_builder import PlanBuildReport, build_plan, render_plan_markdown
from backend.agents.state import NutriBotState
from backend.context.builder import GenerationContext, build_context
from backend.llm.base import GenerationConfig, Message
from backend.llm.factory import get_provider

logger = logging.getLogger("nutribot.agent.meal_plan")

MEAL_PLAN_INTENTS = {"MEAL_PLAN_REQUEST", "PLAN_MODIFICATION", "ROUTINE_REQUEST"}

ACCEPT_PROMPT = "Would you like to accept this plan, or would you like me to adjust anything?"
DOCTOR_NOTE = "Please review this plan with your doctor or dietitian."

# The selection call gets one retry on unparseable output. Two failures in a
# row means something is genuinely wrong (provider outage, truncated output)
# and the user gets an honest "try again", not a third 8K-token attempt.
SELECTION_MAX_ATTEMPTS = 2

# Selection is deterministic bookkeeping (pick foods, pick grams) -- low
# temperature keeps it on-list and on-shape. Prose is where warmth lives.
# Budgets are generous on purpose: on a reasoning model (gpt-5 family) the
# hidden reasoning tokens count against max_tokens, and a tight budget
# yields an EMPTY completion rather than a truncated one (hit 3+ times).
SELECTION_CONFIG = GenerationConfig(profile="full", temperature=0.2, max_tokens=10000)
PROSE_CONFIG = GenerationConfig(profile="full", temperature=0.5, max_tokens=4000)
# Non-plan answers: max_tokens=6000 was tuned for Groq's 8000 TPM ceiling;
# Azure's quota has far more headroom. Lower it again if Groq is reactivated.
ANSWER_CONFIG = GenerationConfig(profile="full", temperature=0.5, max_tokens=6000)


def _technical_issue(user_name: str) -> str:
    return (
        f"I'm sorry, {user_name}, I ran into a technical issue. "
        f"Please try again in a moment."
    )


# ── Prompt pieces ───────────────────────────────────────────────────────────

def _calorie_block(calorie_result: dict[str, Any]) -> str:
    if not calorie_result:
        return ""
    return (
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


def _persona_block(context: GenerationContext) -> str:
    return (
        f"You are {context.bot_name}, a compassionate, knowledgeable, and empathetic nutrition assistant.\n"
        f"Always address the user as {context.user_name}.\n"
        f"Always refer to yourself as {context.bot_name}.\n\n"
        f"{context.profile_context}\n"
    )


def _shared_context(context: GenerationContext, *, include_food_list: bool) -> str:
    rag_block = f"\nCLINICAL GUIDELINES (from knowledge base):\n{context.rag_context}" if context.rag_context else ""
    food_block = f"\n{context.food_context_str}" if (include_food_list and context.food_context_str) else ""
    prev_plans_block = ""
    if context.previous_plans:
        prev_plans_block = "\nPREVIOUS ACCEPTED MEAL PLANS (ensure variety):\n" + "\n".join(
            f"- {p.get('plan_summary', '')}" for p in context.previous_plans[-2:]
        )
    memory_block = f"\n{context.memory_context}" if context.memory_context else ""
    episodic_block = f"\n{context.episodic_context}" if context.episodic_context else ""
    return (
        f"{_calorie_block(context.calorie_result)}\n"
        f"{rag_block}\n"
        f"{food_block}\n"
        f"{prev_plans_block}\n"
        f"{memory_block}\n"
        f"{episodic_block}\n"
    )


def _correction_block(guardrail_feedback: str | None) -> str:
    if not guardrail_feedback:
        return ""
    return (
        f"\n\nCORRECTION REQUIRED: your previous response for this exact request had a problem — "
        f"{guardrail_feedback} Regenerate a corrected response that fixes this."
    )


def _build_selection_prompt(
    context: GenerationContext,
    intent: str,
    guardrail_feedback: str | None = None,
) -> str:
    """Call 1: JSON only -- foods and grams per meal. The system computes nutrients."""
    goal = context.calorie_result.get("goal_calories", "the calorie target")
    routine_rule = (
        "- \"daily_routine\": a detailed schedule for the day — wake time, each meal's time, workout "
        "(type and time), hydration, and sleep time — as one string with line breaks.\n"
        if intent == "ROUTINE_REQUEST"
        else "- \"daily_routine\": one line with wake time, meal times, exercise slot, and sleep time.\n"
    )
    modification_rule = (
        f"- This is a modification of the user's existing plan. Apply the requested change and keep "
        f"everything else consistent with their profile and goal. For the vast majority of requests "
        f"(swapping/disliking a specific food, an allergy or ingredient change, meal timing, adding "
        f"variety, etc.) just make the change — do not ask a question. The ONE narrow exception: if "
        f"the request is SPECIFICALLY about portion size or amount of food (e.g. 'reduce portions', "
        f"'too much food', 'smaller meals') and does NOT mention swapping/removing a specific food or "
        f"say 'lose weight'/'eat less overall', it's genuinely ambiguous between smaller portions at "
        f"the same calorie target vs. an actual calorie reduction. In that case ONLY, return "
        f"{{\"clarifying_question\": \"...\"}} instead of days — a warm, 1-3 sentence question addressed "
        f"to {context.user_name} asking whether they want smaller portions spread across more meals "
        f"while keeping their {goal} kcal target, or to actually lower their daily calorie intake.\n"
        if intent == "PLAN_MODIFICATION"
        else ""
    )
    return (
        f"You are {context.bot_name}, selecting foods for a 7-day meal plan for {context.user_name}. "
        f"Output ONLY a JSON object — no prose, no markdown fence, no explanation.\n\n"
        f"{context.profile_context}\n"
        f"{_shared_context(context, include_food_list=True)}\n"
        f"RULES:\n"
        f"- Use ONLY foods from APPROVED FOOD OPTIONS above, with each food's exact name as listed. "
        f"Never invent a food. Any item not on the list is discarded.\n"
        f"- Exactly 7 days. Each day has exactly these 5 meals, in this order: Breakfast, Mid-Morning "
        f"Snack, Lunch, Evening Snack, Dinner. Use 2-4 items for Breakfast/Lunch/Dinner and 1-2 for "
        f"each snack, choosing foods whose listed meal types fit the slot.\n"
        f"- For every item give \"grams\" (a number). The table shows each food's calories at its "
        f"listed serving size; pick amounts so that each day's items add up close to the Goal "
        f"Target of {goal} kcal. Do NOT write calories or macros yourself — the system computes every "
        f"nutrient from the grams you give and will fine-tune portions if a day is off. Selections "
        f"typically come out 25-40% SHORT of the target, so be generous: for main meals use 1.5-2x a "
        f"food's listed serving size when the target is above 2500 kcal, and add a starchy staple "
        f"(oats, roti, rice) or a fat source (nuts, oil, nut butter) to every main meal.\n"
        f"- Allergy enforcement is absolute. For diabetic/PCOS users use only low-GI foods.\n"
        f"- Vary foods across the 7 days and from any previous accepted plans. Respect remembered "
        f"preferences (e.g. a disliked food is never used).\n"
        f"{routine_rule}"
        f"{modification_rule}"
        f"\nJSON SHAPE (fill all 7 days):\n"
        f'{{"days":[{{"day":"Day 1","meals":[{{"name":"Breakfast","items":[{{"food":"oats","grams":80}},'
        f'{{"food":"low-fat milk","grams":250}}]}},{{"name":"Mid-Morning Snack","items":[]}},'
        f'{{"name":"Lunch","items":[]}},{{"name":"Evening Snack","items":[]}},{{"name":"Dinner","items":[]}}]}}],'
        f'"daily_routine":"Wake 7AM, breakfast 8AM, lunch 1PM, workout 6PM, dinner 8PM, sleep 10:30PM"}}'
        f"{_correction_block(guardrail_feedback)}"
    )


def _build_prose_prompt(
    context: GenerationContext,
    intent: str,
    plan_markdown: str,
    report: PlanBuildReport,
    guardrail_feedback: str | None = None,
) -> str:
    """Call 2: the message around a plan that is already final."""
    adjustment_note = ""
    if report.rebalanced_days:
        adjustment_note = (
            "\n(Portion sizes were fine-tuned by the system so every day lands on the target — "
            "the amounts shown are final.)"
        )
    routine_rule = (
        "5. This is a routine request: spell out the full daily routine in your message — wake time, "
        "meal timings, exercise, hydration, and sleep schedule.\n"
        if intent == "ROUTINE_REQUEST"
        else "5. Briefly mention the daily routine (meal timing, hydration, activity) where it helps.\n"
    )
    return (
        f"{_persona_block(context)}"
        f"{_shared_context(context, include_food_list=False)}\n"
        f"FINAL MEAL PLAN (computed and verified by the system from the nutrition database — every "
        f"food, amount, and number below is final):\n{plan_markdown}{adjustment_note}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. Empathise first — acknowledge how {context.user_name} feels about their goal before anything else.\n"
        f"2. Then write a warm, personal message introducing the week: in a short paragraph or a few "
        f"bullets, explain how the plan is built for their profile, goal, and any medical context, "
        f"naming a few of the actual foods from the plan.\n"
        f"3. Do NOT reproduce the day-by-day plan — it is appended below your message automatically. "
        f"Do not invent any food, amount, calorie, or macro figure; any number you mention must appear "
        f"in the FINAL MEAL PLAN or the targets above.\n"
        f"4. Give 2-4 practical tips (meal prep, hydration, timing, swaps within the plan).\n"
        f"{routine_rule}"
        f"6. If the user has a medical condition, include this sentence verbatim: '{DOCTOR_NOTE}'\n"
        f"7. Do NOT end with a question and do not ask whether to accept — that prompt is appended "
        f"automatically after the plan.\n"
        f"8. Tone: warm, motivating, personal. Use the user's name naturally. Cite the clinical "
        f"guidelines naturally where relevant.\n"
        f"9. Never diagnose a condition or advise on medication."
        f"{_correction_block(guardrail_feedback)}"
    )


def _build_answer_prompt(context: GenerationContext, guardrail_feedback: str | None = None) -> str:
    """Single-call prompt for non-plan intents (questions, calorie results, chat)."""
    return (
        f"{_persona_block(context)}"
        f"{_shared_context(context, include_food_list=False)}\n"
        f"CORE INSTRUCTIONS:\n"
        f"1. Empathise first — acknowledge how the user feels before giving advice.\n"
        f"2. Every response must reflect the user's profile, goals, and medical context.\n"
        f"3. Answer the user's question clearly and thoroughly using the clinical guidelines provided "
        f"above. Cite relevant guidelines naturally in your response.\n"
        f"4. Do not generate a meal plan unless explicitly asked.\n"
        f"5. For users with serious medical conditions, always add: '{DOCTOR_NOTE}'\n"
        f"6. Never diagnose a condition or advise on medication dosage.\n"
        f"7. Tone: warm, motivating, personal. Use the user's name naturally."
        f"{_correction_block(guardrail_feedback)}"
    )


# ── JSON extraction ─────────────────────────────────────────────────────────

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
    """Extract an embedded meal_plan_json block, returning
    (parsed_plan_or_None, response_text_with_the_json_block_stripped).

    Tries the fenced ```meal_plan_json ... ``` format first, falls back to
    balanced-brace scanning for models that include the JSON without the
    fence, then json_repair for syntactically-invalid-but-intact JSON.
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


def _parse_selection(text: str) -> dict[str, Any] | None:
    """Parse the selection call's output: a dict with either "days" or a
    "clarifying_question". Tolerates a stray fence or preamble and minor
    syntax errors the same way _extract_plan_json_and_clean does."""
    span = _find_balanced_json(text, start_marker="{")
    if not span:
        return None
    candidate = text[span[0]:span[1]]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        logger.warning("Selection JSON strict parse failed (%s), attempting repair", exc)
        try:
            parsed = json_repair.loads(candidate)
        except Exception:
            logger.exception("Selection JSON repair failed")
            return None
    if not isinstance(parsed, dict):
        return None
    question = parsed.get("clarifying_question")
    if isinstance(question, str) and question.strip():
        return {"clarifying_question": question.strip()}
    if isinstance(parsed.get("days"), list) and parsed["days"]:
        return parsed
    return None


# ── Node ────────────────────────────────────────────────────────────────────

async def _generate_text(messages: list[Message], config: GenerationConfig) -> str:
    result = await get_provider().generate(messages=messages, config=config)
    return result.text


async def _plan_turn(state: NutriBotState, context: GenerationContext, intent: str) -> NutriBotState:
    food_context = state.get("food_context") or []
    calorie_result = state.get("calorie_result") or {}
    feedback = state.get("guardrail_feedback")
    user_turn = Message(role="user", content=state.get("user_message", ""))

    # Call 1: selection (JSON only), with one retry on unusable output.
    selection: dict[str, Any] | None = None
    selection_prompt = _build_selection_prompt(context, intent, feedback)
    for attempt in range(1, SELECTION_MAX_ATTEMPTS + 1):
        prompt = selection_prompt
        if attempt > 1:
            prompt += "\n\nYour previous output was not a valid JSON object of the required shape. Output ONLY the JSON."
        try:
            text = await _generate_text(
                [Message(role="system", content=prompt)] + context.chat_history + [user_turn],
                SELECTION_CONFIG,
            )
        except Exception as exc:
            logger.exception("Meal plan selection call failed: %s", exc)
            return {**state, "response": _technical_issue(context.user_name), "plan_proposed": False, "proposed_plan": None}
        selection = _parse_selection(text)
        if selection is not None:
            break
        logger.warning("Selection output unparseable on attempt %d/%d", attempt, SELECTION_MAX_ATTEMPTS)

    if selection is None:
        return {
            **state,
            "response": (
                f"I'm sorry, {context.user_name} — I couldn't put a complete plan together just now. "
                f"Please ask again in a moment and I'll build it for you."
            ),
            "plan_proposed": False,
            "proposed_plan": None,
        }

    if "clarifying_question" in selection:
        return {**state, "response": selection["clarifying_question"], "plan_proposed": False, "proposed_plan": None}

    # Deterministic: nutrients, totals, rebalance, render.
    plan, report = build_plan(selection, food_context, calorie_result)
    if plan is None:
        logger.warning("Selection produced no usable plan items (dropped=%s)", report.dropped_items)
        return {
            **state,
            "response": (
                f"I'm sorry, {context.user_name} — I couldn't put a complete plan together just now. "
                f"Please ask again in a moment and I'll build it for you."
            ),
            "plan_proposed": False,
            "proposed_plan": None,
            "plan_build_report": report.model_dump(),
        }
    plan_markdown = render_plan_markdown(plan)

    # Call 2: prose around the finished plan.
    try:
        prose = await _generate_text(
            [Message(role="system", content=_build_prose_prompt(context, intent, plan_markdown, report, feedback))]
            + context.chat_history
            + [user_turn],
            PROSE_CONFIG,
        )
    except Exception as exc:
        logger.exception("Meal plan prose call failed: %s", exc)
        prose = f"{context.user_name}, here is your plan for the week."

    prose = prose.strip()
    response = f"{prose}\n\n{plan_markdown}\n\n{ACCEPT_PROMPT}"
    return {
        **state,
        "response": response,
        "plan_proposed": True,
        "proposed_plan": plan,
        "plan_build_report": report.model_dump(),
        # Recorded separately so the multilingual layer can translate the
        # prose and the accept prompt while leaving the table untouched.
        "response_parts": {"prose": prose, "plan_markdown": plan_markdown, "accept_prompt": ACCEPT_PROMPT},
    }


async def meal_plan_agent_node(state: NutriBotState) -> NutriBotState:
    intent = state.get("intent", "GENERAL_CONVERSATION")
    context = build_context(state)

    if intent in MEAL_PLAN_INTENTS:
        if state.get("food_context"):
            return await _plan_turn(state, context, intent)
        # Food DB unavailable (see food_agent_node's fallback): nothing to
        # compute nutrients from, so answer in prose without a plan rather
        # than trusting model arithmetic on invented foods.
        logger.warning("Meal plan intent %s with no food_context -- answering without a plan", intent)

    messages = (
        [Message(role="system", content=_build_answer_prompt(context, state.get("guardrail_feedback")))]
        + context.chat_history
        + [Message(role="user", content=state.get("user_message", ""))]
    )
    try:
        response = (await _generate_text(messages, ANSWER_CONFIG)).strip()
    except Exception as exc:
        logger.exception("Response generation failed: %s", exc)
        response = _technical_issue(context.user_name)

    return {**state, "response": response, "plan_proposed": False, "proposed_plan": None}
