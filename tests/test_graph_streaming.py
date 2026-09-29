"""Tests for stream_chat_pipeline()'s progress-event sequencing (backend/agents/graph.py).

Uses a fake compiled graph instead of mocking every agent's LLM call -- that
full-pipeline coverage belongs to the eval harness and live testing. This
only proves the streaming wrapper itself: it accumulates node updates into
the right final state and emits progress events in the right order, exactly
once each, followed by exactly one "done" event.
"""
import pytest

from backend.agents import graph as graph_module


class _FakeCompiledGraph:
    def __init__(self, updates):
        self._updates = updates

    async def astream(self, initial_state, stream_mode=None, config=None):
        assert stream_mode == "updates"
        for update in self._updates:
            yield update


@pytest.mark.asyncio
async def test_stream_chat_pipeline_emits_progress_then_one_done_event(monkeypatch):
    fake_graph = _FakeCompiledGraph([
        {"input_guardrail": {"guardrail_blocked": False}},
        {"profile": {"user_name": "Asha"}},
        {"intent": {"intent": "GENERAL_CONVERSATION"}},
        {"meal_plan": {"response": "Hi Asha!", "plan_proposed": False}},
    ])
    monkeypatch.setattr(graph_module, "get_compiled_graph", lambda: fake_graph)

    events = [e async for e in graph_module.stream_chat_pipeline("u1", "s1", "hello")]

    progress = [e for e in events if e["type"] == "progress"]
    done = [e for e in events if e["type"] == "done"]
    assert len(done) == 1
    assert events[-1]["type"] == "done"  # done is strictly last
    assert [e["node"] for e in progress] == ["input_guardrail", "profile", "intent", "meal_plan"]
    assert progress[0]["label"] == "Checking your message"
    assert progress[3]["label"] == "Building your response"

    # Final state is the merge of every node's update, in order.
    final_state = done[0]["state"]
    assert final_state["user_name"] == "Asha"
    assert final_state["intent"] == "GENERAL_CONVERSATION"
    assert final_state["response"] == "Hi Asha!"
    assert final_state["guardrail_blocked"] is False


@pytest.mark.asyncio
async def test_stream_chat_pipeline_falls_back_to_node_name_for_unmapped_node(monkeypatch):
    fake_graph = _FakeCompiledGraph([{"some_future_node": {"foo": "bar"}}])
    monkeypatch.setattr(graph_module, "get_compiled_graph", lambda: fake_graph)

    events = [e async for e in graph_module.stream_chat_pipeline("u1", "s1", "hello")]
    progress = [e for e in events if e["type"] == "progress"]
    assert progress[0]["node"] == "some_future_node"
    assert progress[0]["label"] == "some_future_node"


@pytest.mark.asyncio
async def test_stream_chat_pipeline_with_no_updates_still_yields_done(monkeypatch):
    """A pathological empty graph run (e.g. blocked before any node fires in
    a future topology) must never leave the caller without a final event."""
    fake_graph = _FakeCompiledGraph([])
    monkeypatch.setattr(graph_module, "get_compiled_graph", lambda: fake_graph)

    events = [e async for e in graph_module.stream_chat_pipeline("u1", "s1", "hello")]
    assert len(events) == 1
    assert events[0]["type"] == "done"
    assert events[0]["state"]["user_id"] == "u1"
