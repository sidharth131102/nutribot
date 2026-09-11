"""CLI entrypoint for the evaluation harness.

Usage: python -m backend.eval.runner

Runs every case in the golden set through the real pipeline, scores it, prints
a report, writes eval_results.json, and exits non-zero if any deterministic
check failed, OR if a safety-relevant judge metric failed on a case in a
safety-gated category (Phase 6 -- resolves the roadmap's own flagged-as-
undecided "judge coverage thresholds" item). Judge results stay purely
informational everywhere else.
"""
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone

from backend.config import get_settings
from backend.eval.golden_set import GOLDEN_CASES
from backend.eval.models import CaseResult, DeterministicResult
from backend.eval.pipeline_runner import run_case
from backend.eval.scorers.deepeval_scorer import score_deepeval
from backend.eval.scorers.deterministic import score_deterministic

logging.basicConfig(level=logging.WARNING)

# Judge notes/failure text can contain characters (em/en dashes, curly
# quotes) outside Windows' default cp1252 console codepage -- without this,
# _print_report crashes mid-report on Windows, before eval_results.json even
# gets written. errors="replace" so a genuinely unprintable character still
# degrades to a placeholder instead of killing the whole run.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Categories where hallucination/unsafe-content risk is safety-relevant, not
# just a quality nicety -- a failing medical_safety or faithfulness metric
# here gates the run. ambiguous_unsafe is deliberately excluded: its safety
# property is now enforced deterministically by the input guardrail
# (expect_input_blocked, see scorers/deterministic.py), not semantic judging.
SAFETY_GATED_CATEGORIES = {"rag_dependent", "medical_context", "allergy_diet_edge_case"}

# Cases run sequentially. Groq's on_demand tier has an 8000 TPM shared rate
# limit (see docs/CURRENT_STATE.md) that this pacing protects against; Azure
# OpenAI's quota is far higher, but the delay is harmless there too and keeps
# the harness safe to run under either provider without per-provider logic.
INTER_CASE_DELAY_SECONDS = 5


def _active_model(settings) -> str:
    """The "full" profile model, whichever provider is actually configured --
    settings.llm_model is Groq-specific and was being reported unconditionally
    even when running against Azure OpenAI, which is misleading in the report."""
    if settings.llm_provider == "azure_openai":
        return settings.azure_openai_deployment_full
    return settings.llm_model


async def _run_all() -> list[CaseResult]:
    settings = get_settings()
    model = _active_model(settings)
    results: list[CaseResult] = []

    for i, case in enumerate(GOLDEN_CASES):
        print(f"[{i + 1}/{len(GOLDEN_CASES)}] {case.id} ({case.category}) ...", flush=True)
        try:
            state = await run_case(case)
            deterministic = score_deterministic(case, state)
            judge = await score_deepeval(case, state)
            results.append(
                CaseResult(
                    case_id=case.id,
                    category=case.category,
                    provider=settings.llm_provider,
                    model=model,
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
                    model=model,
                    intent="ERROR",
                    deterministic=DeterministicResult(passed=False, failures=[f"pipeline error: {exc}"]),
                )
            )

        if i < len(GOLDEN_CASES) - 1:
            await asyncio.sleep(INTER_CASE_DELAY_SECONDS)

    return results


def _case_passed(r: CaseResult) -> bool:
    if not r.deterministic.passed:
        return False
    if r.category in SAFETY_GATED_CATEGORIES and r.judge is not None:
        if r.judge.medical_safety_pass is False:
            return False
        if r.judge.faithfulness_pass is False:  # None (not applicable) is not a failure
            return False
    return True


def _print_report(results: list[CaseResult]) -> None:
    print("\n" + "=" * 110)
    print(f"{'CASE':<10} {'CATEGORY':<24} {'INTENT':<22} {'DET':<6} {'JUDGE (f/r/s/c)':<18} GATED  FAILURES")
    print("-" * 110)
    for r in results:
        det = "PASS" if r.deterministic.passed else "FAIL"
        if r.judge:
            f = f"{r.judge.faithfulness:.1f}" if r.judge.faithfulness is not None else "n/a"
            judge_str = f"{f}/{r.judge.answer_relevancy:.1f}/{r.judge.medical_safety:.1f}/{r.judge.completeness:.1f}"
        else:
            judge_str = "n/a"
        gated = "PASS" if _case_passed(r) else "FAIL"
        failures = "; ".join(r.deterministic.failures)
        if r.judge and r.judge.notes:
            failures = f"{failures}; judge: {r.judge.notes}" if failures else f"judge: {r.judge.notes}"
        print(f"{r.case_id:<10} {r.category:<24} {r.intent:<22} {det:<6} {judge_str:<18} {gated:<6} {failures}")
    print("=" * 110)

    total = len(results)
    det_passed = sum(1 for r in results if r.deterministic.passed)
    gated_passed = sum(1 for r in results if _case_passed(r))
    provider = results[0].provider if results else "?"
    model = results[0].model if results else "?"
    print(f"Deterministic: {det_passed}/{total} passed | Gated (det + safety-relevant judge): {gated_passed}/{total} passed | Provider: {provider} | Model: {model}")


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

    return 0 if all(_case_passed(r) for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
