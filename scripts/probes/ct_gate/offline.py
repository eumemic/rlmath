#!/usr/bin/env python
"""Free structural computations for the case_tree ladder local gate (agent G).

Everything here is exact arithmetic off the SHIPPED generator; no Lean, no LM.
"""
from __future__ import annotations

import json
import math
import statistics as st
import sys
from pathlib import Path

ROOT = Path("/Users/tom/code/playground/rlmath")
sys.path.insert(0, str(ROOT / "scripts"))

from rlmath.families import case_tree as ct  # noqa: E402
import stage_ct_candidates as S  # noqa: E402

SEED = 5150
K_GRID = (2, 4, 8)
RUNGS = ["v2", "r1_recip", "r2_prod", "r2_sum", "r3_floor", "r4_floorprod"]
OUT = ROOT / "data" / "families" / "ct_battery"


def piece_of(c):
    idx = int(c.problem_id.rsplit("-", 1)[1])
    variant, pieces = ct.layout(c.k, SEED, idx, preset=c.rung)
    return variant, pieces[c.position - 1]


def stage():
    staged, seen = {}, set()
    for name in RUNGS:
        c, p, s = S.candidates_for_rung(name, k_grid=K_GRID, seed=SEED,
                                        per_rung=30, seen=seen)
        staged[name] = {"candidates": c, "problems": p, "stats": s}
    return staged


def divisors(n):
    return [a for a in range(1, n + 1) if n % a == 0]


