"""Mutation breeding of in-band statements — corridor-widening source 2 (FAMILIES.md).

FAMILIES.md, "Corridor widening (v2 leaf sources)": *(2) mutation breeding —
perturb constants/exponents/bounds of known in-band statements and re-measure
every mutant's pass@8 (mutants inherit the corridor's neighborhood, never
membership; measurement is mandatory).*

This module is the "perturb" half. It takes one bank row's `prop` (a closed
Lean 4 proposition, already normalized by `core.types.normalize_statement`) and
produces structural mutants that differ from the parent **only in numeric
literal slots**. It never decides whether a mutant is in band; that is
`scripts/build_bank.py`'s measurement, and nothing here may be read as evidence
about difficulty.

What may change, and what may not
---------------------------------
Mutable: numeric literals in three positions — coefficient/offset constants
(`const_jitter`), exponents (`exponent_delta`), and constants adjacent to a
relation, i.e. bounds and equation right-hand sides (`bound_shift`).

Frozen in v1, deliberately:

* **Binder structure.** The ∀-telescope — binder names, count, grouping, types —
  is what makes a statement a member of its shape class. Adding, dropping, or
  retyping a hypothesis produces a *different problem*, not the same problem
  with different numbers, and the whole justification for breeding
  ("mutants inherit the corridor's *neighborhood*") evaporates: an inherited
  difficulty neighborhood is only credible when the mutant is the parent
  statement with different constants. Constants *inside* a binder's type
  (`(habc : a + b + c = 1)`) are fair game — that is a bound, not structure.
* **Function identity.** `Real.sqrt` → `Real.log` swaps the Mathlib API surface
  the frozen leaf must know. Leaf competence is per-API and lumpy (the 2026-08-12
  bake-off measured exactly this kind of discontinuity between operating points),
  so a symbol swap is a jump to a different difficulty distribution, not a jitter.
* **Direction of inequalities.** Flipping `≤`↔`≥` (or `<`↔`>`) on a competition
  statement nearly always yields a *false* statement. A false statement is not a
  harder statement — it is an unprovable one; it burns a pass@8 measurement to
  learn a 0 that says nothing about the corridor. The rare survivors of a flip
  are usually trivially true, i.e. out of the band on the other side. Both
  outcomes leave the neighborhood.

Enforcement is structural, not a checklist: every mutation replaces one numeral
token with another numeral token, so `skeleton()` (the prop with every numeral
blanked) is invariant. `assert_structure_preserved` re-checks that invariant on
every emitted mutant and raises if it is violated — a tokenizer bug must be loud
(the ../rl silent-format-failure lesson, PHASE0_NOTES 2026-08-11).

Truth is *not* preserved, and that is fine
------------------------------------------
Jittering a constant routinely turns a true inequality false. That is precisely
why FAMILIES.md makes re-measurement mandatory and why membership is never
inherited: false mutants measure `pass_rate == 0.0` and fall out of the
[0.25, 0.9] band filter (DIRECTION.md §5.4). The cost is GPU spent on mutants
that were never going to land, so every emitted row records its `mutation_ops`:
which op kinds actually breed in-band is an empirical question the
re-measurement answers, and the rows make the answer computable rather than
arguable.

Fresh keys, independent split membership
----------------------------------------
A mutant's `statement_key` is `core.types.statement_key(mutant_prop)` — a fresh
sha256 over different text, so `families.leaf_split.leaf_split` assigns its
train/eval pool independently of the parent's, exactly as that module's
docstring specifies ("mutation-bred variants get their own key and therefore
their own independently-drawn membership"). Callers that need parent/child pool
coherence must filter on the recorded splits; see
`scripts/breed_mutants.py --coherent-split` and the flag it carries.

Determinism: `mutants(prop, seed=s)` is a pure function of
`(normalize_statement(prop), seed)` — the RNG is seeded from a sha256 of both,
never from `hash()`, so it is stable across processes and machines. The output
is also *prefix-stable*: `mutants(p, seed=s, n=2)` is the first two elements of
`mutants(p, seed=s, n=5)`.
"""
from __future__ import annotations

import hashlib
import math
import random
import re
from dataclasses import dataclass

from rlmath.core.types import normalize_statement, statement_key

# --- knobs, with their reasons ------------------------------------------------

