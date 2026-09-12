"""Routing predicates in backend/agents/graph.py (pure functions)."""
from backend.agents.graph import _route_after_calorie, _route_after_intent, _route_after_rag


def test_routine_request_runs_calorie_then_rag_then_food():
    """A routine turn builds a full plan; without goal_calories the plan
    builder can't balance the days (caught live: 2,374-3,128 kcal spread)."""
    state = {"intent": "ROUTINE_REQUEST"}
    assert _route_after_intent(state) == "calorie"
    assert _route_after_calorie(state) == "rag"
    assert _route_after_rag(state) == "food"


def test_other_intents_unchanged():
    assert _route_after_intent({"intent": "MEAL_PLAN_REQUEST"}) == "calorie"
    assert _route_after_intent({"intent": "PLAN_MODIFICATION"}) == "calorie"
    assert _route_after_intent({"intent": "CALORIE_CALCULATION"}) == "calorie"
    assert _route_after_calorie({"intent": "CALORIE_CALCULATION"}) == "meal_plan"
    assert _route_after_intent({"intent": "NUTRITION_QUESTION"}) == "rag"
    assert _route_after_rag({"intent": "NUTRITION_QUESTION"}) == "meal_plan"
    assert _route_after_intent({"intent": "GENERAL_CONVERSATION"}) == "meal_plan"
