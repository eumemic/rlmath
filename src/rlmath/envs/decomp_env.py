"""The rlmath decomposition environment in `verifiers` format (DIRECTION.md §5.3).

This is the Phase-0 shipping artifact: the harness, wrapped so Prime Intellect's
Environments Hub can serve it and prime-rl can train against it (§5.5, Phase 0
gate). It wraps `harness.episode.run_episode` — it does not re-implement any of
it. Scoring, status attribution and sanitization stay in the harness, where the
tests that pin them live; this module only builds prompts, builds rows, and
carries the harness's typed outcome out through whatever per-sample channel the
verifiers surface in use provides.

v0 or v1? — both, with v1 primary
--------------------------------
`verifiers` is mid-migration (research/verifiers.md §1): the v0
`SingleTurnEnv`/`Rubric` surface is still the default `import verifiers as vf`
namespace and what `prime env init` scaffolds, but it is documented as
deprecated, and **prime-rl's orchestrator is built exclusively against
`verifiers.v1`** (research §6 — no `load_environment` usage anywhere in
prime-rl). DIRECTION.md §5.3 names prime-rl as the trainer and §5.5 makes the
published environment the Phase-0 artifact, so the training path decides it:
v1 `Taskset`/`Task` is the primary surface here.

v0 is kept as a thin shim because research §8 is right that it is nearly free
once a raw episode scorer exists — `SingleTurnEnv` + a `Rubric` over the same
`score_plan` is ~40 lines — and it buys the whole legacy toolchain
(`prime eval run`, `vf-eval`, GEPA prompt optimization) for the zero-shot study
in Phase 2, which needs eval tooling long before it needs a trainer.

Nothing above the guarded imports touches verifiers: prompt building, goal
loading and `score_plan` are importable and testable with the `envhub` extra
absent (that is also what keeps the default test suite offline and fast).

Loading vs running
------------------
Both entry points construct with **no arguments and nothing registered**, over
the built-in `DEMO_GOALS` set. That is not a convenience: the Hub's integration
test imports and loads a published environment on infra that has no Lean
toolchain, and `prime env info` / v1 discovery do the same, so an environment
that can only be *constructed* next to a live kernel cannot be published at all.

What never gets a fallback is the reward. Every scoring path goes through
`live_resources()`, which raises when a backend or leaf is missing, so a rollout
run without a kernel fails loudly instead of scoring 0.0 — an absent kernel
scored as a policy failure is exactly the confusion §6 forbids, and on a hosted
eval it would read as a model that never proves anything.

Context isolation (§5.1) is a property of the *prompt*, so it is stated here and
nowhere else: the policy sees goal statements and child statuses only, never
proof text. `EpisodeResult.artifact` and every leaf proof stay on the harness
side of this module and are never rendered into a message.

Diagnostics (§5.7 P4) ride out through the per-sample channel because a status
that only exists inside the runner cannot be analysed later: `status`, `detail`,
`plan_stats` and `leaf_attempts_used` are the instrument for "degenerate
restatement rises under RL and hard budgets contain it", and they have to be in
the training logs from the first run, not added after the plot looks wrong. On
v1 that is `Trace.record_metrics` (floats) plus `Trace.info["rlmath"]` (the JSON
blob); on v0 it is `state["rlmath"]` plus weight-0 rubric functions.

Every `verifiers` call below is pinned against the installed 0.3.0 source, not
against research/verifiers.md — the notes were taken from a repo clone and got
`TaskData.system_prompt` (it exists) and the metric channel (explicit `Trace`
methods) wrong. See the comment above the v1 block.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rlmath.core.backend import LeanBackend
from rlmath.core.types import Budgets, EpisodeResult, GoalSpec, Status
from rlmath.harness.detectors import plan_stats
from rlmath.harness.episode import LeafProver, run_episode

# --- the optional extra ------------------------------------------------------
# `verifiers` pulls the training stack; `pyproject.toml` keeps it behind the
# `envhub` extra. Everything above this point must work without it, so the
# import is a probe, not a dependency. `Exception`, not `ImportError`: a
# half-installed extra (version conflict inside verifiers' own imports) must
# degrade to "not available" rather than break the offline harness path.
try:
    import verifiers.v1 as vf1

    HAS_VERIFIERS_V1 = True
except Exception:  # pragma: no cover - exercised only where the extra is absent
    vf1 = None
    HAS_VERIFIERS_V1 = False

try:
    import verifiers as vf0

    HAS_VERIFIERS_V0 = True
except Exception:  # pragma: no cover
    vf0 = None
    HAS_VERIFIERS_V0 = False

HAS_VERIFIERS = HAS_VERIFIERS_V0 or HAS_VERIFIERS_V1

ENV_ID = "rlmath-decomp"          # Hub environment id (module name: rlmath_decomp)
INFO_DETAIL_CHARS = 2000          # see `episode_info`
_DEFAULTS = Budgets()             # one source of truth for the v1 config defaults


# ---------------------------------------------------------------------------
# Prompt (DIRECTION.md §5.1 — the action space *is* the format)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the root policy of a Lean 4 decomposition harness. Given one goal \
proposition, emit exactly one decomposition plan: the statements of the lemmas you \
want proved for you, plus the tactic block that closes the goal from them.

Context isolation — this is the contract, not a style note:
- You never see proof text. Each lemma you state is dispatched to a separate frozen
  prover; its proof is spliced in by the harness and shown to the Lean kernel, never
  to you. You see goal statements and child statuses only.
- So every lemma must stand alone: a closed Lean 4 proposition, no reference to the
  goal's local binders, no metavariables, no placeholders.
- Your assembly is checked *granting* the lemmas as hypotheses, before any lemma is
  proved. A plan that does not close the goal is rejected even if every lemma is true.

Wire format (exact, line-oriented):

    #lemma <name> : <prop>      zero or more, one per line, before #assembly
    #assembly                   exactly once, after all #lemma lines
    <tactic lines>              verbatim, as many as needed
    #end                        required

Rules:
- <name> matches [A-Za-z][A-Za-z0-9_']*, is unique within the plan, does not start
  with '_', and is not the goal's own declaration name.
- <prop> is a closed Lean 4 proposition on ONE line. Mathlib is imported.
- Inside the assembly every lemma is in scope as a hypothesis under the name and
  proposition you stated; the block is a tactic proof of the goal.
- Zero #lemma lines is legal: then the assembly alone must prove the goal outright.
- Text before the first '#' marker and after #end is ignored. Anything else between
  the markers is a format error and scores zero.
- Banned anywhere in your output: sorry, admit, axiom, native_decide, set_option,
  macro, macro_rules, elab, notation, syntax, unsafe, partial, opaque, #exit.

Example. Goal: 0 <= x ^ 2 + 2 * x + 1 for all real x.

#lemma h1 : ∀ x : ℝ, 0 ≤ (x + 1) ^ 2
#lemma h2 : ∀ x : ℝ, (x + 1) ^ 2 = x ^ 2 + 2 * x + 1
#assembly
intro x
have h := h1 x
rw [h2 x] at h
exact h
#end

Reward is 1 only when the composed proof passes the Lean kernel and the axiom \
audit; everything else is 0. Emit the plan and nothing else.\
"""


