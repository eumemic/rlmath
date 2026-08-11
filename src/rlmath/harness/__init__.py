"""Episode runner: parse -> sanitize -> elaborate -> plan-check -> leaf -> compose -> audit.

`episode.run_episode` is the single entry point every arm scores through
(DIRECTION.md §5.1-5.2); `composer` owns Lean name hygiene, `detectors` the
plan-shape statistics that feed the Phase-2 strategy analysis (§5.7).
"""
from .composer import NameHygieneError, build_artifact, check_names, with_axiom_audit
from .detectors import plan_stats, restatement_similarity
from .episode import LeafProver, run_direct_close, run_episode

__all__ = [
    "LeafProver",
    "NameHygieneError",
    "build_artifact",
    "check_names",
    "plan_stats",
    "restatement_similarity",
    "run_direct_close",
    "run_episode",
    "with_axiom_audit",
]
