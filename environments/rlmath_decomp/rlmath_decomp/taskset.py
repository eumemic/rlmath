"""Hub-package entry module for `rlmath-decomp` — re-export only.

The environment itself lives in `rlmath.envs.decomp_env`, next to the harness it
wraps and the tests that pin it (`tests/test_env.py`). This package exists
because the Hub build pipeline wants one Hatchling package directory per
environment and resolves the id `rlmath-decomp` to the module `rlmath_decomp`;
copying the wrapper in here would give the published artifact a second,
untested, silently-drifting scoring path.

Both surfaces are re-exported:

* `DecompositionTaskset` — v1. The loader imports this package and picks the one
  `vf.Taskset` subclass out of `__all__`
  (`verifiers/v1/utils/loaders.py::_plugin_class`), then constructs it as
  `DecompositionTaskset(config)`. Exactly one taskset may be exported; a second
  makes discovery a hard error.
* `load_environment` — v0. `verifiers.load_environment("rlmath-decomp")` imports
  the module and calls this by name (`verifiers/utils/env_utils.py`).

Both **construct** with no arguments and nothing registered, over the built-in
`DEMO_GOALS` set — importing, discovering and inspecting this package works on a
machine with no Lean toolchain, which is what the Hub's post-push integration
test does.

Both **run** on live Lean/leaf handles, which neither a `TasksetConfig` nor
`--env-args` can carry (they are serializable; a REPL pool is not). Register them
process-globally before the run:

    from rlmath.envs import EpisodeResources, set_resources
    set_resources(EpisodeResources(backend=..., leaf=..., goals=[...]))

A rollout scored without them raises instead of returning 0.0: an absent kernel
reported as a zero reward is indistinguishable from a policy that never proves
anything. See the README's "Loading works anywhere; running needs the resources".
"""

from rlmath.envs.decomp_env import (
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