# Magnitude-preserving jitter: a new constant stays within a factor of two of the
# old one. Wider than that and the term's contribution changes order of magnitude,
# which is a different problem regime rather than a neighbor (FAMILIES.md
# "inheritance of neighborhood").
MAG_LO, MAG_HI = 0.5, 2.0
# Two candidate generators, both clipped to [m/2, 2m]. Additive deltas give real
# variety for small constants (2 → 1, 3, 4), where a multiplicative step is too
# coarse; multipliers do the same for large ones (243 → 122, 182, 365, 486),
# where ±3 is not a perturbation at all.
ADDITIVE_DELTAS = (-3, -2, -1, 1, 2, 3)
MULTIPLIERS = (0.5, 0.75, 1.25, 1.5, 2.0)

# Exponents move by ±1/±2 only. Floor 2: `x^1` and `x^0` collapse the term
# (`x^1 = x`, `x^0 = 1`) — that is a shape change, not a magnitude change.
# Ceiling 12: past that, a product of two such factors is a degree-20+ polynomial
# inequality, a different regime for both the leaf prover and the V0/V5 battery.
EXPONENT_DELTAS = (-2, -1, 1, 2)
MIN_EXPONENT, MAX_EXPONENT = 2, 12

OP_KINDS = ("const_jitter", "exponent_delta", "bound_shift")
_OP_KIND = {"const": "const_jitter", "exponent": "exponent_delta", "bound": "bound_shift"}

# Numerals that are arguments of these heads are **never** touched. They are
# type-level or index-set sizes: `Finset.range 100` sets how many summands a big
# operator has, i.e. it is a *size* parameter. Size is the k-axis the families
# own (DIRECTION.md §5.4a: per-node difficulty flat in k); breeding across it
# would confound corridor-widening with the size axis, and `Fin n` / `ZMod n`
# numerals are part of the *type*, so changing them is a binder-structure change
# wearing a numeral costume.
GUARD_HEADS = frozenset({
    "Fin", "ZMod", "Matrix", "EuclideanSpace",
    "Finset.range", "Finset.Icc", "Finset.Ico", "Finset.Ioc", "Finset.Ioo",
    "Finset.Iic", "Finset.Iio",
    "Set.Icc", "Set.Ico", "Set.Ioc", "Set.Ioo", "Set.Iic", "Set.Iio",
})

# --- lexical layer ------------------------------------------------------------

# A numeral is a maximal digit run that is not part of an identifier and not a
# field/namespace projection. The negative lookbehind on `\w` is what keeps `h1`,
# `a₁`, `x2` and `Nat.choose` intact; the lookbehind/ahead on `.` keeps `Real.sqrt`
# and `p.2` intact while still matching `0.5` as ONE token (so a decimal is never
# split into two mutable integers).
NUMERAL = re.compile(r"(?<![\w.'])(\d+(?:\.\d+)?)(?![\w.'])")

# Identifier: a word char that is not a digit, then word chars / . ' ! ? — this
# matches `x`, `ℝ`, `Real.sqrt`, `Nat.choose`, `h1`, and Lean's `foo'`.
IDENTIFIER = re.compile(r"[^\W\d][\w.'!?]*")
_IDENT_END = re.compile(r"[^\W\d][\w.'!?]*$")
_NUM_END = re.compile(r"\d+(?:\.\d+)?$")

# Relations, connectives and quantifiers, longest-match first. `=>` must precede
# `=` and `>` or a lambda arrow lexes as two relation tokens.
_REL_ALTS = (
    "=>", "↔", "→", "←", "≤", "≥", "≠", "≡", "∣", "∈", "∉", "⊆", "⊂",
    "∧", "∨", "¬", "∀", "∃", "<", ">", "=",
)
RELATION = re.compile("|".join(re.escape(t) for t in _REL_ALTS))

# Characters that put a numeral in "bound" position when they sit next to it
# (modulo spaces, and a wrapping paren or unary minus).
_REL_ADJACENT = frozenset({"≤", "≥", "<", ">", "=", "≠", "≡"})

_OPEN, _CLOSE = "([{⦃⟨", ")]}⦄⟩"


def skeleton(prop: str) -> str:
    """The prop with every numeral blanked — the v1 structure-preservation invariant.

    Two props with equal skeletons are literally the same string outside numeral
    slots, so binders, function symbols, relation symbols and term shape are all
    identical by construction. Every mutant this module emits satisfies
    `skeleton(mutant) == skeleton(parent)`.
    """
    return NUMERAL.sub("#", normalize_statement(prop))


