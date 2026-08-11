"""Environment-wrapper tests (DIRECTION.md §5.3, the Environments Hub artifact).

Split deliberately in two. Everything that must hold *without* the optional
`verifiers` extra — prompt building, goal loading, dataset shape, the raw
scoring helper and the diagnostics it emits — runs unconditionally against
conftest's FakeBackend plus the stub leaf below. Only the surfaces that need the
extra are skipped, so the default suite stays offline, fast, and honest about
what it covers: `verifiers` is not installed in this venv, and the wrapper's
job (prompt + rows + reward + P4 diagnostics) is testable without it.

The scoring tests deliberately re-use the harness's own FakeBackend wiring
rather than mocking `run_episode`: the point of the wrapper is that the status
attribution and the reward reaching `verifiers` are the harness's, unmodified.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from rlmath.core.leancode import statement_check
from rlmath.core.types import Budgets, GoalSpec, LeanMessage, Status, VerifyResult
from rlmath.envs import decomp_env as env

GOAL = GoalSpec(id="g1", prop="P", name="thm")
PLAN_TEXT = "#lemma h1 : A\n#lemma h2 : B\n#assembly\nexact f h1 h2\n#end\n"


# ---------------------------------------------------------------------------
# Fakes (same shapes as tests/test_harness.py — the wrapper changes nothing)
# ---------------------------------------------------------------------------

@dataclass
class FakeLeafResult:
    proof: str | None
    attempts: int


@dataclass
class FakeLeaf:
    proofs: dict[str, str] = field(default_factory=dict)
    calls: list[tuple[str, int]] = field(default_factory=list)

    def prove(self, prop: str, *, k: int, backend) -> FakeLeafResult:
        self.calls.append((prop, k))
        proof = self.proofs.get(prop)
        return FakeLeafResult(proof=proof, attempts=1 if proof else k)


def leaf_ok() -> FakeLeaf:
    return FakeLeaf(proofs={"A": "pa", "B": "pb"})


def wire(fb, *, plan_ok: bool = True, axioms: str = "propext, Classical.choice") -> None:
    fb.rule(lambda c: "#print axioms" in c, VerifyResult(
        ok=True, sorries=0, messages=[LeanMessage("info", f"'thm' depends on axioms: [{axioms}]")]))
    fb.rule(lambda c: c.startswith("theorem _plan"), VerifyResult(
        ok=plan_ok, sorries=0,
        messages=[] if plan_ok else [LeanMessage("error", "unsolved goals")]))
    fb.rule(lambda c: c.startswith("theorem _stmt_check"), VerifyResult(ok=True, sorries=1))


def score(fb, plan_text: str = PLAN_TEXT, *, leaf=None, budgets=None) -> env.EpisodeScore:
    return env.score_plan(GOAL, plan_text, backend=fb, leaf=leaf or leaf_ok(),
                          budgets=budgets or Budgets())


# ---------------------------------------------------------------------------
# Prompt (§5.1 — the format spec and the isolation contract are the prompt)
# ---------------------------------------------------------------------------

def test_system_prompt_states_the_wire_format_exactly():
    """The markers in the prompt must be the ones core/plan_format.py parses.
    A prompt that documents a format the parser rejects is a silent zero."""
    p = env.SYSTEM_PROMPT
    for marker in ("#lemma <name> : <prop>", "#assembly", "#end"):
        assert marker in p
    assert "[A-Za-z][A-Za-z0-9_']*" in p  # the parser's own name rule
    assert "sorry" in p and "native_decide" in p


def test_system_prompt_example_parses_and_survives_the_harness_gates():
    """The worked example is executable documentation: it must parse, and its
    lemma names must clear composer.check_names against a real goal."""
    from rlmath.core.plan_format import parse_plan
    from rlmath.harness import composer

    start = env.SYSTEM_PROMPT.index("#lemma h1")
    example = env.SYSTEM_PROMPT[start:env.SYSTEM_PROMPT.index("#end", start) + len("#end")]
    plan = parse_plan(example)

    assert [l.name for l in plan.lemmas] == ["h1", "h2"]
    assert plan.assembly.splitlines()[0] == "intro x"
    composer.check_names(GOAL, plan)


def test_system_prompt_states_context_isolation():
    p = env.SYSTEM_PROMPT.lower()
    assert "never see proof text" in p
    assert "granting" in p  # the §5.2 two-stage contract, stated to the policy


def test_user_message_carries_id_prop_and_declaration_name():
    """The declaration name is in the prompt because a lemma that shadows it is
    a FORMAT_ERROR the harness refuses to repair (composer docstring)."""
    m = env.user_message(GOAL)
    assert "g1" in m and "P" in m and "thm" in m


def test_build_prompt_is_system_then_user():
    msgs = env.build_prompt(GOAL)
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[0]["content"] == env.SYSTEM_PROMPT
    assert msgs[1]["content"] == env.user_message(GOAL)


def test_single_prompt_inlines_the_system_text():
    """v1 TaskData has one prompt field and the harness owns the system slot."""
    s = env.single_prompt(GOAL)
    assert s.startswith(env.SYSTEM_PROMPT)
    assert s.endswith(env.user_message(GOAL))


def test_prompt_never_contains_proof_text(fake_backend):
    """Context isolation is structural (§5.1): the prompt path takes a GoalSpec
    and nothing else, so no proof the episode produced can reach the policy —
    asserted against a real verified artifact rather than by inspection."""
    wire(fake_backend)
    leaf = FakeLeaf(proofs={"A": "PROOF_ALPHA", "B": "PROOF_BETA"})
    artifact = score(fake_backend, leaf=leaf).result.artifact
    assert artifact is not None and "have h1 : A := PROOF_ALPHA" in artifact

    for text in (env.user_message(GOAL), env.single_prompt(GOAL),
                 json.dumps(env.goal_rows([GOAL]))):
        assert "PROOF_ALPHA" not in text and "PROOF_BETA" not in text
        assert "have h1" not in text


@pytest.mark.parametrize("completion,expected", [
    ("raw text", "raw text"),
    ([{"role": "assistant", "content": "chat text"}], "chat text"),
    ([{"role": "user", "content": "u"}, {"role": "assistant", "content": "last"}], "last"),
    ([{"role": "assistant", "content": None}], ""),
    ([], ""),
    (None, ""),
])
def test_completion_text_handles_both_message_modes(completion, expected):
    """Chat mode gives list[ChatMessage], completion mode a str; an unrecognized
    shape must degrade to '' (a counted FORMAT_ERROR), never raise."""
    assert env.completion_text(completion) == expected


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

def test_load_goals_from_jsonl(tmp_path):
    path = tmp_path / "goals.jsonl"
    path.write_text(
        json.dumps({"id": "a", "prop": "P", "name": "thm_a"}) + "\n"
        + "\n"  # blank lines tolerated
        + json.dumps({"id": "b", "prop": "Q"}) + "\n",
        encoding="utf-8",
    )
    goals = env.load_goals(path)
    assert [(g.id, g.prop, g.name) for g in goals] == [("a", "P", "thm_a"), ("b", "Q", "goal")]


def test_load_goals_accepts_goalspecs_dicts_and_bank_ids():
    assert env.load_goals([GOAL]) == [GOAL]
    # scripts/build_bank.py rows carry source_id/statement_key, not id.
    rows = [{"prop": "P", "source_id": "lw_7"}, {"prop": "Q", "statement_key": "ab12"}, {"prop": "R"}]
    assert [g.id for g in env.load_goals(rows)] == ["lw_7", "ab12", "g2"]


def test_load_goals_rejects_a_row_without_a_prop():
    """Dropping the row silently would make two runs incomparable (../rl lesson)."""
    with pytest.raises(ValueError, match="row 1: missing 'prop'"):
        env.load_goals([{"id": "a", "prop": "P"}, {"id": "b"}])
    with pytest.raises(ValueError, match="no goals"):
        env.load_goals([])


def test_goal_rows_shape_matches_the_v0_dataset_contract():
    (row,) = env.goal_rows([GOAL])
    assert row["prompt"] == [{"role": "user", "content": env.user_message(GOAL)}]
    assert row["answer"] == "P"
    # info is what the reward function rebuilds the GoalSpec from.
    assert row["info"] == {"id": "g1", "prop": "P", "name": "thm"}
    assert env.load_goals([row["info"]]) == [GOAL]


def test_build_dataset_needs_no_verifiers():
    """`datasets` is a core dependency, so dataset shape is testable without the extra."""
    ds = env.build_dataset([GOAL, GoalSpec(id="g2", prop="Q")])
    assert len(ds) == 2
    assert set(ds.column_names) == {"prompt", "answer", "info"}
    assert ds[1]["info"]["id"] == "g2"


# ---------------------------------------------------------------------------
# Raw scoring helper + the P4 diagnostics (§5.6, §5.7)
# ---------------------------------------------------------------------------

def test_score_plan_verified(fake_backend):
    wire(fake_backend)
    s = score(fake_backend)

    assert s.reward == 1.0
    assert s.result.status is Status.VERIFIED
    assert s.info["status"] == "verified"
    assert s.info["goal_id"] == "g1"
    assert s.info["leaf_attempts_used"] == 2
    assert s.info["plan_stats"]["n_lemmas"] == 2


def test_score_plan_reward_is_terminal_only(fake_backend):
    """§5.6: a valid plan whose leaves failed scores 0.0 — r_plan is diagnostic,
    never mixed into the reward."""
    wire(fake_backend)
    s = score(fake_backend, leaf=FakeLeaf(proofs={"A": "pa"}))

    assert s.reward == 0.0
    assert s.result.status is Status.LEAF_FAILED
    assert s.info["plan_stats"] is not None  # the plan *did* check out
    assert s.info["leaf_attempts_used"] == 1 + Budgets().leaf_attempts_per_lemma


def test_score_plan_status_separation_survives_into_info(fake_backend):
    """§5.7's non-negotiable: plan_invalid must not read as leaf_failed."""
    wire(fake_backend, plan_ok=False)
    s = score(fake_backend)

    assert s.info["status"] == "plan_invalid"
    assert "unsolved goals" in s.info["detail"]
    assert s.metrics["status_plan_invalid"] == 1.0
    assert s.metrics["status_leaf_failed"] == 0.0


