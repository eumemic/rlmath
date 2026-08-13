#!/usr/bin/env python
"""case_tree hardening survey B — **alternative-obligation** directions.

Sibling of `scripts/probes/probe_ct_algebraic.py` (survey A, algebraic depth:
two-atom sums, quartic radicands, nested radicals). This script covers the other
axis: keep the algebra roughly where it is and change **the kind of proof
obligation** the leaf poses.

Why a schema ladder at all (`research/case-tree-forensics.md`): case_tree's 68
measured leaves sit at pass@8 mean 0.923 with *every* knob marginal flat
(0.87–0.99), because 68/68 successful DSV2-7B proofs run one memorised idiom —
`Real.sqrt_le_iff` + `nlinarith [sq_nonneg …]`, which is essentially the
generator's own witness template. There is no lever inside the knob support, so
the corridor (FAMILIES.md: mean ≈0.45, band-fit ≥0.60, zero-rate ≤0.20) is
unreachable by retuning. The family has to pose a different obligation.

Directions probed here (`DIRECTIONS`):

    baseline      the shipped schema, run through the identical harness so every
                  number below has a same-session control
    floor_sqrt    piece capped by `⌊√u⌋`, calibrated **tight** (√u exceeds the
                  cap inside the band, only its floor does not) so the memorised
                  route provably cannot close it
    ceil_sqrt     piece capped by `⌈√u⌉` — the deliberate easy twin of floor,
                  because `Int.ceil_le` composes directly with `Real.sqrt_le_iff`
    abs_quad      `N − |a(x−m)² + e|` — same geometry, `abs` instead of `√`
    abs_v         `N − a·|x − m|`     — the V-shaped piece
    two_var       `√` of a positive-definite binary quadratic form over a
                  rectangle (changes the family's case structure, not just the leaf)
    sqrt_product  `N − √u · √w` — two atoms multiplied, not added
    floor_product `N − ⌊√u · √w⌋`, tight — the combination rung
    reciprocal    `c / u` — division, with a positivity side condition
    recip_sqrt    `c / √u` — division stacked on the memorised atom
    min_inside    piece is itself a `min` of two capped quadratics: a *conjunctive*
                  leaf obligation under the goal's outer extremum tree

For each direction the script establishes the same four things, in order:

  (a) EXACT INTEGER PREDICATE — `holds_at` is checked against a 60-digit mpmath
      evaluation of the *rendered* piece at every integer of a wide window, and
      the real-valued coverage claim is checked on a dense grid across the band.
      A single disagreement is disqualifying and is reported as such: an
      under-approximating predicate makes the necessity argument unsound in the
      unsafe direction (this is exactly why `Real.log` was rejected — see the
      `case_tree` module docstring).
  (b) WITNESS EXISTS — the generator-known template kernel-checks on every
      instance, both variants, spanning the knob support.
  (c) BATTERY FLOOR — `families.validate.battery_proofs()` (10 tactics ×
      {bare, intros-first}); ANY success kills the direction. A planted positive
      control that MUST die runs in the same batch, so "everything survives"
      cannot mean "the battery is not executing".
  (d) IDIOM CEILING — the measured DSV2-7B idiom, templated, plus 2–3 plausible
      mechanical adaptations per direction. The idiom is first CALIBRATED on the
      68 measured case_tree leaves in `data/bank/family_leaf_calibration.jsonl`:
      it has to close most of them (measured pass@8 0.923) before its failure on
      a candidate is evidence about that candidate.

Plus two free (no-Lean) structural checks that decide whether a direction can
actually be *shipped* rather than merely being hard:

    necessity   simulate the real k-band tiling with the direction's `holds_at`
                and run `case_tree._redundant`: does every piece stay necessary
                without the repair firing? (a repair that fires at different
                rates per k is itself a flatness leak)
    flatness    leaf-prop length, max |coefficient| and the outer constant at
                k ∈ {2,4,8,16,32} — the outer constant must NOT grow with k

Usage:
    uv run python scripts/probes/probe_ct_functional.py --no-lean       # (a) + structure
    uv run python scripts/probes/probe_ct_functional.py                 # everything
    uv run python scripts/probes/probe_ct_functional.py --directions floor_sqrt,reciprocal
    uv run python scripts/probes/probe_ct_functional.py --skip-battery  # (a),(b),(d) only

Output: a JSON report (`--out`, default **/tmp/ct_functional_probe/report.json**).
The default lives outside the repo on purpose — this task owns exactly two files
(this script and `research/ct-hardening-survey-b.md`) and other agents are
working in the tree concurrently; pass `--out` to put it somewhere durable.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from mpmath import mp, mpf

from rlmath.families import case_tree as ct

ROOT = Path(__file__).resolve().parents[2]
BANK = ROOT / "data" / "bank" / "family_leaf_calibration.jsonl"
DEFAULT_OUT = Path("/tmp/ct_functional_probe/report.json")

mp.dps = 60

C = ct.C_LEVEL          # 3 — the bare side of every goal, shared with the family
VARIANTS = ct.VARIANTS  # ("max", "min")

# Knob grid for the probe instances. Spans WIDTHS × VERTEX_OFFSETS × CURVATURES ×
# SLACKS and four |vertex| magnitudes, because |vertex| is the family's single
# k-dependence (the band's absolute position grows like the domain, ≈7k wide).
BANDS = (
    (-7, 8, 0, 1, 0),
    (-3, 6, 1, 2, 1),
    (5, 8, -1, 3, 0),
    (13, 6, 0, 2, 1),
    (-25, 8, 1, 3, 1),
    (21, 6, -1, 1, 0),
)

# The planted positive control (task brief): v1's bare-quadratic leaf, known dead
# to `intros; nlinarith`. If THIS survives the battery the gate is not measuring
# and every "survives" verdict below is worthless.
CONTROL_PROP = "∀ x : ℝ, -7 ≤ x → x ≤ 1 → 3 ≤ -2 * x ^ 2 - 12 * x + 17"
CONTROL_EXPECTED_KILLER = "by intros; nlinarith"

BATTERY_TIMEOUT_S = 25.0     # families.validate.AUTOMATION_TIMEOUT_S
WITNESS_TIMEOUT_S = 60.0


class ControlFailed(RuntimeError):
    """The planted positive control survived: the battery gate is not measuring."""


# ---------------------------------------------------------------- rendering --


def _poly(pairs: Sequence[tuple[int, str]]) -> str:
    """Expanded polynomial from (coefficient, monomial) pairs, Lean syntax.

    Same conventions as `case_tree._render_poly` (which handles only the 1-var
    (x², x, 1) case) so a rendered radicand here is byte-identical to the shipped
    family's whenever the coefficients agree.
    """
    out = ""
    for coeff, body in pairs:
        if coeff == 0:
            continue
        mag = abs(coeff)
        term = (body if mag == 1 else f"{mag} * {body}") if body else str(mag)
        if not out:
            out = f"-{term}" if coeff < 0 else term
        else:
            out += f" - {term}" if coeff < 0 else f" + {term}"
    return out or "0"


def _lin(m: int, var: str = "x") -> str:
    """`x - m` as it must appear inside `sq_nonneg (…)` / `|…|`."""
    if m == 0:
        return var
    return f"{var} - {m}" if m > 0 else f"{var} + {-m}"


def _binder(lo: int, hi: int) -> str:
    return f"∀ x : ℝ, {lo} ≤ x → x ≤ {hi} → "


def _binder2(lo: int, hi: int, loy: int, hiy: int) -> str:
    return f"∀ x y : ℝ, {lo} ≤ x → x ≤ {hi} → {loy} ≤ y → y ≤ {hiy} → "


def _side(atom: str, variant: str, outer: int) -> str:
    """The goal's inequality for one piece.

    max: `C ≤ (C + outer) − atom`;  min: `atom − (outer − C) ≤ C`.
    Both are `atom ≤ outer`, which is what every `holds_at` below characterises.
    """
    return f"{C} ≤ {C + outer} - {atom}" if variant == "max" else f"{atom} - {outer - C} ≤ {C}"


# ---------------------------------------------------------------- the specs --


@dataclass(frozen=True)
class Spec:
    """One band and its knobs — the same support the shipped family samples."""
    lo: int
    w: int
    off: int
    a: int
    slack: int

    @property
    def m(self) -> int:
        return self.lo + self.w // 2 + self.off

    @property
    def hi(self) -> int:
        return self.lo + self.w

    @property
    def far(self) -> int:
        return max(abs(self.lo - self.m), abs(self.hi - self.m))

    @property
    def label(self) -> str:
        return f"lo{self.lo}w{self.w}o{self.off}a{self.a}s{self.slack}"


@dataclass
class Inst:
    """One probed leaf: the Lean text, the integer predicate, and the real value.

    `holds_at` and `value` are built from the *same* parameters as `prop`, and
    `check_exactness` then re-derives `value` numerically at 60 digits and
    compares — so a rendering/predicate divergence is caught rather than assumed
    away.
    """
    direction: str
    variant: str
    spec: Spec
    prop: str
    witness: str
    idioms: dict[str, str]
    holds_at: Callable[..., bool]
    value: Callable[..., mpf]
    outer: int                      # the cap the atom must respect
    coeffs: tuple[int, ...]
    exact_kind: str                 # "iff" | "over" | "under"
    n_vars: int = 1
    ybounds: tuple[int, int] | None = None
    ycenter: int | None = None
    # extra generator-known routes (not idiom adaptations): route multiplicity
    alt_witnesses: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.direction}/{self.variant}/{self.spec.label}"

    def satisfies(self, *xs) -> bool:
        """Does the rendered piece satisfy the goal's inequality at (real) xs?"""
        v = self.value(*xs)
        return v >= C if self.variant == "max" else v <= C


# --------------------------------------------------------------- the idioms --


def _hints(spec: Spec) -> str:
    """The measured DSV2 hint set: band endpoints + vertex, as `sq_nonneg`s.

    Read off the emitted proof in the task brief — for band [-7,1] with vertex
    −2 it passed `sq_nonneg (x + 2), sq_nonneg (x - 1), sq_nonneg (x + 7)`.
    """
    return (f"sq_nonneg ({_lin(spec.m)}), sq_nonneg ({_lin(spec.lo)}), "
            f"sq_nonneg ({_lin(spec.hi)})")


