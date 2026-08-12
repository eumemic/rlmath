"""Family B (case trees) — offline generator tests + a live 2-problem integration check.

Offline tests pin the properties the generator claims by *construction*, so a
regression shows up without a Lean toolchain: determinism, exact-integer
coverage of every band, necessity of every case (no k-case costume over a
(k-1)-case problem), wire-format round-tripping, V6 hiddenness, and per-node
flatness of the leaf schema in k. The Lean-dependent claims (elaboration,
witness proofs, plan check, battery resistance) are the integration test's job
and the measured table in research/family-case-tree.md.
"""
from __future__ import annotations

import math
import re

import pytest

from rlmath.core.plan_format import MAX_LEMMAS_HARD, PlanFormatError, parse_plan
from rlmath.core.types import VerifyResult, normalize_statement
from rlmath.families import REGISTRY, validate_problem
from rlmath.families import case_tree as ct
from rlmath.families.validate import AUTOMATION_TACTICS
from rlmath.harness.composer import check_names
from rlmath.sanitize import scan_source

KS = (2, 3, 4, 8, 16)


def _problems(k: int, seed: int = 3, n: int = 2):
    return ct.generate(k, seed=seed, n=n)


# --------------------------------------------------------------- registration


def test_registered_under_case_tree():
    assert REGISTRY["case_tree"] is ct.generate


def test_generate_is_deterministic_in_k_and_seed():
    a = ct.generate(4, seed=17, n=3)
    b = ct.generate(4, seed=17, n=3)
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
        "∀ x : ℝ, -9 ≤ x → x ≤ 9 → 3 ≤ max (-3 * x ^ 2 - 36 * x - 78) "
        "(max (-2 * x ^ 2 + 22) (-2 * x ^ 2 + 28 * x - 62))"
    )
    assert p.oracle_plan.lemmas[1].prop == "∀ x : ℝ, -3 ≤ x → x ≤ 3 → 3 ≤ -2 * x ^ 2 + 22"


def test_distinct_seeds_give_distinct_problems():
    assert ct.build(4, 1).goal.prop != ct.build(4, 2).goal.prop


def test_generate_n_gives_n_distinct_ids():
    ps = ct.generate(4, seed=0, n=5)
    assert len({p.id for p in ps}) == 5
    assert len({p.goal.prop for p in ps}) == 5


def test_k_below_two_is_rejected():
    for k in (-1, 0, 1):
        with pytest.raises(ValueError, match="k >= 2"):
            ct.build(k, 0)


# ------------------------------------------------------------------ structure


@pytest.mark.parametrize("k", KS)
def test_k_leaves_with_matching_witnesses(k):
    for p in _problems(k):
        names = [l.name for l in p.oracle_plan.lemmas]
        assert len(names) == k == p.k
        assert len(set(names)) == k
        assert set(names) == set(p.witnesses)
        assert all(p.witnesses[n].prop == l.prop for n, l in zip(names, p.oracle_plan.lemmas))


@pytest.mark.parametrize("k", KS)
def test_props_are_single_line_and_sanitizer_clean(k):
    for p in _problems(k):
        assert "\n" not in p.goal.prop
        assert not scan_source(p.goal.prop)
        for l in p.oracle_plan.lemmas:
            assert "\n" not in l.prop
            assert not scan_source(l.prop)
        assert not scan_source(p.oracle_plan.assembly)
        assert not scan_source(p.witnesses[p.oracle_plan.lemmas[0].name].proof)


@pytest.mark.parametrize("k", KS)
def test_plan_round_trips_through_the_wire_format(k):
    """The oracle plan must be expressible in exactly the format a policy emits
    — otherwise oracle replay and policy episodes are not the same task."""
    for p in _problems(k):
        plan = p.oracle_plan
        wire = "\n".join(
            [f"#lemma {l.name} : {l.prop}" for l in plan.lemmas]
            + ["#assembly", plan.assembly, "#end"]
        )
        back = parse_plan(wire)
        assert [(l.name, l.prop) for l in back.lemmas] == [(l.name, l.prop) for l in plan.lemmas]
        assert back.assembly.strip() == plan.assembly.strip()


@pytest.mark.parametrize("k", KS)
def test_lemma_names_pass_harness_hygiene(k):
    for p in _problems(k):
        check_names(p.goal, p.oracle_plan)  # raises on collision/reserved/duplicate


@pytest.mark.parametrize("k", KS)
def test_assembly_dispatches_to_every_leaf_exactly_once(k):
    for p in _problems(k):
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


def test_assembly_growth_is_subquadratic():
    """A right-nested extremum would put leaf i at depth i and make the
    assembly Θ(k²) — the root policy's own output would then be dominated by
    glue tokens rather than by the decomposition, which is exactly the confound
    the k-axis must not have."""
    a32 = len(ct.build(32, 5).oracle_plan.assembly)
    a128 = len(ct.build(128, 5).oracle_plan.assembly)
    assert a128 / a32 < 8, (a32, a128)  # 4x the leaves; right-nesting would be ~16x


