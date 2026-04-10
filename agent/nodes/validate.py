from agent.state import NutriBotState
from tools.validator import validate_plan


def validate_node(state: NutriBotState) -> NutriBotState:
    errors = state.get("validation_errors", [])
    if not errors and "plan" in state:
        errors = validate_plan(state["plan"], state["targets"], state["profile"])
    return {**state, "validation_errors": errors}
