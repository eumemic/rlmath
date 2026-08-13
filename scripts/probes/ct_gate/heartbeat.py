#!/usr/bin/env python
"""Is the r4_floorprod k=32 V4 wall a heartbeat budget or a real blow-up?

Recompose the same artifact with `set_option maxHeartbeats N in` and re-check.
Also: v2 at k=128 (FAMILIES.md's stated scaling ceiling) and r2_prod at k=64.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from rlmath.core import leancode
from rlmath.families import case_tree as ct
from rlmath.lean.repl_pool import ReplPool

ROOT = Path("/Users/tom/code/playground/rlmath")
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
        for name, k, hb in [("r4_floorprod", 32, 400000), ("r4_floorprod", 32, 1600000),
                            ("r4_floorprod", 32, 6400000), ("r2_sum", 64, 1600000),
                            ("r4_floorprod", 64, 6400000), ("v2", 128, 400000),
                            ("r2_prod", 64, 400000), ("r2_prod", 64, 1600000)]:
            p = ct.build(k, SEED, 0, preset=name)
            art = leancode.compose(p.goal, p.oracle_plan, p.witness_proofs())
            code = f"set_option maxHeartbeats {hb} in\n{art}" if hb != 400000 else art
            t = time.time()
            r = pool.check(code, timeout_s=900.0)
            row = {"rung": name, "k": k, "maxHeartbeats": hb,
                   "ok": bool(r.ok and r.sorries == 0),
                   "seconds": round(time.time() - t, 1),
                   "artifact_chars": len(art),
                   "err": [m.text[:80] for m in r.errors][:1]}
            rows.append(row)
            log(row)
    finally:
        pool.close()
    (OUT / "gate_heartbeat.json").write_text(
        json.dumps({"rows": rows, "note": "PREAMBLE sets maxHeartbeats 400000",
                    "seconds": round(time.time() - t0, 1)}, ensure_ascii=False, indent=2))
    log("wrote gate_heartbeat.json")


main()
