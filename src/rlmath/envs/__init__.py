"""`verifiers`-format packaging of the harness — the Environments Hub artifact
(DIRECTION.md §5.3, Phase-0 gate in §5.5). See `envs_README.md`.

Import-safe without the optional `envhub` extra: `HAS_VERIFIERS` says whether it
is present, and only the environment builders require it. The v1 taskset classes
are re-exported when they exist because the v1 loader discovers a taskset from
the package's `__all__` (research/verifiers.md §5.2).
"""
from .decomp_env import (
    ENV_ID,
    HAS_VERIFIERS,
    HAS_VERIFIERS_V0,
    HAS_VERIFIERS_V1,
    SYSTEM_PROMPT,
    EpisodeResources,
    EpisodeScore,
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
    single_prompt,
    user_message,
)

__all__ = [
    "ENV_ID",
    "HAS_VERIFIERS",
    "HAS_VERIFIERS_V0",
    "HAS_VERIFIERS_V1",
    "SYSTEM_PROMPT",
    "EpisodeResources",
    "EpisodeScore",
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
    "single_prompt",
    "user_message",
]

if HAS_VERIFIERS_V1:  # pragma: no cover - needs the envhub extra
    from .decomp_env import (
        DecompositionConfig,
        DecompositionData,
        DecompositionTask,
        DecompositionTaskset,
    )

    __all__ += ["DecompositionConfig", "DecompositionData", "DecompositionTask",
                "DecompositionTaskset"]
