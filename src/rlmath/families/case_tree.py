"""Family B — case trees (`case_tree`), FAMILIES.md.

A single quantified statement whose natural proof splits into k cases, each case
a distinct leaf lemma. The *split* (where the cases are) and the *per-case
claim* are what a policy has to invent; the assembly performs the split and
dispatches.

    ∀ x : ℝ, L ≤ x → x ≤ R → C ≤ max (max (q₁ x) (q₂ x)) (max (q₃ x) (q₄ x))

Every `qᵢ` dips below `C` somewhere, so no single piece proves the goal; the
pieces' super-level sets cover `[L, R]`, so a k-way interval split does. The
generator asserts at generation time that each piece *covers its own band* and
is *necessary* (there is an integer point in band i that no other piece
covers) — otherwise the "k-case" split would secretly be a j-case split.

The shipped schema (rung `v2`, the default) is a **piecewise extremum of
`Real.sqrt`-capped quadratics**:

    qᵢ x  =  Aᵢ − Real.sqrt (aᵢ x² + bᵢ x + cᵢ)          (max variant, Aᵢ = C + tᵢ)
    qᵢ x  =  Real.sqrt (aᵢ x² + bᵢ x + cᵢ) − nᵢ          (min variant, nᵢ = tᵢ − C)

with the radicand a positive-definite `aᵢ(x − mᵢ)² + eᵢ`, `eᵢ ≥ 1`, written
*expanded* so neither the vertex nor the band is readable off the goal.

The hardening ladder (2026-08-13) — why the piece function became a knob
=======================================================================
`v2` measured **pass@8 0.923** over 68 leaves × 8 DeepSeek-Prover-V2-7B attempts
(`data/bank/family_leaf_calibration.jsonl`), i.e. *above* the corridor ceiling,
with band-fit 18/68 against the required ≥ 0.60 and 50/68 leaves at a perfect
8/8. bridge_chain's fix — retune the draw distribution — does not transfer, and
that is measured, not argued (`research/case-tree-forensics.md`):

* every knob marginal is flat (variant 0.872/0.988, curvature 0.933/0.910/0.925,
  width 0.905/0.939, offset 0.890/0.940/0.944, slack 0.943/0.899, cap 0.875–1.000);
  Mann-Whitney U on in-band vs saturated leaves gives p > 0.4 on *every* knob;
* 68/68 successful proofs run **one memorised idiom** — `Real.sqrt_le_iff` +
  `nlinarith [sq_nonneg …]`, which is this module's own `leaf_proof` template.
  The family was measuring template recall, and template recall has no knob.

So difficulty here is a property of the *piece function*, and `generate` takes a
`preset=` naming one of `RUNGS` (the kwarg is called `preset` because
`gen_families.py --preset` already threads that name through to the registry —
they are schemas, not distributions; see `research/case-tree-hardening.md` §10.5).
Each rung differs from the `v2` control by exactly **one mechanism** (a one-step
star, not a chain: the mechanisms are different kinds of invention and are not
orderable a priori), and `r4_floorprod` is the join of two of them.

| rung | piece | the ONE mechanism vs `v2` |
|---|---|---|
| `v2` | `(C+t) − √u` | — (shipped control; the memorised idiom closes it) |
| `r1_recip` | `c / u` | **retarget the closing lemma**: `Real.sqrt_le_iff` no longer applies, `le_div_iff₀` does, plus a positivity side goal `positivity` cannot discharge |
| `r2_prod` | `(C+T) − √u·√w` | **a second atom, multiplicatively**: the visible budget `T` must be split into a divisor pair and recombined (`mul_le_mul`) |
| `r2_sum` | `(C+t) − √u₁ − √u₂` | **the combinator**: same two atoms, added; the split is additive and *anchored* near `t/2`, and `linarith` finishes |
| `r3_floor` | `(C+T) − ⌊√u⌋` | **integrality + strictness**: the cap is tight, so the memorised sub-goal `√u ≤ T` is not merely unfound but **false** on part of the band; a strict bound (`Real.sqrt_lt'`) plus a floor/cast step is forced |
| `r4_floorprod` | `(C+T) − ⌊√u·√w⌋` | **composition** of the two above: `Real.sqrt_mul` must be applied *before* the floor step |

Local gate (S1/S2 surveys, `research/ct-hardening-survey-{a,b}.md`, Mathlib @
lean v4.34.0-rc1): every rung survives the full V0/V5 battery with a **live
planted control** (the v1-shape leaf `3 ≤ -2x² - 12x + 17` died to
`intros; nlinarith` in the same pool), every witness kernel-checks, and every
rung's integer predicate audited exactly against 60-digit reference arithmetic.
`research/case-tree-hardening.md` §6 registers the pass@8 projections; nothing
here measures pass@8.

The soundness asymmetry — get this right or the family becomes false
====================================================================
* **COVERAGE** ("the goal is true on the whole *real* band") is proven by the
  generator's witness on ℝ. A **sufficient** condition is fine: `r2_prod`'s
  witness bounds `√u ≤ t₁` and `√w ≤ t₂` and multiplies, which is weaker than
  the exact product condition — and that is allowed, because it *implies* the
  goal.
* **NECESSITY** (`_redundant`) is decided by exact integer arithmetic on integer
  points, and `Piece.holds_at` must **not under-approximate** the true
  super-level set. A predicate that believes a piece covers *less* than it truly
  does makes the generator claim a necessity it does not have and ship a k-leaf
  plan that is secretly (k−1)-leaf. (This is why `Real.log` pieces were rejected:
  `log u ≤ t` has no exact integer characterisation.)

Every rung therefore supplies an **exact (iff)** integer predicate, and the
predicate is attached to the *piece*: `Piece.holds_at` has no implementation of
its own, it dispatches to `self.schema`, and `Piece` cannot be constructed
without a schema. `covers_band` is likewise defined as `holds_at` at the two band
endpoints — sound because every rung's piece value is monotone in `|x − m|`
(all atoms share the vertex), so the real-line worst case sits at an endpoint,
which is an integer. There is no code path that can evaluate one rung's piece
with another rung's predicate. `predicate_mismatches()` re-checks the iff
numerically against 60-digit `Decimal` arithmetic, in both directions.

Per rung: the exact predicate, and where the pad comes from
-----------------------------------------------------------
Shared geometry: band `[lo, hi]`, `m = lo + width/2 + offset`,
`far = max(|lo−m|, |hi−m|) = width/2 + |offset|`, `base = a·far²`,
`d = base + slack`.

* `v2` — `u = a(x−m)² + e`, `t = _cap(d)`, `e = t² − d ≥ 1`.
  `√u ≤ t ⟺ u ≤ t² ⟺ a(x−m)² ≤ d`.
* `r1_recip` — `u = a(x−m)² + 1`, numerator `c = C·(d+1)`.
  `C ≤ c/u ⟺ C·u ≤ c`, **unconditionally**, because `u ≥ 1 > 0`. That positivity
  is load-bearing: in Lean `x/0 = 0`, so a vanishing denominator would make the
  piece evaluate to `0 < C` while the integer predicate read `0 ≤ c` = true —
  coverage-fatal. `e ≥ 1` plus a negative discriminant forecloses it.
* `r2_prod` — two atoms at the shared vertex, `T = t₁t₂`.
  `√u·√w ≤ T ⟺ √(uw) ≤ T ⟺ u·w ≤ T²` (both sides ≥ 0).
* `r2_sum` — two atoms at the shared vertex, `t = t₁ + t₂`, `s := t² − U₁ − U₂`.
  `√U₁ + √U₂ ≤ t ⟺ s ≥ 0 ∧ 4·U₁·U₂ ≤ s²` (square twice; both steps are between
  non-negative quantities).
* `r3_floor` — `T = max(_cap(base) − 1, C+1) + slack` (raised further if that
  would leave `e < 1`), `e = (T+1)² − 1 − base`, so `u_max = (T+1)² − 1` sits at
  the top of the tightness interval.
  `⌊√u⌋ ≤ T ⟺ √u < T+1 ⟺ u < (T+1)²`, i.e. `a(x−m)² ≤ base` at integer x.
  **Write it as the integer comparison, never as `floor(sqrt(u)) ≤ T` in
  floating point**: at k=32 the radicand's constant is ~4×10⁴ and a float `√` of
  a perfect square that rounds down would report coverage where there is none.
  Note `slack` shifts `T` (hence the pad) rather than widening `d` here — it is
  still a 2-valued k-independent knob, and it deliberately leaves the geometry
  `a(x−m)² ≤ base` untouched, which is what keeps the spill at v2's value.
* `r4_floorprod` — pads `e₁ = 1 + slack`, `e₂ = 1` bumped until
  `P = u_max·w_max` is **not** a perfect square, `T = ⌊√P⌋`, so `T² < P < (T+1)²`.
  `⌊√u·√w⌋ ≤ T ⟺ u·w < (T+1)²`. The integer form is mandatory, not a
  preference — but **not for the reason an earlier revision of this docstring
  gave**. It claimed `u·w` reaches ~10¹⁸ at k=32 and overflows double
  precision; measured, the largest `u·w` at any integer point `_redundant` can
  ask about is **25,090** within a band and **4.0×10¹²** across the whole
  domain at k=128 — the latter still ~2,200× *inside* float64's exact-integer
  range (2⁵³ ≈ 9.0×10¹⁵). Magnitude is not the problem.

  The real reason is **ties**. Measured across all six rungs, the minimum of
  `|piece value − C_LEVEL|` over the integer points is **exactly 0**: every
  rung has knife-edge points where the piece meets the threshold with no
  margin at all. There, `√` in binary floating point can land on either side
  of the comparison, and `holds_at` would report a coverage or necessity fact
  that the Lean statement contradicts. Exact integer arithmetic is what makes
  the predicate agree with the rendered proposition at those points, and it is
  why every rung's `holds_at` is written over ℤ rather than over floats.
  (Corrected 2026-08-13 from the soundness review's independent re-derivation:
  290,700 integer points to k=128, 0 mismatches in either direction.)

Why v1 died (the reason the `√` wrapper exists at all)
------------------------------------------------------
v1's pieces were bare expanded quadratics (`C ≤ −a x² + b x + c` on a band).
Under the strengthened V0/V5 battery (10 tactics × {bare, intros-first}) **70 of
70 v1 leaves fell to `intros; nlinarith`** — structurally, because `nlinarith`'s
preprocessing multiplies pairs of hypotheses and the pair
`(x − lᵢ ≥ 0, rᵢ − x ≥ 0)` *is* the product certificate v1's witness passed in by
hand. Every rung above keeps the claim behind an opaque atom (`Real.sqrt`, `/`,
`⌊·⌋`) that linear-arithmetic preprocessing cannot connect to the band product.
`nlinarith`-with-hints inside a *witness* is fine; a leaf that bare
`intros; nlinarith` closes is dead.

Directions measured and rejected: ℕ interval and ℕ/ℤ residue bands die to
`decide`/`omega`; affine ℝ bands die to `intros; linarith`; `Real.log` caps break
the necessity argument (above); `abs`/`ceil` pieces are *easier* (2–3 of 4 probed
adaptations close them); `two_var` pieces are closed 12/12 by the verbatim idiom
**and** their necessity collapses with k (16.7% redundant at k=16/32); quartic
radicands are clean on every axis but grow max|coef| 45,000× across k=2→32,
which is bridge_chain's flatness failure with a different variable name.

Visibility (V6)
---------------
The pieces are necessarily visible — a piecewise function has to be *stated*.
What is hidden is everything a policy must produce: the k band endpoints and the
per-band claim. The radicand is in *expanded* form, so neither the vertex nor
the crossing points can be read off the goal without completing the square; the
bands then have to be chosen to tile the domain while each stays inside its own
piece's super-level set. No leaf prop is a substring of the goal — each carries
band hypotheses that appear nowhere in it — so this family sets
`meta["visible_lemmas"] = []` and passes V6 with no exemption at all.

Flatness in k
-------------
Every leaf is drawn from one rung's fixed knob support
(WIDTHS × CURVATURES × VERTEX_OFFSETS × SLACKS, plus the rung's own extra knobs),
independent of k; k changes only how many bands tile the domain. The single
k-dependence is the band's *absolute position*: the domain is `[-T/2, T/2]` with
`T = Σ widths ≈ 7k`, so the constant coefficient of a radicand grows like `a·m²`.
The outer constant (`Aᵢ`/`nᵢ`/`c`) is bounded by the knob support and does **not**
grow with k. `leaf_stats()` reports leaf-prop length, coefficient magnitude,
distinct-knob and distinct-leaf counts per k so this is measured rather than
assumed, and `necessity_sweep()` re-establishes — exhaustively over the rung's
whole knob support, not by inheritance — that `_repair_necessity` is a no-op, so
the leaf distribution cannot drift with k through the repair.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from decimal import Decimal, localcontext
from functools import lru_cache

from rlmath.core.types import DecompositionPlan, GoalSpec, LemmaSpec

from . import register
from .types import GeneratedProblem, LeafWitness

FAMILY = "case_tree"
DEFAULT_PRESET = "v2"

# --- leaf schema knobs. Fixed support, identical at every k (flatness). -------
C_LEVEL = 3               # the bare side of the goal; nonzero so the goal never
                          # takes the `0 ≤ e` shape `positivity` attacks
WIDTHS = (6, 8)           # band width; even so band midpoints stay integral, and
                          # ≥ 6 so no piece can swallow a neighbour (see
                          # _repair_necessity: max spill past a band is
                          # 2·|offset| ≤ 2 for every rung, independent of width)
CURVATURES = (1, 2, 3)    # leading coefficient of the radicand
VERTEX_OFFSETS = (-1, 0, 1)   # vertex displacement from the band midpoint
SLACKS = (0, 1)           # extra margin above the exact covering requirement
VARIANTS = ("max", "min")

_GLUE = {
    # variant -> (left injection, right injection) for the nested extremum
    "max": ("le_max_of_le_left", "le_max_of_le_right"),
    "min": ("min_le_of_left_le", "min_le_of_right_le"),
}

_NAME_OK = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")
_DECIMAL_PREC = 60        # digits used by predicate_mismatches' reference arithmetic


def _cap(d: int) -> int:
    """Smallest integer `t` with `t² > d`.

    The strict inequality (rather than `t² ≥ d`) forces the radicand's additive
    slack `e = t² − d` to be **≥ 1**, which keeps the radicand off two shapes
    that leak the vertex — the thing the policy is supposed to invent. With
    `e = 0` the radicand is a perfect square `a(x−m)²`, one normalisation away
    from `√((x−m)²) = |x−m|` (`Real.sqrt_sq_eq_abs`); with `m = 0` on top it
    degenerates to a bare `a·x²`. The expanded rendering hides both from `simp`,
    but not from a prover that normalises — which is the reader we care about.
    Measured: both shapes survive the battery, so this is an invention
    constraint, not a validity one (research/family-v2-hardening.md §2).
    """
    t = 1
    while t * t <= d:
        t += 1
    return t


def _is_square(n: int) -> bool:
    return n >= 0 and math.isqrt(n) ** 2 == n


# ---------------------------------------------------------------- rendering --


def _render_poly(c2: int, c1: int, c0: int) -> str:
    """Expanded quadratic as single-line Lean over a real `x`."""
    out = ""
    for coeff, body in ((c2, "x ^ 2"), (c1, "x"), (c0, "")):
        if coeff == 0:
            continue
        mag = abs(coeff)
        if body:
            term = body if mag == 1 else f"{mag} * {body}"
        else:
            term = str(mag)
        if not out:
            out = f"-{term}" if coeff < 0 else term
        else:
            out += f" - {term}" if coeff < 0 else f" + {term}"
    return out or "0"


def _shift(m: int) -> str:
    """`x - m` in the form `sq_nonneg` wants it (the vertex, un-expanded)."""
    if m == 0:
        return "x"
    return f"x - {m}" if m > 0 else f"x + {-m}"


def _num(n: int) -> str:
    """Numeral in *application* position. `le_or_gt x -5` parses as a
    subtraction; `le_or_gt x (-5)` is the split point we mean. Comparison
    positions (`-5 ≤ x`) need no parentheses, so only the assembly uses this."""
    return f"({n})" if n < 0 else str(n)


# ------------------------------------------------------------------- atoms --


@dataclass(frozen=True)
class Atom:
    """One positive-definite radicand `a(x − m)² + e`, `e ≥ 1`.

    Integer-valued at integer x, which is what keeps every rung's necessity
    predicate inside exact integer arithmetic.
    """
    a: int
    m: int
    e: int

    def value(self, x: int) -> int:
        return self.a * (x - self.m) ** 2 + self.e

    def coeffs(self) -> tuple[int, int, int]:
        """(x², x, 1) coefficients, expanded — the form the leaf is rendered in,
        so neither the vertex nor the band is readable off the statement."""
        return (self.a, -2 * self.a * self.m, self.a * self.m**2 + self.e)

    def render(self) -> str:
        return _render_poly(*self.coeffs())


@dataclass(frozen=True)
class Derived:
    """Everything a rung computes from a piece's core knobs. Cached, because
    `_redundant` calls `holds_at` O(k²·width) times per problem."""
    atoms: tuple[Atom, ...]
    caps: tuple[int, ...]      # per-atom integer bound the witness proves (may be empty)
    budget: int                # the integer the goal exposes (t / T / c)


# ------------------------------------------------------------------ pieces --


@dataclass(frozen=True)
class Piece:
    """One case: band `[lo, hi]` and the rung-specific piece assigned to it.

    `schema` is the FIRST field and has no default on purpose. The necessity
    machinery decides an exact-integer question about *this* piece's super-level
    set, and a piece that silently inherited `v2`'s predicate would ship a
    k-leaf plan that is secretly (k−1)-leaf (module docstring, "soundness
    asymmetry"). `Piece` therefore carries no predicate of its own: `holds_at`
    and `covers_band` dispatch to `self.schema`, and a piece cannot exist
    without one.

    The stored fields are the *core knobs* shared by every rung; everything else
    (pads, caps, the second atom, the exposed budget) is derived by the rung, so
    two rungs can never disagree about what a stored field means.
    """
    schema: Rung
    lo: int
    hi: int
    a: int          # curvature of the primary radicand (positive)
    m: int          # vertex abscissa (shared by every atom of the piece)
    d: int          # design margin: `a(x-m)^2 ≤ d` is the band-covering target
    width: int
    offset: int     # vertex offset from the band midpoint (a knob, kept for stats)
    slack: int      # margin above the exact requirement (a knob, kept for stats)
    extras: tuple[int, ...] = ()   # rung-specific knobs (see Rung.extra_knobs)
    repaired: bool = False         # tightened by the necessity repair (kept for stats)

    # -- geometry -------------------------------------------------------
    @property
    def far(self) -> int:
        return max(abs(self.lo - self.m), abs(self.hi - self.m))

    @property
    def base(self) -> int:
        return self.a * self.far**2

    # -- rung-derived ---------------------------------------------------
    @property
    def atoms(self) -> tuple[Atom, ...]:
        return _derived(self).atoms

    @property
    def caps(self) -> tuple[int, ...]:
        return _derived(self).caps

    @property
    def budget(self) -> int:
        """The integer the goal exposes: `t` (v2, r2_sum), `T` (r2_prod,
        r3_floor, r4_floorprod) or the numerator `c` (r1_recip)."""
        return _derived(self).budget

    @property
    def cap(self) -> int:
        """`t`: the bound the primary radicand's root must respect on this band.
        Rungs with no `√` cap (r1_recip) report the bound on the radicand."""
        return self.schema.primary_cap(self)

    @property
    def pad(self) -> int:
        """`e ≥ 1`: additive slack inside the primary radicand."""
        return self.atoms[0].e

    def radicand(self) -> tuple[int, int, int]:
        """(x², x, 1) coefficients of the primary radicand, expanded."""
        return self.atoms[0].coeffs()

    # -- the predicate (rung-dispatched; see the class docstring) --------
    def holds_at(self, x: int) -> bool:
        """Does this piece satisfy the goal's inequality at the integer x?
        Exact (iff), by integer arithmetic — no floating point anywhere in the
        truth argument."""
        return self.schema.holds_at(self, x)

    @property
    def covers_band(self) -> bool:
        """Coverage on the *reals*, decided at two integer points.

        Every rung's piece value is monotone in `|x − m|` (all atoms share the
        vertex and are convex), so the goal-side inequality is hardest at
        whichever band endpoint is furthest from the vertex — and both endpoints
        are integers. So the real-line claim reduces *exactly* to two calls of
        the rung's own integer predicate.
        """
        return self.holds_at(self.lo) and self.holds_at(self.hi)

    def outer_const(self, variant: str) -> int:
        """The k-independent integer constant the rendered piece carries."""
        return self.schema.outer_const(self, variant)

    def term(self, variant: str) -> str:
        return self.schema.term(self, variant)


@lru_cache(maxsize=8192)
def _derived(p: Piece) -> Derived:
    return p.schema.derive(p)


def _make(rung: Rung, lo: int, width: int, a: int, offset: int, slack: int,
          extras: tuple[int, ...] = (), *, repaired: bool = False) -> Piece:
    """The only way a *generated* piece is built: from the knob cell alone, so
    the sampler and `_tighten` cannot drift apart."""
    hi = lo + width
    m = lo + width // 2 + offset
    far = max(abs(lo - m), abs(hi - m))
    return Piece(schema=rung, lo=lo, hi=hi, a=a, m=m, d=a * far**2 + slack,
                 width=width, offset=offset, slack=slack, extras=tuple(extras),
                 repaired=repaired)


# -------------------------------------------------------------------- rungs --


class Rung:
    """One schema rung: a piece function plus its exact integer predicate.

    Everything difficulty-relevant lives here. What does *not* move between
    rungs — and is not overridable — is the frame: the balanced extremum tree,
    the flat `rcases` assembly, `C_LEVEL`, the knob support's k-independence,
    the exact-integer necessity test, and V6 with no exemptions. A "rung" that
    changed any of those would be a different family, not a harder one.
    """

    name: str = ""
    rationale: str = ""
    schema_id: str = ""
    n_atoms: int = 1
    extra_knobs: tuple[str, ...] = ()       # names of this rung's extra knob columns

    # -- identity -------------------------------------------------------
    def __init__(self) -> None:
        if not self.name or set(self.name) - _NAME_OK or self.name[0].isdigit():
            raise ValueError(f"rung name must match [a-z_][a-z0-9_]*: {self.name!r}")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<rung {self.name}>"

    @property
    def is_default(self) -> bool:
        return self.name == DEFAULT_PRESET

    # -- sampling -------------------------------------------------------
    def sample_extras(self, rng: random.Random, a: int) -> tuple[int, ...]:
        """Extra knob draws, AFTER (width, curvature, offset, slack).

        `v2` draws nothing, which is what keeps its RNG stream byte-identical to
        the pre-ladder generator's.
        """
        return ()

    def extra_cells(self, a: int) -> list[tuple[int, ...]]:
        """Every legal extras tuple for a given curvature — the exhaustive
        support `necessity_sweep` and `leaf_stats` check against."""
        return [()]

    # -- derived quantities ---------------------------------------------
    def derive(self, p: Piece) -> Derived:
        raise NotImplementedError

    def _check_extras(self, p: Piece) -> None:
        if len(p.extras) != len(self.extra_knobs):
            raise ValueError(
                f"{self.name}: piece needs extras {self.extra_knobs}, got {p.extras!r}")

    def primary_cap(self, p: Piece) -> int:
        return p.caps[0] if p.caps else p.d + p.atoms[0].e

    # -- the predicate ---------------------------------------------------
    def holds_at(self, p: Piece, x: int) -> bool:
        raise NotImplementedError

    def holds_exact(self, p: Piece, x: int) -> bool:
        """The same question answered with 60-digit reference arithmetic, from
        the piece's *real-valued* definition. Only `predicate_mismatches` uses
        it: it is the audit of `holds_at`, never a substitute for it."""
        raise NotImplementedError

    # -- rendering -------------------------------------------------------
    def term(self, p: Piece, variant: str) -> str:
        raise NotImplementedError

    def outer_const(self, p: Piece, variant: str) -> int:
        raise NotImplementedError

    def min_const(self, p: Piece) -> int:
        """The constant subtracted in the min variant; must be ≥ 1 or the
        renderer emits `… - 0` / `… + n`."""
        raise NotImplementedError

    def proof(self, p: Piece) -> str:
        raise NotImplementedError

    # -- reporting / gates ------------------------------------------------
    def knobs(self, p: Piece) -> dict:
        return {"width": p.width, "curvature": p.a, "offset": p.offset,
                "slack": p.slack, "cap": p.cap, "pad": p.pad, "repaired": p.repaired}

    def support_ok(self, kb: dict) -> bool:
        return (kb["width"] in WIDTHS and kb["curvature"] in CURVATURES
                and kb["offset"] in VERTEX_OFFSETS and kb["slack"] in SLACKS)

    def violations(self, p: Piece) -> list[str]:
        """Generation-time tripwire, per piece. Everything here is unreachable
        by construction; a loud failure beats a false problem."""
        out: list[str] = []
        if not p.covers_band:
            out.append("does not cover its band")
        for i, at in enumerate(p.atoms):
            if at.e < 1:
                out.append(f"atom {i} pad {at.e} < 1 (radicand leaks the vertex)")
            if at.a < 1:
                out.append(f"atom {i} curvature {at.a} < 1 (radicand not positive definite)")
        if len({at.coeffs() for at in p.atoms}) != len(p.atoms):
            out.append("two atoms render identically (the piece collapses)")
        if self.min_const(p) < 1:
            out.append(f"min-variant constant {self.min_const(p)} < 1 (renderer cannot emit it)")
        return out + self.extra_violations(p)

    def extra_violations(self, p: Piece) -> list[str]:
        return []


# --- rung v2: the shipped control ---------------------------------------------


class _V2(Rung):
    name = "v2"
    schema_id = "sqrt_capped_quadratic_bands"
    rationale = ("shipped schema; measured pass@8 0.923 over 68 leaves × 8 DSV2 attempts "
                 "— above the corridor ceiling, and the control every rung is read against")

    def derive(self, p: Piece) -> Derived:
        self._check_extras(p)
        t = _cap(p.d)
        return Derived(atoms=(Atom(p.a, p.m, t * t - p.d),), caps=(t,), budget=t)

    def holds_at(self, p: Piece, x: int) -> bool:
        # √(a(x−m)² + e) ≤ t ⟺ a(x−m)² + e ≤ t² ⟺ a(x−m)² ≤ d (both sides ≥ 0)
        return p.a * (x - p.m) ** 2 <= p.d

    def holds_exact(self, p: Piece, x: int) -> bool:
        with localcontext() as ctx:
            ctx.prec = _DECIMAL_PREC
            return Decimal(p.atoms[0].value(x)).sqrt() <= Decimal(p.budget)

    def term(self, p: Piece, variant: str) -> str:
        root = f"Real.sqrt ({p.atoms[0].render()})"
        n = self.outer_const(p, variant)
        return f"{n} - {root}" if variant == "max" else f"{root} - {n}"

    def outer_const(self, p: Piece, variant: str) -> int:
        return C_LEVEL + p.budget if variant == "max" else p.budget - C_LEVEL

    def min_const(self, p: Piece) -> int:
        return p.budget - C_LEVEL

    def proof(self, p: Piece) -> str:
        return (
            "by\n"
            "  intro x hl hr\n"
            f"  have hb : Real.sqrt ({p.atoms[0].render()}) ≤ {p.budget} := Real.sqrt_le_iff.mpr\n"
            "    ⟨by norm_num, by nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]⟩\n"
            "  linarith"
        )


# --- rung r1_recip: retarget the closing lemma --------------------------------


class _Recip(Rung):
    name = "r1_recip"
    schema_id = "reciprocal_quadratic_bands"
    rationale = ("the piece IS a quotient, so `Real.sqrt_le_iff` is inapplicable and "
                 "`le_div_iff₀` is the retarget; the lightest possible schema change, in "
                 "the ladder to test whether 'one extra lemma' is a difficulty lever at all")

    def derive(self, p: Piece) -> Derived:
        self._check_extras(p)
        # numerator c = C·(d + e): `C ≤ c/u ⟺ u ≤ d + e ⟺ a(x−m)² ≤ d`
        return Derived(atoms=(Atom(p.a, p.m, 1),), caps=(), budget=C_LEVEL * (p.d + 1))

    def holds_at(self, p: Piece, x: int) -> bool:
        # u ≥ e = 1 > 0, so the division is total and the iff needs no side condition
        return C_LEVEL * p.atoms[0].value(x) <= p.budget

    def holds_exact(self, p: Piece, x: int) -> bool:
        with localcontext() as ctx:
            ctx.prec = _DECIMAL_PREC
            u = Decimal(p.atoms[0].value(x))
            return Decimal(C_LEVEL) <= Decimal(p.budget) / u

    def term(self, p: Piece, variant: str) -> str:
        q = f"{p.budget} / ({p.atoms[0].render()})"
        return q if variant == "max" else f"{2 * C_LEVEL} - {q}"

    def outer_const(self, p: Piece, variant: str) -> int:
        return p.budget

    def min_const(self, p: Piece) -> int:
        return 2 * C_LEVEL

    def extra_violations(self, p: Piece) -> list[str]:
        # coverage-fatal if it could ever fail: Lean's x/0 = 0 would make the
        # piece 0 while the integer predicate read `0 ≤ c` = true
        return [] if p.atoms[0].e >= 1 else ["denominator can vanish (e < 1)"]

    def proof(self, p: Piece) -> str:
        u = p.atoms[0].render()
        return (
            "by\n"
            "  intro x hl hr\n"
            f"  have hu : (0:ℝ) < {u} := by nlinarith [sq_nonneg ({_shift(p.m)})]\n"
            f"  have hk : ({C_LEVEL}:ℝ) ≤ {p.budget} / ({u}) := by\n"
            "    rw [le_div_iff₀ hu]\n"
            "    nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]\n"
            "  linarith"
        )


# --- the two-atom rungs -------------------------------------------------------


class _TwoAtom(Rung):
    """Shared machinery for `r2_prod` / `r2_sum`: a second radicand at the same
    vertex, its curvature drawn independently (and distinct, so the two atoms
    can never render identically and the piece cannot collapse to `2√u`).

    The independent draw is deliberate: S1's probe derived the second atom
    deterministically from the first, which multiplies the *statement* space
    without multiplying the *knob* space — and this schema's distinct-leaf
    capacity is already only a few thousand at k=8 (F1). One extra `rng.choice`
    buys 2× the knob cells; `leaf_stats()["distinct_leaf_props"]` measures the
    realised capacity.
    """
    n_atoms = 2
    extra_knobs = ("curvature2",)

    def sample_extras(self, rng: random.Random, a: int) -> tuple[int, ...]:
        return (rng.choice([c for c in CURVATURES if c != a]),)

    def extra_cells(self, a: int) -> list[tuple[int, ...]]:
        return [(c,) for c in CURVATURES if c != a]

    def _second(self, p: Piece) -> tuple[int, int]:
        a2 = p.extras[0]
        return a2, a2 * p.far**2 + p.slack

    def derive(self, p: Piece) -> Derived:
        self._check_extras(p)
        t1 = _cap(p.d)
        a2, d2 = self._second(p)
        t2 = _cap(d2)
        atoms = (Atom(p.a, p.m, t1 * t1 - p.d), Atom(a2, p.m, t2 * t2 - d2))
        return Derived(atoms=atoms, caps=(t1, t2), budget=self._budget(t1, t2))

    def _budget(self, t1: int, t2: int) -> int:
        raise NotImplementedError

    def knobs(self, p: Piece) -> dict:
        kb = super().knobs(p)
        kb.update(curvature2=p.extras[0], cap2=p.caps[1], pad2=p.atoms[1].e,
                  outer=p.budget)
        return kb

    def support_ok(self, kb: dict) -> bool:
        return (super().support_ok(kb) and kb["curvature2"] in CURVATURES
                and kb["curvature2"] != kb["curvature"])


class _SqrtProd(_TwoAtom):
    name = "r2_prod"
    schema_id = "sqrt_product_quadratic_bands"
    rationale = ("a second atom, multiplicatively: one `sqrt_le_iff` cannot reach the goal, "
                 "so the visible budget T must be split into a divisor pair and the two "
                 "bounds recombined with `mul_le_mul` — two memorised steps, composed")

    def _budget(self, t1: int, t2: int) -> int:
        return t1 * t2

    def holds_at(self, p: Piece, x: int) -> bool:
        # √u·√w = √(uw) ≤ T ⟺ u·w ≤ T²  (u, w, T ≥ 0)
        u, w = (at.value(x) for at in p.atoms)
        return u * w <= p.budget**2

    def holds_exact(self, p: Piece, x: int) -> bool:
        with localcontext() as ctx:
            ctx.prec = _DECIMAL_PREC
            u, w = (Decimal(at.value(x)).sqrt() for at in p.atoms)
            return u * w <= Decimal(p.budget)

    def term(self, p: Piece, variant: str) -> str:
        root = " * ".join(f"Real.sqrt ({at.render()})" for at in p.atoms)
        n = self.outer_const(p, variant)
        return f"{n} - {root}" if variant == "max" else f"{root} - {n}"

    def outer_const(self, p: Piece, variant: str) -> int:
        return C_LEVEL + p.budget if variant == "max" else p.budget - C_LEVEL

    def min_const(self, p: Piece) -> int:
        return p.budget - C_LEVEL

    def proof(self, p: Piece) -> str:
        (u, w), (t1, t2) = (at.render() for at in p.atoms), p.caps
        return (
            "by\n"
            "  intro x hl hr\n"
            "  have hb := mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)\n"
            f"  have h1 : Real.sqrt ({u}) ≤ {t1} := Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith⟩\n"
            f"  have h2 : Real.sqrt ({w}) ≤ {t2} := Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith⟩\n"
            f"  have h3 : Real.sqrt ({u}) * Real.sqrt ({w}) ≤ {t1} * {t2} :=\n"
            "    mul_le_mul h1 h2 (Real.sqrt_nonneg _) (by norm_num)\n"
            "  linarith"
        )


class _SqrtSum(_TwoAtom):
    name = "r2_sum"
    schema_id = "sqrt_sum_quadratic_bands"
    rationale = ("the same two atoms, added: the memorised one-shot fails for a LOGICAL "
                 "reason (it bounds √u₁ ≤ t and the goal needs √u₁+√u₂ ≤ t), so the prover "
                 "must invent a budget split — anchored near t/2, which is the ladder's "
                 "only continuous, measured difficulty lever (|cap₁ − t/2|)")

    def _budget(self, t1: int, t2: int) -> int:
        return t1 + t2

    def holds_at(self, p: Piece, x: int) -> bool:
        # √U₁ + √U₂ ≤ t ⟺ 2√(U₁U₂) ≤ s := t² − U₁ − U₂, then square again:
        #   ⟺ s ≥ 0 ∧ 4·U₁·U₂ ≤ s²        (both squarings are between non-negatives)
        u, w = (at.value(x) for at in p.atoms)
        s = p.budget**2 - u - w
        return s >= 0 and 4 * u * w <= s * s

    def holds_exact(self, p: Piece, x: int) -> bool:
        with localcontext() as ctx:
            ctx.prec = _DECIMAL_PREC
            u, w = (Decimal(at.value(x)).sqrt() for at in p.atoms)
            return u + w <= Decimal(p.budget)

    def term(self, p: Piece, variant: str) -> str:
        roots = [f"Real.sqrt ({at.render()})" for at in p.atoms]
        n = self.outer_const(p, variant)
        if variant == "max":
            return f"{n} - " + " - ".join(roots)
        return " + ".join(roots) + f" - {n}"

    def outer_const(self, p: Piece, variant: str) -> int:
        return C_LEVEL + p.budget if variant == "max" else p.budget - C_LEVEL

    def min_const(self, p: Piece) -> int:
        return p.budget - C_LEVEL

    def knobs(self, p: Piece) -> dict:
        kb = super().knobs(p)
        # the registered lever (research/case-tree-hardening.md §7/R4.5): how far
        # the unique feasible split sits from the obvious guess t/2
        kb["split_gap"] = abs(p.caps[0] - p.budget / 2)
        return kb

    def proof(self, p: Piece) -> str:
        band = "mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)"
        lines = ["by", "  intro x hl hr"]
        for i, (at, t) in enumerate(zip(p.atoms, p.caps), start=1):
            lines.append(f"  have hb{i} : Real.sqrt ({at.render()}) ≤ {t} :=")
            lines.append(f"    Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith [{band}]⟩")
        lines.append("  linarith")
        return "\n".join(lines)


# --- the floor rungs ----------------------------------------------------------


class _FloorSqrt(Rung):
    name = "r3_floor"
    schema_id = "floor_sqrt_quadratic_bands"
    rationale = ("integrality and strictness: the cap is TIGHT (u_max = (T+1)²−1), so the "
                 "memorised sub-goal `√u ≤ T` is not merely unfound but FALSE on part of "
                 "the band; a strict bound plus a floor/cast step is forced. S2's "
                 "loose-vs-tight control isolates the cause exactly (0/12 tight, 12/12 loose)")

    def _T(self, p: Piece) -> int:
        """The tight cap. Three constraints, all binding somewhere in the support:

        * `T ≥ _cap(base) − 1` — else the piece would not cover its own band;
        * `T ≥ C+1` — else the min variant renders `⌊√u⌋ - 0`. The natural choice
          `_cap(base) − 1` hits exactly `C` at the (a=1, width=6, offset=0) cell;
        * `e = (T+1)² − 1 − base ≥ 1` — else the radicand is a perfect square and
          leaks the vertex (`_cap`'s docstring). Binds when `base + 1` is itself a
          square: `base = 48` (a=3, far=4) gives `e = 49 − 1 − 48 = 0`.

        `slack` is the free knob on top, and it costs nothing: the predicate is
        `a(x−m)² ≤ base` for *every* T (the pad is pinned to the top of the
        tightness interval), so raising T buys leaf capacity without moving the
        super-level set by a single integer point.
        """
        t = max(_cap(p.base) - 1, C_LEVEL + 1) + p.slack
        while (t + 1) ** 2 - 1 - p.base < 1:
            t += 1
        return t

    def derive(self, p: Piece) -> Derived:
        self._check_extras(p)
        t = self._T(p)
        # pin u_max to the TOP of the tightness interval (T² < u_max < (T+1)²):
        # the predicate is then `a(x−m)² ≤ base` at integer x for every T, so the
        # pad is a pure capacity knob and the spill is T-independent.
        return Derived(atoms=(Atom(p.a, p.m, (t + 1) ** 2 - 1 - p.base),), caps=(t + 1,),
                       budget=t)

    def holds_at(self, p: Piece, x: int) -> bool:
        # ⌊√u⌋ ≤ T ⟺ √u < T+1 ⟺ u < (T+1)²   (T ∈ ℤ, u ∈ ℤ at integer x)
        return p.atoms[0].value(x) < (p.budget + 1) ** 2

    def holds_exact(self, p: Piece, x: int) -> bool:
        with localcontext() as ctx:
            ctx.prec = _DECIMAL_PREC
            root = Decimal(p.atoms[0].value(x)).sqrt()
            return math.floor(root) <= p.budget

    def term(self, p: Piece, variant: str) -> str:
        root = f"(⌊Real.sqrt ({p.atoms[0].render()})⌋ : ℝ)"
        n = self.outer_const(p, variant)
        return f"{n} - {root}" if variant == "max" else f"{root} - {n}"

    def outer_const(self, p: Piece, variant: str) -> int:
        return C_LEVEL + p.budget if variant == "max" else p.budget - C_LEVEL

    def min_const(self, p: Piece) -> int:
        return p.budget - C_LEVEL

    def extra_violations(self, p: Piece) -> list[str]:
        t, u_max = p.budget, p.atoms[0].value(p.m + p.far)
        if not t * t < u_max:
            return [(f"cap is not tight: u_max {u_max} ≤ T² {t * t} — `√u ≤ T` holds on "
                     "the whole band and the rung's mechanism is gone")]
        return []

    def proof(self, p: Piece) -> str:
        u, t = p.atoms[0].render(), p.budget
        return (
            "by\n"
            "  intro x hl hr\n"
            f"  have hs : Real.sqrt ({u}) < {t + 1} := (Real.sqrt_lt' (by norm_num)).mpr (by\n"
            "    nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)])\n"
            f"  have hf : ⌊Real.sqrt ({u})⌋ < ({t + 1}:ℤ) := Int.floor_lt.mpr (by push_cast; linarith)\n"
            f"  have hf2 : (⌊Real.sqrt ({u})⌋ : ℝ) ≤ {t} := by\n"
            f"    have hi : ⌊Real.sqrt ({u})⌋ ≤ ({t}:ℤ) := by omega\n"
            "    exact_mod_cast hi\n"
            "  linarith"
        )


class _FloorProd(_TwoAtom):
    name = "r4_floorprod"
    schema_id = "floor_sqrt_product_quadratic_bands"
    rationale = ("the join of r2_prod and r3_floor: `Real.sqrt_mul` must be applied BEFORE "
                 "the floor step, an ordering no probed adaptation found (0 of 4 close it). "
                 "Hardest cell in either survey; projected below the corridor floor")
    _MAX_BUMP = 64

    def derive(self, p: Piece) -> Derived:
        self._check_extras(p)
        a2 = p.extras[0]
        e1 = 1 + p.slack
        u_max = p.base + e1
        e2 = 1
        # bump the second pad until P is not a perfect square, so T = ⌊√P⌋ gives
        # the strict T² < P < (T+1)² the floor step needs
        for _ in range(self._MAX_BUMP):
            if not _is_square(u_max * (a2 * p.far**2 + e2)):
                break
            e2 += 1
        else:  # pragma: no cover - consecutive squares are never this dense
            raise AssertionError(f"{self.name}: no non-square pad within {self._MAX_BUMP} bumps")
        atoms = (Atom(p.a, p.m, e1), Atom(a2, p.m, e2))
        prod = atoms[0].value(p.m + p.far) * atoms[1].value(p.m + p.far)
        return Derived(atoms=atoms, caps=(), budget=math.isqrt(prod))

    def primary_cap(self, p: Piece) -> int:
        return p.budget + 1

    def holds_at(self, p: Piece, x: int) -> bool:
        # ⌊√u·√w⌋ ≤ T ⟺ √(uw) < T+1 ⟺ u·w < (T+1)². The integer form is
        # mandatory: u·w reaches ~1e18 at k=32, past double precision entirely.
        u, w = (at.value(x) for at in p.atoms)
        return u * w < (p.budget + 1) ** 2

    def holds_exact(self, p: Piece, x: int) -> bool:
        with localcontext() as ctx:
            ctx.prec = _DECIMAL_PREC
            u, w = (Decimal(at.value(x)).sqrt() for at in p.atoms)
            return math.floor(u * w) <= p.budget

    def term(self, p: Piece, variant: str) -> str:
        inner = " * ".join(f"Real.sqrt ({at.render()})" for at in p.atoms)
        root = f"(⌊{inner}⌋ : ℝ)"
        n = self.outer_const(p, variant)
        return f"{n} - {root}" if variant == "max" else f"{root} - {n}"

    def outer_const(self, p: Piece, variant: str) -> int:
        return C_LEVEL + p.budget if variant == "max" else p.budget - C_LEVEL

    def min_const(self, p: Piece) -> int:
        return p.budget - C_LEVEL

    def knobs(self, p: Piece) -> dict:
        kb = Rung.knobs(self, p)
        kb.update(curvature2=p.extras[0], pad2=p.atoms[1].e, outer=p.budget)
        return kb

    def extra_violations(self, p: Piece) -> list[str]:
        far = p.m + p.far
        prod = p.atoms[0].value(far) * p.atoms[1].value(far)
        if _is_square(prod):
            return [(f"u_max·w_max = {prod} is a perfect square — ⌊√(uw)⌋ = T on the "
                     "band boundary and the strict floor bound is not available")]
        if not p.budget**2 < prod:
            return [f"cap is not tight: P {prod} ≤ T² {p.budget**2}"]
        return []

    def proof(self, p: Piece) -> str:
        u, w = (at.render() for at in p.atoms)
        far = p.m + p.far
        u_max, w_max = p.atoms[0].value(far), p.atoms[1].value(far)
        t1 = p.budget + 1
        return (
            "by\n"
            "  intro x hl hr\n"
            "  have hb := mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)\n"
            f"  have hu0 : (0:ℝ) ≤ {u} := by nlinarith [sq_nonneg ({_shift(p.m)})]\n"
            f"  have hw0 : (0:ℝ) ≤ {w} := by nlinarith [sq_nonneg ({_shift(p.m)})]\n"
            f"  have hu : {u} ≤ {u_max} := by nlinarith\n"
            f"  have hw : {w} ≤ {w_max} := by nlinarith\n"
            f"  have hp : ({u}) * ({w}) < {t1 * t1} := by nlinarith\n"
            f"  have heq : Real.sqrt ({u}) * Real.sqrt ({w}) = Real.sqrt (({u}) * ({w})) :=\n"
            f"    (Real.sqrt_mul hu0 ({w})).symm\n"
            f"  have hs : Real.sqrt (({u}) * ({w})) < {t1} :="
            " (Real.sqrt_lt' (by norm_num)).mpr (by nlinarith)\n"
            f"  have hlt : Real.sqrt ({u}) * Real.sqrt ({w}) < {t1} := by rw [heq]; exact hs\n"
            f"  have hf : ⌊Real.sqrt ({u}) * Real.sqrt ({w})⌋ < ({t1}:ℤ) :="
            " Int.floor_lt.mpr (by push_cast; linarith)\n"
            f"  have hf2 : (⌊Real.sqrt ({u}) * Real.sqrt ({w})⌋ : ℝ) ≤ {p.budget} := by\n"
            f"    have hi : ⌊Real.sqrt ({u}) * Real.sqrt ({w})⌋ ≤ ({p.budget}:ℤ) := by omega\n"
            "    exact_mod_cast hi\n"
            "  linarith"
        )


RUNGS: dict[str, Rung] = {r.name: r for r in (
    _V2(), _Recip(), _SqrtProd(), _SqrtSum(), _FloorSqrt(), _FloorProd(),
)}


def resolve_preset(preset: str | Rung) -> Rung:
    if isinstance(preset, Rung):
        return preset
    try:
        return RUNGS[preset]
    except KeyError:
        raise ValueError(
            f"unknown case_tree preset {preset!r}; have {sorted(RUNGS)}") from None


# ---------------------------------------------------------------- rendering --


def _piece_term(p: Piece, variant: str) -> str:
    """The piece as a Lean expression. `Real.sqrt` is fully qualified: PREAMBLE
    opens both `Real` and `Nat`, so a bare `sqrt` would be ambiguous."""
    return p.schema.term(p, variant)


def _chain(terms: list[str], variant: str) -> str:
    """**Balanced** `max`/`min` tree over the pieces.

    Right-nesting (`max q₁ (max q₂ (…))`) would put leaf i at depth i, so
    injecting its fact into the root costs i glue lemmas and the assembly is
    Θ(k²) — at k=128 that is ~200 KB of `le_max_of_le_right (` for 128 leaves of
    content. Since the root policy has to *emit* the assembly, that would make
    the k-axis partly measure token copying rather than decomposition, which is
    the confound this whole experiment exists to avoid. A balanced tree puts
    every leaf at depth ⌈log₂ k⌉ and the assembly at Θ(k log k).
    """
    def rec(lo: int, hi: int) -> str:
        if hi - lo == 1:
            return terms[lo]
        mid = (lo + hi) // 2
        return f"{variant} ({rec(lo, mid)}) ({rec(mid, hi)})"

    return rec(0, len(terms))


def _paths(k: int) -> list[tuple[str, ...]]:
    """Root-to-leaf L/R address of each piece in the same balanced tree."""
    out: list[tuple[str, ...]] = [()] * k

    def rec(lo: int, hi: int, prefix: tuple[str, ...]) -> None:
        if hi - lo == 1:
            out[lo] = prefix
            return
        mid = (lo + hi) // 2
        rec(lo, mid, prefix + ("L",))
        rec(mid, hi, prefix + ("R",))

    rec(0, k, ())
    return out


def _side(body: str, variant: str) -> str:
    return f"{C_LEVEL} ≤ {body}" if variant == "max" else f"{body} ≤ {C_LEVEL}"


def _goal_prop(pieces: list[Piece], variant: str) -> str:
    terms = [_piece_term(p, variant) for p in pieces]
    lo, hi = pieces[0].lo, pieces[-1].hi
    return f"∀ x : ℝ, {lo} ≤ x → x ≤ {hi} → {_side(_chain(terms, variant), variant)}"


def _leaf_prop(p: Piece, variant: str) -> str:
    return f"∀ x : ℝ, {p.lo} ≤ x → x ≤ {p.hi} → {_side(_piece_term(p, variant), variant)}"


def leaf_proof(p: Piece) -> str:
    """Generator-known witness — one template per rung, every leaf, every k.

    The witness proves the *real-line* claim and is allowed to use a merely
    sufficient certificate (module docstring); `holds_at` is what must be exact.
    Every rung's `nlinarith` call sits *inside* the witness, where FAMILIES.md
    allows it; what matters is that the leaf itself does not fall to a bare
    `intros; nlinarith` — measured per rung, with a live planted control.
    """
    return p.schema.proof(p)


def _wrap(term: str, path: tuple[str, ...], variant: str) -> str:
    """Inject a per-band fact into the extremum tree, walking its address from
    the leaf back up to the root (so the outermost glue is the root step)."""
    left, right = _GLUE[variant]
    for step in reversed(path):
        term = f"{left if step == 'L' else right} ({term})"
    return term


def _assembly(pieces: list[Piece], variant: str, names: list[str]) -> str:
    """Flat (non-nesting) k-way split.

    `rcases le_or_gt x t with c | c` leaves two goals; the focused `·` closes the
    in-band one and the tactic block continues at the same indentation on the
    other. Depth stays 1 for every k, which is what keeps k=32 (and k=128,
    FAMILIES.md scaling note) readable and cheap to elaborate.
    """
    k = len(pieces)
    paths = _paths(k)
    lines = ["intro x hx0 hxR"]
    for i in range(1, k):
        prev = "hx0" if i == 1 else f"c{i - 1}.le"
        lines.append(f"rcases le_or_gt x {_num(pieces[i - 1].hi)} with c{i} | c{i}")
        lines.append(f"· exact {_wrap(f'{names[i - 1]} x {prev} c{i}', paths[i - 1], variant)}")
    last = f"{names[k - 1]} x c{k - 1}.le hxR"
    lines.append(f"exact {_wrap(last, paths[k - 1], variant)}")
    return "\n".join(lines)


# ---------------------------------------------------------------- sampling ---


def _rng(k: int, seed: int, idx: int, rung: Rung) -> random.Random:
    """Deterministic in (k, seed, idx, rung) across processes and platforms.

    The default rung's seed string is the pre-ladder generator's, character for
    character, so `v2` datasets regenerate byte-identically (F11)."""
    tag = "" if rung.is_default else f"{rung.name}|"
    h = hashlib.sha256(f"{FAMILY}|{tag}{k}|{seed}|{idx}".encode()).hexdigest()[:16]
    return random.Random(int(h, 16))


def _sample_piece(rng: random.Random, lo: int, width: int, rung: Rung) -> Piece:
    """Draw order is rung-independent for the four core knobs, and the rung's
    extras come last — so `v2` makes exactly the draws the pre-ladder sampler
    made, in the same order."""
    a = rng.choice(CURVATURES)
    offset = rng.choice(VERTEX_OFFSETS)
    slack = rng.choice(SLACKS)
    extras = rung.sample_extras(rng, a)
    return _make(rung, lo, width, a, offset, slack, extras)


def _tighten(p: Piece) -> Piece:
    """The minimal legal piece for a band: vertex at the midpoint, zero slack.
    Its super-level set is *exactly* its own band, so it spills into no
    neighbour. Curvature (and the rung's extras) are preserved — only the spill
    is removed, and the rung rebuilds its own pads and caps."""
    return _make(p.schema, p.lo, p.width, p.a, 0, 0, p.extras, repaired=True)


def _redundant(pieces: list[Piece], i: int) -> bool:
    """Is band i's piece unnecessary — is every integer point of band i already
    covered by some other piece? A redundant piece makes the goal a (k-1)-case
    problem wearing a k-case costume, so the generator repairs it away.

    (`not _redundant(·, i)` exhibits an integer point of band i that only piece
    i covers, which is a *sufficient* certificate of necessity — exact integer
    arithmetic, no interval algebra over irrational crossing points. Each
    `holds_at` dispatches to its own piece's rung, so a mixed-rung list is
    answered correctly and no rung can be evaluated with another's predicate.)
    """
    p = pieces[i]
    return all(
        any(q.holds_at(x) for j, q in enumerate(pieces) if j != i)
        for x in range(p.lo, p.hi + 1)
    )


def _repair_necessity(pieces: list[Piece]) -> list[Piece]:
    """Safety net for necessity — under the shipped knobs it never fires, for
    any rung.

    Every rung's integer super-level set is `|x − m| ≤ far` (v2, r1_recip: one
    integer step out costs `a(2·far+1) ≥ 7 > slack`; the two-atom rungs: one step
    out pushes both atoms past their caps; the floor rungs: the pad is pinned so
    the set is exactly `a(x−m)² ≤ base`). So the reach past a band is
    `far − (width − far) = 2·|offset| ≤ 2`, with *no* dependence on the width.
    Since `min(WIDTHS) = 6 > 2·2`, two maximally greedy neighbours still leave
    the victim band's midpoint — an integer, because widths are even —
    uncovered. Necessity is therefore structural, which is what keeps the
    leaf-knob distribution *exactly* independent of k
    (`leaf_stats()["repaired_frac"] == 0.0` everywhere): a repair that fired at
    different rates per k would itself be a flatness leak, which is how this
    constraint was found (see the design log).

    That argument is re-established per rung by `necessity_sweep()`, which walks
    the rung's entire knob support exhaustively — it is **not** inherited from
    v2, because every widening of the support (a second atom, a shifted pad)
    re-opens it.

    Kept anyway as a tripwire: if the knob support is ever widened past the
    bound above, this quietly restores necessity instead of shipping k-leaf
    plans that are secretly (k−1)-leaf. It tightens the pieces that *reach
    into* a swallowed band; a piece with no spill is never rewritten.
    Terminates in at most k passes — a band whose overlappers are all tight
    keeps its midpoint private, so while any band is redundant some overlapping
    piece is still loose, and each pass tightens at least one.
    """
    k = len(pieces)
    for _ in range(k + 1):
        bad = [i for i in range(k) if _redundant(pieces, i)]
        if not bad:
            break
        for i in bad:
            span = range(pieces[i].lo, pieces[i].hi + 1)
            for j in range(k):
                loose = pieces[j].offset != 0 or pieces[j].slack != 0
                if j != i and loose and any(pieces[j].holds_at(x) for x in span):
                    pieces[j] = _tighten(pieces[j])
    return pieces


def _sample_pieces(k: int, rng: random.Random, rung: Rung) -> list[Piece]:
    """k contiguous bands tiling a domain centered on 0, each with its piece."""
    widths = [rng.choice(WIDTHS) for _ in range(k)]
    lo = -(sum(widths) // 2)
    pieces: list[Piece] = []
    for w in widths:
        pieces.append(_sample_piece(rng, lo, w, rung))
        lo += w
    return _repair_necessity(pieces)


# ------------------------------------------------------- soundness auditing --


def predicate_mismatches(p: Piece, radius: int = 12) -> dict:
    """Audit the rung's integer predicate against 60-digit reference arithmetic.

    Returns the two failure directions separately, because they are not equally
    bad (module docstring):

    * `under` — the exact real predicate holds but `holds_at` says no. The
      generator then believes a point is private when a neighbour covers it, and
      ships **false necessity**: a k-leaf plan that is secretly (k−1)-leaf.
    * `over` — `holds_at` says yes but the exact predicate says no. The
      generator then believes a band is covered when it is not, and ships a
      **false theorem**.

    Both must be empty. This is the check that rejected `Real.log` pieces.
    """
    under, over = [], []
    for x in range(p.m - radius, p.m + radius + 1):
        got, want = p.holds_at(x), p.schema.holds_exact(p, x)
        if want and not got:
            under.append(x)
        elif got and not want:
            over.append(x)
    return {"under": under, "over": over,
            "ok": not under and not over, "points": 2 * radius + 1}


def necessity_sweep(rung: str | Rung) -> dict:
    """Exhaustive walk of a rung's whole knob support: how far past its own band
    can one piece reach?

    Necessity is structural iff `max_spill < min(WIDTHS)/2` — then a victim
    band's midpoint (an integer, at distance ≥ width/2 from both neighbours) is
    covered by no other piece, at every k. The sweep is position-independent
    because every rung's predicate is a function of `x − m` alone, so these
    cells settle it for every band in every problem at every k.

    Re-run this whenever the knob support widens; F3 is not inheritable.
    """
    r = resolve_preset(rung)
    cells, worst, at_threshold = 0, 0, []
    threshold = min(WIDTHS) // 2
    for width in WIDTHS:
        for a in CURVATURES:
            for offset in VERTEX_OFFSETS:
                for slack in SLACKS:
                    for extras in r.extra_cells(a):
                        cells += 1
                        p = _make(r, 0, width, a, offset, slack, extras)
                        left = right = 0
                        while p.holds_at(p.lo - left - 1):
                            left += 1
                        while p.holds_at(p.hi + right + 1):
                            right += 1
                        spill = max(left, right)
                        worst = max(worst, spill)
                        if spill >= threshold:
                            at_threshold.append(
                                {"width": width, "curvature": a, "offset": offset,
                                 "slack": slack, "extras": list(extras), "spill": spill})
    return {"rung": r.name, "cells": cells, "max_spill": worst,
            "threshold": threshold, "cells_at_threshold": at_threshold,
            "ok": worst < threshold}


# ---------------------------------------------------------------- generator --


def layout(k: int, seed: int, idx: int = 0,
           preset: str | Rung = DEFAULT_PRESET) -> tuple[str, list[Piece]]:
    """The sampled case structure behind one problem: (variant, pieces).

    Exposed so tests and datasheets can check the geometric invariants against
    the same objects `build` uses, instead of re-deriving them from the RNG.
    """
    if k < 2:
        raise ValueError(f"case_tree needs k >= 2 (a 1-case split is not a case tree); got {k}")
    rung = resolve_preset(preset)
    rng = _rng(k, seed, idx, rung)
    variant = rng.choice(VARIANTS)
    return variant, _sample_pieces(k, rng, rung)


def build(k: int, seed: int, idx: int = 0,
          preset: str | Rung = DEFAULT_PRESET) -> GeneratedProblem:
    """One problem, a pure function of (k, seed, idx, preset)."""
    rung = resolve_preset(preset)
    variant, pieces = layout(k, seed, idx, preset=rung)

    # Generation-time tripwires. All are unreachable by construction; each one
    # is a class of false problem we would otherwise ship silently.
    bad = [f"piece {i}: {v}" for i, p in enumerate(pieces) for v in rung.violations(p)]
    if bad:
        raise AssertionError(f"{rung.name}: {bad} — generator bug")
    if any(p.schema is not rung for p in pieces):  # pragma: no cover - defensive
        raise AssertionError(f"{rung.name}: a piece carries a foreign schema — generator bug")
    red = [i for i in range(k) if _redundant(pieces, i)]
    if red:  # the repair above should have removed these; k-leaf must mean k-leaf
        raise AssertionError(f"{rung.name}: piece(s) {red} are redundant after repair "
                             "— the plan would be secretly (k-1)-leaf")

    idtag = "" if rung.is_default else f"{rung.name}-"
    nametag = "" if rung.is_default else f"_{rung.name}"
    pid = f"{FAMILY}-{idtag}k{k}-s{seed}-{idx}"

    names = [f"hb{i + 1}" for i in range(k)]
    goal = GoalSpec(id=pid, prop=_goal_prop(pieces, variant), name=f"goal{nametag}")
    lemmas = [LemmaSpec(name=n, prop=_leaf_prop(p, variant)) for n, p in zip(names, pieces)]
    plan = DecompositionPlan(lemmas=lemmas, assembly=_assembly(pieces, variant, names))
    witnesses = {n: LeafWitness(prop=l.prop, proof=leaf_proof(p))
                 for n, l, p in zip(names, lemmas, pieces)}

    coeffs = [c for p in pieces for at in p.atoms for c in at.coeffs()]
    return GeneratedProblem(
        id=pid,
        family=FAMILY,
        k=k,
        seed=seed,
        goal=goal,
        oracle_plan=plan,
        witnesses=witnesses,
        meta={
            # V6: nothing is exempt. The split and the per-band claims are all
            # hidden; only the piecewise function itself is (necessarily) visible.
            "visible_lemmas": [],
            "variant": variant,
            "split_kind": "interval",
            "preset": rung.name,
            "schema": rung.schema_id,
            "n_atoms": rung.n_atoms,
            "domain": [pieces[0].lo, pieces[-1].hi],
            "bands": [[p.lo, p.hi] for p in pieces],
            "knobs": [rung.knobs(p) for p in pieces],
            "leaf_prop_lens": [len(l.prop) for l in lemmas],
            "max_abs_coeff": max(abs(c) for c in coeffs),
            "max_outer_const": max(p.outer_const(variant) for p in pieces),
        },
    )


def generate(k: int, seed: int = 0, n: int = 1,
             preset: str | Rung = DEFAULT_PRESET) -> list[GeneratedProblem]:
    """REGISTRY entry point: n problems, deterministic in (k, seed, preset).

    `preset` names a rung of the hardening ladder (see `RUNGS` and the module
    docstring); the default is the shipped `v2` schema and its output is
    byte-identical to the pre-ladder generator's.
    """
    rung = resolve_preset(preset)
    return [build(k, seed, i, preset=rung) for i in range(n)]


def leaf_stats(problems: list[GeneratedProblem]) -> dict[int, dict]:
    """Per-k leaf-shape distribution — the flatness evidence for the datasheet
    (FAMILIES.md: "structural flatness … is checked at generation time").

    Reports each rung's own knob support, so a ladder rung's extra knobs
    (`curvature2`, the `r2_sum` lever) are covered by `knob_support_ok` and by
    `distinct_knob_tuples` rather than silently ignored. `distinct_leaf_props`
    is the distinct-leaf capacity FAMILIES.md's GRPO-correlation note asks
    datasheets to report — this schema's capacity is small and saturating
    (~3.4k at k=8 for v2), so a rung that multiplies statement length without
    multiplying knob cells should be visible here.
    """
    by_k: dict[int, list[GeneratedProblem]] = {}
    for p in problems:
        by_k.setdefault(p.k, []).append(p)

    out: dict[int, dict] = {}
    for k, ps in sorted(by_k.items()):
        lens = [n for p in ps for n in p.meta["leaf_prop_lens"]]
        props = {l.prop for p in ps for l in p.oracle_plan.lemmas}
        rungs = {p.meta.get("preset", DEFAULT_PRESET) for p in ps}
        knobs = {tuple(sorted((key, v) for key, v in kb.items() if key != "repaired"))
                 for p in ps for kb in p.meta["knobs"]}
        coeffs = sorted(p.meta["max_abs_coeff"] for p in ps)
        out[k] = {
            "problems": len(ps),
            "leaves": len(lens),
            "presets": sorted(rungs),
            "leaf_len_mean": round(sum(lens) / len(lens), 1),
            "leaf_len_min": min(lens),
            "leaf_len_max": max(lens),
            "goal_len_mean": round(sum(len(p.goal.prop) for p in ps) / len(ps), 1),
            "max_abs_coeff": max(coeffs),
            "median_abs_coeff": coeffs[len(coeffs) // 2],
            # bounded by the knob support, so unlike the radicand's constant it
            # must NOT grow with k — the flatness claim the outer cap adds
            "max_outer_const": max(p.meta["max_outer_const"] for p in ps),
            "distinct_knob_tuples": len(knobs),
            "distinct_leaf_props": len(props),
            # fraction of leaves whose knobs were tightened by the necessity
            # repair — the one way the leaf distribution could drift with k
            "repaired_frac": round(
                sum(kb["repaired"] for p in ps for kb in p.meta["knobs"]) / len(lens), 3),
            "knob_support_ok": all(
                resolve_preset(p.meta.get("preset", DEFAULT_PRESET)).support_ok(kb)
                for p in ps for kb in p.meta["knobs"]
            ),
        }
    return out


register(FAMILY, generate)
