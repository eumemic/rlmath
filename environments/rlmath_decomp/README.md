# `rlmath-decomp` — the decomposition environment in `verifiers` format

The Phase-0 shipping artifact (DIRECTION.md §5.5): `harness.episode.run_episode` wrapped so
Prime Intellect's Environments Hub can serve it and `prime-rl` can train against it (§5.3).
One completion = one decomposition plan = one kernel verdict.

Code: `src/rlmath/envs/decomp_env.py`. Tests: `tests/test_env.py`. Hub package:
`environments/rlmath_decomp/` (re-export only — one scoring path, one set of tests).

This file is also the Hub package's `README.md`, verbatim: `environments/rlmath_decomp/README.md`
is a copy, and `tests/test_env.py::test_hub_package_readme_is_a_verbatim_copy` fails if they drift.
Edit this one.

Every `verifiers` fact below is checked against the **installed** 0.3.0 source, not
research/verifiers.md — the notes were taken from a repo clone and are wrong in two places, both
now fixed here (see "What the research notes got wrong").

## Which verifiers surface this targets, and why

`verifiers` is mid-migration (research/verifiers.md §1). Both stacks ship in 0.3.0:

| | v0 (`import verifiers as vf`) | v1 (`import verifiers.v1 as vf`) |
|---|---|---|
| Objects | `SingleTurnEnv` / `Rubric` / `Parser` | `Taskset` / `Task` / `TaskData` / `Harness` / `Trace` |
| Status | default namespace, **documented deprecated** | what new environments are told to target |
| Entry point | `load_environment(**kwargs)` | `Taskset` subclass exported in `__all__` |
| `prime-rl` | **not used at all** | the only surface its orchestrator speaks |

**Primary target: v1.** DIRECTION.md §5.3 names `prime-rl` as the trainer and §5.5 makes the
published environment the Phase-0 artifact; `prime-rl`'s orchestrator is built exclusively against
`verifiers.v1` (research §6), so the training path decides it.

**v0 is kept as a thin shim** over the same scorer (`load_environment`), because it is ~40 lines
once `score_plan` exists and it buys the whole legacy eval toolchain — `prime eval run`, `vf-eval`,
`prime gepa run` — which the Phase-2 zero-shot study (§5.5) needs long before a trainer.

Both surfaces call one function, `decomp_env.score_plan`, which calls `run_episode`. There is no
second scoring path and no second sanitizer.

## Install

`verifiers` is heavy (pulls the training stack), so it sits behind an optional extra. The module
imports and the offline tests pass **without** it.

```bash
uv sync                       # core: harness, tests, no verifiers
uv sync --extra envhub        # + verifiers, for the Hub / eval / training surfaces
uv tool install prime         # the Prime CLI (companion; loads verifiers as a plugin)
```

`decomp_env.HAS_VERIFIERS` / `HAS_VERIFIERS_V0` / `HAS_VERIFIERS_V1` report what is present;
`build_taskset()` and `load_environment()` raise a clear `ImportError` naming `uv sync --extra
envhub` when it is not.

## Wire format

Single-shot, line-oriented, chatter-tolerant outside the markers and strict inside. Parsed by
`core/plan_format.py`; the exact spec is in `decomp_env.SYSTEM_PROMPT`, which is the only place the
policy is told about it.

```text
#lemma <name> : <prop>      zero or more, one per line, before #assembly
#assembly                   exactly once, after all #lemma lines
<tactic lines>              verbatim, as many as needed
#end                        required
```

- `<name>` matches `[A-Za-z][A-Za-z0-9_']*`, is unique in the plan, does not start with `_`, is not
  reserved (`_plan`, `_stmt_check`, `_proof_check`, `goal`, `this`) and is not the goal's own
  declaration name — a lemma that would shadow the goal is rejected, never silently renamed
  (`harness/composer.py`).
- `<prop>` is a closed Lean 4 proposition on one line. Mathlib is imported.
- Inside the assembly every lemma is in scope as a hypothesis under the stated name and proposition.
- Zero `#lemma` lines is legal: the direct-close action, where the assembly alone must prove the goal.
- Text before the first marker and after `#end` is ignored; anything else between them is a
  `format_error`.
