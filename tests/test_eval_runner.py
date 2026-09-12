"""Tests for the non-network control flow in backend/eval/runner.py --
the challenger reachability probe and the compare-mode arm swap/restore
(Phase 7). Everything that would hit an LLM is monkeypatched out."""
import pytest

from backend.config import get_settings
from backend.eval import runner
from backend.llm.base import GenerationResult
# The factory's real cached function: tests monkeypatch `runner.get_provider`
# to plain lambdas, and monkeypatch only undoes that AFTER this fixture's
# teardown runs -- so clearing via the runner attribute would hit a lambda
# with no .cache_clear(). Always clear the real thing.
from backend.llm.factory import get_provider as _real_get_provider


class _FakeProvider:
    def __init__(self, fail: bool = False):
        self.fail = fail

    async def generate(self, messages, config):
        if self.fail:
            raise ConnectionError("DeploymentNotFound")
        return GenerationResult(text="pong", model="m", provider="p")


@pytest.fixture(autouse=True)
def _restore_provider_and_cache(monkeypatch):
    _real_get_provider.cache_clear()
    monkeypatch.setattr(get_settings(), "llm_provider", "azure_openai")
    monkeypatch.setattr(get_settings(), "azure_openai_challenger_deployment_full", "gpt-4-1")
    yield
    _real_get_provider.cache_clear()


# ── _probe_challenger ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_probe_raises_clear_error_naming_deployment_when_unreachable(monkeypatch):
    monkeypatch.setattr(runner, "get_provider", lambda name=None: _FakeProvider(fail=True))

    with pytest.raises(RuntimeError) as excinfo:
        await runner._probe_challenger()

    message = str(excinfo.value)
    assert "not reachable" in message
    assert "gpt-4-1" in message
    assert "DeploymentNotFound" in message


@pytest.mark.asyncio
async def test_probe_passes_when_challenger_answers(monkeypatch):
    monkeypatch.setattr(runner, "get_provider", lambda name=None: _FakeProvider())

    await runner._probe_challenger()  # no raise


# ── _run_compare arm swap / restore ──────────────────────────────────────

@pytest.mark.asyncio
async def test_run_compare_swaps_arms_in_order_and_restores_provider(monkeypatch):
    seen_providers: list[str] = []

    async def _fake_run_all():
        seen_providers.append(get_settings().llm_provider)
        return []

    async def _fake_probe():
        return None

    monkeypatch.setattr(runner, "_run_all", _fake_run_all)
    monkeypatch.setattr(runner, "_probe_challenger", _fake_probe)
    monkeypatch.setattr(runner, "INTER_CASE_DELAY_SECONDS", 0)

    results = await runner._run_compare()

    assert seen_providers == [runner.PRIMARY_ARM, runner.CHALLENGER_ARM]
    assert set(results) == {runner.PRIMARY_ARM, runner.CHALLENGER_ARM}
    assert get_settings().llm_provider == "azure_openai"


@pytest.mark.asyncio
async def test_run_compare_restores_provider_even_if_an_arm_fails(monkeypatch):
    async def _failing_run_all():
        raise RuntimeError("arm exploded")

    async def _fake_probe():
        return None

    monkeypatch.setattr(runner, "_run_all", _failing_run_all)
    monkeypatch.setattr(runner, "_probe_challenger", _fake_probe)
    monkeypatch.setattr(runner, "INTER_CASE_DELAY_SECONDS", 0)

    with pytest.raises(RuntimeError, match="arm exploded"):
        await runner._run_compare()

    assert get_settings().llm_provider == "azure_openai"


@pytest.mark.asyncio
async def test_run_compare_aborts_before_any_arm_if_probe_fails(monkeypatch):
    calls: list[str] = []

    async def _fake_run_all():
        calls.append("ran")
        return []

    async def _failing_probe():
        raise RuntimeError("not reachable")

    monkeypatch.setattr(runner, "_run_all", _fake_run_all)
    monkeypatch.setattr(runner, "_probe_challenger", _failing_probe)

    with pytest.raises(RuntimeError, match="not reachable"):
        await runner._run_compare()

    assert calls == []
    assert get_settings().llm_provider == "azure_openai"
