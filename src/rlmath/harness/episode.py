"""The episode runner: one root completion in, one typed outcome out.

Implements the decomposition MDP of DIRECTION.md §5.1 and the two-stage
verification of §5.2. One call = one root action rollout, evaluated as a fixed
pipeline of stages; **the first failing stage names the status**, and every
status carries a `detail` naming the offending lemma / message. Status
separation is non-negotiable (§6): `plan_invalid` vs `leaf_failed` vs
`budget_exhausted` must never share a bucket or Phase 3's transfer plot is
uninterpretable after the fact.

Pipeline (decompose action):

  1 parse          plan_format.parse_plan            -> FORMAT_ERROR
    name hygiene   composer.check_names              -> FORMAT_ERROR
  2 sanitize in    every lemma prop + the assembly   -> SANITIZER_REJECTED
  3 budgets        len(lemmas) <= max_lemmas         -> BUDGET_EXHAUSTED
  4 elaborate      statement_check, ok & sorries==1  -> STATEMENT_ILL_FORMED
  5 plan check     plan_check,     ok & sorries==0   -> PLAN_INVALID
  6 leaves         leaf.prove per lemma              -> LEAF_FAILED / BUDGET_EXHAUSTED
  7 compose        scan + single-theorem, then the
                   kernel, ok & sorries==0           -> SANITIZER_REJECTED / COMPOSE_FAILED
  8 audit          #print axioms, same backend call  -> SANITIZER_REJECTED
  9                                                  -> VERIFIED

Stage 4 before 5 is deliberate: an ill-formed lemma statement makes the stage-1
plan check fail for a reason that has nothing to do with the plan, and
attributing that to PLAN_INVALID would poison the very signal §5.2 exists to
isolate. Stage 5 before 6 is the design gift itself — the plan is judged
independent of leaf luck.

Direct plans (`plan.is_direct`, the `close` action) skip 4–6: the assembly *is*
the proof, so stage 5 becomes a full proof check of the artifact and stages 7–9
collapse into the audit of that same artifact.

Two things this module deliberately does NOT do:

  * It never returns `Status.ERROR` or `CONTEXT_WINDOW_EXCEEDED`. Backend
    explosions and timeouts propagate to the caller: the eval runner records the
    error row and `repair_errors.py` re-runs exactly those samples (../rl
    pattern, §6). Infrastructure failure is not evidence, and swallowing it here
    would turn a retryable blip into a scored policy failure. The window guard
    likewise belongs to the runner, which knows the root model's context size.
  * It never repairs the policy's output (see composer.py).

The root never sees any of the proof text produced here (§5.1 context
isolation); artifacts go to the kernel and the result log only.
"""
from __future__ import annotations

import time
from typing import Any, Protocol, runtime_checkable

from rlmath.core import leancode
from rlmath.core.backend import LeanBackend
from rlmath.core.plan_format import PlanFormatError, parse_plan
from rlmath.core.types import (
    Budgets,
    EpisodeResult,
    GoalSpec,
    LemmaOutcome,
    LemmaSpec,
    Status,
    VerifyResult,
)

from . import composer

_DETAIL_CHARS = 400  # cap per failure detail; full text lives in the Lean log


@runtime_checkable
class LeafProver(Protocol):
    """The frozen leaf adapter (DIRECTION.md §5.3), duck-typed.

    `prove` gets up to `k` attempts at `prop` and is responsible for verifying
    its own candidates through `backend` (it owns the statement-keyed cache, so
    it is the only component that can dedupe them). It returns a result carrying
    a kernel-verified proof or None, plus how many attempts it actually spent —
    see `_leaf_result` for the shapes accepted.
    """

    def prove(self, prop: str, *, k: int, backend: LeanBackend) -> Any: ...


# ---------------------------------------------------------------------------
# Episode
# ---------------------------------------------------------------------------

