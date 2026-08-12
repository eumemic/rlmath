"""Family A (bridge_chain) — offline structural tests + one live integration pass.

Everything except the two marked tests runs with no Lean toolchain: the family's
contract (determinism, witness-key match, single-line props, hidden intermediates,
per-node flatness) is decidable from the emitted objects alone. The Lean-dependent
half of the contract (V0–V6) is measured by validate_problem and is exercised here
on two problems; the full measured table lives in research/family-bridge-chain.md.
"""
from __future__ import annotations

import pytest

import rlmath.families.bridge_chain as bc
from rlmath.core.types import normalize_statement
from rlmath.families import REGISTRY, validate_problem
from rlmath.lean.repl_pool import ReplConfig, ReplPool

K_GRID = (2, 4, 8)


@pytest.fixture(scope="module")
def problems() -> list:
    return [p for k in K_GRID for p in bc.generate(k, seed=2026, n=3)]


# --- registration ----------------------------------------------------------

def test_registered_at_import():
    assert REGISTRY["bridge_chain"] is bc.generate


def test_rejects_k_below_two():
    with pytest.raises(ValueError, match="k >= 2"):
        bc.generate(1, seed=0, n=1)


# --- determinism -----------------------------------------------------------

def test_output_is_a_pure_function_of_k_and_seed():
    a = bc.generate(4, seed=5, n=3)
    b = bc.generate(4, seed=5, n=3)
    assert [p.id for p in a] == [p.id for p in b]
    assert [p.goal.prop for p in a] == [p.goal.prop for p in b]
    assert [[l.prop for l in p.oracle_plan.lemmas] for p in a] == \
           [[l.prop for l in p.oracle_plan.lemmas] for p in b]
    assert [p.witness_proofs() for p in a] == [p.witness_proofs() for p in b]


def test_determinism_is_stable_across_processes():
    """A golden value, not just self-consistency within one interpreter: a dataset
    regenerated next month, on another machine, must be the same dataset. (Since
    Python 3.2 `random.Random(str)` seeds from a sha512 of the string rather than
    `hash()`, so this is stable under PYTHONHASHSEED — pinned rather than assumed.)"""
    p = bc.generate(3, seed=42, n=1)[0]
    assert p.goal.prop == (
        "∀ x y z : ℝ, 3 ≤ x → 3 ≤ y → 3 ≤ z → "
        "8 * x ^ 1 * y ^ 1 * z ^ 1 + 8 * Real.sqrt (x ^ 1 * y ^ 1 * z ^ 1) + 5 ≤ "
        "6 * x ^ 1 * y ^ 1 * z ^ 6 + 4 * Real.log (x ^ 1 * y ^ 1 * z ^ 6) + 5"
    )
    assert p.oracle_plan.lemmas[1].prop == (
        "∀ x y z : ℝ, 3 ≤ x → 3 ≤ y → 3 ≤ z → "
        "7 * x ^ 1 * y ^ 1 * z ^ 2 + 9 * Real.sqrt (x ^ 1 * y ^ 1 * z ^ 2) + 1 ≤ "
        "9 * x ^ 1 * y ^ 1 * z ^ 4 + 5 * Real.log (x ^ 1 * y ^ 1 * z ^ 4) + 9"
    )


def test_different_seeds_give_different_chains():
    a = bc.generate(4, seed=5, n=1)[0]
    b = bc.generate(4, seed=6, n=1)[0]
    assert a.goal.prop != b.goal.prop


def test_prefix_stability_in_n():
    """generate(k, seed, n) must extend, not reshuffle: problem i is seeded from i."""
    few = bc.generate(4, seed=5, n=2)
    many = bc.generate(4, seed=5, n=5)
    assert [p.goal.prop for p in few] == [p.goal.prop for p in many[:2]]


# --- contract shape --------------------------------------------------------

def test_ids_and_counts(problems):
    for p in problems:
        assert p.family == "bridge_chain"
        assert p.id.startswith(f"bridge_chain-k{p.k}-s{p.seed}-")
        assert len(p.oracle_plan.lemmas) == p.k


