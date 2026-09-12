"""CLI entrypoint for the evaluation harness.

Usage:
    python -m backend.eval.runner            # single run on the active provider
    python -m backend.eval.runner --compare  # primary vs. challenger (Phase 7)

Single mode runs every case in the golden set through the real pipeline,
scores it, prints a report, writes eval_results.json, and exits non-zero if
any deterministic check failed OR a safety-relevant judge metric failed on a
case in a safety-gated category (see backend/eval/compare.py). Judge results
stay purely informational everywhere else.

Compare mode runs the same golden set twice -- once on the primary provider
("azure_openai"), once on the challenger ("azure_openai_challenger") -- with
the judge pinned to one fixed provider across both arms, prints a
side-by-side report, writes eval_compare_results.json, and exits 0 iff the
challenger is promotable (compare_arms verdict).
"""
import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone

from backend.config import get_settings
from backend.eval.compare import CompareVerdict, case_passed, compare_arms
from backend.eval.golden_set import GOLDEN_CASES
from backend.eval.models import CaseResult, DeterministicResult
from backend.eval.pipeline_runner import run_case
from backend.eval.scorers.deepeval_scorer import score_deepeval
from backend.eval.scorers.deterministic import score_deterministic
from backend.llm.base import GenerationConfig, Message
from backend.llm.factory import get_provider

logging.basicConfig(level=logging.WARNING)

# Judge notes/failure text can contain characters (em/en dashes, curly
# quotes) outside Windows' default cp1252 console codepage -- without this,
# _print_report crashes mid-report on Windows, before eval_results.json even
# gets written. errors="replace" so a genuinely unprintable character still
# degrades to a placeholder instead of killing the whole run.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Cases run sequentially. Groq's on_demand tier has an 8000 TPM shared rate
# limit (see docs/CURRENT_STATE.md) that this pacing protects against; Azure
# OpenAI's quota is far higher, but the delay is harmless there too and keeps
# the harness safe to run under either provider without per-provider logic.
INTER_CASE_DELAY_SECONDS = 5

PRIMARY_ARM = "azure_openai"
CHALLENGER_ARM = "azure_openai_challenger"
COMPARE_ARMS = (PRIMARY_ARM, CHALLENGER_ARM)  # primary first


def _active_model(settings) -> str:
    """The "full" profile model, whichever provider is actually configured --
    settings.llm_model is Groq-specific and was being reported unconditionally
    even when running against Azure OpenAI, which is misleading in the report."""
    if settings.llm_provider == PRIMARY_ARM:
        return settings.azure_openai_deployment_full
    if settings.llm_provider == CHALLENGER_ARM:
        return settings.azure_openai_challenger_deployment_full
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
                    plan_build=state.get("plan_build_report"),
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


async def _probe_challenger() -> None:
    """One tiny live call so a configured-but-unreachable challenger fails in
    seconds, BEFORE the expensive primary arm runs.

    get_provider() alone only validates config (a missing deployment name
    raises immediately) -- it never touches the network, so a deployment
    that is configured but doesn't exist on the resource would otherwise
    only surface as 16 ERROR rows after the primary arm had already run in
    full. Found the hard way when the challenger deployment hadn't been
    created yet.
    """
    provider = get_provider(CHALLENGER_ARM)
    settings = get_settings()
    try:
        await provider.generate(
            [Message(role="user", content="ping")],
            GenerationConfig(profile="full", temperature=0, max_tokens=5),
        )
    except Exception as exc:
        raise RuntimeError(
            f"Challenger provider {CHALLENGER_ARM!r} (deployment "
            f"{settings.azure_openai_challenger_deployment_full!r}) is configured but not "
            f"reachable -- aborting before the primary arm runs. Does the deployment exist on "
            f"the resource? (Azure reports DeploymentNotFound for a few minutes after creation.) "
            f"Underlying error: {type(exc).__name__}: {exc}"
        ) from exc


