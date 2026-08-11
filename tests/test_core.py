"""Core contract tests — the stable baseline the builder agents' suites sit on."""
from rlmath.core import leancode
from rlmath.core.types import (
    DecompositionPlan,
    GoalSpec,
    LemmaSpec,
    Status,
    VerifyResult,
    normalize_statement,
    statement_key,
)

GOAL = GoalSpec(id="t1", prop="2 ∣ 4 + 6", name="goal_t1")
PLAN = DecompositionPlan(
    lemmas=[LemmaSpec("h1", "2 ∣ 4"), LemmaSpec("h2", "2 ∣ 6")],
    assembly="exact Dvd.dvd.add h1 h2",
)


def test_normalize_strips_comments_and_ws():
    assert normalize_statement("∀ n : ℕ,\n  n + 0 = n  -- trivial") == "∀ n : ℕ, n + 0 = n"
    assert normalize_statement("a /- block\ncomment -/ = a") == "a = a"


def test_statement_key_stable_under_formatting():
    assert statement_key("∀ n : ℕ, n + 0 = n") == statement_key("∀ n : ℕ,\n\tn + 0 = n")
    assert statement_key("a = a") != statement_key("a = b")


def test_statement_check_expects_one_sorry():
    code = leancode.statement_check("2 ∣ 4")
    assert code == "theorem _stmt_check : 2 ∣ 4 := sorry"


def test_proof_check_indents_block():
    code = leancode.proof_check("2 ∣ 4", "by\n  norm_num")
    assert code.startswith("theorem _proof_check : 2 ∣ 4 :=\n  by")


def test_plan_check_grants_lemmas_as_hypotheses():
    code = leancode.plan_check(GOAL, PLAN)
    assert "theorem _plan (h1 : 2 ∣ 4) (h2 : 2 ∣ 6) : 2 ∣ 4 + 6 := by" in code
    assert "exact Dvd.dvd.add h1 h2" in code
    # crucially: no `axiom` declarations — the audit must stay clean
    assert "axiom" not in code


def test_plan_check_direct():
    direct = DecompositionPlan(lemmas=[], assembly="norm_num")
    code = leancode.plan_check(GOAL, direct)
    assert code.startswith("theorem _plan : 2 ∣ 4 + 6 := by")


def test_compose_splices_proofs():
    code = leancode.compose(GOAL, PLAN, {"h1": "by norm_num", "h2": "by norm_num"})
    assert code.startswith("theorem goal_t1 : 2 ∣ 4 + 6 := by\n")
    assert "have h1 : 2 ∣ 4 := by norm_num" in code
    assert "have h2 : 2 ∣ 6 := by norm_num" in code
    assert code.rstrip().endswith("exact Dvd.dvd.add h1 h2")


def test_compose_multiline_leaf_proof():
    code = leancode.compose(GOAL, PLAN, {"h1": "by\n  norm_num", "h2": "by norm_num"})
    assert "have h1 : 2 ∣ 4 :=\n" in code  # multiline proof drops to next line, indented


def test_status_taxonomy_is_complete():
    # DIRECTION.md §5.7 status separation — additions are fine, removals are not.
    required = {
        "verified", "format_error", "sanitizer_rejected", "statement_ill_formed",
        "plan_invalid", "leaf_failed", "compose_failed", "budget_exhausted",
        "context_window_exceeded", "error",
    }
    assert required <= {s.value for s in Status}


def test_verify_result_errors_property():
    from rlmath.core.types import LeanMessage
    r = VerifyResult(ok=False, messages=[LeanMessage("warning", "w"), LeanMessage("error", "e")])
    assert [m.text for m in r.errors] == ["e"]