def test_witness_keys_match_plan_lemma_names(problems):
    """The structural precondition validate_problem short-circuits on."""
    for p in problems:
        names = [l.name for l in p.oracle_plan.lemmas]
        assert len(names) == len(set(names))
        assert set(names) == set(p.witnesses)
        for l in p.oracle_plan.lemmas:
            assert p.witnesses[l.name].prop == l.prop


def test_every_term_carries_a_named_function(problems):
    """v2's named-function content is a schema invariant, not a decoration: a
    silent regression to v1's `c·M + d` re-opens the 16 measured `intros; gcongr
    <;> linarith` kills and must fail offline, not at the next live sweep."""
    for p in problems:
        for prop in [p.goal.prop] + [l.prop for l in p.oracle_plan.lemmas]:
            assert prop.count("Real.sqrt (") + prop.count("Real.log (") == 2, prop
        for w in p.witnesses.values():
            # the two function facts the final linarith consumes
            assert " hfu :" in w.proof and " hfl :" in w.proof
            assert "nlinarith" not in w.proof, "v1's maxHeartbeats lesson"


def test_props_are_single_line_and_closed(problems):
    """Wire format (core/plan_format.py) is line-oriented: a newline in a prop would
    silently truncate a policy-emitted #lemma line, so generator props must be flat."""
    for p in problems:
        for prop in [p.goal.prop] + [l.prop for l in p.oracle_plan.lemmas]:
            assert "\n" not in prop
            assert prop.startswith("∀ x y z : ℝ,")
            assert prop == prop.strip()


def test_lemma_names_survive_the_plan_parser(problems):
    from rlmath.core.plan_format import parse_plan

    for p in problems:
        wire = "".join(f"#lemma {l.name} : {l.prop}\n" for l in p.oracle_plan.lemmas)
        wire += "#assembly\n" + p.oracle_plan.assembly + "\n#end\n"
        parsed = parse_plan(wire)
        assert [(l.name, l.prop) for l in parsed.lemmas] == \
               [(l.name, l.prop) for l in p.oracle_plan.lemmas]
        assert parsed.assembly.strip() == p.oracle_plan.assembly.strip()


# --- the chain is really a chain ------------------------------------------

def test_consecutive_lemmas_share_an_endpoint(problems):
    """h_i's right-hand term is h_{i+1}'s left-hand term — otherwise transitivity in
    the assembly could not close, and the plan would be valid only by accident."""
    def sides(prop: str) -> tuple[str, str]:
        body = prop.removeprefix(bc.BINDER)
        assert body != prop, prop
        lhs, rhs = body.split(" ≤ ")
        return lhs, rhs

    for p in problems:
        chain = [sides(l.prop) for l in p.oracle_plan.lemmas]
        for (_, right), (left, _) in zip(chain, chain[1:]):
            assert right == left
        assert sides(p.goal.prop) == (chain[0][0], chain[-1][1])


def test_exponent_sums_strictly_increase(problems):
    for p in problems:
        sums = p.meta["exponent_sums"]
        assert all(b > a for a, b in zip(sums, sums[1:]))
        assert len(sums) == p.k + 1


def test_assembly_is_pure_transitivity(problems):
    """No term text in the assembly: all invented content must live in the lemmas."""
    for p in problems:
        asm = p.oracle_plan.assembly
        assert asm.count("le_trans") == p.k - 1
        for term in p.meta["intermediate_terms"] + p.meta["endpoint_terms"]:
            assert term not in asm


@pytest.mark.parametrize("k", (2, 4, 8, 16, 32, 128))
def test_the_le_trans_fold_is_balanced(k):
    """Elaboration cost, measured: v1's right-nested fold put step i at depth i and
    at k=32 tipped V3/V4 over PREAMBLE's `maxHeartbeats 400000`
    (`(deterministic) timeout at «synthesize pending MVars»`) with every leaf still
    checking individually. Depth must be ⌈log₂ k⌉, not k."""
    import math

    asm = bc.generate(k, seed=13, n=1)[0].oracle_plan.assembly
    depth = maxdepth = 0
    for ch in asm.split("\n")[-1]:
        if ch == "(":
            depth += 1
            maxdepth = max(maxdepth, depth)
        elif ch == ")":
            depth -= 1
    # one paren level per tree level, plus one for the leaf application itself
    assert maxdepth <= math.ceil(math.log2(k)) + 2, (k, maxdepth)


