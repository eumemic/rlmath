"""C1 probe — bridge_chain growth laws in the "keep the monomial, bound its growth" family.

Owned by the C1 design agent (research/bc-growth-survey-a.md is the write-up).
READ-ONLY on `src/rlmath/families/bridge_chain.py`: every candidate step form is built
here as PROP/WITNESS STRINGS and checked in Lean. Nothing in the shipped generator is
touched, and `preset "v2"`'s stream is never entered.

What this probe answers (in order):

  1. `--refute`   Can degree ever be *traded* between variables (a sawtooth in the
                  exponent)? Kernel-checked answer, by proving the NEGATION of a
                  degree-decreasing step.
  2. `--offline`  The economy of the schema: which resource pays for a step, how much of
                  it there is, and hence exactly how long a chain can be at a given
                  degree/coefficient budget. Exact DP, no Lean, no LM.
  3. `--lemmas`   Which Mathlib spelling gives `1 ≤ √M` (and the log→√ cross bound) in
                  THIS Mathlib — probed, never guessed.
  4. `--witness`  Kernel-check the candidate witnesses on instances spanning the knob
                  support at k = 2/8/32/128.
  5. `--battery`  Full V0/V5 battery (10 tactics × {bare, intros-first}) on the new leaf
                  type, the shipped leaf type, the goals, and a PLANTED CONTROL that must
                  die.
  6. `--adapt`    The corridor CEILING proxy: six one-hint routes (the sibling family's idiom
                  probe, transplanted) against each leaf kind. This is what found the flat step's
                  slack hole and hence the tightness gate.
  7. `--collapse` The flat one-step route on the GOAL: `hbase/hpow/hstep/hring` +
                  `linarith`, i.e. the generator's own witness applied to the endpoints.
                  Run against the SHIPPED presets as well as the candidates.

Usage (from the repo root):
    uv run python scripts/probes/probe_bc_growth_a.py --offline
    uv run python scripts/probes/probe_bc_growth_a.py --refute --lemmas --witness --battery --collapse
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rlmath.families import bridge_chain as bc

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "research" / "bc_growth_a"
BATTERY_TIMEOUT_S = 25.0
KS = (2, 8, 32, 128)

VARS = bc.VARS
LOWER = bc.LOWER
BINDER = bc.BINDER

Knobs = tuple[int, int, int]          # (c, d, o)


# ==========================================================================
# 0. the step economy — the LP conditions a *linarith* witness can certify
# ==========================================================================
#
# Every term is `c * M + d * √M + o` with `M` a bare monomial over x,y,z ≥ 3
# (this probe fixes `funcs=("sqrt",)`, the e3_lowdeg lineage, so the two
# named-function atoms of a step COINCIDE whenever the monomial does).
#
# A step is certified by `linarith` over the atoms it is handed. Which atoms
# exist depends on whether the monomial moved:
#
#   GROWTH step (M' = v^δ·M, δ ≥ 1): atoms M, M', √M, √M'; facts 1 ≤ M,
#     3^δ·M ≤ M', √M ≤ M, 0 ≤ √M'. Feasibility of the resulting LP is exactly
#     the shipped SAMPLING CONSTRAINT `bc._valid`. Unchanged here, deliberately:
#     the growth leaf must stay byte-identical to the shipped leaf so its
#     measured difficulty carries over.
#
#   FLAT step (M' = M): atoms M and s = √M (ONE atom, because the rendered text
#     is identical on both sides); facts 1 ≤ s ≤ M. The step is
#         A·M + B·s + K ≥ 0   with A = Δc, B = Δd, K = Δo
#     on the polytope {1 ≤ s ≤ M}, whose vertex is (1,1) and whose extreme rays
#     are (M→∞, s fixed) and (M→∞, s=M). So the LP is feasible iff
#         A ≥ 0,   A + B ≥ 0,   A + B + K ≥ 0.
#     This is the whole new step form. It needs ONE new witness line, `1 ≤ √M`.

def flat_ok(prev: Knobs, new: Knobs) -> bool:
    """Is the flat step (M' = M) linarith-certifiable from {1 ≤ √M ≤ M}?"""
    a, b, kk = new[0] - prev[0], new[1] - prev[1], new[2] - prev[2]
    return a >= 0 and a + b >= 0 and a + b + kk >= 0


def growth_ok(prev: Knobs, new: Knobs, delta: int) -> bool:
    return bc._valid(prev, new, delta)


def gate(prev: Knobs, new: Knobs) -> bool:
    """The NOT-a-knob per-step congruence gate (bc.step_resists_congruence)."""
    return bc.step_resists_congruence(prev, new)


# --- the monovariant that bounds a flat run -------------------------------
#
# THEOREM (flat-run bound). On a flat step the gate forces one of (c,d,o) down,
# and the LP forces A ≥ 0 and A+B ≥ 0:
#   * Δo < 0  ⇒ A+B ≥ −K ≥ 1, so c+d strictly rises;
#   * Δd < 0  ⇒ A ≥ −B ≥ 1, so c strictly rises;
#   * Δc < 0  is impossible (A ≥ 0).
# So every flat step strictly decreases Φ = (C−c) + (C+D−c−d) ≥ 0. A flat run
# is therefore at most Φ steps long — the schema has a finite RESERVOIR, and the
# only thing that refills it is a growth step (which divides c by 3^δ and frees d).

def phi(state: Knobs, cand: "Cand") -> int:
    c, d, _o = state
    return (cand.coef[1] - c) + (cand.coef[1] + cand.fcoef[1] - c - d)


# ==========================================================================
# 1. candidates
# ==========================================================================

@dataclass(frozen=True)
class Cand:
    name: str
    coef: tuple[int, int]
    fcoef: tuple[int, int]
    offset: tuple[int, int]
    deltas: tuple[int, ...] = (1,)
    start: tuple[int, int, int] = (1, 0, 0)
    flat_steps: bool = True      # False = the shipped law (growth every step)
    final_growth: bool = True    # last step is a growth step (what lets c_k < c_0 close)
    thrift: int = 1              # allowed slack below the Φ-optimal flat successor
    pace: bool = False           # spend the reservoir at Φ₀/k per step instead of ~1
    tight: bool = False          # require A+B+K == 0: the flat step must be TIGHT at
                                 # (M,s)=(1,1). Slack (A+B+K >= 1) makes the leaf
                                 # `A·M + B·s + K >= 0` unconditionally true given
                                 # `s^2 = M`, so ONE `Real.sq_sqrt` hint closes it at
                                 # any degree (measured, §7.3).
    anticollapse: bool = True
    note: str = ""

    def preset(self) -> bc.DifficultyPreset:
        """A shipped DifficultyPreset with the same ranges — used ONLY to reuse
        `bc.live_states` (growth-liveness) and `bc._valid`. Never generated from."""
        return bc.DifficultyPreset(
            name=f"probe_{self.name}", rationale="probe-only", coef_range=self.coef,
            fcoef_range=self.fcoef, offset_range=self.offset, deltas=self.deltas,
            funcs=("sqrt",), start_exponents=self.start)


CANDS: dict[str, Cand] = {c.name: c for c in (
    # A2 — the reservoir law at the SHIPPED knob ranges (e3_lowdeg's).
    Cand(name="g1_reservoir", coef=(2, 9), fcoef=(1, 9), offset=(1, 9), anticollapse=False,
         note="e3_lowdeg ranges + flat steps: how far does the shipped reservoir reach?"),
    # A2' — ranges widened (linearly in k, per report_frontier) to reach k=32.
    Cand(name="g2_wide", coef=(2, 20), fcoef=(1, 24), offset=(1, 20), anticollapse=False,
         note="frontier says budget 20 reaches k=32 at degree 1→2; widened for variety"),
    # A2'' — ranges for k=128 (still inside the measured-neutral coefficient support)
    Cand(name="g3_k128", coef=(2, 100), fcoef=(1, 100), offset=(1, 40), anticollapse=False,
         note="frontier says budget 82 reaches k=128 at degree 1→2; max|coef| 100"),
    # ablation: pace the reservoir spend at Φ₀/k so the coefficient MARGINAL is
    # k-independent (at the cost of making leaf tightness k-dependent instead)
    Cand(name="g3_paced", coef=(2, 100), fcoef=(1, 100), offset=(1, 40), pace=True,
         anticollapse=False, note="g3 ablation — paced spend: flat c-marginal, k-dependent leaf slack"),
    # LEVEL knob: with growth off the exponent, the START degree is constant in k, so
    # `1 ≤ M` (the measured blocker) becomes a difficulty dial that is flat by
    # construction. es_left is then `sum(start)` at EVERY position and EVERY k.
    Cand(name="g4_deg4", coef=(2, 100), fcoef=(1, 100), offset=(1, 40), start=(2, 1, 1),
         anticollapse=False, note="g3 + start degree 4: es_left == 4 at every k"),
    Cand(name="g5_deg6", coef=(2, 100), fcoef=(1, 100), offset=(1, 40), start=(2, 2, 2),
         anticollapse=False, note="g3 + start degree 6: es_left == 6 at every k"),
    # the TIGHTNESS gate: flat steps must be tight at (M,s)=(1,1), which is exactly
    # what forces the certificate through `1 <= M` (the measured blocker) instead of
    # through an unconditional quadratic. Reach at budget 100: see report_reservoir.
    Cand(name="g6_tight", coef=(2, 100), fcoef=(1, 100), offset=(1, 70), start=(2, 1, 1),
         tight=True, anticollapse=False,
         note="g4 + tightness gate A+B+K == 0 (closes the sq_sqrt hole)"),
    # control — the shipped law (growth every step), rebuilt here for comparability
    Cand(name="s0_shipped", coef=(2, 9), fcoef=(1, 9), offset=(1, 9), flat_steps=False,
         final_growth=False, anticollapse=False,
         note="control: growth every step (== e3_lowdeg's law) rebuilt in this probe"),
)}


def in_range(cand: Cand, s: Knobs) -> bool:
    return (cand.coef[0] <= s[0] <= cand.coef[1] and cand.fcoef[0] <= s[1] <= cand.fcoef[1]
            and cand.offset[0] <= s[2] <= cand.offset[1])


def is_live(cand: Cand, s: Knobs) -> bool:
    """Growth-live states. For every candidate here the shipped fixed point reduces
    to "everything but the corner" (the state where nothing can strictly drop) —
    asserted against `bc.live_states` by `--selftest` on the small grids, where the
    O(n²) fixed point is affordable."""
    return in_range(cand, s) and s != (cand.coef[0], cand.fcoef[0], cand.offset[0])


def flat_moves(cand: Cand, state: Knobs, cost: int) -> list[Knobs]:
    """Every legal flat successor at EXACTLY `cost` units of reservoir (ΔΦ = 2A+B).

    Enumerated from the move algebra rather than by scanning the grid, which is
    what makes the wide-range candidates (40k states) tractable.
        A = Δc ≥ 0, B = Δd ≥ −A, K = Δo ≥ −(A+B), and the gate needs min < 0,
        so when A,B ≥ 0 the drop must come from K.
    """
    c, d, o = state
    out: list[Knobs] = []
    for a in range(0, cost + 1):
        b = cost - 2 * a
        if a + b < 0:
            continue
        c2, d2 = c + a, d + b
        klo = max(-(a + b), cand.offset[0] - o)
        khi = (min(-1, cand.offset[1] - o) if (a >= 0 and b >= 0)
               else cand.offset[1] - o)
        for kk in range(klo, khi + 1):
            t = (c2, d2, o + kk)
            if cand.tight and a + b + kk != 0:
                continue
            if t == state or not is_live(cand, t) or not gate(state, t):
                continue
            assert flat_ok(state, t), (state, t)
            out.append(t)
    return out


def growth_moves(cand: Cand, state: Knobs, delta: int, thrift: int | None) -> list[Knobs]:
    """Legal growth successors; `thrift` keeps only the lowest-`c` ones (banking
    reservoir for the next flat run) — `None` = the full set (shipped behaviour)."""
    c, d, o = state
    f = LOWER ** delta
    out: list[Knobs] = []
    for o2 in range(cand.offset[0], cand.offset[1] + 1):
        need = c + d + max(0, o - o2)
        lo = max(cand.coef[0], -(-need // f))
        hi = cand.coef[1] if thrift is None else min(cand.coef[1], lo + thrift)
        for c2 in range(lo, hi + 1):
            for d2 in range(cand.fcoef[0], cand.fcoef[1] + 1):
                t = (c2, d2, o2)
                if t == state or not is_live(cand, t) or not gate(state, t):
                    continue
                assert growth_ok(state, t, delta), (state, t, delta)
                out.append(t)
    return out


@lru_cache(maxsize=None)
def _run(gamma: int, mu: int, sigma: int, lam_tot: int, s_max: int, tight: bool = False) -> int:
    """Exact longest flat run in reduced coordinates.

    Only the two unit-cost moves matter (verified exhaustively against the full
    move algebra by `selftest`):
        m1 = (Δc,Δd,Δo) = (0,+1,−1)   — spends one OFFSET unit, banks a d unit
        m2 = (+1,−1,+t)               — spends one COEFFICIENT unit, refills the
                                        offset to its ceiling and returns a d unit
    `λ + μ = D − d_min` is invariant (m1 and m2 move d in opposite directions), so
    the state is (γ = C−c, μ = d−d_min, σ = o−o_min) and Φ = 2γ + (λ_tot − μ).
    """
    best = 0
    if mu <= lam_tot - 1 and sigma >= 1:
        best = 1 + _run(gamma, mu + 1, sigma - 1, lam_tot, s_max, tight)
    if gamma >= 1 and mu >= 1:
        # tight m2 cannot refill the offset (K must be 0), so σ is a one-way budget
        best = max(best, 1 + _run(gamma - 1, mu - 1, sigma if tight else s_max,
                                  lam_tot, s_max, tight))
    return best


def longest_flat_run(cand: Cand, state: Knobs) -> int:
    c, d, o = state
    return _run(cand.coef[1] - c, d - cand.fcoef[0], o - cand.offset[0],
                cand.fcoef[1] - cand.fcoef[0], cand.offset[1] - cand.offset[0],
                cand.tight)


def best_close(cand: Cand, state: Knobs, delta: int) -> Knobs | None:
    """THE closing growth move — the unique argmin of all three gate quantities.

    Both endpoint gates want `c_k`, `d_k`, `o_k` as small as possible, and the
    sampling constraint makes `c_k` smallest exactly when `o_k` is smallest
    (`c_k ≥ ⌈(c+d+(o−o_k)⁺)/3^δ⌉`), so `(c_k, d_min, o_min)` dominates every other
    closing move: if IT fails the gates, no growth move closes this chain.
    """
    c, d, o = state
    f = LOWER ** delta
    need = c + d + max(0, o - cand.offset[0])
    c2 = max(cand.coef[0], -(-need // f))
    t = (c2, cand.fcoef[0], cand.offset[0])
    if c2 > cand.coef[1] or t == state or not is_live(cand, t) or not gate(state, t):
        return None
    return t


def can_close(cand: Cand, first: Term, state: Knobs, deg: int) -> bool:
    """Is there a closing growth step from `state` that passes BOTH endpoint gates?"""
    for delta in cand.deltas:
        t = best_close(cand, state, delta)
        if t is None:
            continue
        last = (t[0], (deg + delta, 0, 0), t[1], t[2], "sqrt")
        if not bc.endpoints_resist_naive_collapse(first, last):  # type: ignore[arg-type]
            continue
        if cand.anticollapse and collapse_slack([first, last], "sharp") >= 0:  # type: ignore
            continue
        return True
    return False


def longest_flat_run_dp(cand: Cand, state: Knobs, memo: dict) -> int:
    if state in memo:
        return memo[state]
    best = 0
    for cost in range(1, phi(state, cand) + 1):
        for t in flat_moves(cand, state, cost):
            best = max(best, 1 + longest_flat_run_dp(cand, t, memo))
    memo[state] = best
    return best


# ==========================================================================
# 2. sampler for a candidate chain
# ==========================================================================

Step = tuple[str, int, int]     # (kind, var index, delta); kind in {"flat","grow"}
Term = tuple[int, tuple[int, int, int], int, int, str]


def _draw(rng: random.Random, cand: Cand) -> Knobs:
    return (rng.randint(*cand.coef), rng.randint(*cand.fcoef), rng.randint(*cand.offset))


def _pick(rng: random.Random, options: tuple[Knobs, ...]) -> Knobs:
    return options[rng.randrange(len(options))]


def sample_chain(rng: random.Random, k: int, cand: Cand) -> tuple[list[Term], list[Step]]:
    """Flat-first, THRIFTY, with forced growth on reservoir exhaustion.

    * flat while a legal flat successor exists → minimises the number of growth
      steps, hence the degree AND the total multiplicative gain;
    * **thrifty**: among flat successors, keep those whose remaining reservoir is
      within `thrift` of the best. A uniform draw over all flat successors wastes
      the reservoir (measured: realised runs ≈ 40% of the DP optimum), which
      forces extra growth steps and breaks the anti-collapse gate;
    * `pace`: instead of spending ~1 unit per step, spend Φ₀/k per step so the
      COEFFICIENT MARGINAL is identical at every k (ablation — it makes leaf
      slack k-dependent instead);
    * `final_growth`: the last step is a growth step, which is what lets the
      shipped endpoint gate (`c_k < c_0`) close at large k;
    * the initial state is drawn from states whose reservoir can actually cover
      the chain, which is where `c_0` gets its (endpoint-gate) headroom.
    """
    knobs = _start_state(rng, cand, k)
    first = (knobs[0], tuple(cand.start), knobs[1], knobs[2], "sqrt")
    exps = list(cand.start)
    terms: list[Term] = [first]  # type: ignore
    steps: list[Step] = []
    for i in range(k):
        force = (cand.final_growth and i == k - 1) or not cand.flat_steps
        remaining = max(1, (k - 1 if cand.final_growth else k) - i - 1)
        target = max(1, round(phi(knobs, cand) / remaining)) if cand.pace else 1
        opts: list[Knobs] = []
        if not force:
            for cost in _cost_order(target, cand.thrift, phi(knobs, cand)):
                opts = [t for t in flat_moves(cand, knobs, cost)
                        if longest_flat_run(cand, t) >= remaining - 1]
                if opts:
                    break
        if opts and cand.final_growth:
            # lookahead: only take a flat move from which the chain can still be
            # CLOSED (both endpoint gates). Cheap because `best_close` dominates.
            live_opts = [t for t in opts if can_close(cand, first, t, sum(exps))]  # type: ignore
            opts = live_opts or opts
        if opts:
            # prefer the move that spends the least of `c+d` and dumps the offset:
            # that budget is what the endpoint + anti-collapse gates consume at the
            # far end, and m2 (Δ(c+d)=0) conserves it where m1 (+1) does not
            key = min((t[0] + t[1], t[2]) for t in opts)
            opts = [t for t in opts
                    if (t[0] + t[1], t[2]) <= (key[0] + cand.thrift - 1, key[1] + 4)] or opts
            knobs = opts[rng.randrange(len(opts))]
            steps.append(("flat", -1, 0))
        else:
            j = rng.randrange(len(VARS))
            delta = cand.deltas[rng.randrange(len(cand.deltas))]
            if i == k - 1 and cand.final_growth:
                t = best_close(cand, knobs, delta)
                gopts = [t] if t is not None else []
            else:
                gopts = growth_moves(cand, knobs, delta,
                                     cand.thrift if cand.flat_steps else None)
            if not gopts:
                raise RuntimeError(f"{cand.name}: no growth successor from {knobs}")
            knobs = gopts[rng.randrange(len(gopts))]
            exps[j] += delta
            steps.append(("grow", j, delta))
        terms.append((knobs[0], tuple(exps), knobs[1], knobs[2], "sqrt"))  # type: ignore
    return terms, steps


def _cost_order(target: int, thrift: int, cap: int) -> list[int]:
    """Reservoir costs to try, nearest-to-target first (thrift = allowed slack)."""
    seen, out = set(), []
    for r in range(0, thrift + 1):
        for c in (target - r, target + r):
            if 1 <= c <= cap and c not in seen:
                seen.add(c)
                out.append(c)
    return out


def start_ok(cand: Cand, s: Knobs, k: int) -> bool:
    """The three DERIVED necessary conditions on the first knob triple.

    (i)  reservoir — the flat run must cover the chain: `run(s) ≥ k − 1`.
    (ii) endpoint gate `c_k < c₀` — the closing growth step can only reach
         `c_k ≥ ⌈(c+d)/3^δ⌉` and `c+d` never DECREASES on a flat step, so
         `c_k ≥ (c₀+d₀)/3^δ`; with δ=1 that needs `d₀ < 2·c₀`.
    (iii) anti-collapse — the closing step must leave the total gain unable to pay
         the one-step route: `3·c_k + 3·d_k + o_k < c₀ + d₀ + o₀`, and since
         `3·c_k ≥ c_end + d_end ≥ c₀ + d₀`, the chain's growth of `c+d` must fit
         inside `o₀ − o_min − 3·d_min`. Each flat step raises `c+d` by 0 (m2) or
         1 (m1), and `#m2 ≤ (d₀−d_min) + #m1`, so
             k − 1 ≤ 2·(o₀ − o_min − 3·d_min) + (d₀ − d_min)
         is the *combinatorial* cap on chain length. THIS, not the degree, is what
         bounds k for a bounded-growth law.
    """
    if not is_live(cand, s):
        return False
    if not cand.flat_steps:
        return True
    c, d, o = s
    if longest_flat_run(cand, s) < k - (1 if cand.final_growth else 0):
        return False
    if not cand.final_growth:
        return True
    first = (c, tuple(cand.start), d, o, "sqrt")
    if not can_close(cand, first, s, sum(cand.start)):   # type: ignore[arg-type]
        return False
    # the closing move needs c_k ≥ (c+d)/3 and `c+d` never DECREASES on a flat
    # step, so `c_k < c₀` forces `d₀ < 2c₀` (δ=1) for the whole chain
    if d >= 2 * c:
        return False
    if not cand.anticollapse:
        return True
    # anti-collapse budget: `Δ(c+d) + (o_end − o_min) < o₀ − o_min − 3·d_min − 3`,
    # and a run of length L needs `#m1 = Δ(c+d) ≥ (L − (d₀−d_min))/2`.
    # (Unsatisfiable in fact — see `report_collapse_bound`; kept because it is the
    # gate a bounded-growth law WOULD need, and its emptiness is the finding.)
    cap = 2 * (o - cand.offset[0] - 3 * cand.fcoef[0] - 3) + (d - cand.fcoef[0])
    return k - 1 <= cap


def k_cap(cand: Cand) -> dict:
    """Largest k any start state admits, and the state that achieves it."""
    best, arg = 0, None
    for c in range(*_r(cand.coef)):
        for d in range(*_r(cand.fcoef)):
            for o in range(*_r(cand.offset)):
                s = (c, d, o)
                if not is_live(cand, s):
                    continue
                k = 1
                while k < 4096 and start_ok(cand, s, k + 1):
                    k += 1
                if k > best:
                    best, arg = k, s
    return {"k_max": best, "argmax_start": arg,
            "max_coef_range": max(cand.coef[1], cand.fcoef[1], cand.offset[1])}


@lru_cache(maxsize=None)
def admissible_starts(cand: Cand, k: int) -> tuple[Knobs, ...]:
    return tuple(s for s in ((c, d, o) for c in range(*_r(cand.coef))
                             for d in range(*_r(cand.fcoef))
                             for o in range(*_r(cand.offset)))
                 if start_ok(cand, s, k))


def _start_state(rng: random.Random, cand: Cand, k: int) -> Knobs:
    if not cand.flat_steps:
        for _ in range(4096):
            s = _draw(rng, cand)
            if is_live(cand, s):
                return s
    opts = admissible_starts(cand, k)
    if not opts:
        raise RuntimeError(f"{cand.name} k={k}: no admissible start state")
    return opts[rng.randrange(len(opts))]


# --- the two endpoint gates ------------------------------------------------

def endpoint_gate(terms: list[Term]) -> bool:
    return bc.endpoints_resist_naive_collapse(terms[0], terms[-1])


def collapse_slack(terms: list[Term], mode: str = "crude") -> float:
    """`≥ 0` ⇒ the flat ONE-STEP route closes the goal, i.e. the chain is decorative.

    The route is the generator's own witness applied to the ENDPOINTS:
        1 ≤ M₀,  √M₀ ≤ M₀,  L ≤ √M_k,  3^Δdeg · M₀ ≤ M_k,  linarith.

    * `crude`  — exactly the shipped per-step vocabulary (L = 0):
                 `c_k·3^Δdeg − (c₀+d₀) − (o₀−o_k)⁺ ≥ 0`.
    * `refined` — also uses `1 ≤ √M_k` (this probe's new witness line), so `+d_k`.
    * `sharp`  — additionally uses `3^⌊deg₀/2⌋·√M₀ ≤ M₀` and `3^⌊deg_k/2⌋ ≤ √M_k`,
                 which is the sharpest route writable in the same idiom. This is
                 the one the anti-collapse gate must survive: the d₀ tax shrinks
                 by `3^⌊deg₀/2⌋`, so a large `d₀` stops being protection once the
                 left monomial has degree ≥ 2.
    """
    c0, e0, d0, o0, _ = terms[0]
    ck, ek, dk, ok, _ = terms[-1]
    gain = LOWER ** (sum(ek) - sum(e0))
    if mode == "crude":
        return ck * gain - (c0 + d0) - max(0, o0 - ok)
    if mode == "refined":
        return ck * gain - (c0 + d0) + dk - max(0, o0 - ok)
    h0, hk = sum(e0) // 2, sum(ek) // 2
    return (ck * gain - c0 - d0 / (LOWER ** h0)) + dk * (LOWER ** hk) + ok - o0


def build(cand: Cand, k: int, seed: int, idx: int, max_discards: int = 4000) -> dict:
    """One instance: props, witnesses, meta. Deterministic in (cand,k,seed,idx)."""
    why = {"endpoint": 0, "anticollapse": 0}
    for attempt in range(max_discards):
        rng = random.Random(f"probe_a|{cand.name}|{k}|{seed}|{idx}|{attempt}")
        terms, steps = sample_chain(rng, k, cand)
        if not endpoint_gate(terms):
            why["endpoint"] += 1
            continue
        if cand.anticollapse and collapse_slack(terms, "sharp") >= 0:
            why["anticollapse"] += 1
            continue
        leaves = []
        for i in range(1, k + 1):
            prop = bc._prop(terms[i - 1], terms[i])
            kind = steps[i - 1][0]
            proof = (flat_witness(terms[i - 1], terms[i]) if kind == "flat"
                     else bc._witness_proof(terms[i - 1], terms[i],
                                            (steps[i - 1][1], steps[i - 1][2])))
            leaves.append({"i": i, "kind": kind, "prop": prop, "proof": proof,
                           "prev": terms[i - 1][:1] + terms[i - 1][2:4],
                           "new": terms[i][:1] + terms[i][2:4],
                           "es_left": sum(terms[i - 1][1])})
        n_grow = sum(1 for s in steps if s[0] == "grow")
        return {
            "cand": cand.name, "k": k, "seed": seed, "idx": idx, "discards": attempt,
            "goal": bc._prop(terms[0], terms[-1]),
            "first_term": terms[0], "last_term": terms[-1],
            "leaves": leaves,
            "n_grow": n_grow, "n_flat": k - n_grow,
            "deg_first": sum(terms[0][1]), "deg_last": sum(terms[-1][1]),
            "gain": LOWER ** (sum(terms[-1][1]) - sum(terms[0][1])),
            "es_left": [sum(t[1]) for t in terms[:-1]],
            "knobs": [{"c": t[0], "d": t[2], "o": t[3]} for t in terms],
            "collapse_slack_crude": collapse_slack(terms, "crude"),
            "collapse_slack_refined": collapse_slack(terms, "refined"),
            "collapse_slack_sharp": round(collapse_slack(terms, "sharp"), 2),
            "max_knob": max(max(t[0], t[2], t[3]) for t in terms),
            "max_coef": max_coef_of([lf["prop"] for lf in leaves]
                                    + [lf["proof"] for lf in leaves]),
            "max_coef_props": max_coef_of([lf["prop"] for lf in leaves]),
        }
    raise RuntimeError(f"{cand.name} k={k}: no instance passed the gates in "
                       f"{max_discards} (rejects: {why})")


_INT = re.compile(r"(?<![\w.^])(\d+)")


def max_coef_of(texts: list[str]) -> int:
    """Largest integer literal in the given text. CAVEAT: exponents are literals too,
    so this is contaminated for the shipped law (where exponents reach 128). Use
    `max_knob` (computed from the knobs) for the coefficient-magnitude axis."""
    best = 0
    for t in texts:
        for m in _INT.finditer(t):
            best = max(best, int(m.group(1)))
    return best


# ==========================================================================
# 3. the new witness (flat step) — one line more than the shipped one
# ==========================================================================

ONE_LE_SQRT = "by\n    have h := Real.sqrt_le_sqrt hM\n    simpa using h"


def _scaffold(exps: tuple[int, int, int]) -> list[str]:
    """The shipped `1 ≤ M` scaffold, verbatim (bc._witness_proof)."""
    mono = bc._mono(exps)
    lines = [f"  have hp{i} : (1:ℝ) ≤ {v} ^ {e} := one_le_pow₀ (by linarith)"
             for i, (v, e) in enumerate(zip(VARS, exps))]
    lines += [
        f"  have hA : (1:ℝ) ≤ {VARS[0]} ^ {exps[0]} * {VARS[1]} ^ {exps[1]} :="
        " le_trans hp0 (le_mul_of_one_le_right (by linarith) hp1)",
        f"  have hM : (1:ℝ) ≤ {mono} := le_trans hA (le_mul_of_one_le_right (by linarith) hp2)",
    ]
    return lines


def flat_witness(prev: Term, cur: Term, one_le_sqrt: str = ONE_LE_SQRT) -> str:
    """Generator-known proof of a FLAT step (`M' = M`, both functions √).

    Atoms: M and s = √M. Facts: 1 ≤ M (shipped scaffold), s ≤ M (shipped
    `Real.sqrt_le_self_iff`), and the ONE new fact 1 ≤ s. Then `linarith`.
    No `nlinarith`, no ring step, no `gcongr` — strictly cheaper than the
    shipped growth witness, which matters for the composed artifact at k=128.
    """
    assert prev[1] == cur[1], "flat witness requires an unchanged monomial"
    mono = bc._mono(prev[1])
    lines = ["by", "  intro x y z hx hy hz"]
    lines += _scaffold(prev[1])
    lines += [
        f"  have hfu : Real.sqrt ({mono}) ≤ {mono} :="
        " Real.sqrt_le_self_iff.mpr (Or.inr hM)",
        f"  have hfl : (1:ℝ) ≤ Real.sqrt ({mono}) := {one_le_sqrt}",
        "  linarith [hM, hfu, hfl]",
    ]
    return "\n".join(lines)


# ==========================================================================
# 4. the flat ONE-STEP route on a goal (what the endpoint gate must defeat)
# ==========================================================================

def onestep_route(first: Term, last: Term) -> str:
    """The generator's own witness, applied to the ENDPOINTS instead of a step.

    `endpoints_resist_naive_collapse`'s docstring argues a flat prover cannot
    produce a quantitative ratio `M_k ≥ r·M₀` because `gcongr` cannot. It can:
    the multi-variable `hbase` below is one `gcongr <;> linarith`, exactly as in
    the shipped per-step witness.
    """
    e0, ek = first[1], last[1]
    dexp = tuple(b - a for a, b in zip(e0, ek))
    mono0, monok = bc._mono(e0), bc._mono(ek)
    gain = LOWER ** sum(dexp)
    ratio3 = " * ".join((f"({LOWER}:ℝ) ^ {d}" if i == 0 else f"{LOWER} ^ {d}")
                        for i, d in enumerate(dexp))
    ratiov = " * ".join(f"{v} ^ {d}" for v, d in zip(VARS, dexp))
    lines = ["by", "  intro x y z hx hy hz"]
    lines += _scaffold(e0)
    lines.append(f"  have hfu : Real.sqrt ({mono0}) ≤ {mono0} :="
                 " Real.sqrt_le_self_iff.mpr (Or.inr hM)")
    if sum(dexp) == 0:
        lines += [f"  have hfl : (1:ℝ) ≤ Real.sqrt ({monok}) := {ONE_LE_SQRT}",
                  "  linarith [hM, hfu, hfl]"]
        return "\n".join(lines)
    lines += [
        f"  have hbase : {ratio3} ≤ {ratiov} := by gcongr <;> linarith",
        f"  have hpow : ({gain}:ℝ) ≤ {ratiov} := by linarith [hbase]",
        f"  have hstep : ({gain}:ℝ) * ({mono0}) ≤ ({ratiov}) * ({mono0}) :="
        " mul_le_mul_of_nonneg_right hpow (by positivity)",
        f"  have hring : ({ratiov}) * ({mono0}) = {monok} := by ring",
        "  rw [hring] at hstep",
        f"  have hMk : (1:ℝ) ≤ {monok} := by linarith [hM, hstep]",
        f"  have hfl : (1:ℝ) ≤ Real.sqrt ({monok}) := "
        + ONE_LE_SQRT.replace("hM", "hMk"),
        "  linarith [hM, hfu, hfl, hstep]",
    ]
    return "\n".join(lines)


# ==========================================================================
# 5. offline reports
# ==========================================================================

def report_reservoir() -> dict:
    """Exact reservoir sizes and the k a candidate can reach at bounded degree."""
    out = {}
    for name, cand in CANDS.items():
        grid = [(c, d, o) for c in range(*_r(cand.coef)) for d in range(*_r(cand.fcoef))
                for o in range(*_r(cand.offset))]
        lv = [s for s in grid if is_live(cand, s)]
        runs = [longest_flat_run(cand, s) for s in lv]
        best = max(runs)
        # after a growth step the reservoir is only partly refilled: the realised
        # cycle is 1 + the run available from wherever the growth step lands.
        # Sampled on the wide-range candidates: the full product is ~10^10 pairs.
        sample = lv if len(lv) <= 600 else random.Random(3).sample(lv, 600)
        cyc = [1 + longest_flat_run(cand, t) for s in sample for d in cand.deltas
               for t in growth_moves(cand, s, d, cand.thrift)]
        out[name] = {
            "n_live": len(lv),
            "longest_flat_run": best,
            "argmax_state": lv[runs.index(best)],
            "mean_flat_run": round(sum(runs) / len(runs), 2),
            "cycle_len_max": max(cyc) if cyc else 0,
            "cycle_len_mean": round(sum(cyc) / len(cyc), 2) if cyc else 0,
            # k reachable with G growth steps = (G+1) flat runs + G growth steps
            "k_at_G": {G: (G + 1) * best + G for G in (1, 2, 3, 4)},
            "k_at_G_typical": {G: int((G + 1) * (sum(cyc) / len(cyc) if cyc else 0) + G)
                               for G in (1, 2, 3, 4)},
        }
    return out


def _r(rng_: tuple[int, int]) -> tuple[int, int]:
    return (rng_[0], rng_[1] + 1)


def selftest() -> dict:
    """The fast move algebra vs brute force, on the grids where brute force fits."""
    out = {}
    for name in ("g1_reservoir", "s0_shipped"):
        cand = CANDS[name]
        shipped_live = bc.live_states(cand.preset())
        grid = [(c, d, o) for c in range(*_r(cand.coef)) for d in range(*_r(cand.fcoef))
                for o in range(*_r(cand.offset))]
        mine = {s for s in grid if is_live(cand, s)}
        checks = {"live_matches_shipped_fixpoint": set(shipped_live) == mine,
                  "n_live": len(mine), "n_shipped": len(shipped_live)}
        # move enumeration vs grid scan, on 40 sampled states
        rng = random.Random(7)
        ok_flat = ok_grow = True
        for s in rng.sample(sorted(mine), 40):
            brute = {t for t in mine if t != s and flat_ok(s, t) and gate(s, t)}
            fast = {t for cost in range(1, phi(s, cand) + 1) for t in flat_moves(cand, s, cost)}
            ok_flat &= brute == fast
            bg = {t for t in mine if t != s and growth_ok(s, t, 1) and gate(s, t)}
            fg = set(growth_moves(cand, s, 1, None))
            ok_grow &= bg == fg
        checks["flat_moves_exhaustive"] = ok_flat
        checks["growth_moves_exhaustive"] = ok_grow
        # the reduced-coordinate DP == the exact DAG longest path over ALL moves?
        memo: dict = {}
        diffs = [(s, longest_flat_run_dp(cand, s, memo), longest_flat_run(cand, s))
                 for s in sorted(mine)]
        checks["run_dp_matches_brute_force"] = all(a == b for _, a, b in diffs)
        checks["run_dp_mismatches"] = [d for d in diffs if d[1] != d[2]][:5]
        checks["phi_minus_run_max"] = max(phi(s, cand) - longest_flat_run(cand, s)
                                          for s in mine)
        out[name] = checks
    return out


def report_collapse_bound(trials=4000) -> dict:
    """THEOREM (goal collapse is unavoidable), checked numerically as well.

    For a chain whose closing growth step is δ and whose flat steps obey the LP,
    `3^δ·c_k ≥ c_end + d_end + (o_end − o_k)⁺` and `c_end + d_end = c₀ + d₀ + Δ`
    with `Δ = Σ(Δc+Δd) ≥ total o-drop` (because `Δo ≥ −(Δc+Δd)` on every flat
    step). Substituting into the crude one-step slack
        `c_k·3^δ − (c₀+d₀) − (o₀−o_k)⁺`
    the `o` terms cancel and the slack is `≥ Δ − (o₀ − o_end) ≥ 0`.
    So the flat ONE-STEP route ALWAYS closes the goal — for every knob range, every
    k, and every growth law in this term family, INCLUDING the shipped one.
    Measured here over random chains of every candidate: min slack over `trials`.
    """
    out = {}
    for name, cand in CANDS.items():
        worst = {}
        for k in (2, 8, 32):
            vals = []
            for t in range(trials // 40):
                rng = random.Random(f"cb|{name}|{k}|{t}")
                try:
                    terms, _ = sample_chain(rng, k, cand)
                except RuntimeError:
                    continue
                if not endpoint_gate(terms):
                    continue
                vals.append(collapse_slack(terms, "crude"))
            worst[k] = {"n": len(vals), "min_slack_crude": min(vals) if vals else None,
                        "any_negative": any(v < 0 for v in vals)}
        out[name] = worst
    return out


def _frontier_feasible(m: int, k: int, tight: bool, anticollapse: bool):
    """Is a k-step chain admissible with every knob range capped at `m`?

    Pruned scan: the binding conditions are monotone in `(o, d)` and `d₀ < 2c₀` pins
    the cheapest `c₀`, so scanning o↓, d↑, c↑ finds a witness without touching the
    whole grid. Returns the witnessing start or None.
    """
    cand = Cand(name="frontier", coef=(2, m), fcoef=(1, m), offset=(1, m),
                start=(2, 1, 1) if tight else (1, 0, 0), tight=tight,
                anticollapse=anticollapse)
    for o in range(m, 0, -1):
        for d in range(1, m + 1):
            for c in range((d + 2) // 2, m + 1):
                if start_ok(cand, (c, d, o), k):
                    return {"c0": c, "d0": d, "o0": o,
                            "run_available": longest_flat_run(cand, (c, d, o))}
    return None


def report_frontier(ks=KS, hi: int = 200, anticollapse: bool = False) -> dict:
    """THE TRADE-OFF LAW, computed exactly.

    For each k: the smallest **coefficient budget** `M` — the cap on every knob range,
    i.e. the largest numeral that can appear in a prop — for which SOME start state
    admits a k-step chain at bounded degree. Reported for the raw flat LP and for the
    tightness-gated form (§7.3), which is the shippable one.

    Feasibility is monotone in `M` (widening a range never removes an admissible
    start), so this bisects rather than sweeping.
    """
    out: dict = {}
    for tight in (False, True):
        for k in ks:
            if not _frontier_feasible(hi, k, tight, anticollapse):
                out.setdefault("tight" if tight else "slack", {})[k] = {
                    "budget_M": None, "note": f"no budget <= {hi} reaches k={k}"}
                continue
            lo, hiM = 3, hi
            while lo < hiM:
                mid = (lo + hiM) // 2
                if _frontier_feasible(mid, k, tight, anticollapse):
                    hiM = mid
                else:
                    lo = mid + 1
            out.setdefault("tight" if tight else "slack", {})[k] = {
                "budget_M": lo, **(_frontier_feasible(lo, k, tight, anticollapse) or {})}
    return out


def report_collapse_bound(trials=4000) -> dict:
    """THEOREM (goal collapse is unavoidable), checked numerically as well.

    For a chain whose closing growth step is δ and whose flat steps obey the LP,
    `3^δ·c_k ≥ c_end + d_end + (o_end − o_k)⁺` and `c_end + d_end = c₀ + d₀ + Δ`
    with `Δ = Σ(Δc+Δd) ≥ total o-drop` (because `Δo ≥ −(Δc+Δd)` on every flat
    step). Substituting into the crude one-step slack
        `c_k·3^δ − (c₀+d₀) − (o₀−o_k)⁺`
    the `o` terms cancel and the slack is `≥ Δ − (o₀ − o_end) ≥ 0`.
    So the flat ONE-STEP route ALWAYS closes the goal — for every knob range, every
    k, and every growth law in this term family, INCLUDING the shipped one.
    Measured here over random chains of every candidate: min slack over `trials`.
    """
    out = {}
    for name, cand in CANDS.items():
        worst = {}
        for k in (2, 8, 32):
            vals = []
            for t in range(trials // 40):
                rng = random.Random(f"cb|{name}|{k}|{t}")
                try:
                    terms, _ = sample_chain(rng, k, cand)
                except RuntimeError:
                    continue
                if not endpoint_gate(terms):
                    continue
                vals.append(collapse_slack(terms, "crude"))
            worst[k] = {"n": len(vals), "min_slack_crude": min(vals) if vals else None,
                        "any_negative": any(v < 0 for v in vals)}
        out[name] = worst
    return out


def report_ledger() -> dict:
    """The carrier-agnostic growth ledger (why NO law bounds both budgets forever).

    A step that is certified by `linarith` from {1 ≤ M, ρ·M ≤ M', √M ≤ M, L ≤ √M'}
    needs `c₂·ρ ≥ c₁ + d₁ − (L·d₂ + Δo)⁺`, so with L, Δo ≤ their maxima
        log ρ_i ≥ log(c_i + d_i) − log(c_{i+1}) − slack.
    Summing telescopes the c-part, leaving
        Σ log ρ ≥ k·log(1 + d_min/c_max) + log(c_0/c_k).
    Total carrier growth is therefore at least GEOMETRIC in k whatever carries it —
    exponent, integer multiplier, or anything else — and the only free parameter is
    `c_max`. Meanwhile the goal stops needing a decomposition once the ACCUMULATED
    gain pays the one-step route, i.e. once ∏ρ ≥ (c_0+d_0)/c_k. Both bounds together
    cap k.
    """
    rows = []
    for cmax in (9, 15, 20, 25, 40, 60, 96):
        rate = 1.0 + 1.0 / cmax                     # d_min = 1
        # k at which the compulsory gain exceeds the one-step route's requirement
        # (best case for the chain: c0 = 2, d0 = cmax, ck = 2 → ratio (2+cmax)/2)
        import math
        k_star = math.log((2 + cmax) / 2.0) / math.log(rate)
        rows.append({"c_max": cmax, "min_rate_per_step": round(rate, 4),
                     "gain_at_k32": round(rate ** 32, 2), "gain_at_k128": round(rate ** 128, 1),
                     "k_before_goal_collapses": round(k_star, 1)})
    return {"rows": rows,
            "note": "d_min = 1; k_before_goal_collapses ≈ ln(1+d0/c0)/ln(1+d_min/c_max)"}


def report_bound_k() -> dict:
    """Direction 4 — if no law bounds both, how far does the SHIPPED law reach?

    Uses the measured es slope (−0.0353/unit, SE 0.0079, z=−4.48, retune §8) and
    e3_lowdeg's measured k=2 level (0.575). mean es over leaves = k/2 + 0.5.
    """
    slope, se, lvl0 = 0.0353, 0.0079, 0.575
    rows = []
    for k in (2, 4, 8, 12, 16, 20, 24, 32, 64, 128):
        des = (k / 2 + 0.5) - 1.5
        proj = lvl0 - slope * des
        rows.append({"k": k, "mean_es": k / 2 + 0.5, "proj_mean": round(proj, 3),
                     "proj_lo": round(lvl0 - (slope + se) * des, 3),
                     "proj_hi": round(lvl0 - (slope - se) * des, 3)})
    kmax = max(r["k"] for r in rows if r["proj_mean"] >= 0.25)
    kmax_lo = max(r["k"] for r in rows if r["proj_lo"] >= 0.25)
    return {"rows": rows, "k_max_corridor": kmax, "k_max_corridor_pessimistic": kmax_lo,
            "note": "corridor floor 0.25; e3_lowdeg; slope from retune §8 R3'"}


def report_instances(seeds=(4501, 4502, 4503), n_idx=2) -> dict:
    """Degree, coefficient and leaf-mix numbers per candidate per k — the table
    §8.2 asked for (degree AND coefficient magnitude at k=2/8/32/128)."""
    out: dict = {}
    for name, cand in CANDS.items():
        per_k = {}
        for k in KS:
            insts = []
            for s in seeds:
                for i in range(n_idx):
                    try:
                        insts.append(build(cand, k, s, i))
                    except RuntimeError as e:
                        insts.append({"error": str(e)})
            ok = [x for x in insts if "error" not in x]
            if not ok:
                per_k[k] = {"error": insts[0]["error"], "n": 0}
                continue
            es_all = [e for x in ok for e in x["es_left"]]
            per_k[k] = {
                "n": len(ok), "n_error": len(insts) - len(ok),
                "deg_max": max(x["deg_last"] for x in ok),
                "deg_mean_leaf": round(sum(es_all) / len(es_all), 2),
                "es_left_min": min(es_all), "es_left_max": max(es_all),
                "gain_max": max(x["gain"] for x in ok),
                "n_grow_mean": round(sum(x["n_grow"] for x in ok) / len(ok), 2),
                "flat_share": round(sum(x["n_flat"] for x in ok)
                                    / sum(x["k"] for x in ok), 3),
                "max_knob": max(x["max_knob"] for x in ok),
                "max_coef": max(x["max_coef"] for x in ok),
                "max_coef_props": max(x["max_coef_props"] for x in ok),
                "discards_mean": round(sum(x["discards"] for x in ok) / len(ok), 1),
                "discards_max": max(x["discards"] for x in ok),
                "collapse_slack_crude_max": max(x["collapse_slack_crude"] for x in ok),
                "collapse_slack_sharp_max": max(x["collapse_slack_sharp"] for x in ok),
                "c_min_leaf": min(kb["c"] for x in ok for kb in x["knobs"]),
                "c_max_leaf": max(kb["c"] for x in ok for kb in x["knobs"]),
                "c_mean_leaf": round(sum(kb["c"] for x in ok for kb in x["knobs"])
                                     / sum(len(x["knobs"]) for x in ok), 2),
            }
        out[name] = per_k
    return out


# ==========================================================================
# 6. Lean stages
# ==========================================================================

def make_pool(workers: int):
    from rlmath.lean.repl_pool import ReplPool
    return ReplPool(n_workers=workers)


def run_pairs(pool, pairs, timeout_s=40.0):
    from rlmath.core import leancode
    codes = [leancode.proof_check(p, pr) for p, pr in pairs]
    res = pool.check_many(codes, timeout_s=timeout_s)
    return [(r.ok and r.sorries == 0,
             "; ".join(m.text for m in r.messages if m.severity == "error")[:200])
            for r in res]


def stage_lemmas(pool) -> dict:
    """Which spelling of `1 ≤ √M` works here, and does the log→√ cross bound exist?"""
    mono = "x ^ 1 * y ^ 0 * z ^ 0"
    prop = f"{BINDER}(1:ℝ) ≤ Real.sqrt ({mono})"
    variants = {
        "sqrt_le_sqrt+simpa": ONE_LE_SQRT,
        "one_le_sqrt.mpr": "Real.one_le_sqrt.mpr hM",
        "one_le_sqrt(pos).mpr": "(Real.one_le_sqrt (by positivity)).mpr hM",
        "le_sqrt": "by\n    rw [show (1:ℝ) = Real.sqrt 1 by simp]\n    exact Real.sqrt_le_sqrt hM",
    }
    pairs, names = [], []
    for nm, v in variants.items():
        proof = "\n".join(["by", "  intro x y z hx hy hz"] + _scaffold((1, 0, 0))
                          + [f"  exact {v}" if not v.startswith("by") else
                             "  exact " + v.replace("\n    ", "\n      ")])
        pairs.append((prop, proof))
        names.append(nm)
    # the log→sqrt cross bound (the "X" flat flavour; not used by g1/g2)
    cross = (f"{BINDER}Real.log ({mono}) ≤ 2 * Real.sqrt ({mono}) - 2")
    cross_proof = "\n".join(
        ["by", "  intro x y z hx hy hz"] + _scaffold((1, 0, 0)) + [
            f"  have hs : (1:ℝ) ≤ Real.sqrt ({mono}) := {ONE_LE_SQRT}",
            f"  have hsq : Real.sqrt ({mono}) * Real.sqrt ({mono}) = {mono} :="
            " Real.mul_self_sqrt (by linarith)",
            f"  have hl : Real.log (Real.sqrt ({mono})) ≤ Real.sqrt ({mono}) - 1 :="
            " Real.log_le_sub_one_of_pos (by linarith)",
            f"  have he : Real.log (Real.sqrt ({mono})) = Real.log ({mono}) / 2 :="
            " Real.log_sqrt (by linarith)",
            "  linarith [hl, he]"])
    pairs.append((cross, cross_proof))
    names.append("log_le_2sqrt-2")
    res = run_pairs(pool, pairs, timeout_s=60.0)
    return {nm: {"ok": ok, "err": err} for nm, (ok, err) in zip(names, res)}


def spanning_leaves(cand: Cand, ks=KS, seeds=(4501, 4502, 4503), per=6) -> list[dict]:
    """Leaves spanning the knob support: extremes of Δc/Δd/Δo per kind per k."""
    picked: list[dict] = []
    for k in ks:
        pool_: list[dict] = []
        for s in seeds:
            for i in range(2):
                try:
                    inst = build(cand, k, s, i)
                except RuntimeError:
                    continue
                for lf in inst["leaves"]:
                    pool_.append({**lf, "k": k, "seed": s, "idx": i, "cand": cand.name})
        for kind in ("flat", "grow"):
            sub = [x for x in pool_ if x["kind"] == kind]
            if not sub:
                continue
            keyed = sorted(sub, key=lambda x: (x["new"][0] - x["prev"][0],
                                               x["new"][1] - x["prev"][1],
                                               x["new"][2] - x["prev"][2],
                                               x["es_left"]))
            take = {0, len(keyed) - 1, len(keyed) // 2}
            take |= {max(range(len(keyed)), key=lambda j: keyed[j]["es_left"])}
            take |= set(range(0, len(keyed), max(1, len(keyed) // per)))
            picked += [keyed[j] for j in sorted(take)[:per + 2]]
    return picked


def stage_witness(pool) -> dict:
    out = {}
    for name in ("g6_tight",):
        cand = CANDS[name]
        leaves = spanning_leaves(cand)
        res = run_pairs(pool, [(lf["prop"], lf["proof"]) for lf in leaves], timeout_s=60.0)
        rows = []
        for lf, (ok, err) in zip(leaves, res):
            rows.append({"k": lf["k"], "kind": lf["kind"], "i": lf["i"], "ok": ok,
                         "prev": lf["prev"], "new": lf["new"], "es": lf["es_left"],
                         "err": err if not ok else ""})
        out[name] = {"n": len(rows), "n_ok": sum(r["ok"] for r in rows),
                     "by_kind": {kd: [sum(r["ok"] for r in rows if r["kind"] == kd),
                                      sum(1 for r in rows if r["kind"] == kd)]
                                 for kd in ("flat", "grow")},
                     "by_k": {k: [sum(r["ok"] for r in rows if r["k"] == k),
                                  sum(1 for r in rows if r["k"] == k)] for k in KS},
                     "failures": [r for r in rows if not r["ok"]][:8],
                     "rows": rows}
    # exhaustive: every leaf of one k=32 instance of g2_wide
    inst = build(CANDS["g6_tight"], 32, 4501, 0)
    res = run_pairs(pool, [(lf["prop"], lf["proof"]) for lf in inst["leaves"]], timeout_s=60.0)
    out["g6_tight_full_k32"] = {"n": len(res), "n_ok": sum(1 for ok, _ in res if ok),
                               "failures": [(lf["i"], lf["kind"], e)
                                            for lf, (ok, e) in zip(inst["leaves"], res)
                                            if not ok][:6]}
    return out


PLANTED = [
    # must DIE: coefficients all rise, same function both sides — the v1 hole
    (f"{BINDER}2 * x ^ 1 * y ^ 0 * z ^ 0 + 1 * Real.sqrt (x ^ 1 * y ^ 0 * z ^ 0) + 1 ≤ "
     "9 * x ^ 1 * y ^ 0 * z ^ 0 + 9 * Real.sqrt (x ^ 1 * y ^ 0 * z ^ 0) + 9",
     "planted_congruent"),
    # must DIE: a flat step with NO coefficient drop (gate off) — pure gcongr
    (f"{BINDER}4 * x ^ 2 * y ^ 1 * z ^ 0 + 2 * Real.sqrt (x ^ 2 * y ^ 1 * z ^ 0) + 3 ≤ "
     "5 * x ^ 2 * y ^ 1 * z ^ 0 + 3 * Real.sqrt (x ^ 2 * y ^ 1 * z ^ 0) + 7",
     "planted_flat_nogate"),
]


def stage_battery(pool) -> dict:
    from rlmath.core import leancode
    from rlmath.families.validate import battery_proofs
    proofs = battery_proofs()
    props: list[tuple[str, str]] = [(p, tag) for p, tag in PLANTED]
    # candidate leaves: flat and grow, DISTINCT props, spanning k and the knob support
    for name in ("g6_tight",):
        cand = CANDS[name]
        for kind in ("flat", "grow"):
            seen: set[str] = set()
            for lf in spanning_leaves(cand, ks=KS, per=8):
                if lf["kind"] != kind or lf["prop"] in seen or len(seen) >= 5:
                    continue
                seen.add(lf["prop"])
                props.append((lf["prop"],
                             f"{name}/{kind}/k{lf['k']}/i{lf['i']}/"
                             f"{lf['prev']}->{lf['new']}"))
    # goals
    for name in ("g6_tight",):
        for k in (8, 32, 128):
            try:
                props.append((build(CANDS[name], k, 4501, 0)["goal"], f"{name}/GOAL/k{k}"))
            except RuntimeError:
                pass
    # leaves from the LARGEST k specifically: their monomial has degree 2, so the
    # prop text differs from the k=2 leaves above and must be gated separately
    for lf in spanning_leaves(CANDS["g6_tight"], ks=(128,), per=8)[:6]:
        props.append((lf["prop"], f"g3_k128/{lf['kind']}/k128/{lf['prev']}->{lf['new']}"))
    seen_props: set[str] = set()
    props = [(p, t) for p, t in props if not (p in seen_props or seen_props.add(p))]
    out = {}
    for prop, tag in props:
        codes = [leancode.proof_check(prop, p) for p in proofs]
        res = pool.check_many(codes, timeout_s=BATTERY_TIMEOUT_S)
        killed = [p for p, r in zip(proofs, res) if r.ok and r.sorries == 0]
        out[tag] = {"killed_by": killed, "survives": not killed, "prop": prop[:160]}
        print(f"  battery {tag}: {'SURVIVES' if not killed else 'KILLED by ' + str(killed)}",
              flush=True)
    return out


ADAPT_ROUTES = {
    # the case_tree "adaptation ladder" (§5 of research/case-tree-hardening.md),
    # transplanted: routes a prover reaches for ONE hint away from the memorised
    # idiom. A leaf that several of these close is corridor-ceiling risky even
    # though the single-tactic battery cannot touch it.
    "nlinarith+sqrt_nonneg": "nlinarith [Real.sqrt_nonneg ({M}), Real.sqrt_nonneg ({N})]",
    "nlinarith+sq_sqrt": "nlinarith [Real.sq_sqrt (show (0:ℝ) ≤ {M} by positivity), "
                         "Real.sqrt_nonneg ({M})]",
    "nlinarith+one_le_sqrt": "nlinarith [Real.one_le_sqrt.mpr (show (1:ℝ) ≤ {M} by nlinarith)]",
    "nlinarith+sqrt_le_self": "nlinarith [Real.sqrt_le_self (show (1:ℝ) ≤ {M} by nlinarith), "
                              "Real.sqrt_nonneg ({N})]",
    "gcongr+nlinarith": "gcongr <;> nlinarith",
    "nlinarith+both": "nlinarith [Real.sqrt_nonneg ({M}), Real.sqrt_nonneg ({N}), "
                      "Real.sq_sqrt (show (0:ℝ) ≤ {M} by positivity), "
                      "Real.sq_sqrt (show (0:ℝ) ≤ {N} by positivity)]",
}


def stage_adapt(pool) -> dict:
    """Corridor-ceiling proxy: how many one-hint routes close each leaf TYPE.

    The battery is the corridor's FLOOR (single tactics). This is the analogue of
    the sibling family's idiom probe: it ranks the new flat leaf against the
    shipped growth leaf on the routes a prover actually writes. It is a ROUTE
    detector, not a difficulty meter (case-tree-hardening §5).
    """
    picked: list[dict] = []
    for name in ("g6_tight", "g4_deg4"):
        for kind in ("flat", "grow"):
            seen: set[str] = set()
            for lf in spanning_leaves(CANDS[name], ks=(2, 32, 128), per=6):
                if lf["kind"] != kind or lf["prop"] in seen or len(seen) >= 3:
                    continue
                seen.add(lf["prop"])
                picked.append({**lf, "cand": name})
    pairs, tags = [], []
    for lf in picked:
        monos = re.findall(r"Real\.sqrt \(([^)]*)\)", lf["prop"])
        mono_l, mono_r = monos[0], monos[-1]
        for rname, body in ADAPT_ROUTES.items():
            proof = ("by\n  intro x y z hx hy hz\n  "
                     + body.format(M=mono_l, N=mono_r))
            pairs.append((lf["prop"], proof))
            tags.append((f"{lf['cand']}/{lf['kind']}/k{lf['k']}/{lf['prev']}->{lf['new']}",
                         rname))
    res = run_pairs(pool, pairs, timeout_s=BATTERY_TIMEOUT_S)
    out: dict = {}
    for (leaf, rname), (ok, _err) in zip(tags, res):
        out.setdefault(leaf, {})[rname] = ok
    summary: dict = {}
    for leaf, routes in out.items():
        kind = leaf.split("/")[1]
        summary.setdefault(kind, []).append(sum(routes.values()))
    return {"per_leaf": out,
            "closed_route_counts_by_kind": summary,
            "n_routes": len(ADAPT_ROUTES)}


def stage_collapse(pool) -> dict:
    """Does the flat ONE-STEP route close the goal? Shipped presets AND candidates."""
    pairs, tags = [], []
    for preset in ("e3_lowdeg", "v2"):
        for k in (2, 4, 8, 32):
            prob = bc.generate(k, 4501, 1, preset=preset)[0]
            first, last = _endpoint_terms(prob)
            pairs.append((prob.goal.prop, onestep_route(first, last)))
            tags.append(f"SHIPPED/{preset}/k{k}")
    for name in ("g1_reservoir", "g2_wide", "g3_k128", "s0_shipped"):
        for k in (8, 32, 128):
            try:
                inst = build(CANDS[name], k, 4501, 0)
            except RuntimeError:
                continue
            pairs.append((inst["goal"],
                          onestep_route(inst["first_term"], inst["last_term"])))
            tags.append(f"{name}/k{k}")
    res = run_pairs(pool, pairs, timeout_s=90.0)
    return {t: {"closed": ok, "err": err} for t, (ok, err) in zip(tags, res)}


def _endpoint_terms(prob) -> tuple[Term, Term]:
    kn = prob.meta["knobs"]
    es = prob.meta["exponent_sums"]
    # recover exponent triples: re-render from the endpoint term text
    first = _parse_term(prob.meta["endpoint_terms"][0])
    last = _parse_term(prob.meta["endpoint_terms"][1])
    assert sum(first[1]) == es[0] and sum(last[1]) == es[-1], (first, last, es)
    assert first[0] == kn[0]["c"] and last[0] == kn[-1]["c"]
    return first, last


_TERM = re.compile(r"^(\d+) \* x \^ (\d+) \* y \^ (\d+) \* z \^ (\d+) \+ (\d+) \* "
                   r"Real\.(sqrt|log) \([^)]*\) \+ (\d+)$")


def _parse_term(text: str) -> Term:
    m = _TERM.match(text)
    if not m:
        raise ValueError(f"cannot parse term {text!r}")
    c, p, q, r, d, fn, o = m.groups()
    return (int(c), (int(p), int(q), int(r)), int(d), int(o), fn)


def stage_refute(pool) -> dict:
    """A1 — the sawtooth. Kernel-check that a degree-TRADING step is FALSE.

    Claim: for every variable, its exponent is non-decreasing along any true step,
    so no within-band rearrangement exists. Proof of falsity for one witness pair:
    instantiate x large, y = z = 3 and finish with `Real.sqrt_le_self`.
    """
    cases = []
    # (a) trade x-degree for y-degree at constant total degree
    cases.append((((2, (2, 1, 1), 1, 1, "sqrt"), (9, (1, 2, 1), 9, 9, "sqrt")), "trade_x_for_y"))
    # (b) drop total degree, everything else maximally favourable
    cases.append((((2, (2, 0, 0), 1, 1, "sqrt"), (9, (1, 0, 0), 9, 9, "sqrt")), "drop_degree"))
    # (c) the same trade with a large right-hand offset (still false)
    cases.append((((2, (3, 1, 1), 1, 1, "sqrt"), (9, (1, 3, 1), 9, 99, "sqrt")), "trade_big_offset"))
    pairs, tags = [], []
    big = "100"
    for (lo, hi), tag in cases:
        prop = f"¬ ({bc._prop(lo, hi)})"

        def num(exps):
            return bc._mono(exps).replace("x", big).replace("y", "3").replace("z", "3")

        proof = "\n".join([
            "by",
            "  intro h",
            f"  have hh := h {big} 3 3 (by norm_num) (by norm_num) (by norm_num)",
            f"  have hsu : Real.sqrt ({num(hi[1])}) ≤ {num(hi[1])} := "
            "Real.sqrt_le_self_iff.mpr (Or.inr (by norm_num))",
            f"  have hsl : (0:ℝ) ≤ Real.sqrt ({num(lo[1])}) := Real.sqrt_nonneg _",
            "  try norm_num at hh",
            "  try norm_num at hsu",
            "  try linarith [hh, hsu, hsl]",
            "  try nlinarith [hh, hsu, hsl]",
            "  try nlinarith [hh, hsu, hsl, sq_nonneg (1:ℝ)]",
        ])
        pairs.append((prop, proof))
        tags.append(tag)
    res = run_pairs(pool, pairs, timeout_s=90.0)
    return {t: {"refuted": ok, "err": err} for t, (ok, err) in zip(tags, res)}


# ==========================================================================
# main
# ==========================================================================

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--lemmas", action="store_true")
    ap.add_argument("--witness", action="store_true")
    ap.add_argument("--battery", action="store_true")
    ap.add_argument("--collapse", action="store_true")
    ap.add_argument("--refute", action="store_true")
    ap.add_argument("--adapt", action="store_true")
    ap.add_argument("--sample", action="store_true", help="print example props/witnesses")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    res: dict = {}

    if a.offline:
        res["selftest"] = selftest()
        res["reservoir"] = report_reservoir()
        res["frontier"] = report_frontier()
        res["frontier_anticollapse_gate_on"] = report_frontier(ks=(2, 8), hi=60,
                                                               anticollapse=True)
        res["collapse_bound"] = report_collapse_bound()
        res["ledger"] = report_ledger()
        res["bound_k"] = report_bound_k()
        res["instances"] = report_instances()
        (outdir / "offline.json").write_text(json.dumps(res, indent=2, default=str))
        print(json.dumps({k: res[k] for k in ("selftest", "reservoir", "frontier",
                                              "frontier_anticollapse_gate_on",
                                              "collapse_bound", "ledger", "bound_k")},
                         indent=2, default=str))
        print(json.dumps(res["instances"], indent=2, default=str))

    if a.sample:
        for name in ("g1_reservoir", "g2_wide"):
            inst = build(CANDS[name], 8, 4501, 0)
            print(f"\n===== {name} k=8  grow={inst['n_grow']} gain={inst['gain']} "
                  f"slack={inst['collapse_slack_refined']}\nGOAL: {inst['goal']}")
            for lf in inst["leaves"][:3]:
                print(f"--- leaf {lf['i']} [{lf['kind']}] {lf['prop']}\n{lf['proof']}")

    lean_stages = [(a.lemmas, "lemmas", stage_lemmas), (a.refute, "refute", stage_refute),
                   (a.witness, "witness", stage_witness), (a.battery, "battery", stage_battery),
                   (a.adapt, "adapt", stage_adapt), (a.collapse, "collapse", stage_collapse)]
    if any(flag for flag, _, _ in lean_stages):
        pool = make_pool(a.workers)
        try:
            for flag, name, fn in lean_stages:
                if not flag:
                    continue
                print(f"\n### stage {name}", flush=True)
                res[name] = fn(pool)
                (outdir / f"{name}.json").write_text(json.dumps(res[name], indent=2, default=str))
                print(json.dumps(_digest(name, res[name]), indent=2, default=str), flush=True)
        finally:
            pool.close()
    return 0


def _digest(name, payload):
    if name == "witness":
        return {k: {kk: v[kk] for kk in ("n", "n_ok", "by_kind", "by_k", "failures")
                    if kk in v} for k, v in payload.items()}
    if name == "battery":
        return {k: ("SURVIVES" if v["survives"] else v["killed_by"]) for k, v in payload.items()}
    return payload


if __name__ == "__main__":
    sys.exit(main())