async def _run_compare() -> dict[str, list[CaseResult]]:
    """Run the golden set once per arm by swapping the active provider.

    The zero-arg get_provider() entry snapshots settings.llm_provider on
    first use (lru_cache), so each arm clears the cache after switching.
    The pinned judge (eval_judge_provider) is also evicted by cache_clear and
    simply rebuilt from the same settings -- harmless, and it stays the same
    model in both arms, which is the whole point.
    """
    settings = get_settings()
    original_provider = settings.llm_provider
    # Fail fast: config errors raise inside get_provider, reachability errors
    # raise from the probe -- either way before a single case (or dollar) is spent.
    await _probe_challenger()

    results: dict[str, list[CaseResult]] = {}
    try:
        for i, arm in enumerate(COMPARE_ARMS):
            print(f"\n### Arm {i + 1}/{len(COMPARE_ARMS)}: {arm} ###", flush=True)
            settings.llm_provider = arm
            get_provider.cache_clear()
            results[arm] = await _run_all()
            if i < len(COMPARE_ARMS) - 1:
                await asyncio.sleep(INTER_CASE_DELAY_SECONDS)
    finally:
        settings.llm_provider = original_provider
        get_provider.cache_clear()
    return results


def _judge_str(r: CaseResult) -> str:
    if not r.judge:
        return "n/a"
    f = f"{r.judge.faithfulness:.1f}" if r.judge.faithfulness is not None else "n/a"
    return f"{f}/{r.judge.answer_relevancy:.1f}/{r.judge.medical_safety:.1f}/{r.judge.completeness:.1f}"


def _plan_build_str(build: dict) -> str:
    """One line on what plan_builder had to do: how far the model's own
    picks were from target before code corrected them."""
    days = build.get("day_calories") or []
    rebalanced = build.get("rebalanced_days") or {}
    factors = ", ".join(f"{d.replace('Day ', 'D')}x{f:.2f}" for d, f in rebalanced.items())
    parts = [
        f"days kcal {[round(d) for d in days]}",
        f"rebalanced {len(rebalanced)}/{len(days)}" + (f" ({factors})" if factors else ""),
    ]
    if build.get("off_target_days"):
        parts.append(f"OFF-TARGET {build['off_target_days']}")
    if build.get("dropped_items"):
        parts.append(f"dropped {build['dropped_items']}")
    if build.get("unparseable_items"):
        parts.append(f"no-grams {build['unparseable_items']}")
    return " | ".join(parts)


def _print_report(results: list[CaseResult]) -> None:
    print("\n" + "=" * 110)
    print(f"{'CASE':<10} {'CATEGORY':<24} {'INTENT':<22} {'DET':<6} {'JUDGE (f/r/s/c)':<18} GATED  FAILURES")
    print("-" * 110)
    for r in results:
        det = "PASS" if r.deterministic.passed else "FAIL"
        gated = "PASS" if case_passed(r) else "FAIL"
        failures = "; ".join(r.deterministic.failures)
        if r.judge and r.judge.notes:
            failures = f"{failures}; judge: {r.judge.notes}" if failures else f"judge: {r.judge.notes}"
        print(f"{r.case_id:<10} {r.category:<24} {r.intent:<22} {det:<6} {_judge_str(r):<18} {gated:<6} {failures}")
        if r.plan_build:
            print(f"{'':<10} plan: {_plan_build_str(r.plan_build)}")
    print("=" * 110)

    total = len(results)
    det_passed = sum(1 for r in results if r.deterministic.passed)
    gated_passed = sum(1 for r in results if case_passed(r))
    provider = results[0].provider if results else "?"
    model = results[0].model if results else "?"
    print(
        f"Deterministic: {det_passed}/{total} passed | Gated (det + safety-relevant judge): "
        f"{gated_passed}/{total} passed | Provider: {provider} | Model: {model}"
    )


def _arm_cell(r: CaseResult) -> str:
    det = "PASS" if r.deterministic.passed else "FAIL"
    gated = "PASS" if case_passed(r) else "FAIL"
    return f"{det} {_judge_str(r)} {gated}"


