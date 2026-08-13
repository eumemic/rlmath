"""Family B (case trees) — offline generator tests + a live integration check.

Offline tests pin the properties the generator claims by *construction*, so a
regression shows up without a Lean toolchain: determinism, exact-integer
coverage of every band, necessity of every case (no k-case costume over a
(k-1)-case problem), wire-format round-tripping, V6 hiddenness, and per-node
flatness of the leaf schema in k. The Lean-dependent claims (elaboration,
witness proofs, plan check, battery resistance) are the integration test's job
and the measured tables in research/family-case-tree.md and
research/ct-hardening-survey-{a,b}.md.

Since 2026-08-13 the family carries a **hardening ladder**: `generate(preset=)`
selects a piece function (`case_tree.RUNGS`). Two things dominate this file:

* the shipped `v2` rung must stay **byte-identical** — the ladder is only safe
  because the control is pinned, exactly as bridge_chain's retune was
  (`test_default_preset_is_v2_and_its_output_is_byte_identical`);
* every invariant is checked **per rung**, and the necessity machinery must use
  each rung's *own* exact predicate. `test_necessity_uses_the_rungs_own_predicate`
  is the guard for that: it exhibits a case where v2's predicate gives the wrong
  necessity answer, in the unsound direction.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import sys

import pytest

from rlmath.core.plan_format import MAX_LEMMAS_HARD, PlanFormatError, parse_plan
from rlmath.core.types import VerifyResult, normalize_statement
from rlmath.families import REGISTRY, validate_problem
from rlmath.families import case_tree as ct
from rlmath.families.validate import AUTOMATION_TACTICS
from rlmath.harness.composer import check_names
from rlmath.sanitize import scan_source

KS = (2, 3, 4, 8, 16)
RUNGS = tuple(ct.RUNGS)

# What each rung's leaf and witness must look like. Kept as data so a new rung
# cannot be added without saying, in one place, what it renders and which lemma
# its witness turns on — the two things that make it a *different* obligation.
SHAPES = {
    # `markers`: substring -> occurrences per PIECE (the floor wraps the whole
    # product, so `⌊` is once per piece while `Real.sqrt (` is once per atom).
    "v2":           dict(markers={"Real.sqrt (": 1}, atoms=1, lemma="Real.sqrt_le_iff.mpr"),
    "r1_recip":     dict(markers={" / (": 1}, atoms=1, lemma="le_div_iff₀"),
    "r2_prod":      dict(markers={"Real.sqrt (": 2}, atoms=2, lemma="mul_le_mul"),
    "r2_sum":       dict(markers={"Real.sqrt (": 2}, atoms=2, lemma="Real.sqrt_le_iff.mpr"),
    "r3_floor":     dict(markers={"Real.sqrt (": 1, "⌊": 1}, atoms=1, lemma="Int.floor_lt.mpr"),
    "r4_floorprod": dict(markers={"Real.sqrt (": 2, "⌊": 1}, atoms=2, lemma="Real.sqrt_mul"),
}


def _problems(k: int, seed: int = 3, n: int = 2, preset: str = "v2"):
    return ct.generate(k, seed=seed, n=n, preset=preset)


def _fingerprint(cells, preset="v2") -> str:
    """Every byte a consumer sees: ids, declaration names, props, assembly,
    witnesses. Deliberately NOT meta — meta may grow; the artifact may not."""
    blob = json.dumps(
        [[{"id": p.id, "goal_name": p.goal.name, "goal": p.goal.prop,
           "lemmas": [(l.name, l.prop) for l in p.oracle_plan.lemmas],
           "asm": p.oracle_plan.assembly,
           "wit": {n: w.proof for n, w in p.witnesses.items()}}
          for p in ct.generate(k, seed=s, n=2, preset=preset)]
         for k, s in cells],
        ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


GOLDEN_CELLS = ((2, 0), (3, 42), (4, 7), (8, 1), (16, 5), (32, 9), (64, 0), (128, 0))
GOLDEN_V2 = "fa6041bc0f2336f33a4fe53d60a429a9c64ac3f702eefc4433049472bdd952df"


# --------------------------------------------------------------- registration


def test_registered_under_case_tree():
    assert REGISTRY["case_tree"] is ct.generate


def test_default_preset_is_v2_and_its_output_is_byte_identical():
    """The ladder's safety pin (F11, research/case-tree-hardening.md §1).

    `v2` is the *control* the four candidate rungs are measured against and the
    schema behind every existing case_tree artifact — the 68 measured rows in
    data/bank/family_leaf_calibration.jsonl, data/families/case_tree/k*.jsonl,
    the datasheet. If a byte moves, the 0.923 anchor stops describing what the
    generator emits and the whole comparison is void.

    The hash covers ids, declaration names, goal props, leaf props, the assembly
    and every witness, over eight (k, seed) cells spanning k = 2 … 128. It was
    taken from the pre-ladder generator; do not "update" it to make a change
    pass.
    """
    assert ct.DEFAULT_PRESET == "v2"
    assert _fingerprint(GOLDEN_CELLS) == GOLDEN_V2
    assert ct.generate(4, seed=7, n=1)[0].id == "case_tree-k4-s7-0"
    assert ct.generate(4, seed=7, n=1)[0].goal.name == "goal"


def test_generate_is_deterministic_in_k_and_seed():
    for rung in RUNGS:
        a = ct.generate(4, seed=17, n=3, preset=rung)
        b = ct.generate(4, seed=17, n=3, preset=rung)
        assert [p.goal.prop for p in a] == [p.goal.prop for p in b]
        assert [[l.prop for l in p.oracle_plan.lemmas] for p in a] == \
               [[l.prop for l in p.oracle_plan.lemmas] for p in b]
        assert [p.oracle_plan.assembly for p in a] == [p.oracle_plan.assembly for p in b]


def test_determinism_is_stable_across_processes():
    """A golden value, not just self-consistency within one interpreter: the RNG
    is seeded from a sha256 digest precisely because `hash()` and
    `random.Random(str)` are not stable across runs, and a dataset regenerated
    next month must be the same dataset."""
    p = ct.build(3, 42, 0)
    assert p.goal.prop == (
        "∀ x : ℝ, -9 ≤ x → x ≤ 9 → 3 ≤ max (9 - Real.sqrt (3 * x ^ 2 + 36 * x + 117)) "
        "(max (8 - Real.sqrt (2 * x ^ 2 + 6)) (9 - Real.sqrt (2 * x ^ 2 - 28 * x + 101)))"
    )
    assert p.oracle_plan.lemmas[1].prop == \
        "∀ x : ℝ, -3 ≤ x → x ≤ 3 → 3 ≤ 8 - Real.sqrt (2 * x ^ 2 + 6)"


def test_every_rung_is_deterministic_across_processes():
    """PYTHONHASHSEED randomisation is per-process, so a fresh interpreter is
    the only place a `hash()`/set-ordering leak into the RNG stream can show
    up — and the ladder added set-ish code (`extra_cells`, the extras draw)
    where one could hide."""
    code = (
        "import json, hashlib;"
        "from rlmath.families import case_tree as ct;"
        "print(json.dumps({r: [p.goal.prop for k in (2, 5) "
        "for p in ct.generate(k, seed=11, n=2, preset=r)] for r in ct.RUNGS}))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True).stdout
    other = json.loads(out)
    here = {r: [p.goal.prop for k in (2, 5) for p in ct.generate(k, seed=11, n=2, preset=r)]
            for r in ct.RUNGS}
    assert other == here


def test_distinct_seeds_give_distinct_problems():
    assert ct.build(4, 1).goal.prop != ct.build(4, 2).goal.prop


def test_generate_n_gives_n_distinct_ids():
    for rung in RUNGS:
        ps = ct.generate(4, seed=0, n=5, preset=rung)
        assert len({p.id for p in ps}) == 5
        assert len({p.goal.prop for p in ps}) == 5


def test_k_below_two_is_rejected():
    for k in (-1, 0, 1):
        with pytest.raises(ValueError, match="k >= 2"):
            ct.build(k, 0)


# ---------------------------------------------------------------- the ladder


def test_unknown_rung_is_rejected():
    for bad in ("v3", "r2", "", "R2_SUM", "e3_lowdeg"):
        with pytest.raises(ValueError, match="unknown case_tree preset"):
            ct.generate(4, seed=0, n=1, preset=bad)
    with pytest.raises(ValueError, match="unknown case_tree preset"):
        ct.layout(4, 0, 0, preset="nope")


def test_every_rung_is_declared_and_named_legally():
    for name, rung in ct.RUNGS.items():
        assert rung.name == name
        assert re.fullmatch(r"[a-z_][a-z0-9_]*", name), name
        assert rung.rationale and rung.schema_id
        assert name in SHAPES, "a new rung must declare its shape in this test's table"
    assert set(ct.RUNGS) == set(SHAPES)


@pytest.mark.parametrize("rung", RUNGS)
def test_non_default_rungs_tag_their_id_and_declaration_name(rung):
    """Two rungs must be materializable side by side without colliding — ids
    key the bank, declaration names key the composed artifact."""
    p = ct.build(4, 7, 0, preset=rung)
    if rung == ct.DEFAULT_PRESET:
        assert p.id == "case_tree-k4-s7-0" and p.goal.name == "goal"
    else:
        assert p.id == f"case_tree-{rung}-k4-s7-0"
        assert p.goal.name == f"goal_{rung}"
    assert p.meta["preset"] == rung
    assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", p.goal.name)


def test_rungs_do_not_collide_on_ids_or_statements():
    ids, props = set(), set()
    for rung in RUNGS:
        for p in ct.generate(4, seed=7, n=3, preset=rung):
            assert p.id not in ids
            ids.add(p.id)
            assert p.goal.prop not in props, f"{rung} re-emits another rung's goal"
            props.add(p.goal.prop)


@pytest.mark.parametrize("rung", RUNGS)
def test_rung_seed_stream_is_disjoint_from_the_default(rung):
    """Non-default rungs tag the seed string, so a rung is not just v2's knob
    draw wearing a different piece function — otherwise two rungs would share
    band tilings and the ladder's cells would be correlated."""
    mine = [p.meta["bands"] for p in ct.generate(8, seed=5, n=4, preset=rung)]
    v2 = [p.meta["bands"] for p in ct.generate(8, seed=5, n=4)]
    assert (mine == v2) == (rung == ct.DEFAULT_PRESET)