def user_message(goal: GoalSpec) -> str:
    """The per-goal user turn.

    The declaration name is stated because the policy must not shadow it — a
    lemma named like the goal is a FORMAT_ERROR that composer.check_names
    refuses to repair silently (composer docstring), so the constraint has to be
    visible in the prompt rather than discovered through the reward.
    """
    return (
        f"Goal id: {goal.id}\n"
        f"Declaration name: {goal.name}\n"
        f"Prove:\n{goal.prop}\n"
    )


def build_prompt(goal: GoalSpec) -> list[dict[str, str]]:
    """Chat messages for one goal (v0 dataset `prompt` column shape).

    Both surfaces keep the system text in a real system slot rather than inlining
    it into the user turn: v0 through `SingleTurnEnv(system_prompt=...)`, v1
    through `TaskData.system_prompt` (which `Harness.resolve_prompt` emits as a
    separate system message when the harness sets `APPENDS_SYSTEM_PROMPT`, and
    otherwise prepends itself, with a warning). One rendering of the format spec,
    owned by the framework in both cases.
    """
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message(goal)},
    ]


def completion_text(completion: Any) -> str:
    """Last assistant turn as text, from either v0 message mode.

    The v0 path only: chat mode hands the rubric a `list[ChatMessage]`,
    `message_type="completion"` a bare `str`. (v1 needs none of this —
    `Trace.last_reply` is already the last assistant turn as a stripped `str`.)
    Single-shot means there is exactly one assistant turn to read. Anything
    unrecognized becomes the empty string, which the parser turns into a loud
    FORMAT_ERROR — never an exception, because an unexpected completion shape is
    policy evidence, not infrastructure failure (§6), and must be counted rather
    than crash the batch.
    """
    if isinstance(completion, str):
        return completion
    if isinstance(completion, list) and completion:
        last = completion[-1]
        if isinstance(last, dict):
            return str(last.get("content") or "")
        return str(getattr(last, "content", "") or "")
    return ""


