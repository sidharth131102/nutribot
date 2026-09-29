"""Node-level tests for the two-call meal plan agent (fake provider, no
network). Proves: selection -> deterministic build -> prose, the clarifying-
question path, the retry-then-graceful-failure path, and that non-plan
intents are still a single call."""
import json

import pytest

from backend.agents import meal_plan_agent as agent
from backend.agents.meal_plan_agent import ACCEPT_PROMPT, meal_plan_agent_node
from backend.llm.base import GenerationResult

OATS = {"id": "FOOD_001", "food": "oats", "quantity_grams": 60, "calories": 228, "protein": 8, "carbs": 40, "fat": 4, "meal_types": ["breakfast"]}
MILK = {"id": "FOOD_002", "food": "low-fat milk", "quantity_grams": 250, "calories": 105, "protein": 8.5, "carbs": 12, "fat": 2.5, "meal_types": ["breakfast", "snack"]}
PANEER = {"id": "FOOD_006", "food": "paneer", "quantity_grams": 100, "calories": 265, "protein": 18, "carbs": 3, "fat": 20, "meal_types": ["lunch", "dinner"]}
ROTI = {"id": "FOOD_050", "food": "whole wheat roti", "quantity_grams": 80, "calories": 200, "protein": 6, "carbs": 40, "fat": 2, "meal_types": ["lunch", "dinner"]}
PIZZA = {"id": "FOOD_124", "food": "cheese pizza slice", "quantity_grams": 120, "calories": 300, "protein": 12, "carbs": 34, "fat": 12, "meal_types": ["lunch", "dinner"], "tags": ["treat", "indulgent"]}
FOODS = [OATS, MILK, PANEER, ROTI]
FOODS_WITH_TREAT = FOODS + [PIZZA]

SELECTION = {
    "days": [
        {
            "day": f"Day {d}",
            "meals": [
                {"name": "Breakfast", "items": [{"food": "oats", "grams": 80}, {"food": "low-fat milk", "grams": 250}]},
                {"name": "Mid-Morning Snack", "items": [{"food": "low-fat milk", "grams": 250}]},
                {"name": "Lunch", "items": [{"food": "paneer", "grams": 150}, {"food": "whole wheat roti", "grams": 160}]},
                {"name": "Evening Snack", "items": []},
                {"name": "Dinner", "items": [{"food": "paneer", "grams": 100}, {"food": "whole wheat roti", "grams": 160}, {"food": "dragon fruit", "grams": 100}]},
            ],
        }
        for d in range(1, 8)
    ],
    "daily_routine": "Wake 7AM, breakfast 8AM, lunch 1PM, dinner 8PM, sleep 11PM",
}