# ------------------------------------------------------------------ structure


@pytest.mark.parametrize("rung", RUNGS)
@pytest.mark.parametrize("k", KS)
def test_k_leaves_with_matching_witnesses(k, rung):
    for p in _problems(k, preset=rung):
        names = [l.name for l in p.oracle_plan.lemmas]
        assert len(names) == k == p.k
        assert len(set(names)) == k
        assert set(names) == set(p.witnesses)
        assert all(p.witnesses[n].prop == l.prop for n, l in zip(names, p.oracle_plan.lemmas))


@pytest.mark.parametrize("rung", RUNGS)
@pytest.mark.parametrize("k", (2, 4, 8))
def test_every_leaf_carries_its_rungs_opaque_atom(k, rung):
    """Every rung hides the band claim behind an atom that linear-arithmetic
    preprocessing cannot connect to the band product (`Real.sqrt`, `/`, `⌊·⌋`).
    A silent regression to v1's bare quadratic re-opens the 70/70
    `intros; nlinarith` kill and must fail offline, not at the next live sweep.
    """
    shape = SHAPES[rung]
    for p in _problems(k, preset=rung):
        assert p.meta["schema"] == ct.RUNGS[rung].schema_id
        assert p.meta["n_atoms"] == shape["atoms"]
        for marker, per_piece in shape["markers"].items():
            for l in p.oracle_plan.lemmas:
                assert l.prop.count(marker) == per_piece, l.prop
            assert p.goal.prop.count(marker) == k * per_piece


@pytest.mark.parametrize("rung", RUNGS)
@pytest.mark.parametrize("k", (2, 4, 8))
def test_witness_turns_on_the_rungs_own_lemma(k, rung):
    """The witness must *rewrite* before it arithmetises, and which rewrite it
    is IS the rung's mechanism: `Real.sqrt_le_iff` for v2, `le_div_iff₀` for the
    quotient, `mul_le_mul` for the product split, `Int.floor_lt` for the tight
    floor, `Real.sqrt_mul` before the floor for the join."""
    for p in _problems(k, preset=rung):
        for w in p.witnesses.values():
            assert SHAPES[rung]["lemma"] in w.proof, w.proof
            assert w.proof.startswith("by\n  intro x hl hr\n")
            assert w.proof.rstrip().endswith("linarith")


@pytest.mark.parametrize("rung", RUNGS)
@pytest.mark.parametrize("k", KS)
def test_props_are_single_line_and_sanitizer_clean(k, rung):
    for p in _problems(k, preset=rung):
        assert "\n" not in p.goal.prop
        assert not scan_source(p.goal.prop)
        for l in p.oracle_plan.lemmas:
            assert "\n" not in l.prop
            assert not scan_source(l.prop)
        assert not scan_source(p.oracle_plan.assembly)
        for w in p.witnesses.values():
            assert not scan_source(w.proof)


