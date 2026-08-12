"""Few-shot worked exemplars (src/rlmath/eval/exemplars.py) — DIRECTION §5.5 rung 1.5.

Offline by default: building an exemplar is pure Python (a family generator plus
`core.leancode`), so every property below — wire-format round trip, cross-arm
symmetry, sanitizer cleanliness, source hygiene — is checked with no kernel, no
network and no dataset write.

Two of these tests are the ones that matter for the science:

  * `test_exemplar_goal_is_absent_from_every_materialized_dataset` reads the real
    `data/families/**/k*.jsonl` (read-only) and asserts the exemplar seed does
    not collide with anything a cell might evaluate. The runner refuses a
    collision at run time; this catches one at commit time.
  * the `@pytest.mark.integration` test at the bottom replays each arm's worked
    example through that arm's own scorer against a live Lean toolchain. A
    worked example that does not itself verify would be teaching a wrong answer,
    and no offline test can catch that.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from rlmath import sanitize
from rlmath.core.leancode import compose
from rlmath.core.plan_format import parse_plan
from rlmath.core.types import (
    Budgets,
    DecompositionPlan,
    GoalSpec,
    LemmaSpec,
    Status,
    statement_key,
)
from rlmath.eval import arms
from rlmath.eval.exemplars import (
    DEFAULT_EXEMPLAR_K,
    DEFAULT_EXEMPLAR_SEED,
    build_exemplar,
    exemplar_provenance,
    load_exemplar_problem,
    render_plan,
)
from rlmath.families import REGISTRY
from rlmath.families.types import GeneratedProblem, LeafWitness
from rlmath.leaf.prompts import extract_proof

ROOT = Path(__file__).resolve().parent.parent
FAMILIES = sorted(REGISTRY)
ARMS = ["decomp", "direct"]


@pytest.fixture(scope="module")
def problems() -> dict[str, GeneratedProblem]:
    """One exemplar problem per family, at the shipped defaults."""
    return {f: load_exemplar_problem(f) for f in FAMILIES}


# ---------------------------------------------------------------------------
# Wire-format rendering (decomp): the exemplar must parse as what it renders
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("family", FAMILIES)
def test_render_plan_round_trips_through_the_wire_parser(family, problems):
    """`render_plan` is the inverse of `parse_plan`. An exemplar that did not
    parse back would be teaching a format the scorer rejects."""
    plan = problems[family].oracle_plan
    back = parse_plan(render_plan(plan))
    assert [(x.name, x.prop) for x in back.lemmas] == [(x.name, x.prop) for x in plan.lemmas]
    assert back.assembly == plan.assembly


@pytest.mark.parametrize("family", FAMILIES)
def test_decomp_exemplar_parses_back_into_the_oracle_plan(family, problems):
    """The whole block, prose and all: `parse_plan` tolerates chatter before the
    first marker and after `#end`, so the exemplar as sent is a valid plan."""
    problem = problems[family]
    back = parse_plan(build_exemplar(problem, "decomp"))
    assert [(x.name, x.prop) for x in back.lemmas] == [
        (x.name, x.prop) for x in problem.oracle_plan.lemmas
    ]
    assert back.assembly == problem.oracle_plan.assembly
    assert len(back.lemmas) == problem.k    # k leaves = k lemmas (FAMILIES.md)


def test_render_plan_refuses_shapes_the_wire_format_would_silently_mangle():
    """A multi-line prop or a `#`-leading assembly line would render a
    valid-looking but *different* plan; both are errors, not truncations."""
    with pytest.raises(ValueError, match="one line"):
        render_plan(DecompositionPlan(lemmas=[LemmaSpec("h1", "A\nB")], assembly="exact h1"))
    with pytest.raises(ValueError, match="marker"):
        render_plan(DecompositionPlan(lemmas=[], assembly="#assembly\nrfl"))


# ---------------------------------------------------------------------------
# Fenced rendering (direct): the exemplar must extract as a proof
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("family", FAMILIES)
def test_direct_exemplar_extracts_through_the_arm_s_own_parser(family, problems):
    """`leaf.prompts.extract_proof` is what the direct arm runs on a completion;
    the worked reply must survive it and yield the oracle's own proof body."""
    problem = problems[family]
    text = build_exemplar(problem, "direct")
    artifact = compose(problem.goal, problem.oracle_plan, problem.witness_proofs())

    assert "```lean4" in text and artifact in text
    proof = extract_proof(text)
    assert proof is not None
    # the body after `:=` of the composed artifact, not a restated header
    assert proof.startswith("by")
    assert "theorem" not in proof
    # and it is the artifact's own body, modulo the indentation extract_proof strips
    assert problem.oracle_plan.assembly.splitlines()[-1].strip() in proof


@pytest.mark.parametrize("family", FAMILIES)
def test_direct_exemplar_artifact_is_the_single_theorem_the_scorer_expects(family, problems):
    problem = problems[family]
    artifact = compose(problem.goal, problem.oracle_plan, problem.witness_proofs())
    assert sanitize.enforce_single_theorem(artifact, problem.goal.name) == []


