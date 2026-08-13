#!/usr/bin/env python
"""Probe ALGEBRAIC-DEPTH hardening directions for `case_tree` (S1).

Why this exists
---------------
`case_tree` measures pass@8 **0.923** against the frozen DeepSeek-Prover-V2-7B leaf
(68 leaves × 8 attempts, `data/bank/family_leaf_calibration.jsonl`) — far above the
[0.25, 0.9] corridor's ceiling. Every knob marginal inside the shipped support is flat
(variant is the only separator and caps at 0.872), and the proof taxonomy says why:
68/68 successful leaves use **one** memorized idiom —

    intro x hx1 hx2
    have h₁ : 0 ≤ Real.sqrt (U) := by apply Real.sqrt_nonneg
    have h₂ : Real.sqrt (U) ≤ t := by
      apply Real.sqrt_le_iff.mpr
      constructor
      · nlinarith
      · nlinarith [sq_nonneg (x - m), sq_nonneg (x - hi)]
    nlinarith [sq_nonneg (x - m), sq_nonneg (x - hi), sq_nonneg (x - lo)]

— which is the generator's own witness template with the cap `t` read straight off the
goal (`t = A − C`). The family currently measures idiom recall. So a *distribution*
retune cannot move it; a **schema** change must. This script probes four schema
candidates in live Lean, each on four axes:

  (a) EXACT INTEGER PREDICATE — `holds_at(x)` for the new piece, audited numerically
      against 60-digit `Decimal` reference arithmetic. Under-approximation is
      disqualifying (it would let the generator claim necessity it does not have);
      the audit reports over/under/exact per direction.
  (b) WITNESS — the generator-known proof, kernel-checked on every probe instance.
  (c) BATTERY FLOOR — `families.validate.battery_proofs()` (10 tactics × {bare,
      intros-first}); any success kills the direction. Run with a KNOWN-DEAD planted
      control (aborts if it survives) and the current schema as a negative control.
  (d) IDIOM CEILING — the measured DSV2 idiom, templated so it can be instantiated
      mechanically for any candidate piece, plus plausible ADAPTATIONS (two have-steps
      with a guessed budget split, the `sq_sqrt` route, a quartic vertex hint, an
      oracle split). Calibrated on the current schema first: if the templated idiom
      does not close today's leaves, the template is wrong.

Nothing here measures pass@8 — that needs the pod. This is the local gate, mirroring
`scripts/stage_retune_candidates.py` (the bridge_chain playbook).

Usage
-----
    uv run python scripts/probes/probe_ct_algebraic.py --audit          # (a) only, no Lean
    uv run python scripts/probes/probe_ct_algebraic.py --lean           # (a)-(d), needs Lean
    uv run python scripts/probes/probe_ct_algebraic.py --lean --pilot   # 1 instance/direction
    uv run python scripts/probes/probe_ct_algebraic.py --lean --skip-battery

Outputs (--out-dir, default data/families/ct_probe_a/):
    audit.json       exactness + spill report per direction
    lean.json        witness / battery / idiom verdicts per instance
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, getcontext
from pathlib import Path

from rlmath.families import case_tree as ct

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = ROOT / "data" / "families" / "ct_probe_a"

getcontext().prec = 60

C = ct.C_LEVEL          # 3 — the bare side of the goal, unchanged by every direction
BATTERY_TIMEOUT_S = 25.0
WITNESS_TIMEOUT_S = 120.0
IDIOM_TIMEOUT_S = 60.0

# Positive control for the gate itself: the v1 shape, measured dead to `intros; nlinarith`
# (case_tree module docstring — 70/70 v1 leaves fell to it). If THIS survives, the battery
# is not executing and "everything survives" means nothing.
PLANTED_CONTROL = "∀ x : ℝ, -7 ≤ x → x ≤ 1 → 3 ≤ -2 * x ^ 2 - 12 * x + 17"


class ControlFailed(RuntimeError):
    """The known-dead planted control survived: the battery gate is not measuring."""


# --------------------------------------------------------------------------- render --


def render_poly(coeffs: dict[int, int]) -> str:
    """Expanded integer polynomial in a real `x`, single-line Lean.

    Same conventions as `case_tree._render_poly` (which only handles degree ≤ 2):
    descending degree, `-` folded into the connective so no unary minus appears
    mid-expression.
    """
    out = ""
    for deg in sorted(coeffs, reverse=True):
        c = coeffs[deg]
        if c == 0:
            continue
        mag = abs(c)
        body = "" if deg == 0 else ("x" if deg == 1 else f"x ^ {deg}")
        if body:
            term = body if mag == 1 else f"{mag} * {body}"
        else:
            term = str(mag)
        if not out:
            out = f"-{term}" if c < 0 else term
        else:
            out += f" - {term}" if c < 0 else f" + {term}"
    return out or "0"


def _binom_shift(a: int, m: int, deg: int) -> dict[int, int]:
    """Coefficients of `a·(x − m)^deg`, expanded."""
    from math import comb

    return {deg - j: a * comb(deg, j) * ((-m) ** j) for j in range(deg + 1)}


# ---------------------------------------------------------------------------- atoms --


@dataclass(frozen=True)
class PolyAtom:
    """`a·(x − m)^deg + e` under one `Real.sqrt`. `deg ∈ {2, 4}`.

    Invariant established by the sampler: `value(x) ≤ cap²` for every real x in the
    band, so `Real.sqrt (value x) ≤ cap` is provable from the band hypotheses alone.
    """
    deg: int
    a: int
    m: int
    e: int
    cap: int

    def coeffs(self) -> dict[int, int]:
        c = _binom_shift(self.a, self.m, self.deg)
        c[0] = c.get(0, 0) + self.e
        return c

    def render(self) -> str:
        return render_poly(self.coeffs())

    def value(self, x: int) -> int:
        return self.a * (x - self.m) ** self.deg + self.e

    def value_dec(self, x: Decimal) -> Decimal:
        return Decimal(self.a) * (x - Decimal(self.m)) ** self.deg + Decimal(self.e)


@dataclass(frozen=True)
class NestedAtom:
    """`a·(x − m)² + g + Real.sqrt (inner)` under an outer `Real.sqrt`.

    The radicand is itself irrational at integer x, so the exact predicate has to
    isolate the inner root and square twice (see `Instance.holds_at`).
    """
    a: int
    m: int
    g: int
    inner: PolyAtom
    cap: int

    def outer_coeffs(self) -> dict[int, int]:
        c = _binom_shift(self.a, self.m, 2)
        c[0] = c.get(0, 0) + self.g
        return c

    def render(self) -> str:
        return f"{render_poly(self.outer_coeffs())} + Real.sqrt ({self.inner.render()})"

    def outer_value(self, x: int) -> int:
        return self.a * (x - self.m) ** 2 + self.g


Atom = PolyAtom | NestedAtom


# ------------------------------------------------------------------------- instance --


@dataclass
class Instance:
    """One candidate leaf: a band, a piece, the generator's cap budget, its knobs."""
    direction: str
    variant: str            # "max" | "min"
    lo: int
    hi: int
    atoms: list[Atom]
    t: int                  # total cap: piece ⋛ C  ⟺  Σ √atomᵢ ≤ t
    knobs: dict = field(default_factory=dict)

    # ---- rendering
    @property
    def name(self) -> str:
        kb = self.knobs
        return (f"{self.direction}-{self.variant}-b{self.lo}_{self.hi}"
                f"-a{kb.get('a')}o{kb.get('offset')}s{kb.get('slack')}")

    def piece_term(self) -> str:
        roots = [f"Real.sqrt ({a.render()})" for a in self.atoms]
        if self.variant == "max":
            return f"{C + self.t} - " + " - ".join(roots)
        return " + ".join(roots) + f" - {self.t - C}"

    def prop(self) -> str:
        body = self.piece_term()
        side = f"{C} ≤ {body}" if self.variant == "max" else f"{body} ≤ {C}"
        return f"∀ x : ℝ, {self.lo} ≤ x → x ≤ {self.hi} → {side}"

    # ---- (a) the exact integer predicate
    def holds_at(self, x: int) -> bool:
        """Does the piece satisfy the goal's inequality at the *integer* point x?

        Both variants reduce to `Σ √atomᵢ(x) ≤ t`; the three cases below are exact
        iff-characterisations of that over the integers (derivations in
        research/ct-hardening-survey-a.md §2).
        """
        t2 = self.t * self.t
        if len(self.atoms) == 1 and isinstance(self.atoms[0], PolyAtom):
            # √U ≤ t  ⟺  U ≤ t²   (U ≥ 0, t ≥ 0)
            return self.atoms[0].value(x) <= t2
        if len(self.atoms) == 1 and isinstance(self.atoms[0], NestedAtom):
            # √(U + √V) ≤ t  ⟺  U + √V ≤ t²  ⟺  t² − U ≥ 0 ∧ V ≤ (t² − U)²
            at = self.atoms[0]
            s = t2 - at.outer_value(x)
            return s >= 0 and at.inner.value(x) <= s * s
        if len(self.atoms) == 2 and all(isinstance(a, PolyAtom) for a in self.atoms):
            # √U₁ + √U₂ ≤ t  ⟺  t² − U₁ − U₂ ≥ 0 ∧ 4·U₁·U₂ ≤ (t² − U₁ − U₂)²
            u1 = self.atoms[0].value(x)
            u2 = self.atoms[1].value(x)
            s = t2 - u1 - u2
            return s >= 0 and 4 * u1 * u2 <= s * s
        raise NotImplementedError(f"no exact predicate for {self.direction}")

    def holds_at_ref(self, x: int | Decimal) -> bool:
        """60-digit reference evaluation of the SAME condition, for the audit.

        Ties (equality) can only occur at algebraic-integer coincidences — a sum of
        square roots of integers is an integer only when each root is — and in those
        cases the `Decimal` values are exact, so the comparison is not a float race.
        """
        xd = Decimal(x)
        tot = Decimal(0)
        for a in self.atoms:
            if isinstance(a, PolyAtom):
                tot += a.value_dec(xd).sqrt()
            else:
                inner = a.inner.value_dec(xd)
                outer = Decimal(a.a) * (xd - Decimal(a.m)) ** 2 + Decimal(a.g)
                tot += (outer + inner.sqrt()).sqrt()
        return tot <= Decimal(self.t)

    @property
    def covers_band(self) -> bool:
        """Generator's coverage certificate on the REALS: Σ capᵢ = t and each
        `√atomᵢ ≤ capᵢ` on the whole band (a *sufficient* condition — allowed,
        coverage is the safe direction)."""
        return sum(a.cap for a in self.atoms) == self.t

    # ---- (b) the generator-known witness
    def witness(self, order: str) -> str:
        """`order` is the argument order of `Real.sqrt_le_iff` in this Mathlib,
        determined at runtime by `probe_sqrt_le_iff_order` — "nt" means the
        non-negativity conjunct comes first, "tn" means the bound does."""
        band = "mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)"
        lines = ["by", "  intro x hl hr"]
        for i, a in enumerate(self.atoms, start=1):
            if isinstance(a, NestedAtom):
                lines += [
                    f"  have hv{i} : Real.sqrt ({a.inner.render()}) ≤ {a.inner.cap} :=",
                    f"    {_sqrt_le_iff(order, f'by nlinarith [{band}]')}",
                    f"  have hb{i} : Real.sqrt ({a.render()}) ≤ {a.cap} :=",
                    f"    {_sqrt_le_iff(order, f'by nlinarith [{band}, hv{i}]')}",
                ]
            else:
                lines += [
                    f"  have hb{i} : Real.sqrt ({a.render()}) ≤ {a.cap} :=",
                    f"    {_sqrt_le_iff(order, f'by nlinarith [{band}]')}",
                ]
        lines.append("  linarith")
        return "\n".join(lines)


