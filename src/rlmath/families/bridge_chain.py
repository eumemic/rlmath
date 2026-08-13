"""Family A — bridge chains: prove `R(a₀, a_k)` through k hidden intermediates.

Schema (v2, "named-function monomial ladder over ℝ")
----------------------------------------------------
Every problem is a chain `a₀ ≤ a₁ ≤ … ≤ a_k` of real terms

    aᵢ  =  cᵢ * Mᵢ  +  dᵢ * Fᵢ(Mᵢ)  +  oᵢ        Mᵢ = x ^ pᵢ * y ^ qᵢ * z ^ rᵢ

with `cᵢ ∈ [2,9]`, `dᵢ ∈ [1,9]`, `oᵢ ∈ [1,9]` and `Fᵢ ∈ {Real.sqrt, Real.log}` drawn iid
per term, under the shared side conditions `3 ≤ x`, `3 ≤ y`, `3 ≤ z`. One step multiplies
the monomial by `v ^ δ` for a randomly chosen `v ∈ {x,y,z}` and `δ ∈ {1,2}`, and resamples
`(c, d, o, F)`. Exponents start at `(1,1,1)`.

    goal    ∀ x y z : ℝ, 3 ≤ x → 3 ≤ y → 3 ≤ z → a₀ ≤ a_k
    hᵢ      ∀ x y z : ℝ, 3 ≤ x → 3 ≤ y → 3 ≤ z → aᵢ₋₁ ≤ aᵢ            (i = 1..k)
    assembly    intro x y z hx hy hz
                exact (le_trans (h1 x y z hx hy hz) (le_trans (h2 …) … ))

Only `a₀` and `a_k` occur in the goal; every intermediate's coefficients, offset,
named function and exponent triple are what a policy has to invent.

**Step form, not cumulative form.** The alternative plan shape `hᵢ : R(a₀, aᵢ)` was
rejected on two counts, both structural: (1) `h_k` *is* the goal, so the last lemma is a
restatement — it fails V6 unless exempted, and a policy emitting it has decomposed
nothing; (2) a cumulative witness redoes the whole prefix, so leaf difficulty grows with
i and per-node flatness (DIRECTION §5.4a) dies by construction.

Why v1 died, and what v2 changes (measured, 2026-08-12)
-------------------------------------------------------
v1 terms were `cᵢ Mᵢ + dᵢ`. Under the *strengthened* V0/V5 battery (10 tactics × {bare,
intros-first}) **16 of its leaves fell to `intros; gcongr <;> linarith`** — the combo v1
gated at the endpoints but never ran against individual steps. `gcongr` anti-unifies the
two sides, so a step whose every coefficient is non-decreasing (`c₁ ≤ c₂`, `d₁ ≤ d₂`,
`M ≤ M'`) is pure relational congruence and closes in one line.

v2 closes that hole twice over, and both halves were measured before shipping
(`research/family-v2-hardening.md` §2):

1. **Named-function content.** Each term carries `dᵢ * Fᵢ(Mᵢ)` with `Fᵢ` drawn from
   `{Real.sqrt, Real.log}`. When consecutive terms disagree on `F` there is no common
   wrapper to anti-unify, so `gcongr` cannot even build a template; `linarith`/`nlinarith`
   see `Real.sqrt (…)`/`Real.log (…)` as opaque atoms with no connecting hypothesis.
   Measured: `4M + 2 log M ≤ 9M' + 7 √M'` survives the whole battery *even with every
   coefficient rising*, while the same step with `√` on both sides dies to
   `intros; gcongr <;> linarith`.
2. **A per-step congruence gate** (`step_resists_congruence`): at least one of `c`, `d`,
   `o` must strictly *decrease* across every step. That is exactly the negation of
   gcongr's success condition, so it holds regardless of which functions were drawn.
   The multiplicative gain `M' ≥ 3^δ M` pays for the drop.

The gate is applied unconditionally, i.e. it is stricter than the measurement demands
(only `√|√` steps needed it). Making it conditional on the function pair would make the
`(c,d,o)` distribution depend on the function draw for no measured benefit.

Why the step is sound and why its witness needs no search
---------------------------------------------------------
With `M ≥ 1`, `F(M) ≤ M` (for `√`: `Real.sqrt_le_self_iff`; for `log`:
`Real.log_le_sub_one_of_pos`), `F(M') ≥ 0`, and `M' ≥ 3^δ M`, the step
`c₁M + d₁F₁(M) + o₁ ≤ c₂M' + d₂F₂(M') + o₂` is a *linear* consequence over the four
atoms `M, M', F₁(M), F₂(M')` provided

    c₂ · 3^δ − (c₁ + d₁)  ≥  max(0, o₁ − o₂)                     (SAMPLING CONSTRAINT)

which the sampler enforces by rejection. Everything else in the witness is the `1 ≤ M`
scaffold, unchanged from v1 (search-free `gcongr` on a one-variable numeric bound, no
`nlinarith` anywhere — that is what kept the composed k=32 artifact inside PREAMBLE's
`maxHeartbeats`).

Residual, stated plainly and unchanged from v1: bridge chains over an *ordered numeric*
domain are collapsible in principle (`≤` is transitive **and** total), so what the k-axis
stresses here is plan length and intermediate invention. DIRECTION §5.4(d) (flat-prover
decay) is a Phase-2 measurement, not a schema property.

Difficulty presets (2026-08-12 retune — the level, not the shape)
-----------------------------------------------------------------
The overnight calibration measured this schema against the frozen DSV2-7B leaf
(58 leaves × 8 attempts, `data/bank/family_leaf_calibration.jsonl`): per-leaf
pass@8 of **0.225 / 0.125 / 0.129 at k = 2 / 4 / 8**. Flatness passes (k4 vs k8
within 0.004 — the size axis is sound); the *level* fails, sitting below the
[0.25, 0.9] corridor floor. The fix is a knob retune, not a schema change, so
every difficulty-relevant knob now lives in a `DifficultyPreset` and `generate`
takes `preset=`. The shipped values are preset **"v2"** and remain the default;
its output is byte-identical to the pre-preset generator (golden tests pin it).

The candidate easier presets were chosen from the *measured* correlates in that
same calibration file, not from taste (`research/retune-notes.md` §2):

| lever | measured mean pass@8 | mechanism |
|---|---|---|
| right-hand `Real.sqrt` vs `Real.log` | 0.206 (n=31) vs 0.074 (n=27) | `Real.sqrt_nonneg` is unconditional; `Real.log_nonneg` re-requires `1 ≤ M'` |
| δ=1 vs δ=2 | 0.210 (n=25) vs 0.095 (n=33) | smaller ring step, and exponents grow half as fast along the chain |
| left exponent sum ≤ 4 | 0.233 (n=22) vs ~0.09 | `1 ≤ M` is the measured blocker (§4.5 of the v2 log): fewer factors, fewer products |
| offset non-decreasing | 0.194 (n=27) vs 0.101 (n=31) | the step no longer has to pay `o₁ − o₂` out of the multiplicative gain |

**Two invariants are NOT knobs and cannot be turned off by a preset**: the
per-step congruence gate (`step_resists_congruence`, applied unconditionally in
`_sample_chain`) and named-function content on every term (`funcs` must be a
non-empty subset of `FUNCS`, and `render_term` always emits `d * F(M)`). Those
two are what defeat the automation battery; a preset that relaxed either would
be measuring tactic dispatch again (FAMILIES.md V0/V5). `LOWER` is likewise
fixed: `3` is what makes `M' ≥ 3^δ M` and `1 ≤ M` true at all.

Determinism: output is a pure function of `(k, seed, preset)`; problem i,
attempt a uses the derived seed string `bridge_chain|{k}|{seed}|{i}|{a}` for the
default preset and `bridge_chain|{preset}|{k}|{seed}|{i}|{a}` otherwise (the
default's string is unchanged so v2 datasets regenerate byte-identically).
"""
from __future__ import annotations