# ---------------------------------------------------------------------------
# Symmetry: one problem, two arms, difference confined to the reply
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("family", FAMILIES)
def test_the_two_arms_share_their_question_half_and_differ_only_in_the_reply(family, problems):
    """The strategist's symmetry requirement, made mechanical: whatever the
    decomp arm is told about the example goal, the direct arm is told verbatim."""
    problem = problems[family]
    decomp = build_exemplar(problem, "decomp")
    direct = build_exemplar(problem, "direct")
    marker = "Correct reply:"

    assert decomp.split(marker)[0] == direct.split(marker)[0]
    assert problem.goal.prop in decomp and problem.goal.prop in direct
    # ... and each reply is in that arm's own action space, not the other's
    assert "#lemma" in decomp.split(marker)[1] and "```lean4" not in decomp
    assert "```lean4" in direct.split(marker)[1] and "#lemma" not in direct


@pytest.mark.parametrize("family", FAMILIES)
def test_the_direct_exemplar_never_shows_the_sorry_skeleton(family, problems):
    """The arm's real user turn presents the goal as `... := by sorry`; the
    worked example presents it as a proposition instead, so the block a root is
    invited to imitate contains no banned token (see the module docstring)."""
    assert "sorry" not in build_exemplar(problems[family], "direct")


# ---------------------------------------------------------------------------
# Determinism and sanitizer hygiene
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("arm", ARMS)
def test_exemplar_is_deterministic_in_family_k_seed_and_arm(family, arm):
    a = build_exemplar(load_exemplar_problem(family), arm)
    b = build_exemplar(load_exemplar_problem(family), arm)
    assert a == b
    assert a != build_exemplar(load_exemplar_problem(family, k=4), arm)
    assert a != build_exemplar(load_exemplar_problem(family, seed=1234), arm)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("arm", ARMS)
def test_exemplar_output_is_sanitizer_clean(family, arm, problems):
    """The worked reply is the text a root is most likely to copy verbatim, so a
    banned token in it would be an instruction to hack the reward."""
    assert sanitize.scan_source(build_exemplar(problems[family], arm)) == []


def _handmade(proof: str = "by rfl", prop: str = "A") -> GeneratedProblem:
    return GeneratedProblem(
        id="hand-0", family="hand", k=1, seed=0,
        goal=GoalSpec(id="hand-0", prop="P", name="hand_thm"),
        oracle_plan=DecompositionPlan(lemmas=[LemmaSpec("h1", prop)], assembly="exact h1"),
        witnesses={"h1": LeafWitness(prop=prop, proof=proof)},
    )


@pytest.mark.parametrize("arm,problem", [
    ("direct", _handmade(proof="by sorry")),          # a banned witness proof
    ("decomp", _handmade(prop="native_decide = 1")),  # a banned lemma statement
])
def test_a_dirty_exemplar_raises_rather_than_shipping(arm, problem):
    with pytest.raises(ValueError, match="sanitizer-clean"):
        build_exemplar(problem, arm)


def test_an_arm_with_no_matched_exemplar_is_a_loud_error(problems):
    """Adding an arm to `arms.ARMS` must force a decision about its matched
    example; a silent zero-shot fallback would break the comparison while the
    cell still called itself few-shot."""
    with pytest.raises(KeyError, match="no exemplar renderer"):
        build_exemplar(problems[FAMILIES[0]], "flat_best_of_n")


def test_every_shipped_arm_has_an_exemplar_renderer(problems):
    for arm in arms.ARMS:
        assert build_exemplar(problems[FAMILIES[0]], arm)


# ---------------------------------------------------------------------------
# Source hygiene: fresh from the REGISTRY, never from a materialized dataset
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("family", FAMILIES)
def test_load_exemplar_problem_is_the_registry_generator_at_the_dedicated_seed(family):
    got = load_exemplar_problem(family)
    want = REGISTRY[family](k=DEFAULT_EXEMPLAR_K, seed=DEFAULT_EXEMPLAR_SEED, n=1)[0]
    assert (got.family, got.k, got.seed) == (family, DEFAULT_EXEMPLAR_K, DEFAULT_EXEMPLAR_SEED)
    assert got.goal.prop == want.goal.prop
    assert got.witness_proofs() == want.witness_proofs()
    assert DEFAULT_EXEMPLAR_SEED == 999 and DEFAULT_EXEMPLAR_K == 2


@pytest.mark.parametrize("family", FAMILIES)
def test_load_exemplar_problem_reads_no_file_at_all(family, monkeypatch):
    """Generation, not dataset lookup — asserted by making every file read fail.

    An exemplar lifted out of `data/families/**` would put an eval item in the
    prompt; this is the mechanical version of that prohibition."""
    def no_open(*a, **kw):
        raise AssertionError("load_exemplar_problem must not read files")

    monkeypatch.setattr("builtins.open", no_open)
    monkeypatch.setattr(Path, "open", no_open)
    problem = load_exemplar_problem(family)
    assert problem.witnesses


