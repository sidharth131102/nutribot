"""Tests for backend/context/builder.py -- pure, no DB/API calls."""
from datetime import datetime

from backend.context.builder import build_context


def _base_state(**overrides):
    state = {
        "bot_name": "Nova",
        "user_name": "Sid",
        "profile_context": "USER PROFILE:\n- Name: Sid",
        "calorie_result": {"goal_calories": 2000},
        "rag_context": "Some clinical guideline text",
        "food_context_str": "APPROVED FOOD OPTIONS...",
        "previous_plans": [{"plan_summary": "A previous plan"}],
        "chat_history": [{"role": "user", "content": "hi"}],
    }
    state.update(overrides)
    return state


def test_build_context_assembles_all_fields():
    context = build_context(_base_state())
    assert context.bot_name == "Nova"
    assert context.user_name == "Sid"
    assert context.profile_context.startswith("USER PROFILE")
    assert context.calorie_result["goal_calories"] == 2000
    assert context.rag_context == "Some clinical guideline text"
    assert len(context.previous_plans) == 1
    assert len(context.chat_history) == 1


def test_build_context_defaults_when_fields_missing():
    context = build_context({})
    assert context.bot_name == "Nova"
    assert context.user_name == "there"
    assert context.calorie_result == {}
    assert context.memory_context == ""
    assert context.episodic_context == ""
    assert context.chat_history == []


def test_memory_context_formats_active_facts():
    state = _base_state(relevant_memories=[{"fact": "Dislikes oats"}, {"fact": "Prefers high protein"}])
    context = build_context(state)
    assert "Dislikes oats" in context.memory_context
    assert "Prefers high protein" in context.memory_context
    assert context.memory_context.startswith("REMEMBERED CONTEXT:")


def test_memory_context_empty_when_no_memories():
    context = build_context(_base_state(relevant_memories=[]))
    assert context.memory_context == ""


def test_memory_context_groups_medical_history_under_its_own_heading():
    state = _base_state(relevant_memories=[
        {"fact": "Allergic to peanuts", "category": "medical_history"},
        {"fact": "Dislikes oats", "category": "preference"},
    ])
    context = build_context(state)
    assert "Medical history (from uploaded documents):" in context.memory_context
    assert "Other remembered context:" in context.memory_context
    medical_idx = context.memory_context.index("Allergic to peanuts")
    other_idx = context.memory_context.index("Dislikes oats")
    assert medical_idx < other_idx  # medical facts surface first


def test_memory_context_handles_facts_without_a_category():
    """Pre-existing facts (or test fixtures) may lack a category field --
    must not crash, and should fall into the general section."""
    state = _base_state(relevant_memories=[{"fact": "Dislikes oats"}])
    context = build_context(state)
    assert "Other remembered context:" in context.memory_context
    assert "Dislikes oats" in context.memory_context


def test_episodic_context_formats_goal_change():
    state = _base_state(recent_events=[
        {"event_type": "goal_change", "details": {"new_goal": "muscle_gain"}, "timestamp": datetime(2026, 1, 1)},
    ])
    context = build_context(state)
    assert "muscle_gain" in context.episodic_context
    assert "2026-01-01" in context.episodic_context


def test_episodic_context_formats_plan_accepted():
    state = _base_state(recent_events=[
        {"event_type": "plan_accepted", "details": {}, "timestamp": datetime(2026, 1, 2)},
    ])
    context = build_context(state)
    assert "Accepted a meal plan" in context.episodic_context


def test_episodic_context_empty_when_no_events():
    context = build_context(_base_state(recent_events=[]))
    assert context.episodic_context == ""


def test_format_history_prefers_english_form_of_translated_messages():
    """The multilingual layer stores `content` (what the user saw, e.g. Hindi)
    and `content_en` (what the pipeline processed); history fed back into the
    English-only pipeline must use the English form."""
    context = build_context(_base_state(chat_history=[
        {"role": "user", "content": "मुझे एक मील प्लान दो", "content_en": "Give me a meal plan", "language": "hi"},
        {"role": "assistant", "content": "यह रहा आपका प्लान", "content_en": "Here is your plan", "language": "hi"},
        {"role": "user", "content": "thanks"},  # pre-multilingual message, no content_en
    ]))
    assert [m.content for m in context.chat_history] == ["Give me a meal plan", "Here is your plan", "thanks"]
    assert [m.role for m in context.chat_history] == ["user", "assistant", "user"]
