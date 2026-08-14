#!/usr/bin/env python3
"""Apply DIRECTION §7.3's registered rule to the Phase-3 eval trace.

Written before the training run produced a number, for the same reason `analyze_n32.py` was:
the verdict should be arithmetic on a rule fixed in advance, not a judgement made while looking
at numbers I have three days invested in.

§7.3 registered:

    k=2 parse rate    35% -> >85%      (if this does not move, the reward plumbing is broken)
    k=2 valid         15% -> 35-55%
    k=4 valid (untrained)  ~5% -> 15-30%
    k=8 valid (untrained)  ~0% ->  5-15%

    THE RESULT IS THE TRANSFER RATIO, NOT THE LEVELS. lift(k) = trained - baseline.
    The RLM claim predicts lift at k=4/8 that is a substantial fraction of lift at k=2.
    NULL if: lift(k=4) < one third of lift(k=2), or lift(k=8) within noise of zero.

`--eval` defaults to the trainer's own `eval.jsonl`, which holds one row per eval point
(`baseline`, `step25`, ..., `final`) so the trajectory is visible, not just the endpoints.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

REG = {2: (0.35, 0.55), 4: (0.15, 0.30), 8: (0.05, 0.15)}   # registered post-training bands
BASE_PARSE_K2 = 0.35                                        # measured, §7.2 ladder


def two_prop_z(x1: int, n1: int, x2: int, n2: int) -> float:
    """Trained vs baseline as a two-proportion z. The lift is a DIFFERENCE between two
    measured rates, so testing it against one rate's own confidence interval (which an
    earlier version of this file did) is the wrong test — and it made the success band sit
    inside the noise band, a gate with no attainable pass state."""
    if n1 == 0 or n2 == 0:
        return 0.0
    p1, p2 = x1 / n1, x2 / n2
    pp = (x1 + x2) / (n1 + n2)
    d = pp * (1 - pp) * (1 / n1 + 1 / n2)
    return (p2 - p1) / math.sqrt(d) if d > 0 else 0.0


def min_detectable_lift(base_rate: float, n: int) -> float:
    """Smallest lift this n could call significant at ~2 sigma, given the baseline rate.
    Reported so an underpowered cell is labelled underpowered instead of NULL."""
    for pts in range(1, n + 1):
        if two_prop_z(round(base_rate * n), n, round(base_rate * n) + pts, n) >= 1.96:
            return pts / n
    return 1.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--eval", type=Path, default=Path("runs/grpo9b/eval.jsonl"))
    a = ap.parse_args(argv)

    rows = [json.loads(l) for l in a.eval.open()]
    if not rows:
        print("no eval rows"); return 2
    by_tag = {r["tag"]: {int(k): v for k, v in r["res"].items()} for r in rows}
    base = by_tag.get("baseline")
    if base is None:
        print("no baseline row — every lift below would be meaningless"); return 2
    # last non-baseline row is the trained endpoint
    trained_tag = [r["tag"] for r in rows if r["tag"] != "baseline"][-1] if len(rows) > 1 else None
    if trained_tag is None:
        print("only a baseline exists; nothing trained yet"); return 2
    fin = by_tag[trained_tag]

    print(f"trajectory: {' -> '.join(r['tag'] for r in rows)}\n")
    print(f"{'k':>3} {'baseline':>18} {'trained':>18} {'lift':>8} {'registered':>14} {'':>6}")
    lift = {}
    for k in (2, 4, 8):
        b, f = base.get(k), fin.get(k)
        if not b or not f:
            continue
        bl, fl = b["rate"], f["rate"]
        lift[k] = fl - bl
        lo, hi = REG[k]
        hit = "HIT" if lo <= fl <= hi else ("over" if fl > hi else "under")
        print(f"{k:>3} {b['valid']}/{b['n']} = {bl:>6.0%}    {f['valid']}/{f['n']} = {fl:>6.0%}  "
              f"{lift[k]:>+7.0%} {f'{lo:.0%}-{hi:.0%}':>14} {hit:>6}")

    # Plumbing check first: the format tier is the easiest thing to learn, so if parse did not
    # move, nothing below is about decomposition.
    if 2 in base and 2 in fin:
        bp = base[2]["parsed"] / base[2]["n"]
        fp = fin[2]["parsed"] / fin[2]["n"]
        print(f"\nk=2 parse rate: {bp:.0%} -> {fp:.0%} (registered >85%)"
              f"{'  *** DID NOT MOVE — suspect the reward plumbing before reading anything else ***' if fp < 0.6 else ''}")

    print("\n=== registered verdict (§7.3) ===")
    if 2 not in lift or lift[2] <= 0:
        print("  k=2 lift is zero or negative: training did not work at all. Nothing to say about"
              "\n  transfer — the precondition for the experiment failed, not the hypothesis.")
        return 0
    sig, powered = {}, {}
    for k in (2, 4, 8):
        if k not in lift:
            continue
        b, f = base[k], fin[k]
        z = two_prop_z(b["valid"], b["n"], f["valid"], f["n"])
        mdl = min_detectable_lift(b["rate"], f["n"])
        sig[k] = z
        powered[k] = mdl <= REG[k][1]          # can this n even see the predicted band?
        ratio = "" if k == 2 else f"  ratio to k=2 lift: {lift[k]/lift[2]:.2f}"
        print(f"  k={k}: lift {lift[k]:+.0%}, z={z:+.2f}"
              f"{' (SIG)' if abs(z) >= 1.96 else ''}"
              f", min detectable lift at n={f['n']} is {mdl:.0%}"
              f"{'' if powered[k] else '  <-- UNDERPOWERED for the registered band'}{ratio}")

    r4 = lift.get(4, 0.0) / lift[2]
    null_4 = r4 < (1 / 3)
    # k=8 counts as null only if it is BOTH small in ratio and the cell was powered enough to
    # have seen the predicted effect. An underpowered miss is "cannot resolve", not "no effect".
    r8 = lift.get(8, 0.0) / lift[2]
    null_8 = r8 < (1 / 3) and powered.get(8, False)
    if 8 in lift and not powered.get(8, False):
        print(f"\n  NOTE: the k=8 cell is UNDERPOWERED — n={fin[8]['n']} cannot resolve a lift in"
              f"\n  the registered 5-15% band. §7.3's null criterion was mis-specified on this"
              f"\n  point (it tested the lift against one rate's own CI). k=8 is reported"
              f"\n  DIRECTIONAL only; the k=4 cell carries the verdict.")
    if null_4 or null_8:
        print("\n  VERDICT: NULL on the registered criterion"
              + (f"\n    - lift(k=4) is {r4:.2f} of lift(k=2), below the 1/3 threshold" if null_4 else "")
              + (f"\n    - lift(k=8) is {r8:.2f} of lift(k=2) in a cell powered to see it" if null_8 else "")
              + "\n  Reading: the policy improved on the trained size without carrying it to untrained"
                "\n  sizes — it learned these problems, not how to decompose. That is a real result"
                "\n  about this setup, and it is the outcome §7.3 said would count as a null.")
    else:
        print("\n  VERDICT: TRANSFER — lift at untrained k is a substantial fraction of lift at k=2."
              "\n  This is the RLM claim's signature: training short buys competence long."
              "\n  Caveats that still apply (§7.3): one seed, one family, one model size, no"
              "\n  compute-matched flat control, and stage-1 validity is necessary-not-sufficient"
              "\n  for a closed proof.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