def test_score_plan_format_error_has_no_plan_stats(fake_backend):
    """Absence, not zeros: a zero-filled plan_stats would be indistinguishable
    from a direct-close plan in the P4 restatement rates."""
    s = score(fake_backend, "no markers at all")

    assert s.reward == 0.0
    assert s.info["status"] == "format_error"
    assert s.info["plan_stats"] is None
    assert "plan_n_lemmas" not in s.metrics
    assert fake_backend.calls == []


def test_score_plan_flags_a_degenerate_restatement(fake_backend):
    """P4's instrument: restating the goal as one lemma must show up as
    restatement_max ≈ 1.0 even when the episode verifies."""
    fake_backend.rule(lambda c: "#print axioms" in c, VerifyResult(
        ok=True, sorries=0, messages=[LeanMessage("info", "'thm' depends on axioms: [propext]")]))
    fake_backend.rule(lambda c: c.startswith("theorem _plan"), VerifyResult(ok=True, sorries=0))
    fake_backend.rule(lambda c: c == statement_check("P"), VerifyResult(ok=True, sorries=1))
    s = score(fake_backend, "#lemma h1 : P\n#assembly\nexact h1\n#end\n",
              leaf=FakeLeaf(proofs={"P": "pp"}))

    assert s.reward == 1.0
    assert s.info["plan_stats"]["restatement_max"] == 1.0
    assert s.metrics["plan_restatement_max"] == 1.0


