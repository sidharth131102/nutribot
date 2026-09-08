"""Tests for backend/rag/ingest.py's chunk-building -- pure logic, no real
PDFs or Pinecone calls (_load_pdf_pages is monkeypatched)."""
from pathlib import Path

from backend.config import get_settings
from backend.rag import ingest


def test_build_all_chunks_produces_documented_record_shape(monkeypatch):
    monkeypatch.setattr(
        ingest, "_load_pdf_pages",
        lambda path: ["Diabetes management requires careful monitoring of blood sugar levels. " * 10],
    )
    settings = get_settings()

    records = ingest._build_all_chunks([Path("diabetes_guidelines.pdf")], settings)

    assert len(records) > 0
    first = records[0]
    assert set(first.keys()) == {"id", "chunk_text", "condition", "type", "source", "chunk_index", "pdf_name"}
    assert first["id"] == "diabetes_guidelines::0"
    assert first["source"] == "diabetes_guidelines"
    assert first["condition"] == "diabetes"
    assert first["pdf_name"] == "diabetes_guidelines.pdf"
    assert first["chunk_index"] == 0


def test_build_all_chunks_ids_are_sequential_and_stable(monkeypatch):
    long_text = "Sample clinical guideline text. " * 200  # forces multiple chunks
    monkeypatch.setattr(ingest, "_load_pdf_pages", lambda path: [long_text])
    settings = get_settings()

    records = ingest._build_all_chunks([Path("pcos_nutrition.pdf")], settings)

    assert len(records) > 1
    ids = [r["id"] for r in records]
    assert ids == [f"pcos_nutrition::{i}" for i in range(len(records))]


def test_build_all_chunks_skips_pdfs_with_no_extractable_text(monkeypatch):
    monkeypatch.setattr(ingest, "_load_pdf_pages", lambda path: [])
    settings = get_settings()

    records = ingest._build_all_chunks([Path("empty_scan.pdf")], settings)

    assert records == []


def test_write_and_reload_corpus_round_trip(tmp_path, monkeypatch):
    corpus_path = tmp_path / "rag_corpus.json"
    monkeypatch.setattr(get_settings(), "rag_corpus_path", str(corpus_path))

    records = [{"id": "x::0", "chunk_text": "hello", "source": "x", "condition": "general", "type": "dietary", "chunk_index": 0, "pdf_name": "x.pdf"}]
    ingest._write_corpus(records, get_settings())

    assert corpus_path.exists()
    import json
    reloaded = json.loads(corpus_path.read_text(encoding="utf-8"))
    assert reloaded == records