@pytest.mark.parametrize("rung", RUNGS)
@pytest.mark.parametrize("k", KS)
def test_plan_round_trips_through_the_wire_format(k, rung):
    """The oracle plan must be expressible in exactly the format a policy emits
    — otherwise oracle replay and policy episodes are not the same task."""
    for p in _problems(k, preset=rung):
        plan = p.oracle_plan
        wire = "\n".join(
            [f"#lemma {l.name} : {l.prop}" for l in plan.lemmas]
            + ["#assembly", plan.assembly, "#end"]
        )
        back = parse_plan(wire)
        assert [(l.name, l.prop) for l in back.lemmas] == [(l.name, l.prop) for l in plan.lemmas]
        assert back.assembly.strip() == plan.assembly.strip()


@pytest.mark.parametrize("rung", RUNGS)
@pytest.mark.parametrize("k", KS)
def test_lemma_names_pass_harness_hygiene(k, rung):
    for p in _problems(k, preset=rung):
        check_names(p.goal, p.oracle_plan)  # raises on collision/reserved/duplicate


@pytest.mark.parametrize("rung", RUNGS)
@pytest.mark.parametrize("k", KS)
def test_assembly_dispatches_to_every_leaf_exactly_once(k, rung):
    for p in _problems(k, preset=rung):
        asm = p.oracle_plan.assembly
        for l in p.oracle_plan.lemmas:
            assert asm.count(f"{l.name} x ") == 1, f"{l.name} not dispatched exactly once"
        # flat, not nested: one focus dot per non-final case, no indentation growth
        assert asm.count("\n· exact ") == k - 1
        assert all(not line.startswith(" ") for line in asm.splitlines())


@pytest.mark.parametrize("k", KS)
def test_extremum_tree_is_balanced(k):
    paths = ct._paths(k)
    assert len(set(paths)) == k, "every piece needs a distinct address"
    assert max(len(p) for p in paths) == math.ceil(math.log2(k))
    assert max(len(p) for p in paths) - min(len(p) for p in paths) <= 1


@pytest.mark.parametrize("rung", RUNGS)
def test_assembly_growth_is_subquadratic(rung):
    """A right-nested extremum would put leaf i at depth i and make the
    assembly Θ(k²) — the root policy's own output would then be dominated by
    glue tokens rather than by the decomposition, which is exactly the confound
    the k-axis must not have."""
    a32 = len(ct.build(32, 5, preset=rung).oracle_plan.assembly)
    a128 = len(ct.build(128, 5, preset=rung).oracle_plan.assembly)
    assert a128 / a32 < 8, (a32, a128)  # 4x the leaves; right-nesting would be ~16x


@pytest.mark.parametrize("rung", RUNGS)
@pytest.mark.parametrize("k", KS)
def test_variant_glue_matches_the_goal_connective(k, rung):
    for p in _problems(k, preset=rung):
        variant = p.meta["variant"]
        assert variant in ct.VARIANTS
        left, right = ct._GLUE[variant]
        assert f" {variant} (" in p.goal.prop
        assert left in p.oracle_plan.assembly and right in p.oracle_plan.assembly
        other = ct._GLUE["min" if variant == "max" else "max"]
        assert not any(g in p.oracle_plan.assembly for g in other)


# --------------------------------------------------- mathematical invariants


@pytest.mark.parametrize("rung", RUNGS)
@pytest.mark.parametrize("k", KS)
def test_bands_tile_the_goal_domain_contiguously(k, rung):
    for p in _problems(k, preset=rung):
        bands = p.meta["bands"]
        lo, hi = p.meta["domain"]
        assert bands[0][0] == lo and bands[-1][1] == hi
        for (a, b), (c, d) in zip(bands, bands[1:]):
            assert b == c, "bands must be contiguous"
            assert b > a and d > c, "bands must be non-degenerate"
        assert f"{lo} ≤ x → x ≤ {hi} →" in p.goal.prop


@pytest.mark.parametrize("rung", RUNGS)
@pytest.mark.parametrize("k", KS)
def test_every_piece_covers_its_own_band(k, rung):
    """Exact integer arithmetic, no floats: the problem is true by construction.

    `covers_band` is the rung's own predicate at the two band endpoints, which
    is the *real-line* claim because every rung's piece value is monotone in
    |x - m| — so the worst case over the reals sits at an integer."""
    for idx in range(2):
        _, pieces = ct.layout(k, 3, idx, preset=rung)
        assert all(q.covers_band for q in pieces)
        # and it really is the worst case: nothing inside the band fails either
        for q in pieces:
            assert all(q.holds_at(x) for x in range(q.lo, q.hi + 1))


@pytest.mark.parametrize("rung", RUNGS)
@pytest.mark.parametrize("k", KS)
def test_every_case_is_necessary(k, rung):
    """No piece may be redundant — a redundant piece would make a k-leaf plan a
    dressed-up (k-1)-leaf problem and silently flatten the size axis."""
    for seed in range(6):
        for idx in range(2):
            _, pieces = ct.layout(k, seed, idx, preset=rung)
            for i in range(k):
                assert not ct._redundant(pieces, i), \
                    f"{rung} k={k} seed={seed} piece {i} is covered by its neighbours"


@pytest.mark.parametrize("rung", RUNGS)
def test_exact_integer_predicate_matches_60_digit_arithmetic(rung):
    """The soundness obligation, in both directions (module docstring).

    `under` (the real predicate holds, `holds_at` says no) ⇒ the generator
    claims a necessity it does not have and ships a secretly-(k-1)-leaf plan.
    `over` ⇒ a false theorem. This is the check that rejected `Real.log` pieces,
    and it is re-run per rung because each rung derives its own iff.
    """
    checked = 0
    for k in (2, 4, 8, 16):
        for seed in (0, 5150):
            _, pieces = ct.layout(k, seed, 0, preset=rung)
            for p in pieces:
                a = ct.predicate_mismatches(p, radius=14)
                assert a["under"] == [] and a["over"] == [], (rung, k, seed, p, a)
                checked += a["points"]
    assert checked >= 1740, "the audit must actually visit points"


@pytest.mark.parametrize("rung", RUNGS)
def test_necessity_is_structural_over_the_whole_knob_support(rung):
    """F3, re-established per rung rather than inherited (case-tree-hardening
    §8.5): a widened knob support — a second atom, a shifted pad — re-opens the
    argument that `_repair_necessity` never fires.

    The sweep is exhaustive over the rung's cells and position-independent
    (every rung's predicate is a function of x - m alone), so it settles the
    question for every band of every problem at every k.
    """
    sweep = ct.necessity_sweep(rung)
    assert sweep["ok"], sweep
    assert sweep["max_spill"] < min(ct.WIDTHS) / 2
    assert sweep["cells_at_threshold"] == []
    assert sweep["cells"] >= 36


