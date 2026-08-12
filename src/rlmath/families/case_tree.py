"""Family B — case trees (`case_tree`), FAMILIES.md.

A single quantified statement whose natural proof splits into k cases, each case
a distinct leaf lemma. The *split* (where the cases are) and the *per-case
claim* are what a policy has to invent; the assembly performs the split and
dispatches.

The shipped schema: **piecewise extremum over a real interval.**

    ∀ x : ℝ, L ≤ x → x ≤ R → C ≤ max (max (q₁ x) (q₂ x)) (max (q₃ x) (q₄ x))

with each `qᵢ` a quadratic written in *expanded* form. Every `qᵢ` dips below `C`
somewhere, so no single piece proves the goal; the pieces' super-level sets
`{qᵢ ≥ C}` cover `[L, R]`, so a k-way interval split does. The generator picks
band `[lᵢ, rᵢ]` and curvature/vertex/margin so that `qᵢ ≥ C` holds on band i with
exact-integer slack, and asserts at generation time that each piece is
*necessary* (there is a point in band i that no other piece covers) — otherwise
the "k-case" split would secretly be a j-case split for some j < k.

There is a dual variant (`min`, sampled per problem): convex pieces and an upper
bound `min (q₁ x) (…) ≤ C`. Same leaf schema, different Mathlib glue
(`min_le_of_left_le`/`min_le_of_right_le` vs `le_max_of_le_left/right`).

Why this shape and not the obvious alternatives — measured, not argued
---------------------------------------------------------------------
Battery probe (the seven tactics in validate.AUTOMATION_TACTICS, 25 s each,
Mathlib @ lean v4.34.0-rc1, 2026-08-11). "DEAD" = at least one tactic closed it:

    ∀ n : ℕ, 4 ≤ n → n ≤ 9 → 3 * n ≤ 30                 DEAD (omega, decide)
    ∀ n : ℕ, n % 5 = 3 → 5 ∣ n + 2                      DEAD (omega)
    ∀ n : ℕ, n < 12 → n * n ≤ 121                       DEAD (decide)
    ∀ n : ℕ, 4 ≤ n → n ≤ 9 → n * n ≤ 81                 DEAD (decide)
    ∀ x : ℝ, 2 ≤ x → x ≤ 6 → 3 ≤ 4 * x - 5              survives (see below)
    ∀ x : ℝ, 2 ≤ x → x ≤ 6 → 3 ≤ -2*x^2 + 16*x - 20     survives
    ∀ x : ℝ, 2 ≤ x → x ≤ 6 → 2*x^2 - 16*x + 26 ≤ 3      survives

So: **ℕ interval bands and ℕ/ℤ residue bands are not viable leaves.** `decide`
discharges any bounded-ℕ band — nonlinear ones included — through Mathlib's
bounded-∀ decidability instances for ℕ, and `omega` discharges linear-plus-`%`
divisibility outright, which kills candidate directions 1 and 2 in their natural
(ℕ) formulations. Bands over ℝ survive.

The battery is applied to the *closed* prop, and none of its tactics introduce
the leading `∀`/`→`, so even a linear real band survives it. That is a property
of the validator, not of the task, and this family declines to exploit it: run
the same battery **after `intro x hl hr`** and

    ∀ x : ℝ, 2 ≤ x → x ≤ 6 → 3 ≤ 4 * x - 5              DEAD (linarith)
    ∀ x : ℝ, 2 ≤ x → x ≤ 6 → 3 ≤ -2*x^2 + 16*x - 20     survives
    ∀ x : ℝ, 2 ≤ x → x ≤ 6 → 2*x^2 - 16*x + 26 ≤ 3      survives
    the k=3 goals of both variants                       survive

which is why the pieces are quadratic rather than affine: the leaves hold up
against a strictly stronger battery than the contract runs, so a later widening
of AUTOMATION_TACTICS (FAMILIES.md: "extending this list strengthens every
family retroactively") does not silently invalidate the bank.

Visibility (V6)
---------------
The pieces are necessarily visible — a piecewise function has to be *stated*.
What is hidden is everything a policy must produce: the k band endpoints and the
per-band claim. The pieces are in *expanded* form, so neither the vertex nor the
crossing points `qᵢ = C` (at `m ± sqrt(d/a)` — irrational for ~half the sampled
pieces, integral for the rest, and in neither case equal to both band endpoints,
because the vertex is offset from the band midpoint) can be read off the goal
without completing the square; the bands then have to be chosen to tile the
domain while each stays inside its own piece's super-level set. No leaf prop is
a substring of the goal — each carries band hypotheses that appear nowhere in it
— so this family sets `meta["visible_lemmas"] = []` and passes V6 with no
exemption at all.

Flatness in k
-------------
Every leaf is drawn from one schema with a fixed knob support
(WIDTHS × CURVATURES × VERTEX_OFFSETS × SLACKS), independent of k; k changes only
how many bands tile the domain. The single k-dependence is the band's *absolute
position*: the domain is `[-T/2, T/2]` with `T = Σ widths ≈ 7k`, so the constant
coefficient of a piece grows like `a·m²`. `leaf_stats()` reports the leaf-prop
length and coefficient-magnitude distributions per k so this is measured rather
than assumed (see research/family-case-tree.md for the numbers). The domain is
centered on 0 rather than starting at 0 specifically to halve that growth.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

from rlmath.core.types import DecompositionPlan, GoalSpec, LemmaSpec

from . import register
from .types import GeneratedProblem, LeafWitness

FAMILY = "case_tree"

# --- leaf schema knobs. Fixed support, identical at every k (flatness). -------
C_LEVEL = 3               # the bare side of the goal; nonzero so the goal never
                          # takes the `0 ≤ e` shape `positivity` attacks
WIDTHS = (6, 8)           # band width; even so band midpoints stay integral, and
                          # ≥ 6 so no piece can swallow a neighbour (see
                          # _repair_necessity: max spill past a band is
                          # 2·|offset| + ε ≤ 2.24, independent of width)
CURVATURES = (1, 2, 3)    # |leading coefficient| of the piece
VERTEX_OFFSETS = (-1, 0, 1)   # vertex displacement from the band midpoint
SLACKS = (0, 1)           # extra margin above the exact covering requirement
VARIANTS = ("max", "min")

_GLUE = {
    # variant -> (left injection, right injection) for the nested extremum
    "max": ("le_max_of_le_left", "le_max_of_le_right"),
    "min": ("min_le_of_left_le", "min_le_of_right_le"),
}

LEAF_PROOF = "by intro x hl hr; nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]"


@dataclass(frozen=True)
class Piece:
    """One case: band `[lo, hi]` and the quadratic assigned to it.

    Invariant (`covers_band`): the piece satisfies the goal's inequality
    everywhere on its own band, by exact integer arithmetic — the generator
    never relies on floating point to know its problems are true.
    """
    lo: int
    hi: int
    a: int          # curvature (positive; the variant decides the sign)
    m: int          # vertex abscissa
    d: int          # margin: the piece holds at x iff a*(x-m)^2 ≤ d
    width: int
    offset: int     # vertex offset from the band midpoint (a knob, kept for stats)
    slack: int      # margin above the exact requirement (a knob, kept for stats)
    repaired: bool = False   # tightened by the necessity repair (kept for stats)

    def holds_at(self, x: int) -> bool:
        """Does this piece satisfy the goal's inequality at x? (Both variants
        reduce to the same condition — see `coeffs`.)"""
        return self.a * (x - self.m) ** 2 <= self.d

    @property
    def covers_band(self) -> bool:
        far = max(abs(self.lo - self.m), abs(self.hi - self.m))
        return self.a * far**2 <= self.d

    def coeffs(self, variant: str) -> tuple[int, int, int]:
        """(x², x, 1) coefficients of the piece in expanded form.

        max: q(x) = C + d - a(x-m)²   — concave, `C ≤ q(x) ⟺ a(x-m)² ≤ d`
        min: q(x) = a(x-m)² + C - d   — convex,  `q(x) ≤ C ⟺ a(x-m)² ≤ d`
        """
        s = -1 if variant == "max" else 1
        return (s * self.a, -2 * s * self.a * self.m, s * (self.a * self.m**2 - self.d) + C_LEVEL)


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


def _num(n: int) -> str:
    """Numeral in *application* position. `le_or_gt x -5` parses as a
    subtraction; `le_or_gt x (-5)` is the split point we mean. Comparison
    positions (`-5 ≤ x`) need no parentheses, so only the assembly uses this."""
    return f"({n})" if n < 0 else str(n)


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


def _goal_prop(pieces: list[Piece], variant: str) -> str:
    terms = [_render_poly(*p.coeffs(variant)) for p in pieces]
    lo, hi = pieces[0].lo, pieces[-1].hi
    body = _chain(terms, variant)
    side = f"{C_LEVEL} ≤ {body}" if variant == "max" else f"{body} ≤ {C_LEVEL}"
    return f"∀ x : ℝ, {lo} ≤ x → x ≤ {hi} → {side}"


def _leaf_prop(p: Piece, variant: str) -> str:
    poly = _render_poly(*p.coeffs(variant))
    side = f"{C_LEVEL} ≤ {poly}" if variant == "max" else f"{poly} ≤ {C_LEVEL}"
    return f"∀ x : ℝ, {p.lo} ≤ x → x ≤ {p.hi} → {side}"


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


def _rng(k: int, seed: int, idx: int) -> random.Random:
    """Deterministic in (k, seed, idx) across processes and platforms —
    `random.Random(str)` and `hash()` are not, a sha256 digest is."""
    h = hashlib.sha256(f"{FAMILY}|{k}|{seed}|{idx}".encode()).hexdigest()[:16]
    return random.Random(int(h, 16))


def _sample_piece(rng: random.Random, lo: int, width: int) -> Piece:
    hi = lo + width
    a = rng.choice(CURVATURES)
    offset = rng.choice(VERTEX_OFFSETS)
    slack = rng.choice(SLACKS)
    m = lo + width // 2 + offset
    far = max(abs(lo - m), abs(hi - m))
    return Piece(lo=lo, hi=hi, a=a, m=m, d=a * far**2 + slack,
                 width=width, offset=offset, slack=slack)


def _tighten(p: Piece) -> Piece:
    """The minimal legal piece for a band: vertex at the midpoint, zero slack.
    Its super-level set is *exactly* its own band, so it spills into no
    neighbour. Curvature is preserved — only the spill is removed."""
    half = p.width // 2
    return Piece(lo=p.lo, hi=p.hi, a=p.a, m=p.lo + half, d=p.a * half**2,
                 width=p.width, offset=0, slack=0, repaired=True)


def _redundant(pieces: list[Piece], i: int) -> bool:
    """Is band i's piece unnecessary — is every integer point of band i already
    covered by some other piece? A redundant piece makes the goal a (k-1)-case
    problem wearing a k-case costume, so the generator repairs it away.

    (`not _redundant(·, i)` exhibits an integer point of band i that only piece
    i covers, which is a *sufficient* certificate of necessity — exact integer
    arithmetic, no interval algebra over irrational crossing points.)
    """
    p = pieces[i]
    return all(
        any(q.holds_at(x) for j, q in enumerate(pieces) if j != i)
        for x in range(p.lo, p.hi + 1)
    )


def _repair_necessity(pieces: list[Piece]) -> list[Piece]:
    """Safety net for necessity — under the shipped knobs it never fires.

    A piece's super-level set reaches past its own band by
    `|offset| + sqrt(far² + slack/a) − width/2 = 2·|offset| + ε`, with
    `ε < 0.24` and *no* dependence on the band width. Since `min(WIDTHS) = 6 >
    2 · 2.24`, two maximally greedy neighbours still leave the victim band's
    midpoint — an integer, because widths are even — uncovered. Necessity is
    therefore structural, which is what keeps the leaf-knob distribution
    *exactly* independent of k (`leaf_stats()["repaired_frac"] == 0.0`
    everywhere): a repair that fired at different rates per k would itself be a
    flatness leak, which is how this constraint was found (see the design log).

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


