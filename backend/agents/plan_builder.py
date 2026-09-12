"""Deterministic meal-plan construction -- where invariants 1 and 2 are enforced.

The model chooses *which* approved foods go in each meal and roughly *how
much* (grams). Everything numeric -- per-item calories and macros, meal
totals, daily totals, and the final portion sizes -- is computed here from
data/food_db.json. The model's own arithmetic is never used.

Why: before this module, the model wrote every calorie figure itself and the
agent only summed them. Across two very different models (gpt-5-mini,
gpt-4.1) every generated plan undershot the calorie target by 16-34%, on
every day, while the prose claimed "within 10%". A 35-meal knapsack solved
with mental arithmetic in one generation is not something an LLM does
reliably; a multiply-and-sum in Python is.

Pure functions, no I/O, no LLM -- fully unit-testable.
"""
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from backend.utils.food_filter import find_food

logger = logging.getLogger("nutribot.agent.plan_builder")

# A day whose computed total is further than this from goal_calories gets
# its portions scaled. Tighter than the eval scorer's ±15% and the prose
# promise of ±10% on purpose: rounding grams to 5g after scaling can move a
# day by a percent or two, and this leaves room for that.
REBALANCE_TOLERANCE = 0.05
# Bounds on the uniform per-day scale factor. Beyond these the plan the
# model chose is simply wrong for the target (e.g. three salads for a
# 4,000 kcal athlete) and scaling further would produce absurd portions --
# better to leave the day off-target, report it, and let the scorer see it.
MIN_SCALE = 0.6
MAX_SCALE = 1.75
GRAMS_STEP = 5
MIN_GRAMS = 10
MAX_DAYS = 7
# Days still outside this after rebalancing are reported as off-target.
OFF_TARGET_TOLERANCE = 0.10

MEAL_ORDER = ["Breakfast", "Mid-Morning Snack", "Lunch", "Evening Snack", "Dinner"]

# A bare number or a number with a gram unit -- nothing else. "1 bowl" or
# "2 x 40g" must NOT parse as 1g/2g: the builder would then compute a
# nonsense nutrient line, and the scorer would compare against it.
_GRAMS_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:g|gm|gms|gram|grams)?\s*$", re.IGNORECASE)


class PlanBuildReport(BaseModel):
    """What the builder changed relative to the model's selection -- kept
    alongside the plan (state / eval results) so a run can show whether the
    model's picks were on target by themselves or needed correcting."""
    dropped_items: list[str] = Field(default_factory=list)      # not on the allow-list
    unparseable_items: list[str] = Field(default_factory=list)  # no usable grams
    rebalanced_days: dict[str, float] = Field(default_factory=dict)  # day -> scale factor
    off_target_days: list[str] = Field(default_factory=list)    # still outside tolerance
    day_calories: list[float] = Field(default_factory=list)     # final per-day totals