# ---------------------------------------------------------------------------
# Goals dataset
# ---------------------------------------------------------------------------

_ID_FIELDS = ("id", "source_id", "statement_key")  # scripts/build_bank.py rows carry the latter two

# The dataset an environment constructed with no goal source runs on. Four true,
# one-line Mathlib-provable props, ids labelled `demo-` so no result table can
# mistake a demo run for a bank run.
#
# It exists for *loadability*, not for evidence: the Hub's integration test loads
# the published environment on a box with no Lean toolchain, and a `goals`-less
# `load_environment()` / `build_taskset()` has to hand it a real dataset. Kept
# tiny on purpose — a large built-in set would be a second, untracked goal bank
# competing with `data/` — and deliberately easy, so that if one ever *is* run
# against a live backend the interesting signal is the plumbing, not the math.
DEMO_GOALS: tuple[GoalSpec, ...] = (
    GoalSpec(id="demo-00", prop="2 ∣ 4", name="demo_two_dvd_four"),
    GoalSpec(id="demo-01", prop="∀ n : ℕ, n + 0 = n", name="demo_add_zero"),
    GoalSpec(id="demo-02", prop="∀ x : ℝ, 0 ≤ x ^ 2", name="demo_sq_nonneg"),
    GoalSpec(id="demo-03", prop="1 + 1 = 2", name="demo_one_add_one"),
)


def load_goals(source: str | Path | Iterable[GoalSpec | dict]) -> list[GoalSpec]:
    """Normalize a goal source into `list[GoalSpec]`.

    Accepts a JSONL path (`{"id", "prop", "name"}` rows) or any iterable of
    GoalSpec/dict. A row without a usable `prop` raises rather than being
    dropped: a silently shortened dataset makes two runs incomparable, and the
    ../rl lesson (silent format failure) applies to inputs too.
    """
    if isinstance(source, (str, Path)):
        rows: Iterable[Any] = _read_jsonl(Path(source))
    else:
        rows = source

    goals: list[GoalSpec] = []
    for i, row in enumerate(rows):
        if isinstance(row, GoalSpec):
            goals.append(row)
            continue
        if not isinstance(row, dict):
            raise TypeError(f"goal row {i}: expected GoalSpec or dict, got {type(row).__name__}")
        prop = (row.get("prop") or "").strip()
        if not prop:
            raise ValueError(f"goal row {i}: missing 'prop'")
        gid = next((str(row[f]) for f in _ID_FIELDS if row.get(f)), f"g{i}")
        name = str(row.get("name") or "goal")
        goals.append(GoalSpec(id=gid, prop=prop, name=name))
    if not goals:
        raise ValueError("no goals loaded")
    return goals


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def goal_rows(goals: Iterable[GoalSpec]) -> list[dict]:
    """v0 dataset rows (research §3.1: `prompt` / `answer` / `info`).

    `info` carries the GoalSpec verbatim because the reward function is handed
    the row's `info`, not the object: it rebuilds the goal from these three
    fields. `answer` is the proposition — unused by scoring (the kernel is the
    judge) but it is what `prime eval view` shows next to a rollout.
    """
    return [
        {
            "prompt": [{"role": "user", "content": user_message(g)}],
            "answer": g.prop,
            "info": {"id": g.id, "prop": g.prop, "name": g.name},
        }
        for g in goals
    ]


def build_dataset(goals: Iterable[GoalSpec]):
    """`datasets.Dataset` of `goal_rows`. Needs no verifiers (`datasets` is a
    core dependency), so dataset shape is testable without the extra."""
    from datasets import Dataset

    return Dataset.from_list(goal_rows(goals))


# ---------------------------------------------------------------------------
# Raw scoring — the seam every surface below goes through
# ---------------------------------------------------------------------------

# plan_stats keys, for the "there was no plan" case. Kept explicit so a change
# in detectors.plan_stats shows up here as a test failure rather than as a
# silently missing metric column.
_PLAN_STAT_KEYS = ("n_lemmas", "mean_prop_chars", "max_prop_chars", "restatement_max", "is_direct")