def test_score_plan_info_is_json_serializable(fake_backend):
    """These rows go into training logs verbatim; a non-serializable value is a
    crash halfway through a run."""
    wire(fake_backend)
    s = score(fake_backend)
    assert json.loads(json.dumps(s.info)) == s.info


def test_info_detail_is_truncated(fake_backend):
    """A COMPOSE_FAILED detail embeds the whole artifact; logs get a bounded
    slice, the full text stays on the in-process result."""
    wire(fake_backend)
    fake_backend.rules.insert(0, (
        lambda c: "#print axioms" in c,
        VerifyResult(ok=False, sorries=0, messages=[LeanMessage("error", "kernel said no")]),
    ))
    long_assembly = "\n".join(["skip"] * 800)  # a fat assembly makes a fat artifact
    s = score(fake_backend, f"#lemma h1 : A\n#assembly\n{long_assembly}\nexact h1\n#end\n",
              leaf=FakeLeaf(proofs={"A": "pa"}))

    assert s.info["status"] == "compose_failed"
    assert len(s.result.detail) > env.INFO_DETAIL_CHARS
    assert len(s.info["detail"]) == env.INFO_DETAIL_CHARS


def test_metrics_cover_every_status_exactly_once(fake_backend):
    """One 0/1 column per Status, so a group mean *is* that status's rate."""
    wire(fake_backend)
    m = score(fake_backend).metrics
    indicators = {k: v for k, v in m.items() if k.startswith("status_")}

    assert set(indicators) == {f"status_{s.value}" for s in Status}
    assert sum(indicators.values()) == 1.0
    assert set(m) >= {"reward", "leaf_attempts_used", "elapsed_s",
                      "plan_n_lemmas", "plan_restatement_max", "plan_is_direct"}
    assert all(isinstance(v, float) for v in m.values())


