#!/usr/bin/env python
"""Verifier throughput benchmark for the Phase 0 gate (DIRECTION.md §5.5:
≥2–3k verified leaf attempts/hr, else "infra infeasible solo").

Measurement only — this script has no pass/fail assertion, by design. What
counts as clearing the gate depends on the hardware the number was taken on and
on what Phase 3 actually needs; that judgment belongs in PHASE0_NOTES.md next
to the machine description, not in an exit code that later reads as a fact.

Every check goes through `leancode.proof_check`, so the number measures the
path the harness actually uses (parse + elaborate + kernel), not a bare
`import Mathlib` ping.

Usage:
  uv run python scripts/bench_throughput.py --backend repl --workers 8 --n 120
  uv run python scripts/bench_throughput.py --from-bank data/bank/bank.jsonl --n 200
  uv run python scripts/bench_throughput.py --timestamp 2026-08-11T16:00:00Z   # stamped into the JSON

Concurrency is the backend's own: --workers sizes the pool and the batch goes
through `LeanBackend.check_many`, which is where a real backend parallelizes.
Driving it with our own thread pool would measure the wrong thing (and, for the
REPL pool, would race — PHASE0_NOTES / DIRECTION.md §6 single-writer lesson).

`rlmath.lean` is imported lazily inside make_backend so this module's logic is
unit-testable with no toolchain; tests inject a stub by monkeypatching
make_backend, or via `--backend fake` + FAKE_BACKEND_FACTORY.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from rlmath.core.leancode import proof_check

ROOT = Path(__file__).resolve().parent.parent

# One-line Mathlib-provable statements of the norm_num / omega / decide variety:
# cheap enough that the measurement reflects backend overhead (process, session,
# elaboration) rather than search, which is what the gate is about. Written as
# (prop, proof) pairs so the benchmark exercises proof_check, the real path.
TRIVIAL_SUITE: list[tuple[str, str]] = [
    ("(2 : ℕ) + 2 = 4", "by norm_num"),
    ("(123 : ℕ) + 456 = 579", "by norm_num"),
    ("(3 : ℤ) * 7 = 21", "by norm_num"),
    ("(2 : ℕ) ^ 10 = 1024", "by norm_num"),
    ("(2 : ℝ) + 2 = 4", "by norm_num"),
    ("(0 : ℝ) < 1", "by norm_num"),
    ("Nat.Prime 17", "by norm_num"),
    ("Nat.gcd 12 18 = 6", "by norm_num"),
    ("(100 : ℕ) % 7 = 2", "by decide"),
    ("(1 : ℕ) + 1 ≠ 3", "by decide"),
    ("(7 : ℕ) ∣ 42", "by decide"),
    ("(10 : ℕ).choose 2 = 45", "by decide"),
    ("List.length [1, 2, 3] = 3", "by decide"),
    ("∀ n : ℕ, n + 0 = n", "by intro n; omega"),
    ("∀ n : ℕ, n < n + 1", "by intro n; omega"),
    ("∀ n : ℕ, n ≤ 2 * n", "by intro n; omega"),
    ("∀ a b : ℕ, a + b = b + a", "by intro a b; omega"),
    ("∀ n : ℕ, 0 < n → 1 ≤ n", "by intro n h; omega"),
    ("∀ a b c : ℤ, a - b + (b - c) = a - c", "by intro a b c; ring"),
    ("∀ x y : ℝ, (x + y) ^ 2 = x ^ 2 + 2 * x * y + y ^ 2", "by intro x y; ring"),
    ("∀ x : ℝ, x ^ 2 ≥ 0", "by intro x; positivity"),
]

# Test seam (see module docstring).
FAKE_BACKEND_FACTORY: Callable[[], object] | None = None


# ---------------------------------------------------------------------------
# Workload
# ---------------------------------------------------------------------------

def suite_from_bank(path: Path, *, seed: int | None = None) -> list[tuple[str, str]]:
    """(prop, proof) pairs from bank rows that carry a verified proof.

    Bank-sourced timings are the honest ones — real statements are longer and
    their proofs are not one-liners — but only rows with a `first_proof` can be
    replayed, so an elaborate-only bank yields nothing and says so.
    """
    pairs: list[tuple[str, str]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            prop, proof = row.get("prop"), row.get("first_proof")
            if isinstance(prop, str) and prop.strip() and isinstance(proof, str) and proof.strip():
                pairs.append((prop, proof))
    if seed is not None:
        random.Random(seed).shuffle(pairs)
    return pairs


def build_codes(pairs: Sequence[tuple[str, str]], n: int) -> list[str]:
    """n snippets, cycling the pairs if the suite is smaller than n.

    Repeats are deliberate (a fixed suite is the point) but note the bias: a
    backend with a statement cache will look faster than it is on repeated
    snippets. Prefer --from-bank with n ≤ pool size when that matters.
    """
    if not pairs:
        raise SystemExit("no (prop, proof) pairs to benchmark")
    return [proof_check(p, pr) for p, pr in (pairs[i % len(pairs)] for i in range(n))]


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def percentile(xs: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile; None on an empty sample (never a fabricated 0.0)."""
    if not xs:
        return None
    ordered = sorted(xs)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))]


