"""Tests for backend/eval/compare.py -- the gate predicate and the
primary-vs-challenger promotability verdict over canned CaseResults.
Pure logic, no LLM calls."""
from backend.eval.compare import SAFETY_GATED_CATEGORIES, case_passed, compare_arms
from backend.eval.models import CaseResult, DeterministicResult, JudgeResult


def _case(cid, category, *, det=True, safety=True, faith=True, intent="MEAL_PLAN_REQUEST", judge=True):
    judge_result = None
    if judge:
        judge_result = JudgeResult(
            faithfulness=None if faith is None else (0.9 if faith else 0.2),
            faithfulness_pass=faith,
            answer_relevancy=0.9,
            answer_relevancy_pass=True,
            medical_safety=0.9 if safety else 0.2,
            medical_safety_pass=safety,
            completeness=0.9,
            completeness_pass=True,
        )
    return CaseResult(
        case_id=cid,
        category=category,
        provider="p",
        model="m",
        intent=intent,
        deterministic=DeterministicResult(passed=det, failures=[] if det else ["failed"]),
        judge=judge_result,
    )


# ── case_passed ──────────────────────────────────────────────────────────

def test_case_passed_false_on_deterministic_failure():
    assert case_passed(_case("c", "general_qa", det=False)) is False


def test_case_passed_false_on_medical_safety_failure_in_gated_category():
    assert case_passed(_case("c", "medical_context", safety=False)) is False


def test_case_passed_true_on_medical_safety_failure_in_non_gated_category():
    assert "general_qa" not in SAFETY_GATED_CATEGORIES
    assert case_passed(_case("c", "general_qa", safety=False)) is True


def test_case_passed_treats_none_faithfulness_as_not_applicable():
    assert case_passed(_case("c", "rag_dependent", faith=None)) is True


def test_case_passed_false_on_faithfulness_failure_in_gated_category():
    assert case_passed(_case("c", "rag_dependent", faith=False)) is False


# ── compare_arms ─────────────────────────────────────────────────────────

def test_identical_passing_arms_are_promotable():
    primary = [_case("a", "general_qa"), _case("b", "medical_context")]
    challenger = [_case("a", "general_qa"), _case("b", "medical_context")]

    verdict = compare_arms(primary, challenger)

    assert verdict.promotable is True
    assert verdict.primary_gated_passed == 2
    assert verdict.challenger_gated_passed == 2
    assert verdict.safety_regressions == []
    assert verdict.challenger_errors == []
    assert verdict.reasons == []


def test_safety_gated_regression_blocks_promotion():
    primary = [_case("a", "general_qa"), _case("b", "medical_context")]
    challenger = [_case("a", "general_qa"), _case("b", "medical_context", safety=False)]

    verdict = compare_arms(primary, challenger)

    assert verdict.promotable is False
    assert verdict.safety_regressions == ["b"]
    assert any("safety-gated regressions" in r for r in verdict.reasons)


def test_lower_gated_count_on_non_gated_case_blocks_without_safety_regression():
    primary = [_case("a", "general_qa"), _case("b", "general_qa")]
    challenger = [_case("a", "general_qa"), _case("b", "general_qa", det=False)]

    verdict = compare_arms(primary, challenger)

    assert verdict.promotable is False
    assert verdict.safety_regressions == []
    assert verdict.challenger_gated_passed == 1
    assert any("gated-pass count" in r for r in verdict.reasons)


def test_equal_counts_with_different_non_gated_failures_is_promotable():
    primary = [_case("a", "general_qa", det=False), _case("b", "general_qa")]
    challenger = [_case("a", "general_qa"), _case("b", "general_qa", det=False)]

    verdict = compare_arms(primary, challenger)

    assert verdict.promotable is True
    assert verdict.primary_gated_passed == 1
    assert verdict.challenger_gated_passed == 1


def test_challenger_pipeline_error_blocks_promotion():
    primary = [_case("a", "general_qa")]
    challenger = [_case("a", "general_qa", det=False, intent="ERROR", judge=False)]

    verdict = compare_arms(primary, challenger)

    assert verdict.promotable is False
    assert verdict.challenger_errors == ["a"]
    assert any("pipeline errors" in r for r in verdict.reasons)


def test_none_faithfulness_in_gated_category_does_not_regress():
    primary = [_case("a", "rag_dependent", faith=None)]
    challenger = [_case("a", "rag_dependent", faith=None)]

    verdict = compare_arms(primary, challenger)

    assert verdict.promotable is True
    assert verdict.safety_regressions == []


def test_gated_case_missing_from_challenger_counts_as_regression():
    primary = [_case("a", "general_qa"), _case("b", "medical_context")]
    challenger = [_case("a", "general_qa")]

    verdict = compare_arms(primary, challenger)

    assert verdict.promotable is False
    assert verdict.safety_regressions == ["b"]


def test_challenger_improvement_over_primary_is_promotable():
    primary = [_case("a", "general_qa", det=False), _case("b", "medical_context")]
    challenger = [_case("a", "general_qa"), _case("b", "medical_context")]

    verdict = compare_arms(primary, challenger)

    assert verdict.promotable is True
    assert verdict.challenger_gated_passed > verdict.primary_gated_passed
