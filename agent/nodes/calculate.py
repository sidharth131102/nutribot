from agent.state import NutriBotState
from tools.calculator import calculate_targets


def calculate_node(state: NutriBotState) -> NutriBotState:
    return {**state, "targets": calculate_targets(state["profile"])}
