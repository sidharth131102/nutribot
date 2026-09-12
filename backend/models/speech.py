from pydantic import BaseModel, Field


class SpeechTokenResponse(BaseModel):
    token: str
    region: str
    expires_in_seconds: int
    # Candidate locales for the browser's auto language detection (BCP-47).
    languages: list[str] = Field(default_factory=list)