def _sample_pieces(k: int, rng: random.Random) -> list[Piece]:
    """k contiguous bands tiling a domain centered on 0, each with its piece."""
    widths = [rng.choice(WIDTHS) for _ in range(k)]
    lo = -(sum(widths) // 2)
    pieces: list[Piece] = []
    for w in widths:
        pieces.append(_sample_piece(rng, lo, w))
        lo += w
    return _repair_necessity(pieces)


# ---------------------------------------------------------------- generator --


def layout(k: int, seed: int, idx: int = 0) -> tuple[str, list[Piece]]:
    """The sampled case structure behind one problem: (variant, pieces).

    Exposed so tests and datasheets can check the geometric invariants against
    the same objects `build` uses, instead of re-deriving them from the RNG.
    """
    if k < 2:
        raise ValueError(f"case_tree needs k >= 2 (a 1-case split is not a case tree); got {k}")
    rng = _rng(k, seed, idx)
    variant = rng.choice(VARIANTS)
    return variant, _sample_pieces(k, rng)


def build(k: int, seed: int, idx: int = 0) -> GeneratedProblem:
    """One problem, a pure function of (k, seed, idx)."""
    variant, pieces = layout(k, seed, idx)

    bad = [i for i, p in enumerate(pieces) if not p.covers_band]
    if bad:  # unreachable by construction; a loud tripwire beats a false problem
        raise AssertionError(f"piece(s) {bad} do not cover their band — generator bug")

    names = [f"hb{i + 1}" for i in range(k)]
    goal = GoalSpec(id=f"{FAMILY}-k{k}-s{seed}-{idx}", prop=_goal_prop(pieces, variant), name="goal")
    lemmas = [LemmaSpec(name=n, prop=_leaf_prop(p, variant)) for n, p in zip(names, pieces)]
    plan = DecompositionPlan(lemmas=lemmas, assembly=_assembly(pieces, variant, names))
    witnesses = {l.name: LeafWitness(prop=l.prop, proof=LEAF_PROOF) for l in lemmas}

    coeffs = [c for p in pieces for c in p.coeffs(variant)]
    return GeneratedProblem(
        id=f"{FAMILY}-k{k}-s{seed}-{idx}",
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
            "domain": [pieces[0].lo, pieces[-1].hi],
            "bands": [[p.lo, p.hi] for p in pieces],
            "knobs": [{"width": p.width, "curvature": p.a, "offset": p.offset,
                       "slack": p.slack, "repaired": p.repaired} for p in pieces],
            "leaf_prop_lens": [len(l.prop) for l in lemmas],
            "max_abs_coeff": max(abs(c) for c in coeffs),
        },
    )