# --- V6 pre-check, no Lean -------------------------------------------------

def test_no_hidden_intermediate_violations(problems):
    for p in problems:
        assert bc.hidden_intermediate_violations(p) == []


def test_v6_holds_verbatim_as_validate_py_computes_it(problems):
    """Mirror of validate.py's V6 so a drift in either side shows up offline."""
    for p in problems:
        goal_norm = normalize_statement(p.goal.prop)
        for l in p.oracle_plan.lemmas:
            assert normalize_statement(l.prop) not in goal_norm


def test_intermediate_terms_are_absent_from_the_goal(problems):
    """The family's actual claim, stronger than V6: a policy cannot copy an
    intermediate out of the statement, because none of them occurs there."""
    for p in problems:
        assert len(p.meta["intermediate_terms"]) == p.k - 1
        for term in p.meta["intermediate_terms"]:
            assert term not in p.goal.prop
        for term in p.meta["endpoint_terms"]:
            assert term in p.goal.prop


def test_pre_check_catches_a_planted_restatement():
    """The tripwire must actually fire — otherwise the clean runs prove nothing."""
    p = bc.generate(4, seed=5, n=1)[0]
    p.meta["intermediate_terms"].append(p.meta["endpoint_terms"][0])
    assert any("occurs in the goal" in v for v in bc.hidden_intermediate_violations(p))


# --- per-node flatness -----------------------------------------------------

def test_leaf_prop_length_is_flat_in_k(problems):
    """FAMILIES.md 'Scaling requirements': leaf statements at large k must come from
    the same step-schema distribution as at k=2. Only exponent *digits* may grow."""
    stats = bc.leaf_shape_stats(problems)
    assert set(stats) == set(K_GRID)
    base = stats[K_GRID[0]]["leaf_prop_chars"]["median"]
    for k in K_GRID:
        chars = stats[k]["leaf_prop_chars"]
        assert abs(chars["median"] - base) <= 2, (k, chars)
        assert chars["max"] - chars["min"] <= 6, (k, chars)


def test_step_schema_knobs_are_k_independent(problems):
    """Same knobs at every k: only the number of composed steps changes."""
    for p in problems:
        assert p.meta["schema"] == bc.SCHEMA
        assert p.meta["lower_bound"] == bc.LOWER
        for j, delta in p.meta["step_kinds"]:
            assert 0 <= j < len(bc.VARS)
            assert delta in bc.DELTAS
        for kb in p.meta["knobs"]:
            assert bc.COEF_RANGE[0] <= kb["c"] <= bc.COEF_RANGE[1]
            assert bc.FCOEF_RANGE[0] <= kb["d"] <= bc.FCOEF_RANGE[1]
            assert bc.OFFSET_RANGE[0] <= kb["o"] <= bc.OFFSET_RANGE[1]
            assert kb["func"] in bc.FUNCS


def test_both_named_functions_appear_at_every_k(problems):
    """v2's leaf distribution is a mixture over {Real.sqrt, Real.log}; if one arm
    vanished the mixture would differ from the one measured in the design log."""
    stats = bc.leaf_shape_stats(problems)
    for k in K_GRID:
        mix = stats[k]["func_mix"]
        assert set(mix) == set(bc.FUNCS)
        assert all(v > 0 for v in mix.values()), (k, mix)


def test_sampling_constraint_holds_on_every_step(problems):
    """The constraint is what makes each witness a linarith over four atoms; if
    sampling drifts past it, witnesses fail at V2 with no offline warning."""
    for p in problems:
        knobs = [(kb["c"], kb["d"], kb["o"]) for kb in p.meta["knobs"]]
        for i, (_, delta) in enumerate(p.meta["step_kinds"]):
            assert bc._valid(knobs[i], knobs[i + 1], delta), (p.id, i)


def test_every_step_resists_the_congruence_route(problems):
    """The v2 fix for the 16 measured `intros; gcongr <;> linarith` kills: at least
    one of (c, d, o) strictly drops across every step, so no gcongr template closes."""
    for p in problems:
        knobs = [(kb["c"], kb["d"], kb["o"]) for kb in p.meta["knobs"]]
        for prev, new in zip(knobs, knobs[1:]):
            assert bc.step_resists_congruence(prev, new), (p.id, prev, new)