def _sqrt_le_iff(order: str, bound_proof: str) -> str:
    nonneg = "by norm_num"
    pair = f"⟨{nonneg}, {bound_proof}⟩" if order == "nt" else f"⟨{bound_proof}, {nonneg}⟩"
    return f"Real.sqrt_le_iff.mpr {pair}"


# ------------------------------------------------------------------- direction build --


def _cap(d: int) -> int:
    """Smallest integer `t` with `t² > d` (case_tree._cap: forces pad ≥ 1)."""
    t = 1
    while t * t <= d:
        t += 1
    return t


def _far(lo: int, hi: int, m: int) -> int:
    return max(abs(lo - m), abs(hi - m))


def _poly_atom(lo: int, hi: int, a: int, m: int, slack: int, deg: int) -> PolyAtom:
    """The v2 construction, generalized to degree `deg`: pick `d = a·far^deg + slack`,
    take `cap = _cap(d)`, and set the additive pad `e = cap² − d ≥ 1`."""
    d = a * _far(lo, hi, m) ** deg + slack
    cap = _cap(d)
    return PolyAtom(deg=deg, a=a, m=m, e=cap * cap - d, cap=cap)


def _second_atom_knobs(lo: int, hi: int, a1: int, off1: int, slack1: int) -> tuple[int, int, int]:
    """Deterministic second-atom knobs, drawn from the SAME support as the first and
    forced to differ from it — an asymmetric budget split is the point of H1."""
    rng = random.Random(f"atom2|{lo}|{hi}|{a1}|{off1}|{slack1}")
    for _ in range(64):
        a2 = rng.choice(ct.CURVATURES)
        off2 = rng.choice(ct.VERTEX_OFFSETS)
        slack2 = rng.choice(ct.SLACKS)
        if (a2, off2) != (a1, off1):
            return a2, off2, slack2
    return (a1 % 3) + 1, -off1, slack1


