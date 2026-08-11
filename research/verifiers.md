# `verifiers` — research notes (as of 2026-08-11)

Source of truth used: a fresh clone of `github.com/PrimeIntellect-ai/verifiers` (`main`, commit
`c2820d3`), PyPI (`pypi.org/project/verifiers`), and a fresh clone of
`github.com/PrimeIntellect-ai/prime-rl` (`main`). Repo mirrors: `willccbb/verifiers` still exists
but is now a fork/mirror of `PrimeIntellect-ai/verifiers` — the org repo is canonical. Docs moved
off `verifiers.readthedocs.io` (now just a redirect stub) to `docs.primeintellect.ai/verifiers`,
but that hosted site 404s reliably for individual pages during this research; the in-repo
`docs/**/*.md` (Mintlify source) is the same content and is what this file is built from.

**Headline fact that changes everything about "how do I use verifiers today":** the library is
mid-migration from a v0 API (the classic `SingleTurnEnv`/`MultiTurnEnv`/`ToolEnv`/`Rubric`/`Parser`
surface most blog posts and the original README describe) to a v1 API (`Taskset`/`Task`/`Harness`/
`Agent`/`Env`/`Trace`, built around tasksets and an "env server"). Both stacks ship in the same
package today. v0 is explicitly labeled deprecated ("will be fully removed in a future release")
but is still the default `import verifiers as vf` surface and is what `prime env init` scaffolds
unless you ask for v1. v1 is what new environments are told to target, what the bundled example
environments (`gsm8k`, `wordle`, `code_golf`, etc.) are written in, and what `prime-rl`'s
orchestrator actually talks to.

---

## 1. Package identity, version, install

- **PyPI name:** `verifiers` (unchanged). Authored by William Brown (`willccbb`), org-maintained by
  PrimeIntellect-ai. License MIT. `requires-python = ">=3.11,<3.14"`.
- **Current stable version:** **0.3.0**, released **2026-08-07**. As of 2026-08-11 there are
  `0.3.1.dev*` pre-releases already on PyPI (dev15 landed same day), so `0.3.1` is imminent.
  Version is derived from git tags via `hatch-vcs` (`dynamic = ["version"]` in `pyproject.toml`).