def parse_grams(value: Any) -> float | None:
    """80 -> 80.0; "80g" -> 80.0; "1 cup" / "2 x 40g" -> None. Zero/negative -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, str):
        match = _GRAMS_RE.match(value)
        if match:
            grams = float(match.group(1))
            return grams if grams > 0 else None
    return None


def _round_grams(grams: float) -> float:
    return float(max(MIN_GRAMS, GRAMS_STEP * round(grams / GRAMS_STEP)))


def _item_from_food(food: dict[str, Any], grams: float) -> dict[str, Any]:
    """A plan item with every nutrient computed from the DB entry x grams."""
    base_grams = float(food.get("quantity_grams") or 0)
    factor = grams / base_grams if base_grams > 0 else 0.0
    return {
        "food": food["food"],
        "quantity": f"{grams:g}g",
        "calories": round(float(food.get("calories", 0)) * factor, 1),
        "protein": round(float(food.get("protein", 0)) * factor, 1),
        "carbs": round(float(food.get("carbs", 0)) * factor, 1),
        "fat": round(float(food.get("fat", 0)) * factor, 1),
        # Kept so the day can be rescaled without re-matching names; stripped
        # before the plan leaves this module.
        "_food": food,
        "_grams": grams,
    }


def _recompute_totals(day: dict[str, Any]) -> None:
    for meal in day["meals"]:
        meal["total_calories"] = round(sum(i["calories"] for i in meal["items"]), 1)
    items = [i for m in day["meals"] for i in m["items"]]
    day["daily_totals"] = {
        "calories": round(sum(i["calories"] for i in items), 1),
        "protein": round(sum(i["protein"] for i in items), 1),
        "carbs": round(sum(i["carbs"] for i in items), 1),
        "fat": round(sum(i["fat"] for i in items), 1),
    }


def _scale_day(day: dict[str, Any], factor: float) -> None:
    for meal in day["meals"]:
        meal["items"] = [
            _item_from_food(i["_food"], _round_grams(i["_grams"] * factor)) for i in meal["items"]
        ]
    _recompute_totals(day)


def build_plan(
    selection: dict[str, Any],
    food_context: list[dict[str, Any]],
    calorie_result: dict[str, Any],
) -> tuple[dict[str, Any] | None, PlanBuildReport]:
    """Turn the model's {food, grams} selection into a fully computed plan.

    Returns (plan, report). plan is None when nothing usable survives (no
    days, or every item dropped) -- the caller treats that as "no plan this
    turn", never as a plan with empty days.
    """
    report = PlanBuildReport()
    goal = float(calorie_result.get("goal_calories") or 0)

    days_out: list[dict[str, Any]] = []
    for day_index, raw_day in enumerate((selection.get("days") or [])[:MAX_DAYS]):
        if not isinstance(raw_day, dict):
            continue
        day: dict[str, Any] = {"day": str(raw_day.get("day") or f"Day {day_index + 1}"), "meals": []}
        for raw_meal in raw_day.get("meals") or []:
            if not isinstance(raw_meal, dict):
                continue
            meal: dict[str, Any] = {"name": str(raw_meal.get("name") or "Meal"), "items": []}
            for raw_item in raw_meal.get("items") or []:
                if not isinstance(raw_item, dict):
                    continue
                name = str(raw_item.get("food") or "").strip()
                if not name:
                    continue
                food = find_food(name, food_context)
                if food is None:
                    report.dropped_items.append(name)
                    continue
                grams = parse_grams(raw_item.get("grams", raw_item.get("quantity")))
                if grams is None:
                    # No usable amount: fall back to the DB's default serving
                    # rather than losing the food the model deliberately chose.
                    report.unparseable_items.append(name)
                    grams = float(food.get("quantity_grams") or 0)
                    if grams <= 0:
                        continue
                meal["items"].append(_item_from_food(food, _round_grams(grams)))
            day["meals"].append(meal)

        if not any(m["items"] for m in day["meals"]):
            continue
        _recompute_totals(day)
        days_out.append(day)

    if report.dropped_items:
        logger.warning("Dropped %d plan item(s) not on the allow-list: %s", len(report.dropped_items), report.dropped_items)
    if not days_out:
        return None, report

    for day in days_out:
        total = day["daily_totals"]["calories"]
        if goal > 0 and total > 0:
            deviation = abs(total - goal) / goal
            if deviation > REBALANCE_TOLERANCE:
                factor = max(MIN_SCALE, min(MAX_SCALE, goal / total))
                _scale_day(day, factor)
                report.rebalanced_days[day["day"]] = round(factor, 3)
                total = day["daily_totals"]["calories"]
            if abs(total - goal) / goal > OFF_TARGET_TOLERANCE:
                report.off_target_days.append(day["day"])
        report.day_calories.append(total)
        for meal in day["meals"]:
            for item in meal["items"]:
                item.pop("_food", None)
                item.pop("_grams", None)

    if report.rebalanced_days:
        logger.info("Rebalanced %d day(s) toward %.0f kcal: %s", len(report.rebalanced_days), goal, report.rebalanced_days)
    if report.off_target_days:
        logger.warning("Day(s) still off target after rebalancing: %s (goal %.0f)", report.off_target_days, goal)

    plan = {
        "days": days_out,
        "calorie_target": goal,
        "macro_targets": {
            "protein_g": float(calorie_result.get("protein_g") or 0),
            "carbs_g": float(calorie_result.get("carbs_g") or 0),
            "fat_g": float(calorie_result.get("fat_g") or 0),
        },
        "daily_routine": str(selection.get("daily_routine") or ""),
    }
    return plan, report


def plan_averages(plan: dict[str, Any]) -> dict[str, float]:
    """Per-day averages across the plan's days (calories, protein, carbs, fat)."""
    days = plan.get("days", [])
    if not days:
        return {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    keys = ("calories", "protein", "carbs", "fat")
    return {k: round(sum(float(d.get("daily_totals", {}).get(k, 0)) for d in days) / len(days), 1) for k in keys}


def macro_summary_line(plan: dict[str, Any]) -> str:
    """One line of truth about how the week compares to its targets --
    shown to the user and handed to the prose model, so neither can claim a
    macro target is met when the computed numbers say it isn't."""
    avg = plan_averages(plan)
    targets = plan.get("macro_targets", {})

    def _cmp(actual: float, target: float) -> str:
        if not target:
            return f"{actual:.0f}g"
        delta = (actual - target) / target
        if abs(delta) <= 0.10:
            return f"{actual:.0f}g (on target)"
        return f"{actual:.0f}g ({'below' if delta < 0 else 'above'} the {target:.0f}g target)"

    return (
        f"Weekly average per day: {avg['calories']:.0f} kcal · "
        f"protein {_cmp(avg['protein'], float(targets.get('protein_g') or 0))} · "
        f"carbs {_cmp(avg['carbs'], float(targets.get('carbs_g') or 0))} · "
        f"fat {_cmp(avg['fat'], float(targets.get('fat_g') or 0))}"
    )


def render_plan_markdown(plan: dict[str, Any]) -> str:
    """The plan as the user reads it in chat. Generated from the computed
    plan so the text can never disagree with the structured card/email."""
    lines: list[str] = []
    targets = plan.get("macro_targets", {})
    lines.append(
        f"**Daily target: {plan.get('calorie_target', 0):.0f} kcal** "
        f"(protein {targets.get('protein_g', 0):.0f}g · carbs {targets.get('carbs_g', 0):.0f}g · fat {targets.get('fat_g', 0):.0f}g)"
    )
    lines.append(f"_{macro_summary_line(plan)}_")
    for day in plan.get("days", []):
        totals = day.get("daily_totals", {})
        lines.append("")
        lines.append(
            f"**{day.get('day', 'Day')}** — {totals.get('calories', 0):.0f} kcal "
            f"(P {totals.get('protein', 0):.0f}g · C {totals.get('carbs', 0):.0f}g · F {totals.get('fat', 0):.0f}g)"
        )
        for meal in day.get("meals", []):
            if not meal.get("items"):
                continue
            items = ", ".join(f"{i['food']} {i['quantity']}" for i in meal["items"])
            lines.append(f"- {meal.get('name', 'Meal')} ({meal.get('total_calories', 0):.0f} kcal): {items}")
    routine = plan.get("daily_routine")
    if routine:
        lines.append("")
        lines.append(f"**Daily routine:** {routine}")
    return "\n".join(lines)
