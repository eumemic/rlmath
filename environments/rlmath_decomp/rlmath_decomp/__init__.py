"""`rlmath-decomp` — the Environments Hub package. See `taskset.py`.

Layout and re-export shape follow the v1 scaffolder (`uv run init <name>`,
`verifiers/v1/cli/init.py`): a package directory whose `__init__` imports from
`<pkg>.taskset` and names its exports in `__all__`, which is where the v1 loader
looks for the `Taskset` subclass.
"""

from rlmath_decomp.taskset import (
    ENV_ID,
    SYSTEM_PROMPT,
    DecompositionConfig,
    DecompositionData,
    DecompositionTask,
    DecompositionTaskConfig,
    DecompositionTaskset,
    EpisodeResources,
    load_environment,
    set_resources,
)

__all__ = [
    "ENV_ID",
    "SYSTEM_PROMPT",
    "DecompositionConfig",
    "DecompositionData",
    "DecompositionTask",
    "DecompositionTaskConfig",
    "DecompositionTaskset",
    "EpisodeResources",
    "load_environment",
    "set_resources",
]