def idiom_verbatim(spec: Spec, atom_radicand: str | None, cap: int) -> str:
    """The measured idiom, mechanically retargeted.

    Verbatim shape from the brief; `constructor <;> nlinarith [hints]` instead of
    two separate bullets so the probe is robust to the conjunct order of
    `Real.sqrt_le_iff` (which is `0 ≤ y ∧ x ≤ y ^ 2` in this Mathlib) — a
    *strengthening* of the measured idiom, which is the right direction for a
    ceiling probe.
    """
    if atom_radicand is None:      # no √ atom to aim at: the degenerate retarget
        return f"by\n  intro x hx1 hx2\n  nlinarith [{_hints(spec)}]"
    return (
        "by\n"
        "  intro x hx1 hx2\n"
        f"  have h₁ : 0 ≤ Real.sqrt ({atom_radicand}) := by apply Real.sqrt_nonneg\n"
        f"  have h₂ : Real.sqrt ({atom_radicand}) ≤ {cap} := by\n"
        "    apply Real.sqrt_le_iff.mpr\n"
        f"    constructor <;> nlinarith [{_hints(spec)}]\n"
        f"  nlinarith [{_hints(spec)}]"
    )


def idiom_sq_sqrt(spec: Spec, radicand: str) -> str:
    """The other route seen in the bank taxonomy: `sq_sqrt` + one big nlinarith.

    Non-negativity of the radicand goes through `nlinarith [sq_nonneg (x − m)]`,
    NOT `positivity`: measured here, `positivity` cannot prove `0 ≤ x² + 6x + 17`
    (a positive-definite quadratic is not a sum of syntactically-nonneg terms), so
    a probe that used it would fail for a reason that has nothing to do with the
    direction under test."""
    return (
        "by\n"
        "  intro x hx1 hx2\n"
        f"  have hu : (0:ℝ) ≤ {radicand} := by nlinarith [sq_nonneg ({_lin(spec.m)})]\n"
        f"  nlinarith [Real.sq_sqrt hu, Real.sqrt_nonneg ({radicand}), {_hints(spec)}]"
    )


# ------------------------------------------------------------- directions ----
# Each builder maps (Spec, variant) -> Inst | None (None = knobs infeasible for
# that direction, which is recorded rather than silently skipped).


def d_baseline(s: Spec, variant: str) -> Inst | None:
    """The shipped schema. Control for everything below."""
    d = s.a * s.far**2 + s.slack
    t = ct._cap(d)
    e = t * t - d
    c2, c1, c0 = s.a, -2 * s.a * s.m, s.a * s.m**2 + e
    u = _poly([(c2, "x ^ 2"), (c1, "x"), (c0, "")])
    if t - C < 1:
        return None
    prop = _binder(s.lo, s.hi) + _side(f"Real.sqrt ({u})", variant, t)
    # `schema` became a REQUIRED first field when the rung ladder landed, deliberately with
    # no default: a defaulted schema would let a piece silently carry v2's `holds_at` into a
    # rung whose predicate differs, which is the false-necessity hole the ladder exists to
    # make structurally impossible. This probe builds the BASELINE shape, so v2 is correct
    # here — but it has to say so.
    piece = ct.Piece(ct.RUNGS["v2"], lo=s.lo, hi=s.hi, a=s.a, m=s.m, d=d, width=s.w,
                     offset=s.off, slack=s.slack)
    witness = ct.leaf_proof(piece)          # the family's own template, verbatim

    def value(x):
        r = mp.sqrt(mpf(c2) * x * x + mpf(c1) * x + mpf(c0))
        return (C + t) - r if variant == "max" else r - (t - C)

    return Inst(
        direction="baseline", variant=variant, spec=s, prop=prop, witness=witness,
        idioms={"I0_verbatim": idiom_verbatim(s, u, t),
                "I1_sq_sqrt": idiom_sq_sqrt(s, u),
                "I2_sqrt_le_iff": ("by\n  intro x hx1 hx2\n"
                                   f"  have h : Real.sqrt ({u}) ≤ {t} := Real.sqrt_le_iff.mpr\n"
                                   f"    ⟨by norm_num, by nlinarith [{_hints(s)}]⟩\n"
                                   "  linarith")},
        holds_at=lambda x: s.a * (x - s.m) ** 2 <= d,
        value=value, outer=t, coeffs=(c2, c1, c0), exact_kind="iff")


def d_floor_sqrt(s: Spec, variant: str) -> Inst | None:
    """`N − ⌊√u⌋`, calibrated tight.

    slack is forced to 1 so `u_max = t² − 1`: then `√u` exceeds the cap `T = t−1`
    on part of the band while `⌊√u⌋` does not, which is what makes the memorised
    `√u ≤ T` route *provably* insufficient rather than merely unfamiliar.

    Exactness: `⌊√u⌋ ≤ T ⟺ √u < T+1 ⟺ u < (T+1)²` (all non-negative), and at an
    integer x the value `u(x)` is an integer, so the predicate is an **iff**.
    """
    d = s.a * s.far**2 + 1                       # slack forced to 1
    t = ct._cap(d)
    e = t * t - d
    cap_t = t - 1
    if cap_t - C < 1:                            # min variant needs n = T − C ≥ 1
        return None
    c2, c1, c0 = s.a, -2 * s.a * s.m, s.a * s.m**2 + e
    u = _poly([(c2, "x ^ 2"), (c1, "x"), (c0, "")])
    atom = f"(⌊Real.sqrt ({u})⌋ : ℝ)"
    prop = _binder(s.lo, s.hi) + _side(atom, variant, cap_t)
    bound = f"Real.sqrt ({u})"
    witness = (
        "by\n"
        "  intro x hl hr\n"
        f"  have hs : {bound} < {t} := (Real.sqrt_lt' (by norm_num)).mpr (by\n"
        "    nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)])\n"
        f"  have hf : ⌊{bound}⌋ < ({t}:ℤ) := Int.floor_lt.mpr (by push_cast; linarith)\n"
        f"  have hf2 : (⌊{bound}⌋ : ℝ) ≤ {cap_t} := by exact_mod_cast Int.lt_add_one_iff.mp hf\n"
        "  linarith"
    )

    def value(x):
        r = mp.floor(mp.sqrt(mpf(c2) * x * x + mpf(c1) * x + mpf(c0)))
        return (C + cap_t) - r if variant == "max" else r - (cap_t - C)

    idioms = {
        # the memorised idiom retargeted at the √ atom with the cap the goal shows
        "I0_verbatim": idiom_verbatim(s, u, cap_t),
        # the obvious adaptation: ⌊r⌋ ≤ r, then bound r.  FALSE here by design.
        "I1_floor_le": ("by\n  intro x hx1 hx2\n"
                        f"  have hfl : (⌊{bound}⌋ : ℝ) ≤ {bound} := Int.floor_le _\n"
                        f"  have h : {bound} ≤ {cap_t} := Real.sqrt_le_iff.mpr\n"
                        f"    ⟨by norm_num, by nlinarith [{_hints(s)}]⟩\n"
                        "  linarith"),
        # simp the floor away and hand the rest to nlinarith
        "I2_simp_floor": ("by\n  intro x hx1 hx2\n"
                          "  simp only [Int.floor_le_iff, Int.le_floor, Int.floor_lt]\n"
                          f"  push_cast\n  nlinarith [{_hints(s)}, Real.sqrt_nonneg ({u})]"),
        "I3_sq_sqrt": idiom_sq_sqrt(s, u),
        # the honest hard case: the CORRECT floor lemma, with the strict sqrt
        # bound handed to nlinarith via sq_sqrt. If this closes, floor is one
        # lemma away from the idiom rather than a different obligation.
        "I4_floor_le_iff": ("by\n  intro x hx1 hx2\n"
                            f"  have hu : (0:ℝ) ≤ {u} := by nlinarith [sq_nonneg ({_lin(s.m)})]\n"
                            f"  have h : (⌊{bound}⌋ : ℝ) ≤ {cap_t} := by\n"
                            f"    have hz : ⌊{bound}⌋ ≤ ({cap_t} : ℤ) := Int.floor_le_iff.mpr (by\n"
                            "      push_cast\n"
                            f"      nlinarith [Real.sq_sqrt hu, Real.sqrt_nonneg ({u}), "
                            f"{_hints(s)}])\n"
                            "    exact_mod_cast hz\n"
                            "  linarith"),
        "I5_norm_num_floor": ("by\n  intro x hx1 hx2\n"
                              f"  have hu : (0:ℝ) ≤ {u} := by nlinarith [sq_nonneg ({_lin(s.m)})]\n"
                              "  norm_num [Int.floor_le_iff]\n"
                              f"  nlinarith [Real.sq_sqrt hu, Real.sqrt_nonneg ({u}), "
                              f"{_hints(s)}]"),
        # the floor *bracket* ⌊r⌋ ≤ r < ⌊r⌋+1 as raw hypotheses: this is the route
        # that cannot work, because nlinarith has no way to know ⌊r⌋ is an integer
        "I6_bracket": ("by\n  intro x hx1 hx2\n"
                       f"  have hu : (0:ℝ) ≤ {u} := by nlinarith [sq_nonneg ({_lin(s.m)})]\n"
                       f"  have h1 := Int.floor_le ({bound})\n"
                       f"  have h2 := Int.lt_floor_add_one ({bound})\n"
                       f"  nlinarith [Real.sq_sqrt hu, Real.sqrt_nonneg ({u}), {_hints(s)}]"),
    }
    # a SECOND generator-known route, so "only one proof exists" cannot be the
    # reason the idiom probes fail (route multiplicity, not knife-edge)
    alt = {"W1_floor_le_iff_sqrt_lt":
           ("by\n  intro x hx1 hx2\n"
            f"  have hz : ⌊{bound}⌋ ≤ ({cap_t} : ℤ) := Int.floor_le_iff.mpr (by\n"
            "    push_cast\n"
            f"    exact (Real.sqrt_lt' (by norm_num)).mpr (by nlinarith [{_hints(s)}]))\n"
            f"  have h : (⌊{bound}⌋ : ℝ) ≤ {cap_t} := by exact_mod_cast hz\n"
            "  linarith")}
    return Inst(direction="floor_sqrt", variant=variant, spec=s, prop=prop,
                witness=witness, idioms=idioms, alt_witnesses=alt,
                holds_at=lambda x: s.a * (x - s.m) ** 2 + e < t * t,
                value=value, outer=cap_t, coeffs=(c2, c1, c0), exact_kind="iff")


