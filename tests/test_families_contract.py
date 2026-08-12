"""Contract tests for the family validator — offline, FakeBackend-scripted.

Family generators get their own test files; this file pins what *any* family
is measured against, so the validator itself can't drift while two generator
agents build against it in parallel (the Phase-0 frozen-contract discipline).
"""
from __future__ import annotations

from rlmath.core.types import DecompositionPlan, GoalSpec, LemmaSpec, VerifyResult
from rlmath.families import REGISTRY, register, validate_problem
from rlmath.families.types import GeneratedProblem, LeafWitness
from rlmath.families.validate import AUTOMATION_TACTICS


def _problem() -> GeneratedProblem:
    return GeneratedProblem(
        id="test-k2-s0-0",
        family="test",
        k=2,
        seed=0,
        goal=GoalSpec(id="g", prop="GOALPROP", name="goal_t"),
        oracle_plan=DecompositionPlan(
            lemmas=[LemmaSpec("h1", "LEMMA_ONE"), LemmaSpec("h2", "LEMMA_TWO")],
            assembly="exact glue h1 h2",
        ),
        witnesses={
            "h1": LeafWitness("LEMMA_ONE", "by w1"),
            "h2": LeafWitness("LEMMA_TWO", "by w2"),
        },
    )


def _wire_happy_path(fb, *, auto_closes: str | None = None) -> None:
    """Script a backend where everything checks and automation fails everywhere,
    except `auto_closes` (a battery proof string, e.g. "by norm_num" or
    "by intros; linarith") which closes LEMMA_ONE."""
    from rlmath.families.validate import battery_proofs

    fb.rule(lambda c: ":= sorry" in c, VerifyResult(ok=True, sorries=1))          # elaborations
    fb.rule(lambda c: "by w1" in c or "by w2" in c, VerifyResult(ok=True, sorries=0))  # witnesses
    if auto_closes:
        fb.rule(
            lambda c, t=auto_closes: t in c and "LEMMA_ONE" in c,
            VerifyResult(ok=True, sorries=0),
        )
    fb.rule(
        lambda c: any(p in c for p in battery_proofs()),
        VerifyResult(ok=False, sorries=0),                                        # battery fails
    )
    fb.rule(lambda c: "#print axioms" in c, VerifyResult(ok=True, sorries=0))     # composed artifact
    fb.rule(lambda c: True, VerifyResult(ok=True, sorries=0))                     # everything else


def test_valid_problem_passes_all_checks(fake_backend):
    _wire_happy_path(fake_backend)
    report = validate_problem(_problem(), fake_backend)
    assert report.ok, report.failed()
    names = [c.name for c in report.checks]
    assert "V0_goal_resists_automation" in names
    assert "V4_oracle_replay" in names
    assert any(n.startswith("V5_leaf_resists") for n in names)


def test_auto_closable_leaf_fails_v5(fake_backend):
    _wire_happy_path(fake_backend, auto_closes="by norm_num")
    report = validate_problem(_problem(), fake_backend)
    assert not report.ok
    failed = {c.name: c.detail for c in report.failed()}
    assert "V5_leaf_resists[h1]" in failed
    assert "norm_num" in failed["V5_leaf_resists[h1]"]


def test_intro_gated_tactic_kills_leaf(fake_backend):
    """Regression for famB's measured V5 gap: a leaf closable only AFTER intros
    (e.g. a quantified affine band vs `intro; linarith`) must fail V5. The old
    battery never introduced binders, so such leaves passed for free."""
    _wire_happy_path(fake_backend, auto_closes="by intros; linarith")
    report = validate_problem(_problem(), fake_backend)
    assert not report.ok
    failed = {c.name: c.detail for c in report.failed()}
    assert "V5_leaf_resists[h1]" in failed
    assert "intros; linarith" in failed["V5_leaf_resists[h1]"]


