#!/usr/bin/env python
"""Locate the r4_floorprod V4 elaboration wall: which k, which rungs, how close."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path("/Users/tom/code/playground/rlmath")
from rlmath.families import case_tree as ct  # noqa: E402
from rlmath.families import validate_problem  # noqa: E402
from rlmath.lean.repl_pool import ReplPool  # noqa: E402

OUT = ROOT / "data" / "families" / "ct_battery"
SEED = 5150
t0 = time.time()


def log(*a):
    print(f"[{time.time() - t0:7.1f}s]", *a, flush=True)


def main():
    pool = ReplPool(n_workers=4)
    pool.warm()
    rows = []
    try:
        plan = [("r4_floorprod", k, i) for k in (16, 32) for i in (0, 1, 2)]
        plan += [("r2_prod", 32, i) for i in (1, 2)]
        plan += [("r2_sum", 32, i) for i in (1, 2)]
        plan += [("v2", 32, i) for i in (1, 2)]
        plan += [("r1_recip", 32, i) for i in (1, 2)]
        plan += [("r3_floor", 32, i) for i in (1, 2)]
        plan += [("r4_floorprod", 64, 0), ("v2", 64, 0), ("r2_sum", 64, 0)]
        for name, k, idx in plan:
            p = ct.build(k, SEED, idx, preset=name)
            t = time.time()
            r = validate_problem(p, pool, check_automation=False, timeout_s=600.0)
            row = {"rung": name, "k": k, "idx": idx, "ok": r.ok,
                   "seconds": round(time.time() - t, 1),
                   "goal_chars": len(p.goal.prop),
                   "failed": [c.name for c in r.failed()],
                   "detail": (r.failed()[0].detail[:120] if r.failed() else "")}
            rows.append(row)
            log(row)
    finally:
        pool.close()
    (OUT / "gate_validate_scaling.json").write_text(
        json.dumps({"rows": rows, "seconds": round(time.time() - t0, 1)},
                   ensure_ascii=False, indent=2))
    log("wrote gate_validate_scaling.json")


if __name__ == "__main__":
    sys.exit(main())
