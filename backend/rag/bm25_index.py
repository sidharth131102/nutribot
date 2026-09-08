"""In-process BM25 keyword search over the local RAG corpus (Phase 5: RAG 2.0).

Fused with Pinecone's dense-vector search in retriever.py for hybrid
retrieval. Loads data/rag_corpus.json (written by rag/ingest.py) and builds
the BM25 index once per warm serverless instance, cached the same way
utils/food_filter.py::_load_food_db() caches food_db.json -- fine at the
confirmed ≤~50-document scale this app targets.
"""
import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from backend.config import get_settings

logger = logging.getLogger("nutribot.rag.bm25")

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


@lru_cache(maxsize=1)
def _load_corpus() -> list[dict[str, Any]]:
    path = Path(get_settings().rag_corpus_path)
    if not path.exists():
        logger.warning("BM25 corpus file not found at %s -- hybrid search degrades to dense-only", path)
        return []
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def _get_bm25_index() -> tuple[BM25Okapi | None, list[dict[str, Any]]]:
    corpus = _load_corpus()
    if not corpus:
        return None, []
    tokenized = [_tokenize(c["chunk_text"]) for c in corpus]
    return BM25Okapi(tokenized), corpus


def bm25_search(query: str, top_k: int) -> list[dict[str, Any]]:
    """Returns the top-k corpus records for query, each annotated with
    bm25_score/bm25_rank, sorted best-first. Fails open ([]) if the corpus
    is missing or empty rather than raising."""
    bm25, corpus = _get_bm25_index()
    if bm25 is None:
        return []

    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(range(len(corpus)), key=lambda i: scores[i], reverse=True)[:top_k]

    results = []
    for rank, idx in enumerate(ranked, start=1):
        record = {**corpus[idx], "bm25_score": float(scores[idx]), "bm25_rank": rank}
        results.append(record)
    return results