def d_floor_sqrt_loose(s: Spec, variant: str) -> Inst | None:
    """`N − ⌊√u⌋` with the cap set **loose** (`T = t`, so `√u ≤ T` already holds
    on the band).

    This is the mechanism control for `floor_sqrt`: same symbol, same lemma
    surface, only the calibration differs. If the loose version dies to the
    one-line `Int.floor_le` adaptation and the tight one does not, then what
    hardens `floor_sqrt` is the *tightness*, not the `⌊·⌋`."""
    d = s.a * s.far**2 + s.slack
    t = ct._cap(d)
    e = t * t - d
    if t - C < 1:
        return None
    c2, c1, c0 = s.a, -2 * s.a * s.m, s.a * s.m**2 + e
    u = _poly([(c2, "x ^ 2"), (c1, "x"), (c0, "")])
    bound = f"Real.sqrt ({u})"
    prop = _binder(s.lo, s.hi) + _side(f"(⌊{bound}⌋ : ℝ)", variant, t)
    witness = (
        "by\n"
        "  intro x hl hr\n"
        f"  have hs : {bound} ≤ {t} := Real.sqrt_le_iff.mpr ⟨by norm_num, by\n"
        "    nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]⟩\n"
        f"  have hf : (⌊{bound}⌋ : ℝ) ≤ {bound} := Int.floor_le _\n"
        "  linarith"
    )

    def value(x):
        r = mp.floor(mp.sqrt(mpf(c2) * x * x + mpf(c1) * x + mpf(c0)))
        return (C + t) - r if variant == "max" else r - (t - C)

    idioms = {
        "I0_verbatim": idiom_verbatim(s, u, t),
        "I1_floor_le": ("by\n  intro x hx1 hx2\n"
                        f"  have hfl : (⌊{bound}⌋ : ℝ) ≤ {bound} := Int.floor_le _\n"
                        f"  have h : {bound} ≤ {t} := Real.sqrt_le_iff.mpr\n"
                        f"    ⟨by norm_num, by nlinarith [{_hints(s)}]⟩\n"
                        "  linarith"),
        "I2_simp_floor": ("by\n  intro x hx1 hx2\n"
                          "  simp only [Int.floor_le_iff, Int.le_floor, Int.floor_lt]\n"
                          f"  push_cast\n  nlinarith [{_hints(s)}, Real.sqrt_nonneg ({u})]"),
        "I3_sq_sqrt": idiom_sq_sqrt(s, u),
    }
    return Inst(direction="floor_sqrt_loose", variant=variant, spec=s, prop=prop,
                witness=witness, idioms=idioms,
                holds_at=lambda x: s.a * (x - s.m) ** 2 + e < (t + 1) ** 2,
                value=value, outer=t, coeffs=(c2, c1, c0), exact_kind="iff")


def d_ceil_sqrt(s: Spec, variant: str) -> Inst | None:
    """`N − ⌈√u⌉`: the easy twin. `⌈√u⌉ ≤ t ⟺ √u ≤ t ⟺ u ≤ t²` — the *same*
    integer condition as the shipped schema, one `Int.ceil_le` deeper."""
    d = s.a * s.far**2 + s.slack
    t = ct._cap(d)
    e = t * t - d
    if t - C < 1:
        return None
    c2, c1, c0 = s.a, -2 * s.a * s.m, s.a * s.m**2 + e
    u = _poly([(c2, "x ^ 2"), (c1, "x"), (c0, "")])
    atom = f"(⌈Real.sqrt ({u})⌉ : ℝ)"
    prop = _binder(s.lo, s.hi) + _side(atom, variant, t)
    bound = f"Real.sqrt ({u})"
    witness = (
        "by\n"
        "  intro x hl hr\n"
        f"  have hs : {bound} ≤ {t} := Real.sqrt_le_iff.mpr ⟨by norm_num, by\n"
        "    nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]⟩\n"
        f"  have hc : ⌈{bound}⌉ ≤ ({t}:ℤ) := Int.ceil_le.mpr (by push_cast; linarith)\n"
        f"  have hc2 : (⌈{bound}⌉ : ℝ) ≤ {t} := by exact_mod_cast hc\n"
        "  linarith"
    )

    def value(x):
        r = mp.ceil(mp.sqrt(mpf(c2) * x * x + mpf(c1) * x + mpf(c0)))
        return (C + t) - r if variant == "max" else r - (t - C)

    idioms = {
        "I0_verbatim": idiom_verbatim(s, u, t),
        "I1_ceil_le": ("by\n  intro x hx1 hx2\n"
                       f"  have h : {bound} ≤ {t} := Real.sqrt_le_iff.mpr\n"
                       f"    ⟨by norm_num, by nlinarith [{_hints(s)}]⟩\n"
                       f"  have hc : (⌈{bound}⌉ : ℝ) ≤ {t} := by\n"
                       f"    exact_mod_cast Int.ceil_le.mpr (by push_cast; linarith)\n"
                       "  linarith"),
        "I2_simp_ceil": ("by\n  intro x hx1 hx2\n"
                         "  simp only [Int.ceil_le]\n  push_cast\n"
                         f"  nlinarith [{_hints(s)}, Real.sqrt_nonneg ({u})]"),
    }
    return Inst(direction="ceil_sqrt", variant=variant, spec=s, prop=prop,
                witness=witness, idioms=idioms,
                holds_at=lambda x: s.a * (x - s.m) ** 2 <= d,
                value=value, outer=t, coeffs=(c2, c1, c0), exact_kind="iff")


def d_abs_quad(s: Spec, variant: str) -> Inst | None:
    """`N − |a(x−m)² + e|`: identical geometry, `abs` instead of `√`.

    Exactness: the radicand is positive definite, so `|q| ≤ T ⟺ q ≤ T` and the
    predicate is an **iff** on integers (indeed on the reals)."""
    e = 1 + s.slack
    cap_t = s.a * s.far**2 + e
    c2, c1, c0 = s.a, -2 * s.a * s.m, s.a * s.m**2 + e
    q = _poly([(c2, "x ^ 2"), (c1, "x"), (c0, "")])
    prop = _binder(s.lo, s.hi) + _side(f"|{q}|", variant, cap_t)
    witness = (
        "by\n"
        "  intro x hl hr\n"
        f"  have h : |{q}| ≤ {cap_t} := abs_le.mpr ⟨by nlinarith [sq_nonneg ({_lin(s.m)})], by\n"
        "    nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]⟩\n"
        "  linarith"
    )

    def value(x):
        q_ = abs(mpf(c2) * x * x + mpf(c1) * x + mpf(c0))
        return (C + cap_t) - q_ if variant == "max" else q_ - (cap_t - C)

    idioms = {
        "I0_verbatim": idiom_verbatim(s, None, cap_t),
        "I1_abs_le": ("by\n  intro x hx1 hx2\n"
                      f"  have h : |{q}| ≤ {cap_t} := abs_le.mpr\n"
                      f"    ⟨by nlinarith [{_hints(s)}], by nlinarith [{_hints(s)}]⟩\n"
                      "  linarith"),
        "I2_simp_abs": ("by\n  intro x hx1 hx2\n  simp only [abs_le]\n"
                        f"  constructor <;> nlinarith [{_hints(s)}]"),
        "I3_abs_of_nonneg": ("by\n  intro x hx1 hx2\n"
                             f"  rw [abs_of_nonneg (by nlinarith [sq_nonneg ({_lin(s.m)})] : "
                             f"(0:ℝ) ≤ {q})]\n"
                             f"  nlinarith [{_hints(s)}]"),
    }
    return Inst(direction="abs_quad", variant=variant, spec=s, prop=prop,
                witness=witness, idioms=idioms,
                holds_at=lambda x: s.a * (x - s.m) ** 2 + e <= cap_t,
                value=value, outer=cap_t, coeffs=(c2, c1, c0), exact_kind="iff")


def d_abs_v(s: Spec, variant: str) -> Inst | None:
    """`N − a·|x − m|`: the V-shaped piece. `a|x−m| ≤ T` is an **iff** predicate."""
    cap_t = s.a * s.far + s.slack
    if cap_t - C < 1:
        return None
    body = _lin(s.m)
    atom = f"|{body}|" if s.a == 1 else f"{s.a} * |{body}|"
    prop = _binder(s.lo, s.hi) + _side(atom, variant, cap_t)
    witness = (
        "by\n"
        "  intro x hl hr\n"
        f"  have h : |{body}| ≤ {mpf(cap_t) / s.a if s.a != 1 else cap_t} := "
        "abs_le.mpr ⟨by linarith, by linarith⟩\n"
        "  linarith"
    ) if s.a == 1 else (
        "by\n"
        "  intro x hl hr\n"
        f"  have h : |{body}| ≤ {cap_t} / {s.a} := abs_le.mpr ⟨by linarith, by linarith⟩\n"
        "  linarith"
    )

    def value(x):
        v = s.a * abs(mpf(x) - s.m)
        return (C + cap_t) - v if variant == "max" else v - (cap_t - C)

    idioms = {
        "I0_verbatim": idiom_verbatim(s, None, cap_t),
        # bound |x − m| by `far` (an integer, and true on the band) rather than by
        # cap/a, which need not be integral when a > 1
        "I1_abs_le": ("by\n  intro x hx1 hx2\n"
                      f"  have h : |{body}| ≤ {s.far} := abs_le.mpr ⟨by linarith, by linarith⟩\n"
                      "  linarith"),
        "I2_simp_abs": ("by\n  intro x hx1 hx2\n  simp only [abs_le]\n"
                        "  constructor <;> linarith"),
        "I3_cases_abs": ("by\n  intro x hx1 hx2\n"
                         f"  rcases abs_cases ({body}) with ⟨h, _⟩ | ⟨h, _⟩ <;> "
                         "rw [h] <;> linarith"),
    }
    return Inst(direction="abs_v", variant=variant, spec=s, prop=prop,
                witness=witness, idioms=idioms,
                holds_at=lambda x: s.a * abs(x - s.m) <= cap_t,
                value=value, outer=cap_t, coeffs=(s.a, s.m), exact_kind="iff")


