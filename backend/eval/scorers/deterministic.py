"""Deterministic (objective, code-checkable) scoring for eval cases.

Scope per the v2 roadmap: allergen/diet violations, forbidden foods (i.e. foods
outside the food-filter allow-list), macro consistency, calorie-target adherence.
Intent-classification correctness and subjective quality are NOT scored here —
see scorers/judge.py.
"""
from backend.agents.state import NutriBotState
from backend.eval.models import DeterministicResult, GoldenCase

CALORIE_TOLERANCE = 0.15  # ±15%


def _normalize(s: str) -> str:
    return s.strip().lower()


def score_deterministic(case: GoldenCase, state: NutriBotState) -> DeterministicResult:
    failures: list[str] = []

    response = state.get("response", "")
    if not response.strip():
        failures.append("response is empty")

    plan_proposed = state.get("plan_proposed", False)
    if case.expect_plan is not None and plan_proposed != case.expect_plan:
        failures.append(f"expected plan_proposed={case.expect_plan}, got {plan_proposed}")

    if case.category == "rag_dependent" and not state.get("rag_sources"):
        failures.append("rag_dependent case returned no rag_sources")

    proposed_plan = state.get("proposed_plan")
    if plan_proposed and proposed_plan:
        allergies = {_normalize(a) for a in case.profile.get("allergies", []) if a}
        food_context = state.get("food_context") or []
        allowed_food_names = {_normalize(f.get("food", "")) for f in food_context}
        allowed_food_ids = {_normalize(f.get("id", "")) for f in food_context}

        all_items = [
            item
            for day in proposed_plan.get("days", [])
            for meal in day.get("meals", [])
            for item in meal.get("items", [])
        ]

        for item in all_items:
            food_name = _normalize(item.get("food", ""))
            if not food_name:
                continue
            for allergy in allergies:
                if allergy in food_name:
                    failures.append(
                        f"plan includes '{item.get('food')}' which may contain allergen '{allergy}'"
                    )
            if allowed_food_names and food_name not in allowed_food_names and food_name not in allowed_food_ids:
                failures.append(
                    f"plan includes '{item.get('food')}' not in the approved food_context allow-list"
                )

        calorie_result = state.get("calorie_result") or {}
        goal_calories = calorie_result.get("goal_calories")
        if goal_calories:
            low, high = goal_calories * (1 - CALORIE_TOLERANCE), goal_calories * (1 + CALORIE_TOLERANCE)
            for day in proposed_plan.get("days", []):
                day_calories = day.get("daily_totals", {}).get("calories")
                if day_calories is None:
                    continue
                if not (low <= day_calories <= high):
                    failures.append(
                        f"{day.get('day', '?')} totals {day_calories} kcal, outside "
                        f"+/-{int(CALORIE_TOLERANCE * 100)}% of goal {goal_calories}"
                    )

    return DeterministicResult(passed=len(failures) == 0, failures=failures)