def test_plan_stat_keys_match_detectors(fake_backend):
    """Pin the detectors contract: a new key there must be added here, not
    silently dropped from the metric columns."""
    from rlmath.core.types import DecompositionPlan, LemmaSpec
    from rlmath.harness.detectors import plan_stats

    keys = plan_stats(DecompositionPlan([LemmaSpec("h1", "A")], "exact h1"), GOAL).keys()
    assert set(keys) == set(env._PLAN_STAT_KEYS)


def test_backend_errors_propagate_out_of_the_wrapper(fake_backend):
    """Infrastructure failure is not evidence (§6): scoring it 0.0 here would
    hide a dead Lean server as a policy failure."""
    class Boom:
        def check(self, code, *, timeout_s=120.0):
            raise RuntimeError("lean server died")

        def check_many(self, codes, *, timeout_s=120.0):
            raise RuntimeError("lean server died")

        def close(self):
            pass

    with pytest.raises(RuntimeError, match="lean server died"):
        env.score_plan(GOAL, PLAN_TEXT, backend=Boom(), leaf=leaf_ok(), budgets=Budgets())


# ---------------------------------------------------------------------------
# Resources registry + the extra's absence
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_resources():
    yield
    env.set_resources(None)


def test_resources_registry_round_trips(fake_backend):
    res = env.EpisodeResources(backend=fake_backend, leaf=leaf_ok(), goals=[GOAL])
    env.set_resources(res)
    assert env.get_resources() is res
    assert env.get_resources().budgets == Budgets()


def test_get_resources_error_names_the_fix():
    with pytest.raises(RuntimeError, match="set_resources"):
        env.get_resources()


def test_budgets_from_config_maps_every_field():
    class Cfg:
        max_lemmas = 3
        leaf_attempts_per_lemma = 2
        max_total_leaf_attempts = 5
        verify_timeout_s = 7.5

    assert env.budgets_from_config(Cfg()) == Budgets(3, 2, 5, 7.5)


def test_module_imports_without_verifiers_and_flags_say_so():
    """The extra is optional; the offline path must not depend on it."""
    assert env.HAS_VERIFIERS == (env.HAS_VERIFIERS_V0 or env.HAS_VERIFIERS_V1)
    assert isinstance(env.SYSTEM_PROMPT, str)


@pytest.mark.skipif(env.HAS_VERIFIERS_V0, reason="verifiers installed")
def test_load_environment_without_the_extra_says_how_to_install():
    with pytest.raises(ImportError, match="envhub"):
        env.load_environment(goals=[GOAL], backend=object(), leaf=object())


