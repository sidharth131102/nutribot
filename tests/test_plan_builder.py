"""Tests for backend/agents/plan_builder.py -- the deterministic side of
meal-plan generation (invariants 1 and 2). Pure, no LLM, no I/O."""
import pytest

from backend.agents.plan_builder import (
    MAX_SCALE,
    MIN_SCALE,
    PlanBuildReport,
    build_plan,
    parse_grams,
    render_plan_markdown,
)

OATS = {"id": "FOOD_001", "food": "oats", "quantity_grams": 60, "calories": 228, "protein": 8, "carbs": 40, "fat": 4}
MILK = {"id": "FOOD_002", "food": "low-fat milk", "quantity_grams": 250, "calories": 105, "protein": 8.5, "carbs": 12, "fat": 2.5}
PANEER = {"id": "FOOD_006", "food": "paneer", "quantity_grams": 100, "calories": 265, "protein": 18, "carbs": 3, "fat": 20}
ROTI = {"id": "FOOD_050", "food": "whole wheat roti", "quantity_grams": 80, "calories": 200, "protein": 6, "carbs": 40, "fat": 2}
FOODS = [OATS, MILK, PANEER, ROTI]

CALORIES = {"goal_calories": 2000.0, "protein_g": 150.0, "carbs_g": 200.0, "fat_g": 66.7}


def _selection(items_per_meal, days=1, routine="Wake 7AM"):
    return {
        "days": [
            {
                "day": f"Day {d + 1}",
                "meals": [{"name": name, "items": list(items)} for name, items in items_per_meal],
            }
            for d in range(days)
        ],
        "daily_routine": routine,
    }


# ── parse_grams ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "value,expected",
    [(80, 80.0), (80.5, 80.5), ("80g", 80.0), ("80 g", 80.0), ("80 grams", 80.0), (" 120G ", 120.0)],
)
def test_parse_grams_accepts_numbers_and_gram_strings(value, expected):
    assert parse_grams(value) == expected


@pytest.mark.parametrize("value", [None, 0, -5, "", "a handful", "1 cup", "2 x 40g", "1 bowl", True, [80]])
def test_parse_grams_rejects_unusable_values(value):
    assert parse_grams(value) is None


# ── build_plan: nutrients come from the DB, not the model ──────────────────

def test_item_nutrients_are_computed_from_food_db_times_grams():
    selection = _selection([("Breakfast", [{"food": "oats", "grams": 120, "calories": 999, "protein": 999}])])
    # Goal equals the item's true calories so no rebalancing interferes.
    plan, report = build_plan(selection, FOODS, {"goal_calories": 456.0})

    assert report.rebalanced_days == {}
    item = plan["days"][0]["meals"][0]["items"][0]
    # 120g is 2x the 60g DB serving -> exactly double every nutrient; the
    # model-supplied 999s are ignored entirely.
    assert item["quantity"] == "120g"
    assert item["calories"] == 456.0
    assert item["protein"] == 16.0
    assert item["carbs"] == 80.0
    assert item["fat"] == 8.0
    assert "_food" not in item and "_grams" not in item


def test_totals_are_sums_of_computed_items():
    selection = _selection([
        ("Breakfast", [{"food": "oats", "grams": 60}, {"food": "low-fat milk", "grams": 250}]),
        ("Lunch", [{"food": "paneer", "grams": 100}]),
    ])
    # 228 + 105 + 265 = 598 -> far below 2000, so it WILL be rebalanced;
    # check the pre-rebalance sums via the max-scale clamp instead.
    plan, report = build_plan(selection, FOODS, CALORIES)
    day = plan["days"][0]
    assert day["meals"][0]["total_calories"] == pytest.approx(
        sum(i["calories"] for i in day["meals"][0]["items"]), abs=0.1
    )
    assert day["daily_totals"]["calories"] == pytest.approx(
        sum(m["total_calories"] for m in day["meals"]), abs=0.1
    )
    assert day["daily_totals"]["protein"] == pytest.approx(
        sum(i["protein"] for m in day["meals"] for i in m["items"]), abs=0.1
    )


