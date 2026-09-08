"""Typed models for the evaluation harness (v2 roadmap Phase 1b)."""
from typing import Any, Literal

from pydantic import BaseModel, Field

Category = Literal[
    "general_qa",
    "meal_plan_request",
    "plan_modification",
    "allergy_diet_edge_case",
    "medical_context",
    "ambiguous_unsafe",
    "rag_dependent",
    "structured_output",
]


class GoldenCase(BaseModel):
    id: str
    category: Category
    profile: dict[str, Any]
    user_message: str
    chat_history: list[dict[str, str]] = Field(default_factory=list)
    previous_plans: list[dict[str, Any]] = Field(default_factory=list)
    expect_plan: bool | None = None  # None = no assertion on plan_proposed
    # False when the user_message itself asks to deviate from the profile's
    # computed goal_calories (e.g. "reduce my portions") -- the model
    # correctly complying would otherwise look like a calorie-tolerance
    # failure. True/default: check daily totals against goal_calories.
    check_calorie_tolerance: bool = True


class DeterministicResult(BaseModel):
    passed: bool
    failures: list[str] = Field(default_factory=list)


class JudgeResult(BaseModel):
    groundedness: float
    relevance: float
    completeness: float
    unsupported_claims: bool
    notes: str = ""


class CaseResult(BaseModel):
    case_id: str
    category: Category
    provider: str
    model: str
    intent: str
    deterministic: DeterministicResult
    judge: JudgeResult | None = None
    response_preview: str = ""