def throughput_stats(latencies: Sequence[float], wall_s: float, n: int, failures: int) -> dict:
    """The Phase 0 gate number plus the latency shape behind it.

    attempts_per_hr is derived from wall-clock, not from the sum of latencies:
    with a worker pool those differ by the parallelism factor, and the gate is
    about what the box delivers per hour.
    """
    return {
        "n": n,
        "wall_s": round(wall_s, 3),
        "attempts_per_hr": round(3600.0 * n / wall_s, 1) if wall_s > 0 else None,
        # The gate is phrased in *verified* attempts/hr, so failed checks are
        # netted out here rather than left for the reader to do in their head.
        "verified_per_hr": round(3600.0 * (n - failures) / wall_s, 1) if wall_s > 0 else None,
        "p50_s": percentile(latencies, 0.50),
        "p95_s": percentile(latencies, 0.95),
        "mean_s": round(statistics.fmean(latencies), 4) if latencies else None,
        "failures": failures,
    }


def summarize(stats: dict) -> str:
    def fmt(x, spec=".4g"):
        return "n/a" if x is None else format(x, spec)

    return (
        f"throughput: {fmt(stats['attempts_per_hr'], ',.0f')} attempts/hr "
        f"({fmt(stats['verified_per_hr'], ',.0f')} verified/hr)\n"
        f"  {stats['n']} checks in {fmt(stats['wall_s'])}s, {stats['workers']} workers, "
        f"backend={stats['backend']}, suite={stats['suite']}\n"
        f"latency: p50={fmt(stats['p50_s'])}s p95={fmt(stats['p95_s'])}s mean={fmt(stats['mean_s'])}s\n"
        f"failures: {stats['failures']}/{stats['n']}\n"
        f"gate (DIRECTION.md §5.5): 2000-3000 verified attempts/hr — judgment recorded in PHASE0_NOTES.md"
    )


# ---------------------------------------------------------------------------
# Backend seam
# ---------------------------------------------------------------------------

def make_backend(args):
    """Via rlmath.lean's factory, so --workers means pool size on both backends."""
    if args.backend == "fake":
        if FAKE_BACKEND_FACTORY is None:
            raise SystemExit("--backend fake requires FAKE_BACKEND_FACTORY (tests only)")
        return FAKE_BACKEND_FACTORY()
    from rlmath.lean import get_backend

    kw = (
        {"n_workers": args.workers}
        if args.backend == "repl"
        else {"base_url": args.kimina_url, "max_workers": args.workers}
    )
    return get_backend(args.backend, **kw)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Measure verifier throughput (DIRECTION.md §5.5 gate).")
    p.add_argument("--suite", choices=["trivial"], default="trivial")
    p.add_argument("--from-bank", type=Path, default=None, help="sample (prop, proof) pairs from a bank JSONL instead")
    p.add_argument("--n", type=int, default=60, help="total checks to run")
    p.add_argument("--workers", type=int, default=4, help="backend concurrency (pool size)")
    p.add_argument("--backend", choices=["repl", "kimina", "fake"], default="repl")
    p.add_argument("--kimina-url", default=None, help="default: $RLMATH_KIMINA_URL, then the client default")
    p.add_argument("--timeout-s", type=float, default=120.0)
    p.add_argument("--seed", type=int, default=None, help="shuffle seed for --from-bank sampling")
    p.add_argument("--timestamp", default=None, help="stamped into the JSON verbatim; omitted -> null")
    p.add_argument("--out", type=Path, default=ROOT / "analysis" / "throughput.json")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.from_bank:
        pairs = suite_from_bank(args.from_bank, seed=args.seed)
        suite = f"bank:{args.from_bank.name}"
        if not pairs:
            raise SystemExit(f"no rows with a first_proof in {args.from_bank}")
    else:
        pairs = list(TRIVIAL_SUITE)
        suite = "trivial"

    codes = build_codes(pairs, args.n)
    backend = make_backend(args)
    print(f"benchmark: {args.n} checks, suite={suite}, backend={args.backend}, workers={args.workers}",
          file=sys.stderr)
    t0 = time.perf_counter()
    try:
        results = backend.check_many(codes, timeout_s=args.timeout_s)
    finally:
        backend.close()
    wall_s = time.perf_counter() - t0

    failures = sum(1 for r in results if not (r.ok and r.sorries == 0))
    # elapsed_s is per-check backend time; a backend that does not populate it
    # leaves the latency fields null rather than reporting a fabricated zero.
    latencies = [r.elapsed_s for r in results if r.elapsed_s > 0]
    stats = throughput_stats(latencies, wall_s, len(results), failures)
    stats.update(timestamp=args.timestamp, backend=args.backend, workers=args.workers, suite=suite)

    print(summarize(stats))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(stats, f, indent=2)
        f.write("\n")
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