def relation_tokens(prop: str) -> tuple[str, ...]:
    """In-order relation/connective/quantifier tokens. Invariant under mutation —
    in particular no `≤` ever becomes a `≥` (see module docstring)."""
    return tuple(RELATION.findall(normalize_statement(prop)))


def identifiers(prop: str) -> tuple[str, ...]:
    """In-order identifier tokens (`Real.sqrt`, `x`, `ℝ`, `h1`). Invariant under
    mutation: function identity is frozen in v1."""
    return tuple(IDENTIFIER.findall(normalize_statement(prop)))


def split_forall(prop: str) -> tuple[str, str] | None:
    """`∀ <telescope>, <body>` split at the top-level comma, bracket-depth aware.

    Depth-aware because binder types contain commas (`(ha : ∀ i, P i)`), which a
    `[^,]*` regex would cut in the wrong place.
    """
    s = normalize_statement(prop)
    if not s.startswith("∀"):
        return None
    depth = 0
    for i, c in enumerate(s):
        if c in _OPEN:
            depth += 1
        elif c in _CLOSE:
            depth -= 1
            if depth < 0:
                return None
        elif c == "," and depth == 0:
            return s[1:i].strip(), s[i + 1 :].strip()
    return None


def _binder_groups(telescope: str) -> list[str]:
    groups, buf, depth, chunk = [], [], 0, []
    for c in telescope:
        if depth == 0 and c in _OPEN:
            if "".join(buf).strip():
                groups.append("".join(buf).strip())
            buf = []
            depth += 1
            chunk = [c]
        elif depth:
            chunk.append(c)
            if c in _OPEN:
                depth += 1
            elif c in _CLOSE:
                depth -= 1
                if depth == 0:
                    groups.append("".join(chunk))
        else:
            buf.append(c)
    if "".join(buf).strip():
        groups.append("".join(buf).strip())
    return groups


def binder_names(prop: str) -> tuple[str, ...]:
    """Names bound by the leading ∀-telescope, in order. Invariant under mutation.

    Only the leading telescope: nested binders inside a hypothesis type are
    covered by `skeleton()` (they are part of the frozen text).
    """
    parts = split_forall(prop)
    if parts is None:
        return ()
    names: list[str] = []
    for group in _binder_groups(parts[0]):
        inner = group.strip()
        if inner[:1] in _OPEN:
            inner = inner[1:-1]
        lhs = inner.split(":", 1)[0] if ":" in inner else inner
        names.extend(lhs.split())
    return tuple(names)


# --- site classification ------------------------------------------------------

@dataclass(frozen=True)
class Site:
    """One numeral occurrence in a prop, classified."""

    start: int
    end: int
    text: str
    kind: str            # "const" | "exponent" | "bound"
    mutable: bool
    reason: str = ""     # why not, when mutable is False

    @property
    def op_kind(self) -> str:
        return _OP_KIND[self.kind]


def _prev_nonspace(s: str, i: int) -> str:
    j = i - 1
    while j >= 0 and s[j] == " ":
        j -= 1
    return s[j] if j >= 0 else ""


def _next_nonspace(s: str, i: int) -> str:
    j = i
    while j < len(s) and s[j] == " ":
        j += 1
    return s[j] if j < len(s) else ""


# A numeral welded to an arithmetic operator is a *term* inside a larger
# expression, not the bound itself: in `≥ (1 + a) * (1 + b)` the `1`s are
# coefficients that merely happen to sit near the `≥`. `/` is excluded on
# purpose — `≤ 243/8` is one rational bound, and both its digits are part of it.
_ARITH = frozenset("+-*^")


def _rel_before(s: str, start: int, end: int) -> bool:
    """Is this numeral the whole right operand of a relation? Skips spaces, one
    unary minus and any opening parens: `≥ 10`, `≤ (243)`, `> -1`."""
    if _next_nonspace(s, end) in _ARITH:
        return False
    j = start - 1
    while j >= 0 and (s[j] in " (-"):
        j -= 1
    return j >= 0 and s[j] in _REL_ADJACENT