@dataclass(frozen=True)
class EpisodeScore:
    """One scored completion: the reward, the full result, the loggable info."""

    reward: float
    result: EpisodeResult
    info: dict[str, Any]

    @property
    def metrics(self) -> dict[str, float]:
        """The float-only subset, for channels that take numbers.

        Includes one 0/1 indicator per `Status`, which is how the §5.7
        "status separation is non-negotiable" requirement survives averaging:
        the group mean of `status_leaf_failed` *is* the leaf-failure rate, with
        no post-hoc join against a string column.
        """
        out: dict[str, float] = {
            "reward": self.reward,
            "leaf_attempts_used": float(self.info["leaf_attempts_used"]),
            "elapsed_s": float(self.info["elapsed_s"]),
        }
        for s in Status:
            out[f"status_{s.value}"] = 1.0 if self.info["status"] == s.value else 0.0
        stats = self.info["plan_stats"]
        if stats is not None:
            out.update({f"plan_{k}": float(stats[k]) for k in _PLAN_STAT_KEYS})
        return out


def episode_info(goal: GoalSpec, result: EpisodeResult) -> dict[str, Any]:
    """JSON-serializable per-sample diagnostics (DIRECTION.md §5.7).

    `plan_stats` is `None` — not a zero-filled dict — when the completion never
    parsed. Absence is the representation for "no plan existed", the same
    discipline `episode.run_episode` uses for untried lemmas; zeros would make
    a FORMAT_ERROR indistinguishable from a direct-close plan in the P4 rates.

    `detail` is truncated because a COMPOSE_FAILED detail embeds the whole
    artifact and these rows go into every training log; the untruncated text is
    on `EpisodeScore.result`.
    """
    return {
        "goal_id": goal.id,
        "status": result.status.value,
        "detail": result.detail[:INFO_DETAIL_CHARS],
        "leaf_attempts_used": result.leaf_attempts_used,
        "n_lemma_outcomes": len(result.lemma_outcomes),
        "elapsed_s": round(result.elapsed_s, 4),
        "plan_stats": plan_stats(result.plan, goal) if result.plan is not None else None,
    }


def score_plan(
    goal: GoalSpec,
    plan_text: str,
    *,
    backend: LeanBackend,
    leaf: LeafProver,
    budgets: Budgets,
) -> EpisodeScore:
    """Run one episode and package it. The only scoring path in this module.

    Terminal reward only (§5.6): `EpisodeResult.reward` is 1.0 for a sanitized,
    kernel-verified closure and 0.0 otherwise. `r_plan` is diagnostic and is not
    mixed in — it reaches the logs as `plan_stats` / the status indicators.

    Backend explosions propagate, exactly as `run_episode` intends: an
    infrastructure failure scored as 0.0 would be indistinguishable from a
    policy failure and would poison the very separation §6 demands.
    """
    result = run_episode(goal, plan_text, leaf, backend, budgets)
    return EpisodeScore(reward=result.reward, result=result, info=episode_info(goal, result))


# ---------------------------------------------------------------------------
# Live resources
# ---------------------------------------------------------------------------

@dataclass
class EpisodeResources:
    """The live handles a rollout needs: Lean backend, leaf prover, budgets, goals.

    A module-level registry exists because of a v1 constraint, not by taste:
    a v1 `Taskset` is constructed by the loader from a serializable config
    (`load_taskset` -> `taskset_class(config.id)(config)`) and `TaskData` is a
    frozen pydantic model that travels over the env-server wire, so a REPL pool
    or an OpenAI-backed leaf cannot ride through either. The task reaches them
    by process-global lookup instead. The v0 surface captures the same objects
    in closures and never consults this.

    `budgets` is the v0 default and the `build_taskset` seed only; a v1 task
    reads its budgets from `DecompositionTaskConfig`, which is the only copy the
    scoring process is guaranteed to have.

    `backend` and `leaf` are optional *fields* so that a process which has goals
    but no Lean toolchain can still register what it does have and construct an
    inspectable environment (see the module docstring). They are not optional for
    scoring: `live_resources()` is the gate every rollout path goes through, and
    it raises when either is absent rather than letting a `None` backend surface
    as an AttributeError halfway through an episode.
    """

    backend: LeanBackend | None = None
    leaf: LeafProver | None = None
    budgets: Budgets = field(default_factory=Budgets)
    goals: list[GoalSpec] = field(default_factory=list)


_RESOURCES: EpisodeResources | None = None


def set_resources(resources: EpisodeResources | None) -> None:
    global _RESOURCES
    _RESOURCES = resources