- Banned anywhere (`rlmath/sanitize.py`): `sorry`, `admit`, `axiom`, `native_decide`, `set_option`,
  `macro`, `macro_rules`, `elab`, `notation`, `notation3`, `syntax`, `unsafe`, `partial`, `opaque`,
  `implemented_by`, `extern`, `initialize`, `#exit`.

Example (goal `∀ x : ℝ, 0 ≤ x ^ 2 + 2 * x + 1`):

```text
#lemma h1 : ∀ x : ℝ, 0 ≤ (x + 1) ^ 2
#lemma h2 : ∀ x : ℝ, (x + 1) ^ 2 = x ^ 2 + 2 * x + 1
#assembly
intro x
have h := h1 x
rw [h2 x] at h
exact h
#end
```

## Reward semantics

**Terminal reward only** (DIRECTION.md §5.6): `reward = 1.0` iff the composed artifact passes the
Lean kernel *and* the axiom audit, else `0.0`. `r_plan` (§5.2) is diagnostic and is deliberately
**not** mixed into the scalar — it reaches the logs as the status taxonomy and `plan_stats`.
Budgets are hard caps, not cost penalties, for the reason given in §5.6: penalties suppress
decomposition before it can pay off.

Every other channel is weight-0 (a metric, not a reward): one 0/1 indicator per status — so a group
mean *is* that status's rate — plus `leaf_attempts_used`, `elapsed_s` and the `plan_*` shape
statistics from `harness/detectors.py`. The full JSON blob (including `detail`, truncated to
`INFO_DETAIL_CHARS`) rides the per-sample info channel.

The two real channels, per surface:

| | numbers | the JSON blob |
|---|---|---|
| v1 | `Trace.record_metrics(...)` → `trace.metrics` (`dict[str, float \| None]`) | `trace.info["rlmath"]` (`dict[str, Any]`, the declared task-metadata scratch space) |
| v0 | weight-0 rubric functions → the `metrics` columns | `state["rlmath"]` |

Both v1 dicts are ordinary pydantic fields on `Trace` and survive `Trace.to_record()` into
`traces.jsonl`; the blob must **not** go on `trace.metrics`, which is float-typed and feeds the
aggregate means. `tests/test_env.py::test_v1_p4_diagnostics_reach_the_trace_channels` asserts the
whole path, `to_record()` included — it is the regression guard for the one failure mode that
would make a finished training run uninterpretable.

