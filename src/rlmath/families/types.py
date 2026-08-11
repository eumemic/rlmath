"""Data contract for size-parameterized problem families (FAMILIES.md).

A GeneratedProblem is self-certifying: it carries its reference decomposition
and a kernel-checkable witness proof for every leaf, so validity is decidable
by the Lean kernel with no LM anywhere (validate.py). The oracle plan uses the
same DecompositionPlan shape policies emit — oracle replay and policy episodes
run through the same harness code paths on purpose.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from rlmath.core.types import DecompositionPlan, GoalSpec


@dataclass(frozen=True)
class LeafWitness:
    prop: str
    proof: str  # generator-known proof: a term or a `by ...` block


@dataclass
class GeneratedProblem:
    id: str                            # "<family>-k<k>-s<seed>-<idx>"
    family: str
    k: int                             # size parameter = leaves in the reference decomposition
    seed: int
    goal: GoalSpec
    oracle_plan: DecompositionPlan
    witnesses: dict[str, LeafWitness]  # lemma name -> witness; keys match oracle_plan lemma names
    meta: dict = field(default_factory=dict)
    # meta["visible_lemmas"]: list[str] — lemma names exempt from the V6 hidden-intermediate check

    def witness_proofs(self) -> dict[str, str]:
        return {name: w.proof for name, w in self.witnesses.items()}
