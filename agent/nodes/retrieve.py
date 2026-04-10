from agent.state import NutriBotState
from rag.retriever import NutritionRetriever


retriever = NutritionRetriever()


def retrieve_node(state: NutriBotState) -> NutriBotState:
    docs = retriever.retrieve(state["query"], state["profile"])
    return {**state, "rag_docs": docs}
