"""PDF ingestion pipeline: parse → chunk → upsert into Pinecone (integrated embeddings).

Also writes data/rag_corpus.json, a local copy of every chunk used by
backend/rag/bm25_index.py for in-process keyword search (Phase 5: RAG 2.0).
Pinecone and rag_corpus.json must be built from the same run to stay in
sync -- ingest_pdfs() does both together. Adding a new PDF always requires
re-running full ingest_pdfs(), not just rebuild_corpus_only(), or the two
will silently drift apart (chunks rankable by BM25 but never returned by
Pinecone, or vice versa).
"""
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from backend.config import get_settings
from backend.db.vector_store import NAMESPACE, get_index

logger = logging.getLogger("nutribot.rag.ingest")

PDF_METADATA: dict[str, dict[str, str]] = {
    "diabetes_guidelines": {"condition": "diabetes", "type": "medical"},
    "pcos_nutrition": {"condition": "pcos", "type": "medical"},
    "thyroid_diet": {"condition": "thyroid", "type": "medical"},
    "hypertension_diet": {"condition": "hypertension", "type": "medical"},
    "indian_diet_guidelines": {"condition": "general", "type": "dietary"},
    "protein_requirements": {"condition": "general", "type": "macro"},
}


def _metadata_for(path: Path) -> dict[str, str]:
    stem = path.stem.lower()
    for key, meta in PDF_METADATA.items():
        if key in stem:
            return {**meta, "source": stem}
    # Fallback: try to infer condition from filename
    for cond in ("diabetes", "pcos", "thyroid", "hypertension", "kidney"):
        if cond in stem:
            return {"condition": cond, "type": "medical", "source": stem}
    return {"condition": "general", "type": "dietary", "source": stem}


def _load_pdf_pages(pdf_path: Path) -> list[str]:
    """Extract text from PDF using pdfplumber (preferred) with pypdf fallback."""
    texts: list[str] = []
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                if text.strip():
                    texts.append(text)
        return texts
    except Exception as exc:
        logger.warning("pdfplumber failed for %s (%s), trying pypdf", pdf_path.name, exc)

    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                texts.append(text)
    except Exception as exc2:
        logger.error("pypdf also failed for %s: %s", pdf_path.name, exc2)
    return texts


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks by approximate token count (chars/4)."""
    char_size = chunk_size * 4
    char_overlap = overlap * 4
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + char_size
        chunks.append(text[start:end].strip())
        start += char_size - char_overlap
    return [c for c in chunks if len(c) > 50]


def _build_all_chunks(pdf_files: list[Path], settings: Any) -> list[dict[str, Any]]:
    """Parse + chunk every PDF into the flat corpus record list. No Pinecone
    calls here -- shared by ingest_pdfs() (which also upserts) and
    rebuild_corpus_only() (which doesn't), so both stay built the same way."""
    all_records: list[dict[str, Any]] = []

    for pdf_path in pdf_files:
        logger.info("Processing %s …", pdf_path.name)
        meta = _metadata_for(pdf_path)
        pages = _load_pdf_pages(pdf_path)
        full_text = "\n".join(pages)

        chunks = _chunk_text(full_text, settings.rag_chunk_size, settings.rag_chunk_overlap)
        if not chunks:
            logger.warning("No extractable text in %s", pdf_path.name)
            continue

        for idx, chunk in enumerate(chunks):
            all_records.append({
                "id": f"{meta['source']}::{idx}",
                "chunk_text": chunk,
                **meta,
                "chunk_index": idx,
                "pdf_name": pdf_path.name,
            })

        logger.info("  → %d chunks from %s", len(chunks), pdf_path.name)

    return all_records


def _write_corpus(records: list[dict[str, Any]], settings: Any) -> None:
    path = Path(settings.rag_corpus_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=2)
    logger.info("Wrote %d chunk records to %s", len(records), path)


def ingest_pdfs(source_dir: str | None = None) -> int:
    """Parse all PDFs, chunk, upsert into Pinecone, and write the local BM25
    corpus file (data/rag_corpus.json) -- both together, same run, so they
    never drift out of sync.

    Uses the target index's integrated embedding model (configured on the
    index itself) — no local embedding model or API key needed here.

    Returns the total number of chunks ingested.
    """
    settings = get_settings()
    root = Path(source_dir or settings.pdf_source_dir)
    pdf_files = sorted(root.glob("*.pdf"))

    if not pdf_files:
        logger.warning("No PDF files found in %s", root)
        return 0

    records = _build_all_chunks(pdf_files, settings)
    if not records:
        return 0

    index = get_index()
    # Upsert in batches of 50 (records are embedded server-side by Pinecone)
    batch_size = 50
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        pinecone_records: list[dict[str, Any]] = [
            {
                "_id": str(uuid.uuid4()),
                "chunk_text": r["chunk_text"],
                "condition": r["condition"],
                "type": r["type"],
                "source": r["source"],
                "chunk_index": r["chunk_index"],
                "pdf_name": r["pdf_name"],
            }
            for r in batch
        ]
        index.upsert_records(records=pinecone_records, namespace=NAMESPACE)

    _write_corpus(records, settings)
    logger.info("Ingestion complete. Total chunks: %d", len(records))
    return len(records)


def rebuild_corpus_only(source_dir: str | None = None) -> int:
    """Rebuild data/rag_corpus.json from the PDFs without touching Pinecone.

    Use only when Pinecone already holds correct, matching data and just the
    local BM25 corpus needs regenerating -- e.g. RAG 2.0's initial rollout
    against PDFs already ingested under the pre-hybrid pipeline. Any *new*
    PDF must go through ingest_pdfs() instead, or Pinecone and the corpus
    file will silently disagree about what's in the knowledge base.
    """
    settings = get_settings()
    root = Path(source_dir or settings.pdf_source_dir)
    pdf_files = sorted(root.glob("*.pdf"))

    if not pdf_files:
        logger.warning("No PDF files found in %s", root)
        return 0

    records = _build_all_chunks(pdf_files, settings)
    _write_corpus(records, settings)
    logger.info("Corpus rebuild complete (Pinecone untouched). Total chunks: %d", len(records))
    return len(records)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ingest_pdfs()
