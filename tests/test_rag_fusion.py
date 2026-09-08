"""Tests for backend/rag/fusion.py -- pure Reciprocal Rank Fusion logic, no I/O."""
from backend.rag.fusion import hydrate_fused_results, reciprocal_rank_fusion


def test_doc_ranked_in_both_lists_outranks_doc_in_only_one():
    dense = ["a", "b", "c"]
    sparse = ["b", "d", "a"]

    fused = reciprocal_rank_fusion([dense, sparse])
    fused_ids = [doc_id for doc_id, _ in fused]

    # "b" is top-2 in both lists, "a" is top-1 dense / bottom sparse,
    # "c"/"d" each appear in only one list -- b should come out on top.
    assert fused_ids[0] == "b"
    assert "c" in fused_ids and "d" in fused_ids


def test_one_empty_list_degrades_to_the_other_lists_order():
    dense = ["x", "y", "z"]
    fused = reciprocal_rank_fusion([dense, []])
    assert [doc_id for doc_id, _ in fused] == ["x", "y", "z"]


def test_both_empty_returns_empty():
    assert reciprocal_rank_fusion([[], []]) == []


def test_scores_are_deterministic_for_identical_input():
    rank_lists = [["a", "b", "c"], ["c", "a", "b"]]
    first = reciprocal_rank_fusion(rank_lists)
    second = reciprocal_rank_fusion(rank_lists)
    assert first == second


def test_hydrate_prefers_corpus_copy_over_pinecone_hit():
    fused_ids = ["doc-1", "doc-2"]
    pinecone_hits_by_id = {
        "doc-1": {"chunk_text": "pinecone version", "source": "s1", "condition": "diabetes"},
        "doc-2": {"chunk_text": "pinecone only", "source": "s2", "condition": "general"},
    }
    corpus_by_id = {
        "doc-1": {"chunk_text": "corpus version", "source": "s1", "condition": "diabetes"},
    }

    hydrated = hydrate_fused_results(fused_ids, pinecone_hits_by_id, corpus_by_id)

    assert hydrated[0]["chunk_text"] == "corpus version"  # corpus preferred
    assert hydrated[1]["chunk_text"] == "pinecone only"   # falls back when not in corpus


def test_hydrate_skips_ids_missing_from_both_sources():
    hydrated = hydrate_fused_results(["ghost-id"], {}, {})
    assert hydrated == []