def build_instance(direction: str, variant: str, lo: int, hi: int,
                   a: int, offset: int, slack: int) -> Instance:
    """One candidate leaf from the SAME knob draw the shipped sampler would make."""
    mid = lo + (hi - lo) // 2
    m = mid + offset
    kb = {"a": a, "offset": offset, "slack": slack, "width": hi - lo}

    if direction == "v2":                                   # negative control
        at = _poly_atom(lo, hi, a, m, slack, 2)
        return Instance(direction, variant, lo, hi, [at], at.cap, kb)

    if direction == "H2_quartic":
        at = _poly_atom(lo, hi, a, m, slack, 4)
        return Instance(direction, variant, lo, hi, [at], at.cap, kb)

    if direction in ("H1_twoatom", "H4_twoatom_quartic"):
        a2, off2, slack2 = _second_atom_knobs(lo, hi, a, offset, slack)
        deg2 = 4 if direction == "H4_twoatom_quartic" else 2
        at1 = _poly_atom(lo, hi, a, m, slack, 2)
        at2 = _poly_atom(lo, hi, a2, mid + off2, slack2, deg2)
        kb |= {"a2": a2, "offset2": off2, "slack2": slack2,
               "cap1": at1.cap, "cap2": at2.cap}
        return Instance(direction, variant, lo, hi, [at1, at2], at1.cap + at2.cap, kb)

    if direction == "H3_nested":
        a2, off2, slack2 = _second_atom_knobs(lo, hi, a, offset, slack)
        inner = _poly_atom(lo, hi, a2, mid + off2, slack2, 2)
        # outer: u = a(x−m)² + g with  max_band u + inner.cap ≤ t²
        D = a * _far(lo, hi, m) ** 2 + slack + inner.cap
        t = _cap(D)
        at = NestedAtom(a=a, m=m, g=t * t - D, inner=inner, cap=t)
        kb |= {"a2": a2, "offset2": off2, "slack2": slack2, "inner_cap": inner.cap}
        return Instance(direction, variant, lo, hi, [at], t, kb)

    raise ValueError(f"unknown direction {direction!r}")


