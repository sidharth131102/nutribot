from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Gender(StrEnum):
    male = "male"
    female = "female"


class ActivityLevel(StrEnum):
    sedentary = "sedentary"
    light = "light"
    moderate = "moderate"
    active = "active"
    very_active = "very_active"


class Goal(StrEnum):
    fat_loss = "fat_loss"
    lean_loss = "lean_loss"
    maintenance = "maintenance"
    lean_bulk = "lean_bulk"
    bulk = "bulk"


class DietType(StrEnum):
    veg = "veg"
    non_veg = "non_veg"
    vegan = "vegan"


class UserProfile(BaseModel):
    age: int = Field(ge=13, le=100)
    gender: Gender
    weight: float = Field(gt=20, lt=300)
    height: float = Field(gt=100, lt=250)
    activity_level: ActivityLevel
    goal: Goal
    diet_type: DietType
    medical_conditions: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    food_preferences: list[str] = Field(default_factory=list)
    region: str | None = None

    @field_validator("medical_conditions", "allergies", "food_preferences")
    @classmethod
    def normalize_list(cls, values: list[str]) -> list[str]:
        return [value.strip().lower() for value in values if value.strip()]

    @field_validator("region")
    @classmethod
    def normalize_region(cls, value: str | None) -> str | None:
        return value.strip().lower() if value and value.strip() else None


class NutritionTargets(BaseModel):
    bmr: float
    tdee: float
    target_calories: float
    protein_target: float


class FoodDbItem(BaseModel):
    id: str
    food: str
    quantity_grams: float
    calories: float
    protein: float
    carbs: float
    fat: float
    diet_types: list[DietType]
    allergens: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    meal_types: list[str] = Field(default_factory=list)
    glycemic_index: str | None = None
    medical_tags: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("food", "glycemic_index")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return value.strip().lower() if value else value

    @field_validator("allergens", "regions", "meal_types", "medical_tags", "tags")
    @classmethod
    def normalize_food_lists(cls, values: list[str]) -> list[str]:
        return [value.strip().lower() for value in values if value.strip()]


class CagContext(BaseModel):
    user_profile: UserProfile
    targets: dict[str, float]
    constraints: dict[str, Any]
    restrictions: dict[str, list[str]]
    preferences: list[str]
    allowed_foods: list[dict[str, Any]]
    region: str | None = None


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


class DailyTotals(BaseModel):
    calories: float
    protein: float
    carbs: float
    fat: float


class MealPlan(BaseModel):
    meals: list[Meal]
    daily_totals: DailyTotals


class GeneratePlanRequest(BaseModel):
    user_profile: UserProfile
    query: str | None = "Generate a medically-aware daily meal plan."


class CreateUserProfileRequest(BaseModel):
    user_profile: UserProfile


class GeneratePlanResponse(BaseModel):
    status: str
    targets: NutritionTargets
    cag_context: CagContext
    retrieved_knowledge: list[str]
    plan: MealPlan | None = None
    validation_errors: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    user_profile: UserProfile
    message: str


class SavePlanRequest(BaseModel):
    user_id: int
    plan: MealPlan


class UserProfileResponse(UserProfile):
    id: int

    model_config = ConfigDict(from_attributes=True)
