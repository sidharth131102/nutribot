"""Tests for backend/rag/bm25_index.py -- BM25 tokenization, indexing, search.

Uses a temp corpus file + monkeypatched settings so this never touches
data/rag_corpus.json or requires real Pinecone/Azure credentials.
"""
import json

import pytest

from backend.config import get_settings
from backend.rag import bm25_index
from backend.rag.bm25_index import _tokenize, bm25_search


@pytest.fixture(autouse=True)
def _clear_caches():
    """The module caches corpus + index via lru_cache -- clear before and
    after every test so tests don't leak state into each other."""
    bm25_index._load_corpus.cache_clear()
    bm25_index._get_bm25_index.cache_clear()
    yield
    bm25_index._load_corpus.cache_clear()
    bm25_index._get_bm25_index.cache_clear()


def _write_corpus(path, records):
    path.write_text(json.dumps(records), encoding="utf-8")


def test_tokenize_lowercases_and_splits_words():
    assert _tokenize("Diabetes Management, Type 2!") == ["diabetes", "management", "type", "2"]


def test_bm25_search_returns_best_matching_doc_first(tmp_path, monkeypatch):
    corpus_path = tmp_path / "rag_corpus.json"
    _write_corpus(corpus_path, [
        {"id": "a::0", "chunk_text": "Low glycemic index foods help manage blood sugar in diabetes.", "source": "a", "condition": "diabetes"},
        {"id": "b::0", "chunk_text": "PCOS patients benefit from a low-carb diet approach.", "source": "b", "condition": "pcos"},
        {"id": "c::0", "chunk_text": "General hydration guidance for all users.", "source": "c", "condition": "general"},
    ])
    monkeypatch.setattr(get_settings(), "rag_corpus_path", str(corpus_path))

    results = bm25_search("diabetes blood sugar management", top_k=2)

    assert len(results) == 2
    assert results[0]["id"] == "a::0"
    assert results[0]["bm25_rank"] == 1
    assert "bm25_score" in results[0]


def test_bm25_search_returns_empty_when_corpus_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "rag_corpus_path", str(tmp_path / "does_not_exist.json"))

    assert bm25_search("anything", top_k=5) == []


def test_bm25_search_returns_empty_for_empty_corpus(tmp_path, monkeypatch):
    corpus_path = tmp_path / "rag_corpus.json"
    _write_corpus(corpus_path, [])
    monkeypatch.setattr(get_settings(), "rag_corpus_path", str(corpus_path))

    assert bm25_search("anything", top_k=5) == []