@pytest.mark.parametrize("family", FAMILIES)
def test_load_exemplar_problem_rejects_an_unknown_family(family):
    with pytest.raises(ValueError, match="unknown family"):
        load_exemplar_problem(family + "_nope")


_DATASETS = sorted((ROOT / "data" / "families").glob("*/k*.jsonl"))


@pytest.mark.skipif(not _DATASETS, reason="no materialized family datasets in data/families")
@pytest.mark.parametrize("family", FAMILIES)
def test_exemplar_goal_is_absent_from_every_materialized_dataset(family):
    """The contamination property, checked against the real eval material.

    The runner re-checks this per cell (it must: datasets get regenerated), but
    a collision that exists at commit time is a fact about the seeds and should
    fail here, not on a rented GPU."""
    keys = {}
    for path in _DATASETS:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            goal = row.get("goal") or {}
            if goal.get("prop"):
                keys[statement_key(goal["prop"])] = f"{path.name}:{row.get('id')}"
    for k in (2, 4, 8):
        problem = load_exemplar_problem(family, k=k)
        hit = keys.get(statement_key(problem.goal.prop))
        assert hit is None, f"exemplar {problem.id} collides with eval problem {hit}"


def test_provenance_is_what_a_row_needs_to_regenerate_the_exemplar(problems):
    problem = problems[FAMILIES[0]]
    text = build_exemplar(problem, "decomp")
    prov = exemplar_provenance(problem, "decomp", text)
    assert prov == {
        "arm": "decomp",
        "family": problem.family,
        "k": problem.k,
        "seed": problem.seed,
        "problem_id": problem.id,
        "goal_statement_key": statement_key(problem.goal.prop),
        "goal_name": problem.goal.name,
        "chars": len(text),
    }
    regenerated = load_exemplar_problem(prov["family"], k=prov["k"], seed=prov["seed"])
    assert build_exemplar(regenerated, prov["arm"]) == text


# ---------------------------------------------------------------------------
# integration — needs scripts/setup_lean.sh to have completed
# ---------------------------------------------------------------------------

_HAS_LEAN = False
try:  # pragma: no cover - depends on the box
    from rlmath.lean.repl_pool import ReplConfig, ReplPool

    _HAS_LEAN = ReplConfig().available()
except Exception:  # pragma: no cover
    ReplPool = None  # type: ignore[assignment]

needs_lean = pytest.mark.skipif(not _HAS_LEAN, reason="no lean project/repl binary")


@dataclass
class _ReplayRoot:
    """`arms.RootClient` that answers with a fixed text (the exemplar itself)."""

    text: str
    model: str = "exemplar-replay"

    def complete(self, messages):
        return arms.RootCompletion(text=self.text, usage=arms.Usage(), finish_reason="stop")


@dataclass
class _WitnessLeaf:
    """A leaf prover that knows exactly the generator's witness proofs."""

    proofs: dict[str, str]

    def prove(self, prop: str, *, k: int, backend):
        @dataclass
        class R:
            proof: str | None
            attempts: int

        proof = self.proofs.get(prop)
        return R(proof=proof, attempts=1 if proof else k)


@pytest.mark.integration
@needs_lean
@pytest.mark.timeout(1800)
@pytest.mark.parametrize("family", FAMILIES)
def test_live_both_arms_worked_examples_are_kernel_true(family):
    """Replay each arm's exemplar through that arm's own scorer, live.

    This is the only check that the worked example is *correct* rather than
    merely well-shaped: the decomp block goes through `score_plan` (statement
    elaboration -> stage-1 plan check -> leaves -> compose -> kernel -> axiom
    audit) and the direct block through `run_direct_close`. Anything less and a
    broken family would ship a wrong answer into every few-shot prompt.
    """
    problem = load_exemplar_problem(family)
    budgets = Budgets(max_lemmas=max(8, problem.k), leaf_attempts_per_lemma=1,
                      max_total_leaf_attempts=max(8, problem.k), verify_timeout_s=300.0)
    leaf = _WitnessLeaf({w.prop: w.proof for w in problem.witnesses.values()})
    pool = ReplPool(n_workers=2)
    try:
        pool.warm()
        dec = arms.run_decomp(problem.goal, root=_ReplayRoot(build_exemplar(problem, "decomp")),
                              backend=pool, leaf=leaf, budgets=budgets)
        assert dec.status is Status.VERIFIED, dec.detail

        dir_ = arms.run_direct(problem.goal, root=_ReplayRoot(build_exemplar(problem, "direct")),
                               backend=pool, budgets=budgets)
        assert dir_.status is Status.VERIFIED, dir_.detail
    finally:
        pool.close()
