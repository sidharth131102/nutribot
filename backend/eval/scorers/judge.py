"""LLM-judge stub for the evaluation harness (v2 roadmap Phase 1b).

Deliberately lightweight — full risk-based judging with retry/repair loops is
Phase 6's job. This gives an informational, non-gating quality signal per case.
"""
import json
import logging
import re

from backend.agents.state import NutriBotState
from backend.eval.models import GoldenCase, JudgeResult
from backend.llm.base import GenerationConfig, Message
from backend.llm.factory import get_provider

logger = logging.getLogger("nutribot.eval.judge")

JUDGE_SYSTEM_PROMPT = """You are an evaluation judge for a nutrition assistant's responses.
Score the ASSISTANT RESPONSE against the USER MESSAGE and CONTEXT on these axes, each 0.0-1.0:
- groundedness: is the response consistent with the provided context (profile, clinical guidelines, approved foods) rather than invented?
- relevance: does it actually address what the user asked?
- completeness: does it fully answer, not just partially?
Also flag unsupported_claims: true if it states something as fact with no support in the context (e.g. specific medical claims not grounded in the guidelines).

Reply with ONLY a JSON object, no other text:
{"groundedness": 0.0-1.0, "relevance": 0.0-1.0, "completeness": 0.0-1.0, "unsupported_claims": true|false, "notes": "one short sentence"}"""


def _extract_json(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


async def score_judge(case: GoldenCase, state: NutriBotState) -> JudgeResult | None:
    context_block = (
        f"USER MESSAGE: {case.user_message}\n\n"
        f"PROFILE CONTEXT: {state.get('profile_context', '')}\n\n"
        f"RAG CONTEXT USED: {state.get('rag_context', '')}\n\n"
        f"ASSISTANT RESPONSE: {state.get('response', '')}"
    )

    try:
        result = await get_provider().generate(
            messages=[
                Message(role="system", content=JUDGE_SYSTEM_PROMPT),
                Message(role="user", content=context_block),
            ],
            config=GenerationConfig(profile="fast", temperature=0, max_tokens=300),
        )
        parsed = _extract_json(result.text)
        if not parsed:
            logger.warning("Judge returned unparseable output for case %s: %r", case.id, result.text)
            return None
        return JudgeResult(**parsed)
    except Exception:
        logger.exception("Judge scoring failed for case %s", case.id)
        return None
