"""Name hygiene between a parsed plan and its goal, plus the composite Lean
strings the episode runner needs.

`core/leancode.py` owns the Lean *primitives*; this module owns everything that
has to reason about **names**, so shadowing bugs have exactly one home (see the
leancode docstring: Lean source is built here or there, nowhere else).

Why collisions are rejected rather than renamed
-----------------------------------------------
A lemma named like the goal shadows it inside the composed `have` block, and a
lemma named like a harness scratch declaration (`_plan`, `_stmt_check`, …)
shadows that. The obvious "fix" is to uniquify silently. We don't, because the
harness must never edit the policy's output: DIRECTION.md §5.7 P2 measures
*content-masked trajectory isomorphism* over exactly the tokens the root
emitted, and §6 insists each failure mode keep its own bucket. A silently
repaired episode would report `verified` for a plan the policy never wrote and
would corrupt the isomorphism analysis after the fact. Rejecting is loud,
countable (`Status.FORMAT_ERROR`), and keeps the trajectory a faithful record.

`parse_plan` already rejects reserved names, `_`-prefixed names, and duplicates
for *model* output. Plans built programmatically — oracle replay (§5.4b), the
depth-2 probe (§5.1), tests — never pass through the parser, and `goal.name` is
dynamic and unknown to it, so the checks are repeated here.
"""
from __future__ import annotations

from rlmath.core import leancode
from rlmath.core.leancode import RESERVED_NAMES
from rlmath.core.types import DecompositionPlan, GoalSpec


class NameHygieneError(ValueError):
    """A lemma name would shadow the goal or a harness declaration.

    The message lands verbatim in `EpisodeResult.detail`; keep it specific.
    """


def check_names(goal: GoalSpec, plan: DecompositionPlan) -> None:
    """Raise NameHygieneError if any lemma name is unusable for this goal.

    Note `goal.name` itself is deliberately *not* checked against
    RESERVED_NAMES: "goal" is both the reserved word (so no lemma may take it)
    and the default `GoalSpec.name`, which is exactly the intended protection.
    """
    seen: set[str] = set()
    for lemma in plan.lemmas:
        name = lemma.name
        if name == goal.name:
            raise NameHygieneError(
                f"lemma name {name!r} collides with the goal declaration name "
                f"{goal.name!r} (it would shadow the goal in the composed proof); "
                "state the lemma under a different name"
            )
        if name in RESERVED_NAMES or name.startswith("_"):
            raise NameHygieneError(f"lemma name {name!r} is reserved by the harness")
        if name in seen:
            raise NameHygieneError(f"duplicate lemma name: {name!r}")
        seen.add(name)


def build_artifact(goal: GoalSpec, plan: DecompositionPlan, proofs: dict[str, str]) -> str:
    """The final self-contained artifact: leaf proofs spliced into the plan.

    Re-checks name hygiene as defense in depth — this string is what reaches the
    kernel and the result log, so it is the last place a shadowing bug can still
    be caught cheaply.
    """
    check_names(goal, plan)
    missing = [l.name for l in plan.lemmas if l.name not in proofs]
    if missing:
        raise ValueError(f"no leaf proof for lemma(s): {', '.join(missing)}")  # harness bug
    return leancode.compose(goal, plan, proofs)


def with_axiom_audit(artifact: str, name: str) -> str:
    """Artifact + `#print axioms <name>` as ONE snippet.

    `#print axioms` resolves against the *current* environment: a fresh
    `check()` of the command alone reports an unknown identifier, since each
    snippet elaborates in its own environment. Appending it to the artifact is
    the simplest construction that audits the very declaration just elaborated
    (DIRECTION.md §5.1, sanitizer / axiom audit).
    """
    return f"{artifact}\n{leancode.axiom_audit(name)}\n"