def d_two_var(s: Spec, variant: str, s2: Spec | None = None) -> Inst | None:
    """`√` of a positive-definite binary quadratic form over a rectangle.

    `√Q ≤ t ⟺ Q ≤ t²` is still an **iff**; the change is the *case structure* —
    the split now tiles a rectangle, not an interval."""
    s2 = s2 or Spec(lo=s.lo + 11, w=8 if s.w == 6 else 6, off=-s.off, a=(s.a % 3) + 1,
                    slack=s.slack)
    dq = s.a * s.far**2 + s2.a * s2.far**2 + s.slack
    t = ct._cap(dq)
    e = t * t - dq
    if t - C < 1:
        return None
    ax, px = s.a, -2 * s.a * s.m
    by, py = s2.a, -2 * s2.a * s2.m
    c0 = s.a * s.m**2 + s2.a * s2.m**2 + e
    q = _poly([(ax, "x ^ 2"), (px, "x"), (by, "y ^ 2"), (py, "y"), (c0, "")])
    prop = _binder2(s.lo, s.hi, s2.lo, s2.hi) + _side(f"Real.sqrt ({q})", variant, t)
    witness = (
        "by\n"
        "  intro x y hx1 hx2 hy1 hy2\n"
        f"  have h : Real.sqrt ({q}) ≤ {t} := Real.sqrt_le_iff.mpr ⟨by norm_num, by\n"
        "    nlinarith [mul_nonneg (sub_nonneg.mpr hx1) (sub_nonneg.mpr hx2),\n"
        "               mul_nonneg (sub_nonneg.mpr hy1) (sub_nonneg.mpr hy2)]⟩\n"
        "  linarith"
    )

    def value(x, y):
        r = mp.sqrt(mpf(ax) * x * x + mpf(px) * x + mpf(by) * y * y + mpf(py) * y + mpf(c0))
        return (C + t) - r if variant == "max" else r - (t - C)

    h2 = (f"sq_nonneg ({_lin(s.m)}), sq_nonneg ({_lin(s.lo)}), sq_nonneg ({_lin(s.hi)}), "
          f"sq_nonneg ({_lin(s2.m, 'y')}), sq_nonneg ({_lin(s2.lo, 'y')}), "
          f"sq_nonneg ({_lin(s2.hi, 'y')})")
    idioms = {
        "I0_verbatim": ("by\n  intro x y hx1 hx2 hy1 hy2\n"
                        f"  have h₁ : 0 ≤ Real.sqrt ({q}) := by apply Real.sqrt_nonneg\n"
                        f"  have h₂ : Real.sqrt ({q}) ≤ {t} := by\n"
                        "    apply Real.sqrt_le_iff.mpr\n"
                        f"    constructor <;> nlinarith [{h2}]\n"
                        f"  nlinarith [{h2}]"),
        "I1_sq_sqrt": ("by\n  intro x y hx1 hx2 hy1 hy2\n"
                       f"  have hu : (0:ℝ) ≤ {q} := by nlinarith [sq_nonneg ({_lin(s.m)}), sq_nonneg ({_lin(s2.m, 'y')})]\n"
                       f"  nlinarith [Real.sq_sqrt hu, Real.sqrt_nonneg ({q}), {h2}]"),
        "I2_bandprod": ("by\n  intro x y hx1 hx2 hy1 hy2\n"
                        f"  have h : Real.sqrt ({q}) ≤ {t} := Real.sqrt_le_iff.mpr\n"
                        "    ⟨by norm_num, by nlinarith [mul_nonneg (sub_nonneg.mpr hx1) "
                        "(sub_nonneg.mpr hx2), mul_nonneg (sub_nonneg.mpr hy1) "
                        "(sub_nonneg.mpr hy2)]⟩\n"
                        "  linarith"),
    }
    return Inst(direction="two_var", variant=variant, spec=s, prop=prop, witness=witness,
                idioms=idioms,
                holds_at=lambda x, y: s.a * (x - s.m) ** 2 + s2.a * (y - s2.m) ** 2 <= dq,
                value=value, outer=t, coeffs=(ax, px, by, py, c0), exact_kind="iff",
                n_vars=2, ybounds=(s2.lo, s2.hi), ycenter=s2.m)


def d_sqrt_product(s: Spec, variant: str) -> Inst | None:
    """`N − √u · √w`, two atoms multiplied.

    `√u·√w = √(uw)`, so `√u·√w ≤ T ⟺ u·w ≤ T²` — an **iff**, quartic but exactly
    integer. The caps are chosen so `u_max = t₁²` and `w_max = t₂²` *exactly*,
    which makes the real super-level set exactly `[m−far, m+far]`: zero spill,
    hence maximal necessity margin."""
    b = (s.a % 3) + 1
    t1 = ct._cap(s.a * s.far**2)
    t2 = ct._cap(b * s.far**2)
    e1 = t1 * t1 - s.a * s.far**2
    e2 = t2 * t2 - b * s.far**2
    cap_t = t1 * t2
    u = _poly([(s.a, "x ^ 2"), (-2 * s.a * s.m, "x"), (s.a * s.m**2 + e1, "")])
    w = _poly([(b, "x ^ 2"), (-2 * b * s.m, "x"), (b * s.m**2 + e2, "")])
    prop = _binder(s.lo, s.hi) + _side(f"Real.sqrt ({u}) * Real.sqrt ({w})", variant, cap_t)
    witness = (
        "by\n"
        "  intro x hl hr\n"
        "  have hb := mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)\n"
        f"  have h1 : Real.sqrt ({u}) ≤ {t1} := Real.sqrt_le_iff.mpr "
        "⟨by norm_num, by nlinarith⟩\n"
        f"  have h2 : Real.sqrt ({w}) ≤ {t2} := Real.sqrt_le_iff.mpr "
        "⟨by norm_num, by nlinarith⟩\n"
        f"  have h3 : Real.sqrt ({u}) * Real.sqrt ({w}) ≤ {t1} * {t2} :=\n"
        "    mul_le_mul h1 h2 (Real.sqrt_nonneg _) (by norm_num)\n"
        "  linarith"
    )

    def uval(x):
        return mpf(s.a) * (mpf(x) - s.m) ** 2 + e1

    def wval(x):
        return mpf(b) * (mpf(x) - s.m) ** 2 + e2

    def value(x):
        r = mp.sqrt(uval(x)) * mp.sqrt(wval(x))
        return (C + cap_t) - r if variant == "max" else r - (cap_t - C)

    idioms = {
        "I0_verbatim": idiom_verbatim(s, u, cap_t),
        "I1_sqrt_mul": ("by\n  intro x hx1 hx2\n"
                        f"  rw [← Real.sqrt_mul (by nlinarith [sq_nonneg ({_lin(s.m)})]) ({w})]\n"
                        f"  have h : Real.sqrt (({u}) * ({w})) ≤ {cap_t} := Real.sqrt_le_iff.mpr\n"
                        f"    ⟨by norm_num, by nlinarith [{_hints(s)}]⟩\n"
                        "  linarith"),
        "I2_two_bounds": ("by\n  intro x hx1 hx2\n"
                          f"  have h1 : Real.sqrt ({u}) ≤ {t1} := Real.sqrt_le_iff.mpr\n"
                          f"    ⟨by norm_num, by nlinarith [{_hints(s)}]⟩\n"
                          f"  have h2 : Real.sqrt ({w}) ≤ {t2} := Real.sqrt_le_iff.mpr\n"
                          f"    ⟨by norm_num, by nlinarith [{_hints(s)}]⟩\n"
                          f"  nlinarith [Real.sqrt_nonneg ({u}), Real.sqrt_nonneg ({w})]"),
        "I3_sq_sqrt": ("by\n  intro x hx1 hx2\n"
                       f"  have hu : (0:ℝ) ≤ {u} := by nlinarith [sq_nonneg ({_lin(s.m)})]\n"
                       f"  have hw : (0:ℝ) ≤ {w} := by nlinarith [sq_nonneg ({_lin(s.m)})]\n"
                       f"  nlinarith [Real.sq_sqrt hu, Real.sq_sqrt hw, Real.sqrt_nonneg ({u}),"
                       f" Real.sqrt_nonneg ({w}), {_hints(s)}]"),
    }
    return Inst(direction="sqrt_product", variant=variant, spec=s, prop=prop,
                witness=witness, idioms=idioms,
                holds_at=lambda x: (s.a * (x - s.m) ** 2 + e1) * (b * (x - s.m) ** 2 + e2)
                <= cap_t * cap_t,
                value=value, outer=cap_t,
                coeffs=(s.a, -2 * s.a * s.m, s.a * s.m**2 + e1,
                        b, -2 * b * s.m, b * s.m**2 + e2), exact_kind="iff")


def d_floor_product(s: Spec, variant: str) -> Inst | None:
    """`N − ⌊√u · √w⌋`, tight — the combination rung.

    Composes the two directions that resist most: the product atom (the verbatim
    idiom cannot aim at it) and the tight floor (the memorised bound `√· ≤ T` is
    *false* on part of the band). Exactness is still an **iff**:
    `⌊√u·√w⌋ ≤ T ⟺ √(uw) < T+1 ⟺ u·w < (T+1)²`, and `u(x)·w(x)` is an integer at
    integer x. The pad is bumped until `P = u_max·w_max` is not a perfect square,
    which is what guarantees `T² < P < (T+1)²` — coverage and tightness at once.
    """
    b = (s.a % 3) + 1
    e1, e2 = 1 + s.slack, 1
    for _ in range(64):
        p = (s.a * s.far**2 + e1) * (b * s.far**2 + e2)
        t = math.isqrt(p)
        if t * t != p:                 # T² < P < (T+1)²: tight AND covered
            break
        e1 += 1
    else:                              # pragma: no cover — 64 consecutive squares
        return None
    if t - C < 1:
        return None
    u = _poly([(s.a, "x ^ 2"), (-2 * s.a * s.m, "x"), (s.a * s.m**2 + e1, "")])
    w = _poly([(b, "x ^ 2"), (-2 * b * s.m, "x"), (b * s.m**2 + e2, "")])
    atom = f"(⌊Real.sqrt ({u}) * Real.sqrt ({w})⌋ : ℝ)"
    prop = _binder(s.lo, s.hi) + _side(atom, variant, t)
    umax, wmax = s.a * s.far**2 + e1, b * s.far**2 + e2
    witness = (
        "by\n"
        "  intro x hl hr\n"
        "  have hb := mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)\n"
        f"  have hu0 : (0:ℝ) ≤ {u} := by nlinarith [sq_nonneg ({_lin(s.m)})]\n"
        f"  have hw0 : (0:ℝ) ≤ {w} := by nlinarith [sq_nonneg ({_lin(s.m)})]\n"
        f"  have hu : {u} ≤ {umax} := by nlinarith\n"
        f"  have hw : {w} ≤ {wmax} := by nlinarith\n"
        f"  have hp : ({u}) * ({w}) < {(t + 1) ** 2} := by nlinarith\n"
        f"  have heq : Real.sqrt ({u}) * Real.sqrt ({w}) = Real.sqrt (({u}) * ({w})) :=\n"
        f"    (Real.sqrt_mul hu0 ({w})).symm\n"
        f"  have hs : Real.sqrt (({u}) * ({w})) < {t + 1} := "
        "(Real.sqrt_lt' (by norm_num)).mpr (by nlinarith)\n"
        f"  have hlt : Real.sqrt ({u}) * Real.sqrt ({w}) < {t + 1} := by rw [heq]; exact hs\n"
        f"  have hf : ⌊Real.sqrt ({u}) * Real.sqrt ({w})⌋ < ({t + 1}:ℤ) :=\n"
        "    Int.floor_lt.mpr (by push_cast; linarith)\n"
        f"  have hf2 : (⌊Real.sqrt ({u}) * Real.sqrt ({w})⌋ : ℝ) ≤ {t} := by\n"
        "    exact_mod_cast Int.lt_add_one_iff.mp hf\n"
        "  linarith"
    )

    def value(x):
        uu = mpf(s.a) * (mpf(x) - s.m) ** 2 + e1
        ww = mpf(b) * (mpf(x) - s.m) ** 2 + e2
        r = mp.floor(mp.sqrt(uu) * mp.sqrt(ww))
        return (C + t) - r if variant == "max" else r - (t - C)

    idioms = {
        "I0_verbatim": idiom_verbatim(s, u, t),
        "I1_floor_le_two_bounds": ("by\n  intro x hx1 hx2\n"
                                   f"  have hfl : (⌊Real.sqrt ({u}) * Real.sqrt ({w})⌋ : ℝ) ≤ "
                                   f"Real.sqrt ({u}) * Real.sqrt ({w}) := Int.floor_le _\n"
                                   f"  have h1 : Real.sqrt ({u}) ≤ {math.isqrt(umax) + 1} := "
                                   f"Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith [{_hints(s)}]⟩\n"
                                   f"  have h2 : Real.sqrt ({w}) ≤ {math.isqrt(wmax) + 1} := "
                                   f"Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith [{_hints(s)}]⟩\n"
                                   f"  nlinarith [Real.sqrt_nonneg ({u}), Real.sqrt_nonneg ({w})]"),
        "I2_floor_le_iff": ("by\n  intro x hx1 hx2\n"
                            f"  have hu : (0:ℝ) ≤ {u} := by nlinarith [sq_nonneg ({_lin(s.m)})]\n"
                            f"  have hw : (0:ℝ) ≤ {w} := by nlinarith [sq_nonneg ({_lin(s.m)})]\n"
                            f"  have h : (⌊Real.sqrt ({u}) * Real.sqrt ({w})⌋ : ℝ) ≤ {t} := by\n"
                            f"    have hz : ⌊Real.sqrt ({u}) * Real.sqrt ({w})⌋ ≤ ({t} : ℤ) :=\n"
                            "      Int.floor_le_iff.mpr (by\n        push_cast\n"
                            f"        nlinarith [Real.sq_sqrt hu, Real.sq_sqrt hw, "
                            f"Real.sqrt_nonneg ({u}), Real.sqrt_nonneg ({w}), {_hints(s)}])\n"
                            "    exact_mod_cast hz\n"
                            "  linarith"),
        "I3_sq_sqrt": ("by\n  intro x hx1 hx2\n"
                       f"  have hu : (0:ℝ) ≤ {u} := by nlinarith [sq_nonneg ({_lin(s.m)})]\n"
                       f"  have hw : (0:ℝ) ≤ {w} := by nlinarith [sq_nonneg ({_lin(s.m)})]\n"
                       f"  nlinarith [Real.sq_sqrt hu, Real.sq_sqrt hw, Real.sqrt_nonneg ({u}), "
                       f"Real.sqrt_nonneg ({w}), Int.floor_le (Real.sqrt ({u}) * Real.sqrt ({w})), "
                       f"{_hints(s)}]"),
    }
    return Inst(direction="floor_product", variant=variant, spec=s, prop=prop,
                witness=witness, idioms=idioms,
                holds_at=lambda x: ((s.a * (x - s.m) ** 2 + e1) * (b * (x - s.m) ** 2 + e2)
                                    < (t + 1) ** 2),
                value=value, outer=t,
                coeffs=(s.a, -2 * s.a * s.m, s.a * s.m**2 + e1,
                        b, -2 * b * s.m, b * s.m**2 + e2), exact_kind="iff")