def _print_compare_report(primary: list[CaseResult], challenger: list[CaseResult], verdict: CompareVerdict) -> None:
    challenger_by_id = {r.case_id: r for r in challenger}
    total = len(primary)

    print("\n" + "=" * 120)
    print(f"{'CASE':<8} {'CATEGORY':<24} {'PRIMARY det/judge(f/r/s/c)/gated':<38} {'CHALLENGER det/judge/gated':<38} DELTA")
    print("-" * 120)
    for p in primary:
        c = challenger_by_id.get(p.case_id)
        if c is None:
            c_cell, delta = "missing", "REGRESSED (missing)"
        else:
            c_cell = _arm_cell(c)
            p_ok, c_ok = case_passed(p), case_passed(c)
            if c.intent == "ERROR":
                delta = "challenger ERROR"
            elif p_ok == c_ok:
                delta = "same"
            elif p_ok:
                delta = "REGRESSED"
            else:
                delta = "improved"
            if p.intent == "ERROR":
                delta += " / primary ERROR"
        print(f"{p.case_id:<8} {p.category:<24} {_arm_cell(p):<38} {c_cell:<38} {delta}")
    print("=" * 120)

    p_label = f"{primary[0].provider} / {primary[0].model}" if primary else "?"
    c_label = f"{challenger[0].provider} / {challenger[0].model}" if challenger else "?"
    print(f"Primary    ({p_label}): gated {verdict.primary_gated_passed}/{total} passed")
    print(f"Challenger ({c_label}): gated {verdict.challenger_gated_passed}/{total} passed")
    print(f"Safety-gated regressions: {', '.join(verdict.safety_regressions) or 'none'}")
    print(f"Challenger pipeline errors: {', '.join(verdict.challenger_errors) or 'none'}")
    print(f"\nVerdict: {'PROMOTABLE' if verdict.promotable else 'NOT PROMOTABLE'}")
    for reason in verdict.reasons:
        print(f"  - {reason}")
    print(
        "\nCaveat: a single --compare run at generation temperature ~0.5 is noisy -- run it 2-3 times\n"
        "and require a consistent verdict before promoting.\n"
        "Promotion (config only, no code): set AZURE_OPENAI_DEPLOYMENT_FULL/FAST to the challenger\n"
        "deployment and AZURE_OPENAI_REASONING_MODEL=false; LLM_PROVIDER stays azure_openai."
    )


def _main_single() -> int:
    results = asyncio.run(_run_all())
    _print_report(results)

    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "results": [r.model_dump() for r in results],
    }
    with open("eval_results.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print("\nWrote eval_results.json")

    return 0 if all(case_passed(r) for r in results) else 1


def _main_compare() -> int:
    arms = asyncio.run(_run_compare())
    primary, challenger = arms[PRIMARY_ARM], arms[CHALLENGER_ARM]
    verdict = compare_arms(primary, challenger)
    _print_compare_report(primary, challenger, verdict)

    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "primary": {
            "provider": PRIMARY_ARM,
            "model": primary[0].model if primary else "?",
            "results": [r.model_dump() for r in primary],
        },
        "challenger": {
            "provider": CHALLENGER_ARM,
            "model": challenger[0].model if challenger else "?",
            "results": [r.model_dump() for r in challenger],
        },
        "verdict": verdict.model_dump(),
    }
    with open("eval_compare_results.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print("\nWrote eval_compare_results.json")

    return 0 if verdict.promotable else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.eval.runner",
        description="NutriBot evaluation harness (golden set, real API calls, not part of CI).",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help=(
            f"run the golden set on the primary ({PRIMARY_ARM}) and challenger ({CHALLENGER_ARM}) "
            "arms and emit a promotability verdict (Phase 7)"
        ),
    )
    args = parser.parse_args(argv)
    return _main_compare() if args.compare else _main_single()


if __name__ == "__main__":
    raise SystemExit(main())
