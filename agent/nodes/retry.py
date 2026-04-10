from agent.state import NutriBotState
from backend.config import get_settings


def retry_node(state: NutriBotState) -> NutriBotState:
    attempts = state.get("attempts", 1) + 1
    errors = state.get("validation_errors", [])
    retry_query = (
        f"{state['query']}\n\nPrevious output failed validation. Fix these errors without "
        f"changing the deterministic target values: {errors}"
    )
    return {**state, "attempts": attempts, "query": retry_query}


def should_retry(state: NutriBotState) -> str:
    if not state.get("validation_errors"):
        return "success"
    if state.get("attempts", 1) >= get_settings().max_generation_retries:
        return "failed"
    return "retry"