import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache

from rlmath.core.types import DecompositionPlan, GoalSpec, LemmaSpec, normalize_statement
from rlmath.families import register
from rlmath.families.types import GeneratedProblem, LeafWitness

FAMILY = "bridge_chain"
SCHEMA = "named_function_monomial_ladder_R"

# --- schema knobs (identical at every k — this is what makes per-node difficulty flat)
VARS: tuple[str, str, str] = ("x", "y", "z")
HYP_NAMES: tuple[str, str, str] = ("hx", "hy", "hz")   # side-condition names in every proof
LOWER = 3                      # side condition `LOWER ≤ v` on every variable
COEF_RANGE = (2, 9)            # cᵢ — multiplier of the monomial
FCOEF_RANGE = (1, 9)           # dᵢ — multiplier of the named-function term
OFFSET_RANGE = (1, 9)          # oᵢ — additive offset
DELTAS = (1, 2)                # exponent increment per step
START_EXPONENTS = (1, 1, 1)
FUNCS: tuple[str, str] = ("sqrt", "log")   # named function wrapping the monomial
_MAX_REJECTS = 512             # sampler safety valve; the constraint is always satisfiable
_MAX_DISCARDS = 400            # offline regeneration attempts per slot

# The one `(c,d,o)` state with no legal successor under the congruence gate: nothing can
# strictly decrease below the floor of all three ranges. Excluded from the sample space
# so `_sample_chain` can never paint itself into a corner.
_CORNER = (COEF_RANGE[0], FCOEF_RANGE[0], OFFSET_RANGE[0])

BINDER = f"∀ x y z : ℝ, {LOWER} ≤ x → {LOWER} ≤ y → {LOWER} ≤ z → "

Term = tuple[int, tuple[int, int, int], int, int, str]   # (c, exponents, d, o, func)
Step = tuple[int, int]                                   # (variable index, δ)
Knobs = tuple[int, int, int]                             # (c, d, o)


# --------------------------------------------------------------------------
# difficulty presets
# --------------------------------------------------------------------------

DEFAULT_PRESET = "v2"
_NAME_OK = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


