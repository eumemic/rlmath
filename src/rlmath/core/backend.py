"""LeanBackend protocol — the single seam between Python and the Lean toolchain.

Implementations:
  - rlmath.lean.repl_pool.ReplPool   (local REPL worker pool; the macOS-native path)
  - rlmath.lean.kimina.KiminaClient  (HTTP; the Linux/GPU-box path)

All harness/bank/bench code depends only on this protocol so backends stay
swappable — the same discipline as ../rl's arm×backend grid, where one runner
served two model backends because the seam was narrow.
"""
from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from .types import VerifyResult


@runtime_checkable
class LeanBackend(Protocol):
    def check(self, code: str, *, timeout_s: float = 120.0) -> VerifyResult:
        """Compile one self-contained snippet (preamble handled by the backend)."""
        ...

    def check_many(self, codes: Sequence[str], *, timeout_s: float = 120.0) -> list[VerifyResult]:
        """Batch form; order-preserving. May parallelize across workers."""
        ...

    def close(self) -> None: ...
