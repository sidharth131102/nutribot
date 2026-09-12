"""backend/speech/translation.py and token.py against a fake Azure (httpx
MockTransport). No network, no credentials."""
import json

import httpx
import pytest

from backend.config import Settings
from backend.speech import token as speech_token
from backend.speech import translation


def _settings(**overrides) -> Settings:
    base = {
        "_env_file": None,
        "azure_speech_key": "speech-key",
        "azure_speech_region": "centralindia",
    }
    base.update(overrides)
    return Settings(**base)


# ── translation ─────────────────────────────────────────────────────────────

def _translator_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_translate_auto_detects_and_returns_detected_language():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=[{
            "detectedLanguage": {"language": "hi", "score": 0.98},
            "translations": [{"text": "Give me a meal plan", "to": "en"}],
        }])

    async with _translator_client(handler) as client:
        result = await translation.translate(_settings(), "मुझे एक मील प्लान दो", to="en", client=client)

    assert result.text == "Give me a meal plan"
    assert result.language == "hi"
    assert result.score == pytest.approx(0.98)
    assert "api-version=3.0" in seen["url"] and "to=en" in seen["url"] and "from=" not in seen["url"]
    assert seen["headers"]["ocp-apim-subscription-key"] == "speech-key"      # falls back to the speech key
    assert seen["headers"]["ocp-apim-subscription-region"] == "centralindia"  # and region
    assert seen["body"] == [{"text": "मुझे एक मील प्लान दो"}]


@pytest.mark.asyncio
async def test_translate_many_with_explicit_source_batches_in_one_request():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        assert "from=en" in str(request.url) and "to=fr" in str(request.url)
        return httpx.Response(200, json=[
            {"translations": [{"text": "Bonjour", "to": "fr"}]},
            {"translations": [{"text": "Au revoir", "to": "fr"}]},
        ])

    async with _translator_client(handler) as client:
        results = await translation.translate_many(_settings(), ["Hello", "Goodbye"], to="fr", source="en", client=client)

    assert len(calls) == 1
    assert [r.text for r in results] == ["Bonjour", "Au revoir"]
    assert all(r.language == "en" and r.score is None for r in results)


@pytest.mark.asyncio
async def test_translate_many_empty_input_makes_no_request():
    def handler(request):
        raise AssertionError("should not be called")

    async with _translator_client(handler) as client:
        assert await translation.translate_many(_settings(), [], to="en", client=client) == []


@pytest.mark.asyncio
async def test_translate_raises_on_http_error():
    def handler(request):
        return httpx.Response(401, json={"error": {"code": "401000", "message": "bad key"}})

    async with _translator_client(handler) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await translation.translate(_settings(), "hola", to="en", client=client)


def test_translator_key_and_region_override_speech_ones():
    s = _settings(azure_translator_key="t-key", azure_translator_region="westeurope")
    assert translation._key(s) == "t-key"
    assert translation._region(s) == "westeurope"
    assert translation.is_configured(s)
    assert not translation.is_configured(Settings(_env_file=None))


# ── speech token ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_issue_token_posts_key_to_regional_sts_endpoint():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("ocp-apim-subscription-key")
        return httpx.Response(200, text="eyJ.token.value")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        issued = await speech_token.issue_token(_settings(), client=client)

    assert seen["url"] == "https://centralindia.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    assert seen["key"] == "speech-key"
    assert issued.token == "eyJ.token.value"
    assert issued.region == "centralindia"
    assert issued.expires_in_seconds == speech_token.TOKEN_LIFETIME_SECONDS


@pytest.mark.asyncio
async def test_issue_token_raises_on_bad_key():
    def handler(request):
        return httpx.Response(401, text="Access denied")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await speech_token.issue_token(_settings(), client=client)


def test_recognition_languages_parses_and_trims():
    s = _settings(speech_recognition_languages=" en-IN, hi-IN ,ml-IN,,fr-FR ")
    assert speech_token.recognition_languages(s) == ["en-IN", "hi-IN", "ml-IN", "fr-FR"]


def test_speech_not_configured_without_key_and_region():
    assert not speech_token.is_configured(Settings(_env_file=None))
    assert not speech_token.is_configured(_settings(azure_speech_region=""))
    assert speech_token.is_configured(_settings())