def d_reciprocal(s: Spec, variant: str) -> Inst | None:
    """`c / u`: the piece IS the quotient (a bump), so its super-level set is
    bounded without any outer subtraction.

    `C ≤ c/u ⟺ C·u ≤ c` (u > 0 everywhere) — an **iff**, and `u` is an integer at
    integer x, so no floating point enters the truth argument."""
    e = 1 + s.slack
    g = C                                   # max: C ≤ c/u ; min: (n−C) ≤ c/u with n = 2C
    cval = g * (s.a * s.far**2 + e)
    c2, c1, c0 = s.a, -2 * s.a * s.m, s.a * s.m**2 + e
    u = _poly([(c2, "x ^ 2"), (c1, "x"), (c0, "")])
    body = f"{cval} / ({u})"
    prop = _binder(s.lo, s.hi) + (f"{C} ≤ {body}" if variant == "max"
                                  else f"{C + g} - {body} ≤ {C}")
    pos = f"  have hu : (0:ℝ) < {u} := by nlinarith [sq_nonneg ({_lin(s.m)})]\n"
    core = ("  rw [le_div_iff₀ hu]\n"
            "  nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]")
    if variant == "max":
        witness = "by\n  intro x hl hr\n" + pos + core
    else:
        witness = ("by\n  intro x hl hr\n" + pos
                   + f"  have h : ({g}:ℝ) ≤ {body} := by\n"
                     "    rw [le_div_iff₀ hu]\n"
                     "    nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]\n"
                     "  linarith")

    def value(x):
        q = mpf(cval) / (mpf(c2) * x * x + mpf(c1) * x + mpf(c0))
        return q if variant == "max" else (C + g) - q

    idioms = {
        "I0_verbatim": idiom_verbatim(s, None, cval),
        "I1_le_div": ("by\n  intro x hx1 hx2\n"
                      f"  have hu : (0:ℝ) < {u} := by nlinarith [{_hints(s)}]\n"
                      f"  rw [le_div_iff₀ hu]\n"
                      f"  nlinarith [{_hints(s)}]") if variant == "max" else (
                      "by\n  intro x hx1 hx2\n"
                      f"  have hu : (0:ℝ) < {u} := by nlinarith [{_hints(s)}]\n"
                      f"  have h : ({g}:ℝ) ≤ {body} := by\n"
                      f"    rw [le_div_iff₀ hu]\n    nlinarith [{_hints(s)}]\n"
                      "  linarith"),
        "I2_field_simp": ("by\n  intro x hx1 hx2\n"
                          f"  have hu : (0:ℝ) < {u} := by nlinarith [{_hints(s)}]\n"
                          "  rw [ge_iff_le, div_le_iff₀ hu] <;> "
                          f"nlinarith [{_hints(s)}]"),
        "I3_div_nlinarith": ("by\n  intro x hx1 hx2\n"
                             f"  have hu : (0:ℝ) < {u} := by nlinarith [sq_nonneg ({_lin(s.m)})]\n"
                             f"  have hd : {body} * ({u}) = {cval} := by field_simp\n"
                             f"  nlinarith [{_hints(s)}, hd, hu]"),
    }
    return Inst(direction="reciprocal", variant=variant, spec=s, prop=prop,
                witness=witness, idioms=idioms,
                holds_at=lambda x: g * (s.a * (x - s.m) ** 2 + e) <= cval,
                value=value, outer=cval, coeffs=(c2, c1, c0), exact_kind="iff")


def d_recip_sqrt(s: Spec, variant: str) -> Inst | None:
    """`c / √u`: division stacked on the memorised atom.

    `C ≤ c/√u ⟺ C·√u ≤ c ⟺ C²·u ≤ c²` (everything positive) — an **iff**."""
    e = 1 + s.slack
    t = ct._cap(s.a * s.far**2 + e - 1)      # smallest t with t² ≥ u_max
    cval = C * t
    c2, c1, c0 = s.a, -2 * s.a * s.m, s.a * s.m**2 + e
    u = _poly([(c2, "x ^ 2"), (c1, "x"), (c0, "")])
    body = f"{cval} / Real.sqrt ({u})"
    prop = _binder(s.lo, s.hi) + (f"{C} ≤ {body}" if variant == "max"
                                  else f"{2 * C} - {body} ≤ {C}")
    core = (
        f"  have hu : (0:ℝ) < {u} := by nlinarith [sq_nonneg ({_lin(s.m)})]\n"
        f"  have hs : Real.sqrt ({u}) ≤ {t} := Real.sqrt_le_iff.mpr ⟨by norm_num, by\n"
        "    nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]⟩\n"
        f"  have hp : 0 < Real.sqrt ({u}) := Real.sqrt_pos.mpr hu\n"
        f"  have hk : ({C}:ℝ) ≤ {body} := by\n"
        "    rw [le_div_iff₀ hp]\n    nlinarith\n"
    )
    witness = "by\n  intro x hl hr\n" + core + "  linarith"

    def value(x):
        q = mpf(cval) / mp.sqrt(mpf(c2) * x * x + mpf(c1) * x + mpf(c0))
        return q if variant == "max" else 2 * C - q

    idioms = {
        "I0_verbatim": idiom_verbatim(s, u, t),
        "I1_le_div": (("by\n  intro x hx1 hx2\n"
                       f"  have hu : (0:ℝ) < {u} := by nlinarith [{_hints(s)}]\n"
                       f"  have hp : 0 < Real.sqrt ({u}) := Real.sqrt_pos.mpr hu\n"
                       f"  rw [le_div_iff₀ hp]\n"
                       f"  nlinarith [Real.sq_sqrt hu.le, Real.sqrt_nonneg ({u}), {_hints(s)}]")
                      if variant == "max" else
                      ("by\n  intro x hx1 hx2\n"
                       f"  have hu : (0:ℝ) < {u} := by nlinarith [{_hints(s)}]\n"
                       f"  have hp : 0 < Real.sqrt ({u}) := Real.sqrt_pos.mpr hu\n"
                       f"  have h : ({C}:ℝ) ≤ {body} := by\n"
                       f"    rw [le_div_iff₀ hp]\n"
                       f"    nlinarith [Real.sq_sqrt hu.le, Real.sqrt_nonneg ({u}), {_hints(s)}]\n"
                       "  linarith")),
        "I2_sqrt_le_then_div": ("by\n  intro x hx1 hx2\n"
                                f"  have hu : (0:ℝ) < {u} := by nlinarith [sq_nonneg ({_lin(s.m)})]\n"
                                f"  have hs : Real.sqrt ({u}) ≤ {t} := Real.sqrt_le_iff.mpr\n"
                                f"    ⟨by norm_num, by nlinarith [{_hints(s)}]⟩\n"
                                f"  have hp : 0 < Real.sqrt ({u}) := Real.sqrt_pos.mpr hu\n"
                                f"  rw [le_div_iff₀ hp]\n  nlinarith"),
    }
    return Inst(direction="recip_sqrt", variant=variant, spec=s, prop=prop,
                witness=witness, idioms=idioms,
                holds_at=lambda x: C * C * (s.a * (x - s.m) ** 2 + e) <= cval * cval,
                value=value, outer=cval, coeffs=(c2, c1, c0), exact_kind="iff")


