"""Core data contracts for the rlmath decomposition harness.

Every module implements against these types; they are the frozen seam between
concurrently-developed components. See DIRECTION.md §5.

The status taxonomy is deliberately fine-grained (DIRECTION.md §6, "evidence
discipline"): feasibility evidence, policy failure, and infrastructure failure
must never share a bucket, or Phase 3's transfer analysis becomes
uninterpretable after the fact.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum


class Status(StrEnum):
    VERIFIED = "verified"
    # --- policy failures, in pipeline order (each names the first stage that failed)
    FORMAT_ERROR = "format_error"                  # completion did not parse into a plan
    SANITIZER_REJECTED = "sanitizer_rejected"      # banned token / axiom-audit failure
    STATEMENT_ILL_FORMED = "statement_ill_formed"  # a lemma statement failed elaboration
    PLAN_INVALID = "plan_invalid"                  # assembly fails even granting the lemmas
    LEAF_FAILED = "leaf_failed"                    # plan valid, but a lemma resisted the leaf prover
    COMPOSE_FAILED = "compose_failed"              # plan + leaves ok, spliced artifact failed kernel
                                                   #   (should be rare — always investigate)
    BUDGET_EXHAUSTED = "budget_exhausted"
    # --- feasibility evidence, NOT scored as failure (excluded from mean scores; ../rl pattern)
    CONTEXT_WINDOW_EXCEEDED = "context_window_exceeded"
    # --- infrastructure, not evidence
    ERROR = "error"


@dataclass
class LeanMessage:
    severity: str  # "error" | "warning" | "info"
    text: str
    line: int | None = None
    col: int | None = None


@dataclass
class VerifyResult:
    """Result of running one Lean snippet through a backend.

    `ok` means compilation produced no error-severity messages. Whether sorries
    are acceptable is the *caller's* policy, not the backend's: statement
    elaboration expects exactly one sorry; proof checks expect zero.
    """
    ok: bool
    messages: list[LeanMessage] = field(default_factory=list)
    sorries: int = 0
    elapsed_s: float = 0.0
    env_id: int | None = None
    raw: dict | None = None

    @property
    def errors(self) -> list[LeanMessage]:
        return [m for m in self.messages if m.severity == "error"]


@dataclass(frozen=True)
class GoalSpec:
    id: str
    prop: str              # a closed Lean 4 proposition, e.g. "∀ n : ℕ, n + 0 = n"
    name: str = "goal"     # declaration name used in the final artifact


@dataclass(frozen=True)
class LemmaSpec:
    name: str              # binder-safe identifier, e.g. "h1"
    prop: str


@dataclass
class DecompositionPlan:
    lemmas: list[LemmaSpec]
    assembly: str          # tactic block proving the goal; may use lemma names as hypotheses

    @property
    def is_direct(self) -> bool:
        """No lemmas: the assembly must prove the goal outright (the `close` action)."""
        return not self.lemmas


@dataclass
class Budgets:
    """Hard caps, not cost penalties (DIRECTION.md §5.6 — penalties suppress
    decomposition before it can pay off; budgets bound compute without shaping)."""
    max_lemmas: int = 8
    leaf_attempts_per_lemma: int = 4
    max_total_leaf_attempts: int = 64
    verify_timeout_s: float = 120.0


@dataclass
class LemmaOutcome:
    lemma: LemmaSpec
    status: Status
    proof: str | None = None
    attempts_used: int = 0


@dataclass
class EpisodeResult:
    status: Status
    goal: GoalSpec
    plan: DecompositionPlan | None = None
    lemma_outcomes: list[LemmaOutcome] = field(default_factory=list)
    artifact: str | None = None       # final kernel-checked, self-contained Lean source
    detail: str = ""                  # human-readable failure detail (names the offending lemma etc.)
    leaf_attempts_used: int = 0
    elapsed_s: float = 0.0

    @property
    def reward(self) -> float:
        """Terminal reward only in v1 (DIRECTION.md §5.6). r_plan is diagnostic."""
        return 1.0 if self.status is Status.VERIFIED else 0.0


@dataclass
class AttemptRecord:
    """One leaf-prover generation, for the bank and the cache."""
    statement_key: str
    model: str
    index: int
    proof: str
    verified: bool | None = None      # None = generated but not yet kernel-checked


_WS = re.compile(r"\s+")
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/-.*?-/", re.DOTALL)


def normalize_statement(prop: str) -> str:
    """Whitespace/comment normalization for cache keys and restatement detection.

    NOT α-normalization — renamed binders defeat it (accepted for v1; noted as
    future work in DIRECTION.md §5.4 discussion of the restatement detector).
    """
    s = _BLOCK_COMMENT.sub(" ", prop)
    s = _LINE_COMMENT.sub(" ", s)
    return _WS.sub(" ", s).strip()


def statement_key(prop: str) -> str:
    return hashlib.sha256(normalize_statement(prop).encode()).hexdigest()[:16]