@pytest.mark.parametrize("k", KS)
def test_variant_glue_matches_the_goal_connective(k):
    for p in _problems(k):
        variant = p.meta["variant"]
        assert variant in ct.VARIANTS
        left, right = ct._GLUE[variant]
        assert f" {variant} (" in p.goal.prop
        assert left in p.oracle_plan.assembly and right in p.oracle_plan.assembly
        other = ct._GLUE["min" if variant == "max" else "max"]
        assert not any(g in p.oracle_plan.assembly for g in other)


# --------------------------------------------------- mathematical invariants


@pytest.mark.parametrize("k", KS)
def test_bands_tile_the_goal_domain_contiguously(k):
    for p in _problems(k):
        bands = p.meta["bands"]
        lo, hi = p.meta["domain"]
        assert bands[0][0] == lo and bands[-1][1] == hi
        for (a, b), (c, d) in zip(bands, bands[1:]):
            assert b == c, "bands must be contiguous"
            assert b > a and d > c, "bands must be non-degenerate"
        assert f"{lo} ≤ x → x ≤ {hi} →" in p.goal.prop


@pytest.mark.parametrize("k", KS)
def test_every_piece_covers_its_own_band(k):
    """Exact integer arithmetic, no floats: the problem is true by construction."""
    for idx in range(2):
        _, pieces = ct.layout(k, 3, idx)
        assert all(q.covers_band for q in pieces)


@pytest.mark.parametrize("k", KS)
def test_every_case_is_necessary(k):
    """No piece may be redundant — a redundant piece would make a k-leaf plan a
    dressed-up (k-1)-leaf problem and silently flatten the size axis."""
    for seed in range(6):
        for idx in range(2):
            _, pieces = ct.layout(k, seed, idx)
            for i in range(k):
                assert not ct._redundant(pieces, i), \
                    f"k={k} seed={seed} piece {i} is covered by its neighbours"


@pytest.mark.parametrize("k", KS)
def test_necessity_repair_preserves_band_coverage(k):
    """Repair may only shrink a piece to its own band — never below it."""
    for seed in range(4):
        _, pieces = ct.layout(k, seed, 0)
        assert all(q.covers_band for q in pieces)
        assert all(q.a in ct.CURVATURES for q in pieces)


def test_redundancy_detector_actually_fires():
    """Guard the guard: two over-generous pieces on adjacent narrow bands are
    mutually redundant, and _redundant must say so."""
    wide = [ct.Piece(lo=0, hi=2, a=1, m=1, d=99, width=2, offset=0, slack=0),
            ct.Piece(lo=2, hi=4, a=1, m=3, d=99, width=2, offset=0, slack=0)]
    assert ct._redundant(wide, 0) and ct._redundant(wide, 1)
    tight = [ct.Piece(lo=0, hi=2, a=1, m=1, d=1, width=2, offset=0, slack=0),
             ct.Piece(lo=2, hi=4, a=1, m=3, d=1, width=2, offset=0, slack=0)]
    assert not ct._redundant(tight, 0) and not ct._redundant(tight, 1)


def test_repair_tightens_the_spilling_pieces_only():
    """The greedy neighbours lose their spill; a piece that does not spill
    (offset 0, slack 0) is never rewritten, even when it is the swallowed one."""
    victim = ct.Piece(lo=2, hi=6, a=1, m=4, d=4, width=4, offset=0, slack=0)
    greedy = [ct.Piece(lo=-2, hi=2, a=1, m=1, d=99, width=4, offset=1, slack=1),
              victim,
              ct.Piece(lo=6, hi=10, a=1, m=9, d=99, width=4, offset=1, slack=1)]
    assert ct._redundant(greedy, 1)
    out = ct._repair_necessity(list(greedy))
    assert out[1] == victim, "a non-spilling piece must be untouched"
    assert out[0].repaired and out[2].repaired
    assert all(not ct._redundant(out, i) for i in range(3))


@pytest.mark.parametrize("k", KS)
def test_pieces_are_not_all_identical(k):
    """A case tree whose leaves are copies of one lemma is not a case tree."""
    for p in _problems(k):
        assert len({l.prop for l in p.oracle_plan.lemmas}) == k


# ------------------------------------------------------------------- V6 / meta


@pytest.mark.parametrize("k", KS)
def test_no_leaf_is_a_substring_of_the_goal_and_nothing_is_exempt(k):
    for p in _problems(k):
        assert p.meta["visible_lemmas"] == []
        g = normalize_statement(p.goal.prop)
        for l in p.oracle_plan.lemmas:
            assert normalize_statement(l.prop) not in g


@pytest.mark.parametrize("k", KS)
def test_band_hypotheses_are_absent_from_the_goal(k):
    """The split points are the invented content: the goal states exactly one
    upper bound on x — the domain's — and no interior band endpoint."""
    for p in _problems(k):
        assert p.goal.prop.count("x ≤ ") == 1
        for _, hi in p.meta["bands"][:-1]:
            assert hi != p.meta["domain"][1]
            assert f"x ≤ {hi} →" not in p.goal.prop