def test_necessity_uses_the_rungs_own_predicate():
    """THE guard for the ladder's highest-risk change.

    A rung that silently reused v2's predicate would ship false necessity. Here
    is a two-atom piece where the two predicates disagree **in the unsound
    direction**: v2's `a(x-m)² ≤ d` believes the covering piece reaches only
    x ∈ {4,5,6}, while the truth (verified against 60-digit arithmetic) is
    {3..7}. So the victim band [3,5] IS fully covered by its neighbour and the
    plan is secretly 1-leaf — and v2's predicate would have called it necessary
    and shipped it.

    `_redundant` gets this right because `Piece.holds_at` has no implementation
    of its own; it dispatches to `self.schema`, and `Piece` cannot be built
    without one.
    """
    sums, v2 = ct.RUNGS["r2_sum"], ct.RUNGS["v2"]
    victim = ct.Piece(schema=sums, lo=3, hi=5, a=1, m=4, d=3,
                      width=2, offset=0, slack=0, extras=(2,))
    cover = ct.Piece(schema=sums, lo=2, hi=8, a=1, m=5, d=1,
                     width=6, offset=0, slack=0, extras=(2,))
    pieces = [victim, cover]

    assert [x for x in range(0, 11) if cover.holds_at(x)] == [3, 4, 5, 6, 7]
    assert [x for x in range(0, 11) if v2.holds_at(cover, x)] == [4, 5, 6]
    # the rung's predicate is the one that matches reality, not v2's
    assert ct.predicate_mismatches(cover)["ok"]
    assert sums.holds_exact(cover, 3) and not v2.holds_at(cover, 3)

    assert ct._redundant(pieces, 0), "the victim really is unnecessary"
    v2_answer = all(any(v2.holds_at(q, x) for j, q in enumerate(pieces) if j != 0)
                    for x in range(victim.lo, victim.hi + 1))
    assert not v2_answer, "the counterfactual this test exists to forbid"


def test_a_piece_cannot_be_built_without_a_schema():
    """Structural, not remembered: there is no default schema to fall back to,
    and no `holds_at` on `Piece` itself."""
    with pytest.raises(TypeError):
        ct.Piece(lo=0, hi=6, a=1, m=3, d=9, width=6, offset=0, slack=0)  # type: ignore[call-arg]
    assert "holds_at" not in vars(ct.Piece) or ct.Piece.holds_at.__doc__
    # ... and a piece of a 2-atom rung cannot be built without its extra knobs
    bad = ct.Piece(schema=ct.RUNGS["r2_sum"], lo=0, hi=6, a=1, m=3, d=9,
                   width=6, offset=0, slack=0)
    with pytest.raises(ValueError, match="extras"):
        bad.holds_at(3)


def test_redundancy_detector_actually_fires():
    """Guard the guard: two over-generous pieces on adjacent narrow bands are
    mutually redundant, and _redundant must say so."""
    v2 = ct.RUNGS["v2"]
    wide = [ct.Piece(v2, lo=0, hi=2, a=1, m=1, d=99, width=2, offset=0, slack=0),
            ct.Piece(v2, lo=2, hi=4, a=1, m=3, d=99, width=2, offset=0, slack=0)]
    assert ct._redundant(wide, 0) and ct._redundant(wide, 1)
    tight = [ct.Piece(v2, lo=0, hi=2, a=1, m=1, d=1, width=2, offset=0, slack=0),
             ct.Piece(v2, lo=2, hi=4, a=1, m=3, d=1, width=2, offset=0, slack=0)]
    assert not ct._redundant(tight, 0) and not ct._redundant(tight, 1)


def test_repair_tightens_the_spilling_pieces_only():
    """The greedy neighbours lose their spill; a piece that does not spill
    (offset 0, slack 0) is never rewritten, even when it is the swallowed one."""
    v2 = ct.RUNGS["v2"]
    victim = ct.Piece(v2, lo=2, hi=6, a=1, m=4, d=4, width=4, offset=0, slack=0)
    greedy = [ct.Piece(v2, lo=-2, hi=2, a=1, m=1, d=99, width=4, offset=1, slack=1),
              victim,
              ct.Piece(v2, lo=6, hi=10, a=1, m=9, d=99, width=4, offset=1, slack=1)]
    assert ct._redundant(greedy, 1)
    out = ct._repair_necessity(list(greedy))
    assert out[1] == victim, "a non-spilling piece must be untouched"
    assert out[0].repaired and out[2].repaired
    assert all(not ct._redundant(out, i) for i in range(3))


@pytest.mark.parametrize("rung", RUNGS)
def test_repair_rebuilds_with_the_pieces_own_rung(rung):
    """`_tighten` must go through the rung, or a repaired two-atom piece would
    lose its second atom (and a repaired floor piece its tight cap)."""
    r = ct.RUNGS[rung]
    p = ct._make(r, lo=-4, width=8, a=2, offset=1, slack=1, extras=r.extra_cells(2)[0])
    t = ct._tighten(p)
    assert t.schema is r and t.repaired and t.extras == p.extras
    assert t.offset == 0 and t.slack == 0 and t.covers_band
    assert len(t.atoms) == r.n_atoms
    # tightening removes the spill: the super-level set is exactly the band
    assert not t.holds_at(t.lo - 1) and not t.holds_at(t.hi + 1)


@pytest.mark.parametrize("rung", RUNGS)
@pytest.mark.parametrize("k", KS)
def test_pieces_are_not_all_identical(k, rung):
    """A case tree whose leaves are copies of one lemma is not a case tree."""
    for p in _problems(k, preset=rung):
        assert len({l.prop for l in p.oracle_plan.lemmas}) == k


@pytest.mark.parametrize("rung", RUNGS)
def test_generation_tripwires_reject_a_broken_piece(rung):
    """The generation-time asserts are the difference between a loud bug and a
    false problem. Each is unreachable by construction, so they are exercised
    here on hand-broken pieces.

    Which breakage is available is itself informative. A degenerate curvature
    breaks every rung. A margin that does not reach the band edge breaks only
    the rungs where `d` is load-bearing: the floor rungs derive their pad from
    the band geometry (`e = (T+1)² − 1 − a·far²`), so their coverage is
    *structural* and cannot be broken by moving `d` at all.
    """
    r = ct.RUNGS[rung]
    good = ct._make(r, lo=-4, width=8, a=1, offset=0, slack=0, extras=r.extra_cells(1)[0])
    assert r.violations(good) == []

    flat = ct.Piece(schema=r, lo=-4, hi=4, a=0, m=0, d=9, width=8, offset=0,
                    slack=0, extras=good.extras)
    assert any("curvature" in v for v in r.violations(flat)), r.violations(flat)

    starved = ct.Piece(schema=r, lo=-4, hi=4, a=1, m=0, d=1, width=8, offset=0,
                       slack=0, extras=good.extras)
    if rung in ("r3_floor", "r4_floorprod"):
        assert r.violations(starved) == [], "floor rungs: coverage is structural in d"
    else:
        assert any("cover" in v for v in r.violations(starved))