def get_resources() -> EpisodeResources:
    """Whatever is registered — the construction-time question ("is there a goal
    source, a budget default?"). `live_resources` is the scoring-time one."""
    if _RESOURCES is None:
        raise RuntimeError(
            "no EpisodeResources registered: call rlmath.envs.set_resources("
            "EpisodeResources(backend=..., leaf=..., budgets=..., goals=[...])) "
            "before the taskset/environment runs a rollout"
        )
    return _RESOURCES


def live_resources() -> EpisodeResources:
    """The registered resources, asserted to carry a live backend *and* leaf.

    The one gate between every surface and `score_plan`. It raises — it does not
    return a default, a null backend, or a reward — because the alternative is a
    0.0 produced by a missing kernel, which is indistinguishable from a policy
    failure in every downstream mean (§6, §5.7). A hosted eval with no Lean
    toolchain must fail loudly; it must never publish fake numbers.
    """
    res = get_resources()
    missing = [name for name in ("backend", "leaf") if getattr(res, name) is None]
    if missing:
        raise RuntimeError(
            f"registered EpisodeResources carry no {' and no '.join(missing)}: an episode "
            "cannot be scored without a live Lean backend and leaf prover. Call "
            "rlmath.envs.set_resources(EpisodeResources(backend=..., leaf=..., "
            "goals=[...])) in the process that scores"
        )
    return res


def resolve_goals(
    goals: str | Path | Iterable[GoalSpec | dict] | None = None,
) -> list[GoalSpec]:
    """The one goal-source rule, shared by every surface.

    Explicit argument > registered `EpisodeResources` > `DEMO_GOALS`. The demo
    tail is what makes a bare `load_environment()` / `build_taskset()` work where
    no resources exist (Hub discovery and the Hub's integration test).

    It is a tail, not a repair: resources registered with an *empty* goal list
    still raise, because silently swapping in four demo goals would turn a
    misconfigured run into a green four-sample report instead of an error — the
    same discipline `load_goals` applies to a dropped row.
    """
    if goals is not None:
        return load_goals(goals)
    if _RESOURCES is None:
        return list(DEMO_GOALS)
    if not _RESOURCES.goals:
        raise ValueError(
            "the registered EpisodeResources carry no goals: register "
            "EpisodeResources(..., goals=[...]), pass goals=..., or set the taskset "
            "config's `goals` to a JSONL path"
        )
    return list(_RESOURCES.goals)


def _require(available: bool, what: str) -> None:
    if not available:
        raise ImportError(
            f"{what} requires the optional `verifiers` dependency, which is not installed. "
            "Install it with: uv sync --extra envhub   (or: uv add verifiers)"
        )


# ---------------------------------------------------------------------------
# v1 surface (primary) — Taskset / Task / TaskData
# ---------------------------------------------------------------------------
#
# Verified against the installed `verifiers` 0.3.0 source (not the research
# notes, which predate the wheel). What the real API turned out to be:
#
#   * `Taskset.__init__(self, config)` takes the config positionally and is not
#     meant to be overridden (`verifiers/v1/taskset.py`); `load_taskset` calls
#     `taskset_class(config.id)(config)`. One construction, no fallback.
#   * The per-trace channels are explicit methods on `Trace`
#     (`verifiers/v1/trace.py`): `record_metric(name, float)` /
#     `record_metrics(mapping)` write `trace.metrics: dict[str, float | None]`,
#     and `trace.info: dict[str, Any]` is the declared "scratch space for
#     task-specific metadata". Both survive `Trace.to_record()`.
#   * `TaskData` *does* have a `system_prompt` slot, so the prompt is not
#     inlined: `Harness.resolve_prompt` emits it as a real system message.
#
# The one structural adaptation: budgets moved from `TasksetConfig` to
# `TaskConfig` (`config.task`). In a served run the client owns the taskset and
# the server "never `load()`s data" — it rebuilds each task as
# `task_cls(wire_data, env.config.taskset.task)` (`verifiers/v1/serve/server.py`
# `_build_task`). Budgets applied as a side effect of `load()` would therefore
# never reach the process that scores, and §5.6's hard caps would silently
# revert to defaults under prime-rl. Read from `self.config` they arrive
# wherever the task is executed, and stay sweepable from TOML as
# `[env.taskset.task]`.
#
# The classes are defined under a flag rather than in a factory because the v1
# loader discovers the taskset from the module's `__all__`
# (`verifiers/v1/utils/loaders.py::_plugin_class`, which requires *exactly one*
# `Taskset` subclass there) — that needs a real class at module scope, while
# `import rlmath.envs.decomp_env` must still succeed with the extra absent.