@dataclass(frozen=True)
class DifficultyPreset:
    """The difficulty-relevant knobs of one draw distribution over the *same* schema.

    A preset changes the term distribution only. The step form, the witness
    template, the three gates, the balanced fold and the rendered shape
    `c·M + d·F(M) + o` are schema and are identical across presets — that is
    what makes a retune a retune rather than a new family (and what keeps the
    measured V0–V6 tables in research/family-v2-hardening.md applicable).

    `name` doubles as a Lean identifier fragment (goal names) and an id
    fragment, so it is restricted to `[a-z0-9_]`.
    """

    name: str
    rationale: str
    coef_range: tuple[int, int] = COEF_RANGE
    fcoef_range: tuple[int, int] = FCOEF_RANGE
    offset_range: tuple[int, int] = OFFSET_RANGE
    deltas: tuple[int, ...] = DELTAS
    funcs: tuple[str, ...] = FUNCS
    start_exponents: tuple[int, int, int] = START_EXPONENTS
    max_discards: int = _MAX_DISCARDS

    def __post_init__(self) -> None:
        if not self.name or set(self.name) - _NAME_OK or self.name[0].isdigit():
            raise ValueError(f"preset name must match [a-z_][a-z0-9_]*: {self.name!r}")
        for label, rng in (("coef_range", self.coef_range), ("fcoef_range", self.fcoef_range),
                           ("offset_range", self.offset_range)):
            if len(rng) != 2 or rng[0] > rng[1] or rng[0] < 1:
                raise ValueError(f"{self.name}: {label}={rng} must be a 1-based (lo <= hi) pair")
        if not self.deltas or any(d < 1 for d in self.deltas):
            raise ValueError(f"{self.name}: deltas must be non-empty and >= 1; got {self.deltas}")
        # NOT a knob: named-function content is what defeats the battery (module
        # docstring), so a preset may narrow the mixture but never empty it, and
        # only the two functions `_fn_bounds` knows how to witness are allowed.
        if not self.funcs or set(self.funcs) - set(FUNCS):
            raise ValueError(f"{self.name}: funcs must be a non-empty subset of {FUNCS}")
        if len(self.start_exponents) != len(VARS) or any(e < 0 for e in self.start_exponents):
            raise ValueError(f"{self.name}: start_exponents must be {len(VARS)} non-negative ints")
        if not live_states(self):
            raise ValueError(f"{self.name}: no (c,d,o) state survives both gates")

    @property
    def is_default(self) -> bool:
        return self.name == DEFAULT_PRESET

    def knobs(self) -> dict:
        """Recorded in `meta['preset_knobs']` so a dataset row says which
        distribution produced it without a lookup against this file."""
        return {
            "coef_range": list(self.coef_range), "fcoef_range": list(self.fcoef_range),
            "offset_range": list(self.offset_range), "deltas": list(self.deltas),
            "funcs": list(self.funcs), "start_exponents": list(self.start_exponents),
            "lower_bound": LOWER,
        }


def _grid(preset: DifficultyPreset) -> list[Knobs]:
    return [(c, d, o)
            for c in range(preset.coef_range[0], preset.coef_range[1] + 1)
            for d in range(preset.fcoef_range[0], preset.fcoef_range[1] + 1)
            for o in range(preset.offset_range[0], preset.offset_range[1] + 1)]


@lru_cache(maxsize=None)
def live_states(preset: DifficultyPreset) -> frozenset[Knobs]:
    """The `(c,d,o)` states the sampler may occupy: the greatest set in which
    **every** δ has a legal successor **inside the set**.

    v2 gets this for free from one excluded corner (`_CORNER`), which is why the
    shipped sampler could just compare against it. A narrower preset can strand
    more states — e.g. with a fixed offset, every `(c_min, d_min, o)` is a dead
    end because nothing is left to decrease — and a state whose only successors
    are dead ends is itself a dead end, so this is a greatest-fixed-point, not
    one filtering pass. Computed once per preset (≤ 648 states) and cached.
    """
    live = set(_grid(preset))
    while True:
        stranded = {
            s for s in live
            if not all(any(t != s and _valid(s, t, delta) and step_resists_congruence(s, t)
                           for t in live)
                       for delta in preset.deltas)
        }
        if not stranded:
            return frozenset(live)
        live -= stranded


def dead_end_states(preset: DifficultyPreset) -> frozenset[Knobs]:
    """Complement of `live_states` — the states excluded from the sample space."""
    return frozenset(_grid(preset)) - live_states(preset)


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _mono(exps: Sequence[int]) -> str:
    """`x ^ 2 * y ^ 1 * z ^ 3` — exponent 1 stays explicit so that leaf prop text has
    the same shape at every position in the chain (flatness is measured on this text)."""
    return " * ".join(f"{v} ^ {e}" for v, e in zip(VARS, exps))


def _fn(func: str, arg: str) -> str:
    """Fully qualified: PREAMBLE opens both `Real` and `Nat`, so bare `log`/`sqrt`
    would be ambiguous."""
    return f"Real.{func} ({arg})"