@pytest.mark.parametrize("rung", RUNGS)
def test_every_radicand_keeps_a_strictly_positive_pad(rung):
    """F10, over the rung's whole knob support rather than on a sample.

    `e ≥ 1` is an *invention* constraint, not a validity one: at `e = 0` the
    radicand is a perfect square that `Real.sqrt_sq_eq_abs` rewrites to
    `|x − m|`, handing the policy the vertex it is supposed to invent. For v2
    it follows from `_cap`'s strict `t² > d`; the floor rungs have to floor `T`
    explicitly to keep it (base = 48 is where it binds).
    """
    r = ct.RUNGS[rung]
    for width in ct.WIDTHS:
        for a in ct.CURVATURES:
            for off in ct.VERTEX_OFFSETS:
                for slack in ct.SLACKS:
                    for extras in r.extra_cells(a):
                        p = ct._make(r, 0, width, a, off, slack, extras)
                        assert all(at.e >= 1 for at in p.atoms), (rung, p)
                        # ...and never a bare `a·x²` either: the vertex is off 0
                        # or the pad shows, both of which the expansion hides
                        assert all(at.coeffs()[2] != 0 for at in p.atoms)


# ------------------------------------------------------------------- V6 / meta


@pytest.mark.parametrize("rung", RUNGS)
@pytest.mark.parametrize("k", KS)
def test_no_leaf_is_a_substring_of_the_goal_and_nothing_is_exempt(k, rung):
    for p in _problems(k, preset=rung):
        assert p.meta["visible_lemmas"] == []
        g = normalize_statement(p.goal.prop)
        for l in p.oracle_plan.lemmas:
            assert normalize_statement(l.prop) not in g


@pytest.mark.parametrize("rung", RUNGS)
@pytest.mark.parametrize("k", KS)
def test_band_hypotheses_are_absent_from_the_goal(k, rung):
    """The split points are the invented content: the goal states exactly one
    upper bound on x — the domain's — and no interior band endpoint."""
    for p in _problems(k, preset=rung):
        assert p.goal.prop.count("x ≤ ") == 1
        for _, hi in p.meta["bands"][:-1]:
            assert hi != p.meta["domain"][1]
            assert f"x ≤ {hi} →" not in p.goal.prop


# --------------------------------------------------------------- flatness in k


@pytest.mark.parametrize("rung", RUNGS)
def test_necessity_never_needs_repair_at_any_k(rung):
    """The flatness claim's load-bearing invariant: necessity holds structurally
    (min width 6 > 2 × max spill 2), so the repair — which would tighten leaves
    at a k-dependent rate — never fires and the knob distribution is exactly the
    same at every k."""
    stats = ct.leaf_stats([p for k in (2, 4, 8, 16, 32)
                           for p in ct.generate(k, seed=101, n=6, preset=rung)])
    assert {k: s["repaired_frac"] for k, s in stats.items()} == {k: 0.0 for k in stats}
    assert min(ct.WIDTHS) >= 6, "widths below 6 let a piece swallow a neighbour"


@pytest.mark.parametrize("rung", RUNGS)
def test_leaf_schema_support_is_identical_across_k(rung):
    stats = ct.leaf_stats([p for k in KS for p in _problems(k, seed=5, n=4, preset=rung)])
    assert set(stats) == set(KS)
    for k, s in stats.items():
        assert s["knob_support_ok"], (rung, k)
        assert s["leaves"] == 4 * k
        assert s["presets"] == [rung]


@pytest.mark.parametrize("rung", RUNGS)
def test_leaf_length_is_near_flat_in_k(rung):
    """Only the band's absolute position depends on k, so leaf props may grow by
    a few numeral digits — but not by a different schema. 16x the leaf count
    must not double the leaf statement."""
    stats = ct.leaf_stats([p for k in (2, 32)
                           for p in ct.generate(k, seed=9, n=4, preset=rung)])
    lo, hi = stats[2]["leaf_len_mean"], stats[32]["leaf_len_mean"]
    assert hi / lo < 1.5, (rung, lo, hi)


@pytest.mark.parametrize("rung", RUNGS)
def test_outer_constant_is_bounded_by_the_knob_support_not_by_k(rung):
    """F4's sharp half. The radicand's constant grows like a·m² and that is
    accepted (it is the schema's one k-dependence); the OUTER constant is what
    must not, or the goal itself would carry a difficulty gradient in k."""
    r = ct.RUNGS[rung]
    ceiling = max(
        ct._make(r, 0, w, a, off, s, ex).outer_const(v)
        for w in ct.WIDTHS for a in ct.CURVATURES for off in ct.VERTEX_OFFSETS
        for s in ct.SLACKS for ex in r.extra_cells(a) for v in ct.VARIANTS
    )
    seen = {k: ct.leaf_stats(ct.generate(k, seed=13, n=6, preset=rung))[k]["max_outer_const"]
            for k in (2, 8, 32)}
    assert max(seen.values()) <= ceiling, (rung, seen, ceiling)
    assert seen[32] <= seen[8] or seen[8] == 0, (rung, seen)


@pytest.mark.parametrize("rung", RUNGS)
def test_knob_mix_is_drawn_from_the_same_support_at_every_k(rung):
    """Same distribution, not merely same support: with enough leaves every k
    should exercise several distinct knob tuples."""
    for k in (2, 8, 32):
        s = ct.leaf_stats(ct.generate(k, seed=4, n=6, preset=rung))[k]
        assert s["distinct_knob_tuples"] >= min(6, s["leaves"])


def test_leaf_stats_reports_per_k_and_per_rung():
    s = ct.leaf_stats(ct.generate(4, seed=1, n=3) + ct.generate(8, seed=1, n=3))
    assert sorted(s) == [4, 8]
    assert s[4]["problems"] == 3 and s[4]["leaves"] == 12
    assert s[8]["leaf_len_max"] >= s[8]["leaf_len_min"]
    assert s[4]["presets"] == ["v2"]
    # mixed input reports every rung that produced it, and the support check is
    # then per-rung rather than v2's
    mixed = ct.leaf_stats(ct.generate(4, seed=1, n=2)
                          + ct.generate(4, seed=1, n=2, preset="r2_sum"))
    assert mixed[4]["presets"] == ["r2_sum", "v2"]
    assert mixed[4]["knob_support_ok"]


