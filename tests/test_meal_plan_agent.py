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
FOODS = [OATS, MILK, PANEER, ROTI]

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
