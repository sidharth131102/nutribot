"""Spoken-language locales a user may pick for voice input.

Azure Speech's at-start language identification weighs at most 4 candidate
locales per utterance and rejects two locales of the same language (en-IN
with en-US), so the per-user list is validated to those rules here -- once,
on the backend -- rather than trusted from the client. The frontend keeps a
copy of the labels for its chip selector; the codes are the contract.
"""
from backend.config import Settings

MAX_SPOKEN_LANGUAGES = 4

# code -> label. Curated, not exhaustive: Indian languages first (the
# product's primary audience), then widely spoken others. Extend freely;
# any locale Azure Speech supports is valid here.
SUPPORTED_SPOKEN_LOCALES: dict[str, str] = {
    "en-IN": "English (India)",
    "en-US": "English (US)",
    "en-GB": "English (UK)",
    "hi-IN": "Hindi",
    "ml-IN": "Malayalam",
    "ta-IN": "Tamil",
    "te-IN": "Telugu",
    "kn-IN": "Kannada",
    "mr-IN": "Marathi",
    "bn-IN": "Bengali",
    "gu-IN": "Gujarati",
    "pa-IN": "Punjabi",
    "ur-IN": "Urdu",
    "fr-FR": "French",
    "es-ES": "Spanish",
    "de-DE": "German",
    "it-IT": "Italian",
    "pt-BR": "Portuguese (Brazil)",
    "ar-SA": "Arabic",
    "zh-CN": "Chinese (Mandarin)",
    "ja-JP": "Japanese",
    "ko-KR": "Korean",
    "ru-RU": "Russian",
    "nl-NL": "Dutch",
    "tr-TR": "Turkish",
    "id-ID": "Indonesian",
    "vi-VN": "Vietnamese",
    "th-TH": "Thai",
}


def validate_spoken_languages(codes: list[str]) -> list[str]:
    """Normalise and validate a user's list. Raises ValueError with a
    user-facing message on any violation; returns the cleaned list."""
    cleaned: list[str] = []
    seen_languages: set[str] = set()
    for raw in codes:
        code = (raw or "").strip()
        if not code:
            continue
        if code not in SUPPORTED_SPOKEN_LOCALES:
            raise ValueError(f"Unsupported spoken language '{code}'.")
        if code in cleaned:
            continue
        base = code.split("-")[0].lower()
        if base in seen_languages:
            raise ValueError(
                f"Only one variant per language can be selected (you chose two kinds of '{base}')."
            )
        seen_languages.add(base)
        cleaned.append(code)
    if len(cleaned) > MAX_SPOKEN_LANGUAGES:
        raise ValueError(f"Choose at most {MAX_SPOKEN_LANGUAGES} spoken languages.")
    return cleaned


def default_spoken_languages(settings: Settings) -> list[str]:
    return [c.strip() for c in settings.speech_recognition_languages.split(",") if c.strip()]


def languages_for_user(settings: Settings, user: dict | None) -> list[str]:
    """The user's own list when they've set one, else the server default."""
    chosen = (user or {}).get("spoken_languages") or []
    return list(chosen) if chosen else default_spoken_languages(settings)