def generate(k: int, seed: int = 0, n: int = 1) -> list[GeneratedProblem]:
    """REGISTRY entry point: n problems, deterministic in (k, seed)."""
    return [build(k, seed, i) for i in range(n)]


def leaf_stats(problems: list[GeneratedProblem]) -> dict[int, dict]:
    """Per-k leaf-shape distribution — the flatness evidence for the datasheet
    (FAMILIES.md: "structural flatness … is checked at generation time")."""
    by_k: dict[int, list[GeneratedProblem]] = {}
    for p in problems:
        by_k.setdefault(p.k, []).append(p)

    out: dict[int, dict] = {}
    for k, ps in sorted(by_k.items()):
        lens = [n for p in ps for n in p.meta["leaf_prop_lens"]]
        knobs = {tuple(sorted(kb.items())) for p in ps for kb in p.meta["knobs"]}
        out[k] = {
            "problems": len(ps),
            "leaves": len(lens),
            "leaf_len_mean": round(sum(lens) / len(lens), 1),
            "leaf_len_min": min(lens),
            "leaf_len_max": max(lens),
            "goal_len_mean": round(sum(len(p.goal.prop) for p in ps) / len(ps), 1),
            "max_abs_coeff": max(p.meta["max_abs_coeff"] for p in ps),
            "distinct_knob_tuples": len(knobs),
            # fraction of leaves whose knobs were tightened by the necessity
            # repair — the one way the leaf distribution could drift with k
            "repaired_frac": round(
                sum(kb["repaired"] for p in ps for kb in p.meta["knobs"]) / len(lens), 3),
            "knob_support_ok": all(
                kb["width"] in WIDTHS and kb["curvature"] in CURVATURES
                and kb["offset"] in VERTEX_OFFSETS and kb["slack"] in SLACKS
                for p in ps for kb in p.meta["knobs"]
            ),
        }
    return out


register(FAMILY, generate)