def d_min_inside(s: Spec, variant: str) -> Inst | None:
    """The piece is itself a `min` of two capped quadratics (a `max` under the
    `min` goal): a **conjunctive** leaf obligation.

    Exactness: the super-level set is the *intersection* of two exact conditions,
    so the predicate stays an **iff** and the piece spills *less* than either
    half — the necessity margin improves."""
    m1, m2 = s.m - 1, s.m + 1
    a1, a2 = s.a, (s.a % 3) + 1
    far1 = max(abs(s.lo - m1), abs(s.hi - m1))
    far2 = max(abs(s.lo - m2), abs(s.hi - m2))
    d1, d2 = a1 * far1**2 + s.slack, a2 * far2**2 + s.slack
    t1, t2 = ct._cap(d1), ct._cap(d2)
    e1, e2 = t1 * t1 - d1, t2 * t2 - d2
    if min(t1, t2) - C < 1:
        return None
    u1 = _poly([(a1, "x ^ 2"), (-2 * a1 * m1, "x"), (a1 * m1**2 + e1, "")])
    u2 = _poly([(a2, "x ^ 2"), (-2 * a2 * m2, "x"), (a2 * m2**2 + e2, "")])
    if variant == "max":
        atom = (f"min ({C + t1} - Real.sqrt ({u1})) ({C + t2} - Real.sqrt ({u2}))")
        prop = _binder(s.lo, s.hi) + f"{C} ≤ {atom}"
        close = "  exact le_min (by linarith) (by linarith)"
    else:
        atom = (f"max (Real.sqrt ({u1}) - {t1 - C}) (Real.sqrt ({u2}) - {t2 - C})")
        prop = _binder(s.lo, s.hi) + f"{atom} ≤ {C}"
        close = "  exact max_le (by linarith) (by linarith)"
    witness = (
        "by\n"
        "  intro x hl hr\n"
        "  have hb := mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)\n"
        f"  have h1 : Real.sqrt ({u1}) ≤ {t1} := Real.sqrt_le_iff.mpr "
        "⟨by norm_num, by nlinarith⟩\n"
        f"  have h2 : Real.sqrt ({u2}) ≤ {t2} := Real.sqrt_le_iff.mpr "
        "⟨by norm_num, by nlinarith⟩\n" + close
    )

    def value(x):
        r1 = mp.sqrt(mpf(a1) * (mpf(x) - m1) ** 2 + e1)
        r2 = mp.sqrt(mpf(a2) * (mpf(x) - m2) ** 2 + e2)
        if variant == "max":
            return min((C + t1) - r1, (C + t2) - r2)
        return max(r1 - (t1 - C), r2 - (t2 - C))

    hint1 = f"sq_nonneg ({_lin(m1)}), sq_nonneg ({_lin(s.lo)}), sq_nonneg ({_lin(s.hi)})"
    hint2 = f"sq_nonneg ({_lin(m2)}), sq_nonneg ({_lin(s.lo)}), sq_nonneg ({_lin(s.hi)})"
    idioms = {
        "I0_verbatim": idiom_verbatim(s, u1, t1),
        "I1_split": ("by\n  intro x hx1 hx2\n"
                     + ("  simp only [le_min_iff]\n" if variant == "max"
                        else "  simp only [max_le_iff]\n")
                     + "  constructor\n"
                     f"  · have h : Real.sqrt ({u1}) ≤ {t1} := Real.sqrt_le_iff.mpr\n"
                     f"      ⟨by norm_num, by nlinarith [{hint1}]⟩\n    linarith\n"
                     f"  · have h : Real.sqrt ({u2}) ≤ {t2} := Real.sqrt_le_iff.mpr\n"
                     f"      ⟨by norm_num, by nlinarith [{hint2}]⟩\n    linarith"),
        "I2_le_min": ("by\n  intro x hx1 hx2\n"
                      f"  have h1 : Real.sqrt ({u1}) ≤ {t1} := Real.sqrt_le_iff.mpr\n"
                      f"    ⟨by norm_num, by nlinarith [{hint1}]⟩\n"
                      f"  have h2 : Real.sqrt ({u2}) ≤ {t2} := Real.sqrt_le_iff.mpr\n"
                      f"    ⟨by norm_num, by nlinarith [{hint2}]⟩\n"
                      + ("  exact le_min (by linarith) (by linarith)" if variant == "max"
                         else "  exact max_le (by linarith) (by linarith)")),
        "I3_sq_sqrt": ("by\n  intro x hx1 hx2\n"
                       f"  have hu1 : (0:ℝ) ≤ {u1} := by nlinarith [sq_nonneg ({_lin(m1)})]\n"
                       f"  have hu2 : (0:ℝ) ≤ {u2} := by nlinarith [sq_nonneg ({_lin(m2)})]\n"
                       + ("  simp only [le_min_iff]\n  constructor <;> "
                          if variant == "max" else
                          "  simp only [max_le_iff]\n  constructor <;> ")
                       + f"nlinarith [Real.sq_sqrt hu1, Real.sq_sqrt hu2, "
                         f"Real.sqrt_nonneg ({u1}), Real.sqrt_nonneg ({u2}), {hint1}]"),
    }
    return Inst(direction="min_inside", variant=variant, spec=s, prop=prop,
                witness=witness, idioms=idioms,
                holds_at=lambda x: (a1 * (x - m1) ** 2 <= d1) and (a2 * (x - m2) ** 2 <= d2),
                value=value, outer=min(t1, t2),
                coeffs=(a1, -2 * a1 * m1, a1 * m1**2 + e1,
                        a2, -2 * a2 * m2, a2 * m2**2 + e2), exact_kind="iff")


DIRECTIONS: dict[str, Callable[[Spec, str], Inst | None]] = {
    "baseline": d_baseline,
    "floor_sqrt": d_floor_sqrt,
    "floor_sqrt_loose": d_floor_sqrt_loose,
    "ceil_sqrt": d_ceil_sqrt,
    "abs_quad": d_abs_quad,
    "abs_v": d_abs_v,
    "two_var": d_two_var,
    "sqrt_product": d_sqrt_product,
    "floor_product": d_floor_product,
    "reciprocal": d_reciprocal,
    "recip_sqrt": d_recip_sqrt,
    "min_inside": d_min_inside,
}


def build_instances(names: Sequence[str]) -> tuple[list[Inst], list[str]]:
    out, skipped = [], []
    for name in names:
        fn = DIRECTIONS[name]
        for band in BANDS:
            s = Spec(*band)
            for variant in VARIANTS:
                inst = fn(s, variant)
                if inst is None:
                    skipped.append(f"{name}/{variant}/{s.label}")
                else:
                    out.append(inst)
    return out, skipped


# --------------------------------------------------- V0: the assembled goal --


def piece_term(inst: Inst) -> str:
    """The piece as it appears inside the goal's extremum tree.

    Recovered from the rendered leaf rather than carried separately, so a goal
    built here is guaranteed to contain exactly the term the leaf talks about
    (the same reason `stage_retune_candidates._knobs_of` parses the text)."""
    body = inst.prop.split("→ ")[-1]
    if inst.variant == "max":
        return body[len(f"{C} ≤ "):]
    return body[: -len(f" ≤ {C}")]