def main():
    staged = stage()
    out = {}

    # --- 1. target width: how many integer splits close, and is the obvious
    #        guess one of them?  (§5's "offline target-width measurement")
    tw = {}
    for name in ("r2_sum", "r2_prod"):
        rows = []
        for c in staged[name]["candidates"]:
            _, p = piece_of(c)
            far = p.m + p.far
            umax, wmax = p.atoms[0].value(far), p.atoms[1].value(far)
            T = p.budget
            t1, t2 = p.caps
            if name == "r2_sum":
                cands = [(s1, T - s1) for s1 in range(1, T)]
                naive = (T // 2, T - T // 2)
            else:
                cands = [(a, T // a) for a in divisors(T)]
                bal = max((a for a in divisors(T) if a * a <= T), default=1)
                naive = (bal, T // bal)
            feas = [(s1, s2) for s1, s2 in cands if s1 * s1 >= umax and s2 * s2 >= wmax]
            rows.append({"id": c.key[:6], "k": c.k, "T": T, "oracle": [t1, t2],
                         "n_candidate_splits": len(cands), "n_feasible": len(feas),
                         "feasible": feas[:4], "naive": list(naive),
                         "naive_feasible": list(naive) in [list(f) for f in feas],
                         "gap": abs(t1 - T / 2)})
        tw[name] = {
            "n": len(rows),
            "unique_feasible_frac": round(sum(r["n_feasible"] == 1 for r in rows) / len(rows), 3),
            "median_candidate_splits": st.median(r["n_candidate_splits"] for r in rows),
            "min_candidate_splits": min(r["n_candidate_splits"] for r in rows),
            "max_candidate_splits": max(r["n_candidate_splits"] for r in rows),
            "naive_is_feasible_frac": round(sum(r["naive_feasible"] for r in rows) / len(rows), 3),
            "split_gap_median": st.median(r["gap"] for r in rows),
            "split_gap_max": max(r["gap"] for r in rows),
            "split_gap_le_half_frac": round(sum(r["gap"] <= 0.5 for r in rows) / len(rows), 3),
            "rows": rows,
        }
    out["target_width"] = tw

    # --- 2. r3_floor / r4_floorprod: is the memorised sub-goal FALSE, and where?
    fl = {}
    for name in ("r3_floor", "r4_floorprod"):
        rows = []
        for c in staged[name]["candidates"]:
            _, p = piece_of(c)
            T = p.budget
            npts = 0
            bad = 0
            # sample the real band on a fine grid; exact integer comparison at
            # the crossing is not needed for a *fraction*, but use exact ints at
            # integer x to cross-check
            N = 1000
            for i in range(N + 1):
                x = p.lo + (p.hi - p.lo) * i / N
                if len(p.atoms) == 1:
                    val = math.sqrt(p.a * (x - p.m) ** 2 + p.atoms[0].e)
                else:
                    val = math.sqrt(p.atoms[0].a * (x - p.m) ** 2 + p.atoms[0].e) * \
                        math.sqrt(p.atoms[1].a * (x - p.m) ** 2 + p.atoms[1].e)
                npts += 1
                if val > T:
                    bad += 1
            rows.append({"id": c.key[:6], "k": c.k, "T": T,
                         "frac_band_where_sqrt_le_T_is_false": round(bad / npts, 3)})
        fr = [r["frac_band_where_sqrt_le_T_is_false"] for r in rows]
        fl[name] = {"n": len(rows), "min": min(fr), "median": st.median(fr),
                    "max": max(fr), "always_false_somewhere": all(f > 0 for f in fr),
                    "rows": rows}
    out["tightness"] = fl

    # --- 3. distinct-leaf capacity per rung (§2.3, R4.3)
    cap = {}
    for name in RUNGS:
        props = set()
        knobs = set()
        for idx in range(300):
            p = ct.build(8, 4242, idx, preset=name)
            for l in p.oracle_plan.lemmas:
                props.add(l.prop)
            for kb in p.meta["knobs"]:
                knobs.add(tuple(sorted((k, v) for k, v in kb.items() if k != "repaired")))
        cap[name] = {"problems": 300, "leaves": 300 * 8,
                     "distinct_leaf_props": len(props),
                     "distinct_knob_tuples": len(knobs)}
    out["capacity_k8_300problems"] = cap

    # --- 4. flatness structurals: leaf length / coeff magnitude / outer const by k
    fla = {}
    for name in RUNGS:
        rows = {}
        for k in (2, 4, 8, 16, 32):
            ps = [ct.build(k, 7777, i, preset=name) for i in range(10)]
            stats = ct.leaf_stats(ps)[k]
            rows[k] = {"leaf_len_min": stats["leaf_len_min"],
                       "leaf_len_mean": stats["leaf_len_mean"],
                       "leaf_len_max": stats["leaf_len_max"],
                       "median_abs_coeff": stats["median_abs_coeff"],
                       "max_abs_coeff": stats["max_abs_coeff"],
                       "max_outer_const": stats["max_outer_const"],
                       "repaired_frac": stats["repaired_frac"],
                       "knob_support_ok": stats["knob_support_ok"]}
        fla[name] = rows
    out["flatness_structural"] = fla

    # --- 5. R3' power: log10 max|coef| spread over the staged rows
    logs = []
    for name in RUNGS:
        for c in staged[name]["candidates"]:
            logs.append(math.log10(max(1, c.max_abs_coeff)))
    out["r3prime_power"] = {
        "n_rows": len(logs), "mean": round(st.mean(logs), 3),
        "sd": round(st.pstdev(logs), 3),
        "se_slope_per_decade": round(0.30 / (st.pstdev(logs) * math.sqrt(len(logs))), 4),
    }

    # --- 6. necessity sweep + predicate audit, per rung, restated
    nec = {}
    for name in RUNGS:
        r = ct.resolve_preset(name)
        sw = ct.necessity_sweep(r)
        under = over = pts = 0
        for k in (2, 4, 8, 16, 32):
            _, pieces = ct.layout(k, SEED, 0, preset=r)
            for pc in pieces:
                a = ct.predicate_mismatches(pc, radius=14)
                under += len(a["under"])
                over += len(a["over"])
                pts += a["points"]
        nec[name] = {"cells": sw["cells"], "max_spill": sw["max_spill"],
                     "threshold": sw["threshold"], "ok": sw["ok"],
                     "cells_at_threshold": len(sw["cells_at_threshold"]),
                     "audit_points": pts, "audit_under": under, "audit_over": over}
    out["necessity_and_predicate"] = nec

    # --- 7. staged-row summary per rung
    sm = {}
    for name in RUNGS:
        cands = staged[name]["candidates"]
        chars = sorted(len(c.prop) for c in cands)
        sm[name] = {
            "leaves": len(cands),
            "k_mix": {k: sum(1 for c in cands if c.k == k) for k in K_GRID},
            "variant_mix": {v: sum(1 for c in cands if c.variant == v)
                            for v in ("max", "min")},
            "leaf_chars": [chars[0], chars[len(chars) // 2], chars[-1]],
            "deduped": staged[name]["stats"]["deduped"],
            "distinct_statements": len({c.key for c in cands}),
            "knob_cells": len({tuple(sorted(c.knobs.items())) for c in cands}),
            "log10_coef": [round(math.log10(max(1, min(c.max_abs_coeff for c in cands))), 2),
                           round(st.mean(math.log10(max(1, c.max_abs_coeff)) for c in cands), 2),
                           round(math.log10(max(c.max_abs_coeff for c in cands)), 2)],
        }
    out["staged_summary"] = sm

    (OUT / "gate_offline.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in out.items() if k != "target_width"},
                     ensure_ascii=False, indent=2)[:6000])
    print("\n--- target width ---")
    for n, v in out["target_width"].items():
        print(n, {k: x for k, x in v.items() if k != "rows"})


if __name__ == "__main__":
    main()
