"""Translate-at-the-edges: the user may write or speak in any language; the
pipeline only ever sees English; the reply goes back in the user's language.

Per message, not per session -- English, then French, then English again
just works, because each message's language is decided on its own.

What is and isn't translated on the way out:
- the conversational prose and the accept prompt: translated.
- the meal-plan table (food names, grams, calories): kept as rendered.
  Food names come from food_db.json and machine-translating "paneer" or
  "whole wheat roti" produces nonsense; for the Indian languages this
  targets, those are the words people use anyway.
- guardrail canned responses: translated (they're fixed English strings; a
  machine translation of a vetted string is still not LLM-authored text).

Fails open to English at every step: a Translator outage must never turn
into a failed chat turn.
"""
import logging
from typing import Any

from pydantic import BaseModel

from backend.config import Settings
from backend.speech import translation

logger = logging.getLogger("nutribot.speech.multilingual")

ENGLISH = "en"
# A short, all-ASCII message ("ok", "yes please", "hi") is far more likely to
# be English than for the detector to be right about it being something
# else -- language detection on 1-3 words is unreliable in both directions,
# and a wrong non-English guess here would translate the reply into a
# language the user never used. Longer ASCII text (French, Spanish...) is
# still detected normally.
_SHORT_MESSAGE_WORDS = 3
# Below this detection confidence, treat the message as English rather than
# risk replying in the wrong language.
_MIN_DETECTION_SCORE = 0.7


class InboundMessage(BaseModel):
    language: str          # Translator code the reply should be in ("en", "hi", ...)
    english_text: str      # what the pipeline runs on
    original_text: str     # what the user actually sent (stored for display)
    translated: bool       # False = passthrough (English, disabled, or fail-open)


def language_from_locale(locale: str | None) -> str | None:
    """'hi-IN' -> 'hi', 'en-IN' -> 'en', '' / None -> None."""
    if not locale:
        return None
    code = locale.strip().split("-")[0].lower()
    return code or None


def _looks_like_short_english(text: str) -> bool:
    return text.isascii() and len(text.split()) <= _SHORT_MESSAGE_WORDS


def enabled(settings: Settings) -> bool:
    return settings.multilingual_enabled and translation.is_configured(settings)


async def inbound(settings: Settings, text: str, locale_hint: str | None = None) -> InboundMessage:
    """Decide the message's language and get its English form.

    `locale_hint` is the locale the browser's speech recognizer detected
    ("ml-IN"); when present it's authoritative for the source language
    (the recognizer heard it -- better evidence than text detection on a
    short transcript). Typed text is auto-detected.
    """
    passthrough = InboundMessage(language=ENGLISH, english_text=text, original_text=text, translated=False)
    if not text.strip() or not enabled(settings):
        return passthrough

    source = language_from_locale(locale_hint)
    if source == ENGLISH or (source is None and _looks_like_short_english(text)):
        return passthrough

    try:
        result = await translation.translate(settings, text, to=ENGLISH, source=source)
    except Exception:
        logger.exception("Inbound translation failed; treating message as English")
        return passthrough

    if result.language == ENGLISH:
        return passthrough
    if source is None and result.score is not None and result.score < _MIN_DETECTION_SCORE:
        logger.info("Low-confidence language detection (%s, %.2f); treating as English", result.language, result.score)
        return passthrough

    return InboundMessage(language=result.language, english_text=result.text, original_text=text, translated=True)


def _split_response(result: dict[str, Any]) -> tuple[str, str, str] | None:
    """(prose, plan_markdown, accept_prompt) when the response is a plan turn
    whose parts are still current. The meal-plan agent records the parts it
    assembled; a later node (the output guardrail's fallback) may replace
    `response` wholesale without touching them, so only trust the parts if
    they still reassemble into the response verbatim."""
    parts = result.get("response_parts")
    if not parts:
        return None
    prose, plan_md, accept = parts.get("prose", ""), parts.get("plan_markdown", ""), parts.get("accept_prompt", "")
    if f"{prose}\n\n{plan_md}\n\n{accept}" != result.get("response", ""):
        return None
    return prose, plan_md, accept


async def outbound(settings: Settings, result: dict[str, Any], language: str) -> str:
    """The reply in the user's language. English in, English out, unchanged."""
    response = result.get("response", "") or ""
    if language == ENGLISH or not response.strip() or not enabled(settings):
        return response

    try:
        parts = _split_response(result)
        if parts:
            prose, plan_md, accept = parts
            translated = await translation.translate_many(settings, [prose, accept], to=language, source=ENGLISH)
            return f"{translated[0].text}\n\n{plan_md}\n\n{translated[1].text}"
        return (await translation.translate(settings, response, to=language, source=ENGLISH)).text
    except Exception:
        logger.exception("Outbound translation to %s failed; replying in English", language)
        return response
