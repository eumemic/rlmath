#!/usr/bin/env python3
"""Apply research/case-tree-hardening.md §12.2's registered rule to the n=32 replication.

Written and committed BEFORE the data landed, so the verdict is arithmetic rather than a
judgement made while looking at the numbers. §12.2 fixes the thresholds:

    PASS      >= 70% of in-band leaves stay in band AND the filtered mean moves < 0.10
    MARGINAL  50-70% stay
    FAIL      < 50% stay

The run is two-sided on purpose. Re-measuring only the 33 kept leaves cannot separate "the
filter works" from "a noisy sample regressed toward the middle", so 8 leaves that measured 0/8
and 8 that measured 8/8 go in alongside. Their movement estimates the true-rate distribution,
which is the thing the n=8 filter is really being asked about.

Usage:  uv run python scripts/analyze_n32.py [--measure PATH] [--staged PATH]
"""
from __future__ import annotations

import argparse
import json
import math
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

BAND_LO, BAND_HI = 0.25, 0.9
N8_FILTERED_MEAN = {"r3_floor": 0.448, "r2_prod": 0.363}   # §12.1, the numbers under test


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson interval — honest at the small n this run has, unlike normal approximation."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--measure", type=Path, default=Path("data/bank/ct_n32_measure.jsonl"))
    ap.add_argument("--staged", type=Path, default=Path("data/families/ct_n32_replication.jsonl"))
    a = ap.parse_args(argv)

    staged = {json.loads(l)["statement_key"]: json.loads(l) for l in a.staged.open()}
    rows = []
    for line in a.measure.open():
        r = json.loads(line)
        s = staged.get(r["statement_key"])
        if s is None:
            continue
        rows.append({"n8": s["n8_pass_rate"], "n32": r["pass_rate"], "stratum": s["stratum"],
                     "preset": s["preset"], "k": s["k"], "status": r.get("status"),
                     "n_attempts": r.get("n_attempts")})

    print(f"joined {len(rows)}/{len(staged)} staged leaves")
    print(f"statuses: {dict(Counter(r['status'] for r in rows))}")
    att = Counter(r["n_attempts"] for r in rows)
    print(f"attempts per leaf: {dict(att)}"
          f"{'   *** NOT 32 — the comparison is void ***' if set(att) != {32} else ''}\n")

    by = defaultdict(list)
    for r in rows:
        by[r["stratum"]].append(r)

    print(f"{'stratum':11} {'n':>3} {'n8 mean':>8} {'n32 mean':>9} {'in band @32':>12} {'95% CI':>16}")
    for s in ("in_band", "zero", "saturated"):
        v = by.get(s, [])
        if not v:
            continue
        kept = sum(1 for r in v if BAND_LO <= r["n32"] <= BAND_HI)
        lo, hi = wilson(kept, len(v))
        print(f"{s:11} {len(v):>3} {st.mean(r['n8'] for r in v):>8.3f} "
              f"{st.mean(r['n32'] for r in v):>9.3f} {kept:>5}/{len(v):<6} "
              f"{f'[{lo:.2f}, {hi:.2f}]':>16}")

    ib = by.get("in_band", [])
    if not ib:
        print("\nno in_band rows — cannot evaluate the registered rule")
        return 2
    stay = sum(1 for r in ib if BAND_LO <= r["n32"] <= BAND_HI)
    frac = stay / len(ib)
    lo, hi = wilson(stay, len(ib))

    print("\n=== per-rung filtered mean: n=8 (the claim) vs n=32 (the test) ===")
    drift_ok = True
    for rung, claimed in N8_FILTERED_MEAN.items():
        v = [r for r in ib if r["preset"] == rung]
        if not v:
            continue
        m = st.mean(r["n32"] for r in v)
        d = m - claimed
        if abs(d) >= 0.10:
            drift_ok = False
        print(f"  {rung:10} n={len(v):<3} n8-filtered {claimed:.3f} -> n32 {m:.3f}  "
              f"drift {d:+.3f}  {'ok' if abs(d) < 0.10 else 'MOVED >= 0.10'}")

    print("\n=== registered rule (§12.2) ===")
    print(f"  in-band retention: {stay}/{len(ib)} = {frac:.0%}   95% CI [{lo:.0%}, {hi:.0%}]")
    print(f"  filtered-mean drift < 0.10: {'yes' if drift_ok else 'NO'}")
    verdict = ("PASS" if frac >= 0.70 and drift_ok
               else "MARGINAL" if frac >= 0.50 else "FAIL")
    print(f"\n  VERDICT: {verdict}")
    print({
        "PASS": "  -> measure-and-filter is a real instrument; Phase 1 closes for case_tree.",
        "MARGINAL": "  -> the filter leaks; filter at n=16 and caveat the corridor claim wherever cited.",
        "FAIL": "  -> the n=8 filter is mostly noise. A genuine Phase-1 negative, not a setback to\n"
                "     engineer around. Phase 2 still runs; the leaves change, the question does not.",
    }[verdict])

    # Registered side-predictions, scored (§12.2 predicted 1-2 of 8 for each).
    print("\n=== side predictions (registered: 1-2 of 8 each) ===")
    z = by.get("zero", [])
    s8 = by.get("saturated", [])
    if z:
        n = sum(1 for r in z if r["n32"] >= BAND_LO)
        print(f"  zero -> >= 0.25 at n=32:      {n}/{len(z)}  {'hit' if 1 <= n <= 2 else 'MISS'}")
    if s8:
        n = sum(1 for r in s8 if r["n32"] <= BAND_HI)
        print(f"  saturated -> <= 0.9 at n=32:  {n}/{len(s8)}  {'hit' if 1 <= n <= 2 else 'MISS'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