def render_term(t: Term) -> str:
    c, exps, d, o, func = t
    mono = _mono(exps)
    return f"{c} * {mono} + {d} * {_fn(func, mono)} + {o}"


def _prop(lo: Term, hi: Term) -> str:
    return f"{BINDER}{render_term(lo)} ≤ {render_term(hi)}"


# --------------------------------------------------------------------------
# sampling
# --------------------------------------------------------------------------

def _valid(prev: tuple[int, int, int], new: tuple[int, int, int], delta: int) -> bool:
    """SAMPLING CONSTRAINT (see module docstring): what makes the leaf witness a
    `linarith` over four atoms rather than a nonlinear search.

    `F(M) ≤ M` and `F(M') ≥ 0` reduce the step to `(c₁+d₁)M + o₁ ≤ c₂M' + o₂`, and
    `M' ≥ 3^δ M ≥ 3^δ` closes it exactly when the inequality below holds.
    """
    c1, d1, o1 = prev
    c2, _d2, o2 = new
    return c2 * (LOWER ** delta) - (c1 + d1) >= max(0, o1 - o2)


def step_resists_congruence(prev: tuple[int, int, int], new: tuple[int, int, int]) -> bool:
    """Per-step gate against `gcongr <;> linarith` — the tactic that killed 16 v1 leaves.

    `gcongr` anti-unifies the two sides of `≤` and emits one side goal per differing
    position. For `c₁M + d₁F(M) + o₁ ≤ c₂M' + d₂F(M') + o₂` those are `c₁ ≤ c₂`,
    `M ≤ M'`, `d₁ ≤ d₂`, `o₁ ≤ o₂` (plus the monotonicity of `F`), all of which the
    `<;> linarith` discharger closes when the coefficients rise together. Forcing **one
    of the three coefficients strictly down** makes a side goal false, so no template
    succeeds, while the multiplicative gain `M' ≥ 3^δ M` keeps the step true.

    Measured (research/family-v2-hardening.md §2): with every coefficient rising and the
    same function on both sides the step dies to `intros; gcongr <;> linarith` in ~1 s;
    with one coefficient dropping it survives all 20 battery proofs.
    """
    return any(n < p for n, p in zip(new, prev))


def endpoints_resist_naive_collapse(first: Term, last: Term) -> bool:
    """Endpoint gate: reject chains the *endpoints alone* give away.

    The k-independent flat route on the goal is `have hj : M₀ ≤ M_k := by gcongr <;>
    linarith` plus a lower bound `t ≤ M₀`, then `linarith`. Its strongest form closes the
    goal iff `(c_k − c₀)·t ≥ o₀ − o_k` for the best available `t`. Demanding

        c_k < c₀   and   o_k ≤ o₀   and   d_k ≤ d₀

    makes the left side *negative* and the right side non-negative, so **no** lower bound
    on `M₀`, however sharp, can rescue it: a flat prover must instead establish a
    quantitative ratio `M_k ≥ r·M₀` with `r ≥ c₀/c_k > 1`. The
    `d_k ≤ d₀` conjunct extends the same argument to the named-function term (whose
    coefficient a prover could otherwise trade against, since `F(M) ≤ M`).

    Measured for v1 (§4 of research/family-bridge-chain.md): before the gate a k=8 goal
    fell to that route in 8 lines; after it, all five flat routes we know of close 0/3
    goals at every k ∈ {2,4,8,16,32}. The gate touches only the endpoints, so leaf
    difficulty is untouched. It defeats a *family* of routes, not collapse in general.

    **CORRECTION 2026-08-13 — this docstring used to claim the ratio was one `gcongr`
    cannot produce. That was false, and it was load-bearing.** `gcongr <;> linarith`
    produces `3^Δ ≤ v^Δ` in one line, and `mul_le_mul_of_nonneg_right` + `ring` finish the
    ratio — which is precisely what this module's own `_witness_proof` does per step. The
    resulting fixed, **k-independent** route closes the shipped `e3_lowdeg` goal at
    k = 2, 4, 8 **and 32** (verified twice: survey agent and orchestrator, see
    `research/bc_growth_a/collapse_orchestrator_verify.json`).

    So this gate does *not* establish what its final sentence implies. It still defeats the
    five routes it was measured against — that much is real — but the goal is collapsible
    anyway, which means DIRECTION §5.4(d) ("flat-prover solve rate decays in k") does not
    hold for this family as shipped. The underlying reason is that the crude relaxations
    (`√M ≤ M`, `1 ≤ M`) are **scale-free**: applying them once at the endpoints is never
    weaker than applying them k times, so no endpoint condition can make the chain
    necessary. See `research/retune-notes.md` §9; the family's fate is task #18.

    Do not read a `True` from this function as "the goal requires the decomposition".
    """
    c0, _exps0, d0, o0, _f0 = first
    ck, _expsk, dk, ok, _fk = last
    return ck < c0 and ok <= o0 and dk <= d0


