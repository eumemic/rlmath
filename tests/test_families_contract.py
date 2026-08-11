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
    except `auto_closes` (a tactic name) which closes LEMMA_ONE."""
    fb.rule(lambda c: ":= sorry" in c, VerifyResult(ok=True, sorries=1))          # elaborations
    if auto_closes:
        fb.rule(
            lambda c, t=auto_closes: f"by {t}" in c and "LEMMA_ONE" in c,
            VerifyResult(ok=True, sorries=0),
        )
    fb.rule(
        lambda c: any(f"by {t}" in c for t in AUTOMATION_TACTICS),
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
    _wire_happy_path(fake_backend, auto_closes="norm_num")
    report = validate_problem(_problem(), fake_backend)
    assert not report.ok
    failed = {c.name: c.detail for c in report.failed()}
    assert "V5_leaf_resists[h1]" in failed
    assert "norm_num" in failed["V5_leaf_resists[h1]"]


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
    if name not in REGISTRY:
        register(name, lambda k, seed, n: [])
    with pytest.raises(ValueError):
        register(name, lambda k, seed, n: [])
