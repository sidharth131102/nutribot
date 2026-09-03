from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ConsentType = Literal["medical_data_processing"]
ConsentAction = Literal["granted", "revoked"]


class ConsentRecord(BaseModel):
    """One entry in the append-only consent event log -- never mutated, so
    history is preserved (roadmap: consent must be explicit, recorded, revocable)."""

    user_id: str
    consent_type: ConsentType
    action: ConsentAction
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ConsentStatusResponse(BaseModel):
    consent_type: ConsentType
    granted: bool
    last_updated: datetime | None = None