# The retune candidates (2026-08-12). v2 is the shipped distribution and the
# measured control; every other preset is EASIER by one more measured lever than
# the one above it, so the GPU session reads a ladder rather than four unrelated
# points and a null result localizes to a lever.
PRESETS: dict[str, DifficultyPreset] = {
    p.name: p for p in (
        DifficultyPreset(
            name="v2",
            rationale="shipped distribution; measured pass@8 0.225/0.125/0.129 at k=2/4/8 "
                      "(mean ~0.13, below the 0.25 corridor floor) — the control",
        ),
        DifficultyPreset(
            name="e1_sqrt", funcs=("sqrt",),
            rationale="√ only: the right-hand function's non-negativity becomes unconditional "
                      "(Real.sqrt_nonneg) instead of re-requiring 1 ≤ M' — measured 0.206 vs "
                      "0.074 for log-on-the-right",
        ),
        DifficultyPreset(
            name="e2_flatstep", funcs=("sqrt",), deltas=(1,),
            rationale="e1 + δ=1 only: one ring step per leaf and exponents grow half as fast, "
                      "so late leaves stay near the measured-easy small-monomial end "
                      "(δ=1 measured 0.210 vs 0.095)",
        ),
        DifficultyPreset(
            name="e3_lowdeg", funcs=("sqrt",), deltas=(1,), start_exponents=(1, 0, 0),
            rationale="e2 + total degree 1 at the start: keeps `1 ≤ M` — the single blocker the "
                      "v2 log measured (§4.5) — a one-variable fact for most of the chain "
                      "(exponent-sum ≤ 4 measured 0.233 vs ~0.09)",
        ),
        DifficultyPreset(
            name="e4_slack", funcs=("sqrt",), deltas=(1,), coef_range=(2, 6),
            fcoef_range=(1, 4), offset_range=(5, 5),
            rationale="e2 + fixed offset and narrower coefficient spans: the step never has to "
                      "pay an offset drop out of the multiplicative gain (o non-decreasing "
                      "measured 0.194 vs 0.101) and the opaque √ atom carries less weight",
        ),
    )
}


def resolve_preset(preset: str | DifficultyPreset) -> DifficultyPreset:
    if isinstance(preset, DifficultyPreset):
        return preset
    try:
        return PRESETS[preset]
    except KeyError:
        raise ValueError(f"unknown bridge_chain preset {preset!r}; have {sorted(PRESETS)}") from None


def _sample_knobs(rng: random.Random, preset: DifficultyPreset) -> Knobs:
    return (rng.randint(*preset.coef_range), rng.randint(*preset.fcoef_range),
            rng.randint(*preset.offset_range))


def _sample_chain(rng: random.Random, k: int,
                  preset: DifficultyPreset) -> tuple[list[Term], list[Step], int]:
    """Rejection sampler over `preset`'s knob grid, gates unchanged.

    The draw ORDER is preset-independent and must stay that way: initial knobs,
    initial func, then per step (variable, δ, knob retries…, func). v2's stream
    is therefore the pre-preset generator's stream call for call — `live_states`
    reduces to `{_CORNER}` there — which is what keeps the golden tests green.
    """
    live = live_states(preset)
    exps = list(preset.start_exponents)
    rejects = 0
    knobs = _sample_knobs(rng, preset)
    while knobs not in live:
        knobs = _sample_knobs(rng, preset)
        rejects += 1
    func = rng.choice(preset.funcs)
    terms: list[Term] = [(knobs[0], tuple(exps), knobs[1], knobs[2], func)]  # type: ignore[arg-type]
    steps: list[Step] = []
    for _ in range(k):
        j = rng.randrange(len(VARS))
        delta = rng.choice(preset.deltas)
        for _attempt in range(_MAX_REJECTS):
            new = _sample_knobs(rng, preset)
            if new in live and _valid(knobs, new, delta) and step_resists_congruence(knobs, new):
                break
            rejects += 1
        else:  # pragma: no cover - unreachable: dead ends are excluded from the
               # sample space, so every live state has a legal successor for every δ
            raise RuntimeError(f"bridge_chain[{preset.name}]: step constraints unsatisfiable")
        exps[j] += delta
        steps.append((j, delta))
        knobs = new
        terms.append((knobs[0], tuple(exps), knobs[1], knobs[2],  # type: ignore[arg-type]
                      rng.choice(preset.funcs)))
    return terms, steps, rejects


# --------------------------------------------------------------------------
# witnesses
# --------------------------------------------------------------------------

def _fn_bounds(prev: Term, cur: Term) -> list[str]:
    """The two named-function facts the final `linarith` needs, per function pair.

    Upper bound on the *left* term's function (`F₁(M) ≤ M`) and non-negativity of the
    *right* one (`0 ≤ F₂(M')`). Both are single lemma applications — no search — which
    is what keeps the composed artifact cheap at large k.
    """
    mono, mono_next = _mono(prev[1]), _mono(cur[1])
    left, right = prev[4], cur[4]
    lines = []
    if left == "sqrt":
        lines.append(f"  have hfu : Real.sqrt ({mono}) ≤ {mono} :="
                     " Real.sqrt_le_self_iff.mpr (Or.inr hM)")
    else:
        lines.append(f"  have hfu : Real.log ({mono}) ≤ {mono} - 1 :="
                     " Real.log_le_sub_one_of_pos (by linarith)")
    if right == "sqrt":
        lines.append(f"  have hfl : (0:ℝ) ≤ Real.sqrt ({mono_next}) := Real.sqrt_nonneg _")
    else:
        lines.append(f"  have hfl : (0:ℝ) ≤ Real.log ({mono_next}) :="
                     " Real.log_nonneg (by linarith [hM, hstep])")
    return lines