@pytest.mark.skipif(env.HAS_VERIFIERS_V1, reason="verifiers installed")
def test_build_taskset_without_the_extra_says_how_to_install():
    with pytest.raises(ImportError, match="envhub"):
        env.build_taskset(goals=[GOAL], backend=object(), leaf=object())


@pytest.mark.skipif(env.HAS_VERIFIERS_V1, reason="verifiers installed")
def test_v1_classes_are_absent_without_the_extra():
    """`__all__` must stay importable: the v1 loader reads it, and a name in it
    that does not resolve breaks `from rlmath.envs import *`."""
    import rlmath.envs as pkg

    assert "DecompositionTaskset" not in pkg.__all__
    assert all(hasattr(pkg, n) for n in pkg.__all__)


# ---------------------------------------------------------------------------
# verifiers surfaces (skipped without the `envhub` extra)
# ---------------------------------------------------------------------------

v1only = pytest.mark.skipif(not env.HAS_VERIFIERS_V1, reason="needs the envhub extra")
v0only = pytest.mark.skipif(not env.HAS_VERIFIERS_V0, reason="needs the envhub extra")


@v1only
def test_v1_taskset_loads_one_task_per_goal(fake_backend):
    ts = env.build_taskset(goals=[GOAL, GoalSpec(id="g2", prop="Q")],
                           backend=fake_backend, leaf=leaf_ok(), budgets=Budgets(max_lemmas=3))
    tasks = list(ts.load())

    assert [t.data.goal_id for t in tasks] == ["g1", "g2"]
    assert tasks[0].data.prompt == env.single_prompt(GOAL)
    assert env.get_resources().budgets.max_lemmas == 3


@v1only
def test_v1_reward_runs_the_episode_and_attaches_diagnostics(fake_backend):
    import asyncio

    wire(fake_backend)
    ts = env.build_taskset(goals=[GOAL], backend=fake_backend, leaf=leaf_ok())
    task = list(ts.load())[0]

    class Trace:
        last_reply = PLAN_TEXT
        metrics: dict = {}

    trace = Trace()
    assert asyncio.run(task.verified(trace)) == 1.0
    assert trace.metrics["status_verified"] == 1.0
    assert trace.metrics["rlmath_info"]["plan_stats"]["n_lemmas"] == 2


@v1only
def test_v1_taskset_is_discoverable_off_dunder_all():
    import verifiers.v1 as vf

    import rlmath.envs as pkg

    assert "DecompositionTaskset" in pkg.__all__
    assert issubclass(pkg.DecompositionTaskset, vf.Taskset)


@v0only
def test_v0_environment_builds_with_dataset_and_rubric(fake_backend):
    e = env.load_environment(goals=[GOAL], backend=fake_backend, leaf=leaf_ok())

    assert e.system_prompt == env.SYSTEM_PROMPT
    assert len(e.get_dataset()) == 1
    # exactly one weighted function; the rest are weight-0 metric columns (§5.6)
    assert list(e.rubric.weights).count(1.0) == 1
    assert set(e.rubric.weights) == {0.0, 1.0}


@v0only
def test_v0_reward_function_scores_and_parks_diagnostics_in_state(fake_backend):
    import asyncio

    wire(fake_backend)
    e = env.load_environment(goals=[GOAL], backend=fake_backend, leaf=leaf_ok())
    reward_fn = e.rubric.funcs[0]
    state: dict = {}

    r = asyncio.run(reward_fn(
        completion=[{"role": "assistant", "content": PLAN_TEXT}],
        info={"id": "g1", "prop": "P", "name": "thm"},
        state=state,
    ))
    assert r == 1.0
    assert state["rlmath"]["status"] == "verified"
    assert state["rlmath_metrics"]["plan_n_lemmas"] == 2.0

    metric_fn = next(f for f in e.rubric.funcs if f.__name__ == "leaf_attempts_used")
    assert asyncio.run(metric_fn(state=state)) == 2.0


@v0only
def test_v0_load_environment_falls_back_to_registered_resources(fake_backend):
    env.set_resources(env.EpisodeResources(backend=fake_backend, leaf=leaf_ok(), goals=[GOAL]))
    e = env.load_environment()
    assert len(e.get_dataset()) == 1
