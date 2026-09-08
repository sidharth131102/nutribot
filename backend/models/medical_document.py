from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

DocumentStatus = Literal["uploaded", "processing", "processed", "failed"]
DocumentType = Literal["pdf", "image"]


class MedicalDocumentRecord(BaseModel):
    """Mongo shape -- includes blob_path, never returned to a client directly."""
    user_id: str
    filename: str
    content_type: str
    document_type: DocumentType
    blob_path: str
    size_bytes: int
    status: DocumentStatus = "uploaded"
    facts_extracted: int = 0
    error_message: Optional[str] = None
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: Optional[datetime] = None


class MedicalDocumentSummary(BaseModel):
    """API response shape -- deliberately excludes blob_path."""
    id: str
    filename: str
    content_type: str
    status: DocumentStatus
    facts_extracted: int
    error_message: Optional[str] = None
    uploaded_at: datetime
    processed_at: Optional[datetime] = None


class DocumentUploadResponse(BaseModel):
    id: str
    status: DocumentStatus
    facts_extracted: int


class ExtractedMedicalFact(BaseModel):
    """LLM extraction output -- one entry per fact found in a document."""
    fact: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.7)


class DocumentBatchDeleteRequest(BaseModel):
    """Body for deleting a user-selected set of documents (not all of them)."""
    document_ids: list[str]


class DocumentDeleteResponse(BaseModel):
    deleted_count: int
    not_found_ids: list[str] = Field(default_factory=list)