def _witness_proof(prev: Term, cur: Term, step: Step) -> str:
    """Generator-known proof of `_prop(prev, cur)`.

    Search-free: `gcongr` on a one-variable numeric bound, two named-function lemma
    applications, then `linarith` over the four atoms `M, M', F₁(M), F₂(M')`. No
    `nlinarith` anywhere — it is what made the composed artifact expensive at large k.
    """
    j, delta = step
    v = VARS[j]
    exps = prev[1]
    mono = _mono(exps)
    mono_next = _mono(cur[1])
    factor = LOWER ** delta
    # `hbase` comes first, while the context is still just hx/hy/hz: proved later it
    # would drag every big-monomial hypothesis into the search, and the composed k=32
    # artifact then blows PREAMBLE's maxHeartbeats budget (measured — see the design log).
    lines = [
        "by",
        "  intro x y z hx hy hz",
        f"  have hbase : ({LOWER}:ℝ) ^ {delta} ≤ {v} ^ {delta} := by gcongr <;> linarith",
        f"  have hpow : ({factor}:ℝ) ≤ {v} ^ {delta} := by linarith [hbase]",
    ]
    for idx, (var, e) in enumerate(zip(VARS, exps)):
        lines.append(f"  have hp{idx} : (1:ℝ) ≤ {var} ^ {e} := one_le_pow₀ (by linarith)")
    lines += [
        f"  have hA : (1:ℝ) ≤ {VARS[0]} ^ {exps[0]} * {VARS[1]} ^ {exps[1]} :="
        " le_trans hp0 (le_mul_of_one_le_right (by linarith) hp1)",
        f"  have hM : (1:ℝ) ≤ {mono} := le_trans hA (le_mul_of_one_le_right (by linarith) hp2)",
        f"  have hstep : {factor} * ({mono}) ≤ {v} ^ {delta} * ({mono}) :="
        " mul_le_mul_of_nonneg_right hpow (by linarith)",
        f"  have hring : {v} ^ {delta} * ({mono}) = {mono_next} := by ring",
        "  rw [hring] at hstep",
    ]
    lines += _fn_bounds(prev, cur)
    lines.append("  linarith [hM, hstep, hfu, hfl]")
    return "\n".join(lines)


def _assembly(k: int) -> str:
    """**Balanced** `le_trans` fold. Deliberately mentions no term text: the assembly is
    pure transitivity, so all invented content lives in the lemma statements.

    Balanced rather than right-nested for elaboration cost, and this was measured, not
    assumed: v1's right-nested fold `le_trans h1 (le_trans h2 (…))` puts step i at depth
    i, so the elaborator propagates postponed metavariables through k levels. v2's leaf
    props carry two extra function applications each, and at k=32 the right-nested fold
    tipped V3 (`plan_check`) over PREAMBLE's `maxHeartbeats 400000` —
    `(deterministic) timeout at «synthesize pending MVars»` — while every leaf still
    checked individually. A balanced fold puts every step at depth ⌈log₂ k⌉; same k−1
    `le_trans` applications, same absence of term text, k=32 back inside budget.
    """
    apply = [f"h{i} x y z hx hy hz" for i in range(1, k + 1)]

    def rec(lo: int, hi: int) -> str:
        if hi - lo == 1:
            return f"({apply[lo]})"
        mid = (lo + hi) // 2
        return f"(le_trans {rec(lo, mid)} {rec(mid, hi)})"

    return f"intro x y z hx hy hz\nexact {rec(0, k)}"


# --------------------------------------------------------------------------
# offline self-checks (a V6 pre-check that needs no Lean)
# --------------------------------------------------------------------------

def hidden_intermediate_violations(problem: GeneratedProblem) -> list[str]:
    """Stricter than V6: V6 only asks that a *lemma prop* is not a substring of the
    goal, which any binder prefix defeats. Here we also require that no intermediate
    *term* text `a₁ … a_{k-1}` occurs anywhere in the goal — the property the family
    actually claims (a policy cannot copy an intermediate out of the statement)."""
    out: list[str] = []
    goal_norm = normalize_statement(problem.goal.prop)
    visible = set(problem.meta.get("visible_lemmas", ()))
    for lemma in problem.oracle_plan.lemmas:
        if lemma.name not in visible and normalize_statement(lemma.prop) in goal_norm:
            out.append(f"lemma {lemma.name} prop is a substring of the goal")
    for i, term in enumerate(problem.meta["intermediate_terms"], start=1):
        if term in goal_norm:
            out.append(f"intermediate term a{i} ({term!r}) occurs in the goal")
    return out