# --------------------------------------------------------------- flatness in k


def test_necessity_never_needs_repair_at_any_k():
    """The flatness claim's load-bearing invariant: necessity holds structurally
    (min width 6 > 2 × max spill 2.24), so the repair — which would tighten
    leaves at a k-dependent rate — never fires and the knob distribution is
    exactly the same at every k."""
    stats = ct.leaf_stats([p for k in (2, 4, 8, 16, 32) for p in ct.generate(k, seed=101, n=6)])
    assert {k: s["repaired_frac"] for k, s in stats.items()} == {k: 0.0 for k in stats}
    assert min(ct.WIDTHS) >= 6, "widths below 6 let a piece swallow a neighbour"


def test_leaf_schema_support_is_identical_across_k():
    stats = ct.leaf_stats([p for k in KS for p in _problems(k, seed=5, n=4)])
    assert set(stats) == set(KS)
    for k, s in stats.items():
        assert s["knob_support_ok"], k
        assert s["leaves"] == 4 * k


def test_leaf_length_is_near_flat_in_k():
    """Only the band's absolute position depends on k, so leaf props may grow by
    a few numeral digits — but not by a different schema. 16x the leaf count
    must not double the leaf statement."""
    stats = ct.leaf_stats([p for k in (2, 32) for p in ct.generate(k, seed=9, n=4)])
    lo, hi = stats[2]["leaf_len_mean"], stats[32]["leaf_len_mean"]
    assert hi / lo < 1.5, (lo, hi)


def test_knob_mix_is_drawn_from_the_same_support_at_every_k():
    """Same distribution, not merely same support: with enough leaves every k
    should exercise several distinct knob tuples."""
    for k in (2, 8, 32):
        s = ct.leaf_stats(ct.generate(k, seed=4, n=6))[k]
        assert s["distinct_knob_tuples"] >= min(6, s["leaves"])


def test_leaf_stats_reports_per_k():
    s = ct.leaf_stats(ct.generate(4, seed=1, n=3) + ct.generate(8, seed=1, n=3))
    assert sorted(s) == [4, 8]
    assert s[4]["problems"] == 3 and s[4]["leaves"] == 12
    assert s[8]["leaf_len_max"] >= s[8]["leaf_len_min"]


def test_scales_past_the_phase1_grid():
    """FAMILIES.md: the schema must not break at k=128 even if Phase 1 ships k≤32."""
    p = ct.build(128, 0)
    assert len(p.oracle_plan.lemmas) == 128
    assert "\n" not in p.goal.prop
    assert p.oracle_plan.assembly.count("rcases") == 127


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


def test_coeffs_reduce_to_one_covering_condition():
    """max and min variants differ by a sign; `holds_at` is variant-free."""
    p = ct.Piece(lo=0, hi=4, a=2, m=2, d=8, width=4, offset=0, slack=0)
    c2, c1, c0 = p.coeffs("max")
    assert (c2, c1, c0) == (-2, 8, ct.C_LEVEL + 8 - 8)
    d2, d1, d0 = p.coeffs("min")
    assert (d2, d1, d0) == (2, -8, 8 - 8 + ct.C_LEVEL)
    assert p.holds_at(2) and p.holds_at(0) and not p.holds_at(5)


# ------------------------------------------------------- validator, offline


def _wire_ok(fb) -> None:
    from rlmath.families.validate import battery_proofs

    fb.rule(lambda c: ":= sorry" in c, VerifyResult(ok=True, sorries=1))
    fb.rule(lambda c: any(p in c for p in battery_proofs()),
            VerifyResult(ok=False, sorries=0))
    fb.rule(lambda c: True, VerifyResult(ok=True, sorries=0))


@pytest.mark.parametrize("k", (2, 4, 8))
def test_validator_passes_on_a_scripted_backend(fake_backend, k):
    _wire_ok(fake_backend)
    for p in ct.generate(k, seed=2, n=1):
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
    part, and this box is shared with the sibling family agent."""
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
@pytest.mark.timeout(1800)
def test_leaves_resist_the_intro_first_battery_live():
    """A *stronger* battery than the contract's, self-imposed.

    None of `AUTOMATION_TACTICS` introduces the leading `∀`/`→`, so V5 alone
    cannot distinguish a genuinely hard band from a `linarith` one-liner wearing
    a quantifier (measured: an affine band passes V5 and dies to
    `intro; linarith`). This family's leaves are quadratic so that they survive
    the battery *after* `intro` too — which is what makes a future widening of
    AUTOMATION_TACTICS safe for banks generated today. Run on real generated
    goals and leaves at both ends of the k-grid, not on hand-picked samples.
    """
    from rlmath.core import leancode

    props: list[tuple[str, str]] = []
    for k in (2, 32):
        p = ct.build(k, 3000, 0)
        props.append((f"k{k}-goal", p.goal.prop))
        props.append((f"k{k}-leaf-first", p.oracle_plan.lemmas[0].prop))
        props.append((f"k{k}-leaf-last", p.oracle_plan.lemmas[-1].prop))

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
