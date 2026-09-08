"""Tests for backend/rag/reranker.py -- JSON-array parsing and fallback
behavior, no real LLM calls (mirrors test_medical_extraction_prompt.py's shape)."""
import pytest

from backend.rag.reranker import _extract_index_array, rerank


# ── Parsing ───────────────────────────────────────────────────────────────

def test_parses_valid_array():
    assert _extract_index_array("[3, 0, 7]") == [3, 0, 7]


def test_parses_empty_array():
    assert _extract_index_array("[]") == []


def test_parses_array_wrapped_in_prose():
    assert _extract_index_array("Here you go:\n[2, 1, 0]\nDone.") == [2, 1, 0]


def test_returns_none_for_malformed_json():
    assert _extract_index_array("[1, 2,") is None


def test_returns_none_for_no_array_at_all():
    assert _extract_index_array("No array here.") is None


def test_returns_none_for_array_with_non_integer_elements():
    assert _extract_index_array('["a", "b"]') is None


# ── rerank() fallback behavior ───────────────────────────────────────────

CANDIDATES = [
    {"chunk_text": "chunk zero", "source": "a", "condition": "diabetes"},
    {"chunk_text": "chunk one", "source": "b", "condition": "pcos"},
    {"chunk_text": "chunk two", "source": "c", "condition": "general"},
]


@pytest.mark.asyncio
async def test_rerank_falls_back_to_fused_order_on_provider_error(monkeypatch):
    def _raise():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("backend.rag.reranker.get_provider", _raise)

    result = await rerank("query", CANDIDATES, top_k=2)

    assert result == CANDIDATES[:2]


@pytest.mark.asyncio
async def test_rerank_falls_back_when_response_has_no_parseable_array(monkeypatch):
    class _FakeResult:
        text = "I cannot help with that."

    class _FakeProvider:
        async def generate(self, **kwargs):
            return _FakeResult()

    monkeypatch.setattr("backend.rag.reranker.get_provider", lambda: _FakeProvider())

    result = await rerank("query", CANDIDATES, top_k=2)

    assert result == CANDIDATES[:2]


@pytest.mark.asyncio
async def test_rerank_reorders_by_returned_indices(monkeypatch):
    class _FakeResult:
        text = "[2, 0]"

    class _FakeProvider:
        async def generate(self, **kwargs):
            return _FakeResult()

    monkeypatch.setattr("backend.rag.reranker.get_provider", lambda: _FakeProvider())

    result = await rerank("query", CANDIDATES, top_k=2)

    assert result == [CANDIDATES[2], CANDIDATES[0]]


@pytest.mark.asyncio
async def test_rerank_pads_with_remaining_candidates_when_llm_returns_fewer_than_top_k(monkeypatch):
    class _FakeResult:
        text = "[1]"

    class _FakeProvider:
        async def generate(self, **kwargs):
            return _FakeResult()

    monkeypatch.setattr("backend.rag.reranker.get_provider", lambda: _FakeProvider())

    result = await rerank("query", CANDIDATES, top_k=3)

    assert result[0] == CANDIDATES[1]
    assert len(result) == 3
    assert set(id(c) for c in result) == set(id(c) for c in CANDIDATES)


@pytest.mark.asyncio
async def test_rerank_drops_out_of_range_and_duplicate_indices(monkeypatch):
    class _FakeResult:
        text = "[5, 1, 1, -1]"

    class _FakeProvider:
        async def generate(self, **kwargs):
            return _FakeResult()

    monkeypatch.setattr("backend.rag.reranker.get_provider", lambda: _FakeProvider())

    result = await rerank("query", CANDIDATES, top_k=3)

    assert result[0] == CANDIDATES[1]
    assert len(result) == 3  # padded back up to top_k


@pytest.mark.asyncio
async def test_rerank_returns_empty_for_empty_candidates():
    assert await rerank("query", [], top_k=5) == []
