from typing import Literal

from pydantic import BaseModel, Field

InputCategory = Literal["NONE", "MEDICAL_EMERGENCY", "MEDICATION_MISUSE", "SELF_HARM"]


class InputCheckResult(BaseModel):
    blocked: bool
    category: InputCategory = "NONE"
    # The fixed, vetted string actually shown to the user when blocked --
    # never LLM-generated. None when not blocked.
    canned_response: str | None = None


class OutputCheckResult(BaseModel):
    safe: bool
    issues: list[str] = Field(default_factory=list)
    # Short corrective text fed back into the next meal_plan_agent_node call
    # when safe=False and a regeneration attempt remains.
    feedback: str = ""
