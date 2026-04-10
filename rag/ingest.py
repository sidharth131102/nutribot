from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.config import get_settings


DOCUMENT_METADATA: dict[str, dict[str, str]] = {
    "diabetes_guidelines": {"source": "diabetes_guidelines", "type": "medical", "condition": "diabetes"},
    "pcos_nutrition": {"source": "pcos_nutrition", "type": "medical", "condition": "pcos"},
    "thyroid_diet": {"source": "thyroid_diet", "type": "medical", "condition": "thyroid"},
    "hypertension_diet": {"source": "hypertension_diet", "type": "medical", "condition": "hypertension"},
    "indian_diet_guidelines": {"source": "indian_diet_guidelines", "type": "regional", "condition": "general"},
    "protein_requirements": {"source": "protein_requirements", "type": "macro", "condition": "general"},
}


def metadata_for_pdf(path: Path) -> dict[str, str]:
    base_name = path.stem.lower()
    if base_name in DOCUMENT_METADATA:
        return DOCUMENT_METADATA[base_name]

    condition = "general"
    for candidate in ("diabetes", "pcos", "thyroid", "hypertension", "kidney"):
        if candidate in base_name:
            condition = candidate
            break

    return {"source": base_name, "type": "medical" if condition != "general" else "general", "condition": condition}


def load_pdf_documents(source_dir: str | None = None) -> list[Document]:
    root = Path(source_dir or get_settings().rag_source_dir)
    documents: list[Document] = []
    for pdf_path in sorted(root.glob("*.pdf")):
        loader = PyPDFLoader(str(pdf_path))
        metadata = metadata_for_pdf(pdf_path)
        for document in loader.load():
            document.metadata.update(metadata)
            documents.append(document)
    return documents


def ingest_documents(source_dir: str | None = None, output_path: str | None = None) -> None:
    """Build a FAISS index from PDFs using 300-500 token-ish chunks and strict metadata."""
    settings = get_settings()
    documents = load_pdf_documents(source_dir or settings.rag_source_dir)
    if not documents:
        raise FileNotFoundError(f"No PDFs found in {source_dir or settings.rag_source_dir}")

    splitter = RecursiveCharacterTextSplitter(chunk_size=1800, chunk_overlap=150)
    chunks = splitter.split_documents(documents)
    for chunk in chunks:
        chunk.metadata.setdefault("source", "unknown")
        chunk.metadata.setdefault("type", "general")
        chunk.metadata.setdefault("condition", "general")

    index = FAISS.from_documents(chunks, OpenAIEmbeddings())
    target = Path(output_path or settings.vector_store_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    index.save_local(str(target))


if __name__ == "__main__":
    ingest_documents()
