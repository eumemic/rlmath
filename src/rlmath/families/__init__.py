"""Size-parameterized problem families (FAMILIES.md).

REGISTRY maps family name -> generate(k, seed, n) -> list[GeneratedProblem].
Family modules call register() at import; scripts/gen_families.py imports the
package and reads REGISTRY — one seam, same shape as data/<benchmark>/ in ../rl.
"""
from __future__ import annotations

from collections.abc import Callable

from .types import GeneratedProblem, LeafWitness
from .validate import AUTOMATION_TACTICS, ValidationReport, validate_problem

Generator = Callable[..., list[GeneratedProblem]]  # generate(k: int, seed: int, n: int) -> problems

REGISTRY: dict[str, Generator] = {}


def register(name: str, gen: Generator) -> None:
    if name in REGISTRY:
        raise ValueError(f"family already registered: {name}")
    REGISTRY[name] = gen


__all__ = [
    "AUTOMATION_TACTICS",
    "GeneratedProblem",
    "Generator",
    "LeafWitness",
    "REGISTRY",
    "ValidationReport",
    "register",
    "validate_problem",
]