def check_preset_invariants(problem: GeneratedProblem) -> list[str]:
    """Every offline gate a problem must satisfy, whatever preset produced it.

    Composed here rather than in each caller because a retune has to be able to
    say "this candidate distribution still satisfies the invariants v2 was
    measured under" in one call, per preset, with no Lean in the loop
    (scripts/stage_retune_candidates.py; FAMILIES.md V5/V6 pre-checks). Returns
    a list of human-readable violations; empty means clean.

    The two battery-facing invariants (the congruence gate and named-function
    content on every term) are checked on the *emitted text and knobs*, not on
    the preset's declaration, so a sampler bug cannot pass by declaration.
    """
    out: list[str] = []
    preset = resolve_preset(problem.meta.get("preset", DEFAULT_PRESET))
    knobs = [(kb["c"], kb["d"], kb["o"]) for kb in problem.meta["knobs"]]
    for i, (prev, new) in enumerate(zip(knobs, knobs[1:]), start=1):
        if not step_resists_congruence(prev, new):
            out.append(f"step {i}: congruence gate violated ({prev} -> {new})")
    for i, ((_, delta), (prev, new)) in enumerate(
            zip(problem.meta["step_kinds"], zip(knobs, knobs[1:])), start=1):
        if not _valid(prev, new, delta):
            out.append(f"step {i}: sampling constraint violated ({prev} -> {new}, δ={delta})")
        if delta not in preset.deltas:
            out.append(f"step {i}: δ={delta} outside preset support {preset.deltas}")
    first, last = problem.meta["knobs"][0], problem.meta["knobs"][-1]
    if not endpoints_resist_naive_collapse(
            (first["c"], (0, 0, 0), first["d"], first["o"], first["func"]),
            (last["c"], (0, 0, 0), last["d"], last["o"], last["func"])):
        out.append("endpoint gate violated (the naive flat route is open)")
    for prop in [problem.goal.prop] + [l.prop for l in problem.oracle_plan.lemmas]:
        if prop.count("Real.sqrt (") + prop.count("Real.log (") != 2:
            out.append(f"named-function content missing: {prop}")
        if "\n" in prop or prop != prop.strip():
            out.append(f"prop is not a single trimmed line: {prop!r}")
    for kb in problem.meta["knobs"]:
        if kb["func"] not in preset.funcs:
            out.append(f"func {kb['func']!r} outside preset support {preset.funcs}")
        if not (preset.coef_range[0] <= kb["c"] <= preset.coef_range[1]
                and preset.fcoef_range[0] <= kb["d"] <= preset.fcoef_range[1]
                and preset.offset_range[0] <= kb["o"] <= preset.offset_range[1]):
            out.append(f"knobs {kb} outside preset ranges")
    sums = problem.meta["exponent_sums"]
    if any(b <= a for a, b in zip(sums, sums[1:])):
        out.append(f"exponent sums are not strictly increasing: {sums}")
    return out + hidden_intermediate_violations(problem)