DIRECTIONS = ("v2", "H1_twoatom", "H2_quartic", "H3_nested", "H4_twoatom_quartic")


# -------------------------------------------------------------- probe-instance picks --


def knob_cells(n_bands: int = 3) -> list[tuple[str, int, int, int, int, int]]:
    """Probe cells spanning the shipped knob support, with realistic band positions.

    Bands are taken from the shipped sampler at k ∈ {2, 4, 8} so the *absolute*
    position (and hence coefficient magnitude, the one k-dependence in the schema)
    is realistic at both ends of the Phase-1 grid. Cells: curvature {1,3} ×
    offset {0, ±1} × variant {max,min} — the four axes the brief names.
    """
    bands: list[tuple[int, int]] = []
    for k in (2, 4, 8):
        _, pieces = ct.layout(k, seed=9001, idx=0)
        bands.append((pieces[0].lo, pieces[0].hi))          # near the domain edge
        bands.append((pieces[len(pieces) // 2].lo, pieces[len(pieces) // 2].hi))
    seen: list[tuple[int, int]] = []
    for b in bands:
        if b not in seen:
            seen.append(b)
    bands = seen[:n_bands * 2]

    cells = []
    combos = [(1, 0, 0), (3, 0, 1), (1, 1, 1), (3, -1, 0), (2, 1, 0), (2, -1, 1),
              (3, 1, 1), (1, -1, 0)]
    for i, (a, off, slack) in enumerate(combos):
        lo, hi = bands[i % len(bands)]
        variant = "max" if i % 2 == 0 else "min"
        cells.append((variant, lo, hi, a, off, slack))
    return cells


def instances_for(direction: str, n: int) -> list[Instance]:
    return [build_instance(direction, v, lo, hi, a, off, s)
            for v, lo, hi, a, off, s in knob_cells()[:n]]


# ------------------------------------------------------- (a) exactness + spill audit --


def audit_direction(direction: str, n_random: int = 400) -> dict:
    """Compare the integer predicate against 60-digit reference arithmetic.

    Reports, over a wide integer grid on randomly drawn instances:
      * `mismatch_under` — predicate says False where the truth is True. **This is the
        disqualifying direction**: the generator would believe a piece covers less than
        it does and claim necessity it lacks.
      * `mismatch_over`  — predicate says True where the truth is False. Safe for
        necessity (it makes `_redundant` more likely, i.e. repairs more), unsafe for
        nothing, but still a defect worth knowing about.
      * `spill` — how far past its own band the piece's exact super-level set reaches.
        `case_tree._repair_necessity` is a no-op today only because that reach is
        < width/2; a direction whose reach grows would make the necessity repair fire
        at k-dependent rates, which is a flatness leak.
    """
    rng = random.Random(f"audit|{direction}")
    under = over = checked = 0
    worst: list[dict] = []
    spills: list[int] = []
    caps: list[int] = []
    coeffs: list[int] = []
    for _ in range(n_random):
        k = rng.choice((2, 4, 8))
        _, pieces = ct.layout(k, seed=rng.randrange(10**6), idx=0)
        p = rng.choice(pieces)
        variant = rng.choice(ct.VARIANTS)
        inst = build_instance(direction, variant, p.lo, p.hi, p.a, p.offset, p.slack)
        assert inst.covers_band, f"{inst.name}: cap budget does not sum"
        caps.append(inst.t)
        for a in inst.atoms:
            src = a.coeffs() if isinstance(a, PolyAtom) else a.outer_coeffs()
            coeffs.append(max(abs(c) for c in src.values()))
            if isinstance(a, NestedAtom):
                coeffs.append(max(abs(c) for c in a.inner.coeffs().values()))
        span = range(inst.lo - 12, inst.hi + 13)
        reach = 0
        for x in span:
            got, ref = inst.holds_at(x), inst.holds_at_ref(x)
            checked += 1
            if got != ref:
                (under, over) = (under + (not got), over + got)
                if len(worst) < 5:
                    worst.append({"instance": inst.name, "x": x, "predicate": got, "reference": ref})
            if ref:
                if x < inst.lo:
                    reach = max(reach, inst.lo - x)
                elif x > inst.hi:
                    reach = max(reach, x - inst.hi)
        # band must be fully covered on the integers (a necessary condition for the
        # real-line coverage the witness proves)
        assert all(inst.holds_at(x) for x in range(inst.lo, inst.hi + 1)), \
            f"{inst.name}: piece fails on its own band at an integer point"
        spills.append(reach)
    return {
        "direction": direction,
        "instances": n_random,
        "points_checked": checked,
        "mismatch_under": under,
        "mismatch_over": over,
        "status": ("EXACT" if under == over == 0 else
                   "OVER-APPROXIMATES" if under == 0 else "UNDER-APPROXIMATES (DISQUALIFYING)"),
        "examples": worst,
        "spill_max": max(spills),
        "spill_mean": round(sum(spills) / len(spills), 2),
        "spill_ge_3": sum(1 for s in spills if s >= 3),
        "cap_min": min(caps), "cap_max": max(caps),
        "max_abs_coeff": max(coeffs),
    }


# ------------------------------------------------------------------- (d) idiom probes --


def _hints(inst: Instance, extra: Sequence[str] = ()) -> str:
    """The measured hint bag: squares at every vertex and both band endpoints.

    This is *generous* — DSV2 has to complete the square to find the vertex, and the
    templated idiom is handed it. That generosity is deliberate: the probe is a
    ceiling instrument, so a direction the oracle-hinted idiom cannot close is one
    the model certainly cannot close by copying.
    """
    vs = []
    for a in inst.atoms:
        vs.append(a.m)
        if isinstance(a, NestedAtom):
            vs.append(a.inner.m)
    terms = [f"sq_nonneg (x - {v})" if v >= 0 else f"sq_nonneg (x + {-v})" for v in dict.fromkeys(vs)]
    for v in (inst.lo, inst.hi):
        t = f"sq_nonneg (x - {v})" if v >= 0 else f"sq_nonneg (x + {-v})"
        if t not in terms:
            terms.append(t)
    return ", ".join(list(terms) + list(extra))


def _atom_render(a: Atom) -> str:
    return a.render()


def _measured_idiom(inst: Instance, bounds: Sequence[tuple[str, str]], hints: str) -> str:
    """The measured DSV2 shape, parameterized by which atoms get bounded and by what.

    `bounds` is a list of (radicand, bound) pairs. Structure copied verbatim from the
    modal bank proof: `sqrt_nonneg` for every atom, then one
    `apply Real.sqrt_le_iff.mpr / constructor / nlinarith / nlinarith [hints]` block
    per bounded atom, then a final `nlinarith [hints]`.
    """
    lines = ["by", "  intro x hx1 hx2"]
    for i, a in enumerate(inst.atoms, start=1):
        lines.append(f"  have hn{i} : 0 ≤ Real.sqrt ({_atom_render(a)}) := by apply Real.sqrt_nonneg")
    for i, (rad, bnd) in enumerate(bounds, start=1):
        lines += [
            f"  have hb{i} : Real.sqrt ({rad}) ≤ {bnd} := by",
            "    apply Real.sqrt_le_iff.mpr",
            "    constructor",
            "    · nlinarith",
            f"    · nlinarith [{hints}]",
        ]
    lines.append(f"  nlinarith [{hints}]")
    return "\n".join(lines)


def _sqsqrt_idiom(inst: Instance, hints: str) -> str:
    """The second measured signature (5/68 leaves): materialize `√U ^ 2 = U` and let
    `nlinarith` work with the square plus non-negativity."""
    lines = ["by", "  intro x hx1 hx2"]
    facts = []
    for i, a in enumerate(inst.atoms, start=1):
        r = _atom_render(a)
        lines += [
            f"  have hn{i} : 0 ≤ Real.sqrt ({r}) := by apply Real.sqrt_nonneg",
            f"  have hq{i} : Real.sqrt ({r}) ^ 2 = {r} := by rw [Real.sq_sqrt] <;> nlinarith",
        ]
        facts += [f"hn{i}", f"hq{i}"]
        if isinstance(a, NestedAtom):
            ir = a.inner.render()
            lines += [
                f"  have hin{i} : 0 ≤ Real.sqrt ({ir}) := by apply Real.sqrt_nonneg",
                f"  have hiq{i} : Real.sqrt ({ir}) ^ 2 = {ir} := by rw [Real.sq_sqrt] <;> nlinarith",
            ]
            facts += [f"hin{i}", f"hiq{i}"]
    lines.append(f"  nlinarith [{hints}, {', '.join(facts)}]")
    return "\n".join(lines)


def idiom_variants(inst: Instance) -> dict[str, str]:
    """Base idiom + the adaptations a competent prover tries next.

    Naming: `base` is the one-shot copy of the measured proof; every other key is an
    ADAPTATION, i.e. what the model would have to *think of*, not copy.
    """
    h = _hints(inst)
    out: dict[str, str] = {}
    first = inst.atoms[0]

    # base: one bound on the first atom at the cap read off the goal (t = A − C)
    out["base"] = _measured_idiom(inst, [(_atom_render(first), str(inst.t))], h)

    if len(inst.atoms) == 2:
        half_lo, half_hi = inst.t // 2, inst.t - inst.t // 2
        # adaptation 1: two have-steps, naive even split of the visible budget
        out["adapt_evensplit"] = _measured_idiom(
            inst, [(_atom_render(inst.atoms[0]), str(half_lo)),
                   (_atom_render(inst.atoms[1]), str(half_hi))], h)
        # adaptation 2: two have-steps at the generator's own split (oracle)
        out["adapt_oraclesplit"] = _measured_idiom(
            inst, [(_atom_render(a), str(a.cap)) for a in inst.atoms], h)
        # adaptation 3: both atoms bounded by the whole visible budget (sound but loose)
        out["adapt_bothfull"] = _measured_idiom(
            inst, [(_atom_render(a), str(inst.t)) for a in inst.atoms], h)
    elif isinstance(first, NestedAtom):
        # adaptation 1: bound the inner root by the visible outer cap, then the outer
        out["adapt_innerfull"] = _measured_idiom(
            inst, [(first.inner.render(), str(inst.t)),
                   (_atom_render(first), str(inst.t))], h)
        # adaptation 2: oracle inner cap, then the outer at the visible budget
        out["adapt_oracleinner"] = _measured_idiom(
            inst, [(first.inner.render(), str(first.inner.cap)),
                   (_atom_render(first), str(inst.t))], h)
    else:
        # single polynomial atom (v2 control, H2): a vertex/plateau hint is the
        # competent next try when the plain hint bag fails
        m, a = first.m, first.a
        far = _far(inst.lo, inst.hi, m)
        vx = f"(x - {m})" if m >= 0 else f"(x + {-m})"
        extra = (f"sq_nonneg ({vx} ^ 2 - {far * far})",
                 f"mul_nonneg (sub_nonneg.mpr hx1) (sub_nonneg.mpr hx2)")
        out["adapt_degreehint"] = _measured_idiom(
            inst, [(_atom_render(first), str(inst.t))], _hints(inst, extra))
        _ = a

    out["adapt_sqsqrt"] = _sqsqrt_idiom(inst, h)
    return out


# ------------------------------------------------------------------------- Lean glue --


def make_pool(workers: int):
    """Lazy seam: this module imports (and `--audit` runs) with no Lean toolchain."""
    from rlmath.lean.repl_pool import ReplPool

    return ReplPool(n_workers=workers)


def probe_sqrt_le_iff_order(pool) -> str:
    """Which conjunct does `Real.sqrt_le_iff` put first in THIS Mathlib?

    The generator witness is a term-mode anonymous constructor, so the order matters
    and must not be guessed. Probed with two throwaway proofs of a statement whose
    two conjuncts are discharged by *different* tactics.
    """
    from rlmath.core import leancode

    prop = "Real.sqrt (4 : ℝ) ≤ 2"
    codes = [leancode.proof_check(prop, "Real.sqrt_le_iff.mpr ⟨by norm_num, by norm_num⟩")]
    r = pool.check_many(codes, timeout_s=60.0)[0]
    if not (r.ok and r.sorries == 0):
        raise RuntimeError("Real.sqrt_le_iff.mpr ⟨_, _⟩ did not elaborate at all — API drift")
    # both conjuncts are numeric here, so disambiguate with a genuinely asymmetric one
    prop2 = "∀ x : ℝ, 0 ≤ x → x ≤ 1 → Real.sqrt (x ^ 2 + 1) ≤ 2"
    for order in ("nt", "tn"):
        proof = ("by\n  intro x hl hr\n  exact "
                 + _sqrt_le_iff(order, "by nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]"))
        rr = pool.check_many([leancode.proof_check(prop2, proof)], timeout_s=60.0)[0]
        if rr.ok and rr.sorries == 0:
            return order
    raise RuntimeError("neither argument order of Real.sqrt_le_iff worked")


def run_checks(pool, pairs: Sequence[tuple[str, str]], timeout_s: float) -> list[bool]:
    from rlmath.core import leancode

    codes = [leancode.proof_check(prop, proof) for prop, proof in pairs]
    return [r.ok and r.sorries == 0 for r in pool.check_many(codes, timeout_s=timeout_s)]


def run_battery(pool, props: Sequence[str]) -> list[list[str]]:
    """Per prop, the battery proofs that CLOSED it (empty list = survives)."""
    from rlmath.core import leancode
    from rlmath.families.validate import battery_proofs

    proofs = battery_proofs()
    out = []
    for prop in props:
        codes = [leancode.proof_check(prop, p) for p in proofs]
        res = pool.check_many(codes, timeout_s=BATTERY_TIMEOUT_S)
        out.append([p for p, r in zip(proofs, res) if r.ok and r.sorries == 0])
    return out


def calibration_leaves(n: int = 10) -> list[dict]:
    """Real measured case_tree leaves from the bank, with their measured pass@8.

    The idiom template is calibrated against THESE, not against regenerated ones:
    if the template does not close what DSV2 closed at 0.92, the template is wrong.
    """
    path = ROOT / "data" / "bank" / "family_leaf_calibration.jsonl"
    rows = [json.loads(line) for line in open(path)]
    ct_rows = [r for r in rows if "case_tree" in r.get("source_id", "")]
    ct_rows.sort(key=lambda r: r["statement_key"])
    return ct_rows[:n]


def _instance_from_prop(prop: str) -> Instance | None:
    """Recover the shipped-schema Instance behind a measured bank leaf.

    Regenerate-and-join by prop string (the F1 forensics lesson: the id suffix is a
    flat counter, not a generator index), so the idiom template gets the true vertex
    and cap rather than a re-derived guess.
    """
    for k in (2, 4, 8):
        for seed in (42, 2026, 9001):
            for idx in range(12):
                try:
                    variant, pieces = ct.layout(k, seed, idx)
                except ValueError:
                    continue
                for p in pieces:
                    if ct._leaf_prop(p, variant) == prop:
                        return build_instance("v2", variant, p.lo, p.hi, p.a, p.offset, p.slack)
    return None


# ------------------------------------------------------------------------------ main --


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--audit", action="store_true", help="(a) exactness audit only, no Lean")
    ap.add_argument("--lean", action="store_true", help="(a)-(d): witness, battery, idiom")
    ap.add_argument("--pilot", action="store_true", help="1 instance per direction")
    ap.add_argument("--n-probe", type=int, default=8, dest="n_probe")
    ap.add_argument("--n-random", type=int, default=300, dest="n_random")
    ap.add_argument("--skip-battery", action="store_true", dest="skip_battery")
    ap.add_argument("--directions", default=",".join(DIRECTIONS))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, dest="out_dir")
    args = ap.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    dirs = [d.strip() for d in args.directions.split(",") if d.strip()]
    n_probe = 1 if args.pilot else args.n_probe

    audit = {d: audit_direction(d, n_random=(20 if args.pilot else args.n_random)) for d in dirs}
    (args.out_dir / "audit.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False))
    print("## (a) exact-integer-predicate audit\n", file=sys.stderr)
    print("| direction | points | under | over | status | spill max/mean | cap range | max|coef| |",
          file=sys.stderr)
    print("|---|---|---|---|---|---|---|---|", file=sys.stderr)
    for d, a in audit.items():
        print(f"| {d} | {a['points_checked']} | {a['mismatch_under']} | {a['mismatch_over']} "
              f"| {a['status']} | {a['spill_max']}/{a['spill_mean']} "
              f"| {a['cap_min']}–{a['cap_max']} | {a['max_abs_coeff']} |", file=sys.stderr)
    disq = [d for d, a in audit.items() if a["mismatch_under"]]
    if disq:
        print(f"\nDISQUALIFIED (under-approximating predicate): {disq}", file=sys.stderr)
    if not args.lean:
        return 2 if disq else 0

    pool = make_pool(args.workers)
    report: dict = {"audit": audit}
    try:
        pool.warm()
        order = probe_sqrt_le_iff_order(pool)
        report["sqrt_le_iff_order"] = order
        print(f"\nReal.sqrt_le_iff conjunct order: {order}", file=sys.stderr)

        # ---- planted positive control: the battery MUST kill this
        if not args.skip_battery:
            killers = run_battery(pool, [PLANTED_CONTROL])[0]
            report["planted_control"] = {"prop": PLANTED_CONTROL, "killers": killers}
            if not killers:
                raise ControlFailed(
                    "the planted v1-shape control SURVIVED the full battery — the gate is "
                    "not measuring; every 'survives' verdict below is void")
            print(f"planted control killed by: {'; '.join(killers)}", file=sys.stderr)

        # ---- (d) calibration of the idiom template on measured leaves
        cal = []
        for row in calibration_leaves():
            inst = _instance_from_prop(row["prop"])
            cal.append({"statement_key": row["statement_key"], "prop": row["prop"],
                        "measured_pass8": row["pass_rate"], "recovered": inst is not None,
                        "instance": inst})
        pairs = [(c["prop"], idiom_variants(c["instance"])["base"]) for c in cal if c["instance"]]
        oks = run_checks(pool, pairs, IDIOM_TIMEOUT_S)
        it = iter(oks)
        for c in cal:
            c["base_idiom_closes"] = next(it) if c["instance"] else None
            c.pop("instance")
        n_ok = sum(1 for c in cal if c["base_idiom_closes"])
        report["idiom_calibration"] = {"leaves": len(cal), "recovered": len(pairs),
                                       "base_idiom_closes": n_ok, "rows": cal}
        print(f"\nidiom calibration on measured leaves: base closes {n_ok}/{len(pairs)} "
              f"(recovered {len(pairs)}/{len(cal)}); measured DSV2 pass@8 mean "
              f"{sum(c['measured_pass8'] for c in cal) / len(cal):.3f}", file=sys.stderr)

        # ---- (b)(c)(d) per direction
        report["directions"] = {}
        for d in dirs:
            insts = instances_for(d, n_probe)
            wit = run_checks(pool, [(i.prop(), i.witness(order)) for i in insts], WITNESS_TIMEOUT_S)
            bat = ([[] for _ in insts] if args.skip_battery
                   else run_battery(pool, [i.prop() for i in insts]))
            names: list[str] = []
            for i in insts:
                for kname in idiom_variants(i):
                    if kname not in names:
                        names.append(kname)
            idiom_pairs, index = [], []
            for i in insts:
                for kname, proof in idiom_variants(i).items():
                    idiom_pairs.append((i.prop(), proof))
                    index.append((i.name, kname))
            idiom_ok = run_checks(pool, idiom_pairs, IDIOM_TIMEOUT_S)
            per_inst: dict[str, dict] = {}
            for (iname, kname), ok in zip(index, idiom_ok):
                per_inst.setdefault(iname, {})[kname] = ok
            report["directions"][d] = {
                "instances": [{
                    "name": i.name, "prop": i.prop(), "witness": i.witness(order),
                    "knobs": i.knobs, "t": i.t, "variant": i.variant,
                    "witness_ok": w, "battery_killers": b,
                    "idiom": per_inst.get(i.name, {}),
                } for i, w, b in zip(insts, wit, bat)],
                "witness_ok": f"{sum(wit)}/{len(wit)}",
                "battery_survives": f"{sum(1 for b in bat if not b)}/{len(bat)}",
                "idiom_counts": {kname: sum(1 for i in insts if per_inst.get(i.name, {}).get(kname))
                                 for kname in names},
            }
            print(f"\n### {d}: witness {sum(wit)}/{len(wit)} | battery survives "
                  f"{sum(1 for b in bat if not b)}/{len(bat)} | idiom "
                  + ", ".join(f"{kname} {report['directions'][d]['idiom_counts'][kname]}/{len(insts)}"
                              for kname in names), file=sys.stderr)
            for i, b in zip(insts, bat):
                if b:
                    print(f"    KILLED {i.name}: {'; '.join(b)}", file=sys.stderr)
    finally:
        pool.close()
    (args.out_dir / "lean.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nwrote {args.out_dir / 'lean.json'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