def test_off_list_items_are_dropped_and_reported():
    selection = _selection([("Lunch", [{"food": "unicorn steak", "grams": 200}, {"food": "paneer", "grams": 100}])])
    plan, report = build_plan(selection, FOODS, CALORIES)

    names = [i["food"] for i in plan["days"][0]["meals"][0]["items"]]
    assert names == ["paneer"]
    assert report.dropped_items == ["unicorn steak"]


def test_name_matching_is_tolerant_like_the_allow_list_check():
    selection = _selection([("Lunch", [{"food": "Whole Wheat Roti", "grams": 80}, {"food": "FOOD_006", "grams": 100}])])
    plan, report = build_plan(selection, FOODS, CALORIES)
    names = [i["food"] for i in plan["days"][0]["meals"][0]["items"]]
    assert names == ["whole wheat roti", "paneer"]
    assert report.dropped_items == []


def test_missing_grams_falls_back_to_db_serving_and_is_reported():
    selection = _selection([("Breakfast", [{"food": "oats"}])])
    plan, report = build_plan(selection, FOODS, {"goal_calories": 228.0})
    item = plan["days"][0]["meals"][0]["items"][0]
    assert item["quantity"] == "60g"
    assert item["calories"] == 228.0
    assert report.unparseable_items == ["oats"]


def test_returns_none_when_nothing_usable_survives():
    selection = _selection([("Lunch", [{"food": "unicorn steak", "grams": 200}])])
    plan, report = build_plan(selection, FOODS, CALORIES)
    assert plan is None
    assert report.dropped_items == ["unicorn steak"]


def test_returns_none_for_no_days():
    plan, report = build_plan({"days": []}, FOODS, CALORIES)
    assert plan is None
    assert isinstance(report, PlanBuildReport)


def test_truncates_to_seven_days():
    selection = _selection([("Lunch", [{"food": "paneer", "grams": 100}])], days=9)
    plan, _ = build_plan(selection, FOODS, CALORIES)
    assert len(plan["days"]) == 7


# ── rebalancing ─────────────────────────────────────────────────────────────

def test_short_day_is_scaled_up_to_the_target():
    # oats 60g (228) + roti 160g (400) + paneer 200g (530) + milk 250 (105) = 1263 vs 1500 goal
    selection = _selection([
        ("Breakfast", [{"food": "oats", "grams": 60}, {"food": "low-fat milk", "grams": 250}]),
        ("Lunch", [{"food": "whole wheat roti", "grams": 160}]),
        ("Dinner", [{"food": "paneer", "grams": 200}]),
    ])
    plan, report = build_plan(selection, FOODS, {"goal_calories": 1500.0})

    total = plan["days"][0]["daily_totals"]["calories"]
    assert abs(total - 1500) / 1500 <= 0.10
    assert "Day 1" in report.rebalanced_days
    assert 1.1 < report.rebalanced_days["Day 1"] < 1.3
    assert report.off_target_days == []
    assert report.day_calories == [total]
    # Every item was re-derived from the DB at the scaled grams.
    for meal in plan["days"][0]["meals"]:
        for item in meal["items"]:
            grams = parse_grams(item["quantity"])
            assert grams % 5 == 0


def test_day_already_on_target_is_left_alone():
    # 60g oats (228) + 250g milk (105) + 100g paneer (265) + 80g roti (200) = 798
    selection = _selection([
        ("Breakfast", [{"food": "oats", "grams": 60}, {"food": "low-fat milk", "grams": 250}]),
        ("Lunch", [{"food": "paneer", "grams": 100}, {"food": "whole wheat roti", "grams": 80}]),
    ])
    plan, report = build_plan(selection, FOODS, {"goal_calories": 800.0})
    assert report.rebalanced_days == {}
    assert plan["days"][0]["daily_totals"]["calories"] == 798.0


def test_scale_factor_is_clamped_and_unreachable_day_is_reported():
    # One 60g serving of oats (228 kcal) against a 2000 kcal goal needs ~8.8x.
    selection = _selection([("Breakfast", [{"food": "oats", "grams": 60}])])
    plan, report = build_plan(selection, FOODS, CALORIES)

    assert report.rebalanced_days["Day 1"] == MAX_SCALE
    assert report.off_target_days == ["Day 1"]
    assert plan["days"][0]["daily_totals"]["calories"] == pytest.approx(228 * MAX_SCALE, rel=0.05)


