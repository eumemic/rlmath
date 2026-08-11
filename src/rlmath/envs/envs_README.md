# `rlmath-decomp` — the decomposition environment in `verifiers` format

The Phase-0 shipping artifact (DIRECTION.md §5.5): `harness.episode.run_episode` wrapped so
Prime Intellect's Environments Hub can serve it and `prime-rl` can train against it (§5.3).
One completion = one decomposition plan = one kernel verdict.

Code: `src/rlmath/envs/decomp_env.py`. Tests: `tests/test_env.py`.

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
`INFO_DETAIL_CHARS`) rides the per-sample info channel: v0 parks it in `state["rlmath"]`, v1
attaches it to the trace.

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

A rollout needs a `LeanBackend`, a `LeafProver` and `Budgets`. v1 forbids live handles on the wire —
"only `TaskData` is stored on the trace" (research §5.1) — and a `TasksetConfig` is serializable, so
they cannot travel through either. They are registered process-globally instead:

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

Budget knobs are also v1 config fields (`max_lemmas`, `leaf_attempts_per_lemma`,
`max_total_leaf_attempts`, `verify_timeout_s`), so an RL run can sweep §5.6's hard caps from TOML
without touching code.

### Goals dataset

`load_goals` takes a JSONL path or any iterable of `GoalSpec`/dict. Rows:

```json
{"id": "lw_00123", "prop": "∀ n : ℕ, n + 0 = n", "name": "thm_lw_00123"}
```

`prop` is required (a row without one raises — a silently shortened dataset makes two runs
incomparable). `id` falls back to `source_id` / `statement_key` (the shapes
`scripts/build_bank.py` writes) and then to the row index; `name` defaults to `goal`.

## Publishing to the Environments Hub

Steps exactly as research/verifiers.md §7 documents them. **TODO (Phase-0 pending item, see
PHASE0_NOTES.md): needs a Prime Intellect account — no push has been made yet.**

1. **Auth.** `uv tool install prime && prime login`  ← *TODO: account decision*
2. **Package.** The Hub build pipeline assumes Hatchling and one package directory per environment.
   Hub id `rlmath-decomp` → module `rlmath_decomp`. Create at publish time (not committed yet —
   deciding to publish is a user decision, per §7.2):

   ```text
   environments/rlmath_decomp/
   ├── rlmath_decomp/
   │   ├── __init__.py     # from rlmath.envs.decomp_env import DecompositionTaskset, load_environment
   │   │                   # __all__ = ["DecompositionTaskset"]   # v1 discovery reads __all__
   │   └── taskset.py      # optional: re-export only
   ├── pyproject.toml
   └── README.md           # this file
   ```

   ```toml
   [project]
   name = "rlmath-decomp"
   description = "Lean 4 decomposition MDP: root states lemmas + assembly, frozen leaf prover closes them"
   tags = ["single-turn", "math", "lean", "formal-verification", "train", "eval"]
   version = "0.1.0"
   requires-python = ">=3.12"
   dependencies = ["verifiers>=0.3.0", "rlmath"]

   [build-system]
   requires = ["hatchling"]
   build-backend = "hatchling.build"

   [tool.hatch.build]
   include = ["rlmath_decomp", "pyproject.toml"]   # pyproject must ship: metadata is read post-install

   [tool.verifiers.eval]
   num_examples = 20
   rollouts_per_example = 5
   ```

3. **Verify locally first.** `prime eval run rlmath-decomp -m <model> -n 5` (or `vf-eval`), with a
   live Lean backend and leaf registered via `set_resources`.
4. **Push.** `prime env push rlmath-decomp --visibility PRIVATE|PUBLIC` (defaults to
   `./environments/rlmath-decomp`). Visibility is **a user decision, never a default** — research
   §7.2: "Publishing is an external state change... Do not publish merely because local verification
   passed."  ← *TODO: visibility decision*
5. **Hosted eval.** `prime eval run rlmath-decomp --hosted --follow`.
6. **Consume elsewhere.** `prime env install <owner>/rlmath-decomp`, `prime env info
   <owner>/rlmath-decomp`, or in code `vf.load_environment("<owner>/rlmath-decomp")` (v0) /
   `vf.load_taskset(...)` (v1).

Scaffolding commands, if a from-scratch package is preferred over the hand-written one above:
`prime env init rlmath-decomp` emits a **v0** stub; `uv run init rlmath-decomp` inside the verifiers
repo emits a **v1** taskset package.

### Training with prime-rl

Orchestrator config sections are `[[orchestrator.train.source]]` / `[[orchestrator.eval.source]]`
(research §6). Sketch:

```toml
[[orchestrator.train.source]]
name = "rlmath-decomp"

[orchestrator.train.source.env.taskset]
id = "rlmath-decomp"
max_lemmas = 8
leaf_attempts_per_lemma = 4

[orchestrator.train.source.env.agent.runtime]
type = "prime"
```

Open question for that step (§5.3 assumes a Kimina/REPL backend on a large-CPU box): the Lean
backend and the frozen leaf are *outside* the rollout runtime here, reached through
`set_resources`, so a `prime`/`modal` runtime needs them exposed as services rather than
in-process. That is a Phase-3 integration decision, not a Phase-0 blocker.