if HAS_VERIFIERS_V1:

    class DecompositionData(vf1.TaskData):
        """Immutable per-goal row. Mirrors GoalSpec; carries no live handles.

        `prompt` is the goal turn only and `system_prompt` the format spec — the
        base `TaskData` fields, so the harness owns the system slot and the
        saved trace stays self-describing without a hand-flattened string.

        `decl_name`, not `name`: `TaskData.name` is the framework's display label
        and overloading it with the goal's Lean declaration name would make an
        eval listing read as a pile of theorem names with no goal ids.
        """

        goal_id: str
        prop: str
        decl_name: str

    class DecompositionTaskConfig(vf1.TaskConfig):
        """Per-task knobs, reachable as `[env.taskset.task]` / `--env.taskset.task.*`.

        §5.6's hard caps live here rather than on the taskset config because the
        env server builds every task from *its* copy of this subtree without
        ever calling `load()` (see the note above).
        """

        max_lemmas: int = _DEFAULTS.max_lemmas
        leaf_attempts_per_lemma: int = _DEFAULTS.leaf_attempts_per_lemma
        max_total_leaf_attempts: int = _DEFAULTS.max_total_leaf_attempts
        verify_timeout_s: float = _DEFAULTS.verify_timeout_s

    class DecompositionTask(vf1.Task[DecompositionData, vf1.State, DecompositionTaskConfig]):
        """One goal, one plan, one kernel verdict.

        A single `@vf.reward` method does all the work: the episode is real Lean
        (and possibly real leaf-model) compute, so it must run exactly once per
        trace. `Task.score` runs every `@metric` concurrently with no shared
        cache, so splitting the diagnostics out into their own methods would
        re-run the episode; recording them from here is cheaper and race-free.
        """

        NEEDS_CONTAINER = False  # the Lean backend is the harness's, not the rollout's

        @vf1.reward(weight=1.0)
        async def verified(self, trace: vf1.Trace) -> float:
            # live_resources, not get_resources: the taskset may have been built
            # for inspection over DEMO_GOALS with no kernel in the process. That
            # is legal to *load*; scoring it must raise, and `Task.score` turns
            # the raise into a TaskError with no reward recorded on the trace —
            # never a 0.0 that would average in as a policy failure.
            res = live_resources()
            goal = GoalSpec(id=self.data.goal_id, prop=self.data.prop,
                            name=self.data.decl_name)
            # to_thread: run_episode blocks on the Lean backend, and every
            # concurrent rollout shares one event loop (research §8 gotcha a).
            score = await asyncio.to_thread(
                score_plan,
                goal,
                trace.last_reply,  # already the last assistant turn as text
                backend=res.backend,
                leaf=res.leaf,
                budgets=budgets_from_config(self.config),
            )
            attach_diagnostics(trace, score)
            return score.reward

    class DecompositionConfig(vf1.TasksetConfig):
        """Load-time knobs (`[env.taskset]`): which goals, and the task subtree."""

        # JSONL path; None = the registered resources' goals, else DEMO_GOALS
        goals: str | None = None
        task: DecompositionTaskConfig = DecompositionTaskConfig()

    class DecompositionTaskset(vf1.Taskset[DecompositionTask, DecompositionConfig]):
        def load(self) -> list[DecompositionTask]:
            """Tasks for the configured goals.

            `resolve_goals` is what makes `DecompositionTaskset(DecompositionConfig())`
            — the default-config construction a v1 discovery/integration check
            performs — succeed with no registered resources: it falls back to
            DEMO_GOALS. It still raises when a *named* source is empty.

            Both config fields are read with `getattr`, because `load_taskset` is
            `taskset_class(id)(config)` and a discovery path that has not resolved
            our config specialization (`loaders.taskset_config_type`) hands us a
            *base* `TasksetConfig`, which carries neither field — an AttributeError
            there would fail a load for a reason unrelated to what it was asking
            for. Neither fallback can mask a real setting: the field *names* are
            pinned by `test_v1_taskset_reads_the_goals_path_off_its_config` and
            `test_v1_taskset_takes_its_config_positionally`, and the task fallback
            is `DecompositionTaskConfig()` — the same §5.6 defaults a base config
            implies anyway.
            """
            goals = resolve_goals(getattr(self.config, "goals", None) or None)
            task_cfg = getattr(self.config, "task", None) or DecompositionTaskConfig()
            return [
                DecompositionTask(
                    DecompositionData(
                        idx=i,
                        name=g.id,
                        prompt=user_message(g),
                        system_prompt=SYSTEM_PROMPT,
                        goal_id=g.id,
                        prop=g.prop,
                        decl_name=g.name,
                    ),
                    task_cfg,
                )
                for i, g in enumerate(goals)
            ]


