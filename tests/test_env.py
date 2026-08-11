"""Environment-wrapper tests (DIRECTION.md §5.3, the Environments Hub artifact).

Split deliberately in two. Everything that must hold *without* the optional
`verifiers` extra — prompt building, goal loading, dataset shape, the raw
scoring helper and the diagnostics it emits — runs unconditionally against
conftest's FakeBackend plus the stub leaf below, so the default suite stays
offline and fast even where the extra is absent. The `v0only`/`v1only` block at
the bottom exercises the real `verifiers` surfaces and runs whenever the
`envhub` extra is installed (it is, as of 0.3.0).

The scoring tests deliberately re-use the harness's own FakeBackend wiring
rather than mocking `run_episode`: the point of the wrapper is that the status
attribution and the reward reaching `verifiers` are the harness's, unmodified.
"""
from __future__ import annotations

import importlib
import json
import pathlib
import tomllib
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


def test_prompt_never_contains_proof_text(fake_backend):
    """Context isolation is structural (§5.1): the prompt path takes a GoalSpec
    and nothing else, so no proof the episode produced can reach the policy —
    asserted against a real verified artifact rather than by inspection."""
    wire(fake_backend)
    leaf = FakeLeaf(proofs={"A": "PROOF_ALPHA", "B": "PROOF_BETA"})
    artifact = score(fake_backend, leaf=leaf).result.artifact
    assert artifact is not None and "have h1 : A := PROOF_ALPHA" in artifact

    for text in (env.user_message(GOAL), env.SYSTEM_PROMPT,
                 json.dumps(env.build_prompt(GOAL)),
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
# verifiers surfaces — asserted against the installed library, not a stand-in
#
# These run whenever the `envhub` extra is present. They deliberately drive the
# real objects (a real `vf.Trace`, the real `Task.score` entry point, a real
# `Rubric`) rather than duck-typed fakes: the whole point of this block is to
# catch the day a `verifiers` upgrade renames the channel the P4 diagnostics
# ride on, which a fake with the right attribute names would never notice.
# ---------------------------------------------------------------------------

v1only = pytest.mark.skipif(not env.HAS_VERIFIERS_V1, reason="needs the envhub extra")
v0only = pytest.mark.skipif(not env.HAS_VERIFIERS_V0, reason="needs the envhub extra")


def make_trace(task, reply: str = PLAN_TEXT):
    """A real `vf.Trace` for `task`, carrying `reply` as the sampled last turn.

    Built the way the runtime builds one — a sampled assistant `MessageNode`, so
    `trace.last_reply` is exercised rather than stubbed.
    """
    import verifiers.v1 as vf

    trace = vf.Trace(
        task=vf.TraceTask(type=type(task).__name__, data=task.data),
        agent=vf.AgentInfo(config=vf.AgentConfig()),
    )
    trace.nodes.append(
        vf.MessageNode(message=vf.AssistantMessage(content=reply), sampled=True)
    )
    return trace


@v1only
def test_v1_taskset_loads_one_task_per_goal(fake_backend):
    ts = env.build_taskset(goals=[GOAL, GoalSpec(id="g2", prop="Q")],
                           backend=fake_backend, leaf=leaf_ok(), budgets=Budgets(max_lemmas=3))
    tasks = list(ts.load())

    assert [t.data.goal_id for t in tasks] == ["g1", "g2"]
    assert [t.data.decl_name for t in tasks] == ["thm", "goal"]
    # §5.6's caps ride on the task config, which is the copy an env server
    # rebuilds each task from — not on a `load()` side effect it never runs.
    assert tasks[0].config.max_lemmas == 3
    assert env.budgets_from_config(tasks[0].config) == Budgets(max_lemmas=3)


@v1only
def test_v1_task_uses_the_real_system_prompt_slot(fake_backend):
    """`TaskData.system_prompt` exists (verifiers 0.3.0), so the format spec is a
    real system message the harness places — never inlined into the user turn."""
    import verifiers.v1 as vf

    ts = env.build_taskset(goals=[GOAL], backend=fake_backend, leaf=leaf_ok())
    data = list(ts.load())[0].data

    assert data.system_prompt == env.SYSTEM_PROMPT
    assert data.prompt == env.user_message(GOAL)
    assert env.SYSTEM_PROMPT not in data.prompt

    # The harness is what places it; both placements keep the text intact.
    harness = vf.load_harness(vf.HarnessConfig(id="null"))
    assert harness.APPENDS_SYSTEM_PROMPT
    assert harness.resolve_prompt(data) == (env.SYSTEM_PROMPT, env.user_message(GOAL))


@v1only
def test_v1_reward_runs_the_episode_through_task_score(fake_backend):
    """`Task.score` is the real entry point: it discovers the `@vf.reward`, runs
    it, and records the terminal reward under the method name."""
    import asyncio

    wire(fake_backend)
    ts = env.build_taskset(goals=[GOAL], backend=fake_backend, leaf=leaf_ok())
    task = list(ts.load())[0]
    trace = make_trace(task)

    asyncio.run(task.score(trace))

    assert trace.rewards["verified"].score == 1.0
    assert trace.rewards["verified"].weight == 1.0
    assert trace.reward == 1.0  # the weighted scalar prime-rl trains on


@v1only
def test_v1_p4_diagnostics_reach_the_trace_channels(fake_backend):
    """G1 regression guard (DIRECTION.md §5.7).

    The status indicators, `plan_stats`, `leaf_attempts_used` and `elapsed_s`
    must land on `trace.metrics` as floats, the full JSON blob on `trace.info`,
    and both must survive `Trace.to_record()` — that record *is* the training
    log. Asserted through `Task.score` so a channel rename fails here loudly
    instead of silently emptying the P4 plot.
    """
    import asyncio

    wire(fake_backend, plan_ok=False)
    ts = env.build_taskset(goals=[GOAL], backend=fake_backend, leaf=leaf_ok())
    task = list(ts.load())[0]
    trace = make_trace(task)

    asyncio.run(task.score(trace))

    m = trace.metrics
    assert m["status_plan_invalid"] == 1.0 and m["status_leaf_failed"] == 0.0
    assert {f"status_{s.value}" for s in Status} <= set(m)
    assert {"leaf_attempts_used", "elapsed_s", "plan_n_lemmas",
            "plan_restatement_max"} <= set(m)
    # trace.metrics is typed dict[str, float|None]: nothing but numbers here, or
    # the schema breaks and the aggregate means go with it.
    assert all(isinstance(v, float) for v in m.values())

    info = trace.info[env.TRACE_INFO_KEY]
    assert info["status"] == "plan_invalid"
    assert info["goal_id"] == "g1"
    assert "unsolved goals" in info["detail"]
    assert info["plan_stats"]["n_lemmas"] == 2

    record = trace.to_record()
    assert record["info"][env.TRACE_INFO_KEY] == info
    assert record["metrics"]["status_plan_invalid"] == 1.0


@v1only
def test_v1_format_error_keeps_plan_stats_absent_on_the_trace(fake_backend):
    """Absence survives the channel: a completion that never parsed must not
    contribute zero-valued plan_* columns (they would read as a direct close)."""
    import asyncio

    ts = env.build_taskset(goals=[GOAL], backend=fake_backend, leaf=leaf_ok())
    task = list(ts.load())[0]
    trace = make_trace(task, reply="I think the answer is 4.")

    asyncio.run(task.score(trace))

    assert trace.rewards["verified"].score == 0.0
    assert trace.metrics["status_format_error"] == 1.0
    assert not [k for k in trace.metrics if k.startswith("plan_")]
    assert trace.info[env.TRACE_INFO_KEY]["plan_stats"] is None
    assert fake_backend.calls == []


@v1only
def test_v1_taskset_is_discoverable_the_way_the_loader_discovers_it():
    """`loaders._plugin_class` resolves the taskset off `__all__` and requires
    exactly one `Taskset` subclass there — two would be a hard error."""
    import verifiers.v1 as vf
    from verifiers.v1.utils.loaders import _plugin_class

    import rlmath.envs as pkg

    assert "DecompositionTaskset" in pkg.__all__
    assert all(hasattr(pkg, n) for n in pkg.__all__)
    assert _plugin_class(pkg, vf.Taskset, "taskset") is pkg.DecompositionTaskset
    # and the generic parameters the loader reads back for config/task typing
    assert pkg.DecompositionTaskset.task_type() is pkg.DecompositionTask
    assert vf.Taskset in pkg.DecompositionTaskset.__mro__
    assert pkg.DecompositionTask.data_type() is pkg.DecompositionData
    assert pkg.DecompositionTask.config_type() is pkg.DecompositionTaskConfig


@v1only
def test_v1_taskset_takes_its_config_positionally(fake_backend):
    """`load_taskset` calls `taskset_class(id)(config)` — one signature, and the
    config subtree must round-trip so `[env.taskset]` TOML actually lands."""
    env.set_resources(env.EpisodeResources(backend=fake_backend, leaf=leaf_ok(), goals=[GOAL]))
    cfg = env.DecompositionConfig(
        id=env.ENV_ID,
        task=env.DecompositionTaskConfig(max_lemmas=2, leaf_attempts_per_lemma=1),
    )
    ts = env.DecompositionTaskset(cfg)

    (task,) = list(ts.load())
    assert task.config.max_lemmas == 2
    assert env.budgets_from_config(task.config) == Budgets(
        max_lemmas=2, leaf_attempts_per_lemma=1)


@v1only
def test_v1_taskset_iteration_applies_the_config_system_prompt_override(tmp_path, fake_backend):
    """`TasksetConfig.system_prompt` is a file override applied on iteration (the
    GEPA path). Our per-task prompt is the default, not a hard-coded constant."""
    override = tmp_path / "best_system_prompt.txt"
    override.write_text("OVERRIDDEN", encoding="utf-8")
    env.set_resources(env.EpisodeResources(backend=fake_backend, leaf=leaf_ok(), goals=[GOAL]))

    ts = env.DecompositionTaskset(env.DecompositionConfig(id=env.ENV_ID))
    assert next(iter(ts)).data.system_prompt == env.SYSTEM_PROMPT

    ts = env.DecompositionTaskset(env.DecompositionConfig(id=env.ENV_ID, system_prompt=override))
    assert next(iter(ts)).data.system_prompt == "OVERRIDDEN"


def our_rubric(e):
    """Our `Rubric` out of the env.

    `MultiTurnEnv.__init__` adds a `MultiTurnMonitorRubric`, so `env.rubric` is a
    `RubricGroup` and ours is the first member — pinned here rather than assumed
    at each call site, because that wrapping is verifiers' business and may move.
    """
    import verifiers as vf

    return e.rubric.rubrics[0] if isinstance(e.rubric, vf.RubricGroup) else e.rubric


@v0only
def test_v0_environment_builds_with_dataset_and_rubric(fake_backend):
    import verifiers as vf

    e = env.load_environment(goals=[GOAL], backend=fake_backend, leaf=leaf_ok())
    rubric = our_rubric(e)

    assert isinstance(e, vf.SingleTurnEnv)
    assert isinstance(rubric, vf.Rubric)
    assert e.system_prompt == env.SYSTEM_PROMPT  # the real system slot, not inlined
    assert len(e.get_dataset()) == 1
    # exactly one weighted function; the rest are weight-0 metric columns (§5.6)
    assert list(rubric.weights).count(1.0) == 1
    assert set(rubric.weights) == {0.0, 1.0}


@v0only
def test_v0_rubric_scores_a_rollout_and_emits_the_metric_columns(fake_backend):
    """`Rubric.score_rollout` is the real entry point. It calls the funcs in
    registration order over one shared `state` — which is what lets the weighted
    function run the episode once and the weight-0 columns read it back. It
    writes `state["reward"]` / `state["metrics"]` in place and returns None."""
    import asyncio

    wire(fake_backend)
    e = env.load_environment(goals=[GOAL], backend=fake_backend, leaf=leaf_ok())
    state: dict = {
        "prompt": [{"role": "user", "content": env.user_message(GOAL)}],
        "completion": [{"role": "assistant", "content": PLAN_TEXT}],
        "answer": GOAL.prop,
        "info": {"id": "g1", "prop": "P", "name": "thm"},
    }

    asyncio.run(our_rubric(e).score_rollout(state))

    assert state["reward"] == 1.0  # terminal only: the metric columns are weight-0
    metrics = state["metrics"]
    assert metrics["episode_reward"] == 1.0
    assert metrics["status_verified"] == 1.0
    assert metrics["status_leaf_failed"] == 0.0
    assert metrics["leaf_attempts_used"] == 2.0
    assert metrics["plan_n_lemmas"] == 2.0
    assert {f"status_{s.value}" for s in Status} <= set(metrics)
    # the JSON blob rides `state`, which survives into the saved results rows
    assert state["rlmath"]["status"] == "verified"
    assert state["rlmath"]["plan_stats"]["n_lemmas"] == 2


@v0only
def test_v0_load_environment_falls_back_to_registered_resources(fake_backend):
    env.set_resources(env.EpisodeResources(backend=fake_backend, leaf=leaf_ok(), goals=[GOAL]))
    e = env.load_environment()
    assert len(e.get_dataset()) == 1


# ---------------------------------------------------------------------------
# The Hub package (`environments/rlmath_decomp/`)
#
# Unconditional: the package is source-on-disk, and its shape is what a push
# would ship. Nothing here installs, builds or contacts the Hub.
# ---------------------------------------------------------------------------

REPO = pathlib.Path(__file__).resolve().parent.parent
HUB_PKG = REPO / "environments" / "rlmath_decomp"


def test_hub_package_has_the_layout_the_v1_scaffolder_emits():
    """`init <name>` (verifiers/v1/cli/init.py) writes exactly these four files;
    the Hub id `rlmath-decomp` resolves to the module `rlmath_decomp`."""
    assert (HUB_PKG / "pyproject.toml").is_file()
    assert (HUB_PKG / "README.md").is_file()
    assert (HUB_PKG / "rlmath_decomp" / "__init__.py").is_file()
    assert (HUB_PKG / "rlmath_decomp" / "taskset.py").is_file()


def test_hub_package_readme_is_a_verbatim_copy():
    """The Hub page and the in-repo doc are one file, so publishing cannot ship a
    stale description of the reward semantics."""
    canonical = REPO / "src" / "rlmath" / "envs" / "envs_README.md"
    assert (HUB_PKG / "README.md").read_text(encoding="utf-8") == canonical.read_text(
        encoding="utf-8"
    )


def test_hub_pyproject_declares_what_the_hub_build_needs():
    """Hatchling backend, a `verifiers` floor, the package directory, and the
    eval defaults `prime eval run` falls back to."""
    cfg = tomllib.loads((HUB_PKG / "pyproject.toml").read_text(encoding="utf-8"))

    assert cfg["project"]["name"] == env.ENV_ID
    assert cfg["build-system"]["build-backend"] == "hatchling.build"
    assert cfg["build-system"]["requires"] == ["hatchling"]
    assert cfg["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["rlmath_decomp"]
    assert "verifiers>=0.3.0" in cfg["project"]["dependencies"]
    assert "rlmath" in cfg["project"]["dependencies"]
    assert cfg["project"]["tags"]  # non-standard field; verifiers' own tooling reads it
    assert set(cfg["tool"]["verifiers"]["eval"]) == {"num_examples", "rollouts_per_example"}


def test_hub_package_module_re_exports_rather_than_reimplementing():
    """One scoring path. A second copy of the wrapper in the published package
    would be a second thing to keep correct and only one would have tests."""
    source = (HUB_PKG / "rlmath_decomp" / "taskset.py").read_text(encoding="utf-8")

    assert "from rlmath.envs.decomp_env import" in source
    assert "run_episode" not in source and "score_plan" not in source


@v1only
def test_hub_package_exports_exactly_one_taskset_and_the_v0_entry_point(monkeypatch):
    """What both loaders actually do: v1 pulls the single `Taskset` subclass out
    of `__all__`, v0 calls `load_environment` by name off the same module."""
    import sys

    import verifiers.v1 as vf
    from verifiers.v1.utils.loaders import _plugin_class

    monkeypatch.syspath_prepend(str(HUB_PKG))
    for name in [n for n in sys.modules if n == "rlmath_decomp" or n.startswith("rlmath_decomp.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    pkg = importlib.import_module("rlmath_decomp")

    assert _plugin_class(pkg, vf.Taskset, "taskset") is env.DecompositionTaskset
    assert pkg.load_environment is env.load_environment
