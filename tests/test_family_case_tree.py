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

import pytest

from rlmath.core.plan_format import parse_plan
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
def test_variant_glue_matches_the_goal_connective(k):
    for p in _problems(k):
        variant = p.meta["variant"]
        assert variant in ct.VARIANTS
        left, right = ct._GLUE[variant]
        assert f" {variant} (" in p.goal.prop
        assert left in p.oracle_plan.assembly
        if k > 1:
            assert right in p.oracle_plan.assembly


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
    for p in _problems(k):
        pieces = ct._sample_pieces(k, ct._rng(k, p.seed, int(p.id.rsplit("-", 1)[1])))
        assert all(q.covers_band for q in pieces)


@pytest.mark.parametrize("k", KS)
def test_every_case_is_necessary(k):
    """No piece may be redundant — a redundant piece would make a k-leaf plan a
    dressed-up (k-1)-leaf problem and silently flatten the size axis."""
    for p in _problems(k):
        pieces = ct._sample_pieces(k, ct._rng(k, p.seed, int(p.id.rsplit("-", 1)[1])))
        for i in range(k):
            assert not ct._redundant(pieces, i), f"piece {i} is covered by its neighbours"


def test_redundancy_detector_actually_fires():
    """Guard the guard: two identical wide pieces on adjacent narrow bands are
    mutually redundant, and _redundant must say so."""
    wide = [ct.Piece(lo=0, hi=2, a=1, m=1, d=99, width=2, offset=0, slack=0),
            ct.Piece(lo=2, hi=4, a=1, m=3, d=99, width=2, offset=0, slack=0)]
    assert ct._redundant(wide, 0) and ct._redundant(wide, 1)
    tight = [ct.Piece(lo=0, hi=2, a=1, m=1, d=1, width=2, offset=0, slack=0),
             ct.Piece(lo=2, hi=4, a=1, m=3, d=1, width=2, offset=0, slack=0)]
    assert not ct._redundant(tight, 0) and not ct._redundant(tight, 1)


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
    """The split points are the invented content: no interior band endpoint may
    appear as a bound in the goal (only the domain endpoints do)."""
    for p in _problems(k):
        for lo, hi in p.meta["bands"][:-1]:
            assert f"x ≤ {hi} →" not in p.goal.prop or hi == p.meta["domain"][1]


# --------------------------------------------------------------- flatness in k


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
    """`le_or_gt x -5` is a subtraction; `le_or_gt x (-5)` is the split."""
    assert ct._num(-5) == "(-5)" and ct._num(5) == "5"
    asm = ct.build(4, 7).oracle_plan.assembly
    assert " -" not in asm.replace("· ", "")  # no bare negative in application position


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
    fb.rule(lambda c: ":= sorry" in c, VerifyResult(ok=True, sorries=1))
    fb.rule(lambda c: any(f"by {t}" in c for t in AUTOMATION_TACTICS),
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


@pytest.mark.integration
@needs_lean
@pytest.mark.timeout(1800)
def test_two_problems_pass_the_full_validator_live():
    """The whole contract, V0–V6, against Mathlib: one problem per variant.

    Two workers max — this box is shared with the sibling family agent.
    """
    problems = [ct.build(2, 11, 0), ct.build(4, 11, 0)]
    assert {p.meta["variant"] for p in problems} <= set(ct.VARIANTS)
    pool = ReplPool(n_workers=2)
    try:
        for p in problems:
            report = validate_problem(p, pool, check_automation=True, timeout_s=180)
            assert report.ok, f"{p.id}: {[(c.name, c.detail) for c in report.failed()]}"
    finally:
        pool.close()