def test_hidden_terms_leak_fails_v6b(fake_backend):
    """V6b: a family-declared hidden term occurring in the goal is a failure —
    the strong form of the hidden-intermediate property (whole-prop substring
    was measured near-vacuous by both family agents)."""
    p = _problem()
    p.meta["hidden_terms"] = ["SECRET_TERM", "GOALPROP"]  # second one leaks
    _wire_happy_path(fake_backend)
    report = validate_problem(p, fake_backend, check_automation=False)
    names = {c.name: c.ok for c in report.checks}
    assert names["V6b_hidden_term[0]"] is True
    assert names["V6b_hidden_term[1]"] is False


def test_v6a_catches_restatement_across_binder_spelling(fake_backend):
    """Body-level check: a lemma restating the goal body under different binder
    spelling must still be caught (the defeat both agents measured)."""
    p = _problem()
    goal = "∀ x y : ℝ, BODY_XYZ"
    lemma = "∀ (x : ℝ) (y : ℝ), BODY_XYZ"
    from rlmath.core.types import GoalSpec, LemmaSpec
    from rlmath.families.types import LeafWitness
    p.goal = GoalSpec(id="g", prop=goal, name="goal_t")
    p.oracle_plan.lemmas[0] = LemmaSpec("h1", lemma)
    p.witnesses["h1"] = LeafWitness(lemma, "by w1")
    _wire_happy_path(fake_backend)
    report = validate_problem(p, fake_backend, check_automation=False)
    assert any(c.name == "V6_hidden[h1]" and not c.ok for c in report.checks)


def test_plan_witness_mismatch_short_circuits(fake_backend):
    p = _problem()
    del p.witnesses["h2"]
    report = validate_problem(p, fake_backend)
    assert [c.name for c in report.checks] == ["structure"]
    assert not report.ok
    assert fake_backend.calls == []  # no Lean spent on a malformed problem


def test_restated_goal_lemma_fails_v6(fake_backend):
    p = _problem()
    p.oracle_plan.lemmas[0] = LemmaSpec("h1", "GOALPROP")
    p.witnesses["h1"] = LeafWitness("GOALPROP", "by w1")
    _wire_happy_path(fake_backend)
    report = validate_problem(p, fake_backend, check_automation=False)
    assert any(c.name == "V6_hidden[h1]" and not c.ok for c in report.checks)


def test_visible_lemmas_exempt_from_v6(fake_backend):
    p = _problem()
    p.oracle_plan.lemmas[0] = LemmaSpec("h1", "GOALPROP")
    p.witnesses["h1"] = LeafWitness("GOALPROP", "by w1")
    p.meta["visible_lemmas"] = ["h1"]
    _wire_happy_path(fake_backend)
    report = validate_problem(p, fake_backend, check_automation=False)
    assert not any(c.name.startswith("V6") and not c.ok for c in report.checks)


def test_registry_rejects_duplicates():
    import pytest

    name = "_contract_test_family"
    try:
        register(name, lambda k, seed, n: [])
        with pytest.raises(ValueError):
            register(name, lambda k, seed, n: [])
    finally:
        REGISTRY.pop(name, None)  # integrator flag: never leak stubs into the process-global registry


def test_package_import_populates_registry():
    """FAMILIES.md's promise, now true (all three agents flagged it false):
    importing the package registers the shipped families."""
    import rlmath.families as fam

    assert {"bridge_chain", "case_tree"} <= set(fam.REGISTRY)


def test_leaf_split_is_deterministic_and_partitions():
    """Anti-contamination contract (strategist review 2026-08-12): membership is
    a pure function of the key — stable across bank growth, re-sweeps, machines."""
    from rlmath.families.leaf_split import leaf_split, split_pools

    keys = [f"{i:015x}{n}" for i in range(4) for n in "0123456789abcdef"]
    assert all(leaf_split(k) == leaf_split(k) for k in keys)
    train, ev = split_pools(keys)
    assert set(train).isdisjoint(ev)
    assert len(train) + len(ev) == len(keys)
    assert len(ev) / len(keys) == 0.25  # 4/16 nibbles
    assert leaf_split("0123456789abcdef") == "eval"
    assert leaf_split("0123456789abcde0") == "train"


def test_leaf_split_rejects_empty():
    import pytest

    from rlmath.families.leaf_split import leaf_split

    with pytest.raises(ValueError):
        leaf_split("")
