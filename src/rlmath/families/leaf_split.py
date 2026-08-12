"""Leaf-level train/eval split — the anti-contamination contract.

Strategist review (2026-08-12): with a finite leaf bank, the transfer plot is
uninterpretable without leaf-level disjointness — if eval-k problems are built
from leaves the policy saw during training at k≤k₀, "decomposition structure
transferred" cannot be distinguished from "the root memorized these statements."
This channel did not exist in the retrieval RLM (content was inexhaustible);
here it must be closed by construction, before any family dataset materializes.

The split is a pure function of the statement_key (sha256-derived hex), NOT a
stored manifest: membership is decided the moment a statement exists, is stable
across bank growth (40 leaves today, thousands after the wide sweep), across
re-sweeps, and across machines. Nobody can leak a leaf by re-rolling a split
file, and mutation-bred variants get their own key and therefore their own
independently-drawn membership.

Rule (FAMILIES.md): TRAIN problems (any k) draw leaves exclusively from the
train pool; EVAL problems exclusively from the eval pool. Datasets record the
pool per problem; the gen CLI refuses mixed draws.
"""
from __future__ import annotations

# Last hex nibble of the statement_key: 4/16 values -> 25% eval hold-out.
# With today's ~40-leaf band sample that is ~30/10 — thin, as the strategist
# noted; the wide sweep is the real fix, and this split extends to it unchanged.
_EVAL_NIBBLES = frozenset("cdef")


def leaf_split(statement_key: str) -> str:
    """"train" or "eval", deterministically from the key's last hex nibble."""
    if not statement_key:
        raise ValueError("empty statement_key")
    return "eval" if statement_key[-1].lower() in _EVAL_NIBBLES else "train"


def split_pools(keys: list[str]) -> tuple[list[str], list[str]]:
    """(train_keys, eval_keys), order-preserving."""
    train = [k for k in keys if leaf_split(k) == "train"]
    ev = [k for k in keys if leaf_split(k) == "eval"]
    return train, ev
