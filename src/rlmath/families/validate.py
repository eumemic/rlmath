"""Self-certification checks V0–V6 for generated problems (FAMILIES.md table).

Everything here is kernel-decided: a problem is valid iff Lean says its goal
elaborates, its witnesses prove, its oracle plan closes granting the lemmas,
the composed artifact passes kernel + sanitizer, and neither the goal nor any
leaf falls to the automation battery. No LM is involved — this is what makes
oracle-replay a *ceiling*, not an estimate.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from rlmath.core import leancode
from rlmath.core.backend import LeanBackend
from rlmath.core.types import normalize_statement
from rlmath.sanitize import audit_axioms, enforce_single_theorem, parse_axiom_output, scan_source

from .types import GeneratedProblem

# V0/V5 battery (FAMILIES.md): ANY success fails the check. Extending this list
# strengthens every family retroactively; keep it in one place.
AUTOMATION_TACTICS = ("simp", "aesop", "norm_num", "omega", "decide", "linarith", "positivity")
AUTOMATION_TIMEOUT_S = 25.0


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class ValidationReport:
    problem_id: str
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(name, ok, detail[:300]))

    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]


def _resists_automation(prop: str, backend: LeanBackend, label: str, report: ValidationReport) -> None:
    codes = [leancode.proof_check(prop, f"by {t}") for t in AUTOMATION_TACTICS]
    results = backend.check_many(codes, timeout_s=AUTOMATION_TIMEOUT_S)
    closed = [t for t, r in zip(AUTOMATION_TACTICS, results) if r.ok and r.sorries == 0]
    report.add(label, not closed, f"auto-closable by: {', '.join(closed)}" if closed else "")


def validate_problem(
    problem: GeneratedProblem,
    backend: LeanBackend,
    *,
    check_automation: bool = True,   # False = fast structural pass during schema iteration
    timeout_s: float = 120.0,
) -> ValidationReport:
    r = ValidationReport(problem_id=problem.id)
    goal, plan = problem.goal, problem.oracle_plan

    # structural preconditions (free): plan lemma names must match witness keys exactly
    plan_names = [l.name for l in plan.lemmas]
    if set(plan_names) != set(problem.witnesses) or len(plan_names) != len(set(plan_names)):
        r.add("structure", False, f"plan lemmas {plan_names} != witness keys {sorted(problem.witnesses)}")
        return r  # nothing downstream is meaningful
    r.add("structure", True)

    # V1 goal elaborates
    res = backend.check(leancode.statement_check(goal.prop), timeout_s=timeout_s)
    r.add("V1_goal_elaborates", res.ok and res.sorries == 1,
          "; ".join(m.text for m in res.errors))
    if not r.checks[-1].ok:
        return r

    # V0 goal resists automation
    if check_automation:
        _resists_automation(goal.prop, backend, "V0_goal_resists_automation", r)

    # V2 witnesses: props elaborate, proofs check (batched)
    stmt_codes = [leancode.statement_check(l.prop) for l in plan.lemmas]
    proof_codes = [leancode.proof_check(problem.witnesses[l.name].prop, problem.witnesses[l.name].proof)
                   for l in plan.lemmas]
    for l, res in zip(plan.lemmas, backend.check_many(stmt_codes, timeout_s=timeout_s)):
        r.add(f"V2_stmt[{l.name}]", res.ok and res.sorries == 1, "; ".join(m.text for m in res.errors))
    for l, res in zip(plan.lemmas, backend.check_many(proof_codes, timeout_s=timeout_s)):
        r.add(f"V2_proof[{l.name}]", res.ok and res.sorries == 0, "; ".join(m.text for m in res.errors))

    # V3 stage-1 plan check
    res = backend.check(leancode.plan_check(goal, plan), timeout_s=timeout_s)
    r.add("V3_plan_check", res.ok and res.sorries == 0, "; ".join(m.text for m in res.errors))

    # V4 full oracle compose -> kernel + sanitizer + axiom audit (mirrors episode stages 7-8)
    artifact = leancode.compose(goal, plan, problem.witness_proofs())
    viol = scan_source(artifact) + enforce_single_theorem(artifact, goal.name)
    audited = artifact + "\n" + leancode.axiom_audit(goal.name)
    res = backend.check(audited, timeout_s=timeout_s)
    axioms = parse_axiom_output(" ".join(m.text for m in res.messages))
    viol += audit_axioms(axioms)
    r.add("V4_oracle_replay", res.ok and res.sorries == 0 and not viol,
          "; ".join(m.text for m in res.errors) or "; ".join(viol))

    # V5 leaves resist automation
    if check_automation:
        for l in plan.lemmas:
            _resists_automation(l.prop, backend, f"V5_leaf_resists[{l.name}]", r)

    # V6 hidden intermediates
    visible = set(problem.meta.get("visible_lemmas", ()))
    goal_norm = normalize_statement(goal.prop)
    for l in plan.lemmas:
        if l.name in visible:
            continue
        r.add(f"V6_hidden[{l.name}]", normalize_statement(l.prop) not in goal_norm,
              "lemma prop is a substring of the goal")

    return r
