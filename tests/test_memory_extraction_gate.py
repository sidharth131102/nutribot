"""Tests for backend/memory/extraction.py's should_attempt_extraction() gate.

Pure function, no LLM call -- this is what decides whether the (real,
API-calling) extraction step runs at all. Getting this wrong either misses
facts worth remembering or adds unnecessary Groq calls on the already-fragile
rate budget, so it's tested directly and thoroughly.
"""
import pytest

from backend.memory.extraction import should_attempt_extraction


def test_plan_modification_intent_always_triggers():
    assert should_attempt_extraction("PLAN_MODIFICATION", "swap the eggs please") is True


@pytest.mark.parametrize(
    "message",
    [
        "I prefer chicken over fish",
        "I don't like oats",
        "I dont like oats",
        "I dislike spicy food",
        "I hate broccoli",
        "I love paneer dishes",
        "My goal is now to build muscle",
        "I want to switch to a vegan diet",
        "From now on please avoid dairy",
        "I'd rather have rice than roti",
        "Actually, id rather skip breakfast",
    ],
)
def test_signal_phrases_trigger_extraction(message):
    assert should_attempt_extraction("GENERAL_CONVERSATION", message) is True


@pytest.mark.parametrize(
    "message",
    [
        "What's my calorie target?",
        "Can you give me a meal plan?",
        "hi",
        "How much protein is in chicken breast?",
    ],
)
def test_ordinary_messages_do_not_trigger(message):
    assert should_attempt_extraction("NUTRITION_QUESTION", message) is False
    assert should_attempt_extraction("GENERAL_CONVERSATION", message) is False


def test_signal_phrase_matching_is_case_insensitive():
    assert should_attempt_extraction("GENERAL_CONVERSATION", "I PREFER low carb meals") is True
