"""Lean source generation primitives.

All Lean code strings are built here or in harness/composer.py — nowhere else —
so name hygiene, preambles, and the axiom whitelist stay auditable in one place.

Design note (DIRECTION.md §5.2): the two-stage check needs no `axiom`
declarations — stage 1 grants the lemmas as *hypotheses* of a throwaway
theorem, so the sanitizer's axiom audit stays clean and strict.
"""
from __future__ import annotations

import textwrap

from .types import DecompositionPlan, GoalSpec

PREAMBLE = "import Mathlib\n"

# Standard axioms any Mathlib proof may depend on. Everything else — sorryAx,
# Lean.ofReduceBool/ofReduceNat (native_decide), user axioms — is rejected.
ALLOWED_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})

# Declaration names reserved by the harness; the plan parser rejects them and
# composer must never let a lemma shadow them.
RESERVED_NAMES = frozenset({"_stmt_check", "_proof_check", "_plan", "goal", "this"})


def _indent(block: str, n: int = 2) -> str:
    return textwrap.indent(textwrap.dedent(block).strip("\n"), " " * n)


def statement_check(prop: str, name: str = "_stmt_check") -> str:
    """Elaboration check: compiles iff `prop` is a well-formed closed proposition.

    Caller must require ok=True AND sorries == 1 (the sorry is the point:
    no proving happens, only elaboration — this is the cheap loud check that
    replaces ../rl's silent format-failure mode).
    """
    return f"theorem {name} : {prop} := sorry"


def proof_check(prop: str, proof: str, name: str = "_proof_check") -> str:
    """Full kernel check of a candidate proof.

    `proof` is a term or a `by ...` tactic block. Caller requires ok AND sorries == 0.
    """
    return f"theorem {name} : {prop} :=\n{_indent(proof)}"


def plan_check(goal: GoalSpec, plan: DecompositionPlan) -> str:
    """Stage-1 check: does the assembly close the goal *granting* the lemmas
    as hypotheses? Verifies the decomposition independent of leaf luck —
    separates PLAN_INVALID from LEAF_FAILED (DIRECTION.md §5.2)."""
    binders = " ".join(f"({l.name} : {l.prop})" for l in plan.lemmas)
    binders = f" {binders}" if binders else ""
    return f"theorem _plan{binders} : {goal.prop} := by\n{_indent(plan.assembly)}"


def _have(name: str, prop: str, proof: str) -> str:
    p = textwrap.dedent(proof).strip("\n").strip()
    if "\n" in p:
        return f"have {name} : {prop} :=\n{textwrap.indent(p, '  ')}"
    return f"have {name} : {prop} := {p}"


def compose(goal: GoalSpec, plan: DecompositionPlan, proofs: dict[str, str]) -> str:
    """Splice leaf proofs into the plan: the final self-contained artifact.

    Structure: `have <lemma> : <prop> := <leaf proof>` per lemma, then the
    assembly. The root never sees this string (context isolation) — it goes to
    the kernel and the result log only.
    """
    parts = [_have(l.name, l.prop, proofs[l.name]) for l in plan.lemmas]
    parts.append(textwrap.dedent(plan.assembly).strip("\n").strip())
    body = "\n".join(parts)
    return f"theorem {goal.name} : {goal.prop} := by\n{_indent(body)}"


def axiom_audit(name: str) -> str:
    """`#print axioms` command for the named declaration; parse with
    sanitize.parse_axiom_output and check against ALLOWED_AXIOMS."""
    return f"#print axioms {name}"