def _rel_after(s: str, start: int, end: int) -> bool:
    """Is this numeral the whole left operand of a relation? `0 < x`, `3 ≤ x`."""
    if _prev_nonspace(s, start) in _ARITH:
        return False
    j = end
    while j < len(s) and (s[j] in " )"):
        j += 1
    return j < len(s) and s[j] in _REL_ADJACENT


def _guard_head(s: str, start: int) -> str | None:
    """Nearest applied head if this numeral is one of its space-separated
    arguments (up to two args deep, so `Finset.Icc 1 5` guards both numerals).

    Only *whitespace* application continues the walk; hitting an operator or a
    bracket ends it, so `a + 3` and `x ^ 2` are never mistaken for arguments.
    """
    i = start
    for _ in range(3):
        j = i
        while j > 0 and s[j - 1] == " ":
            j -= 1
        if j == i:
            return None
        m = _IDENT_END.search(s[:j])
        if m is not None:
            tok = m.group(0)
            if tok in GUARD_HEADS:
                return tok
            i = m.start()
            continue
        m2 = _NUM_END.search(s[:j])
        if m2 is None:
            return None
        i = m2.start()
    return None


def numeral_sites(prop: str) -> list[Site]:
    """Every numeral in `prop`, classified and marked mutable or not.

    Offsets are into `normalize_statement(prop)` — which is what bank rows already
    store, so for a bank row the offsets index the row's own `prop` string.
    """
    s = normalize_statement(prop)
    sites: list[Site] = []
    for m in NUMERAL.finditer(s):
        text = m.group(1)
        if _prev_nonspace(s, m.start()) == "^":
            kind = "exponent"
        elif _rel_before(s, m.start(), m.end()) or _rel_after(s, m.start(), m.end()):
            kind = "bound"
        else:
            kind = "const"
        head = _guard_head(s, m.start())
        if head is not None:
            sites.append(Site(m.start(), m.end(), text, kind, False,
                              f"argument of {head} (index-set/type-level size)"))
        elif "." in text:
            sites.append(Site(m.start(), m.end(), text, kind, False,
                              "decimal literal (v1 mutates integer literals only)"))
        else:
            sites.append(Site(m.start(), m.end(), text, kind, True))
    return sites


# --- candidate values ---------------------------------------------------------

def _int_candidates(m: int) -> list[int]:
    """Magnitude-preserving neighbours of a positive integer: within [m/2, 2m],
    never 0 (a zero coefficient deletes a term — a shape change, not a jitter)."""
    lo = max(1, math.ceil(m * MAG_LO))
    hi = max(lo, math.floor(m * MAG_HI))
    cands = {m + d for d in ADDITIVE_DELTAS}
    cands |= {round(m * r) for r in MULTIPLIERS}
    return sorted(c for c in cands if lo <= c <= hi and c != m)


def _exp_candidates(m: int) -> list[int]:
    return sorted({
        c for c in (m + d for d in EXPONENT_DELTAS)
        if MIN_EXPONENT <= c <= min(m + max(EXPONENT_DELTAS), MAX_EXPONENT) and c != m
    })


def site_candidates(site: Site) -> list[str]:
    """Replacement numerals for a site, in ascending order (deterministic)."""
    if not site.mutable:
        return []
    v = int(site.text)
    if site.kind == "exponent":
        return [str(c) for c in _exp_candidates(v)]
    if v == 0:
        # A zero bound is a positivity/nonnegativity threshold; nudging it up is a
        # genuine bound shift (and strengthens a hypothesis, which preserves the
        # validity of an implication). A zero *coefficient* means the term is not
        # there — conjuring one is a shape change, so const sites stay put.
        return ["1", "2"] if site.kind == "bound" else []
    return [str(c) for c in _int_candidates(v)]


# --- mutations ----------------------------------------------------------------

@dataclass(frozen=True)
class MutationOp:
    """One numeral substitution. `pos` indexes the normalized parent prop, so
    (parent, ops) replays to the mutant exactly — see `apply_ops`."""

    kind: str
    pos: int
    old: str
    new: str

    def as_dict(self) -> dict:
        return {"kind": self.kind, "pos": self.pos, "old": self.old, "new": self.new}

    @classmethod
    def from_dict(cls, d: dict) -> "MutationOp":
        return cls(kind=d["kind"], pos=int(d["pos"]), old=d["old"], new=d["new"])


