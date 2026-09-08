"""Tests for backend/agents/meal_plan_agent.py's JSON extraction pipeline.

Covers the three-tier fallback: fenced regex -> balanced-brace scan (for
models that omit the ```meal_plan_json fence) -> json_repair (for models
that emit syntactically-invalid JSON, e.g. a trailing comma) -- all pure,
no LLM calls needed.
"""
from backend.agents.meal_plan_agent import _extract_plan_json_and_clean

VALID_PLAN = '{"days":[{"day":"Day 1","meals":[],"daily_totals":{"calories":2000}}],"calorie_target":2000}'


def test_extracts_fenced_json():
    text = f"Here's your plan.\n\n```meal_plan_json\n{VALID_PLAN}\n```\n\nEnjoy!"
    plan, cleaned = _extract_plan_json_and_clean(text)
    assert plan is not None
    assert plan["calorie_target"] == 2000
    assert "meal_plan_json" not in cleaned
    assert "Enjoy!" in cleaned


def test_extracts_unfenced_json_via_balanced_brace_scan():
    """GPT-5-mini doesn't reliably emit the fence even when instructed to."""
    text = f"Here's your plan.\n\nmeal_plan_json\n{VALID_PLAN}"
    plan, cleaned = _extract_plan_json_and_clean(text)
    assert plan is not None
    assert plan["calorie_target"] == 2000
    assert "meal_plan_json" not in cleaned
    assert "{" not in cleaned


def test_repairs_json_with_trailing_comma():
    """A real malformation seen from GPT-5-mini: syntactically invalid JSON
    despite being structurally complete."""
    malformed = '{"days":[{"day":"Day 1","meals":[],"daily_totals":{"calories":2000,}}],"calorie_target":2000,}'
    text = f"```meal_plan_json\n{malformed}\n```"
    plan, cleaned = _extract_plan_json_and_clean(text)
    assert plan is not None
    assert plan["calorie_target"] == 2000


def test_discards_repaired_json_that_is_not_a_meal_plan():
    """If repair 'succeeds' but produces something that clearly isn't a meal
    plan (no 'days' key), don't hand back garbage as if it were valid."""
    not_a_plan = '{"foo": "bar",}'
    text = f"```meal_plan_json\n{not_a_plan}\n```"
    plan, cleaned = _extract_plan_json_and_clean(text)
    assert plan is None


def test_returns_none_for_no_json_at_all():
    text = "I have a question for you, but no plan today."
    plan, cleaned = _extract_plan_json_and_clean(text)
    assert plan is None
    assert cleaned == text