def goal_props(direction: str, *, k: int = 4, seed: int = 7) -> list[tuple[str, str]]:
    """(variant, goal prop) for a k-band tiling — the V0 side of the check.

    A new piece shape changes the *goal* too, and a goal that falls to the
    battery voids the whole problem rather than one leaf (FAMILIES.md V0)."""
    out = []
    fn = DIRECTIONS[direction]
    if direction == "two_var":
        return out
    for variant in VARIANTS:
        rng = random.Random(seed)
        widths = [rng.choice(ct.WIDTHS) for _ in range(k)]
        lo = -(sum(widths) // 2)
        insts = []
        for w in widths:
            for _ in range(12):
                s = Spec(lo=lo, w=w, off=rng.choice(ct.VERTEX_OFFSETS),
                         a=rng.choice(ct.CURVATURES), slack=rng.choice(ct.SLACKS))
                inst = fn(s, variant)
                if inst is not None:
                    insts.append(inst)
                    break
            lo += w
        if len(insts) != k:
            continue
        terms = [piece_term(i) for i in insts]
        tree = ct._chain(terms, variant)
        body = (f"{C} ≤ {tree}" if variant == "max" else f"{tree} ≤ {C}")
        out.append((variant, _binder(insts[0].spec.lo, insts[-1].spec.hi) + body))
    return out


# ------------------------------------------------------- (a) exactness -------


def check_exactness(inst: Inst, *, window: int = 40, grid: int = 401) -> dict:
    """Compare `holds_at` (integers) against a 60-digit evaluation of the piece,
    and verify the real-valued coverage claim on a dense grid across the band.

    Three verdicts matter:
      * `mismatches` — any disagreement at an integer point: the predicate is not
        exact, and if the disagreement is `holds_at False / truth True` it is
        UNDER-approximating, which is the disqualifying direction (the generator
        would claim a necessity it does not have).
      * `coverage_fail` — the piece does not satisfy the goal somewhere on its own
        band: the generated problem would be FALSE.
      * `spill` — how far past its band the piece's real super-level set reaches;
        this is what the necessity repair has to survive.
    """
    s = inst.spec
    mism_under, mism_over = [], []
    if inst.n_vars == 1:
        for x in range(s.m - window, s.m + window + 1):
            pred = bool(inst.holds_at(x))
            truth = bool(inst.satisfies(mpf(x)))
            if pred != truth:
                (mism_under if truth and not pred else mism_over).append(x)
    else:
        assert inst.ybounds is not None and inst.ycenter is not None
        for x in range(s.m - window // 2, s.m + window // 2 + 1):
            for y in range(inst.ycenter - window // 2, inst.ycenter + window // 2 + 1):
                pred = bool(inst.holds_at(x, y))
                truth = bool(inst.satisfies(mpf(x), mpf(y)))
                if pred != truth:
                    (mism_under if truth and not pred else mism_over).append((x, y))

    # coverage on the reals (the generator's truth claim), dense grid
    tol = mpf(10) ** -30
    cov_fail = []
    if inst.n_vars == 1:
        for i in range(grid):
            x = mpf(s.lo) + (mpf(s.hi - s.lo) * i) / (grid - 1)
            v = inst.value(x)
            ok = (v >= C - tol) if inst.variant == "max" else (v <= C + tol)
            if not ok:
                cov_fail.append(float(x))
    else:
        assert inst.ybounds is not None
        n = int(math.isqrt(grid))
        for i in range(n):
            for j in range(n):
                x = mpf(s.lo) + (mpf(s.hi - s.lo) * i) / (n - 1)
                y = mpf(inst.ybounds[0]) + (mpf(inst.ybounds[1] - inst.ybounds[0]) * j) / (n - 1)
                v = inst.value(x, y)
                ok = (v >= C - tol) if inst.variant == "max" else (v <= C + tol)
                if not ok:
                    cov_fail.append((float(x), float(y)))

    # spill: the real super-level half-width, past the band, by bisection
    spill = None
    if inst.n_vars == 1:
        hi = mpf(s.m) + 1
        while inst.satisfies(hi) and hi - s.m < 10_000:
            hi = (hi - s.m) * 2 + s.m
        lo = mpf(s.m)
        for _ in range(200):
            mid = (lo + hi) / 2
            if inst.satisfies(mid):
                lo = mid
            else:
                hi = mid
        spill = float(lo - s.hi)          # >0 means it reaches past its own band

    return {
        "label": inst.label,
        "exact_kind_claimed": inst.exact_kind,
        "n_mismatch_under": len(mism_under),
        "n_mismatch_over": len(mism_over),
        "mismatch_under_sample": mism_under[:5],
        "mismatch_over_sample": mism_over[:5],
        "coverage_failures": len(cov_fail),
        "coverage_fail_sample": cov_fail[:3],
        "real_spill_past_band": spill,
        "verdict": ("UNDER-APPROXIMATING (disqualifying)" if mism_under
                    else "over-approximating (safe)" if mism_over
                    else "EXACT (iff)"),
    }


# --------------------------------------------- structural: necessity + k ------


def _tile(direction: str, k: int, rng: random.Random) -> list[Inst]:
    """k contiguous bands tiling a domain centred on 0 — the family's own layout
    (`case_tree._sample_pieces`), rebuilt with this direction's piece."""
    fn = DIRECTIONS[direction]
    widths = [rng.choice(ct.WIDTHS) for _ in range(k)]
    lo = -(sum(widths) // 2)
    out = []
    for w in widths:
        for _ in range(12):                        # resample knobs if infeasible
            s = Spec(lo=lo, w=w, off=rng.choice(ct.VERTEX_OFFSETS), a=rng.choice(ct.CURVATURES),
                     slack=rng.choice(ct.SLACKS))
            inst = fn(s, "max")
            if inst is not None:
                out.append(inst)
                break
        lo += w
    return out


def necessity_scan(direction: str, *, ks=(2, 4, 8, 16), n=40, seed=4242) -> dict:
    """Does every piece stay NECESSARY under this direction's `holds_at`?

    Runs `case_tree._redundant`'s exact test — "is every integer point of band i
    covered by some other piece" — on real tilings. A redundant piece means a
    k-leaf plan that is secretly (k−1)-leaf, so a direction whose redundancy rate
    is non-zero needs the repair, and a repair that fires at different rates per
    k is itself a flatness leak (`case_tree._repair_necessity` docstring)."""
    if direction == "two_var":
        return necessity_scan_two_var()
    rng = random.Random(seed)
    per_k = {}
    for k in ks:
        red = tot = 0
        min_private = 10**9
        for _ in range(n):
            pieces = _tile(direction, k, rng)
            for i, p in enumerate(pieces):
                tot += 1
                pts = range(p.spec.lo, p.spec.hi + 1)
                private = [x for x in pts
                           if not any(q.holds_at(x) for j, q in enumerate(pieces) if j != i)]
                if not private:
                    red += 1
                min_private = min(min_private, len(private))
        per_k[k] = {"pieces": tot, "redundant": red,
                    "redundant_frac": round(red / tot, 4),
                    "min_private_points": min_private}
    return per_k


def necessity_scan_two_var(*, grids=((2, 2), (2, 4), (4, 4), (4, 8)), n=12,
                           seed=4242) -> dict:
    """Necessity for the RECTANGLE tiling — the check `two_var` actually needs.

    The 1-D argument does not transfer. A piece must cover its cell's *corner*,
    so its super-level set is an ellipse `a(x−mx)² + b(y−my)² ≤ dq` with
    `dq ≥ a·farx² + b·fary²`; along the cell's centre line that ellipse reaches
    `√(farx² + (b/a)·fary²)` in x, which can exceed the *neighbouring cell's
    centre* whenever the two axes' "energies" are lopsided. The scan measures the
    redundancy rate and splits it by the energy ratio, so the knob constraint the
    direction would need is measured rather than argued.
    """
    rng = random.Random(seed)
    out = {}
    for kx, ky in grids:
        red = tot = 0
        min_private = 10**9
        red_bal = tot_bal = red_lop = tot_lop = 0
        max_coeff = 0
        for _ in range(n):
            xw = [rng.choice(ct.WIDTHS) for _ in range(kx)]
            yw = [rng.choice(ct.WIDTHS) for _ in range(ky)]
            xs, cur = [], -(sum(xw) // 2)
            for w in xw:
                xs.append(Spec(lo=cur, w=w, off=rng.choice(ct.VERTEX_OFFSETS),
                               a=rng.choice(ct.CURVATURES), slack=rng.choice(ct.SLACKS)))
                cur += w
            ys, cur = [], -(sum(yw) // 2)
            for w in yw:
                ys.append(Spec(lo=cur, w=w, off=rng.choice(ct.VERTEX_OFFSETS),
                               a=rng.choice(ct.CURVATURES), slack=rng.choice(ct.SLACKS)))
                cur += w
            cells = [(sx, sy, d_two_var(sx, "max", sy)) for sx in xs for sy in ys]
            cells = [(sx, sy, c) for sx, sy, c in cells if c is not None]
            for i, (sx, sy, c) in enumerate(cells):
                tot += 1
                max_coeff = max(max_coeff, max(abs(v) for v in c.coeffs))
                ratio = (sy.a * sy.far**2) / (sx.a * sx.far**2)
                balanced = (1 / 3) < ratio < 3
                private = 0
                for x in range(sx.lo, sx.hi + 1):
                    for y in range(sy.lo, sy.hi + 1):
                        if not any(q.holds_at(x, y) for j, (_, _, q) in enumerate(cells)
                                   if j != i):
                            private += 1
                min_private = min(min_private, private)
                if balanced:
                    tot_bal += 1
                    red_bal += private == 0
                else:
                    tot_lop += 1
                    red_lop += private == 0
                red += private == 0
        out[f"{kx}x{ky}"] = {
            "k": kx * ky, "cells": tot, "redundant": red,
            "redundant_frac": round(red / tot, 4), "min_private_points": min_private,
            "redundant_frac_energy_balanced": round(red_bal / tot_bal, 4) if tot_bal else None,
            "redundant_frac_energy_lopsided": round(red_lop / tot_lop, 4) if tot_lop else None,
            "n_balanced": tot_bal, "n_lopsided": tot_lop,
            "max_abs_coeff": max_coeff,
        }
    return out


def flatness_scan(direction: str, *, ks=(2, 4, 8, 16, 32), n=8, seed=99) -> dict:
    """Leaf-shape distribution per k — FAMILIES.md's structural flatness check.

    The outer constant must NOT grow with k (only the radicand's constant may,
    because the band's absolute position does)."""
    if direction == "two_var":
        return {"skipped": "2-D tiling; see the note's assembly section"}
    rng = random.Random(seed)
    out = {}
    for k in ks:
        lens, outers, coefs = [], [], []
        for _ in range(n):
            for inst in _tile(direction, k, rng):
                lens.append(len(inst.prop))
                outers.append(inst.outer)
                coefs.append(max(abs(c) for c in inst.coeffs))
        out[k] = {"leaves": len(lens), "leaf_len_mean": round(sum(lens) / len(lens), 1),
                  "leaf_len_max": max(lens), "outer_const_max": max(outers),
                  "outer_const_mean": round(sum(outers) / len(outers), 1),
                  "max_abs_coeff": max(coefs)}
    return out


# ------------------------------------------------------------ (d) calibration -


_BANK_MAX = re.compile(
    r"^∀ x : ℝ, (-?\d+) ≤ x → x ≤ (-?\d+) → 3 ≤ (\d+) - Real\.sqrt \((.+)\)$")
_BANK_MIN = re.compile(
    r"^∀ x : ℝ, (-?\d+) ≤ x → x ≤ (-?\d+) → Real\.sqrt \((.+)\) - (\d+) ≤ 3$")
_QUAD = re.compile(r"^(?:(\d+) \* )?x \^ 2 ([+-]) (?:(\d+) \* )?x ([+-]) (\d+)$")
_QUAD_NOX = re.compile(r"^(?:(\d+) \* )?x \^ 2 ([+-]) (\d+)$")


def parse_bank_leaf(prop: str) -> dict | None:
    """Recover (lo, hi, radicand, cap, vertex) from a measured case_tree leaf.

    The idiom probe needs the same three things a prover reads off the goal: the
    band, the radicand, and the cap the atom must respect. The vertex is
    recovered by completing the square (`m = −c₁ / 2c₂`), which is exactly the
    step the schema's expanded rendering is designed to force.
    """
    m = _BANK_MAX.match(prop)
    variant = "max"
    if not m:
        m = _BANK_MIN.match(prop)
        variant = "min"
        if not m:
            return None
        lo, hi, rad, n = m.group(1), m.group(2), m.group(3), m.group(4)
        cap = int(n) + C
    else:
        lo, hi, rad, N = m.group(1), m.group(2), m.group(4), m.group(3)
        cap = int(N) - C
    q = _QUAD.match(rad)
    if q:
        c2 = int(q.group(1) or 1)
        c1 = int(q.group(3) or 1) * (1 if q.group(2) == "+" else -1)
    else:
        q = _QUAD_NOX.match(rad)
        if not q:
            return None
        c2, c1 = int(q.group(1) or 1), 0
    if c1 % (2 * c2) != 0:
        return None
    return {"lo": int(lo), "hi": int(hi), "radicand": rad, "cap": cap,
            "vertex": -c1 // (2 * c2), "variant": variant}


def calibration_proofs(parsed: dict) -> dict[str, str]:
    """The idiom, aimed at a measured leaf — the calibration of probe (d)."""
    s = Spec(lo=parsed["lo"], w=parsed["hi"] - parsed["lo"], off=0, a=1, slack=0)
    s = Spec(lo=parsed["lo"], w=parsed["hi"] - parsed["lo"],
             off=parsed["vertex"] - (parsed["lo"] + (parsed["hi"] - parsed["lo"]) // 2),
             a=1, slack=0)
    return {"I0_verbatim": idiom_verbatim(s, parsed["radicand"], parsed["cap"]),
            "I1_sq_sqrt": idiom_sq_sqrt(s, parsed["radicand"]),
            "I2_sqrt_le_iff": ("by\n  intro x hx1 hx2\n"
                               f"  have h : Real.sqrt ({parsed['radicand']}) ≤ {parsed['cap']} := "
                               "Real.sqrt_le_iff.mpr\n"
                               f"    ⟨by norm_num, by nlinarith [{_hints(s)}]⟩\n"
                               "  linarith")}


def load_bank_leaves(limit: int | None = None) -> list[dict]:
    rows = []
    if not BANK.exists():
        return rows
    for line in BANK.read_text().splitlines():
        r = json.loads(line)
        if "case_tree" not in r.get("source_id", ""):
            continue
        p = parse_bank_leaf(r["prop"])
        if p is None:
            rows.append({"prop": r["prop"], "pass_rate": r.get("pass_rate"), "parsed": None})
            continue
        rows.append({"prop": r["prop"], "pass_rate": r.get("pass_rate"), "parsed": p})
    return rows[:limit] if limit else rows


# ------------------------------------------------------------------ Lean ----


@dataclass
class LeanJob:
    kind: str    # battery | witness | idiom | control | calib | goal | goal_elab
    label: str
    key: str
    code: str
    want_sorries: int = 0     # 1 for a statement-elaboration check (V1-shaped)
    result: bool = False
    err: str = ""


def build_jobs(insts: Sequence[Inst], bank: Sequence[dict], *,
               skip_battery: bool, skip_calib: bool,
               goals: Sequence[tuple[str, str, str]] = ()) -> list[LeanJob]:
    from rlmath.core import leancode
    from rlmath.families.validate import battery_proofs

    jobs: list[LeanJob] = []
    for p in battery_proofs():
        jobs.append(LeanJob("control", "CONTROL", p,
                            leancode.proof_check(CONTROL_PROP, p)))
    for direction, variant, prop in goals:
        for p in battery_proofs():
            jobs.append(LeanJob("goal", f"{direction}/{variant}", p,
                                leancode.proof_check(prop, p)))
        jobs.append(LeanJob("goal_elab", f"{direction}/{variant}", "statement",
                            leancode.statement_check(prop), want_sorries=1))
    for inst in insts:
        jobs.append(LeanJob("witness", inst.label, "witness",
                            leancode.proof_check(inst.prop, inst.witness)))
        for name, proof in inst.idioms.items():
            jobs.append(LeanJob("idiom", inst.label, name,
                                leancode.proof_check(inst.prop, proof)))
        for name, proof in inst.alt_witnesses.items():
            jobs.append(LeanJob("alt_witness", inst.label, name,
                                leancode.proof_check(inst.prop, proof)))
        if not skip_battery:
            for p in battery_proofs():
                jobs.append(LeanJob("battery", inst.label, p,
                                    leancode.proof_check(inst.prop, p)))
    if not skip_calib:
        for i, row in enumerate(bank):
            if row["parsed"] is None:
                continue
            for name, proof in calibration_proofs(row["parsed"]).items():
                jobs.append(LeanJob("calib", f"bank{i}", name,
                                    leancode.proof_check(row["prop"], proof)))
    return jobs


def run_jobs(jobs: list[LeanJob], workers: int) -> float:
    from rlmath.lean.repl_pool import ReplPool

    pool = ReplPool(n_workers=workers)
    t0 = time.time()
    try:
        pool.warm()
        results = pool.check_many([j.code for j in jobs], timeout_s=BATTERY_TIMEOUT_S)
        for j, r in zip(jobs, results):
            j.result = bool(r.ok and r.sorries == j.want_sorries)
            if not j.result:
                j.err = "; ".join(m.text for m in r.errors)[:200].replace("\n", " ")
    finally:
        pool.close()
    return time.time() - t0


# --------------------------------------------------------------------- main --


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--directions", default=",".join(DIRECTIONS))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--no-lean", action="store_true", dest="no_lean")
    ap.add_argument("--skip-battery", action="store_true", dest="skip_battery")
    ap.add_argument("--skip-calib", action="store_true", dest="skip_calib")
    ap.add_argument("--calib-limit", type=int, default=None, dest="calib_limit")
    ap.add_argument("--goals", action="store_true",
                    help="also run V0 (elaborates + battery) on an assembled k=4 goal")
    ap.add_argument("--goals-only", action="store_true", dest="goals_only",
                    help="V0 goal check only (implies --goals)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    args.goals = args.goals or args.goals_only
    names = [n.strip() for n in args.directions.split(",") if n.strip()]
    bad = [n for n in names if n not in DIRECTIONS]
    if bad:
        print(f"unknown direction(s): {bad}; known: {list(DIRECTIONS)}", file=sys.stderr)
        return 2

    insts, skipped = build_instances(names)
    print(f"## {len(insts)} instances over {len(names)} directions "
          f"({len(skipped)} knob combos infeasible)", file=sys.stderr)

    report: dict = {"directions": {}, "skipped_specs": skipped,
                    "control_prop": CONTROL_PROP}

    # (a) exactness + structure — free
    for name in names:
        mine = [i for i in insts if i.direction == name]
        ex = [check_exactness(i) for i in mine]
        report["directions"][name] = {
            "n_instances": len(mine),
            "exactness": ex,
            "exactness_summary": {
                "under": sum(e["n_mismatch_under"] for e in ex),
                "over": sum(e["n_mismatch_over"] for e in ex),
                "coverage_failures": sum(e["coverage_failures"] for e in ex),
                # None for multivariate directions, where "spill past the band"
                # is not a single number (see the note's assembly section)
                "max_spill": (None if any(e["real_spill_past_band"] is None for e in ex)
                              else max(e["real_spill_past_band"] for e in ex)),
            },
            "necessity": necessity_scan(name),
            "flatness": flatness_scan(name),
            "example_prop": mine[0].prop if mine else None,
            "example_witness": mine[0].witness if mine else None,
        }
        s = report["directions"][name]["exactness_summary"]
        spill = "n/a" if s["max_spill"] is None else f"{s['max_spill']:.3f}"
        print(f"  {name:17s} exact: under={s['under']} over={s['over']} "
              f"covfail={s['coverage_failures']} maxspill={spill}", file=sys.stderr)

    if not args.no_lean:
        bank = load_bank_leaves(args.calib_limit)
        goals: list[tuple[str, str, str]] = []
        if args.goals:
            for name in names:
                for variant, prop in goal_props(name):
                    goals.append((name, variant, prop))
            report["goal_props"] = {f"{d}/{v}": p for d, v, p in goals}
        if args.goals_only:
            insts = []
            args.skip_calib = True
        jobs = build_jobs(insts, bank, skip_battery=args.skip_battery,
                          skip_calib=args.skip_calib, goals=goals)
        print(f"## {len(jobs)} Lean checks …", file=sys.stderr)
        elapsed = run_jobs(jobs, args.workers)
        print(f"   {elapsed:.1f}s wall", file=sys.stderr)

        # planted control MUST die
        ctrl = [j for j in jobs if j.kind == "control"]
        killers = [j.key for j in ctrl if j.result]
        report["control"] = {"killers": killers, "expected": CONTROL_EXPECTED_KILLER}
        if not killers:
            raise ControlFailed(
                "the planted positive control survived the full battery — the gate is not "
                "measuring, and every 'survives' verdict in this report is void")
        print(f"   control DIED to: {killers}", file=sys.stderr)

        # V0: the assembled k=4 goal must elaborate and must resist the battery
        if goals:
            gv: dict[str, dict] = {}
            for j in jobs:
                if j.kind == "goal" and j.result:
                    gv.setdefault(j.label, {"killers": [], "elaborates": None})[
                        "killers"].append(j.key)
                elif j.kind == "goal":
                    gv.setdefault(j.label, {"killers": [], "elaborates": None})
                elif j.kind == "goal_elab":
                    gv.setdefault(j.label, {"killers": [], "elaborates": None})[
                        "elaborates"] = j.result
            report["goal_v0"] = gv
            for lbl, v in sorted(gv.items()):
                print(f"  V0 {lbl:24s} elaborates={v['elaborates']} "
                      f"battery={'**DEAD** ' + str(v['killers']) if v['killers'] else 'survives'}",
                      file=sys.stderr)

        by_label: dict[str, dict] = {}
        for j in jobs:
            if j.kind in ("control", "calib", "goal", "goal_elab"):
                continue
            e = by_label.setdefault(j.label, {"battery_kills": [], "witness": None,
                                              "idioms": {}, "alt_witnesses": {},
                                              "witness_err": "", "idiom_errs": {}})
            if j.kind == "witness":
                e["witness"] = j.result
                e["witness_err"] = j.err
            elif j.kind == "alt_witness":
                e["alt_witnesses"][j.key] = j.result
            elif j.kind == "idiom":
                e["idioms"][j.key] = j.result
                if not j.result:
                    e["idiom_errs"][j.key] = j.err
            elif j.kind == "battery" and j.result:
                e["battery_kills"].append(j.key)

        for name in names:
            mine = [i.label for i in insts if i.direction == name]
            d = report["directions"][name]
            d["lean"] = {lbl: by_label[lbl] for lbl in mine if lbl in by_label}
            d["witness_ok"] = sum(1 for lbl in mine if by_label.get(lbl, {}).get("witness"))
            d["battery_survivors"] = sum(
                1 for lbl in mine if not by_label.get(lbl, {}).get("battery_kills"))
            d["battery_kill_tactics"] = sorted({t for lbl in mine
                                                for t in by_label.get(lbl, {}).get(
                                                    "battery_kills", [])})
            idiom_names = sorted({k for lbl in mine
                                  for k in by_label.get(lbl, {}).get("idioms", {})})
            d["idiom_closed"] = {
                k: sum(1 for lbl in mine if by_label.get(lbl, {}).get("idioms", {}).get(k))
                for k in idiom_names}
            d["idiom_any_closed"] = sum(
                1 for lbl in mine if any(by_label.get(lbl, {}).get("idioms", {}).values()))
            alt = sorted({k for lbl in mine
                          for k in by_label.get(lbl, {}).get("alt_witnesses", {})})
            if alt:
                d["alt_witness_closed"] = {
                    k: sum(1 for lbl in mine
                           if by_label.get(lbl, {}).get("alt_witnesses", {}).get(k))
                    for k in alt}
            print(f"  {name:17s} witness {d['witness_ok']}/{len(mine)} | "
                  f"battery survives {d['battery_survivors']}/{len(mine)} "
                  f"{d['battery_kill_tactics'] or ''} | idiom any "
                  f"{d['idiom_any_closed']}/{len(mine)} {d['idiom_closed']}",
                  file=sys.stderr)

        if not args.skip_calib:
            calib = [j for j in jobs if j.kind == "calib"]
            by_leaf: dict[str, dict[str, bool]] = {}
            for j in calib:
                by_leaf.setdefault(j.label, {})[j.key] = j.result
            n_parsed = len(by_leaf)
            closed_any = sum(1 for v in by_leaf.values() if any(v.values()))
            per_probe = {k: sum(1 for v in by_leaf.values() if v.get(k))
                         for k in ("I0_verbatim", "I1_sq_sqrt", "I2_sqrt_le_iff")}
            rates = [r["pass_rate"] for r in bank if r["parsed"] is not None
                     and r["pass_rate"] is not None]
            report["calibration"] = {
                "bank_leaves_total": len(bank), "parsed": n_parsed,
                "unparsed": len(bank) - n_parsed,
                "idiom_closed_any": closed_any,
                "idiom_closed_any_frac": round(closed_any / n_parsed, 3) if n_parsed else None,
                "per_probe_closed": per_probe,
                "measured_pass8_mean": round(sum(rates) / len(rates), 3) if rates else None,
                "per_leaf": by_leaf,
            }
            print(f"   CALIBRATION: idiom closes {closed_any}/{n_parsed} measured leaves "
                  f"(measured pass@8 mean "
                  f"{report['calibration']['measured_pass8_mean']}); per-probe {per_probe}",
                  file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    print(f"\nwrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