def test_congruence_gate_rejects_a_uniformly_rising_step():
    """Pinned against the measurement: `4M + 2√M + 3 ≤ 9M' + 7√M' + 5` (everything
    rising, same function) fell to `intros; gcongr <;> linarith` in ~1 s."""
    assert not bc.step_resists_congruence((4, 2, 3), (9, 7, 5))
    assert not bc.step_resists_congruence((4, 2, 3), (4, 2, 3))
    assert bc.step_resists_congruence((9, 2, 3), (4, 7, 5))   # c drops
    assert bc.step_resists_congruence((4, 7, 3), (9, 2, 5))   # d drops
    assert bc.step_resists_congruence((4, 2, 5), (9, 7, 3))   # o drops


def test_every_non_corner_state_has_a_legal_successor():
    """Exhaustive: the sampler cannot stall. `_sample_chain` draws (c,d,o) by rejection
    against BOTH gates, so a state with zero legal successors would hit `_MAX_REJECTS`
    and raise — at some k, on some seed, long after the schema shipped. The corner is
    the only such state, and it is excluded from the sample space."""
    states = [(c, d, o)
              for c in range(*_incl(bc.COEF_RANGE))
              for d in range(*_incl(bc.FCOEF_RANGE))
              for o in range(*_incl(bc.OFFSET_RANGE))]
    assert bc._CORNER in states
    for prev in states:
        for delta in bc.DELTAS:
            ok = [s for s in states
                  if s != bc._CORNER and bc._valid(prev, s, delta)
                  and bc.step_resists_congruence(prev, s)]
            if prev == bc._CORNER:
                assert not ok, "the corner is supposed to be a dead end"
            else:
                assert ok, (prev, delta)


def _incl(r: tuple[int, int]) -> tuple[int, int]:
    return (r[0], r[1] + 1)


def test_the_gate_corner_is_excluded_from_the_sample_space(problems):
    """`(c,d,o) = (2,1,1)` has no legal successor (nothing can drop below the floor
    of all three ranges), so the sampler must never produce it."""
    for p in problems:
        for kb in p.meta["knobs"][:-1]:   # the last term needs no successor
            assert (kb["c"], kb["d"], kb["o"]) != bc._CORNER, p.id


def test_scales_past_the_phase1_grid():
    """§5.4(e): the schema must not break where full proof text exceeds the window."""
    p = bc.generate(128, seed=3, n=1)[0]
    assert len(p.oracle_plan.lemmas) == 128
    assert max(len(l.prop) for l in p.oracle_plan.lemmas) < 210
    assert bc.hidden_intermediate_violations(p) == []


def test_discards_and_resamples_are_reported(problems):
    """The datasheet needs a real discard rate, not an assumed one."""
    assert sum(p.meta["discards"] for p in problems) > 0, "endpoint gate should bite"
    for p in problems:
        assert p.meta["discards"] >= 0
        assert p.meta["resamples"] >= 0


def test_endpoints_resist_the_naive_flat_route(problems):
    """Every emitted problem must survive the endpoint gate — otherwise the goal falls
    to a k-independent `1 ≤ M₀` + `gcongr` + `linarith` proof (measured, see §4)."""
    for p in problems:
        first, last = p.meta["knobs"][0], p.meta["knobs"][-1]
        assert bc.endpoints_resist_naive_collapse(
            (first["c"], (1, 1, 1), first["d"], first["o"], first["func"]),
            (last["c"], (9, 9, 9), last["d"], last["o"], last["func"]))


def _t(c: int, exps: tuple[int, int, int], d: int, o: int, func: str = "sqrt") -> bc.Term:
    return (c, exps, d, o, func)