class FakeProvider:
    """Returns scripted outputs in order and records every call's prompt."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    async def generate(self, messages, config):
        self.calls.append({"messages": messages, "config": config})
        text = self.outputs.pop(0)
        if isinstance(text, Exception):
            raise text
        return GenerationResult(text=text, model="fake", provider="fake")


def _state(intent="MEAL_PLAN_REQUEST", **overrides):
    base = {
        "user_message": "Give me a 7 day plan",
        "intent": intent,
        "user_name": "Asha",
        "bot_name": "Nova",
        "profile_context": "USER PROFILE: Asha, vegetarian",
        "calorie_result": {"goal_calories": 2000.0, "protein_g": 150.0, "carbs_g": 200.0, "fat_g": 66.7},
        "food_context": FOODS,
        "food_context_str": "APPROVED FOOD OPTIONS: oats, low-fat milk, paneer, whole wheat roti",
        "chat_history": [],
        "previous_plans": [],
    }
    base.update(overrides)
    return base


@pytest.fixture
def use_fake(monkeypatch):
    def _install(outputs):
        fake = FakeProvider(outputs)
        monkeypatch.setattr(agent, "get_provider", lambda name=None: fake)
        return fake
    return _install


@pytest.mark.asyncio
async def test_plan_request_makes_two_calls_and_computes_every_number(use_fake):
    fake = use_fake([json.dumps(SELECTION), "Asha, here is a week built around paneer and roti."])

    result = await meal_plan_agent_node(_state())

    assert len(fake.calls) == 2
    # Call 1 is the selection prompt: it carries the food list and asks for JSON only.
    sel_prompt = fake.calls[0]["messages"][0].content
    assert "APPROVED FOOD OPTIONS" in sel_prompt
    assert "Output ONLY a JSON object" in sel_prompt
    assert fake.calls[0]["config"].temperature == pytest.approx(0.2)
    # Call 2 is the prose prompt: it carries the rendered, final plan and NOT the food list.
    prose_prompt = fake.calls[1]["messages"][0].content
    assert "FINAL MEAL PLAN" in prose_prompt
    assert "**Day 1**" in prose_prompt
    assert "APPROVED FOOD OPTIONS" not in prose_prompt

    assert result["plan_proposed"] is True
    plan = result["proposed_plan"]
    assert len(plan["days"]) == 7
    # The off-list item was dropped, everything else re-derived from the DB.
    day1_dinner = plan["days"][0]["meals"][4]
    assert [i["food"] for i in day1_dinner["items"]] == ["paneer", "whole wheat roti"]
    report = result["plan_build_report"]
    assert report["dropped_items"] == ["dragon fruit"] * 7
    for day in plan["days"]:
        assert abs(day["daily_totals"]["calories"] - 2000) / 2000 <= 0.10
    # Response = prose + rendered plan + accept prompt, in that order.
    assert result["response"].startswith("Asha, here is a week")
    assert "**Day 7**" in result["response"]
    assert result["response"].rstrip().endswith(ACCEPT_PROMPT)


@pytest.mark.asyncio
async def test_clarifying_question_short_circuits_before_the_prose_call(use_fake):
    fake = use_fake([json.dumps({"clarifying_question": "Asha, do you mean smaller portions or fewer calories overall?"})])

    result = await meal_plan_agent_node(_state(intent="PLAN_MODIFICATION", user_message="reduce my portions"))

    assert len(fake.calls) == 1
    assert result["plan_proposed"] is False
    assert result["proposed_plan"] is None
    assert result["response"] == "Asha, do you mean smaller portions or fewer calories overall?"


@pytest.mark.asyncio
async def test_unparseable_selection_is_retried_once_then_fails_gracefully(use_fake):
    fake = use_fake(["I would love to help but here is prose", "still not json"])

    result = await meal_plan_agent_node(_state())

    assert len(fake.calls) == 2
    assert "not a valid JSON object" in fake.calls[1]["messages"][0].content
    assert result["plan_proposed"] is False
    assert result["proposed_plan"] is None
    assert "couldn't put a complete plan together" in result["response"]


@pytest.mark.asyncio
async def test_selection_with_a_stray_fence_and_trailing_comma_still_parses(use_fake):
    messy = "```json\n" + json.dumps(SELECTION)[:-1] + ",}\n```"
    fake = use_fake([messy, "prose"])

    result = await meal_plan_agent_node(_state())

    assert len(fake.calls) == 2
    assert result["plan_proposed"] is True


@pytest.mark.asyncio
async def test_prose_failure_still_delivers_the_computed_plan(use_fake):
    fake = use_fake([json.dumps(SELECTION), RuntimeError("provider down")])

    result = await meal_plan_agent_node(_state())

    assert result["plan_proposed"] is True
    assert "**Day 1**" in result["response"]
    assert result["response"].rstrip().endswith(ACCEPT_PROMPT)


@pytest.mark.asyncio
async def test_guardrail_feedback_reaches_both_calls(use_fake):
    fake = use_fake([json.dumps(SELECTION), "prose"])

    await meal_plan_agent_node(_state(guardrail_feedback="Remove any mention of peanuts."))

    for call in fake.calls:
        assert "CORRECTION REQUIRED" in call["messages"][0].content
        assert "Remove any mention of peanuts." in call["messages"][0].content


@pytest.mark.asyncio
async def test_non_plan_intent_is_a_single_answer_call(use_fake):
    fake = use_fake(["Protein needs depend on your weight, Asha."])

    result = await meal_plan_agent_node(_state(intent="NUTRITION_QUESTION", user_message="How much protein?"))

    assert len(fake.calls) == 1
    assert "CORE INSTRUCTIONS" in fake.calls[0]["messages"][0].content
    assert result["plan_proposed"] is False
    assert result["response"] == "Protein needs depend on your weight, Asha."


@pytest.mark.asyncio
async def test_plan_intent_without_food_context_answers_without_a_plan(use_fake):
    fake = use_fake(["I can't build a full plan right now, but here's guidance."])

    result = await meal_plan_agent_node(_state(food_context=[]))

    assert len(fake.calls) == 1
    assert result["plan_proposed"] is False
    assert result["proposed_plan"] is None


@pytest.mark.asyncio
async def test_prose_prompt_carries_the_true_macro_summary_and_honesty_rule(use_fake):
    fake = use_fake([json.dumps(SELECTION), "prose"])
    await meal_plan_agent_node(_state())
    prose_prompt = fake.calls[1]["messages"][0].content
    assert "Weekly average per day:" in prose_prompt
    assert "NEVER state or imply that a target is met" in prose_prompt


@pytest.mark.asyncio
async def test_portion_nudge_only_for_high_targets(use_fake):
    fake = use_fake([json.dumps(SELECTION), "prose", json.dumps(SELECTION), "prose"])
    await meal_plan_agent_node(_state(calorie_result={"goal_calories": 1400.0}))
    await meal_plan_agent_node(_state(calorie_result={"goal_calories": 3400.0}))
    low, high = fake.calls[0]["messages"][0].content, fake.calls[2]["messages"][0].content
    assert "be generous" not in low and "listed serving sizes" in low
    assert "be generous" in high


@pytest.mark.asyncio
async def test_chat_history_reaches_prose_but_not_selection(use_fake):
    """Regression for the latency fix: chat_history used to be replayed into
    BOTH calls; the selection call (picking foods/grams for a new plan)
    doesn't need the conversational back-and-forth, so it's dropped there
    -- the prose call still gets it for continuity."""
    # Raw stored-message shape (as read from Mongo), matching what
    # build_context()/format_history() actually expects in state -- not
    # Message objects, which is what context.chat_history becomes *after*
    # that conversion.
    history = [
        {"role": "user", "content": "I don't like broccoli"},
        {"role": "assistant", "content": "Noted!"},
    ]
    fake = use_fake([json.dumps(SELECTION), "prose"])

    await meal_plan_agent_node(_state(chat_history=history))

    selection_messages = fake.calls[0]["messages"]
    prose_messages = fake.calls[1]["messages"]
    assert selection_messages == [selection_messages[0], selection_messages[-1]]  # system + user turn only
    assert not any(m.content == "I don't like broccoli" for m in selection_messages)
    assert any(m.content == "I don't like broccoli" for m in prose_messages)


# ── Requested day count ──────────────────────────────────────────────────────

@pytest.mark.parametrize("message,expected", [
    ("Give me a 5 day meal plan", 5),
    ("Generate a 5-day plan please", 5),
    ("I want a 1 day plan", 1),
    ("Can I get a 14 day plan", 7),         # clamped to MAX_DAYS (7)
    ("Generate a 20 day plan", 7),          # clamped to MAX_DAYS (7)
    ("Give me a meal plan", 7),             # no count mentioned -- default
    ("Calculate my calories for 2000 kcal", 7),  # bare number, not "N day(s)"
])
def test_requested_day_count_parses_and_clamps(message, expected):
    assert agent._requested_day_count(message) == expected


@pytest.mark.asyncio
async def test_five_day_request_produces_a_five_day_plan(use_fake):
    """The reported bug: asking for 5 days silently produced 7. The selection
    prompt must say 5, and the builder must not keep more than 5 even if the
    model ignores the instruction and returns all 7 anyway."""
    fake = use_fake([json.dumps(SELECTION), "Asha, here is your 5-day plan."])

    result = await meal_plan_agent_node(_state(user_message="Generate a meal plan for 5 days"))

    sel_prompt = fake.calls[0]["messages"][0].content
    assert "5-day meal plan" in sel_prompt
    assert "Exactly 5 days" in sel_prompt
    assert "fill all 5 days" in sel_prompt

    plan = result["proposed_plan"]
    assert len(plan["days"]) == 5


@pytest.mark.asyncio
async def test_one_day_request_uses_singular_wording(use_fake):
    fake = use_fake([json.dumps(SELECTION), "prose"])

    await meal_plan_agent_node(_state(user_message="Give me a 1 day meal plan"))

    sel_prompt = fake.calls[0]["messages"][0].content
    assert "1-day meal plan" in sel_prompt
    assert "Exactly 1 day." in sel_prompt
    assert "fill all 1 day)" in sel_prompt


# ── Cheat day ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cheat_day_requested_with_treats_available_adds_selection_rule(use_fake):
    fake = use_fake([json.dumps(SELECTION), "prose"])

    await meal_plan_agent_node(_state(
        user_message="Generate a 7 day meal plan with one cheat day",
        food_context=FOODS_WITH_TREAT,
    ))

    sel_prompt = fake.calls[0]["messages"][0].content
    assert "CHEAT DAY: Day 7 is a cheat day" in sel_prompt
    assert "cheese pizza slice" in sel_prompt


@pytest.mark.asyncio
async def test_cheat_day_requested_with_treats_tells_prose_to_call_it_out(use_fake):
    fake = use_fake([json.dumps(SELECTION), "prose"])

    await meal_plan_agent_node(_state(
        user_message="Generate a 7 day meal plan with one cheat day",
        food_context=FOODS_WITH_TREAT,
    ))

    prose_prompt = fake.calls[1]["messages"][0].content
    assert "Day 7 is it" in prose_prompt
    assert "call this out explicitly" in prose_prompt


@pytest.mark.asyncio
async def test_cheat_day_requested_without_treats_available_has_no_selection_rule(use_fake):
    """A diabetic/PCOS profile filters every treat item out at the food_agent
    stage (see test_food_filter.py) -- food_context then carries no treat
    items even though a cheat day was asked for. The selection prompt must
    not tell the model to build a cheat day with nothing to build it from."""
    fake = use_fake([json.dumps(SELECTION), "prose"])

    await meal_plan_agent_node(_state(
        user_message="Generate a 7 day meal plan with one cheat day",
        food_context=FOODS,  # no treat items
    ))

    sel_prompt = fake.calls[0]["messages"][0].content
    assert "CHEAT DAY" not in sel_prompt


@pytest.mark.asyncio
async def test_cheat_day_requested_without_treats_tells_prose_to_explain_why(use_fake):
    fake = use_fake([json.dumps(SELECTION), "prose"])

    await meal_plan_agent_node(_state(
        user_message="Generate a 7 day meal plan with one cheat day",
        food_context=FOODS,  # no treat items
    ))

    prose_prompt = fake.calls[1]["messages"][0].content
    assert "none of the approved treat-style foods were safe" in prose_prompt


@pytest.mark.asyncio
async def test_no_cheat_day_requested_adds_no_cheat_day_language(use_fake):
    fake = use_fake([json.dumps(SELECTION), "prose"])

    await meal_plan_agent_node(_state(
        user_message="Generate a 7 day meal plan",
        food_context=FOODS_WITH_TREAT,  # treats available but not asked for
    ))

    sel_prompt = fake.calls[0]["messages"][0].content
    prose_prompt = fake.calls[1]["messages"][0].content
    assert "CHEAT DAY" not in sel_prompt
    assert "cheat day" not in prose_prompt.lower()


@pytest.mark.asyncio
async def test_cheat_day_lands_on_the_last_requested_day(use_fake):
    fake = use_fake([json.dumps(SELECTION), "prose"])

    await meal_plan_agent_node(_state(
        user_message="Generate a 3 day meal plan with a cheat day",
        food_context=FOODS_WITH_TREAT,
    ))

    sel_prompt = fake.calls[0]["messages"][0].content
    assert "CHEAT DAY: Day 3 is a cheat day" in sel_prompt


@pytest.mark.asyncio
async def test_plan_modification_prose_is_told_to_explain_allergy_refusals(use_fake):
    """Regression: a modification request for an off-list food (e.g. 'add a
    burger' for a milk-allergic user) got a technically-true but unhelpful
    'wasn't in your approved foods list' refusal with no reason given."""
    fake = use_fake([json.dumps(SELECTION), "prose"])

    await meal_plan_agent_node(_state(
        intent="PLAN_MODIFICATION",
        user_message="Add a burger or pizza for the cheat day",
        food_context=FOODS_WITH_TREAT,
    ))

    prose_prompt = fake.calls[1]["messages"][0].content
    assert "say that plainly" in prose_prompt
    assert "milk allergy" in prose_prompt


@pytest.mark.asyncio
async def test_cheat_day_stays_active_on_a_later_turn_that_does_not_repeat_the_words(use_fake):
    """Regression: a follow-up modification turn ('use fries instead') that
    never repeats "cheat day" used to silently drop the cheat day from the
    plan entirely -- food_context still carries the treat items from
    food_agent_node (which is also now conversation-sticky), but
    meal_plan_agent's own cheat_day_requested flag must independently agree,
    or the CHEAT DAY rule never gets added to the selection prompt."""
    fake = use_fake([json.dumps(SELECTION), "prose"])
    history = [
        {"role": "user", "content": "Generate a 7 day plan with one cheat day"},
        {"role": "assistant", "content": "Here is your plan with Day 7 as a cheat day."},
    ]

    await meal_plan_agent_node(_state(
        intent="PLAN_MODIFICATION",
        user_message="just use fries instead please",
        food_context=FOODS_WITH_TREAT,
        chat_history=history,
    ))

    sel_prompt = fake.calls[0]["messages"][0].content
    assert "CHEAT DAY: Day 7 is a cheat day" in sel_prompt


@pytest.mark.asyncio
async def test_non_modification_prose_has_no_allergy_refusal_instruction(use_fake):
    fake = use_fake([json.dumps(SELECTION), "prose"])

    await meal_plan_agent_node(_state(
        intent="MEAL_PLAN_REQUEST",
        user_message="Generate a 7 day meal plan with one cheat day",
        food_context=FOODS_WITH_TREAT,
    ))

    prose_prompt = fake.calls[1]["messages"][0].content
    assert "wasn't on the approved list" not in prose_prompt