These are the §5.7 **P4** instrument ("degenerate restatement rises under RL; hard budgets contain
it"). `plan_restatement_max ≈ 1.0` means the root restated the goal as a single lemma and delegated
it — a decomposition that decomposes nothing. It must be in the training logs from the first run,
not added after the plot looks wrong.

### Status taxonomy (`core/types.py`, verbatim semantics)

| Status | Stage that failed | Class |
|---|---|---|
| `verified` | — kernel-checked and axiom-audited | success (reward 1.0) |
| `format_error` | completion did not parse into a plan (or a lemma name collides with the goal) | policy failure |
| `sanitizer_rejected` | banned token, multi-declaration artifact, or axiom-audit failure | policy failure |
| `statement_ill_formed` | a lemma statement failed elaboration | policy failure |
| `plan_invalid` | assembly fails **even granting all the lemmas** | policy failure |
| `leaf_failed` | plan valid, but a lemma resisted the frozen leaf prover | policy failure |
| `compose_failed` | plan + leaves ok, spliced artifact failed the kernel (rare — always investigate) | policy failure |
| `budget_exhausted` | max lemmas or max leaf attempts hit | policy failure |
| `context_window_exceeded` | root prompt/completion beyond the model's window | **feasibility evidence, not scored as failure** (excluded from mean scores) |
| `error` | infrastructure: dead Lean server, timeout, network | **not evidence** — re-run the sample |

Status separation is non-negotiable (§5.7, §6): `plan_invalid` / `leaf_failed` / `budget_exhausted`
/ `context_window_exceeded` / `statement_ill_formed` must never share a bucket, or Phase 3's
transfer plot is uninterpretable after the fact. The last two rows are never produced by this
wrapper: `run_episode` lets backend exceptions propagate so the runner can record an error row and
re-run it (`../rl`'s `repair_errors.py` pattern), and the window guard belongs to the runner, which
knows the root model's context size.

## Context isolation (DIRECTION.md §5.1–§5.2)

The RLM premise being tested is context isolation via external state, so the prompt path is the
experiment:

- The policy sees **goal statements and child statuses only — never proof text.** Leaf proofs and
  the composed artifact live in `EpisodeResult`, go to the kernel and the result log, and are never
  rendered into a message. `tests/test_env.py::test_prompt_never_contains_proof_text` asserts this
  against a real verified artifact rather than by inspection.
- The format spec sits in a **real system slot on both surfaces**, never inlined into the user turn:
  v0 `SingleTurnEnv(system_prompt=...)`, v1 `TaskData.system_prompt` (placed by
  `Harness.resolve_prompt` — emitted as a system message by any harness with
  `APPENDS_SYSTEM_PROMPT`, e.g. `null`). `TasksetConfig.system_prompt` is a file-path override
  applied on iteration, which is what makes the environment GEPA-optimizable.
- The action space is **restricted to decomposition** (`decompose` / direct `close`), not a free
  REPL. §5.1's design note: given a free REPL in `../rl`, the root wrote a Python BFS and made zero
  sub-calls. The analog here would be a root string-generating whole Lean proofs, at which point the
  experiment measures program synthesis instead of decomposition policy.
- **Two-stage verification** (§5.2) is what makes the reward informative: the assembly is checked
  *granting* the lemmas as hypotheses, before any leaf runs, so `plan_invalid` and `leaf_failed`
  are separable and `r = r_plan × r_leaves` factorizes. The prompt states this contract to the
  policy explicitly, because it changes what a good plan looks like.
- v1 is single-shot on purpose (§5.1): vanilla GRPO on completions, no multi-turn machinery.
  Reacting to failed children is v1.5.

## Live resources (the one piece of construction friction)

A rollout needs a `LeanBackend`, a `LeafProver` and `Budgets`. v1 puts only serializable data on the
wire — `TaskData` is a frozen pydantic model shipped per rollout, and a `TasksetConfig` is parsed
from TOML/CLI — so a REPL pool or an OpenAI-backed leaf can travel through neither. They are
registered process-globally instead:

```python
from rlmath.core.types import Budgets, GoalSpec
from rlmath.envs import EpisodeResources, set_resources, build_taskset, load_environment

backend = ...   # rlmath.lean.repl_pool.ReplPool | rlmath.lean.kimina.KiminaClient
leaf    = ...   # rlmath.leaf.LeafProver

# v1 (primary): registers the resources and returns the taskset
taskset = build_taskset(goals="data/goals.jsonl", backend=backend, leaf=leaf,
                        budgets=Budgets(max_lemmas=8))

# v0 (shim): same handles, passed directly or read from the registry
env = load_environment(goals="data/goals.jsonl", backend=backend, leaf=leaf)

# CLI paths (`prime eval run`) cannot pass objects through --env-args:
set_resources(EpisodeResources(backend=backend, leaf=leaf, budgets=Budgets(), goals=[...]))
```

Budget knobs are v1 **task**-config fields (`DecompositionTaskConfig`: `max_lemmas`,
`leaf_attempts_per_lemma`, `max_total_leaf_attempts`, `verify_timeout_s`), so an RL run can sweep
§5.6's hard caps from TOML (`[env.taskset.task]`) or the CLI
(`--env.taskset.task.max-lemmas 4`) without touching code.

They are on the **task** config, not the taskset config, for a reason that only shows up under
prime-rl: in a served run the client owns the taskset and the env server "never `load()`s data" —
it rebuilds each task as `task_cls(wire_data, env.config.taskset.task)`
(`verifiers/v1/serve/server.py::_build_task`). Budgets applied as a side effect of `load()` would
be set in the wrong process and the caps would silently revert to defaults in the one place they
matter most.

### Goals dataset

`load_goals` takes a JSONL path or any iterable of `GoalSpec`/dict. Rows:

```json
{"id": "lw_00123", "prop": "∀ n : ℕ, n + 0 = n", "name": "thm_lw_00123"}
```

`prop` is required (a row without one raises — a silently shortened dataset makes two runs
incomparable). `id` falls back to `source_id` / `statement_key` (the shapes
`scripts/build_bank.py` writes) and then to the row index; `name` defaults to `goal`.

### Running a local eval in-process

The CLIs (`vf-eval`, `prime eval run`, `uv run eval`) each run in their own process, so nothing can
hand them a live `LeanBackend` — `set_resources` has to happen inside the process that scores. Until
the backend is a service (the Phase-3 item at the end of this file), a local eval is an in-process
script:

```python
env = load_environment(goals=[...], backend=ReplPool(n_workers=1), leaf=..., budgets=Budgets(...))
out = env.evaluate_sync(client=vf.ClientConfig(client_type="openai_chat_completions",
                                               api_base_url="http://localhost:11434/v1",
                                               api_key_var="OLLAMA_API_KEY"),
                        model="...", num_examples=3, rollouts_per_example=1,
                        state_columns=["rlmath"])
```

Two things that are easy to get wrong, both found by running it:

- **`client=` wants a `vf.ClientConfig` (or a `vf.Client`), not an `AsyncOpenAI`** — `resolve_client`
  rejects a raw OpenAI client with `Unsupported client type`.
- **`state_columns=["rlmath"]` is required for the JSON blob to reach the saved rows.** The float
  metric columns are promoted automatically; anything parked in `state` is not. Omit it and the
  status/`plan_stats` numbers survive but `detail` and the rest of the blob are dropped — exactly
  the silent-diagnostic-loss failure mode this whole channel exists to prevent.

The first rollout of a run pays the REPL's cold `import Mathlib` (~30 s here, and it lands in that
rollout's `elapsed_s`); warm episodes cost milliseconds. Budget the first one accordingly rather
than reading it as a per-episode cost.

## The Hub package

`environments/rlmath_decomp/` — built, committed, **not pushed**. Layout matches what the real v1
scaffolder emits (`init rlmath-decomp`, a console script `verifiers` installs;
`verifiers/v1/cli/init.py`), because the tooling's layout beats a hand-drawn sketch:

```text
environments/rlmath_decomp/
├── pyproject.toml
├── README.md                # a verbatim copy of this file (kept in sync by a test)
└── rlmath_decomp/
    ├── __init__.py          # re-exports from rlmath_decomp.taskset; names them in __all__
    └── taskset.py           # re-export only — from rlmath.envs.decomp_env import ...
```

Re-export, never a copy of the wrapper: a second scoring path in the published artifact is a second
thing to keep correct, and only one of them would have tests.

Both entry points come out of that one module:

- **v1** — the loader imports `rlmath_decomp` and picks the single `vf.Taskset` subclass out of
  `__all__` (`verifiers/v1/utils/loaders.py::_plugin_class`; **exactly one** — a second export is a
  hard error), then constructs it as `DecompositionTaskset(config)`.
- **v0** — `verifiers.load_environment("rlmath-decomp")` imports the same module and calls
  `load_environment(**env_args)` by name (`verifiers/utils/env_utils.py`).

`pyproject.toml` uses `[tool.hatch.build.targets.wheel] packages = ["rlmath_decomp"]` (the v1
scaffolder's form) rather than the older v0 `[tool.hatch.build] include = [...]`; `tags` and
`[tool.verifiers.eval]` are kept because the Hub pipeline reads them off the pyproject. Nothing in
the installed `verifiers` reads either, so they are unverified locally.

**Resolved 2026-08-11:** `rlmath` is not on PyPI, so the dependency is a git-dep on the public
repo, **pinned to a full commit SHA** (supply-chain review: a floating branch ref would let two
installs of the same published env version resolve to different `rlmath` code — the environment
must be reproducible). `tests/test_env.py` enforces the 40-hex pin.

### Publishing steps

1. **Auth.** `uv tool install prime && prime login`  ✓ done 2026-08-11 (team Eumemic).
2. **Re-pin the `rlmath` dependency to the pushed HEAD.** Before *every* `prime env push`:
   `git push` the library first, then set the dep in `environments/rlmath_decomp/pyproject.toml`
   to `rlmath @ git+https://github.com/eumemic/rlmath@$(git rev-parse HEAD~0)` for the commit the
   push made public, bump the package `version`, and commit the pin. (The pin commit itself need
   not be inside the pinned tree — installers fetch the pinned SHA, which already contains the
   whole library.)
3. **Verify locally first.** `prime eval run rlmath-decomp -m <model> -n 5` (or `vf-eval`, or the v1
   `eval` script), with a live Lean backend and leaf registered via `set_resources` and a harness
   that does not need a container:
   `uv run eval rlmath-decomp --env.agent.harness.id null --env.agent.runtime.type subprocess -n 3`.
   `null` is the tool-less chat loop (`EXECUTES_CODE = False`, `NEEDS_CONTAINER = False`,
   `APPENDS_SYSTEM_PROMPT = True`) — the right shape for a single-shot plan emitter. A code-executing
   harness would hand the policy a shell and quietly turn §5.1's restricted action space back into a
   free REPL.
4. **Push.** `prime env push rlmath-decomp --visibility PRIVATE|PUBLIC` (defaults to
   `./environments/rlmath_decomp`). Visibility is **a user decision, never a default** — research
   §7.2: "Publishing is an external state change... Do not publish merely because local verification
   passed."  ← *TODO: visibility decision*
5. **Hosted eval.** `prime eval run rlmath-decomp --hosted --follow`.
6. **Consume elsewhere.** `prime env install <owner>/rlmath-decomp`, `prime env info
   <owner>/rlmath-decomp`, or in code `vf.load_environment("<owner>/rlmath-decomp")` (v0) /
   `vf.load_taskset(...)` (v1).

Scaffolders, if a from-scratch package is ever preferred: `init <name>` emits a **v1** taskset
package (`--v0` for the legacy stub); `prime env init <name>` / `vf-init <name>` emit the **v0**
stub.

### Training with prime-rl

Orchestrator config sections are `[[orchestrator.train.source]]` / `[[orchestrator.eval.source]]`
(research §6). Sketch:

```toml
[[orchestrator.train.source]]
name = "rlmath-decomp"

[orchestrator.train.source.env.taskset]
id = "rlmath-decomp"
goals = "data/goals.jsonl"

# §5.6's hard caps live on the *task* config — the subtree the env server rebuilds
# each task from. Putting them one level up would not reach the scoring process.
[orchestrator.train.source.env.taskset.task]
max_lemmas = 8
leaf_attempts_per_lemma = 4

[orchestrator.train.source.env.agent.harness]
id = "null"

[orchestrator.train.source.env.agent.runtime]
type = "prime"
```

Open question for that step (§5.3 assumes a Kimina/REPL backend on a large-CPU box): the Lean
backend and the frozen leaf are *outside* the rollout runtime here, reached through
`set_resources` in the **env-server** process, so a `prime`/`modal` runtime needs them exposed as
services rather than in-process. That is a Phase-3 integration decision, not a Phase-0 blocker.

## What the research notes got wrong

Kept as a record, because the wrapper was written against the notes before the library was
installed and both errors were load-bearing:

| research/verifiers.md said | installed 0.3.0 |
|---|---|
| §5.1 "only `TaskData` is stored on the trace"; the harness owns the system slot, so a v1 task has one `prompt` field | `TaskData.system_prompt` exists. The spec is a real system message, not text inlined into the user turn. |
| a `Trace` carries "rewards + metrics + errors" — no call named | `Trace.record_metric(name, float)` / `record_metrics(mapping)` write `trace.metrics`; `trace.info` is the declared task-metadata dict. Explicit methods, not attribute assignment. |
| §5.2 "Don't override `Taskset.__init__`" (correct) but the constructor's arity was unstated | `Taskset(config)`, positional; `load_taskset` calls `taskset_class(config.id)(config)`. |

Not wrong, but only visible in the source: the env server never calls `load()`, which is why the
budgets moved to the task config (above).
