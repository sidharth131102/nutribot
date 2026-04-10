from langgraph.graph import END, StateGraph

from agent.nodes.calculate import calculate_node
from agent.nodes.context import context_node
from agent.nodes.generate import generate_node
from agent.nodes.retrieve import retrieve_node
from agent.nodes.retry import retry_node, should_retry
from agent.nodes.validate import validate_node
from agent.state import NutriBotState
from backend.schemas import GeneratePlanResponse, UserProfile


def build_graph():
    graph = StateGraph(NutriBotState)
    graph.add_node("calculate", calculate_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("context", context_node)
    graph.add_node("generate", generate_node)
    graph.add_node("validate", validate_node)
    graph.add_node("retry", retry_node)

    graph.set_entry_point("calculate")
    graph.add_edge("calculate", "retrieve")
    graph.add_edge("retrieve", "context")
    graph.add_edge("context", "generate")
    graph.add_edge("generate", "validate")
    graph.add_conditional_edges(
        "validate",
        should_retry,
        {"success": END, "retry": "retry", "failed": END},
    )
    graph.add_edge("retry", "generate")
    return graph.compile()


async def generate_plan(profile: UserProfile, query: str) -> GeneratePlanResponse:
    app = build_graph()
    state = await app.ainvoke({"profile": profile, "query": query, "attempts": 1})
    has_errors = bool(state.get("validation_errors"))
    return GeneratePlanResponse(
        status="error" if has_errors else "ok",
        targets=state["targets"],
        cag_context=state["cag_context"],
        retrieved_knowledge=state["rag_docs"],
        plan=None if has_errors else state.get("plan"),
        validation_errors=state.get("validation_errors", []),
    )
