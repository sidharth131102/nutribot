"""Context Builder (v2 roadmap Phase 3): assembles one typed object from
profile + relevant memory + episodic events + RAG + deterministic calcs,
replacing ad hoc state.get(...) access scattered through prompt-building code.

memory_context/episodic_context are deliberately terse (top few facts/events,
one short line each) -- the generation prompt's token budget is tightly
guarded against the shared Groq rate limit (see docs/CURRENT_STATE.md).
"""
from typing import Any

from pydantic import BaseModel

from backend.agents.state import NutriBotState
from backend.llm.base import Message


class GenerationContext(BaseModel):
    bot_name: str
    user_name: str
    profile_context: str
    calorie_result: dict[str, Any]
    rag_context: str
    food_context_str: str
    previous_plans: list[dict[str, Any]]
    memory_context: str
    episodic_context: str
    chat_history: list[Message]


def format_history(messages: list[dict]) -> list[Message]:
    """Convert stored chat messages to provider-agnostic Message objects."""
    formatted: list[Message] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        formatted.append(Message(role="user" if role == "user" else "assistant", content=content))
    return formatted


def _format_memory_context(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return ""
    lines = [f"- {m['fact']}" for m in memories]
    return "REMEMBERED CONTEXT:\n" + "\n".join(lines)


def _format_episodic_context(events: list[dict[str, Any]]) -> str:
    if not events:
        return ""
    lines: list[str] = []
    for e in events:
        ts = e.get("timestamp")
        ts_str = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)
        details = e.get("details", {})
        if e.get("event_type") == "goal_change":
            lines.append(f"- Goal changed to '{details.get('new_goal', '?')}' on {ts_str}")
        elif e.get("event_type") == "plan_accepted":
            lines.append(f"- Accepted a meal plan on {ts_str}")
    return "RECENT ACTIVITY:\n" + "\n".join(lines) if lines else ""


def build_context(state: NutriBotState) -> GenerationContext:
    return GenerationContext(
        bot_name=state.get("bot_name", "Nova"),
        user_name=state.get("user_name", "there"),
        profile_context=state.get("profile_context", ""),
        calorie_result=state.get("calorie_result") or {},
        rag_context=state.get("rag_context", ""),
        food_context_str=state.get("food_context_str", ""),
        previous_plans=state.get("previous_plans", []),
        memory_context=_format_memory_context(state.get("relevant_memories") or []),
        episodic_context=_format_episodic_context(state.get("recent_events") or []),
        chat_history=format_history(state.get("chat_history", [])),
    )
