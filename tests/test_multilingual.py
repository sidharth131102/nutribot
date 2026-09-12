"""backend/speech/multilingual.py -- translate-at-the-edges orchestration,
with the Translator calls faked. Proves: per-message language decisions,
the English/short-message/low-confidence passthroughs, fail-open on
errors, and that a plan turn's table is never translated."""
import pytest

from backend.config import Settings
from backend.speech import multilingual
from backend.speech.translation import Translation


def _settings(**overrides) -> Settings:
    base = {"_env_file": None, "azure_speech_key": "k", "azure_speech_region": "centralindia"}
    base.update(overrides)
    return Settings(**base)


class FakeTranslator:
    """Scripted Translator: records calls, returns canned results."""

    def __init__(self, detected="hi", score=0.95, fail=False):
        self.detected, self.score, self.fail = detected, score, fail
        self.calls: list[dict] = []

    async def translate_many(self, settings, texts, *, to, source=None, client=None):
        self.calls.append({"texts": list(texts), "to": to, "source": source})
        if self.fail:
            raise RuntimeError("translator down")
        out = []
        for t in texts:
            lang = source or self.detected
            out.append(Translation(text=f"[{to}] {t}", language=lang, score=None if source else self.score))
        return out

    async def translate(self, settings, text, *, to, source=None, client=None):
        return (await self.translate_many(settings, [text], to=to, source=source, client=client))[0]


@pytest.fixture
def fake(monkeypatch):
    def _install(**kwargs):
        f = FakeTranslator(**kwargs)
        monkeypatch.setattr(multilingual.translation, "translate", f.translate)
        monkeypatch.setattr(multilingual.translation, "translate_many", f.translate_many)
        return f
    return _install


# ── inbound ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_typed_hindi_is_detected_and_translated(fake):
    f = fake(detected="hi")
    msg = await multilingual.inbound(_settings(), "मुझे सात दिन का मील प्लान चाहिए")
    assert msg.language == "hi"
    assert msg.translated is True
    assert msg.english_text == "[en] मुझे सात दिन का मील प्लान चाहिए"
    assert msg.original_text == "मुझे सात दिन का मील प्लान चाहिए"
    assert f.calls[0]["source"] is None  # auto-detect for typed text


@pytest.mark.asyncio
async def test_speech_locale_hint_is_authoritative_for_source(fake):
    f = fake(detected="ignored")
    msg = await multilingual.inbound(_settings(), "enikku oru meal plan venam", locale_hint="ml-IN")
    assert msg.language == "ml"
    assert f.calls[0]["source"] == "ml"


@pytest.mark.asyncio
async def test_english_locale_hint_skips_translation(fake):
    f = fake()
    msg = await multilingual.inbound(_settings(), "Give me a plan", locale_hint="en-IN")
    assert msg.language == "en" and msg.translated is False
    assert f.calls == []


@pytest.mark.asyncio
async def test_short_ascii_message_is_assumed_english_without_a_call(fake):
    f = fake(detected="it")  # detector would have said Italian
    for text in ("ok", "yes please", "hi"):
        msg = await multilingual.inbound(_settings(), text)
        assert msg.language == "en" and msg.translated is False
    assert f.calls == []


@pytest.mark.asyncio
async def test_longer_ascii_text_is_still_detected(fake):
    fake(detected="fr")
    msg = await multilingual.inbound(_settings(), "Je voudrais un plan de repas pour la semaine")
    assert msg.language == "fr" and msg.translated is True


@pytest.mark.asyncio
async def test_detected_english_is_passthrough_with_original_text(fake):
    fake(detected="en")
    msg = await multilingual.inbound(_settings(), "What is a good breakfast for diabetes?")
    assert msg.language == "en" and msg.translated is False
    assert msg.english_text == "What is a good breakfast for diabetes?"  # not the "[en] ..." echo


@pytest.mark.asyncio
async def test_low_confidence_detection_falls_back_to_english(fake):
    fake(detected="pt", score=0.4)
    msg = await multilingual.inbound(_settings(), "Something ambiguous and longer than three words")
    assert msg.language == "en" and msg.translated is False


@pytest.mark.asyncio
async def test_inbound_fails_open_to_english_when_translator_errors(fake):
    fake(fail=True)
    msg = await multilingual.inbound(_settings(), "मुझे एक मील प्लान दो")
    assert msg.language == "en" and msg.translated is False
    assert msg.english_text == "मुझे एक मील प्लान दो"


@pytest.mark.asyncio
async def test_inbound_is_passthrough_when_disabled_or_unconfigured(fake):
    f = fake()
    assert (await multilingual.inbound(_settings(multilingual_enabled=False), "मुझे")).translated is False
    assert (await multilingual.inbound(Settings(_env_file=None), "मुझे")).translated is False
    assert f.calls == []


def test_language_from_locale():
    assert multilingual.language_from_locale("hi-IN") == "hi"
    assert multilingual.language_from_locale("en-US") == "en"
    assert multilingual.language_from_locale("fr") == "fr"
    assert multilingual.language_from_locale("") is None
    assert multilingual.language_from_locale(None) is None


# ── outbound ────────────────────────────────────────────────────────────────

PLAN_MD = "**Day 1** — 2000 kcal\n- Breakfast (400 kcal): oats 80g, low-fat milk 250g"


def _plan_result(prose="Asha, here is your week.", accept="Would you like to accept this plan?"):
    return {
        "response": f"{prose}\n\n{PLAN_MD}\n\n{accept}",
        "response_parts": {"prose": prose, "plan_markdown": PLAN_MD, "accept_prompt": accept},
    }


@pytest.mark.asyncio
async def test_english_reply_is_returned_untouched(fake):
    f = fake()
    result = _plan_result()
    assert await multilingual.outbound(_settings(), result, "en") == result["response"]
    assert f.calls == []


@pytest.mark.asyncio
async def test_plan_turn_translates_prose_and_accept_but_keeps_the_table(fake):
    f = fake()
    out = await multilingual.outbound(_settings(), _plan_result(), "hi")
    assert out == f"[hi] Asha, here is your week.\n\n{PLAN_MD}\n\n[hi] Would you like to accept this plan?"
    assert len(f.calls) == 1  # one batched request
    assert f.calls[0] == {"texts": ["Asha, here is your week.", "Would you like to accept this plan?"], "to": "hi", "source": "en"}


@pytest.mark.asyncio
async def test_non_plan_reply_is_translated_whole(fake):
    fake()
    out = await multilingual.outbound(_settings(), {"response": "Protein needs depend on your weight."}, "fr")
    assert out == "[fr] Protein needs depend on your weight."


@pytest.mark.asyncio
async def test_stale_response_parts_are_ignored_after_a_guardrail_fallback(fake):
    """The output guardrail can replace `response` wholesale; the parts the
    meal-plan agent recorded no longer describe it and must not be used."""
    fake()
    result = _plan_result()
    result["response"] = "I wasn't able to put together a safe response."
    out = await multilingual.outbound(_settings(), result, "hi")
    assert out == "[hi] I wasn't able to put together a safe response."


@pytest.mark.asyncio
async def test_outbound_fails_open_to_english(fake):
    fake(fail=True)
    result = _plan_result()
    assert await multilingual.outbound(_settings(), result, "hi") == result["response"]


@pytest.mark.asyncio
async def test_outbound_passthrough_when_disabled(fake):
    f = fake()
    out = await multilingual.outbound(_settings(multilingual_enabled=False), {"response": "Hello"}, "hi")
    assert out == "Hello" and f.calls == []
