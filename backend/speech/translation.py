"""Azure Translator (REST v3) wrapper -- the only file that talks to the
Translator service.

Deterministic machine translation, not an LLM: the point of translating at
the edges is that everything between the edges (guardrails, intent, food
matching, memory extraction, the eval harness) keeps running on English
text exactly as it was built and evaluated. An LLM "just reply in Hindi"
would silently bypass the English-only deterministic safety checks.

Language codes here are Translator's (ISO 639-1 style: "en", "hi", "ml",
"fr"), not the Speech service's BCP-47 locales ("hi-IN"). multilingual.py
converts between them.
"""
import httpx
from pydantic import BaseModel

from backend.config import Settings

_REQUEST_TIMEOUT_SECONDS = 15


class Translation(BaseModel):
    text: str
    language: str            # source language (detected, or the caller's `source`)
    score: float | None = None  # detection confidence when auto-detected, else None


def is_configured(settings: Settings) -> bool:
    return bool(_key(settings) and _region(settings))


def _key(settings: Settings) -> str:
    return settings.azure_translator_key or settings.azure_speech_key


def _region(settings: Settings) -> str:
    return settings.azure_translator_region or settings.azure_speech_region


async def translate_many(
    settings: Settings,
    texts: list[str],
    *,
    to: str,
    source: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[Translation]:
    """Translate several strings in one request (Translator accepts a batch).

    `source=None` lets the service detect the language; the detected code
    and its confidence come back on each result. Raises httpx errors on
    failure -- callers decide how to fail (multilingual.py fails open to
    English).
    """
    if not texts:
        return []
    params: dict[str, str] = {"api-version": "3.0", "to": to}
    if source:
        params["from"] = source
    headers = {
        "Ocp-Apim-Subscription-Key": _key(settings),
        "Ocp-Apim-Subscription-Region": _region(settings),
        "Content-Type": "application/json",
    }
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)
    try:
        response = await client.post(
            f"{settings.azure_translator_endpoint.rstrip('/')}/translate",
            params=params,
            headers=headers,
            json=[{"text": t} for t in texts],
        )
        response.raise_for_status()
        payload = response.json()
    finally:
        if owns_client:
            await client.aclose()

    results: list[Translation] = []
    for item in payload:
        detected = item.get("detectedLanguage") or {}
        results.append(
            Translation(
                text=item["translations"][0]["text"],
                language=source or detected.get("language") or to,
                score=detected.get("score"),
            )
        )
    return results


async def translate(
    settings: Settings,
    text: str,
    *,
    to: str,
    source: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> Translation:
    return (await translate_many(settings, [text], to=to, source=source, client=client))[0]
