import json

from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from agent.prompts import MEAL_PLAN_PROMPT
from agent.state import NutriBotState
from backend.config import get_settings
from backend.schemas import MealPlan


def _llm() -> ChatOpenAI:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("NUTRIBOT_OPENAI_API_KEY is required for meal generation.")
    return ChatOpenAI(model=settings.model_name, api_key=settings.openai_api_key, temperature=0)


def generate_node(state: NutriBotState) -> NutriBotState:
    prompt = MEAL_PLAN_PROMPT.format_messages(
        cag_context=state["cag_context"].model_dump_json(indent=2),
        rag_docs=json.dumps(state["rag_docs"], indent=2),
        query=state["query"],
    )
    response = _llm().invoke(prompt)
    raw = response.content if isinstance(response.content, str) else json.dumps(response.content)

    try:
        parsed = MealPlan.model_validate_json(raw)
        return {**state, "raw_generation": raw, "plan": parsed, "validation_errors": []}
    except ValidationError as exc:
        return {
            **state,
            "raw_generation": raw,
            "validation_errors": [f"invalid JSON meal plan: {exc}"],
        }
