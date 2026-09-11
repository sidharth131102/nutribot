"""Custom LLM wrapper for DeepEval (Phase 6).

DeepEval defaults to calling OpenAI directly for its LLM-judge metrics --
this file exists specifically so it doesn't: every metric call routes
through the existing LLMProvider abstraction (get_provider()) instead,
keeping invariant 6 intact (generation stays behind one provider interface)
and avoiding a stray non-Azure API key requirement.

Confined entirely to backend/eval/ -- nothing in backend/agents/ or
backend/guardrails/ imports deepeval or this file.
"""
import asyncio

from deepeval.models.base_model import DeepEvalBaseLLM

from backend.config import get_settings
from backend.llm.base import GenerationConfig, Message
from backend.llm.factory import get_provider


class NutriBotDeepEvalLLM(DeepEvalBaseLLM):
    def load_model(self) -> "NutriBotDeepEvalLLM":
        return self

    async def a_generate(self, prompt: str) -> str:
        # profile="full" (not "fast"): DeepEval's internal prompts (truths/
        # claims extraction, GEval reasoning steps) are longer and more
        # complex than a quick classification -- "fast"'s tighter reasoning
        # budget was observed to silently return empty/truncated text here,
        # the same reasoning-token-overhead failure mode hit repeatedly
        # elsewhere in this codebase with small max_tokens on a reasoning model.
        result = await get_provider().generate(
            messages=[Message(role="user", content=prompt)],
            config=GenerationConfig(profile="full", temperature=0, max_tokens=4096),
        )
        return result.text

    def generate(self, prompt: str) -> str:
        # Required by the DeepEvalBaseLLM ABC but never exercised by this
        # harness: runner.py already runs inside asyncio.run(), and every
        # metric call in scorers/deepeval_scorer.py uses a_measure() (async),
        # never the sync .measure() path that would reach this method.
        return asyncio.run(self.a_generate(prompt))

    def get_model_name(self) -> str:
        return f"nutribot-{get_settings().llm_provider}"
