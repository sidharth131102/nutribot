"""backend/tools/pdf_tool.py -- renders a computed plan to PDF. Verified by
parsing the output back with pypdf (already a dependency): page count,
footers, and that every food, quantity, total and target made it in."""
from datetime import date
from io import BytesIO

import pytest
from pypdf import PdfReader

from backend.agents.plan_builder import build_plan
from backend.tools.pdf_tool import DISCLAIMER, render_meal_plan_pdf

OATS = {"id": "FOOD_001", "food": "oats", "quantity_grams": 60, "calories": 228, "protein": 8, "carbs": 40, "fat": 4}
MILK = {"id": "FOOD_002", "food": "low-fat milk", "quantity_grams": 250, "calories": 105, "protein": 8.5, "carbs": 12, "fat": 2.5}
PANEER = {"id": "FOOD_006", "food": "paneer", "quantity_grams": 100, "calories": 265, "protein": 18, "carbs": 3, "fat": 20}
ROTI = {"id": "FOOD_050", "food": "whole wheat roti", "quantity_grams": 80, "calories": 200, "protein": 6, "carbs": 40, "fat": 2}
FOODS = [OATS, MILK, PANEER, ROTI]


def _plan(days=7):
    selection = {
        "days": [
            {
                "day": f"Day {d}",
                "meals": [
                    {"name": "Breakfast", "items": [{"food": "oats", "grams": 80}, {"food": "low-fat milk", "grams": 250}]},
                    {"name": "Mid-Morning Snack", "items": [{"food": "low-fat milk", "grams": 250}]},
                    {"name": "Lunch", "items": [{"food": "paneer", "grams": 150}, {"food": "whole wheat roti", "grams": 160}]},
                    {"name": "Evening Snack", "items": []},
                    {"name": "Dinner", "items": [{"food": "paneer", "grams": 100}, {"food": "whole wheat roti", "grams": 160}]},
                ],
            }
            for d in range(1, days + 1)
        ],
        "daily_routine": "Wake 7AM, breakfast 8AM, lunch 1PM, dinner 8PM, sleep 11PM",
    }
    plan, _ = build_plan(selection, FOODS, {"goal_calories": 2000.0, "protein_g": 150.0, "carbs_g": 200.0, "fat_g": 66.7})
    return plan


def _text(pdf_bytes: bytes) -> tuple[str, int]:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages), len(reader.pages)


def test_renders_a_valid_multipage_pdf_with_numbered_footers():
    pdf = render_meal_plan_pdf(_plan(), user_name="Asha", bot_name="Nova", generated_on=date(2026, 9, 12))
    assert pdf.startswith(b"%PDF")
    text, pages = _text(pdf)
    assert pages >= 2
    for n in range(1, pages + 1):
        assert f"Page {n} of {pages}" in text


def test_every_day_food_quantity_and_total_is_in_the_document():
    plan = _plan()
    pdf = render_meal_plan_pdf(plan, user_name="Asha", bot_name="Nova")
    text, _ = _text(pdf)

    assert "7-Day Meal Plan" in text
    assert "Prepared for Asha by Nova" in text
    for day in plan["days"]:
        assert day["day"] in text
        for meal in day["meals"]:
            for item in meal["items"]:
                assert item["food"] in text
                assert item["quantity"] in text
    # Day totals come straight from the plan.
    day1 = plan["days"][0]["daily_totals"]
    assert f"{day1['calories']:.0f}" in text
    assert "Day total" in text and "Meal total" in text


def test_targets_summary_routine_and_disclaimer_are_present():
    plan = _plan()
    pdf = render_meal_plan_pdf(plan, user_name="Asha", bot_name="Nova",
                               profile={"goal": "fat_loss", "diet_type": "vegetarian", "activity_level": "moderately_active",
                                        "medical_conditions": ["diabetes"], "allergies": ["peanuts"]})
    text, _ = _text(pdf)
    assert "Daily target" in text and "2000 kcal" in text and "150 g" in text
    assert "Weekly average" in text
    assert "below the 150g target" in text  # the honest macro summary line
    assert "Wake 7AM" in text
    assert "Goal: fat loss" in text and "Conditions: diabetes" in text and "Allergies: peanuts" in text
    assert DISCLAIMER[:40] in text


def test_empty_meals_are_skipped_and_single_day_fits_one_page():
    pdf = render_meal_plan_pdf(_plan(days=1), user_name="Asha", bot_name="Nova")
    text, pages = _text(pdf)
    assert pages == 1
    assert "Evening Snack" not in text  # that meal had no items


def test_plan_without_days_is_rejected():
    with pytest.raises(ValueError):
        render_meal_plan_pdf({"days": []}, user_name="Asha", bot_name="Nova")