def run_episode(
    goal: GoalSpec,
    plan_text: str,
    leaf: LeafProver,
    backend: LeanBackend,
    budgets: Budgets,
) -> EpisodeResult:
    """Score one root completion against `goal`. See the module docstring."""
    t0 = time.monotonic()

    def done(status: Status, **kw) -> EpisodeResult:
        return EpisodeResult(status=status, goal=goal, elapsed_s=time.monotonic() - t0, **kw)

    # -- 1. parse ----------------------------------------------------------
    try:
        plan = parse_plan(plan_text)
    except PlanFormatError as e:
        return done(Status.FORMAT_ERROR, detail=str(e))
    try:
        composer.check_names(goal, plan)
    except composer.NameHygieneError as e:
        return done(Status.FORMAT_ERROR, plan=plan, detail=str(e))

    # -- 2. sanitize the root's own text -----------------------------------
    scan = _sanitize().scan_source
    sources = [(f"lemma {l.name!r}", l.prop) for l in plan.lemmas] + [("assembly", plan.assembly)]
    for what, src in sources:
        bad = _guard(scan, src)
        if bad:
            return done(Status.SANITIZER_REJECTED, plan=plan, detail=f"{what}: {bad}")

    # -- 3. budgets (hard caps, not penalties — §5.6) -----------------------
    if len(plan.lemmas) > budgets.max_lemmas:
        return done(
            Status.BUDGET_EXHAUSTED,
            plan=plan,
            detail=f"{len(plan.lemmas)} lemmas exceeds max_lemmas={budgets.max_lemmas}",
        )

    # -- direct close: the assembly is the whole proof ----------------------
    if plan.is_direct:
        artifact = leancode.proof_check(goal.prop, plan.assembly, name=goal.name)
        bad = _verify_and_audit(artifact, goal, backend, budgets, Status.PLAN_INVALID)
        if bad:
            status, detail, kernel_ok = bad
            return done(status, plan=plan, detail=detail,
                        artifact=artifact if kernel_ok else None)
        return done(Status.VERIFIED, plan=plan, artifact=artifact)

    # -- 4. elaborate every lemma statement --------------------------------
    codes = [leancode.statement_check(l.prop) for l in plan.lemmas]
    results = backend.check_many(codes, timeout_s=budgets.verify_timeout_s)
    for lemma, r in zip(plan.lemmas, results):
        if not (r.ok and r.sorries == 1):
            return done(
                Status.STATEMENT_ILL_FORMED,
                plan=plan,
                detail=f"lemma {lemma.name!r} does not elaborate ({_why(r, 1)}): {lemma.prop}",
            )

    # -- 5. stage-1 plan check: does the assembly close the goal, granting
    #       the lemmas as hypotheses? (§5.2, independent of leaf luck) ------
    r = backend.check(leancode.plan_check(goal, plan), timeout_s=budgets.verify_timeout_s)
    if not (r.ok and r.sorries == 0):
        return done(
            Status.PLAN_INVALID,
            plan=plan,
            detail=f"assembly does not close the goal granting all "
                   f"{len(plan.lemmas)} lemmas ({_why(r, 0)})",
        )

    # -- 6. discharge the leaves -------------------------------------------
    #
    # `lemma_outcomes` holds one entry per *attempted* lemma, in plan order. We
    # stop at the first failure (the episode is already lost and leaf calls are
    # the expensive part), so a short list means "the rest were never tried" —
    # absence is the representation for untried, rather than a fake status that
    # would inflate leaf-failure rates in the analysis.
    proofs: dict[str, str] = {}
    outcomes: list[LemmaOutcome] = []
    used = 0
    for lemma in plan.lemmas:
        k = min(budgets.leaf_attempts_per_lemma, budgets.max_total_leaf_attempts - used)
        if k <= 0:
            return done(
                Status.BUDGET_EXHAUSTED,
                plan=plan,
                lemma_outcomes=outcomes,
                leaf_attempts_used=used,
                detail=f"max_total_leaf_attempts={budgets.max_total_leaf_attempts} spent before "
                       f"lemma {lemma.name!r} ({len(outcomes)}/{len(plan.lemmas)} lemmas attempted)",
            )
        proof, spent = _leaf_result(leaf.prove(lemma.prop, k=k, backend=backend), k=k)
        used += spent
        outcomes.append(LemmaOutcome(
            lemma=lemma,
            status=Status.VERIFIED if proof else Status.LEAF_FAILED,
            proof=proof,
            attempts_used=spent,
        ))
        if not proof:
            # A lemma whose attempt budget was clipped by the episode-wide cap
            # did not get a fair try: report the cap, not the leaf. The *lemma*
            # outcome stays LEAF_FAILED (it is unproved); only the episode
            # status changes, keeping the two levels of evidence separate (§6).
            clipped = k < budgets.leaf_attempts_per_lemma
            note = f" (budget-clipped from k={budgets.leaf_attempts_per_lemma})" if clipped else ""
            return done(
                Status.BUDGET_EXHAUSTED if clipped else Status.LEAF_FAILED,
                plan=plan,
                lemma_outcomes=outcomes,
                leaf_attempts_used=used,
                detail=f"leaf found no verified proof for lemma {lemma.name!r} in "
                       f"{spent} attempt(s){note}: {lemma.prop}",
            )
        proofs[lemma.name] = proof

    # -- 7/8. compose, kernel-check and audit in one backend call -----------
    artifact = composer.build_artifact(goal, plan, proofs)
    bad = _verify_and_audit(artifact, goal, backend, budgets, Status.COMPOSE_FAILED)
    if bad:
        status, detail, kernel_ok = bad
        return done(status, plan=plan, lemma_outcomes=outcomes, leaf_attempts_used=used,
                    detail=detail, artifact=artifact if kernel_ok else None)

    # -- 9. --------------------------------------------------------------
    return done(Status.VERIFIED, plan=plan, lemma_outcomes=outcomes,
                leaf_attempts_used=used, artifact=artifact)


