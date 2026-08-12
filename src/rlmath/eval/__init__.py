"""Phase-2 evaluation surface (DIRECTION.md §5.5 Phase 2, §6).

The zero-shot study's arms and root-model client. Scoring is NOT here — it is
`rlmath.harness` and `rlmath.envs.decomp_env`, which this package calls (see
`arms.py`'s docstring). `scripts/run_zeroshot.py` is the runner over one
(problem-set, k, arm, root-model) cell.

Importing this package pulls `rlmath.envs.decomp_env`, whose `verifiers` import
is a guarded probe, so it stays importable without the `envhub` extra.
"""
from .arms import (
    ARMS,
    ARMS_NEEDING_LEAF,
    CHARS_PER_TOKEN,
    DIRECT_SYSTEM,
    DIRECT_USER,
    ArmOutcome,
    OpenAIRootClient,
    RootClient,
    RootCompletion,
    Usage,
    direct_prompt,
    estimate_tokens,
    make_root_client,
    model_slug,
    parse_extra_headers,
    run_arm,
    run_decomp,
    run_direct,
    status_for_exception,
    usage_from_response,
)

__all__ = [
    "ARMS",
    "ARMS_NEEDING_LEAF",
    "CHARS_PER_TOKEN",
    "DIRECT_SYSTEM",
    "DIRECT_USER",
    "ArmOutcome",
    "OpenAIRootClient",
    "RootClient",
    "RootCompletion",
    "Usage",
    "direct_prompt",
    "estimate_tokens",
    "make_root_client",
    "model_slug",
    "parse_extra_headers",
    "run_arm",
    "run_decomp",
    "run_direct",
    "status_for_exception",
    "usage_from_response",
]