def test_endpoint_gate_rejects_the_collapsible_pair():
    """Pinned against the measurements in research/family-bridge-chain.md §4."""
    # fell to `1 ≤ M₀` + gcongr + linarith in 8 lines at k=8: coefficient grows
    assert not bc.endpoints_resist_naive_collapse(
        _t(4, (1, 1, 1), 2, 3), _t(6, (4, 3, 5), 2, 7))
    # coefficient grows, so a sharp enough bound on M₀ would still close it
    assert not bc.endpoints_resist_naive_collapse(
        _t(6, (1, 1, 1), 2, 9), _t(9, (16, 21, 14), 2, 4))
    # offset rises: gcongr on the monomials plus `o₀ ≤ o_k` closes it outright
    assert not bc.endpoints_resist_naive_collapse(
        _t(6, (1, 1, 1), 2, 2), _t(2, (6, 5, 4), 2, 8))
    # the named-function coefficient rises: same route, one summand further out
    assert not bc.endpoints_resist_naive_collapse(
        _t(6, (1, 1, 1), 2, 8), _t(2, (6, 5, 4), 5, 2))
    # emitted shape: c drops 6→2, d drops 5→2 and o drops 8→2 — 0/3 for every flat
    # route measured, at every k
    assert bc.endpoints_resist_naive_collapse(
        _t(6, (1, 1, 1), 5, 8), _t(2, (6, 5, 4), 2, 2))


# --- offline check of the Lean strings the harness will build --------------

def test_composed_artifact_is_a_single_theorem(problems):
    from rlmath.core import leancode
    from rlmath.sanitize import enforce_single_theorem, scan_source

    for p in problems:
        art = leancode.compose(p.goal, p.oracle_plan, p.witness_proofs())
        assert scan_source(art) == []
        assert enforce_single_theorem(art, p.goal.name) == []


# --------------------------------------------------------------------------
# integration — needs scripts/setup_lean.sh to have completed
# --------------------------------------------------------------------------

_cfg = ReplConfig()
needs_lean = pytest.mark.skipif(
    not _cfg.available(), reason=f"no lean project/repl binary at {_cfg.project_dir}"
)


@pytest.mark.integration
@needs_lean
@pytest.mark.timeout(1800)
def test_the_congruence_gate_is_what_survives_gcongr_linarith():
    """The v2 decision, pinned as a live A/B (research/family-v2-hardening.md §2).

    v1 lost 16 leaves to `intros; gcongr <;> linarith`: with every coefficient
    non-decreasing the step is pure relational congruence. This test asserts
    both halves — a uniformly-rising step dies, the emitted (gated) step
    survives the whole battery — so a Mathlib change that re-opens the route
    fails loudly instead of the family going soft.
    """
    from rlmath.core import leancode
    from rlmath.families.validate import battery_proofs

    rising = (f"{bc.BINDER}4 * x ^ 1 * y ^ 1 * z ^ 1 + 2 * Real.sqrt (x ^ 1 * y ^ 1 * z ^ 1)"
              " + 3 ≤ 9 * x ^ 2 * y ^ 1 * z ^ 1 + 7 * Real.sqrt (x ^ 2 * y ^ 1 * z ^ 1) + 5")
    pool = ReplPool(n_workers=2)
    try:
        res = pool.check(leancode.proof_check(rising, "by intros; gcongr <;> linarith"),
                         timeout_s=60.0)
        assert res.ok and res.sorries == 0, \
            "the uniformly-rising control no longer dies to gcongr <;> linarith"

        for k in (2, 8):
            p = bc.generate(k, seed=4242, n=1)[0]
            for prop in [l.prop for l in p.oracle_plan.lemmas[:3]]:
                codes = [leancode.proof_check(prop, b) for b in battery_proofs()]
                out = pool.check_many(codes, timeout_s=25.0)
                killers = [b for b, r in zip(battery_proofs(), out)
                           if r.ok and r.sorries == 0]
                assert not killers, f"{prop} closed by {killers}"
    finally:
        pool.close()


@pytest.mark.integration
@needs_lean
@pytest.mark.timeout(1800)
def test_live_validate_two_problems():
    """V0–V6 end to end, one small and one larger chain, automation battery on."""
    pool = ReplPool(n_workers=2)
    try:
        pool.warm()
        for problem in (bc.generate(2, seed=2026, n=1)[0], bc.generate(8, seed=2026, n=1)[0]):
            report = validate_problem(problem, pool, check_automation=True, timeout_s=180.0)
            assert report.ok, [(c.name, c.detail) for c in report.failed()]
            names = {c.name.split("[")[0] for c in report.checks}
            assert {"V0_goal_resists_automation", "V4_oracle_replay", "V5_leaf_resists",
                    "V6_hidden"} <= names
    finally:
        pool.close()