def run_direct_close(
    goal: GoalSpec,
    leaf: LeafProver,
    backend: LeanBackend,
    budgets: Budgets,
) -> EpisodeResult:
    """The `close` action (§5.1): hand the goal straight to the leaf prover.

    Also the flat-arm baseline — the same goal, same leaf, no decomposition —
    so control and treatment share one scoring path and one sanitizer.

    The goal is recorded in `lemma_outcomes` as its own pseudo-lemma so
    attempt accounting is uniform with `run_episode` in the analysis.
    """
    t0 = time.monotonic()

    def done(status: Status, **kw) -> EpisodeResult:
        return EpisodeResult(status=status, goal=goal, elapsed_s=time.monotonic() - t0, **kw)

    k = min(budgets.leaf_attempts_per_lemma, budgets.max_total_leaf_attempts)
    if k <= 0:
        return done(Status.BUDGET_EXHAUSTED,
                    detail=f"no leaf attempts available (max_total_leaf_attempts="
                           f"{budgets.max_total_leaf_attempts})")

    proof, spent = _leaf_result(leaf.prove(goal.prop, k=k, backend=backend), k=k)
    outcome = LemmaOutcome(
        lemma=LemmaSpec(name=goal.name, prop=goal.prop),
        status=Status.VERIFIED if proof else Status.LEAF_FAILED,
        proof=proof,
        attempts_used=spent,
    )
    if not proof:
        return done(Status.LEAF_FAILED, lemma_outcomes=[outcome], leaf_attempts_used=spent,
                    detail=f"leaf found no verified proof for the goal in {spent} attempt(s)")

    artifact = leancode.proof_check(goal.prop, proof, name=goal.name)
    bad = _verify_and_audit(artifact, goal, backend, budgets, Status.COMPOSE_FAILED)
    if bad:
        status, detail, kernel_ok = bad
        return done(status, lemma_outcomes=[outcome], leaf_attempts_used=spent,
                    detail=detail, artifact=artifact if kernel_ok else None)
    return done(Status.VERIFIED, lemma_outcomes=[outcome], leaf_attempts_used=spent,
                artifact=artifact)


# ---------------------------------------------------------------------------
# Verification + audit
# ---------------------------------------------------------------------------

