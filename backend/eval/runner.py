"""CLI entrypoint for the evaluation harness.

Usage: python -m backend.eval.runner

Runs every case in the golden set through the real pipeline, scores it, prints
a report, writes eval_results.json, and exits non-zero if any deterministic
check failed (the part CI gates on — judge scores are informational, not gating,
per the v2 roadmap's "LLM-judge stub" scope for Phase 1b).
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

from backend.config import get_settings
from backend.eval.golden_set import GOLDEN_CASES
from backend.eval.models import CaseResult, DeterministicResult
from backend.eval.pipeline_runner import run_case
from backend.eval.scorers.deterministic import score_deterministic
from backend.eval.scorers.judge import score_judge

logging.basicConfig(level=logging.WARNING)

# Cases run sequentially against a real Groq account with an 8000 TPM shared
# rate limit (see docs/CURRENT_STATE.md) — pace requests so the harness itself
# doesn't trip the same limit it exists to help catch regressions against.
INTER_CASE_DELAY_SECONDS = 5


async def _run_all() -> list[CaseResult]:
    settings = get_settings()
    results: list[CaseResult] = []

    for i, case in enumerate(GOLDEN_CASES):
        print(f"[{i + 1}/{len(GOLDEN_CASES)}] {case.id} ({case.category}) ...", flush=True)
        try:
            state = await run_case(case)
            deterministic = score_deterministic(case, state)
            judge = await score_judge(case, state)
            results.append(
                CaseResult(
                    case_id=case.id,
                    category=case.category,
                    provider=settings.llm_provider,
                    model=settings.llm_model,
                    intent=state.get("intent", "?"),
                    deterministic=deterministic,
                    judge=judge,
                    response_preview=state.get("response", "")[:120],
                )
            )
        except Exception as exc:
            results.append(
                CaseResult(
                    case_id=case.id,
                    category=case.category,
                    provider=settings.llm_provider,
                    model=settings.llm_model,
                    intent="ERROR",
                    deterministic=DeterministicResult(passed=False, failures=[f"pipeline error: {exc}"]),
                )
            )

        if i < len(GOLDEN_CASES) - 1:
            await asyncio.sleep(INTER_CASE_DELAY_SECONDS)

    return results


def _print_report(results: list[CaseResult]) -> None:
    print("\n" + "=" * 100)
    print(f"{'CASE':<10} {'CATEGORY':<24} {'INTENT':<22} {'DET':<6} {'JUDGE (g/r/c)':<16} FAILURES")
    print("-" * 100)
    for r in results:
        det = "PASS" if r.deterministic.passed else "FAIL"
        judge_str = (
            f"{r.judge.groundedness:.1f}/{r.judge.relevance:.1f}/{r.judge.completeness:.1f}"
            if r.judge
            else "n/a"
        )
        failures = "; ".join(r.deterministic.failures)
        print(f"{r.case_id:<10} {r.category:<24} {r.intent:<22} {det:<6} {judge_str:<16} {failures}")
    print("=" * 100)

    total = len(results)
    passed = sum(1 for r in results if r.deterministic.passed)
    provider = results[0].provider if results else "?"
    model = results[0].model if results else "?"
    print(f"Deterministic: {passed}/{total} passed | Provider: {provider} | Model: {model}")


def main() -> int:
    results = asyncio.run(_run_all())
    _print_report(results)

    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "results": [r.model_dump() for r in results],
    }
    with open("eval_results.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print("\nWrote eval_results.json")

    return 0 if all(r.deterministic.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