def leaf_shape_stats(problems: Iterable[GeneratedProblem]) -> dict:
    """Structural flatness evidence for the datasheet: leaf prop length distribution,
    step-kind mix and named-function mix, grouped by k (FAMILIES.md 'Scaling
    requirements').

    The mix histograms are keyed on the *declared support* of whichever presets
    produced the input (union), not on the module constants: a δ=1-only preset
    must report `{1: n}`, not `{1: n, 2: 0}` with a phantom column. For v2-only
    input the support is `DELTAS`/`FUNCS` and the output is unchanged.
    """
    by_k: dict[int, dict] = {}
    presets: set[DifficultyPreset] = set()   # filled in the single pass below
    for p in problems:
        s = by_k.setdefault(p.k, {"n_problems": 0, "leaf_chars": [], "deltas": [],
                                  "vars": [], "funcs": [], "fn_pairs": [], "exp_sums": []})
        presets.add(resolve_preset(p.meta.get("preset", DEFAULT_PRESET)))
        s["n_problems"] += 1
        s["leaf_chars"].extend(len(l.prop) for l in p.oracle_plan.lemmas)
        s["deltas"].extend(d for _, d in p.meta["step_kinds"])
        s["vars"].extend(VARS[j] for j, _ in p.meta["step_kinds"])
        s["funcs"].extend(p.meta["funcs"])
        s["fn_pairs"].extend(p.meta["fn_pairs"])
        # the dominant measured pass-rate correlate (module docstring): a leaf's
        # LEFT exponent sum, i.e. every term but the last one in the chain
        s["exp_sums"].extend(p.meta["exponent_sums"][:-1])
    deltas = tuple(sorted({d for p in presets for d in p.deltas})) or DELTAS
    funcs = tuple(f for f in FUNCS if any(f in p.funcs for p in presets)) or FUNCS
    out = {}
    for k, s in sorted(by_k.items()):
        chars = sorted(s["leaf_chars"])
        out[k] = {
            "n_problems": s["n_problems"],
            "n_leaves": len(chars),
            "leaf_prop_chars": {
                "min": chars[0], "median": chars[len(chars) // 2], "max": chars[-1],
                "mean": round(sum(chars) / len(chars), 1),
            },
            "delta_mix": {d: s["deltas"].count(d) for d in deltas},
            "var_mix": {v: s["vars"].count(v) for v in VARS},
            "func_mix": {f: s["funcs"].count(f) for f in funcs},
            "fn_pair_mix": {f"{a}|{b}": s["fn_pairs"].count(f"{a}|{b}")
                            for a in funcs for b in funcs},
            "exponent_sums": {"min": min(s["exp_sums"]), "max": max(s["exp_sums"]),
                              "mean": round(sum(s["exp_sums"]) / len(s["exp_sums"]), 1)},
        }
    return out


# --------------------------------------------------------------------------
# generator
# --------------------------------------------------------------------------

def generate(k: int, seed: int, n: int = 1,
             preset: str | DifficultyPreset = DEFAULT_PRESET) -> list[GeneratedProblem]:
    """`k` bridge steps, `n` problems, deterministic in `(k, seed, preset)`.

    `preset` selects the difficulty knobs (see `PRESETS` and the module
    docstring); the default is the shipped v2 distribution and its output is
    byte-identical to the pre-preset generator.
    """
    if k < 2:
        raise ValueError(f"bridge_chain needs k >= 2 (k=1 makes the lemma the goal); got {k}")
    if n < 0:
        raise ValueError(f"n must be >= 0; got {n}")

    p = resolve_preset(preset)
    problems: list[GeneratedProblem] = []
    for idx in range(n):
        problems.append(_one(k, seed, idx, p))
    return problems


def _one(k: int, seed: int, idx: int, preset: DifficultyPreset) -> GeneratedProblem:
    """Discard/regenerate loop, on two offline gates:

    * `endpoints_resist_naive_collapse` — the binding one;
    * `hidden_intermediate_violations` — a tripwire, 0% in every run measured (distinct
      exponent sums already make an intermediate/endpoint collision impossible).

    The realised count lands in `meta["discards"]`, so the datasheet reports a measured
    discard rate rather than an assumed one.

    Non-default presets are tagged in the seed string, the problem id and the
    Lean declaration name, so two presets can be materialized side by side
    without id collisions; the default's three strings are unchanged."""
    tag = "" if preset.is_default else f"{preset.name}|"
    idtag = "" if preset.is_default else f"{preset.name}-"
    nametag = "" if preset.is_default else f"{preset.name}_"
    for attempt in range(preset.max_discards + 1):
        rng = random.Random(f"{FAMILY}|{tag}{k}|{seed}|{idx}|{attempt}")
        terms, steps, rejects = _sample_chain(rng, k, preset)
        if not endpoints_resist_naive_collapse(terms[0], terms[-1]):
            continue
        pid = f"{FAMILY}-{idtag}k{k}-s{seed}-{idx}"

        goal = GoalSpec(id=pid, prop=_prop(terms[0], terms[-1]),
                        name=f"bridge_{nametag}k{k}_s{seed}_{idx}")
        lemmas, witnesses = [], {}
        for i in range(1, k + 1):
            prop = _prop(terms[i - 1], terms[i])
            name = f"h{i}"
            lemmas.append(LemmaSpec(name=name, prop=prop))
            witnesses[name] = LeafWitness(prop=prop, proof=_witness_proof(terms[i - 1], terms[i],
                                                                         steps[i - 1]))
        plan = DecompositionPlan(lemmas=lemmas, assembly=_assembly(k))

        problem = GeneratedProblem(
            id=pid, family=FAMILY, k=k, seed=seed, goal=goal, oracle_plan=plan,
            witnesses=witnesses,
            meta={
                "visible_lemmas": [],
                "schema": SCHEMA,
                "preset": preset.name,
                "preset_knobs": preset.knobs(),
                "lower_bound": LOWER,
                "vars": list(VARS),
                "step_kinds": steps,
                "funcs": [t[4] for t in terms],
                "fn_pairs": [f"{terms[i - 1][4]}|{terms[i][4]}" for i in range(1, k + 1)],
                "intermediate_terms": [render_term(t) for t in terms[1:-1]],
                # consumed by validate.py V6b: these strings must not occur in the goal
                "hidden_terms": [render_term(t) for t in terms[1:-1]],
                "endpoint_terms": [render_term(terms[0]), render_term(terms[-1])],
                "exponent_sums": [sum(t[1]) for t in terms],
                "knobs": [{"c": t[0], "d": t[2], "o": t[3], "func": t[4]} for t in terms],
                "leaf_prop_chars": [len(l.prop) for l in lemmas],
                "goal_prop_chars": len(goal.prop),
                "resamples": rejects,
                "discards": attempt,
            },
        )
        if not hidden_intermediate_violations(problem):
            return problem
    raise RuntimeError(  # pragma: no cover - unreachable with distinct exponent sums
        f"{FAMILY}-{idtag}k{k}-s{seed}-{idx}: no candidate passed the hidden-intermediate "
        f"pre-check in {preset.max_discards} attempts"
    )


register(FAMILY, generate)