@dataclass(frozen=True)
class Mutant:
    prop: str
    parent_prop: str
    ops: tuple[MutationOp, ...]

    @property
    def statement_key(self) -> str:
        """Fresh key over fresh text -> independent leaf_split membership
        (families/leaf_split.py docstring)."""
        return statement_key(self.prop)

    @property
    def parent_key(self) -> str:
        return statement_key(self.parent_prop)

    @property
    def source_id(self) -> str:
        return f"mutant:{self.parent_key}"

    def as_row(self) -> dict:
        return {
            "statement_key": self.statement_key,
            "prop": self.prop,
            "source_id": self.source_id,
            "parent_key": self.parent_key,
            "mutation_ops": [o.as_dict() for o in self.ops],
        }


def apply_ops(prop: str, ops) -> str:
    """Replay `ops` against `prop`. Raises if an op does not match the parent text
    at its recorded position — provenance that cannot be replayed is not provenance."""
    s = normalize_statement(prop)
    items = sorted((MutationOp.from_dict(o) if isinstance(o, dict) else o for o in ops),
                   key=lambda o: o.pos, reverse=True)
    seen: set[int] = set()
    for op in items:
        if op.pos in seen:
            raise ValueError(f"two ops at the same position {op.pos}")
        seen.add(op.pos)
        end = op.pos + len(op.old)
        if s[op.pos : end] != op.old:
            raise ValueError(f"op {op} does not match parent text {s[op.pos:end]!r}")
        s = s[: op.pos] + op.new + s[end:]
    return s


def assert_structure_preserved(parent: str, mutant: str) -> None:
    """The v1 contract, checked rather than trusted (raises ValueError).

    Skeleton equality is the whole guarantee: identical text outside numeral
    slots => identical binders, identical function symbols, identical relation
    directions. The finer checks are listed separately so a violation names the
    thing that broke.
    """
    if skeleton(parent) != skeleton(mutant):
        raise ValueError("mutation changed non-numeral structure")
    if binder_names(parent) != binder_names(mutant):
        raise ValueError("mutation changed binder names")
    if identifiers(parent) != identifiers(mutant):
        raise ValueError("mutation changed function/variable identity")
    if relation_tokens(parent) != relation_tokens(mutant):
        raise ValueError("mutation changed relation/connective tokens")


def _rng(prop: str, seed: int) -> random.Random:
    """Seeded from sha256(seed, normalized prop) — never `hash()`, which is
    salted per process and would make "deterministic in (prop, seed)" false."""
    h = hashlib.sha256(f"{seed}\x00{prop}".encode()).digest()
    return random.Random(int.from_bytes(h[:16], "big"))


def mutants(
    prop: str,
    *,
    seed: int,
    n: int = 4,
    max_ops: int = 2,
    pair_prob: float = 0.35,
) -> list[Mutant]:
    """Up to `n` distinct mutants of `prop`, deterministic in `(prop, seed)`.

    `max_ops` caps how many numerals one mutant may change: 1 or 2 in v1, because
    each additional simultaneous perturbation moves the mutant further from the
    parent's difficulty neighborhood, and the neighborhood is the entire reason
    this source is cheaper than a wide sweep (FAMILIES.md corridor widening).

    Prefix-stable in `n` (see module docstring), so a caller that raises `n` on a
    re-run re-derives the same first mutants rather than a fresh population.
    """
    if max_ops < 1:
        raise ValueError("max_ops must be >= 1")
    base = normalize_statement(prop)
    if not base:
        raise ValueError("empty prop")
    sites = [s for s in numeral_sites(base) if s.mutable]
    singles = [(s, v) for s in sites for v in site_candidates(s)]
    if not singles or n <= 0:
        return []
    rng = _rng(base, seed)
    rng.shuffle(singles)

    out: list[Mutant] = []
    seen = {base}
    for s1, v1 in singles:
        if len(out) >= n:
            break
        ops = [MutationOp(s1.op_kind, s1.start, s1.text, v1)]
        if max_ops >= 2 and rng.random() < pair_prob:
            others = [(s, v) for (s, v) in singles if s.start != s1.start]
            if others:
                s2, v2 = others[rng.randrange(len(others))]
                ops.append(MutationOp(s2.op_kind, s2.start, s2.text, v2))
        text = apply_ops(base, ops)
        if text in seen:
            continue
        assert_structure_preserved(base, text)
        seen.add(text)
        out.append(Mutant(prop=text, parent_prop=base, ops=tuple(ops)))
    return out
