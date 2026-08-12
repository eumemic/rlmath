#!/usr/bin/env python
"""Stage bridge_chain difficulty-preset candidates for the GPU re-calibration.

Phase 1 stayed open on one finding (OVERNIGHT.md, 2026-08-12): bridge_chain's
per-leaf **flatness passes** (k=4 0.125 vs k=8 0.129, within 0.004) but the
**level fails** — ~0.13 pass@8 sits below the [0.25, 0.9] corridor floor. The fix
is a knob retune, and the retune is decided by measurement, not by argument. This
script does the part that can be done without a GPU:

  1. materialize N deduped leaf props per candidate preset, in a `build_bank`
     ingestable shape, so the pod runs one command and gets measured pass@8;
  2. run the **local** automation battery (V0/V5, `families.validate`) plus a
     kernel check of the generator's own witness on a handful of leaves per
     preset — a preset whose leaves fall to a bare tactic is dropped *here*,
     before it spends GPU minutes, and a preset whose witness stops checking is
     a generator bug, not a difficulty result.

Measurement of pass@8 is emphatically NOT done here: the frozen DSV2-7B leaf
lives on the pod. This script stages; `research/retune-notes.md` holds the
decision rule the pod applies to the numbers.

Usage:
  uv run python scripts/stage_retune_candidates.py                     # stage only (offline)
  uv run python scripts/stage_retune_candidates.py --with-battery      # + local Lean gate
  uv run python scripts/stage_retune_candidates.py --presets v2,e2_flatstep --per-preset 12

Outputs (`--out-dir`, default data/families/):

    retune_candidates.jsonl          all surviving presets, build_bank-ingestable
    retune_battery/<preset>.jsonl    the battery/witness subset for that preset
    retune_battery/battery.json      kill table + witness verdicts (--with-battery only)

Row shape of the candidates file — `formal_statement` + `id` are what
`build_bank.py` reads (`PROP_FIELDS`/`ID_FIELDS`); every other column is flat
scalar provenance so the measured bank can be regressed back onto the knobs that
produced each leaf (that regression is what produced the presets in the first
place — see research/retune-notes.md §2):

    {"formal_statement": "∀ x y z : ℝ, …", "id": "e2_flatstep-k4-3",
     "preset": …, "k": …, "problem_id": …, "position": …, "statement_key": …,
     "delta": …, "es_left": …, "c_left": …, "d_left": …, "o_left": …,
     "c_right": …, "d_right": …, "o_right": …, "func_left": …, "func_right": …}

Seams: `rlmath.lean` is imported lazily inside `make_pool`, so this module
imports, and its staging logic runs, with no Lean toolchain present. Only
`--with-battery` needs one.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from rlmath.core.types import statement_key
from rlmath.families import bridge_chain as bc
from rlmath.families.types import GeneratedProblem

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_OUT_DIR = ROOT / "data" / "families"
CANDIDATES_NAME = "retune_candidates.jsonl"
BATTERY_DIR_NAME = "retune_battery"
# seed 4242 is the retune's own seed: disjoint from the shipped datasets (42,
# 2026) and from the v2 hardening sweeps (7001-7004), so no candidate leaf here
# is a leaf the frozen leaf prover has already been measured on.
DEFAULT_SEED = 4242
DEFAULT_K_GRID = (2, 4, 8)
DEFAULT_PER_PRESET = 30
DEFAULT_BATTERY_N = 6
# 2 workers, not 4: each holds a full Mathlib image (gen_families.py's note).
DEFAULT_WORKERS = 2
BATTERY_TIMEOUT_S = 25.0     # families.validate.AUTOMATION_TIMEOUT_S
WITNESS_TIMEOUT_S = 120.0


# ---------------------------------------------------------------------------
# staging (pure; no Lean)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    """One leaf, with the provenance needed to join a measured pass rate back
    onto the knobs that produced it."""
    preset: str
    k: int
    position: int              # 1-based index of the step in its chain
    problem_id: str
    prop: str
    witness: str

    @property
    def key(self) -> str:
        return statement_key(self.prop)


def _problems_for(preset: str, k: int, seed: int, n_leaves: int) -> list[GeneratedProblem]:
    """Enough problems to source `n_leaves` leaves at this k (k leaves each)."""
    n = max(1, -(-n_leaves // k))
    return bc.generate(k, seed=seed, n=n, preset=preset)


def candidates_for_preset(
    preset: str, *, k_grid: Sequence[int] = DEFAULT_K_GRID, seed: int = DEFAULT_SEED,
    per_preset: int = DEFAULT_PER_PRESET,
) -> tuple[list[Candidate], list[GeneratedProblem], dict]:
    """`per_preset` leaves, split as evenly as the k-grid allows, deduped by key.

    Leaves are taken in (problem, chain-position) order, so when `per_preset/|k|`
    is not a multiple of k the tail of a slice slightly over-weights early
    positions. That bias is *recorded, not hidden*: every row carries its
    `position` and `es_left`, which is the knob the measurement is most sensitive
    to (research/retune-notes.md §2), so the pod-side analysis can condition on
    it instead of assuming a uniform position mix.
    """
    per_k = max(1, per_preset // len(k_grid))
    out: list[Candidate] = []
    problems: list[GeneratedProblem] = []
    seen: set[str] = set()
    dupes = 0
    for k in k_grid:
        taken = 0
        for p in _problems_for(preset, k, seed, per_k):
            problems.append(p)
            for pos, lemma in enumerate(p.oracle_plan.lemmas, start=1):
                if taken >= per_k:
                    break
                cand = Candidate(preset=preset, k=k, position=pos, problem_id=p.id,
                                 prop=lemma.prop, witness=p.witnesses[lemma.name].proof)
                if cand.key in seen:
                    dupes += 1
                    continue
                seen.add(cand.key)
                out.append(cand)
                taken += 1
    return out, problems, {"deduped": dupes, "requested": per_preset, "emitted": len(out)}


def _knobs_of(prop: str) -> dict:
    """Flat scalar knob columns parsed back out of the rendered leaf.

    Parsed from the text rather than read from `meta` on purpose: the emitted
    row must describe the statement the leaf prover actually sees, so a
    rendering bug shows up as a knob mismatch instead of travelling silently
    into the analysis.
    """
    body = prop.removeprefix(bc.BINDER)
    lhs, rhs = body.split(" ≤ ")

    def side(term: str) -> dict:
        c, rest = term.split(" * ", 1)
        mono, rest = rest.split(" + ", 1)
        d, rest = rest.split(" * ", 1)
        func = "sqrt" if "Real.sqrt" in rest else "log"
        o = rest.rsplit(" + ", 1)[1]
        exps = [int(part.split(" ^ ")[1]) for part in mono.split(" * ")]
        return {"c": int(c), "d": int(d), "o": int(o), "func": func, "es": sum(exps)}

    left, right = side(lhs), side(rhs)
    return {
        "delta": right["es"] - left["es"], "es_left": left["es"], "es_right": right["es"],
        "c_left": left["c"], "d_left": left["d"], "o_left": left["o"],
        "c_right": right["c"], "d_right": right["d"], "o_right": right["o"],
        "func_left": left["func"], "func_right": right["func"],
    }


def candidate_rows(cands: Iterable[Candidate]) -> list[dict]:
    rows = []
    for i, c in enumerate(cands):
        row = {"formal_statement": c.prop, "id": f"{c.preset}-k{c.k}-{i}",
               "preset": c.preset, "k": c.k, "position": c.position,
               "problem_id": c.problem_id, "statement_key": c.key}
        row.update(_knobs_of(c.prop))
        rows.append(row)
    return rows


def battery_subset(cands: Sequence[Candidate], n: int = DEFAULT_BATTERY_N) -> list[Candidate]:
    """The leaves the local battery runs on: both ends of the within-chain
    difficulty gradient at every k.

    Not a random sample. Battery risk lives at the *small-monomial* end (fewest
    factors for a tactic to chew through — and, for `e3_lowdeg`, the exponent-0
    factors a normalizing tactic could simplify away), while witness risk lives
    at the far end. So per k we take the smallest and the largest `es_left`,
    which brackets everything in between.
    """
    by_k: dict[int, list[Candidate]] = {}
    for c in cands:
        by_k.setdefault(c.k, []).append(c)
    picked: list[Candidate] = []
    for k in sorted(by_k):
        ranked = sorted(by_k[k], key=lambda c: (_knobs_of(c.prop)["es_left"], c.position))
        for c in (ranked[0], ranked[-1]):
            if c not in picked:
                picked.append(c)
    return picked[:n] if n < len(picked) else picked


def goal_probe(problems: Sequence[GeneratedProblem]) -> GeneratedProblem | None:
    """The largest-k problem, whose GOAL gets a V0 spot check alongside the leaves.

    V0 held at every k for v2 (research/family-v2-hardening.md §4), but an easier
    preset moves the endpoints too, and a goal that falls to the battery voids the
    whole problem, not just one leaf.
    """
    return max(problems, key=lambda p: p.k) if problems else None


# ---------------------------------------------------------------------------
# local Lean gate (--with-battery)
# ---------------------------------------------------------------------------

def make_pool(workers: int):
    """Lazy seam: importing this module must not require a Lean toolchain."""
    from rlmath.lean.repl_pool import ReplPool

    return ReplPool(n_workers=workers)


def run_battery(pool, props: Sequence[str], *, timeout_s: float = BATTERY_TIMEOUT_S) -> list[list[str]]:
    """Per prop, the battery proofs that CLOSED it (empty = survives).

    Same battery constant as `validate.py` (10 tactics × {bare, intros-first}),
    so extending the battery there strengthens this gate too.
    """
    from rlmath.core import leancode
    from rlmath.families.validate import battery_proofs

    proofs = battery_proofs()
    out: list[list[str]] = []
    for prop in props:
        codes = [leancode.proof_check(prop, p) for p in proofs]
        results = pool.check_many(codes, timeout_s=timeout_s)
        out.append([p for p, r in zip(proofs, results) if r.ok and r.sorries == 0])
    return out


def check_witnesses(pool, pairs: Sequence[tuple[str, str]],
                    *, timeout_s: float = WITNESS_TIMEOUT_S) -> list[bool]:
    """Kernel-check each (prop, generator witness).

    The other half of the empirical loop in research/family-v2-hardening.md §2:
    "survives the battery" is only interesting if the leaf is provable at all.
    A False here is a generator bug (a knob range the witness template does not
    cover), not evidence about difficulty.
    """
    from rlmath.core import leancode

    codes = [leancode.proof_check(prop, proof) for prop, proof in pairs]
    return [r.ok and r.sorries == 0 for r in pool.check_many(codes, timeout_s=timeout_s)]


# Positive control for the gate itself: the uniformly-rising step that killed 16
# v1 leaves (research/family-v2-hardening.md §2, BC-v1/BC-C). If THIS survives,
# the battery is not running — a gate that cannot kill anything would wave every
# preset through, which is the failure mode that costs GPU time.
CONTROL_PROP = (
    f"{bc.BINDER}4 * x ^ 1 * y ^ 1 * z ^ 1 + 2 * Real.sqrt (x ^ 1 * y ^ 1 * z ^ 1) + 3"
    " ≤ 9 * x ^ 2 * y ^ 1 * z ^ 1 + 7 * Real.sqrt (x ^ 2 * y ^ 1 * z ^ 1) + 5"
)


class ControlFailed(RuntimeError):
    """The known-dead control survived: the battery gate is not measuring."""


def gate_presets(pool, staged: dict[str, dict], *, battery_n: int) -> dict:
    """Battery + witness verdicts per preset. Returns the report; killed presets
    are the ones with a non-empty `kills` list on any probe."""
    control = run_battery(pool, [CONTROL_PROP])[0]
    if not control:
        raise ControlFailed(
            "the uniformly-rising control survived the battery — either Mathlib no longer "
            "closes it with `intros; gcongr <;> linarith` (then this control needs replacing "
            "and every preset needs re-measuring) or the pool is not executing proofs"
        )
    report: dict[str, dict] = {"_control": {"probes": [
        {"kind": "control", "id": "rising-step-control", "k": 0, "position": 0,
         "prop": CONTROL_PROP, "killers": control, "witness_ok": None}],
        "kills": [], "witness_failures": []}}
    for name, s in staged.items():
        probes = [{"kind": "leaf", "id": f"{name}-k{c.k}-p{c.position}", "k": c.k,
                   "position": c.position, "prop": c.prop, "witness": c.witness}
                  for c in battery_subset(s["candidates"], battery_n)]
        goal = goal_probe(s["problems"])
        if goal is not None:
            probes.append({"kind": "goal", "id": f"{name}-k{goal.k}-goal", "k": goal.k,
                           "position": 0, "prop": goal.goal.prop, "witness": None})
        kills = run_battery(pool, [p["prop"] for p in probes])
        leaf_probes = [p for p in probes if p["witness"]]
        ok = check_witnesses(pool, [(p["prop"], p["witness"]) for p in leaf_probes])
        witness_ok = dict(zip((p["id"] for p in leaf_probes), ok))
        for probe, killers in zip(probes, kills):
            probe["killers"] = killers
            probe["witness_ok"] = witness_ok.get(probe["id"])
            probe.pop("witness", None)
        report[name] = {
            "probes": probes,
            "kills": [p["id"] for p in probes if p["killers"]],
            "witness_failures": [p["id"] for p in probes if p["witness_ok"] is False],
        }
    return report


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

def kill_table(report: dict) -> str:
    lines = ["| preset | probe | kind | k | pos | battery | witness |",
             "|---|---|---|---|---|---|---|"]
    for name, r in report.items():
        for p in r["probes"]:
            killers = "; ".join(p["killers"]) if p["killers"] else "survives"
            wit = {True: "ok", False: "**FAILED**", None: "-"}[p["witness_ok"]]
            lines.append(f"| {name} | {p['id']} | {p['kind']} | {p['k']} | {p['position'] or '-'} "
                         f"| {'**DEAD** — ' + killers if p['killers'] else killers} | {wit} |")
    return "\n".join(lines)


def staging_table(staged: dict[str, dict]) -> str:
    lines = ["| preset | leaves | k mix | leaf chars (min/med/max) | es_left (min/mean/max) "
             "| discards (mean/max) | invariant violations |", "|---|---|---|---|---|---|---|"]
    for name, s in staged.items():
        cands = s["candidates"]
        chars = sorted(len(c.prop) for c in cands)
        es = sorted(_knobs_of(c.prop)["es_left"] for c in cands)
        kmix = ",".join(f"k{k}:{sum(1 for c in cands if c.k == k)}"
                        for k in sorted({c.k for c in cands}))
        disc = [p.meta["discards"] for p in s["problems"]]
        lines.append(
            f"| {name} | {len(cands)} | {kmix} | {chars[0]}/{chars[len(chars) // 2]}/{chars[-1]} "
            f"| {es[0]}/{sum(es) / len(es):.1f}/{es[-1]} "
            f"| {sum(disc) / len(disc):.1f}/{max(disc)} | {len(s['violations'])} |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def write_jsonl(path: Path, rows: Sequence[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--presets", default=",".join(bc.PRESETS),
                   help=f"comma-separated (default: all — {', '.join(bc.PRESETS)})")
    p.add_argument("--k-grid", default=",".join(str(k) for k in DEFAULT_K_GRID), dest="k_grid")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--per-preset", type=int, default=DEFAULT_PER_PRESET, dest="per_preset")
    p.add_argument("--battery-n", type=int, default=DEFAULT_BATTERY_N, dest="battery_n",
                   help="leaves per preset handed to the local battery")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, dest="out_dir")
    p.add_argument("--with-battery", action="store_true", dest="with_battery",
                   help="run the local automation battery + witness kernel check (needs Lean)")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    names = [n.strip() for n in args.presets.split(",") if n.strip()]
    for n in names:
        bc.resolve_preset(n)   # fail fast on a typo, before any generation
    k_grid = tuple(int(k) for k in args.k_grid.split(",") if k.strip())

    staged: dict[str, dict] = {}
    for name in names:
        cands, problems, stats = candidates_for_preset(
            name, k_grid=k_grid, seed=args.seed, per_preset=args.per_preset)
        violations = [f"{p.id}: {v}" for p in problems for v in bc.check_preset_invariants(p)]
        staged[name] = {"candidates": cands, "problems": problems,
                        "stats": stats, "violations": violations}

    print("## staged (offline)\n", file=sys.stderr)
    print(staging_table(staged), file=sys.stderr)
    hard = {n: s["violations"] for n, s in staged.items() if s["violations"]}
    if hard:
        # An invariant violation is a generator bug, not a difficulty finding:
        # staging a leaf that breaks the congruence gate would put a
        # battery-soluble statement on the pod under an "easier preset" label.
        for n, v in hard.items():
            print(f"FATAL {n}: {v[:5]}", file=sys.stderr)
        return 2

    battery_dir = args.out_dir / BATTERY_DIR_NAME
    for name, s in staged.items():
        write_jsonl(battery_dir / f"{name}.jsonl",
                    candidate_rows(battery_subset(s["candidates"], args.battery_n)))

    dropped: dict[str, dict] = {}
    if args.with_battery:
        pool = make_pool(args.workers)
        try:
            pool.warm()
            report = gate_presets(pool, staged, battery_n=args.battery_n)
        finally:
            pool.close()
        (battery_dir / "battery.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print("\n## local battery + witness gate\n", file=sys.stderr)
        print(kill_table(report), file=sys.stderr)
        dropped = {n: r for n, r in report.items() if r["kills"] or r["witness_failures"]}
        for n in dropped:
            staged.pop(n, None)

    rows = [r for s in staged.values() for r in candidate_rows(s["candidates"])]
    out = args.out_dir / CANDIDATES_NAME
    write_jsonl(out, rows)
    print(f"\nwrote {len(rows)} rows -> {out}", file=sys.stderr)
    print(f"presets staged: {', '.join(staged) or '(none)'}", file=sys.stderr)
    if dropped:
        print(f"presets DROPPED by the local gate: {', '.join(dropped)}", file=sys.stderr)
    elif not args.with_battery:
        print("battery gate NOT run (--with-battery); these rows are unvetted", file=sys.stderr)
    return 1 if dropped else 0


if __name__ == "__main__":
    sys.exit(main())
