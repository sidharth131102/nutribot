"""Azure Speech authorization tokens -- the only file that talks to the
Speech service's token endpoint.

The browser runs speech recognition itself with the Speech SDK, but it must
never hold the subscription key. It asks this backend for a 10-minute
authorization token instead (the standard Azure pattern for client-side
recognition). Issuing one is a single POST with the key; nothing else about
the Speech service is touched here.
"""
import httpx
from pydantic import BaseModel

from backend.config import Settings

# Azure tokens are valid for 10 minutes; tell the client a little less so it
# refreshes before the service would reject the token mid-recognition.
TOKEN_LIFETIME_SECONDS = 540
_REQUEST_TIMEOUT_SECONDS = 10


class SpeechToken(BaseModel):
    token: str
    region: str
    expires_in_seconds: int = TOKEN_LIFETIME_SECONDS


def is_configured(settings: Settings) -> bool:
    return bool(settings.azure_speech_key and settings.azure_speech_region)


def token_url(region: str) -> str:
    return f"https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"


async def issue_token(settings: Settings, client: httpx.AsyncClient | None = None) -> SpeechToken:
    """Exchange the subscription key for a short-lived authorization token.

    Raises httpx.HTTPStatusError on a non-2xx (bad key, wrong region) so the
    endpoint can turn it into a clear 502 rather than handing the browser a
    token that isn't one.
    """
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)
    try:
        response = await client.post(
            token_url(settings.azure_speech_region),
            headers={
                "Ocp-Apim-Subscription-Key": settings.azure_speech_key,
                "Content-Length": "0",
            },
        )
        response.raise_for_status()
        return SpeechToken(token=response.text.strip(), region=settings.azure_speech_region)
    finally:
        if owns_client:
            await client.aclose()


def recognition_languages(settings: Settings) -> list[str]:
    return [lang.strip() for lang in settings.speech_recognition_languages.split(",") if lang.strip()]
