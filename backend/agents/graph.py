"""LangGraph stateful multi-agent graph definition for NutriBot.

Graph topology:
  profile → memory_retrieval → intent → [route] → calorie? → rag? → food?
    → meal_plan → [extract?] → END

Routing rules:
  CALORIE_CALCULATION  → calorie → meal_plan
  MEAL_PLAN_REQUEST    → calorie → rag → food → meal_plan
  PLAN_MODIFICATION    → calorie → rag → food → meal_plan
  NUTRITION_QUESTION   → rag → meal_plan
  ROUTINE_REQUEST      → rag → food → meal_plan
  GENERAL_CONVERSATION → meal_plan

memory_extraction after meal_plan is conditional (see
backend.memory.extraction.should_attempt_extraction) -- it only runs on
turns carrying a preference/goal signal, not every turn, to avoid adding a
3rd Groq call per message on top of the already-fragile rate budget.
"""
import logging

from langgraph.graph import END, StateGraph

from backend.agents.calorie_agent import calorie_agent_node
from backend.agents.food_agent import food_agent_node
from backend.agents.intent_agent import intent_agent_node
from backend.agents.meal_plan_agent import meal_plan_agent_node
from backend.agents.memory_extraction_agent import memory_extraction_agent_node
from backend.agents.memory_retrieval_agent import memory_retrieval_agent_node
from backend.agents.profile_agent import profile_agent_node
from backend.agents.rag_agent import rag_agent_node
from backend.agents.state import NutriBotState
from backend.memory.extraction import should_attempt_extraction
from backend.observability import new_trace_id, trace_id_var

logger = logging.getLogger("nutribot.graph")

# Intents that require calorie calculation before anything else
CALORIE_INTENTS = {"CALORIE_CALCULATION", "MEAL_PLAN_REQUEST", "PLAN_MODIFICATION"}
# Intents that require RAG retrieval
RAG_INTENTS = {"MEAL_PLAN_REQUEST", "PLAN_MODIFICATION", "NUTRITION_QUESTION", "ROUTINE_REQUEST"}
# Intents that require food DB filtering
FOOD_INTENTS = {"MEAL_PLAN_REQUEST", "PLAN_MODIFICATION", "ROUTINE_REQUEST"}


def _route_after_intent(state: NutriBotState) -> str:
    intent = state.get("intent", "GENERAL_CONVERSATION")
    if intent in CALORIE_INTENTS:
        return "calorie"
    if intent in RAG_INTENTS:
        return "rag"
    return "meal_plan"


def _route_after_calorie(state: NutriBotState) -> str:
    intent = state.get("intent", "GENERAL_CONVERSATION")
    if intent == "CALORIE_CALCULATION":
        return "meal_plan"
    # MEAL_PLAN_REQUEST and PLAN_MODIFICATION both need RAG next
    return "rag"


def _route_after_rag(state: NutriBotState) -> str:
    intent = state.get("intent", "GENERAL_CONVERSATION")
    if intent in FOOD_INTENTS:
        return "food"
    return "meal_plan"


def _route_after_meal_plan(state: NutriBotState) -> str:
    intent = state.get("intent", "GENERAL_CONVERSATION")
    user_message = state.get("user_message", "")
    if should_attempt_extraction(intent, user_message):
        return "extract"
    return "end"


def build_graph() -> StateGraph:
    graph = StateGraph(NutriBotState)

    # Register nodes
    graph.add_node("profile", profile_agent_node)
    graph.add_node("memory_retrieval", memory_retrieval_agent_node)
    graph.add_node("intent", intent_agent_node)
    graph.add_node("calorie", calorie_agent_node)
    graph.add_node("rag", rag_agent_node)
    graph.add_node("food", food_agent_node)
    graph.add_node("meal_plan", meal_plan_agent_node)
    graph.add_node("memory_extraction", memory_extraction_agent_node)

    # Fixed edges
    graph.set_entry_point("profile")
    graph.add_edge("profile", "memory_retrieval")
    graph.add_edge("memory_retrieval", "intent")
    graph.add_edge("food", "meal_plan")
    graph.add_edge("memory_extraction", END)

    # Conditional routing
    graph.add_conditional_edges(
        "intent",
        _route_after_intent,
        {"calorie": "calorie", "rag": "rag", "meal_plan": "meal_plan"},
    )
    graph.add_conditional_edges(
        "calorie",
        _route_after_calorie,
        {"rag": "rag", "meal_plan": "meal_plan"},
    )
    graph.add_conditional_edges(
        "rag",
        _route_after_rag,
        {"food": "food", "meal_plan": "meal_plan"},
    )
    graph.add_conditional_edges(
        "meal_plan",
        _route_after_meal_plan,
        {"extract": "memory_extraction", "end": END},
    )

    return graph


_compiled_graph = None


def get_compiled_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph().compile()
    return _compiled_graph


async def run_chat_pipeline(
    user_id: str,
    session_id: str,
    user_message: str,
) -> NutriBotState:
    """Execute the full LangGraph pipeline for a single chat message."""
    # Caller (backend/main.py) sets trace_id_var per-request; fall back to a
    # fresh one if this is invoked directly (e.g. a script) without that.
    trace_id = trace_id_var.get()
    if trace_id == "-":
        trace_id = new_trace_id()
        trace_id_var.set(trace_id)

    graph = get_compiled_graph()
    initial_state: NutriBotState = {
        "trace_id": trace_id,
        "user_id": user_id,
        "session_id": session_id,
        "user_message": user_message,
    }
    result = await graph.ainvoke(initial_state)
    logger.info(
        "Pipeline complete — intent=%s plan_proposed=%s",
        result.get("intent"),
        result.get("plan_proposed"),
    )
    return result