def budgets_from_config(cfg: Any) -> Budgets:
    """v1 task config -> core Budgets (verifiers-free, so it is unit-testable)."""
    return Budgets(
        max_lemmas=cfg.max_lemmas,
        leaf_attempts_per_lemma=cfg.leaf_attempts_per_lemma,
        max_total_leaf_attempts=cfg.max_total_leaf_attempts,
        verify_timeout_s=cfg.verify_timeout_s,
    )


TRACE_INFO_KEY = "rlmath"


def attach_diagnostics(trace: Any, score: EpisodeScore) -> None:
    """Put the §5.7 diagnostics on the trace, through the two real channels.

    `Trace.record_metrics` coerces to float and writes `trace.metrics`, which is
    typed `dict[str, float | None]` — the JSON blob must therefore *not* go
    there (it would break the schema and the aggregate means). It goes to
    `trace.info`, the declared scratch space for task-specific metadata; both
    dicts are ordinary pydantic fields and both survive `Trace.to_record()` into
    `traces.jsonl`. No fallback: if either call ever disappears this must fail
    loudly, because losing the P4 instrument silently is the one outcome that
    makes a whole training run uninterpretable after the fact.
    """
    trace.record_metrics(score.metrics)
    trace.info[TRACE_INFO_KEY] = score.info


def build_taskset(
    *,
    goals: str | Path | Iterable[GoalSpec | dict] | None = None,
    backend: LeanBackend | None = None,
    leaf: LeafProver | None = None,
    budgets: Budgets | None = None,
    config: Any = None,
):
    """Construct the v1 taskset in-process (local eval, tests, the depth-2 probe).

    A published Hub run never calls this — the v1 loader instantiates
    `DecompositionTaskset` from TOML — so this is the path that also registers
    the live handles the config cannot carry.

    Every argument is optional so that `build_taskset()` is a valid no-argument
    construction over `DEMO_GOALS`, which is what makes the module importable and
    discoverable where there is no Lean toolchain. A call that names *nothing*
    registers nothing: it must not clobber handles a launcher already registered,
    and the taskset it returns raises at score time until some process registers
    a backend and leaf.
    """
    _require(HAS_VERIFIERS_V1, "build_taskset")
    budgets = budgets or Budgets()
    if goals is not None or backend is not None or leaf is not None:
        set_resources(EpisodeResources(backend=backend, leaf=leaf, budgets=budgets,
                                       goals=resolve_goals(goals)))
    if config is None:
        config = DecompositionConfig(
            id=ENV_ID,
            task=DecompositionTaskConfig(
                max_lemmas=budgets.max_lemmas,
                leaf_attempts_per_lemma=budgets.leaf_attempts_per_lemma,
                max_total_leaf_attempts=budgets.max_total_leaf_attempts,
                verify_timeout_s=budgets.verify_timeout_s,
            ),
        )
    return DecompositionTaskset(config)


# ---------------------------------------------------------------------------
# v0 surface (shim) — SingleTurnEnv + Rubric
# ---------------------------------------------------------------------------

_STATE_KEY = "rlmath"


def _episode_reward(backend: LeanBackend | None, leaf: LeafProver | None, budgets: Budgets):
    """The weighted reward function; also the only place the episode runs.

    v0 rubric functions execute in registration order over a shared `state`
    (research §3.3), so this one runs the episode, parks the diagnostics in
    `state` — where they survive into `RolloutOutput` and the saved results
    columns — and the weight-0 metric functions below just read them back.

    The handles are resolved per call, not captured at load time: `load_environment()`
    must build with nothing registered (Hub discovery), and a launcher is allowed
    to `set_resources` after building the env. Absent at score time, the call
    raises. Note that verifiers' own `Rubric` catches a reward-function exception
    and records 0.0 with a logged error (`rubrics/rubric.py::_call_individual_reward_func`),
    so on v0 that log is the loudest signal available — which is precisely why
    this function must *raise* rather than return a number: the fabrication is
    then the framework's and recoverable from its log, never ours and silent.
    (v1, the training path, propagates it as a `TaskError` and records no reward.)
    """

    async def episode_reward(completion, info=None, state=None, **kwargs) -> float:
        live_backend, live_leaf = backend, leaf
        if live_backend is None or live_leaf is None:
            res = live_resources()
            live_backend = live_backend or res.backend
            live_leaf = live_leaf or res.leaf
        info = info or {}
        goal = GoalSpec(
            id=str(info.get("id", "")),
            prop=str(info.get("prop", "")),
            name=str(info.get("name", "goal")),
        )
        score = await asyncio.to_thread(
            score_plan,
            goal,
            completion_text(completion),
            backend=live_backend,
            leaf=live_leaf,
            budgets=budgets,
        )
        if state is not None:
            state[_STATE_KEY] = score.info
            state[f"{_STATE_KEY}_metrics"] = score.metrics
        return score.reward

    return episode_reward


