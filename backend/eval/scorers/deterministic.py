"""Deterministic (objective, code-checkable) scoring for eval cases.

Scope per the v2 roadmap: allergen/diet violations, forbidden foods (i.e. foods
outside the food-filter allow-list), macro consistency, calorie-target adherence.
Intent-classification correctness and subjective quality are NOT scored here —
see scorers/judge.py.
"""
import re
from typing import Any

from backend.agents.plan_builder import parse_grams
from backend.agents.state import NutriBotState
from backend.eval.models import DeterministicResult, GoldenCase
from backend.utils.food_filter import find_food

CALORIE_TOLERANCE = 0.15  # ±15%
# Per-item calories must equal food_db calories x grams / serving, to within
# rounding. This is the eval-side proof of invariants 1 and 2: if a plan item
# ever carries a figure the builder didn't compute, this catches it.
ITEM_CALORIE_SLACK_KCAL = 1.0


def _normalize(s: str) -> str:
    return s.strip().lower()


def _matched_food(food_name: str, food_context: list[dict[str, Any]]) -> dict[str, Any] | None:
    return find_food(food_name, food_context)


def score_deterministic(case: GoldenCase, state: NutriBotState) -> DeterministicResult:
    failures: list[str] = []

    response = state.get("response", "")
    if not response.strip():
        failures.append("response is empty")

    plan_proposed = state.get("plan_proposed", False)
    if case.expect_plan is not None and plan_proposed != case.expect_plan:
        # A plan withheld because the output guardrail caught a real issue
        # (e.g. an allergen mentioned in prose) and safely fell back after
        # exhausting its regeneration budget is the guardrail working as
        # designed -- not a generation failure to penalize the same as an
        # ordinary "the model forgot to produce a plan" bug.
        if not (case.expect_plan and state.get("guardrail_blocked")):
            failures.append(f"expected plan_proposed={case.expect_plan}, got {plan_proposed}")

    if case.expect_input_blocked and not state.get("guardrail_blocked"):
        failures.append("expected the input guardrail to block this message, but it did not")

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
                grams = parse_grams(item.get("quantity"))
                base = float(matched.get("quantity_grams") or 0)
                if grams is not None and base > 0:
                    expected = float(matched.get("calories", 0)) * grams / base
                    actual = float(item.get("calories", 0) or 0)
                    if abs(actual - expected) > ITEM_CALORIE_SLACK_KCAL:
                        failures.append(
                            f"'{item.get('food')}' {item.get('quantity')} lists {actual} kcal but food_db "
                            f"gives {expected:.1f} -- item nutrients were not computed from the database"
                        )
            else:
                # No structured match to check against -- fall back to a
                # name-based heuristic so an invented/off-list food doesn't
                # silently skip allergen checking entirely. Word-boundary,
                # not a bare substring -- "nut" as a substring false-
                # positives on "coconut" (common in Indian/vegan cooking).
                for allergy in allergies:
                    if re.search(r"\b" + re.escape(allergy) + r"\b", food_name):
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