- **Recent stable line:** 0.2.0 (Jul 10 2026) → 0.2.1 (Jul 20 2026) → 0.3.0 (Aug 7 2026). Going back
  further: 0.1.9 (Jan 2026), 0.1.10 (Feb 2026), 0.1.11 (Mar 2026), 0.1.12 (Apr 2026), 0.1.14
  (May 2026). First release was 0.0.0 (Jan 28 2025), so v0.1.x/v0.2.x/v0.3.x line spans roughly a
  year with the v0→v1 rewrite landing inside that line (no major version bump was used to mark it —
  it's an internal `verifiers.legacy` vs `verifiers.v1` split, not `verifiers` vs `verifiers2`).
- **Install:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh   # uv
  uv tool install prime                              # Prime CLI (recommended companion)
  uv add verifiers                                   # or: pip install verifiers
  ```
  Extras: `verifiers[modal]` (v1 Modal sandbox runtime), `verifiers[notebook]` (`generate_sync()`
  inside Jupyter/an active event loop), `verifiers[ta]` (TextArena), `verifiers[browser]`
  (Browserbase), `verifiers[openenv]` (OpenEnv gym/MCP tasksets), `verifiers[harbor]`,
  `verifiers[nemo-gym]`.
- **Workspace bootstrap:** `prime lab setup` — runs `uv init` if needed, `uv add verifiers`, and
  drops a recommended workspace layout:
  ```text
  configs/{endpoints.toml, rl/, eval/, gepa/}
  .prime/skills/          # bundled create/browse/review/eval/GEPA/train/brainstorm skills
  environments/AGENTS.md
  AGENTS.md
  CLAUDE.md
  ```
  Add to an existing project instead with `uv add verifiers && prime lab setup --skip-install`.

### The v0/v1 import split (mechanism)

`verifiers/__init__.py` installs a `MetaPathFinder` (`LegacyAliasFinder`) at the front of
`sys.meta_path`. It resolves `verifiers.<name>` to `verifiers.legacy.<name>` for any top-level
submodule that historically lived at that path (`verifiers.envs`, `verifiers.types`,
`verifiers.parsers`, `verifiers.rubrics`, ...), lazily, so `import verifiers` itself stays
side-effect-free and doesn't eagerly load the (heavier) v0 stack. Concretely:

- `import verifiers as vf` → gives you the **v0/legacy** surface (`vf.SingleTurnEnv`, `vf.Rubric`,
  `vf.Parser`, `vf.load_environment`, ...) via this alias shim. This is what almost all existing
  docs, blog posts, and third-party code mean by "`vf`".
  `verifiers.legacy` is the real package; `verifiers.envs`, `verifiers.types` etc. are aliases onto
  it, so `verifiers.types.State is verifiers.legacy.types.State`.
- `import verifiers.v1 as vf` → the **new native** surface (`vf.Taskset`, `vf.Task`, `vf.TaskData`,
  `vf.Harness`, `vf.Agent`, `vf.Env`, `vf.Trace`, `vf.reward`, ...). The repo's own `AGENTS.md`
  explicitly says: "Never mix v0 `Environment`, `Rubric`, `Parser`, `SingleTurnEnv`, `MultiTurnEnv`,
  or `ToolEnv` objects into a v1 taskset."
- `verifiers.legacy` and `verifiers.v1` are otherwise fully separate implementations — no shared
  base classes across the split.

---

## 2. v0 (legacy) — the classic Environment hierarchy

This is the API the task prompt is asking about by name (`SingleTurnEnv`/`MultiTurnEnv`/`ToolEnv`)
and the one that's easiest to bolt an existing sync/async "run one episode, get one score" function
onto. **It is marked deprecated in the docs** ("v0 is considered deprecated and will be fully
removed in a future release") but as of 0.3.0 it is fully functional, still the default `import
verifiers as vf` namespace, and still what `prime env init <name>` scaffolds by default.

### 2.1 Class hierarchy

```
Environment (ABC)                              verifiers.legacy.envs.environment.Environment
└── MultiTurnEnv                                verifiers.legacy.envs.multiturn_env.MultiTurnEnv
    ├── SingleTurnEnv                           max_turns=1, env_response raises NotImplementedError
    ├── ToolEnv                                 stateless Python-function tool calling
    │   ├── StatefulToolEnv                     per-rollout state injected into tool args
    │   │   ├── SandboxEnv                      containerized bash shell (Prime Sandboxes)
    │   │   │   └── PythonEnv                   + persistent Python REPL
    │   │   └── (your CliAgentEnv-style subclasses)
    │   └── MCPEnv                              tools auto-discovered from MCP servers
    └── (your custom MultiTurnEnv subclasses — games, simulations, arbitrary protocols)

EnvGroup                                        combines multiple Environments for mixed-task eval/RL
```

Key architectural fact stated directly in the docs: **every built-in environment type is built on
`MultiTurnEnv`.** `SingleTurnEnv` is *not* a separate rollout implementation — it's literally
`MultiTurnEnv` constructed with `max_turns=1`, with `env_response` overridden to raise (it should
never be called, because the loop stops after turn 1). `ToolEnv` is `MultiTurnEnv` plus tool-calling
wired into `env_response`.

Other environment classes that exist but are integrations/experimental (not part of the stable
hierarchy): `TextArenaEnv`, `ReasoningGymEnv`, `BrowserEnv`, `OpenEnvEnv` (third-party
integrations, each behind an extra); `GymEnv`, `CliAgentEnv`, `SandboxDebugEnv` (deprecated alias:
`SWEDebugEnv`), `HarborEnv`, `OpenCodeEnv`, `OpenCodeRLMEnv` (newer/experimental, "less stable and
more subject to frequent changes").

### 2.2 `Environment` — base class

```python
class Environment(ABC):
    def __init__(
        self,
        dataset: Dataset | None = None,
        eval_dataset: Dataset | None = None,
        system_prompt: str | None = None,
        few_shot: list[ChatMessage] | None = None,
        parser: Parser | None = None,
        rubric: Rubric | None = None,
        sampling_args: SamplingArgs | None = None,
        message_type: MessageType = "chat",       # "chat" | "completion"
        max_workers: int = 512,
        env_id: str | None = None,
        env_args: dict | None = None,
        max_seq_len: int | None = None,
        score_rollouts: bool = True,
        pass_threshold: float = 0.5,
        **kwargs,
    ): ...
```

Notable methods:

| Method | Returns | Description |
|---|---|---|
| `generate(inputs, client, model, sampling_args=None, max_concurrent=-1, ...)` | `GenerateOutputs` | Run rollouts async. `client: Client \| ClientConfig`. `inputs` can be a HF `Dataset` or `list[RolloutInput]`. |
| `generate_sync(...)` | `GenerateOutputs` | Sync wrapper (needs `verifiers[notebook]` inside an already-running loop) |
| `evaluate(client, model, sampling_args=None, num_examples=-1, rollouts_per_example=1, ...)` | `GenerateOutputs` | Runs on `eval_dataset` (falls back to `dataset` if none given) |
| `evaluate_sync(...)` | `GenerateOutputs` | Sync wrapper |
| `get_dataset(n=-1, seed=None)` / `get_eval_dataset(...)` | `Dataset` | |
| `rollout(input, client, model, sampling_args)` | `State` | **Abstract.** Subclasses implement this (or, in practice, subclass `MultiTurnEnv` and implement `env_response` instead — most people never touch `rollout` directly). |
| `is_completed(state)` | `bool` | Runs all registered `@vf.stop` conditions |
| `set_concurrency(n)` | — | Resizes the default `asyncio.to_thread` executor and all registered thread/process-pool executors |
| `add_rubric(rubric)` | — | Merges another rubric in (auto-wraps into a `RubricGroup` as needed) |

### 2.3 `MultiTurnEnv`

```python
class MultiTurnEnv(Environment):
    def __init__(self, max_turns: int = -1, timeout_seconds: float | None = None, **kwargs): ...

    @abstractmethod
    async def env_response(self, messages: Messages, state: State, **kwargs) -> Messages:
        """Generate environment feedback after a model turn. Return new messages to append."""
```

Rollout loop (from `docs/legacy/environments.md`, matches source in `multiturn_env.py`):

1. `setup_state(state)` — per-rollout init hook, no-op by default.
2. Loop until a stop condition fires:
   - get prompt messages (`get_prompt_messages(state)` — initial prompt, or prior turns +
     `env_response(...)`)
   - get model response
   - check stop conditions (`is_completed`)
3. `render_completion(state)` — assemble final `state["completion"]`.
4. Run all `@vf.cleanup` handlers.

Built-in stop conditions (checked every turn, in priority order, all defined with `@vf.stop`):
`has_error` (priority 100 — errors always checked first), `prompt_too_long`, `max_turns_reached`,
`timeout_reached`, `max_total_completion_tokens_reached`, `has_final_env_response`. `ToolEnv` adds
`no_tools_called`.

Hooks you can override in a subclass: `setup_state(state)`, `get_prompt_messages(state)`,
`render_completion(state)`, `add_trajectory_step(state, step)`.

Decorators for lifecycle control (all live on `vf`, imported from `verifiers.legacy.decorators`):

```python
@vf.stop                      # bool method checked after each turn; @vf.stop(priority=10) for order
@vf.cleanup                    # per-rollout teardown, must be idempotent
@vf.teardown                   # environment-shutdown teardown (once)
```

Early termination from inside `env_response`: set `state["final_env_response"]` — this bypasses the
normal loop and ends the rollout immediately (useful when the env's own response is the terminal
signal, e.g. "game over").

Errors: `vf.Error` hierarchy (`ModelError`, `OverlongPromptError`, `ToolError` →
`ToolParseError`/`ToolCallError`, `InfraError` → `SandboxError`/`TunnelError`). Any `vf.Error` raised
during a rollout is caught automatically and stored in `state["error"]`, which trips `has_error` on
the next check — rollouts fail gracefully rather than crashing the whole batch.

### 2.4 `SingleTurnEnv`

The entire class (from `verifiers/legacy/envs/singleturn_env.py`):

```python
class SingleTurnEnv(vf.MultiTurnEnv):
    def __init__(self, **kwargs):
        super().__init__(max_turns=1, **kwargs)

    async def env_response(self, messages, state, **kwargs) -> vf.Messages:
        raise NotImplementedError("env_response is not implemented for SingleTurnEnv")

    async def render_completion(self, state): ...
```

That's it — no rollout logic of its own. One model call, one stop-check (`max_turns_reached` fires
immediately since `max_turns=1`), completion rendered, rubric scores it.

### 2.5 `ToolEnv`

```python
class ToolEnv(MultiTurnEnv):
    def __init__(
        self,
        tools: list[Callable] | None = None,
        max_turns: int = 10,
        error_formatter: Callable[[Exception], str] = lambda e: f"{e}",
        stop_errors: list[type[Exception]] | None = None,
        **kwargs,
    ): ...
```

Tools are plain Python functions (sync or async — async strongly recommended, sync blocks the
shared event loop for *every* concurrent rollout). Name → tool name, type hints → JSON schema,
docstring (Google-style `Args:` section) → tool + per-arg descriptions:

```python
async def calculate(expression: str) -> str:
    """Evaluate a mathematical expression.

    Args:
        expression: A mathematical expression to evaluate (e.g. "2 + 2 * 3")
    """
    try:
        return str(eval(expression))
    except Exception as e:
        return f"Error: {e}"

env = vf.ToolEnv(dataset=dataset, tools=[calculate], rubric=rubric, max_turns=10)
```

Loop: model responds → if it made tool calls, they're executed and results appended as tool
messages → repeat, until the model responds with no tool calls (`no_tools_called` stop condition)
or `max_turns` is hit. Errors not listed in `stop_errors` are caught and turned into tool-response
messages (model gets a chance to recover); errors *in* `stop_errors` end the rollout immediately.
Methods: `add_tool(tool)`, `remove_tool(tool)`, override `call_tool(name, args, id)` to customize
execution.

`MCPEnv` extends `ToolEnv`: point it at MCP servers and it auto-connects and exposes their tools —
```python
vf.MCPEnv(mcp_servers=[{"name": "fetch", "command": "uvx", "args": ["mcp-server-fetch"]}],
          dataset=dataset, rubric=rubric)
```

### 2.6 `StatefulToolEnv` / `SandboxEnv` / `PythonEnv`

`ToolEnv`/`MCPEnv` assume stateless, read-only tools. For a tool that needs per-rollout state (a
sandbox handle, DB connection, session id), subclass `StatefulToolEnv` and:

1. Register the tool with `args_to_skip` — those params are hidden from the model's tool schema.
2. Override `update_tool_args(tool_name, tool_args, messages, state, **kwargs)` to inject the
   skipped values back in before the call.
3. Override `setup_state(state)` to create the per-rollout resource (must call `super().setup_state`).

```python
class MySandboxEnv(vf.StatefulToolEnv):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_tool(self.run_code, args_to_skip=["session_id"])

    async def setup_state(self, state, **kwargs):
        state["session_id"] = await create_session()
        await super().setup_state(state, **kwargs)

    def update_tool_args(self, tool_name, tool_args, messages, state, **kwargs):
        if tool_name == "run_code":
            tool_args["session_id"] = state["session_id"]
        return tool_args

    async def run_code(self, code: str, session_id: str) -> str:
        """Execute code in the sandbox."""
        return await execute_in_session(session_id, code)
```

Built-in stateful envs, both backed by Prime Sandboxes and both handling sandbox lifecycle
automatically:

```python
class SandboxEnv(StatefulToolEnv):
    def __init__(
        self,
        sandbox_name: str = "sandbox-env",
        docker_image: str = "python:3.11-slim",
        start_command: str = "tail -f /dev/null",
        cpu_cores: int = 1, memory_gb: int = 2, disk_size_gb: int = 5, gpu_count: int = 0,
        timeout_minutes: int = 60, timeout_per_command_seconds: int = 30,
        environment_vars: dict[str, str] | None = None,
        team_id: str | None = None,
        advanced_configs: AdvancedConfigs | None = None,
        labels: list[str] | None = None,
        **kwargs,
    ): ...
```

`PythonEnv` extends `SandboxEnv` with a persistent Python REPL.

### 2.7 `EnvGroup`

```python
env_group = vf.EnvGroup(envs=[math_env, code_env, reasoning_env],
                         env_names=["math", "code", "reasoning"])
```

Concatenates all sub-environment datasets, routes via an internal `info["env_id"]` key (not a
top-level input/state/output field), aggregates metrics across sub-environments. Each
sub-environment keeps its own dataset, rubric, rollout logic.

---

## 3. v0 — Dataset, Parser, Rubric (exact declaration mechanics)

### 3.1 Dataset

Just a HuggingFace `datasets.Dataset`. Expected columns:

- `prompt` — `list[ChatMessage]` (chat mode) — the full initial message list, **or**
- `question` — plain `str`, auto-wrapped into a single user message if `prompt` is absent,
- `answer` — `str`, ground truth for simple comparisons (optional),
- `info` — `dict` or JSON string, arbitrary structured metadata (optional; prefer JSON strings if
  rows have heterogeneous schemas — the environment parses them into `dict` at rollout time).

```python
from datasets import Dataset

dataset = Dataset.from_list([
    {"prompt": [{"role": "user", "content": "What is 2+2?"}], "answer": "4"},
    {"question": "What is 3*5?", "answer": "15"},  # question form also legal
])
```

`system_prompt: str` on the environment constructor prepends a system message (unless the row's
`prompt` already starts with one). `eval_dataset` is a separate optional `Dataset`/`DatasetBuilder`
used by `evaluate()`/`prime eval run`; falls back to `dataset` if omitted.

**Lazy loading:** pass a `DatasetBuilder` (a zero-arg callable returning a `Dataset`) instead of a
materialized `Dataset` to `dataset=`/`eval_dataset=` to defer expensive loads (e.g. an HF download)
until first access — useful for large datasets or when spinning up multiple environment replicas.
A raw `Dataset` passed directly is still loaded eagerly (kept for backwards compatibility).

```python
def get_dataset_builder(split: str = "train", seed: int = 42) -> vf.DatasetBuilder:
    def build() -> Dataset:
        return load_dataset("my-dataset", split=split).shuffle(seed=seed)
    return build
```

### 3.2 Parser

```python
class Parser:
    def __init__(self, extract_fn: Callable[[str], str] = lambda x: x): ...
    def parse(self, text: str) -> Any: ...                    # default: identity
    def parse_answer(self, completion: Messages) -> str | None: ...  # default: last message content
    def get_format_reward_func(self) -> Callable: ...
```

Built-ins: `XMLParser(fields=[...], answer_field="answer", extract_fn=...)` (extracts XML-tagged
fields, e.g. `fields=["reasoning", "answer"]` or `fields=["reasoning", ("code", "answer")]` for
either/or fields — has `.parse()`, `.parse_answer()`, `.get_format_str()`, `.get_fields()`,
`.format(**kwargs)`); `ThinkParser` (content after `</think>`); `MaybeThinkParser` (`<think>` is
optional). A `Rubric`'s `parser` (if set) is auto-injected into reward functions as the `parser`
kwarg, and stored as `rubric.class_objects["parser"]`.

### 3.3 Rubric / reward functions

```python
class Rubric:
    def __init__(
        self,
        funcs: list[RewardFunc] | None = None,
        weights: list[float] | None = None,   # default 1.0 each; must match len(funcs) if given
        parser: Parser | None = None,
    ): ...
    def add_reward_func(self, func: RewardFunc, weight: float = 1.0) -> None: ...
    def add_metric(self, func: RewardFunc, weight: float = 0.0) -> None: ...   # weight=0 shorthand
    def add_class_object(self, name: str, obj: Any) -> None: ...              # inject a shared helper
```

**Individual reward function signature** — arguments are matched *by name* (the rubric introspects
the function signature and calls it with only the kwargs it declares):

```python
async def my_reward(
    completion: Messages,          # model output (list of chat messages, or str in completion mode)
    answer: str = "",              # from dataset row
    prompt: Messages | None = None,
    state: State | None = None,    # full mutable rollout state — write here to share across funcs
    parser: Parser | None = None,  # present only if the Rubric has a parser
    info: Info | None = None,      # from dataset row
    **kwargs,
) -> float: ...
```

Sync or async both work; the type alias is
`IndividualRewardFunc = Callable[..., float | Awaitable[float]]`.

**Group reward function** — use plural parameter names (`completions`, `prompts`, `answers`,
`states`, `infos`) and return `list[float]`, one score per rollout in the group. Detected
automatically by inspecting the signature for plural/group-indicator param names or a `list`
return annotation:

```python
async def diversity_bonus(completions) -> list[float]:
    responses = [c[-1]["content"] for c in completions]
    return [0.2 if responses.count(r) == 1 else 0.0 for r in responses]
```

Groups = "all rollouts sampled for the same dataset example" (size = `rollouts_per_example`); used
for pass@k stats during eval and for advantage computation during RL.

Final reward = weighted sum over all functions. Functions added with `weight=0.0`
(`add_metric`) don't affect reward but still show up in per-rollout metrics — this is the
mechanism for "log this value without scoring on it."

**Execution order matters and state is shared** — functions run in registration order and can
stash intermediate values in `state` for later functions to reuse (avoids recomputing something
expensive like a similarity score and then a thresholded version of it).

Composition: `RubricGroup([rubric_a, rubric_b])` runs member rubrics in parallel and sums
rewards/collects metrics from all of them — used for combining heterogeneous rubrics (e.g.
`MathRubric()` + a custom `JudgeRubric`). Environments auto-wrap into a `RubricGroup` as needed so
subclass hierarchies (e.g. `PythonEnv` inheriting `SandboxEnv` + `ToolEnv` monitor metrics) stack.

Built-ins: `MathRubric()` (symbolic equivalence via `math-verify`, parses `\boxed{}`),
`JudgeRubric(judge_model=..., judge_prompt=...)` (LLM-as-judge; exposes a `judge(prompt, completion,
answer)` callable to reward funcs, plus `judge_client`/`judge_model`/`judge_prompt`/
`judge_sampling_args` as class objects).

Built-in per-environment-type metrics (auto-tracked via "monitor rubrics", `add_rubric`-merged):

| Environment | Metrics |
|---|---|
| `MultiTurnEnv` | `num_turns` |
| `ToolEnv` | `total_tool_calls`, per-tool-name counts |
| `SandboxEnv` | `sandbox_ready_wait_time`, `sandbox_command_execution_time` |
| `PythonEnv` | `python_ready_wait_time` |

---

## 4. Minimal working v0 custom environment (complete, runnable shape)

This is the smallest legal Hub-style package — matches what `prime env init my-env` scaffolds, then
filled in. Single-file layout:

```text
environments/my_env/
├── my_env.py
├── pyproject.toml
└── README.md
```

`my_env.py`:

```python
import verifiers as vf
from datasets import Dataset


def load_environment(difficulty: str = "easy") -> vf.Environment:
    """Entry point every verifiers tool calls: `prime eval run`, `vf.load_environment(...)`,
    prime-rl (via the v1 path), Hosted Training. Must be named exactly `load_environment` and
    return a `vf.Environment`. kwargs come from --env-args / TOML [env.env_args]."""

    dataset = Dataset.from_list([
        {"prompt": [{"role": "user", "content": "What is 2+2?"}], "answer": "4"},
        {"prompt": [{"role": "user", "content": "What is 3*5?"}], "answer": "15"},
    ])

    async def correct_answer(completion, answer) -> float:
        response = completion[-1]["content"]
        return 1.0 if answer in response else 0.0

    async def concise(completion) -> float:
        """Metric only (weight 0 below) — doesn't affect reward, just observability."""
        return float(len(completion[-1]["content"]))

    rubric = vf.Rubric(funcs=[correct_answer, concise], weights=[1.0, 0.0])

    return vf.SingleTurnEnv(
        dataset=dataset,
        system_prompt="You are a helpful, concise math tutor.",
        rubric=rubric,
    )
```

`pyproject.toml`:

```toml
[project]
name = "my-env"
description = "Minimal single-turn arithmetic QA environment"
tags = ["single-turn", "math", "train", "eval"]
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["verifiers>=0.3.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build]
include = ["my_env.py", "pyproject.toml"]

[tool.verifiers.eval]
num_examples = 20
rollouts_per_example = 5
```

Run it:

```bash
prime eval run my-env -m openai/gpt-4.1-mini -n 10
# equivalently, in Python:
import verifiers as vf
env = vf.load_environment("my-env")            # local install, or "owner/my-env" from the Hub
results = env.evaluate_sync(client=..., model="gpt-4.1-mini", num_examples=10, rollouts_per_example=3)
```

`prime eval run` resolves/installs the package, imports the module, calls `load_environment()`,
runs (default) 5 examples × 3 rollouts, scores with the rubric, prints aggregate metrics.
`vf-eval` (legacy standalone script, still shipped: `vf-eval = "verifiers.legacy.scripts.eval:main"`)
does the same thing without the Prime CLI wrapper, defaulting to `gpt-4.1-mini`, 5 prompts, 3
rollouts each.

---

## 5. v1 (native) — Taskset / Task / Harness / Agent / Env / Trace

This is what "new environments should target" per the in-repo docs, and what `prime-rl`'s
orchestrator actually drives (§6). Conceptually it separates **data** (Taskset/Task/TaskData) from
**execution** (Harness/Agent/Runtime) from **the record of what happened** (Trace/Episode), whereas
v0 fused rollout-loop-plus-scoring into one `Environment` subclass.

### 5.1 Core vocabulary (from `docs/v1/overview.md` and `docs/v1/architecture.md`)

- **Taskset** — the loader for the work to run. `Taskset[TaskT, ConfigT]`; `load()` returns/yields
  the task objects.
- **Task** — one row's *behavior*: lifecycle hooks (`setup`, `finalize`, `validate`), stop
  conditions, tools, metrics, `@vf.reward`-decorated scoring methods.
- **TaskData** — one row's immutable, serializable *data*: prompt, files, references, resource
  requirements. Only `TaskData` is stored on the trace — never live clients/handles.
- **Harness** — the program the model runs in (Claude Code, Codex, mini-swe-agent, or a
  purpose-built one). Model traffic never goes directly to the provider — it's routed through a
  local **interception server** so traces can be built live regardless of harness.
- **Agent** — harness × model × runtime policy → produces a `Trace`. `vf.make_agent(vf.AgentConfig(...))`.
- **Env** — defines control flow across multiple agents (only needed for multi-agent episodes —
  judge-and-solver, best-of-n, simulated users). `Env.run(task, agents) -> None`; every finished
  agent run auto-joins the resulting `Episode`.
- **Trace** — the message graph + rewards + metrics + errors + one `ModelCall` per provider
  exchange. For training with prime-rl it also carries tokens/logprobs, built incrementally via the
  `renderers` package.
- **Runtime** — where a rollout's code actually executes: `subprocess` (local, debugging only —
  side effects can leak between concurrent rollouts), `docker` (local containers), or sandbox
  runtimes (`prime`, `modal`) for production/training scale.
- **Toolset** — a set of task/taskset-owned tools, installed into supporting harnesses as MCP
  servers (`SUPPORTS_MCP`).

### 5.2 Minimal v1 taskset (single-turn, from the `create-environments` skill)

```python
import verifiers.v1 as vf


class AdditionData(vf.TaskData):
    answer: int                       # immutable per-row reference data


class AdditionTask(vf.Task[AdditionData]):
    @vf.reward
    async def exact_match(self, trace: vf.Trace) -> float:
        return float(trace.last_reply == str(self.data.answer))


class AdditionTaskset(vf.Taskset[AdditionTask, vf.TasksetConfig]):
    def load(self) -> list[AdditionTask]:
        return [
            AdditionTask(AdditionData(idx=i, prompt=f"What is {i} + {i}?", answer=2 * i),
                         self.config.task)
            for i in range(100)
        ]


__all__ = ["AdditionTaskset"]     # v1 loader discovers the taskset off __all__ + generic bases
```

Rules that differ sharply from v0:

- **No `load_environment()` function.** The v1 loader resolves the `Taskset` subclass (and its
  generic `TaskT`/`ConfigT` type params) straight from the module's `__all__`.
- **Don't override `Taskset.__init__`** — implement `load()`. Don't override `Harness.__init__` —
  use `setup()`.
- Config is layered: `TasksetConfig` (dataset-load-time knobs: split/seed/size) vs. `TaskConfig`
  nested under it as `.task` (per-task knobs applied to every task, e.g. a judge model) —
  overridable via CLI as `--env.taskset.num-tasks` / `--env.taskset.task.tolerance`, or TOML
  `[env.taskset]`.
- `load()` may be a generator; set `INFINITE = True` for a taskset that never terminates (then a
  consuming run *must* pass a bound, e.g. `-n`, and shuffling is disallowed — bound first via
  `taskset.head(n).shuffle()`).
- Scaffold with `uv run init <name>` (inside the verifiers repo's own dev environment) — flags
  `-T`/`--add-tool` (adds a `vf.Toolset` server at `servers/tool.py`) and `-H`/`--add-harness`
  (adds a custom `vf.Harness`). Generated layout:
  ```text
  environments/addition_v1/addition_v1/
  ├── __init__.py   # from addition_v1.taskset import AdditionTaskset; __all__ = ["AdditionTaskset"]
  └── taskset.py
  ```

### 5.3 v0 → v1 concept map (from the `create-environments` skill doc)

| v0 | v1 |
|---|---|
| Dataset row | Typed `vf.TaskData` subclass |
| `load_environment(**kwargs)` | Exported `vf.Taskset` class + typed config |
| `Rubric` reward function | `Task.@vf.reward` method |
| `Parser` object | Ordinary parsing inside task scoring |
| `ToolEnv` tools | `vf.Toolset` constructed in `Task.toolsets`/`Taskset.toolsets` |
| `MultiTurnEnv.env_response` | An interaction loop inside the env's `run()` |
| Dict `state` | Typed `vf.State` |
| Sandbox subclass | Runtime config + task hooks |

### 5.4 Real bundled example: GSM8K in v1 (`environments/gsm8k/gsm8k/taskset.py`)

Shows the pattern for "verify with an isolated-dependency script run inside the rollout's own
runtime" (keeps `math-verify` off the eval process, works identically across subprocess/docker/prime
runtimes):

```python
import verifiers.v1 as vf

class GSM8KData(vf.TaskData):
    answer: str

class GSM8KTask(vf.Task[GSM8KData]):
    async def setup(self, runtime: vf.Runtime) -> None:
        await runtime.prepare_uv_script(VERIFY)     # provision verifier's uv env early (needs net)

    @vf.reward(weight=1.0)
    async def correct(self, trace: vf.Trace, runtime: vf.Runtime) -> float:
        prediction = trace.last_reply
        result = await runtime.run_uv_script(VERIFY, args=[self.data.answer, prediction or ""])
        ...
        return float(lines[-1]) if lines else 0.0

    async def validate(self, runtime: vf.Runtime) -> bool:
        """Model-free check that the verifier accepts the gold answer — catches unparseable rows."""
        ...

class GSM8KConfig(vf.TasksetConfig):
    split: Literal["train", "test"] = "test"

class GSM8KTaskset(vf.Taskset[GSM8KTask, GSM8KConfig]):
    def load(self) -> list[GSM8KTask]:
        rows = load_dataset("openai/gsm8k", "main", split=self.config.split)
        return [GSM8KTask(GSM8KData(idx=i, prompt=..., answer=...), self.config.task)
                for i, row in enumerate(rows)]
```

### 5.5 Multi-agent `Env` (only needed beyond single-agent)

```python
class Env(ABC):
    @abstractmethod
    async def run(self, task: Task, agents: Agents) -> None: ...
```

Bundled `Env`s: `AgenticJudgeEnv` (solver → judge; `SharedAgenticJudgeEnv` reuses the solver's
runtime for the judge, `IsolatedAgenticJudgeEnv` gives the judge its own), `UserSimEnv` (turn-by-turn
user↔assistant conversation, user modeled as another agent), `BestOfNEnv` (n independent attempts,
marks best + pass@n).

---

## 6. How `prime-rl` consumes verifiers environments

`prime-rl` (`github.com/PrimeIntellect-ai/prime-rl`) is Prime Intellect's async RL trainer
(multi-node, MoE, LoRA, SFT/distillation). As of this repo snapshot, **its orchestrator is built
exclusively against `verifiers.v1`** — no v0/`load_environment` usage was found anywhere in
`prime-rl`'s source. The integration is a client/server split, not an in-process function call:

- **Env servers.** Each configured environment runs as its own server process
  (`verifiers.v1.serve` — `EnvClient`/`EnvServer`). The orchestrator (`src/prime_rl/orchestrator/
  envs.py`) is a thin client (`Env` class) onto that server: it imports `verifiers.v1 as vf`, does
  `vf.load_taskset(config.env.taskset)` **once, client-side**, and iterates/materializes the task
  list itself. Every dispatched rollout ships that task's `TaskData` over the wire in the request;
  the server pydantic-validates it against the taskset's declared type and executes it. Servers and
  their worker pools stay stateless about data — no per-worker dataset loads, no idx-addressed task
  cache.
- **One episode per run request.** `Env.run(client, model_name, cache_salt, task_data)` calls
  `self.env_client.run(task_data=..., client=..., model=..., sampling=...)` and gets back an
  `Episode`; each of the episode's wire traces is validated into `Rollout[WireTaskData]`
  (`WireTaskData` uses `extra="allow"` so the orchestrator never needs the env's own typed
  `TaskData` class — it only reads `task.idx` / `task.model_dump()`). A zero-trace episode raises
  (dispatcher synthesizes an error marker); a non-`ok` episode marks its otherwise-clean traces
  failed too, so partial episodes never enter training.
- **Config shape.** TOML config sections are `[[orchestrator.train.source]]` / `[[orchestrator.eval.source]]`,
  each with an `env` block: `env.taskset.id = "<taskset-name>"` (+ nested `env.taskset.task.*` for
  per-task config, e.g. judge specs), `env.agent.harness.id = "<harness>"` (+ harness-specific
  fields like `skills`, `forward_env`), `env.agent.runtime` (`type = "prime"|"modal"|"docker"`,
  resource/labels/idle-timeout knobs). Real example (`examples/advanced/glm-4.5-air/search.toml`
  in the prime-rl repo):
  ```toml
  [[orchestrator.train.source]]
  name = "openseeker"

  [orchestrator.train.source.env.agent.harness]
  id = "rlm"
  skills = ["search"]
  forward_env = ["SERPER_API_KEY"]

  [orchestrator.train.source.env.agent.runtime]
  type = "prime"
  vm = true
  labels = ["glm45air-search"]

  [orchestrator.train.source.env.taskset]
  id = "openseeker"

  [[orchestrator.train.source.env.taskset.task.judges]]
  id = "reference"
  name = "correct"
  model = "Qwen/Qwen3-235B-A22B-Instruct-2507"
  ```
- **Sampling / inference client types.** Verifiers exposes multiple `ClientType`s
  (`openai_chat_completions`, `openai_chat_completions_token`, `renderer`, `anthropic_messages`,
  ...). For production RL, `openai_chat_completions_token` (server-side templating + returned
  token IDs, so the trainer never re-tokenizes) is the recommended/battle-tested path; the newer
  `renderer` client type does client-side tokenization for exact multi-turn token-boundary
  preservation but has renderer coverage for only a subset of models.
- **Hosted Training** (Prime's managed platform, "Private Beta" as of this doc) runs `prime-rl`
  for you against any verifiers environment via `prime lab setup` + TOML configs under
  `configs/rl/`; supports LoRA. `prime lab setup --prime-rl` clones/installs `prime-rl` directly for
  self-managed GPU training.
- **Third-party trainer integrations** (each wraps verifiers environments, not prime-rl):
  Tinker via `tinker-cookbook`'s `verifiers_rl` recipe; SkyRL via `skyrl-train`'s verifiers
  integration; rLLM (backends: verl locally, Tinker remotely).
- Note: the earlier (pre-rewrite) "included `GRPOTrainer`" that some older summaries/cached docs
  mention does **not** exist in the current `verifiers` source — no `GRPOTrainer` class is present
  in the repo snapshot used here. Training now happens via `prime-rl`, Hosted Training, or a
  third-party trainer; `verifiers` itself is described as "trainer-agnostic" and only needs the
  trainer to expose an OpenAI-compatible inference client for rollouts.

---

## 7. Packaging & publishing to the Environments Hub

### 7.1 CLI surface

All of this is via the **Prime CLI** (`uv tool install prime`), which loads `verifiers` as a plugin
(`PrimeCLIPlugin`, `PRIME_PLUGIN_API_VERSION = 1`, module paths `verifiers.cli.commands.{eval,gepa,
install,init,setup,build}`) — i.e. `prime env ...` / `prime eval ...` / `prime gepa ...` subcommands
are implemented inside the `verifiers` package and just invoked as `python -m <module>` by `prime`.

| Command | Effect |
|---|---|
| `prime login` | Auth |
| `prime lab setup [--skip-install] [--prime-rl]` | Scaffold workspace (`configs/`, `.prime/skills/`, `environments/AGENTS.md`, top-level `AGENTS.md`/`CLAUDE.md`); optionally clone+install `prime-rl` |
| `prime env init <name> [--path DIR] [--multi-file] [--rewrite-readme]` | Scaffold a **v0** stub at `<path>/<name_with_underscores>/` (single-file by default: `<env>.py` + `pyproject.toml` + `README.md`; `--multi-file` also emits `__init__.py`) |
| `uv run init <name> [-T\|--add-tool] [-H\|--add-harness] [-p\|--path DIR]` | Scaffold a **v1** taskset package (inside a repo with the verifiers v1 CLI installed) |
| `prime env install <name-or-owner/name>[@version] [-p PATH]` | `uv pip install -e` for a local env, or install from the Hub |
| `prime env pull <owner>/<name>` | Download an installed/Hub env's source for inspection/editing |
| `prime env info <owner>/<name>` | Show install methods (pip/uv/wheel URL) |
| `prime env push <name> [--visibility PUBLIC\|PRIVATE]` | Build + publish/update the package on the Environments Hub. Defaults to `./environments/<name>`; equivalent to `--path ./environments/<name>` |
| `prime eval run <env-id-or-toml> [-m MODEL] [-n N] [-r ROLLOUTS] [-a JSON] [-x JSON] [--timeout SECS] [--hosted [--follow]]` | Run an eval (locally by default; `--hosted` runs on Prime-managed infra against an already-pushed Hub env) |
| `prime eval view` | TUI browser (`environment → model → run` panes) over saved local eval results |
| `prime gepa run <env> [-m MODEL] [-M REFLECTION_MODEL] [-B MAX_CALLS] [...]` | GEPA prompt optimization (system-prompt-only) — writes `system_prompt.txt`, `results.jsonl`, `pareto_frontier.jsonl`, `metadata.json` |

Legacy standalone scripts (bypass the Prime CLI entirely, work with just `uv add verifiers`):
`vf-eval`, `vf-gepa`, `vf-init`, `vf-install`, `vf-setup`, `vf-build`, `vf-tui` — all thin wrappers
declared in `[project.scripts]` pointing at `verifiers.legacy.scripts.*`. `vf-init <name>` is the
same v0 scaffold as `prime env init <name>`.

### 7.2 Module layout / naming conventions

- **Hub identifier format:** `owner/environment-name`, e.g. `will/wordle`,
  `primeintellect/math-python`, `primeintellect/reverse-text`, `primeintellect/gsm8k`. Version
  pinning: `owner/name@X.Y.Z` (e.g. `will/wordle@0.1.3`).
- **Local directory naming:** hyphenated env id on the CLI (`my-env`) maps to an
  underscore-named directory and Python module (`environments/my_env/my_env.py`) — "Environment IDs
  are converted to Python module names (`my-env` → `my_env`) and imported after `prime eval run`
  resolves the package."
- **Single-file package** (default, v0):
  ```text
  environments/my_env/
  ├── my_env.py           # must define load_environment(**kwargs) -> vf.Environment
  ├── pyproject.toml
  └── README.md
  ```
- **Multi-file package** (`--multi-file`, v0):
  ```text
  environments/my_env/
  ├── my_env/
  │   ├── __init__.py     # from .my_env import load_environment; __all__ = ["load_environment"]
  │   └── my_env.py
  ├── pyproject.toml
  └── README.md
  ```
- **v1 taskset package**:
  ```text
  environments/addition_v1/
  └── addition_v1/
      ├── __init__.py     # from addition_v1.taskset import AdditionTaskset; __all__ = ["AdditionTaskset"]
      └── taskset.py
  ```
  (plus `servers/tool.py` and/or `harness.py` if scaffolded with `-T`/`-H`).
- **`pyproject.toml` contract** (both stacks): Hatchling build backend is required ("Hatchling is
  used as the build backend for the Environments Hub" — the Hub build pipeline assumes it).
  `[project.name]` is the Hub package name; `[project.tags]` (custom, non-standard field — verifiers'
  own tooling reads it) is free-form categorization (`["single-turn", "math", "train", "eval"]`
  etc.); `dependencies` **must** list `verifiers` with a floor version plus anything else the module
  imports — these install automatically on `prime env install`; `[tool.hatch.build].include` must
  list the environment source file(s) *and* `pyproject.toml` itself (metadata needs to be present
  post-install); `[tool.verifiers.eval]` sets defaults (`num_examples`, `rollouts_per_example`) for
  `prime eval run` when flags are omitted.
- **Required secrets pattern:** call `vf.ensure_keys([...])` early in `load_environment()` — raises
  `MissingKeyError` (a `ValueError` subclass) listing exactly which env vars are missing, with
  instructions covering all three run contexts (Hub secrets tab, Hosted Training `env_file`, local
  shell export). Document required vars in the README under "Required Environment Variables".
- **Publish workflow:**
  ```bash
  prime env push my-env                       # build + publish/update, ./environments/my_env
  prime eval run my-env --hosted --follow     # run on Prime-managed infra against the pushed env
  prime eval run primeintellect/math-python   # run someone else's published env directly
  ```
  The `create-environments` skill is explicit that visibility (`PUBLIC`/`PRIVATE`) is a **user
  decision, not a default** — "Publishing is an external state change and requires the user's
  requested visibility. Do not publish merely because local verification passed."
- **Custom container images** (v1, when a task needs one beyond what Harbor/the taskset provides):
  `prime images push` (cloud build, no local Docker needed), naming convention
  `<env>.x86.<task>:latest`.

### 7.3 Installing published environments in code

```python
from verifiers import load_environment
env = load_environment("will/wordle")          # or "owner/name@X.Y.Z" for a pin
results = env.evaluate(examples=100, rollouts_per_example=1)
```
Non-CLI install paths also work (discoverable per-env via `prime env info owner/name`):
```bash
pip install https://hub.primeintellect.ai/will/wordle/@latest/wordle-0.1.4-py2.py3-none-any.whl
uv add wordle@<same-wheel-url>
```

---

## 8. Report field — wrapping an existing episode-runner as a v0 SingleTurnEnv

The fastest correct path for "I already have a function that runs one episode end-to-end
(prompt in, some scoring out) and I want it inside verifiers" is v0 `SingleTurnEnv` + `Rubric`, not
the v1 taskset stack (which requires per-row `TaskData`/`Task` classes and — for anything beyond a
pure string-diff score — a `Runtime`). Minimal essentials:

1. **Build a `datasets.Dataset`** with one row per episode: a `prompt` column
   (`list[{"role": "user", "content": ...}]`, optionally prefixed by a system message) or a plain
   `question` string column, plus whatever your scorer needs on `answer` (str) and/or `info`
   (dict/JSON — use JSON strings if rows have heterogeneous shapes). If your runner currently takes
   a *problem object*, put its serialized form in `info` and its ground-truth in `answer`.
2. **Wrap your existing scoring logic as an async (or sync) reward function** matched by parameter
   name — you only need to declare the subset of these you actually use:
   ```python
   async def my_reward(completion, answer="", prompt=None, state=None, info=None, **kw) -> float:
       response_text = completion[-1]["content"]     # the model's single turn of output
       return your_existing_scorer(response_text, answer)   # or use `info` for a richer object
   ```
   `completion` is always `list[ChatMessage]` in chat mode (or `str` in `message_type="completion"`
   mode) — there is exactly one assistant turn to read since `max_turns=1`. If your runner needs
   to log auxiliary values, add a second, `weight=0.0` function via `rubric.add_metric(...)`.
3. **Construct:**
   ```python
   rubric = vf.Rubric(funcs=[my_reward], weights=[1.0])
   env = vf.SingleTurnEnv(dataset=dataset, eval_dataset=eval_dataset, rubric=rubric,
                           system_prompt="...")   # system_prompt optional
   ```
4. **Export it** as `load_environment(**kwargs) -> vf.Environment` from a module named after the
   Hub-style env id (underscored), package it per §7.2, and it's runnable via `prime eval run`,
   `vf.load_environment(...)`, or (if you push it) the Hub / prime-rl.
5. **No rollout-loop code to write at all** — `SingleTurnEnv` supplies the one-model-call loop;
   your only job is dataset shape + reward-function signature. If your existing runner does more
   than "one model call, one score" (multiple turns, tool calls, external state), it doesn't fit
   `SingleTurnEnv` — go to `MultiTurnEnv` (override `env_response`) or `ToolEnv` instead (§2.3–2.6).
6. **Gotchas specific to adapting an existing runner:** (a) reward functions must be pure w.r.t.
   concurrency — many rollouts run on one asyncio event loop, so any blocking call in the reward
   function (sync HTTP, `time.sleep`, sync file IO) stalls *every other in-flight rollout*, not just
   this one — wrap it in `asyncio.to_thread(...)` at minimum, ideally rewrite the runner's blocking
   parts as async; (b) if your runner's scoring already returns a rich object rather than a scalar,
   collapse it to `float` for the weighted reward but keep the rest via `add_metric` calls or by
   stashing it in `state[...]` (visible to other reward funcs, and surfaced in
   `RolloutOutput`/saved-results state columns) — don't lose the diagnostic info.

---

## 9. Sources

- `github.com/PrimeIntellect-ai/verifiers` — cloned `main` @ `c2820d3` (2026-08-11). Files quoted
  directly: `pyproject.toml`, `README.md`, `verifiers/__init__.py`, `AGENTS.md`,
  `verifiers/legacy/envs/{environment,multiturn_env,singleturn_env,tool_env,stateful_tool_env}.py`,
  `verifiers/legacy/{parsers/parser.py,rubrics/rubric.py,scripts/init.py}`,
  `docs/{overview.md,legacy/{overview,environments,evaluation,training,reference}.md,
  v1/{overview,architecture,env,agent,tasksets}.md}`, `skills/create-environments/SKILL.md`,
  `environments/gsm8k/gsm8k/{taskset.py,verify.py,__init__.py}`.
- `github.com/PrimeIntellect-ai/prime-rl` — cloned `main` (2026-08-11). Files quoted directly:
  `src/prime_rl/orchestrator/envs.py`, `packages/prime-rl-configs/src/prime_rl/configs/
  orchestrator.py`, `examples/advanced/glm-4.5-air/search.toml`.
- `pypi.org/project/verifiers/` — version/release-date listing (fetched 2026-08-11).
- `docs.primeintellect.ai/tutorials-environments/install` — Hub install/naming conventions (fetched
  2026-08-11; the corresponding `/verifiers/environments` doc page 404s in the hosted site as of
  this date — the in-repo `docs/legacy/environments.md` is the same content and was used instead).
- `verifiers.readthedocs.io` now redirects to `docs.primeintellect.ai/verifiers` (confirmed live —
  no independent content left there).
