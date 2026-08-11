"""`verifiers`-format packaging of the harness — the Environments Hub artifact
(DIRECTION.md §5.3, Phase-0 gate in §5.5). See `envs_README.md`.

Import-safe without the optional `envhub` extra: `HAS_VERIFIERS` says whether it
is present, and only the environment builders require it. The v1 taskset classes
are re-exported when they exist because the v1 loader discovers a taskset from
the package's `__all__` — and requires exactly one `Taskset` subclass there
(`verifiers/v1/utils/loaders.py::_plugin_class`).
"""
from .decomp_env import (
    ENV_ID,
    HAS_VERIFIERS,
    HAS_VERIFIERS_V0,
    HAS_VERIFIERS_V1,
    SYSTEM_PROMPT,
    TRACE_INFO_KEY,
    EpisodeResources,
    EpisodeScore,
    attach_diagnostics,
    build_dataset,
    build_prompt,
    build_taskset,
    budgets_from_config,
    completion_text,
    episode_info,
    get_resources,
    goal_rows,
    load_environment,
    load_goals,
    score_plan,
    set_resources,
    user_message,
)

__all__ = [
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
    "load_environment",
    "load_goals",
    "score_plan",
    "set_resources",
    "user_message",
]

if HAS_VERIFIERS_V1:
    from .decomp_env import (
        DecompositionConfig,
        DecompositionData,
        DecompositionTask,
        DecompositionTaskConfig,
        DecompositionTaskset,
    )

    __all__ += ["DecompositionConfig", "DecompositionData", "DecompositionTask",
                "DecompositionTaskConfig", "DecompositionTaskset"]
