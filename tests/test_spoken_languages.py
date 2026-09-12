"""Per-user "languages I speak" (backend/speech/locales.py + the profile
models). The 4-locale / one-variant-per-language rules come from Azure
Speech's at-start language identification and are enforced here so the
client can't push a list the recognizer would reject."""
import pytest
from pydantic import ValidationError

from backend.config import Settings
from backend.models.user import ProfileCreateRequest, ProfileUpdateRequest
from backend.speech.locales import (
    MAX_SPOKEN_LANGUAGES,
    SUPPORTED_SPOKEN_LOCALES,
    default_spoken_languages,
    languages_for_user,
    validate_spoken_languages,
)


def test_validate_normalises_and_dedupes():
    assert validate_spoken_languages([" hi-IN ", "ta-IN", "hi-IN", ""]) == ["hi-IN", "ta-IN"]


def test_validate_rejects_unknown_locale():
    with pytest.raises(ValueError, match="Unsupported spoken language 'xx-YY'"):
        validate_spoken_languages(["xx-YY"])


def test_validate_rejects_two_variants_of_one_language():
    with pytest.raises(ValueError, match="one variant per language"):
        validate_spoken_languages(["en-IN", "en-US"])


def test_validate_rejects_more_than_max():
    codes = list(SUPPORTED_SPOKEN_LOCALES)[: MAX_SPOKEN_LANGUAGES + 1]
    # Make sure the sample doesn't trip the one-per-language rule first.
    codes = ["hi-IN", "ta-IN", "te-IN", "kn-IN", "ml-IN"]
    with pytest.raises(ValueError, match=f"at most {MAX_SPOKEN_LANGUAGES}"):
        validate_spoken_languages(codes)


def test_empty_list_is_allowed_and_means_server_default():
    assert validate_spoken_languages([]) == []
    settings = Settings(_env_file=None, speech_recognition_languages="en-IN,hi-IN")
    assert languages_for_user(settings, {"spoken_languages": []}) == ["en-IN", "hi-IN"]
    assert languages_for_user(settings, None) == ["en-IN", "hi-IN"]
    assert default_spoken_languages(settings) == ["en-IN", "hi-IN"]


def test_user_list_overrides_server_default():
    settings = Settings(_env_file=None, speech_recognition_languages="en-IN,hi-IN")
    assert languages_for_user(settings, {"spoken_languages": ["ta-IN"]}) == ["ta-IN"]


def _create_payload(**overrides):
    base = dict(
        full_name="Asha", gender="female", age=29, height_cm=162, weight_kg=58,
        activity_level="moderately_active", diet_type="vegetarian", goal="maintenance",
    )
    base.update(overrides)
    return base


def test_profile_create_accepts_valid_list_and_defaults_to_empty():
    assert ProfileCreateRequest(**_create_payload()).spoken_languages == []
    req = ProfileCreateRequest(**_create_payload(spoken_languages=["ml-IN", "en-IN"]))
    assert req.spoken_languages == ["ml-IN", "en-IN"]


def test_profile_create_rejects_invalid_list_with_the_user_facing_message():
    with pytest.raises(ValidationError, match="Unsupported spoken language"):
        ProfileCreateRequest(**_create_payload(spoken_languages=["klingon"]))


def test_profile_update_leaves_none_alone_and_validates_when_given():
    assert ProfileUpdateRequest().spoken_languages is None
    assert ProfileUpdateRequest(spoken_languages=[]).spoken_languages == []
    assert ProfileUpdateRequest(spoken_languages=["fr-FR"]).spoken_languages == ["fr-FR"]
    with pytest.raises(ValidationError, match="one variant per language"):
        ProfileUpdateRequest(spoken_languages=["en-GB", "en-US"])
