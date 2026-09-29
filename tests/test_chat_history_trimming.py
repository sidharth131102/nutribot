"""Tests for backend/main.py::_content_for_history -- the text stored in
`content_en` (what gets replayed as pipeline context in later turns).

A plan turn's full response is prose + an entire day-by-day table, easily
1,500-3,000+ tokens; replaying that verbatim on every future turn (into two
separate generation calls, see meal_plan_agent.py) is how a session with a
few plans in it snowballs into tens of thousands of tokens per turn. Only
the table should be dropped from what's replayed -- `content` (the
user-facing field) always keeps the full text.
"""
from backend.main import _content_for_history

PLAN_MD = "**Day 1** — 2000 kcal\n- Breakfast (400 kcal): oats 80g, low-fat milk 250g"
PROSE = "Asha, here is your week."
ACCEPT = "Would you like to accept this plan?"
FULL_RESPONSE = f"{PROSE}\n\n{PLAN_MD}\n\n{ACCEPT}"


def _plan_result(**overrides):
    base = {
        "response": FULL_RESPONSE,
        "response_parts": {"prose": PROSE, "plan_markdown": PLAN_MD, "accept_prompt": ACCEPT},
        "proposed_plan": {"days": [{"day": "Day 1"}] * 7, "calorie_target": 1994.1},
    }
    base.update(overrides)
    return base


def test_plan_turn_keeps_prose_and_summarizes_the_table():
    text = _content_for_history(_plan_result())
    assert text.startswith(PROSE)
    assert PLAN_MD not in text
    assert "7-day meal plan" in text
    assert "1994" in text


def test_non_plan_turn_is_stored_in_full():
    result = {"response": "Protein needs depend on your weight.", "response_parts": None, "proposed_plan": None}
    assert _content_for_history(result) == "Protein needs depend on your weight."


def test_stale_response_parts_after_a_guardrail_fallback_are_ignored():
    """The output guardrail can replace `response` wholesale on failure; the
    parts recorded by meal_plan_agent no longer describe it and must not be
    trusted -- fall back to storing the actual response in full."""
    result = _plan_result(response="I wasn't able to put together a safe response.")
    assert _content_for_history(result) == "I wasn't able to put together a safe response."


def test_plan_without_calorie_target_still_gets_a_generic_marker():
    result = _plan_result(proposed_plan={"days": [], "calorie_target": None})
    text = _content_for_history(result)
    assert text.startswith(PROSE)
    assert "a meal plan was generated here" in text
    assert PLAN_MD not in text


def test_history_text_is_shorter_than_the_full_response():
    assert len(_content_for_history(_plan_result())) < len(FULL_RESPONSE)
