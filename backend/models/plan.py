from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class MealItem(BaseModel):
    food: str
    quantity: str
    calories: float
    protein: float
    carbs: float
    fat: float


class Meal(BaseModel):
    name: str
    items: list[MealItem]
    total_calories: float


class DayPlan(BaseModel):
    day: str  # e.g. "Day 1 - Monday"
    meals: list[Meal]
    daily_totals: dict[str, float]


class WeeklyMealPlan(BaseModel):
    days: list[DayPlan]
    calorie_target: float
    macro_targets: dict[str, float]
    daily_routine: str = ""


class AcceptedPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    accepted_at: datetime = Field(default_factory=datetime.utcnow)
    calorie_target: float
    plan_summary: str
    plan_full: dict[str, Any]


class PlanAcceptRequest(BaseModel):
    user_id: str
    session_id: str
    plan_data: dict[str, Any]
    calorie_target: float
    plan_summary: str


class PlanAcceptResponse(BaseModel):
    status: str
    plan_id: str
    message: str
