"""Upload validation for medical documents. Pure function, no FastAPI/Azure
imports -- kept separate so it's testable without either.

No magic-byte sniffing: this app never executes or renders the uploaded file,
it only OCRs it (Document Intelligence) and stores the bytes (Blob Storage).
Extension + content-type checks exist to fail fast with a clear error before
spending an upload + OCR call on an obviously wrong file, not as a security
boundary -- sniffing would add a native libmagic dependency for a threat model
(a user mislabeling their own file) that doesn't apply here.
"""
import os

ALLOWED_CONTENT_TYPES = {"application/pdf", "image/jpeg", "image/png"}
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def validate_upload(filename: str, content_type: str, size_bytes: int) -> None:
    """Raises ValueError with a user-facing message if the upload is rejected."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type '{ext}'. Allowed: PDF, JPG, PNG.")
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError(f"Unsupported content type '{content_type}'. Allowed: PDF, JPG, PNG.")
    if size_bytes <= 0:
        raise ValueError("Uploaded file is empty.")
    if size_bytes > MAX_UPLOAD_SIZE_BYTES:
        raise ValueError(f"File too large ({size_bytes} bytes). Max {MAX_UPLOAD_SIZE_BYTES} bytes.")


def document_type_for(content_type: str) -> str:
    """'pdf' | 'image' -- used to populate MedicalDocumentRecord.document_type."""
    return "pdf" if content_type == "application/pdf" else "image"
