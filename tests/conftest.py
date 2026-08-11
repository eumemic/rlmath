"""Shared test fixtures. FakeBackend is the offline stand-in for a live Lean
toolchain — scripted (predicate → result) rules so unit tests assert exact
harness behavior without Mathlib installed."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest

from rlmath.core.types import LeanMessage, VerifyResult


@dataclass
class FakeBackend:
    """First matching rule wins; unmatched code fails the test loudly (a silent
    default would hide harness codegen drift — the ../rl lesson, applied to tests)."""
    rules: list[tuple[Callable[[str], bool], VerifyResult]] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    def rule(self, pred: Callable[[str], bool], result: VerifyResult) -> None:
        self.rules.append((pred, result))

    def rule_contains(self, needle: str, *, ok: bool = True, sorries: int = 0, errtext: str = "") -> None:
        msgs = [] if ok else [LeanMessage("error", errtext or "fake error")]
        self.rules.append(
            (lambda c, n=needle: n in c, VerifyResult(ok=ok, messages=msgs, sorries=sorries))
        )

    def check(self, code: str, *, timeout_s: float = 120.0) -> VerifyResult:
        self.calls.append(code)
        for pred, res in self.rules:
            if pred(code):
                return res
        raise AssertionError(f"FakeBackend: no rule matched code:\n---\n{code}\n---")

    def check_many(self, codes: Sequence[str], *, timeout_s: float = 120.0) -> list[VerifyResult]:
        return [self.check(c, timeout_s=timeout_s) for c in codes]

    def close(self) -> None:
        pass


@pytest.fixture
def fake_backend() -> FakeBackend:
    return FakeBackend()
