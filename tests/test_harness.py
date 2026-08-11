"""Episode-runner tests: one per status path, plus the accounting and codegen
details that would otherwise fail silently.

Everything runs offline against conftest's FakeBackend (scripted predicate →
VerifyResult) and the FakeLeaf below. That is the point: the pipeline's *status
attribution* is the experiment's instrument (DIRECTION.md §6 — "leaf_failed vs
plan_invalid vs budget_exhausted need status separation from day one"), so it
has to be pinned by tests that do not need Mathlib installed.

Two statuses are unreachable here by design and that is asserted, not assumed:
CONTEXT_WINDOW_EXCEEDED belongs to the eval runner (it knows the root model's
window) and ERROR to infrastructure — backend exceptions propagate so
repair_errors.py can re-run the sample (../rl pattern).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from rlmath.core.leancode import compose, plan_check, statement_check
from rlmath.core.types import (
    Budgets,
    DecompositionPlan,
    GoalSpec,
    LeanMessage,
    LemmaSpec,
    Status,
    VerifyResult,
)
from rlmath.harness import composer, detectors
from rlmath.harness.episode import run_direct_close, run_episode

GOAL = GoalSpec(id="g1", prop="P", name="thm")
PLAN_TEXT = """
sure, here is my plan
#lemma h1 : A
#lemma h2 : B
#assembly
exact f h1 h2
#end
"""
AUDIT_LINE = "'thm' depends on axioms: [propext, Classical.choice, Quot.sound]"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

@dataclass
class FakeLeafResult:
    proof: str | None
    attempts: int


@dataclass
class FakeLeaf:
    """Scripted leaf prover: prop -> proof, prop -> attempts it costs.

    Defaults mirror the real adapter's shape — a hit costs one attempt, a miss
    burns the whole `k` it was granted — so budget accounting is exercised
    without any model or cache.
    """
    proofs: dict[str, str] = field(default_factory=dict)
    cost: dict[str, int] = field(default_factory=dict)
    calls: list[tuple[str, int]] = field(default_factory=list)

    def prove(self, prop: str, *, k: int, backend) -> FakeLeafResult:
        self.calls.append((prop, k))
        proof = self.proofs.get(prop)
        n = self.cost.get(prop, 1 if proof else k)
        return FakeLeafResult(proof=proof, attempts=min(n, k))


def leaf_ok() -> FakeLeaf:
    return FakeLeaf(proofs={"A": "pa", "B": "pb", "P": "pp"})


def audit_result(axioms: str = "propext, Classical.choice") -> VerifyResult:
    return VerifyResult(
        ok=True, sorries=0,
        messages=[LeanMessage("info", f"'thm' depends on axioms: [{axioms}]")],
    )


def wire(fb, *, stmt_ok=True, plan_ok=True, artifact=audit_result) -> None:
    """Register the three snippet classes an episode sends, in match order."""
    fb.rule(lambda c: "#print axioms" in c,
            artifact() if callable(artifact) else artifact)
    fb.rule(lambda c: c.startswith("theorem _plan"),
            VerifyResult(ok=plan_ok, sorries=0,
                         messages=[] if plan_ok else [LeanMessage("error", "unsolved goals")]))
    fb.rule(lambda c: c.startswith("theorem _stmt_check"),
            VerifyResult(ok=stmt_ok, sorries=1 if stmt_ok else 0,
                         messages=[] if stmt_ok else [LeanMessage("error", "unknown identifier 'A'")]))


def budgets(**kw) -> Budgets:
    return Budgets(**{"max_lemmas": 8, "leaf_attempts_per_lemma": 4,
                      "max_total_leaf_attempts": 64, **kw})


# ---------------------------------------------------------------------------
# The verified path, and exactly what it sent to Lean
# ---------------------------------------------------------------------------

def test_verified_artifact_is_exact(fake_backend):
    wire(fake_backend)
    r = run_episode(GOAL, PLAN_TEXT, leaf_ok(), fake_backend, budgets())

    assert r.status is Status.VERIFIED
    assert r.reward == 1.0
    assert r.artifact == (
        "theorem thm : P := by\n"
        "  have h1 : A := pa\n"
        "  have h2 : B := pb\n"
        "  exact f h1 h2"
    )
    assert [o.lemma.name for o in r.lemma_outcomes] == ["h1", "h2"]
    assert all(o.status is Status.VERIFIED for o in r.lemma_outcomes)
    assert r.leaf_attempts_used == 2
    assert r.elapsed_s >= 0.0


def test_pipeline_sends_expected_snippets(fake_backend):
    """Stage 4 batches the statement checks; stage 5 is the hypothesis-binder
    plan check; stage 7/8 is one call, not two (§5.2 + the audit-context note)."""
    wire(fake_backend)
    r = run_episode(GOAL, PLAN_TEXT, leaf_ok(), fake_backend, budgets())
    plan = r.plan

    assert fake_backend.calls[:2] == [statement_check("A"), statement_check("B")]
    assert fake_backend.calls[2] == plan_check(GOAL, plan)
    assert len(fake_backend.calls) == 4


def test_axiom_audit_runs_in_the_artifact_check(fake_backend):
    """`#print axioms` must ride along with the artifact: a fresh environment
    would not know the theorem, and a vacuous audit is worse than none."""
    wire(fake_backend)
    r = run_episode(GOAL, PLAN_TEXT, leaf_ok(), fake_backend, budgets())

    audits = [c for c in fake_backend.calls if "#print axioms" in c]
    assert len(audits) == 1
    assert audits[0] == f"{r.artifact}\n#print axioms thm\n"
    assert audits[0].index("theorem thm") < audits[0].index("#print axioms thm")


# ---------------------------------------------------------------------------
# One test per failure status
# ---------------------------------------------------------------------------

def test_format_error(fake_backend):
    r = run_episode(GOAL, "no markers at all", leaf_ok(), fake_backend, budgets())
    assert r.status is Status.FORMAT_ERROR
    assert "no plan markers" in r.detail
    assert r.plan is None
    assert fake_backend.calls == []


def test_format_error_on_goal_name_collision(fake_backend):
    """A lemma named like the goal would shadow it. Rejected, never renamed —
    silent repair would corrupt the trajectory-isomorphism analysis (§5.7 P2)."""
    text = "#lemma thm : A\n#assembly\nexact thm\n#end\n"
    r = run_episode(GOAL, text, leaf_ok(), fake_backend, budgets())
    assert r.status is Status.FORMAT_ERROR
    assert "thm" in r.detail and "goal" in r.detail
    assert fake_backend.calls == []


def test_sanitizer_rejects_input_lemma(fake_backend):
    text = "#lemma h1 : A ∧ (by sorry)\n#assembly\nexact h1\n#end\n"
    r = run_episode(GOAL, text, leaf_ok(), fake_backend, budgets())
    assert r.status is Status.SANITIZER_REJECTED
    assert "h1" in r.detail and "sorry" in r.detail
    assert fake_backend.calls == []


def test_sanitizer_rejects_input_assembly(fake_backend):
    text = "#lemma h1 : A\n#assembly\nexact native_decide\n#end\n"
    r = run_episode(GOAL, text, leaf_ok(), fake_backend, budgets())
    assert r.status is Status.SANITIZER_REJECTED
    assert "assembly" in r.detail
    assert fake_backend.calls == []


def test_sanitizer_rejects_bad_axiom_in_audit(fake_backend):
    """The kernel is happy; the proof term is not. sorryAx is the backstop."""
    wire(fake_backend, artifact=lambda: audit_result("propext, sorryAx"))
    r = run_episode(GOAL, PLAN_TEXT, leaf_ok(), fake_backend, budgets())
    assert r.status is Status.SANITIZER_REJECTED
    assert "sorryAx" in r.detail
    assert r.artifact is not None  # it did pass the kernel; keep the evidence


def test_sanitizer_rejects_unaudited_artifact(fake_backend):
    """No recognizable `#print axioms` output = unaudited = rejected. Failing
    open here would score a silently unaudited artifact as verified."""
    wire(fake_backend, artifact=VerifyResult(ok=True, sorries=0, messages=[]))
    r = run_episode(GOAL, PLAN_TEXT, leaf_ok(), fake_backend, budgets())
    assert r.status is Status.SANITIZER_REJECTED
    assert "not recognized" in r.detail or "axiom" in r.detail


def test_sanitizer_rejects_a_leaf_proof_before_the_kernel(fake_backend):
    """A `sorry` smuggled in by the leaf is a sanitizer rejection, not a
    COMPOSE_FAILED — that bucket means "harness bug, investigate" (core/types).
    The lexical gates run before the expensive check, so no audit is sent."""
    wire(fake_backend)
    r = run_episode(GOAL, PLAN_TEXT, FakeLeaf(proofs={"A": "pa", "B": "by sorry"}),
                    fake_backend, budgets())
    assert r.status is Status.SANITIZER_REJECTED
    assert "sorry" in r.detail
    assert not any("#print axioms" in c for c in fake_backend.calls)
    assert r.artifact is None


def test_statement_ill_formed_names_the_lemma(fake_backend):
    wire(fake_backend)
    fake_backend.rules.insert(0, (
        lambda c: c == statement_check("B"),
        VerifyResult(ok=False, sorries=0, messages=[LeanMessage("error", "unknown identifier 'B'")]),
    ))
    r = run_episode(GOAL, PLAN_TEXT, leaf_ok(), fake_backend, budgets())
    assert r.status is Status.STATEMENT_ILL_FORMED
    assert "'h2'" in r.detail and "unknown identifier" in r.detail


def test_statement_check_requires_exactly_one_sorry(fake_backend):
    """ok but zero sorries means the snippet did not elaborate the way we think
    it did; treat it as ill-formed rather than trusting the shape."""
    wire(fake_backend, stmt_ok=True)
    fake_backend.rules.insert(0, (lambda c: c == statement_check("A"),
                                  VerifyResult(ok=True, sorries=0)))
    r = run_episode(GOAL, PLAN_TEXT, leaf_ok(), fake_backend, budgets())
    assert r.status is Status.STATEMENT_ILL_FORMED
    assert "sorries=0, expected 1" in r.detail


def test_plan_invalid(fake_backend):
    """Stage 1 fails *granting* the lemmas: the decomposition itself is wrong,
    and no leaf is ever called (§5.2 — this is the whole point of the split)."""
    wire(fake_backend, plan_ok=False)
    leaf = leaf_ok()
    r = run_episode(GOAL, PLAN_TEXT, leaf, fake_backend, budgets())
    assert r.status is Status.PLAN_INVALID
    assert "unsolved goals" in r.detail
    assert leaf.calls == []
    assert r.lemma_outcomes == []


def test_leaf_failed_records_attempted_lemmas_only(fake_backend):
    wire(fake_backend)
    leaf = FakeLeaf(proofs={"A": "pa"})  # B never closes
    r = run_episode(GOAL, PLAN_TEXT, leaf, fake_backend, budgets())

    assert r.status is Status.LEAF_FAILED
    assert "'h2'" in r.detail
    # h1 verified, h2 failed, nothing else: absence == never attempted.
    assert [(o.lemma.name, o.status) for o in r.lemma_outcomes] == [
        ("h1", Status.VERIFIED), ("h2", Status.LEAF_FAILED)
    ]
    assert r.leaf_attempts_used == 1 + 4
    assert r.artifact is None


def test_compose_failed_carries_the_artifact(fake_backend):
    """Plan checked, leaves verified, spliced result rejected by the kernel:
    a harness bug or name capture. The detail must be enough to reproduce it."""
    wire(fake_backend, artifact=VerifyResult(
        ok=False, sorries=0, messages=[LeanMessage("error", "type mismatch at h1")]))
    r = run_episode(GOAL, PLAN_TEXT, leaf_ok(), fake_backend, budgets())
    assert r.status is Status.COMPOSE_FAILED
    assert "type mismatch at h1" in r.detail
    assert "theorem thm : P := by" in r.detail
    assert r.artifact is None  # never passed the kernel; do not advertise it


def test_budget_exhausted_on_lemma_count(fake_backend):
    text = "".join(f"#lemma h{i} : A{i}\n" for i in range(5)) + "#assembly\ntrivial\n#end\n"
    r = run_episode(GOAL, text, leaf_ok(), fake_backend, budgets(max_lemmas=4))
    assert r.status is Status.BUDGET_EXHAUSTED
    assert "max_lemmas=4" in r.detail
    assert fake_backend.calls == []


def test_budget_exhausted_mid_episode_keeps_outcomes(fake_backend):
    """Three lemmas, six total attempts, four per lemma: the first two lemmas
    burn the budget and the third never gets a call."""
    text = "#lemma h1 : A\n#lemma h2 : B\n#lemma h3 : C\n#assembly\nexact f h1 h2 h3\n#end\n"
    wire(fake_backend)
    fake_backend.rule(lambda c: c == statement_check("C"), VerifyResult(ok=True, sorries=1))
    leaf = FakeLeaf(proofs={"A": "pa", "B": "pb", "C": "pc"}, cost={"A": 4, "B": 2})
    r = run_episode(GOAL, text, leaf, fake_backend, budgets(max_total_leaf_attempts=6))

    assert r.status is Status.BUDGET_EXHAUSTED
    assert "h3" in r.detail and "2/3 lemmas attempted" in r.detail
    assert [(o.lemma.name, o.attempts_used) for o in r.lemma_outcomes] == [("h1", 4), ("h2", 2)]
    assert r.leaf_attempts_used == 6
    assert [p for p, _ in leaf.calls] == ["A", "B"]


def test_leaf_k_is_clipped_to_the_remaining_budget(fake_backend):
    """A lemma that only got a clipped k and failed is budget evidence, not
    leaf evidence — the lemma outcome still says LEAF_FAILED (it is unproved),
    but the episode status must not blame the prover (§6)."""
    wire(fake_backend)
    leaf = FakeLeaf(proofs={"A": "pa"}, cost={"A": 3})
    r = run_episode(GOAL, PLAN_TEXT, leaf, fake_backend, budgets(max_total_leaf_attempts=5))

    assert leaf.calls == [("A", 4), ("B", 2)]  # second call clipped 4 -> 2
    assert r.status is Status.BUDGET_EXHAUSTED
    assert "budget-clipped" in r.detail
    assert r.lemma_outcomes[-1].status is Status.LEAF_FAILED
    assert r.leaf_attempts_used == 5


# ---------------------------------------------------------------------------
# Direct plans and the close action
# ---------------------------------------------------------------------------

DIRECT_TEXT = "#assembly\nsimpa using pp\n#end\n"


def test_direct_plan_verified(fake_backend):
    fake_backend.rule(lambda c: "#print axioms" in c, audit_result())
    leaf = FakeLeaf()  # never consulted
    r = run_episode(GOAL, DIRECT_TEXT, leaf, fake_backend, budgets())

    assert r.status is Status.VERIFIED
    assert r.plan.is_direct
    assert r.artifact == "theorem thm : P :=\n  simpa using pp"
    assert leaf.calls == []
    assert r.leaf_attempts_used == 0
    assert len(fake_backend.calls) == 1  # proof check and audit are the same call


def test_direct_plan_invalid(fake_backend):
    """A failing direct assembly is a bad plan, not a compose bug: the artifact
    is verbatim what the policy emitted."""
    fake_backend.rule(lambda c: "#print axioms" in c,
                      VerifyResult(ok=False, messages=[LeanMessage("error", "unsolved goals")]))
    r = run_episode(GOAL, DIRECT_TEXT, FakeLeaf(), fake_backend, budgets())
    assert r.status is Status.PLAN_INVALID
    assert "unsolved goals" in r.detail
    assert r.artifact is None


def test_run_direct_close_verified(fake_backend):
    fake_backend.rule(lambda c: "#print axioms" in c, audit_result())
    leaf = leaf_ok()
    r = run_direct_close(GOAL, leaf, fake_backend, budgets())

    assert r.status is Status.VERIFIED
    assert r.artifact == "theorem thm : P :=\n  pp"
    assert leaf.calls == [("P", 4)]
    assert r.leaf_attempts_used == 1
    assert [(o.lemma.name, o.status) for o in r.lemma_outcomes] == [("thm", Status.VERIFIED)]
    assert r.plan is None


def test_run_direct_close_leaf_failed(fake_backend):
    r = run_direct_close(GOAL, FakeLeaf(), fake_backend, budgets(leaf_attempts_per_lemma=3))
    assert r.status is Status.LEAF_FAILED
    assert r.leaf_attempts_used == 3
    assert fake_backend.calls == []


def test_run_direct_close_audits_axioms(fake_backend):
    fake_backend.rule(lambda c: "#print axioms" in c, audit_result("Lean.ofReduceBool"))
    r = run_direct_close(GOAL, leaf_ok(), fake_backend, budgets())
    assert r.status is Status.SANITIZER_REJECTED
    assert "ofReduceBool" in r.detail


# ---------------------------------------------------------------------------
# Statuses this module must never invent
# ---------------------------------------------------------------------------

def test_backend_errors_propagate(fake_backend):
    """Infrastructure failure is not evidence (§6): it must reach the runner,
    which writes the error row that repair_errors.py later re-runs."""
    fake_backend.rule(lambda c: True, VerifyResult(ok=True))

    class Boom:
        def check(self, code, *, timeout_s=120.0):
            raise RuntimeError("lean server died")

        def check_many(self, codes, *, timeout_s=120.0):
            raise RuntimeError("lean server died")

        def close(self):
            pass

    with pytest.raises(RuntimeError, match="lean server died"):
        run_episode(GOAL, PLAN_TEXT, leaf_ok(), Boom(), budgets())


# ---------------------------------------------------------------------------
# composer
# ---------------------------------------------------------------------------

def test_composer_rejects_reserved_and_duplicate_names():
    """parse_plan guards model output; programmatic plans (oracle replay, the
    depth-2 probe) skip it, so composer re-checks."""
    dup = DecompositionPlan([LemmaSpec("h1", "A"), LemmaSpec("h1", "B")], "trivial")
    with pytest.raises(composer.NameHygieneError, match="duplicate"):
        composer.check_names(GOAL, dup)

    reserved = DecompositionPlan([LemmaSpec("_plan", "A")], "trivial")
    with pytest.raises(composer.NameHygieneError, match="reserved"):
        composer.check_names(GOAL, reserved)


def test_composer_allows_default_goal_name():
    """`goal` is in RESERVED_NAMES *and* is GoalSpec's default name — that is
    the protection working, not a collision."""
    plan = DecompositionPlan([LemmaSpec("h1", "A")], "exact h1")
    composer.check_names(GoalSpec(id="g", prop="P"), plan)


def test_build_artifact_matches_leancode_compose():
    plan = DecompositionPlan([LemmaSpec("h1", "A")], "exact h1")
    proofs = {"h1": "pa"}
    assert composer.build_artifact(GOAL, plan, proofs) == compose(GOAL, plan, proofs)
    with pytest.raises(ValueError, match="no leaf proof"):
        composer.build_artifact(GOAL, plan, {})


def test_with_axiom_audit_appends_to_the_same_snippet():
    assert composer.with_axiom_audit("theorem thm : P := by trivial", "thm") == (
        "theorem thm : P := by trivial\n#print axioms thm\n"
    )


# ---------------------------------------------------------------------------
# detectors (DIRECTION.md §5.7 P4)
# ---------------------------------------------------------------------------

def test_restatement_similarity_extremes():
    goal = "∀ n : ℕ, n + 0 = n"
    assert detectors.restatement_similarity(goal, goal) == 1.0
    assert detectors.restatement_similarity(goal, "  ∀ n : ℕ,   n + 0 = n  ") == 1.0
    assert detectors.restatement_similarity(goal, "∀ n : ℕ, n + 0 = n -- comment") > 0.95
    assert detectors.restatement_similarity(goal, "Continuous fun x : ℝ => Real.exp x") < 0.4


def test_plan_stats_flags_a_restatement():
    goal = GoalSpec(id="g", prop="∀ n : ℕ, n + 0 = n", name="thm")
    honest = DecompositionPlan([LemmaSpec("h1", "0 < 1"), LemmaSpec("h2", "2 ∣ 4")], "trivial")
    degenerate = DecompositionPlan([LemmaSpec("h1", "∀ n : ℕ, n + 0 = n")], "exact h1")

    s = detectors.plan_stats(honest, goal)
    assert s["n_lemmas"] == 2 and not s["is_direct"]
    assert s["max_prop_chars"] == max(len("0 < 1"), len("2 ∣ 4"))
    assert s["mean_prop_chars"] == pytest.approx(5.0)
    assert s["restatement_max"] < 0.5

    assert detectors.plan_stats(degenerate, goal)["restatement_max"] == 1.0

    direct = detectors.plan_stats(DecompositionPlan([], "trivial"), goal)
    assert direct == {"n_lemmas": 0, "mean_prop_chars": 0.0, "max_prop_chars": 0,
                      "restatement_max": 0.0, "is_direct": True}