def test_oversized_day_is_scaled_down_within_clamp():
    selection = _selection([("Dinner", [{"food": "paneer", "grams": 1000}])])  # 2650 kcal vs 800
    plan, report = build_plan(selection, FOODS, {"goal_calories": 800.0})
    factor = report.rebalanced_days["Day 1"]
    assert MIN_SCALE <= factor < 1
    assert plan["days"][0]["daily_totals"]["calories"] < 2650


def test_no_goal_means_no_rebalancing():
    selection = _selection([("Breakfast", [{"food": "oats", "grams": 60}])])
    plan, report = build_plan(selection, FOODS, {})
    assert report.rebalanced_days == {}
    assert report.off_target_days == []
    assert plan["calorie_target"] == 0.0


def test_plan_carries_targets_and_routine():
    selection = _selection([("Breakfast", [{"food": "oats", "grams": 60}])], routine="Wake 6AM, sleep 10PM")
    plan, _ = build_plan(selection, FOODS, CALORIES)
    assert plan["calorie_target"] == 2000.0
    assert plan["macro_targets"] == {"protein_g": 150.0, "carbs_g": 200.0, "fat_g": 66.7}
    assert plan["daily_routine"] == "Wake 6AM, sleep 10PM"


# ── render_plan_markdown ────────────────────────────────────────────────────

def test_markdown_lists_every_item_with_final_quantities_and_totals():
    selection = _selection([
        ("Breakfast", [{"food": "oats", "grams": 60}, {"food": "low-fat milk", "grams": 250}]),
        ("Mid-Morning Snack", []),
        ("Lunch", [{"food": "paneer", "grams": 100}, {"food": "whole wheat roti", "grams": 80}]),
    ])
    plan, _ = build_plan(selection, FOODS, {"goal_calories": 800.0, "protein_g": 60, "carbs_g": 80, "fat_g": 27})
    text = render_plan_markdown(plan)

    assert "Daily target: 800 kcal" in text
    assert "**Day 1** — 798 kcal" in text
    assert "Breakfast (333 kcal): oats 60g, low-fat milk 250g" in text
    assert "Lunch (465 kcal): paneer 100g, whole wheat roti 80g" in text
    assert "Mid-Morning Snack" not in text  # empty meals are skipped
    assert "**Daily routine:** Wake 7AM" in text


# ── macro honesty: averages + summary line ──────────────────────────────────

def test_plan_averages_and_summary_flag_a_protein_shortfall():
    # 60g oats (228 kcal, 8g P) + 100g paneer (265 kcal, 18g P) = 493 kcal, 26g P
    selection = _selection([("Breakfast", [{"food": "oats", "grams": 60}, {"food": "paneer", "grams": 100}])], days=2)
    plan, _ = build_plan(selection, FOODS, {"goal_calories": 493.0, "protein_g": 60.0, "carbs_g": 43.0, "fat_g": 24.0})

    from backend.agents.plan_builder import macro_summary_line, plan_averages
    avg = plan_averages(plan)
    assert avg["calories"] == pytest.approx(493.0)
    assert avg["protein"] == pytest.approx(26.0)

    line = macro_summary_line(plan)
    assert "493 kcal" in line
    assert "protein 26g (below the 60g target)" in line
    assert "carbs 43g (on target)" in line
    assert "fat 24g (on target)" in line
    # And it's printed in the plan text the user reads.
    assert line in render_plan_markdown(plan)


def test_summary_marks_an_overshoot_above_target():
    selection = _selection([("Lunch", [{"food": "paneer", "grams": 100}])])
    plan, _ = build_plan(selection, FOODS, {"goal_calories": 265.0, "protein_g": 10.0})
    from backend.agents.plan_builder import macro_summary_line
    assert "protein 18g (above the 10g target)" in macro_summary_line(plan)


def test_summary_without_targets_just_reports_actuals():
    selection = _selection([("Lunch", [{"food": "paneer", "grams": 100}])])
    plan, _ = build_plan(selection, FOODS, {})
    from backend.agents.plan_builder import macro_summary_line
    assert "protein 18g ·" in macro_summary_line(plan)
    assert "target" not in macro_summary_line(plan)