def _metric_func(key: str):
    async def metric(state=None, **kwargs) -> float:
        return float((state or {}).get(f"{_STATE_KEY}_metrics", {}).get(key, 0.0))

    metric.__name__ = key
    return metric


def _metric_keys() -> list[str]:
    """Metric columns, fixed independently of any one rollout so the schema is
    stable across a run (a plan-less episode contributes no `plan_*` values)."""
    return (
        ["leaf_attempts_used", "elapsed_s"]
        + [f"status_{s.value}" for s in Status]
        + [f"plan_{k}" for k in _PLAN_STAT_KEYS]
    )


def load_environment(
    *,
    goals: str | Path | Iterable[GoalSpec | dict] | None = None,
    backend: LeanBackend | None = None,
    leaf: LeafProver | None = None,
    budgets: Budgets | None = None,
    eval_goals: str | Path | Iterable[GoalSpec | dict] | None = None,
    **kwargs: Any,
):
    """v0 Hub entry point (`prime eval run`, `vf.load_environment`, `vf-eval`).

    Must keep this exact name to be discoverable (research §4/§7.2). Live
    handles cannot come from `--env-args`, so an omitted `backend`/`leaf` falls
    back to the registered `EpisodeResources` — the CLI path is expected to
    register them from a launcher, the in-process path to pass them directly.

    `load_environment()` with no arguments and nothing registered is a supported
    call and returns a real `SingleTurnEnv` over `DEMO_GOALS`: the Hub's
    integration test loads the published environment on infra with no Lean
    toolchain, and a load-time failure there means the version cannot be
    published at all. Only construction is served that way — the rubric resolves
    the live handles at *score* time and raises when they are missing (see
    `_episode_reward`), so no rollout is ever scored against an absent kernel.
    """
    _require(HAS_VERIFIERS_V0, "load_environment")
    # Registered resources fill in whatever the caller omitted; `goals` is
    # resolved by the shared rule (argument > resources > demo).
    if _RESOURCES is not None:
        backend = backend if backend is not None else _RESOURCES.backend
        leaf = leaf if leaf is not None else _RESOURCES.leaf
        budgets = budgets or _RESOURCES.budgets
    budgets = budgets or Budgets()

    funcs = [_episode_reward(backend, leaf, budgets)] + [_metric_func(k) for k in _metric_keys()]
    weights = [1.0] + [0.0] * (len(funcs) - 1)  # terminal reward only (§5.6)
    return vf0.SingleTurnEnv(
        dataset=build_dataset(resolve_goals(goals)),
        eval_dataset=build_dataset(load_goals(eval_goals)) if eval_goals is not None else None,
        system_prompt=SYSTEM_PROMPT,
        rubric=vf0.Rubric(funcs=funcs, weights=weights),
        **kwargs,
    )


__all__ = [
    "DEMO_GOALS",
    "ENV_ID",
    "HAS_VERIFIERS",
    "HAS_VERIFIERS_V0",
    "HAS_VERIFIERS_V1",
    "SYSTEM_PROMPT",
    "TRACE_INFO_KEY",
    "EpisodeResources",
    "EpisodeScore",
    "attach_diagnostics",
    "build_dataset",
    "build_prompt",
    "build_taskset",
    "budgets_from_config",
    "completion_text",
    "episode_info",
    "get_resources",
    "goal_rows",
    "live_resources",
    "load_environment",
    "load_goals",
    "resolve_goals",
    "score_plan",
    "set_resources",
    "user_message",
]

# The v1 loader resolves the taskset off `__all__` and requires *exactly one*
# `Taskset` subclass there (`loaders._plugin_class`) — adding a second would
# turn discovery into a hard error, so keep this list at one taskset.
if HAS_VERIFIERS_V1:
    __all__ += ["DecompositionConfig", "DecompositionData", "DecompositionTask",
                "DecompositionTaskConfig", "DecompositionTaskset"]