def _verify_and_audit(
    artifact: str,
    goal: GoalSpec,
    backend: LeanBackend,
    budgets: Budgets,
    fail_status: Status,
) -> tuple[Status, str, bool] | None:
    """Sanitize, kernel-check and axiom-audit the artifact. None if it is clean.

    The kernel check and the audit must share ONE backend call: `#print axioms`
    resolves against the environment of the snippet it appears in, and each
    `check()` elaborates a fresh one, so an audit sent on its own would only
    ever report an unknown identifier.

    The two *lexical* gates run before that call. They are pure and cheap, so
    ordering them first saves the expensive check — but the real reason is
    attribution: a leaf proof carrying a `sorry` would otherwise surface as
    COMPOSE_FAILED, a status that means "harness bug or name capture, always
    investigate" (core/types.py). It is neither; it is a sanitizer rejection.

    `fail_status` is what a *kernel* failure means at this point in the
    pipeline: COMPOSE_FAILED after a passed plan check (detail carries the whole
    artifact, since reproducing it is the first debugging step), PLAN_INVALID
    for a direct plan, where the artifact is the policy's own assembly.

    The third element of the rejection tuple says whether the artifact reached
    and passed the kernel — only then may the caller put it in
    `EpisodeResult.artifact`, which is documented as kernel-checked source.
    """
    sanitize = _sanitize()
    for gate, args in ((sanitize.scan_source, (artifact,)),
                       (sanitize.enforce_single_theorem, (artifact, goal.name))):
        bad = _guard(gate, *args)
        if bad:
            return (Status.SANITIZER_REJECTED,
                    f"composed artifact: {bad}\n--- artifact ---\n{artifact}", False)

    r = backend.check(composer.with_axiom_audit(artifact, goal.name),
                      timeout_s=budgets.verify_timeout_s)
    if not (r.ok and r.sorries == 0):
        return fail_status, (f"artifact failed the kernel ({_why(r, 0)})"
                             f"\n--- artifact ---\n{artifact}"), False

    text = "\n".join(m.text for m in r.messages)
    bad = _guard(sanitize.audit_axiom_output, text)
    if bad:
        return Status.SANITIZER_REJECTED, f"axiom audit for {goal.name!r}: {bad}", True
    return None


def _why(r: VerifyResult, want_sorries: int) -> str:
    """One-line reason a VerifyResult did not meet the caller's sorry policy."""
    if r.errors:
        joined = "; ".join(" ".join(m.text.split()) for m in r.errors[:3])
        return joined[:_DETAIL_CHARS]
    if r.sorries != want_sorries:
        return f"sorries={r.sorries}, expected {want_sorries}"
    return "no error messages reported"


# ---------------------------------------------------------------------------
# Seams to the other §5.1 components
# ---------------------------------------------------------------------------

def _sanitize():
    """Lazy import: `rlmath.sanitize` is a separate component (§5.1) and this
    keeps `import rlmath.harness` free of its load order."""
    from rlmath import sanitize

    return sanitize


def _guard(fn, *args) -> str | None:
    """Call one sanitize gate: None if clean, else a one-line rejection detail.

    The gates return a list of violation strings. An exception from one is also
    a rejection — a gate that crashed did not clear the artifact, and failing
    open here would hand the policy exactly the hole sanitize.py exists to
    close (its module docstring).
    """
    try:
        violations = fn(*args)
    except Exception as e:
        return f"{type(e).__name__}: {e}"
    return "; ".join(str(v) for v in violations)[:_DETAIL_CHARS] if violations else None


def _leaf_result(res: Any, *, k: int) -> tuple[str | None, int]:
    """Normalize a leaf return into (verified proof or None, attempts spent).

    The one place that touches the leaf adapter's return shape, so a contract
    that settles differently (result object, pair, bare proof) is a fix here
    rather than a scatter of call sites. Permissive about shape, never about
    verdict: `verified is False` clears the proof.

    An unknown attempt count is charged as the full `k` the leaf was granted:
    over-charging ends an episode early, under-charging would silently blow the
    episode-wide cap, and §5.6's budgets exist to bound compute.
    """
    if res is None:
        return None, k
    if isinstance(res, str):
        return (res or None), (1 if res else k)
    if isinstance(res, tuple) and len(res) == 2:
        proof, n = res
        if isinstance(n, (list, tuple)):  # leaf adapter's actual contract: list[AttemptRecord]
            n = len(n)
        return (proof or None), (k if n is None else int(n))
    proof = getattr(res, "proof", None)
    if getattr(res, "verified", True) is False:
        proof = None
    n = getattr(res, "attempts_used", None)
    if n is None:
        n = getattr(res, "attempts", None)
    if isinstance(n, (list, tuple)):  # e.g. a list of AttemptRecord
        n = len(n)
    return (proof or None), (k if n is None else int(n))
