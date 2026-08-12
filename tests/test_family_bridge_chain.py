"""Family A (bridge_chain) — offline structural tests + one live integration pass.

Everything except the two marked tests runs with no Lean toolchain: the family's
contract (determinism, witness-key match, single-line props, hidden intermediates,
per-node flatness) is decidable from the emitted objects alone. The Lean-dependent
half of the contract (V0–V6) is measured by validate_problem and is exercised here
on two problems; the full measured table lives in research/family-bridge-chain.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import rlmath.families.bridge_chain as bc
from rlmath.core.types import normalize_statement, statement_key
from rlmath.families import REGISTRY, validate_problem
from rlmath.lean.repl_pool import ReplConfig, ReplPool

K_GRID = (2, 4, 8)
ROOT = Path(__file__).resolve().parent.parent


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
# difficulty presets (2026-08-12 retune) — offline half
#
# The measured finding these exist for: flatness PASSES but the level does not
# (per-leaf pass@8 ~0.13, below the 0.25 corridor floor — OVERNIGHT.md). A
# preset changes the draw distribution only, so the tests below assert (a) the
# default is byte-identical to the pre-preset generator, (b) no preset can turn
# off the two invariants that defeat the automation battery, and (c) each
# candidate really is easier on the *measured* lever it claims.
# --------------------------------------------------------------------------

EASIER = tuple(n for n in bc.PRESETS if n != bc.DEFAULT_PRESET)


def _preset_problems(name: str, k_grid=K_GRID, n: int = 3) -> list:
    return [p for k in k_grid for p in bc.generate(k, seed=4242, n=n, preset=name)]


def test_default_preset_is_v2_and_its_output_is_byte_identical():
    """The retune must not move the shipped dataset. Explicit-v2 and no-preset
    calls agree, and the golden values above (seed 42, k=3) still hold — that
    golden test is the one thing standing between a knob refactor and a silently
    regenerated Phase-1 dataset."""
    assert bc.DEFAULT_PRESET == "v2" and bc.PRESETS["v2"].is_default
    for k, seed in ((2, 7), (4, 5), (8, 2026)):
        a = bc.generate(k, seed=seed, n=3)
        b = bc.generate(k, seed=seed, n=3, preset="v2")
        c = bc.generate(k, seed=seed, n=3, preset=bc.PRESETS["v2"])
        for x, y, z in zip(a, b, c):
            assert x.id == y.id == z.id
            assert x.goal.prop == y.goal.prop == z.goal.prop
            assert x.goal.name == y.goal.name == z.goal.name
            assert x.witness_proofs() == y.witness_proofs() == z.witness_proofs()
            assert [l.prop for l in x.oracle_plan.lemmas] == [l.prop for l in y.oracle_plan.lemmas]


def test_v2_ids_and_declaration_names_carry_no_preset_tag():
    """Only non-default presets are tagged, so v2 ids/`theorem` names — which
    already exist in data/families/ and in the measured calibration rows — are
    unchanged, while two presets can still be materialized side by side."""
    v2 = bc.generate(2, seed=4242, n=1)[0]
    assert v2.id == "bridge_chain-k2-s4242-0" and v2.goal.name == "bridge_k2_s4242_0"
    ids = {name: bc.generate(2, seed=4242, n=1, preset=name)[0] for name in bc.PRESETS}
    assert len({p.id for p in ids.values()}) == len(bc.PRESETS)
    assert len({p.goal.name for p in ids.values()}) == len(bc.PRESETS)
    for name, p in ids.items():
        if name != bc.DEFAULT_PRESET:
            assert p.id == f"bridge_chain-{name}-k2-s4242-0"
            assert p.meta["preset"] == name


def test_no_preset_can_switch_off_the_battery_invariants():
    """CRITICAL and not negotiable by knob: every preset keeps named-function
    content on every term (the `gcongr` anti-unification barrier) and the
    per-step congruence gate (the measured fix for v1's 16 kills). A preset that
    relaxed either would be measuring tactic dispatch, not decomposition."""
    for name, preset in bc.PRESETS.items():
        assert preset.funcs and set(preset.funcs) <= set(bc.FUNCS), name
        for p in _preset_problems(name, n=2):
            assert bc.check_preset_invariants(p) == [], (name, p.id)
            for prop in [p.goal.prop] + [l.prop for l in p.oracle_plan.lemmas]:
                assert prop.count("Real.sqrt (") + prop.count("Real.log (") == 2, (name, prop)
            knobs = [(kb["c"], kb["d"], kb["o"]) for kb in p.meta["knobs"]]
            for prev, new in zip(knobs, knobs[1:]):
                assert bc.step_resists_congruence(prev, new), (name, prev, new)


def test_a_preset_that_drops_named_functions_is_rejected_at_construction():
    """The tripwire for the invariant above: it must be impossible to *declare*
    a function-free preset, not merely unusual."""
    with pytest.raises(ValueError, match="funcs"):
        bc.DifficultyPreset(name="bad", rationale="", funcs=())
    with pytest.raises(ValueError, match="funcs"):
        bc.DifficultyPreset(name="bad", rationale="", funcs=("cos",))
    with pytest.raises(ValueError, match="deltas"):
        bc.DifficultyPreset(name="bad", rationale="", deltas=())
    with pytest.raises(ValueError, match="preset name"):
        bc.DifficultyPreset(name="Bad-Name", rationale="")
    with pytest.raises(ValueError, match="unknown bridge_chain preset"):
        bc.generate(2, seed=1, n=1, preset="nope")


def test_every_candidate_preset_is_easier_on_its_measured_lever():
    """Each easier preset must actually move the knob its rationale cites —
    otherwise the GPU session measures a relabelled v2. Levers and their measured
    effect sizes are in the module docstring (n=58 calibrated leaves)."""
    stats = {name: bc.leaf_shape_stats(_preset_problems(name, n=4)) for name in bc.PRESETS}
    for name in EASIER:
        # lever 1: no `Real.log` on the right of any step (unconditional non-negativity)
        for p in _preset_problems(name, n=2):
            assert set(p.meta["funcs"]) == {"sqrt"}, name
    for name in ("e2_flatstep", "e3_lowdeg", "e4_slack"):
        # lever 2: δ=1 only, so exponents grow half as fast along the chain
        assert bc.PRESETS[name].deltas == (1,)
        for k in K_GRID:
            assert set(stats[name][k]["delta_mix"]) == {1}
    # lever 3: e3 keeps the monomial small — the dominant measured correlate
    for k in K_GRID:
        assert (stats["e3_lowdeg"][k]["exponent_sums"]["mean"]
                < stats["e2_flatstep"][k]["exponent_sums"]["mean"]
                <= stats["v2"][k]["exponent_sums"]["mean"]), k
    # lever 4: e4 never pays an offset drop out of the multiplicative gain
    for p in _preset_problems("e4_slack", n=3):
        offsets = {kb["o"] for kb in p.meta["knobs"]}
        assert offsets == {bc.PRESETS["e4_slack"].offset_range[0]}, offsets


def test_live_states_is_a_fixpoint_and_v2_reduces_to_the_known_corner():
    """v2's single excluded corner is a special case of the general rule; a
    narrower preset strands more states (with a fixed offset, nothing can drop
    below the floor of c AND d), and a state whose only successors are dead ends
    is itself dead — hence a fixpoint, not one filtering pass."""
    assert bc.dead_end_states(bc.PRESETS["v2"]) == frozenset({bc._CORNER})
    assert bc.dead_end_states(bc.PRESETS["e4_slack"]) == frozenset({(2, 1, 5)})
    for name, preset in bc.PRESETS.items():
        live = bc.live_states(preset)
        for s in live:                      # the fixpoint property itself
            for delta in preset.deltas:
                assert any(t in live and bc._valid(s, t, delta)
                           and bc.step_resists_congruence(s, t) for t in live), (name, s, delta)
        for p in _preset_problems(name, n=2):
            for kb in p.meta["knobs"]:      # nothing outside it is ever emitted
                assert (kb["c"], kb["d"], kb["o"]) in live, (name, kb)


def test_presets_are_deterministic_and_mutually_distinct():
    for name in bc.PRESETS:
        assert [p.goal.prop for p in bc.generate(4, seed=9, n=3, preset=name)] == \
               [p.goal.prop for p in bc.generate(4, seed=9, n=3, preset=name)]
    goals = {name: bc.generate(4, seed=9, n=1, preset=name)[0].goal.prop for name in bc.PRESETS}
    assert len(set(goals.values())) == len(bc.PRESETS), goals


def test_preset_knobs_travel_on_the_row():
    """A dataset row must say which distribution produced it without a lookup
    against this file — the measured bank is joined back onto these knobs."""
    p = bc.generate(2, seed=4242, n=1, preset="e3_lowdeg")[0]
    assert p.meta["preset"] == "e3_lowdeg"
    assert p.meta["preset_knobs"]["funcs"] == ["sqrt"]
    assert p.meta["preset_knobs"]["deltas"] == [1]
    assert p.meta["preset_knobs"]["start_exponents"] == [1, 0, 0]
    assert p.meta["preset_knobs"]["lower_bound"] == bc.LOWER


def test_leaf_shape_stats_reports_the_presets_own_support():
    """A δ=1-only preset must not report a phantom `{2: 0}` column, and v2-only
    input must keep the histogram the v2 datasheet was built from."""
    v2 = bc.leaf_shape_stats(_preset_problems("v2", n=3))
    assert set(v2[2]["delta_mix"]) == set(bc.DELTAS)
    assert set(v2[2]["func_mix"]) == set(bc.FUNCS)
    e2 = bc.leaf_shape_stats(_preset_problems("e2_flatstep", n=3))
    assert set(e2[2]["delta_mix"]) == {1}
    assert set(e2[2]["func_mix"]) == {"sqrt"}
    mixed = bc.leaf_shape_stats(_preset_problems("v2", n=2) + _preset_problems("e2_flatstep", n=2))
    assert set(mixed[2]["delta_mix"]) == set(bc.DELTAS)


def test_check_preset_invariants_catches_a_broken_step():
    """The offline gate the staging script trusts must actually fire."""
    p = bc.generate(4, seed=4242, n=1, preset="e2_flatstep")[0]
    assert bc.check_preset_invariants(p) == []
    p.meta["knobs"][1] = dict(p.meta["knobs"][0])          # kills the coefficient drop
    viol = bc.check_preset_invariants(p)
    assert any("congruence gate" in v for v in viol), viol


def test_presets_scale_past_the_phase1_grid():
    """A retune must not narrow the schema's reach: k=32 still generates for
    every preset (the sampler cannot stall, the gates still admit a chain)."""
    for name in bc.PRESETS:
        p = bc.generate(32, seed=3, n=1, preset=name)[0]
        assert len(p.oracle_plan.lemmas) == 32
        assert bc.check_preset_invariants(p) == []


# --------------------------------------------------------------------------
# scripts/stage_retune_candidates.py — offline half
# --------------------------------------------------------------------------

def _load_script(stem: str, alias: str):
    """Load a `scripts/` entry point by path (test_scripts.py's pattern), with
    the module registered in `sys.modules` first — `@dataclass` resolves its
    annotations through `sys.modules[cls.__module__]` and raises without it."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(alias, ROOT / "scripts" / f"{stem}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_stage_script():
    return _load_script("stage_retune_candidates", "_script_stage_retune")


def test_staged_rows_are_build_bank_ingestable(tmp_path):
    """The pod runs `build_bank.py --dataset json --data-files <this file>`, so
    the row must survive build_bank's own extractor untouched — a leading
    `theorem` or a stray `:=` would silently drop every candidate."""
    stage = _load_stage_script()
    bb = _load_script("build_bank", "_script_bb_retune")

    cands, _, _ = stage.candidates_for_preset("e2_flatstep", k_grid=(2, 4), per_preset=6)
    rows = stage.candidate_rows(cands)
    for row in rows:
        assert bb.extract_prop(row) == row["formal_statement"]
        assert bb.source_id(row, "json", 0) == f"json#{row['id']}"
        assert row["statement_key"] == statement_key(row["formal_statement"])
        assert set(row) >= {"formal_statement", "id", "preset", "k", "position", "es_left"}
        assert all(not isinstance(v, (dict, list)) for v in row.values()), "flat columns only"


def test_staged_candidates_are_deduped_and_k_mixed():
    stage = _load_stage_script()
    for name in bc.PRESETS:
        cands, problems, stats = stage.candidates_for_preset(name, per_preset=30)
        assert len({c.key for c in cands}) == len(cands) == 30, name
        assert {c.k for c in cands} == set(K_GRID), name
        assert all(v == [] for v in (bc.check_preset_invariants(p) for p in problems)), name
        assert stats["emitted"] == 30


def test_knob_columns_are_parsed_from_the_emitted_text():
    """Parsed from the rendered statement, not from meta: a rendering bug must
    show up as a knob mismatch instead of travelling into the analysis."""
    stage = _load_stage_script()
    p = bc.generate(2, seed=4242, n=1, preset="v2")[0]
    cols = stage._knobs_of(p.oracle_plan.lemmas[0].prop)
    kb0, kb1 = p.meta["knobs"][0], p.meta["knobs"][1]
    assert (cols["c_left"], cols["d_left"], cols["o_left"]) == (kb0["c"], kb0["d"], kb0["o"])
    assert (cols["c_right"], cols["d_right"], cols["o_right"]) == (kb1["c"], kb1["d"], kb1["o"])
    assert cols["func_left"] == kb0["func"] and cols["func_right"] == kb1["func"]
    assert cols["es_left"] == p.meta["exponent_sums"][0]
    assert cols["delta"] == p.meta["step_kinds"][0][1]


def test_battery_subset_brackets_the_within_chain_gradient():
    """Battery risk lives at the small-monomial end, witness risk at the far end;
    the probe set must contain both extremes at every k, not a random sample."""
    stage = _load_stage_script()
    cands, _, _ = stage.candidates_for_preset("v2", per_preset=30)
    subset = stage.battery_subset(cands, 6)
    assert len(subset) == 6 and {c.k for c in subset} == set(K_GRID)
    for k in K_GRID:
        es = [stage._knobs_of(c.prop)["es_left"] for c in cands if c.k == k]
        picked = [stage._knobs_of(c.prop)["es_left"] for c in subset if c.k == k]
        assert min(picked) == min(es) and max(picked) == max(es), k


def test_stage_script_writes_a_candidates_file_without_lean(tmp_path):
    stage = _load_stage_script()
    rc = stage.main(["--presets", "v2,e3_lowdeg", "--per-preset", "6", "--k-grid", "2,4",
                     "--out-dir", str(tmp_path)])
    assert rc == 0
    rows = [json.loads(line)
            for line in (tmp_path / "retune_candidates.jsonl").read_text().splitlines()]
    assert {r["preset"] for r in rows} == {"v2", "e3_lowdeg"}
    assert len(rows) == 12 and len({r["id"] for r in rows}) == 12
    for name in ("v2", "e3_lowdeg"):
        probe = (tmp_path / "retune_battery" / f"{name}.jsonl").read_text().splitlines()
        assert 0 < len(probe) <= 6
    assert not (tmp_path / "retune_battery" / "battery.json").exists(), "battery needs Lean"


def test_stage_script_refuses_a_preset_whose_invariants_break(monkeypatch, tmp_path):
    """An invariant violation is a generator bug, not a difficulty finding: the
    script must fail loudly rather than ship a battery-soluble leaf to the pod
    under an 'easier preset' label."""
    stage = _load_stage_script()
    monkeypatch.setattr(bc, "check_preset_invariants", lambda p: ["planted violation"])
    assert stage.main(["--presets", "v2", "--per-preset", "4", "--k-grid", "2",
                       "--out-dir", str(tmp_path)]) == 2
    assert not (tmp_path / "retune_candidates.jsonl").exists()


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
def test_every_preset_survives_the_battery_and_its_witnesses_check():
    """The retune gate, live and cheap (research/retune-notes.md §4).

    One leaf per preset plus the known-dead control: an easier preset is only a
    difficulty candidate if its leaves still resist all 20 battery proofs *and*
    the generator's own witness still kernel-checks. The full 6-leaf-per-preset
    table is what `scripts/stage_retune_candidates.py --with-battery` produces;
    this is the regression tripwire for a Mathlib change that softens one of the
    candidate distributions.
    """
    stage = _load_stage_script()
    pool = ReplPool(n_workers=2)
    try:
        pool.warm()
        report = stage.gate_presets(
            pool,
            {name: dict(zip(("candidates", "problems", "stats"),
                            stage.candidates_for_preset(name, k_grid=(2,), per_preset=2)))
             for name in bc.PRESETS},
            battery_n=1,
        )
    finally:
        pool.close()
    assert report["_control"]["probes"][0]["killers"], "the known-dead control survived"
    for name in bc.PRESETS:
        assert report[name]["kills"] == [], (name, report[name]["probes"])
        assert report[name]["witness_failures"] == [], (name, report[name]["probes"])


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
