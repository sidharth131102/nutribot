"""Deterministic (objective, code-checkable) scoring for eval cases.

Scope per the v2 roadmap: allergen/diet violations, forbidden foods (i.e. foods
outside the food-filter allow-list), macro consistency, calorie-target adherence.
Intent-classification correctness and subjective quality are NOT scored here —
see scorers/judge.py.
"""
from typing import Any

from backend.agents.state import NutriBotState
from backend.eval.models import DeterministicResult, GoldenCase
from backend.utils.food_filter import food_name_matches

CALORIE_TOLERANCE = 0.15  # ±15%


def _normalize(s: str) -> str:
    return s.strip().lower()


def _matched_food(food_name: str, food_context: list[dict[str, Any]]) -> dict[str, Any] | None:
    for food in food_context:
        if food_name_matches(food_name, [food]):
            return food
    return None


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

    if case.expected_rag_condition:
        conditions_returned = {s.get("condition") for s in state.get("rag_sources", [])}
        if case.expected_rag_condition not in conditions_returned:
            failures.append(
                f"expected a '{case.expected_rag_condition}' source, got conditions={conditions_returned}"
            )

    proposed_plan = state.get("proposed_plan")
    if plan_proposed and proposed_plan:
        allergies = {_normalize(a) for a in case.profile.get("allergies", []) if a}
        food_context = state.get("food_context") or []

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

            matched = _matched_food(item.get("food", ""), food_context) if food_context else None
            if matched is not None:
                # Check the food's own declared allergens, not a substring match
                # on its display name -- "soy milk" contains the substring
                # "milk" but is dairy-free (allergens: ["soy"]), so name-based
                # matching false-positives against a milk allergy.
                declared = {_normalize(a) for a in matched.get("allergens", [])}
                for allergy in allergies:
                    if allergy in declared:
                        failures.append(
                            f"plan includes '{item.get('food')}' which contains allergen '{allergy}'"
                        )
            else:
                # No structured match to check against -- fall back to a
                # name-based heuristic so an invented/off-list food doesn't
                # silently skip allergen checking entirely.
                for allergy in allergies:
                    if allergy in food_name:
                        failures.append(
                            f"plan includes '{item.get('food')}' which may contain allergen '{allergy}'"
                        )
                if food_context:
                    failures.append(
                        f"plan includes '{item.get('food')}' not in the approved food_context allow-list"
                    )

        calorie_result = state.get("calorie_result") or {}
        goal_calories = calorie_result.get("goal_calories")
        if goal_calories and case.check_calorie_tolerance:
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
