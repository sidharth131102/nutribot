"""PDF ingestion pipeline: parse → chunk → upsert into Pinecone (integrated embeddings)."""
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


def ingest_pdfs(source_dir: str | None = None) -> int:
    """Parse all PDFs, chunk, and upsert into Pinecone.

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

    index = get_index()
    total_chunks = 0

    for pdf_path in pdf_files:
        logger.info("Ingesting %s …", pdf_path.name)
        meta = _metadata_for(pdf_path)
        pages = _load_pdf_pages(pdf_path)
        full_text = "\n".join(pages)

        chunks = _chunk_text(full_text, settings.rag_chunk_size, settings.rag_chunk_overlap)
        if not chunks:
            logger.warning("No extractable text in %s", pdf_path.name)
            continue

        # Upsert in batches of 50 (records are embedded server-side by Pinecone)
        batch_size = 50
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            records: list[dict[str, Any]] = [
                {
                    "_id": str(uuid.uuid4()),
                    "chunk_text": chunk,
                    **meta,
                    "chunk_index": i + j,
                    "pdf_name": pdf_path.name,
                }
                for j, chunk in enumerate(batch)
            ]
            index.upsert_records(records=records, namespace=NAMESPACE)
            total_chunks += len(batch)

        logger.info("  → %d chunks from %s", len(chunks), pdf_path.name)

    logger.info("Ingestion complete. Total chunks: %d", total_chunks)
    return total_chunks


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ingest_pdfs()