@pytest.mark.parametrize("rung", RUNGS)
def test_leaf_stats_reports_the_new_rungs_knobs(rung):
    """The datasheet has to say what a rung's knobs were, or the pod-side
    regression (R3′, R4) has nothing to condition on."""
    p = ct.build(8, 21, 0, preset=rung)
    r = ct.RUNGS[rung]
    for kb in p.meta["knobs"]:
        assert {"width", "curvature", "offset", "slack", "cap", "pad", "repaired"} <= set(kb)
        for extra in r.extra_knobs:
            assert extra in kb, (rung, extra)
        assert r.support_ok(kb)
    if rung == "r2_sum":   # the registered continuous lever
        assert all(kb["split_gap"] >= 0 for kb in p.meta["knobs"])
    if rung == ct.DEFAULT_PRESET:  # v2's knob dict must not have grown
        assert set(p.meta["knobs"][0]) == {"width", "curvature", "offset", "slack",
                                           "cap", "pad", "repaired"}


@pytest.mark.parametrize("rung", RUNGS)
def test_scales_past_the_phase1_grid(rung):
    """FAMILIES.md: the schema must not break at k=128 even if Phase 1 ships k≤32."""
    p = ct.build(128, 0, preset=rung)
    assert len(p.oracle_plan.lemmas) == 128
    assert "\n" not in p.goal.prop
    assert p.oracle_plan.assembly.count("rcases") == 127


@pytest.mark.parametrize("rung", RUNGS)
def test_generation_is_clean_at_k32(rung):
    """k=32 is the top of the Phase-1 grid: every tripwire, on every piece, on
    several seeds — coverage, necessity, pads, tight caps, renderability."""
    for seed in (0, 42, 5150):
        p = ct.build(32, seed, 0, preset=rung)      # build() runs every tripwire
        assert len(p.oracle_plan.lemmas) == 32
        _, pieces = ct.layout(32, seed, 0, preset=rung)
        assert all(q.covers_band for q in pieces)
        assert not any(ct._redundant(pieces, i) for i in range(32))


def test_wire_format_lemma_cap_bounds_the_policy_emittable_k():
    """Contract boundary, pinned rather than worked around.

    `core.plan_format.MAX_LEMMAS_HARD` caps a *parsed* plan. Originally 64,
    which sat below this family's beyond-window tier (k≈512 post tree-balancing)
    — exactly the "cap, not the family, has to move" case this test predicted.
    Moved to 1024 on 2026-08-11; the pin remains so the next move is deliberate.
    """
    assert MAX_LEMMAS_HARD == 1024

    def wire(p):
        return "\n".join([f"#lemma {l.name} : {l.prop}" for l in p.oracle_plan.lemmas]
                         + ["#assembly", p.oracle_plan.assembly, "#end"])

    # the old cap (64) sat inside this family's k-grid; both sides now emit-able
    assert len(parse_plan(wire(ct.build(64, 0))).lemmas) == 64
    assert len(parse_plan(wire(ct.build(65, 0))).lemmas) == 65

    # the boundary itself, checked synthetically (family-independent)
    lines = [f"#lemma h{i} : P{i}" for i in range(MAX_LEMMAS_HARD + 1)]
    with pytest.raises(PlanFormatError, match=f"more than {MAX_LEMMAS_HARD} lemmas"):
        parse_plan("\n".join(lines + ["#assembly", "trivial", "#end"]))


# ------------------------------------------------------------------ rendering


@pytest.mark.parametrize("coeffs,expected", [
    ((-2, 16, -20), "-2 * x ^ 2 + 16 * x - 20"),
    ((1, -6, 3), "x ^ 2 - 6 * x + 3"),
    ((-1, 0, 5), "-x ^ 2 + 5"),
    ((3, -6, 0), "3 * x ^ 2 - 6 * x"),
    ((0, 0, 0), "0"),
])
def test_render_poly(coeffs, expected):
    assert ct._render_poly(*coeffs) == expected


def test_negative_split_points_are_parenthesised_in_application_position():
    """`le_or_gt x -5` elaborates as a subtraction and the plan check fails;
    `le_or_gt x (-5)` is the split point. Caught live, pinned here."""
    assert ct._num(-5) == "(-5)" and ct._num(5) == "5"
    for k in KS:
        asm = ct.build(k, 7).oracle_plan.assembly
        assert not re.search(r"le_or_gt x -", asm), asm
        neg = [m for m in re.findall(r"le_or_gt x (\S+)", asm) if m.startswith("(-")]
        assert all(re.fullmatch(r"\(-\d+\)", m) for m in neg)
    # the k=7 seed above must actually exercise a negative split point
    assert "le_or_gt x (-" in ct.build(4, 7).oracle_plan.assembly


def test_each_rung_renders_the_exemplar_its_survey_gated():
    """The four candidate rungs' battery/witness verdicts (research/
    ct-hardening-survey-{a,b}.md, carried into case-tree-hardening.md §3-4) were
    measured on *hand-built* instances. This pins that the shipped generator
    emits those exact statements for the corresponding knob cell — otherwise the
    inherited local-gate table describes something this code does not produce.
    """
    cell = dict(lo=-7, width=8, a=1, offset=0, slack=0)          # band [-7, 1], far 4
    expect = {
        "v2": "3 ≤ 9 - Real.sqrt (2 * x ^ 2 + 12 * x + 22)",     # (a=2 variant of the cell)
        "r1_recip": "3 ≤ 51 / (x ^ 2 + 6 * x + 10)",
        "r2_prod": ("3 ≤ 33 - Real.sqrt (x ^ 2 + 6 * x + 18) "
                    "* Real.sqrt (2 * x ^ 2 + 12 * x + 22)"),
        "r3_floor": "3 ≤ 7 - (⌊Real.sqrt (x ^ 2 + 6 * x + 17)⌋ : ℝ)",
        "r4_floorprod": ("3 ≤ 26 - (⌊Real.sqrt (x ^ 2 + 6 * x + 10) "
                         "* Real.sqrt (2 * x ^ 2 + 12 * x + 19)⌋ : ℝ)"),
    }
    for rung, tail in expect.items():
        r = ct.RUNGS[rung]
        a = 2 if rung == "v2" else 1
        extras = (2,) if r.extra_knobs else ()
        p = ct._make(r, cell["lo"], cell["width"], a, cell["offset"], cell["slack"], extras)
        assert ct._leaf_prop(p, "max") == f"∀ x : ℝ, -7 ≤ x → x ≤ 1 → {tail}", rung
    # r2_sum's exemplar is on the narrower band [-7, -1]
    p = ct._make(ct.RUNGS["r2_sum"], -7, 6, 1, 0, 0, (2,))
    assert ct._leaf_prop(p, "max") == (
        "∀ x : ℝ, -7 ≤ x → x ≤ -1 → 3 ≤ 12 - Real.sqrt (x ^ 2 + 8 * x + 23) "
        "- Real.sqrt (2 * x ^ 2 + 16 * x + 39)")


