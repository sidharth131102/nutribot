from pydantic import BaseModel, Field


class SpeechTokenResponse(BaseModel):
    token: str
    region: str
    expires_in_seconds: int
    # Candidate locales for the browser's auto language detection (BCP-47):
    # the user's own "languages I speak" list, or the server default.
    languages: list[str] = Field(default_factory=list)


class SpokenLocale(BaseModel):
    code: str
    label: str


class SpokenLanguagesResponse(BaseModel):
    supported: list[SpokenLocale]
    default: list[str]
    max_selectable: int
