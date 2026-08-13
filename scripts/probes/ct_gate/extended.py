#!/usr/bin/env python
"""Extended local gate for the case_tree hardening ladder (agent G).

Phases, all written incrementally to data/families/ct_battery/:
  A  planted control, on its own, first          -> gate_control.json
  B  full battery on a KNOB-SPANNING subset      -> gate_battery_ext.json
  C  witness kernel check on EVERY staged leaf   -> gate_witness_all.json
  D  the idiom probe, per rung + control rung    -> gate_idiom.json
  E  k=32 structural validation (V1..V4,V6)      -> gate_validate_k32.json

Reads only; the generator is not modified.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path("/Users/tom/code/playground/rlmath")
sys.path.insert(0, str(ROOT / "scripts"))

from rlmath.families import case_tree as ct  # noqa: E402
from rlmath.core import leancode  # noqa: E402
from rlmath.families.validate import battery_proofs  # noqa: E402

import stage_ct_candidates as S  # noqa: E402

OUT = ROOT / "data" / "families" / "ct_battery"
SEED = 5150
K_GRID = (2, 4, 8)
PER_RUNG = 30
RUNGS = ["v2", "r1_recip", "r2_prod", "r2_sum", "r3_floor", "r4_floorprod"]

_t0 = time.time()


def log(*a):
    print(f"[{time.time() - _t0:7.1f}s]", *a, flush=True)


def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2))
    log(f"wrote {name}")


# --------------------------------------------------------------- staging ----

def stage():
    staged, seen = {}, set()
    for name in RUNGS:
        c, p, st = S.candidates_for_rung(name, k_grid=K_GRID, seed=SEED,
                                         per_rung=PER_RUNG, seen=seen)
        staged[name] = {"candidates": c, "problems": p, "stats": st}
    return staged


def piece_of(c):
    idx = int(c.problem_id.rsplit("-", 1)[1])
    variant, pieces = ct.layout(c.k, SEED, idx, preset=c.rung)
    return variant, pieces[c.position - 1]


def spanning(cands):
    """Greedy cover of the observed knob support + coefficient extremes per k."""
    picked, keys = [], set()

    def add(c):
        if c.key not in keys:
            keys.add(c.key)
            picked.append(c)

    by_k = {}
    for c in cands:
        by_k.setdefault(c.k, []).append(c)
    for k in sorted(by_k):
        r = sorted(by_k[k], key=lambda c: (c.max_abs_coeff, c.position))
        add(r[0])
        add(r[-1])

    def cells(c):
        out = {("k", c.k), ("variant", c.variant)}
        for f in ("width", "curvature", "offset", "slack", "curvature2"):
            if f in c.knobs:
                out.add((f, c.knobs[f]))
        return out

    need = set()
    for c in cands:
        need |= cells(c)
    have = set()
    for c in picked:
        have |= cells(c)
    while need - have:
        best = max(cands, key=lambda c: (len(cells(c) - have), -c.max_abs_coeff))
        if not (cells(best) - have):
            break
        add(best)
        have |= cells(best)
    return picked, sorted(f"{a}={b}" for a, b in sorted(need, key=str))


# ----------------------------------------------------------- the idioms ----

def hints(p):
    return (f"sq_nonneg ({ct._shift(p.m)}), sq_nonneg ({ct._shift(p.lo)}), "
            f"sq_nonneg ({ct._shift(p.hi)})")


def i0_verbatim(p, radicand, cap):
    """The measured DSV2 idiom, mechanically retargeted (survey S1/S2 form)."""
    h = hints(p)
    if radicand is None:
        return f"by\n  intro x hx1 hx2\n  nlinarith [{h}]"
    return (
        "by\n"
        "  intro x hx1 hx2\n"
        f"  have h₁ : 0 ≤ Real.sqrt ({radicand}) := by apply Real.sqrt_nonneg\n"
        f"  have h₂ : Real.sqrt ({radicand}) ≤ {cap} := by\n"
        "    apply Real.sqrt_le_iff.mpr\n"
        f"    constructor <;> nlinarith [{h}]\n"
        f"  nlinarith [{h}]"
    )


def i1_sq_sqrt(p, radicand):
    h = hints(p)
    return (
        "by\n"
        "  intro x hx1 hx2\n"
        f"  have hu : (0:ℝ) ≤ {radicand} := by nlinarith [sq_nonneg ({ct._shift(p.m)})]\n"
        f"  nlinarith [Real.sq_sqrt hu, Real.sqrt_nonneg ({radicand}), {h}]"
    )


def divisor_pairs(T):
    return [(a, T // a) for a in range(1, T + 1) if T % a == 0]


def balanced_pair(T):
    best = (1, T)
    for a, b in divisor_pairs(T):
        if a <= b:
            best = (a, b)
    return best


def idioms_for(rung, p):
    """dict name -> proof, plus a dict name -> what it tests."""
    h = hints(p)
    u = p.atoms[0].render()
    out = {}
    if rung == "v2":
        out["I0_verbatim"] = i0_verbatim(p, u, p.budget)
        out["I1_sq_sqrt"] = i1_sq_sqrt(p, u)
    elif rung == "r1_recip":
        c, ur = p.budget, u
        out["I0_verbatim"] = i0_verbatim(p, None, c)   # no √ atom to aim at
        out["A1_le_div_iff0"] = (
            "by\n  intro x hx1 hx2\n"
            f"  have hu : (0:ℝ) < {ur} := by nlinarith [sq_nonneg ({ct._shift(p.m)})]\n"
            f"  have hk : ({ct.C_LEVEL}:ℝ) ≤ {c} / ({ur}) := by\n"
            "    rw [le_div_iff₀ hu]\n"
            f"    nlinarith [{h}]\n"
            "  linarith")
        out["A2_div_nonneg_only"] = (
            "by\n  intro x hx1 hx2\n"
            f"  have hu : (0:ℝ) < {ur} := by nlinarith [sq_nonneg ({ct._shift(p.m)})]\n"
            f"  have hd : (0:ℝ) ≤ {c} / ({ur}) := by positivity\n"
            f"  nlinarith [{h}, hd]")
    elif rung == "r2_prod":
        w = p.atoms[1].render()
        t1, t2 = p.caps
        out["I0_verbatim"] = i0_verbatim(p, u, p.budget)
        out["I1_sq_sqrt"] = i1_sq_sqrt(p, u)
        out["A1_oracle_split"] = (
            "by\n  intro x hx1 hx2\n"
            f"  have h1 : Real.sqrt ({u}) ≤ {t1} := Real.sqrt_le_iff.mpr "
            f"⟨by norm_num, by nlinarith [{h}]⟩\n"
            f"  have h2 : Real.sqrt ({w}) ≤ {t2} := Real.sqrt_le_iff.mpr "
            f"⟨by norm_num, by nlinarith [{h}]⟩\n"
            f"  have h3 : Real.sqrt ({u}) * Real.sqrt ({w}) ≤ {t1} * {t2} :=\n"
            "    mul_le_mul h1 h2 (Real.sqrt_nonneg _) (by norm_num)\n"
            "  linarith")
        b1, b2 = balanced_pair(p.budget)
        out["A2_balanced_split"] = (
            "by\n  intro x hx1 hx2\n"
            f"  have h1 : Real.sqrt ({u}) ≤ {b1} := Real.sqrt_le_iff.mpr "
            f"⟨by norm_num, by nlinarith [{h}]⟩\n"
            f"  have h2 : Real.sqrt ({w}) ≤ {b2} := Real.sqrt_le_iff.mpr "
            f"⟨by norm_num, by nlinarith [{h}]⟩\n"
            f"  have h3 : Real.sqrt ({u}) * Real.sqrt ({w}) ≤ {b1} * {b2} :=\n"
            "    mul_le_mul h1 h2 (Real.sqrt_nonneg _) (by norm_num)\n"
            "  linarith")
    elif rung == "r2_sum":
        w = p.atoms[1].render()
        t1, t2 = p.caps
        out["I0_verbatim"] = i0_verbatim(p, u, p.budget)
        out["I1_sq_sqrt"] = i1_sq_sqrt(p, u)
        out["A1_oracle_split"] = (
            "by\n  intro x hx1 hx2\n"
            f"  have h1 : Real.sqrt ({u}) ≤ {t1} := Real.sqrt_le_iff.mpr "
            f"⟨by norm_num, by nlinarith [{h}]⟩\n"
            f"  have h2 : Real.sqrt ({w}) ≤ {t2} := Real.sqrt_le_iff.mpr "
            f"⟨by norm_num, by nlinarith [{h}]⟩\n"
            "  linarith")
        e1 = p.budget // 2
        e2 = p.budget - e1
        out["A2_even_split"] = (
            "by\n  intro x hx1 hx2\n"
            f"  have h1 : Real.sqrt ({u}) ≤ {e1} := Real.sqrt_le_iff.mpr "
            f"⟨by norm_num, by nlinarith [{h}]⟩\n"
            f"  have h2 : Real.sqrt ({w}) ≤ {e2} := Real.sqrt_le_iff.mpr "
            f"⟨by norm_num, by nlinarith [{h}]⟩\n"
            "  linarith")
    elif rung == "r3_floor":
        T = p.budget
        out["I0_verbatim"] = i0_verbatim(p, u, T)
        out["I1_floor_le"] = (
            "by\n  intro x hx1 hx2\n"
            f"  have hfl : (⌊Real.sqrt ({u})⌋ : ℝ) ≤ Real.sqrt ({u}) := Int.floor_le _\n"
            f"  have hb : Real.sqrt ({u}) ≤ {T} := Real.sqrt_le_iff.mpr "
            f"⟨by norm_num, by nlinarith [{h}]⟩\n"
            "  linarith")
        out["A1_floor_le_iff"] = (
            "by\n  intro x hx1 hx2\n"
            f"  have hu : (0:ℝ) ≤ {u} := by nlinarith [sq_nonneg ({ct._shift(p.m)})]\n"
            f"  have hz : ⌊Real.sqrt ({u})⌋ ≤ ({T} : ℤ) := Int.floor_le_iff.mpr (by\n"
            "    push_cast\n"
            f"    nlinarith [Real.sq_sqrt hu, Real.sqrt_nonneg ({u}), {h}])\n"
            f"  have hr : (⌊Real.sqrt ({u})⌋ : ℝ) ≤ {T} := by exact_mod_cast hz\n"
            "  linarith")
        out["A2_bracket"] = (
            "by\n  intro x hx1 hx2\n"
            f"  have hu : (0:ℝ) ≤ {u} := by nlinarith [sq_nonneg ({ct._shift(p.m)})]\n"
            f"  have h1 := Int.floor_le (Real.sqrt ({u}))\n"
            f"  have h2 := Int.lt_floor_add_one (Real.sqrt ({u}))\n"
            f"  nlinarith [Real.sq_sqrt hu, Real.sqrt_nonneg ({u}), {h}]")
    elif rung == "r4_floorprod":
        w = p.atoms[1].render()
        T = p.budget
        out["I0_verbatim"] = i0_verbatim(p, u, T)
        far = p.m + p.far
        umax, wmax = p.atoms[0].value(far), p.atoms[1].value(far)
        b1, b2 = ct._cap(umax - 1), ct._cap(wmax - 1)
        out["A1_prod_then_floor"] = (
            "by\n  intro x hx1 hx2\n"
            f"  have h1 : Real.sqrt ({u}) ≤ {b1} := Real.sqrt_le_iff.mpr "
            f"⟨by norm_num, by nlinarith [{h}]⟩\n"
            f"  have h2 : Real.sqrt ({w}) ≤ {b2} := Real.sqrt_le_iff.mpr "
            f"⟨by norm_num, by nlinarith [{h}]⟩\n"
            f"  have h3 : Real.sqrt ({u}) * Real.sqrt ({w}) ≤ {b1} * {b2} :=\n"
            "    mul_le_mul h1 h2 (Real.sqrt_nonneg _) (by norm_num)\n"
            f"  have hfl : (⌊Real.sqrt ({u}) * Real.sqrt ({w})⌋ : ℝ) ≤ "
            f"Real.sqrt ({u}) * Real.sqrt ({w}) := Int.floor_le _\n"
            "  linarith")
        out["A2_floor_le_iff"] = (
            "by\n  intro x hx1 hx2\n"
            f"  have hu : (0:ℝ) ≤ {u} := by nlinarith [sq_nonneg ({ct._shift(p.m)})]\n"
            f"  have hw : (0:ℝ) ≤ {w} := by nlinarith [sq_nonneg ({ct._shift(p.m)})]\n"
            f"  have hz : ⌊Real.sqrt ({u}) * Real.sqrt ({w})⌋ ≤ ({T} : ℤ) := "
            "Int.floor_le_iff.mpr (by\n"
            "    push_cast\n"
            f"    nlinarith [Real.sq_sqrt hu, Real.sq_sqrt hw, Real.sqrt_nonneg ({u}), "
            f"Real.sqrt_nonneg ({w}), {h}])\n"
            f"  have hr : (⌊Real.sqrt ({u}) * Real.sqrt ({w})⌋ : ℝ) ≤ {T} := by "
            "exact_mod_cast hz\n"
            "  linarith")
        out["A3_sqrt_mul_first"] = (
            "by\n  intro x hx1 hx2\n"
            f"  have hu : (0:ℝ) ≤ {u} := by nlinarith [sq_nonneg ({ct._shift(p.m)})]\n"
            f"  have heq : Real.sqrt ({u}) * Real.sqrt ({w}) = "
            f"Real.sqrt (({u}) * ({w})) := (Real.sqrt_mul hu ({w})).symm\n"
            f"  have hs : Real.sqrt (({u}) * ({w})) < {T + 1} := "
            f"(Real.sqrt_lt' (by norm_num)).mpr (by nlinarith [{h}])\n"
            f"  have hlt : Real.sqrt ({u}) * Real.sqrt ({w}) < {T + 1} := by "
            "rw [heq]; exact hs\n"
            f"  have hf : ⌊Real.sqrt ({u}) * Real.sqrt ({w})⌋ < ({T + 1}:ℤ) := "
            "Int.floor_lt.mpr (by push_cast; linarith)\n"
            f"  have hr : (⌊Real.sqrt ({u}) * Real.sqrt ({w})⌋ : ℝ) ≤ {T} := by\n"
            f"    have hi : ⌊Real.sqrt ({u}) * Real.sqrt ({w})⌋ ≤ ({T}:ℤ) := by omega\n"
            "    exact_mod_cast hi\n"
            "  linarith")
    return out


# ------------------------------------------------------------------ main ----

def main():
    staged = stage()
    log("staged", {k: len(v["candidates"]) for k, v in staged.items()})

    from rlmath.lean.repl_pool import ReplPool
    pool = ReplPool(n_workers=4)
    t = time.time()
    pool.warm()
    log(f"pool warm in {time.time() - t:.1f}s")
    proofs = battery_proofs()

    def battery(props, timeout_s=25.0):
        out = []
        for prop in props:
            codes = [leancode.proof_check(prop, p) for p in proofs]
            res = pool.check_many(codes, timeout_s=timeout_s)
            out.append([p for p, r in zip(proofs, res) if r.ok and r.sorries == 0])
        return out

    try:
        # ---- A: planted control, alone, first --------------------------
        t = time.time()
        killers = battery([S.CONTROL_PROP])[0]
        ctl = {"prop": S.CONTROL_PROP, "killers": killers, "alive": not killers,
               "n_battery_proofs": len(proofs), "seconds": round(time.time() - t, 2)}
        dump("gate_control.json", ctl)
        log("CONTROL:", "DEAD (gate is live) killers=" + str(killers) if killers
            else "SURVIVED -- ABORT")
        if not killers:
            return 2

        # ---- B: battery on a knob-spanning subset + one goal per rung --
        t = time.time()
        brep = {}
        for name, s in staged.items():
            sub, covered = spanning(s["candidates"])
            probes = [{"kind": "leaf", "id": f"{name}-k{c.k}-p{c.position}-{c.key[:6]}",
                       "k": c.k, "variant": c.variant, "position": c.position,
                       "knobs": c.knobs, "max_abs_coeff": c.max_abs_coeff,
                       "prop": c.prop} for c in sub]
            goal = S.goal_probe(s["problems"])
            probes.append({"kind": "goal", "id": f"{name}-k{goal.k}-goal", "k": goal.k,
                           "variant": goal.meta["variant"], "position": 0, "knobs": {},
                           "max_abs_coeff": goal.meta["max_abs_coeff"],
                           "prop": goal.goal.prop})
            kills = battery([p["prop"] for p in probes])
            for p, kl in zip(probes, kills):
                p["killers"] = kl
            brep[name] = {"n_probes": len(probes), "covered_cells": covered,
                          "probes": probes,
                          "kills": [p["id"] for p in probes if p["killers"]]}
            log(f"battery {name}: {len(probes)} props, kills="
                f"{brep[name]['kills']}")
        brep["_meta"] = {"seconds": round(time.time() - t, 2),
                         "battery_proofs": proofs}
        dump("gate_battery_ext.json", brep)

        # ---- C: witness kernel check on EVERY staged leaf --------------
        t = time.time()
        wrep = {}
        for name, s in staged.items():
            cands = s["candidates"]
            codes = [leancode.proof_check(c.prop, c.witness) for c in cands]
            res = pool.check_many(codes, timeout_s=120.0)
            rows = [{"id": f"{name}-k{c.k}-p{c.position}-{c.key[:6]}", "k": c.k,
                     "variant": c.variant, "knobs": c.knobs,
                     "ok": bool(r.ok and r.sorries == 0),
                     "errors": [m.text for m in r.errors][:2]}
                    for c, r in zip(cands, res)]
            wrep[name] = {"n": len(rows), "ok": sum(r["ok"] for r in rows),
                          "failures": [r for r in rows if not r["ok"]],
                          "rows": rows}
            log(f"witness {name}: {wrep[name]['ok']}/{len(rows)}")
        wrep["_meta"] = {"seconds": round(time.time() - t, 2)}
        dump("gate_witness_all.json", wrep)

        # ---- D: the idiom probe ----------------------------------------
        t = time.time()
        irep = {}
        for name, s in staged.items():
            # 4 instances: both variants at the smallest and largest k
            cands = s["candidates"]
            picks = []
            for k in (min(c.k for c in cands), max(c.k for c in cands)):
                for v in ("max", "min"):
                    m = [c for c in cands if c.k == k and c.variant == v]
                    if m:
                        picks.append(m[0])
            rows = []
            for c in picks:
                variant, piece = piece_of(c)
                assert variant == c.variant
                ids = idioms_for(name, piece)
                codes = [leancode.proof_check(c.prop, pf) for pf in ids.values()]
                res = pool.check_many(codes, timeout_s=60.0)
                rows.append({"id": f"{name}-k{c.k}-{c.variant}-p{c.position}",
                             "k": c.k, "variant": c.variant,
                             "closes": {n: bool(r.ok and r.sorries == 0)
                                        for n, r in zip(ids, res)},
                             "errors": {n: [m.text for m in r.errors][:1]
                                        for n, r in zip(ids, res)
                                        if not (r.ok and r.sorries == 0)}})
            names = sorted({n for r in rows for n in r["closes"]})
            irep[name] = {"instances": len(rows),
                          "summary": {n: f"{sum(r['closes'].get(n, False) for r in rows)}"
                                         f"/{sum(n in r['closes'] for r in rows)}"
                                      for n in names},
                          "rows": rows}
            log(f"idiom {name}: {irep[name]['summary']}")
        irep["_meta"] = {"seconds": round(time.time() - t, 2)}
        dump("gate_idiom.json", irep)

        # ---- E: k=32 structural validation (no battery) ----------------
        from rlmath.families import validate_problem
        t = time.time()
        vrep = {}
        for name in RUNGS:
            p = ct.build(32, SEED, 0, preset=name)
            tt = time.time()
            r = validate_problem(p, pool, check_automation=False, timeout_s=300.0)
            vrep[name] = {"id": p.id, "ok": r.ok,
                          "seconds": round(time.time() - tt, 1),
                          "goal_chars": len(p.goal.prop),
                          "failed": [(c.name, c.detail) for c in r.failed()]}
            log(f"k32 {name}: ok={r.ok} in {vrep[name]['seconds']}s "
                f"{vrep[name]['failed'][:1]}")
        vrep["_meta"] = {"seconds": round(time.time() - t, 2)}
        dump("gate_validate_k32.json", vrep)
    finally:
        pool.close()
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