def test_radicand_and_cap_reduce_to_one_covering_condition():
    """v2: both variants reduce to `√u ≤ t`, i.e. `a(x-m)² ≤ d`; `holds_at` is
    variant-free and the radicand is positive definite (pad ≥ 1) so the
    `√u ≤ t ⟺ u ≤ t²` characterisation is exact everywhere."""
    p = ct.Piece(ct.RUNGS["v2"], lo=0, hi=4, a=2, m=2, d=8, width=4, offset=0, slack=0)
    assert p.cap == 3 and p.pad == 1                     # 3² = 9 > 8, e = 1
    assert p.radicand() == (2, -8, 2 * 4 + 1)            # 2(x-2)² + 1
    assert p.outer_const("max") == ct.C_LEVEL + 3        # piece is `6 - √u`
    # (this hand-built piece has width 4, outside WIDTHS; the shipped support keeps
    #  the min-variant constant ≥ 1 — see test_shipped_knobs_… below)
    assert p.outer_const("min") == 3 - ct.C_LEVEL
    assert p.holds_at(2) and p.holds_at(0) and not p.holds_at(5)


def test_cap_forces_a_strictly_positive_radicand_pad():
    """`e ≥ 1` keeps the radicand off `a·x²` (vertex at the origin, readable) and
    off a perfect square (which `Real.sqrt_sq_eq_abs` rewrites to `|x - m|`)."""
    for d in range(0, 200):
        t = ct._cap(d)
        assert t * t > d and (t - 1) ** 2 <= d
    for rung in RUNGS:
        for k in KS:
            for p in _problems(k, seed=11, n=2, preset=rung):
                for kb in p.meta["knobs"]:
                    assert kb["pad"] >= 1, (rung, k, kb)


@pytest.mark.parametrize("rung", RUNGS)
def test_shipped_knobs_keep_the_min_variant_constant_positive(rung):
    """The min-variant piece renders `f x - n`, so `n ≥ 1` for every legal cell:
    at `n = 0` the renderer would emit `… - 0` and at `n < 0` a `+`. For v2 that
    is `t - C ≥ 1` (width ≥ 6 and curvature ≥ 1 force `d ≥ 9`, hence `t ≥ 4`);
    r3_floor's tight cap is one below v2's and has to be floored explicitly."""
    r = ct.RUNGS[rung]
    for width in ct.WIDTHS:
        for a in ct.CURVATURES:
            for off in ct.VERTEX_OFFSETS:
                for slack in ct.SLACKS:
                    for extras in r.extra_cells(a):
                        p = ct._make(r, 0, width, a, off, slack, extras)
                        assert r.min_const(p) >= 1, (rung, width, a, off, slack, extras)
                        assert r.violations(p) == [], (rung, width, a, off, slack, extras)


@pytest.mark.parametrize("rung", ("r3_floor", "r4_floorprod"))
def test_floor_rungs_have_a_tight_cap(rung):
    """The mechanism, not a detail: `T² < u_max` is what makes the memorised
    sub-goal `√u ≤ T` FALSE on part of the band. S2's loose-vs-tight control
    (12/12 vs 0/12 on one knob) is the whole reason this rung is in the ladder,
    so a pad that drifted loose would silently turn it back into v2 wearing a
    floor."""
    r = ct.RUNGS[rung]
    for width in ct.WIDTHS:
        for a in ct.CURVATURES:
            for off in ct.VERTEX_OFFSETS:
                for slack in ct.SLACKS:
                    for extras in r.extra_cells(a):
                        p = ct._make(r, 0, width, a, off, slack, extras)
                        peak = math.prod(at.value(p.m + p.far) for at in p.atoms)
                        assert p.budget**2 < peak < (p.budget + 1) ** 2, (rung, p)


# ------------------------------------------------------- validator, offline


def _wire_ok(fb) -> None:
    """Battery calls fail, everything else succeeds.

    Matching is on the *whole* proof body (`endswith`), not a substring: the
    witnesses legitimately contain `by nlinarith [...]` / `by norm_num` inside
    a `Real.sqrt_le_iff.mpr ⟨_, _⟩` term, and a substring rule would score the
    generator's own witness as an automation kill."""
    from rlmath.families.validate import battery_proofs

    fb.rule(lambda c: ":= sorry" in c, VerifyResult(ok=True, sorries=1))
    fb.rule(lambda c: c.rstrip().endswith(tuple(battery_proofs())),
            VerifyResult(ok=False, sorries=0))
    fb.rule(lambda c: True, VerifyResult(ok=True, sorries=0))


@pytest.mark.parametrize("rung", RUNGS)
@pytest.mark.parametrize("k", (2, 4))
def test_validator_passes_on_a_scripted_backend(fake_backend, k, rung):
    _wire_ok(fake_backend)
    for p in ct.generate(k, seed=2, n=1, preset=rung):
        r = validate_problem(p, fake_backend)
        assert r.ok, r.failed()
        names = [c.name for c in r.checks]
        assert "V0_goal_resists_automation" in names
        assert sum(n.startswith("V5_leaf_resists") for n in names) == k
        assert sum(n.startswith("V6_hidden") for n in names) == k


def test_validator_surfaces_an_auto_closable_leaf(fake_backend):
    p = ct.build(2, 2)
    victim = p.oracle_plan.lemmas[0].prop
    fake_backend.rule(lambda c: ":= sorry" in c, VerifyResult(ok=True, sorries=1))
    fake_backend.rule(lambda c, v=victim: "by omega" in c and v in c,
                      VerifyResult(ok=True, sorries=0))
    fake_backend.rule(lambda c: any(f"by {t}" in c for t in AUTOMATION_TACTICS),
                      VerifyResult(ok=False, sorries=0))
    fake_backend.rule(lambda c: True, VerifyResult(ok=True, sorries=0))
    r = validate_problem(p, fake_backend)
    assert not r.ok
    assert any(c.name.startswith("V5_leaf_resists") and "omega" in c.detail for c in r.failed())


# ------------------------------------------------------------- integration


_HAS_LEAN = False
try:  # pragma: no cover - depends on the box
    from rlmath.lean.repl_pool import ReplConfig, ReplPool

    _HAS_LEAN = ReplConfig().available()
except Exception:  # pragma: no cover
    pass

needs_lean = pytest.mark.skipif(not _HAS_LEAN, reason="no local Lean toolchain")


@pytest.fixture(scope="module")
def live_pool():
    """One warm 2-worker pool for the module: `import Mathlib` is the expensive
    part, and this box is shared with the sibling family agents."""
    p = ReplPool(n_workers=2)
    yield p
    p.close()


