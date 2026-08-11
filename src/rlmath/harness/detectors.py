"""Cheap structural detectors over decomposition plans.

These feed the Phase-2 strategy analysis (DIRECTION.md §5.7), the analog of
`../rl/analysis/strategy_stats.py`, which caught the degenerate "offload the
whole task to one sub-call" policy there.

The one that matters is restatement. §5.2's caveat: `r_plan` alone is hackable
by restating the goal as a single lemma and letting the leaf do all the work —
a *decomposition* that decomposes nothing. §5.7 P4 registers the prediction that
degenerate restatement rises under RL and that hard budgets contain it. Testing
that prediction requires the per-episode score to exist from day one, recorded
whether or not anyone is looking at it yet.

Heuristics, not gates: `normalize_statement` is whitespace/comment
normalization only — not α-normalization — so renamed binders defeat it (noted
as future work in §5.4). Use these for aggregate rates across episodes, never to
reject a single episode.
"""
from __future__ import annotations

import difflib
from statistics import fmean

from rlmath.core.types import DecompositionPlan, GoalSpec, normalize_statement


def restatement_similarity(goal_prop: str, lemma_prop: str) -> float:
    """Similarity of a lemma statement to the goal, in [0, 1]; 1.0 = restatement.

    `autojunk=False`: SequenceMatcher's default popularity heuristic kicks in at
    200 characters and would silently change the scale for long statements —
    exactly the beyond-window tier where the number matters most (§5.4e).
    """
    a = normalize_statement(goal_prop)
    b = normalize_statement(lemma_prop)
    if not a or not b:
        return 1.0 if a == b else 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def plan_stats(plan: DecompositionPlan, goal: GoalSpec) -> dict:
    """Per-episode plan shape, for the strategy CSV.

    `restatement_max` is the headline: near 1.0 means the root delegated the
    goal to a leaf under a new name instead of decomposing it.
    """
    props = [l.prop for l in plan.lemmas]
    sims = [restatement_similarity(goal.prop, p) for p in props]
    return {
        "n_lemmas": len(plan.lemmas),
        "mean_prop_chars": fmean(len(p) for p in props) if props else 0.0,
        "max_prop_chars": max((len(p) for p in props), default=0),
        "restatement_max": max(sims, default=0.0),
        "is_direct": plan.is_direct,
    }
