from agent.context import build_cag_context
from agent.state import NutriBotState


def context_node(state: NutriBotState) -> NutriBotState:
    profile = state["profile"]
    targets = state["targets"]
    context = build_cag_context(profile, targets)
    return {**state, "cag_context": context, "allowed_foods": context.allowed_foods}