@pytest.mark.integration
@needs_lean
@pytest.mark.timeout(1800)
def test_two_problems_pass_the_full_validator_live(live_pool):
    """The whole contract, V0–V6, against Mathlib: one problem per variant."""
    problems = [ct.build(2, 0, 0), ct.build(4, 0, 0)]  # seed 0: min at k=2, max at k=4
    assert {p.meta["variant"] for p in problems} == set(ct.VARIANTS), "cover both variants"
    for p in problems:
        report = validate_problem(p, live_pool, check_automation=True, timeout_s=180)
        assert report.ok, f"{p.id}: {[(c.name, c.detail) for c in report.failed()]}"


@pytest.mark.integration
@needs_lean
@pytest.mark.timeout(3600)
@pytest.mark.parametrize("rung", [r for r in RUNGS if r != "v2"])
def test_every_rung_passes_the_full_validator_live(live_pool, rung):
    """R0b (research/case-tree-hardening.md §7): V3 and V4 have never been run
    for any candidate rung — both surveys measured V0/V1/V2/V5 on hand-built
    probe instances and neither went through `case_tree.build`. This is the
    blocking pre-flight, and it is free."""
    for p in ct.generate(4, seed=5150, n=1, preset=rung):
        report = validate_problem(p, live_pool, check_automation=True, timeout_s=180)
        assert report.ok, f"{p.id}: {[(c.name, c.detail) for c in report.failed()]}"


@pytest.mark.integration
@needs_lean
@pytest.mark.timeout(3600)
def test_every_rungs_witness_kernel_checks_at_both_ends_of_the_k_grid():
    """A witness that stops checking is a generator bug, not a difficulty
    result — S1 found exactly that on two directions by running this. Both
    variants, both ends of the grid, first and last band."""
    from rlmath.core import leancode

    cases = []
    for rung in RUNGS:
        for k, seed in ((2, 5), (8, 3)):
            _, pieces = ct.layout(k, seed, 0, preset=rung)
            for piece in (pieces[0], pieces[-1]):
                for variant in ct.VARIANTS:
                    cases.append((f"{rung}-k{k}-{variant}", ct._leaf_prop(piece, variant),
                                  ct.leaf_proof(piece)))
    pool = ReplPool(n_workers=3)
    try:
        res = pool.check_many([leancode.proof_check(pr, pf) for _, pr, pf in cases],
                              timeout_s=90.0)
    finally:
        pool.close()
    bad = [(lab, "; ".join(m.text for m in r.errors))
           for (lab, _, _), r in zip(cases, res) if not (r.ok and r.sorries == 0)]
    assert not bad, bad


@pytest.mark.integration
@needs_lean
@pytest.mark.timeout(1800)
def test_leaves_resist_the_intro_first_battery_live():
    """A *stronger* battery than the contract's, self-imposed.

    None of `AUTOMATION_TACTICS` introduces the leading `∀`/`→`, so V5 alone
    cannot distinguish a genuinely hard band from a `linarith` one-liner wearing
    a quantifier (measured: an affine band passes V5 and dies to
    `intro; linarith`). Every rung's leaves must survive the battery *after*
    `intro` too — which is what makes a future widening of AUTOMATION_TACTICS
    safe for banks generated today. Run on real generated goals and leaves at
    both ends of the k-grid, not on hand-picked samples.
    """
    from rlmath.core import leancode

    props: list[tuple[str, str]] = []
    for rung in RUNGS:
        for k in (2, 32):
            p = ct.build(k, 3000, 0, preset=rung)
            props.append((f"{rung}-k{k}-goal", p.goal.prop))
            props.append((f"{rung}-k{k}-leaf-first", p.oracle_plan.lemmas[0].prop))
            props.append((f"{rung}-k{k}-leaf-last", p.oracle_plan.lemmas[-1].prop))

    pool = ReplPool(n_workers=2)
    try:
        for label, prop in props:
            codes = [leancode.proof_check(prop, f"by\n  intro x hl hr\n  {t}", name=f"_ib{i}")
                     for i, t in enumerate(AUTOMATION_TACTICS)]
            res = pool.check_many(codes, timeout_s=25.0)
            killers = [t for t, r in zip(AUTOMATION_TACTICS, res) if r.ok and r.sorries == 0]
            assert not killers, f"{label} closed by intro + {killers}"
    finally:
        pool.close()


def _v1_unwrapped(p: ct.Piece, variant: str) -> str:
    """The same band claim as v1 wrote it: the bare expanded quadratic, no `√`.

    max: `C ≤ C + d − a(x−m)²`   min: `a(x−m)² − d + C ≤ C`
    Same truth condition (`a(x−m)² ≤ d`), same band — only the `√` cap removed.
    """
    s = -1 if variant == "max" else 1
    poly = ct._render_poly(s * p.a, -2 * s * p.a * p.m,
                           s * (p.a * p.m**2 - p.d) + ct.C_LEVEL)
    side = f"{ct.C_LEVEL} ≤ {poly}" if variant == "max" else f"{poly} ≤ {ct.C_LEVEL}"
    return f"∀ x : ℝ, {p.lo} ≤ x → x ≤ {p.hi} → {side}"


@pytest.mark.integration
@needs_lean
@pytest.mark.timeout(1800)
def test_the_opaque_atom_is_what_survives_intros_nlinarith():
    """The v2 decision, pinned as a live A/B (research/family-v2-hardening.md §2)
    and extended to every rung.

    v1's bare quadratic band died 70/70 to `intros; nlinarith` — structurally,
    because nlinarith's preprocessing multiplies hypothesis *pairs* and
    `(x − lo ≥ 0, hi − x ≥ 0)` is exactly the product certificate the witness
    used. This test asserts both halves on the *same* geometry: unwrapped dies
    (the live planted control), wrapped survives. If a future Mathlib teaches
    nlinarith about `Real.sqrt` / `⌊·⌋` / division, this fails loudly instead of
    the family silently going soft.
    """
    from rlmath.core import leancode
    from rlmath.families.validate import battery_proofs

    pool = ReplPool(n_workers=2)
    try:
        for rung in RUNGS:
            for k in (2, 8):
                variant, pieces = ct.layout(k, 4242, 0, preset=rung)
                for p in pieces[:2]:
                    control = _v1_unwrapped(p, variant)
                    res = pool.check(leancode.proof_check(control, "by intros; nlinarith"),
                                     timeout_s=60.0)
                    assert res.ok and res.sorries == 0, \
                        f"planted control did not die to intros; nlinarith — {control}"

                    leaf = ct._leaf_prop(p, variant)
                    codes = [leancode.proof_check(leaf, b) for b in battery_proofs()]
                    out = pool.check_many(codes, timeout_s=25.0)
                    killers = [b for b, r in zip(battery_proofs(), out)
                               if r.ok and r.sorries == 0]
                    assert not killers, f"{leaf} closed by {killers}"
    finally:
        pool.close()
