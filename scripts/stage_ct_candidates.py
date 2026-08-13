#!/usr/bin/env python
"""Stage `case_tree` hardening-ladder rungs for the GPU re-calibration.

Phase 1 stayed open on case_tree for the *opposite* reason it stayed open on
bridge_chain (HANDOFF.md §1): the family measures pass@8 **0.923** over 68 leaves
× 8 DSV2 attempts — above the [0.25, 0.9] corridor ceiling, band-fit 18/68 — and
`research/case-tree-forensics.md` shows there is no lever inside the knob
support, because 68/68 successful proofs run one memorised idiom. So the fix is a
**schema ladder**, not a retune (`research/case-tree-hardening.md` is the spec),
and this script does the part that costs no GPU:

  1. materialize N deduped leaf props per rung, in a `build_bank`-ingestable
     shape, with the flat scalar provenance the pod-side regressions need
     (R3′ regresses pass@8 on `log10(max|coef|)`; R4.5 regresses `r2_sum` on its
     `split_gap` lever);
  2. run the **offline** structural report — per-rung invariant violations,
     the exhaustive `necessity_sweep` (F3: `_repair_necessity` must be a no-op at
     every k, re-established per rung and never inherited), and the
     exact-predicate audit against 60-digit `Decimal` arithmetic in **both**
     directions (under-approximation ⇒ false necessity, over ⇒ false theorem);
  3. optionally (`--with-battery`) run the **local Lean gate**: the V0/V5
     automation battery on a leaf subset plus the largest-k goal, a kernel check
     of the generator's own witness, and a **planted control** that is known to
     die. If the control survives, the run ABORTS (`ControlFailed`) — a gate that
     cannot kill anything would wave every rung through, which is the failure
     mode that costs GPU minutes.
  4. optionally (`--validate`) run the full validator V0–V6 through the shipped
     generator (R0b). Neither survey ever ran V3/V4 for any candidate.

Measurement of pass@8 is emphatically NOT done here: the frozen DSV2-7B leaf
lives on the pod. `research/case-tree-hardening.md` §7 holds the decision rule
the pod applies to the numbers.

Usage:
  uv run python scripts/stage_ct_candidates.py                      # stage only (offline)
  uv run python scripts/stage_ct_candidates.py --with-battery       # + local Lean gate
  uv run python scripts/stage_ct_candidates.py --rungs v2,r2_sum --per-rung 12
  uv run python scripts/stage_ct_candidates.py --with-battery --validate --battery-n 4

Outputs (`--out-dir`, default data/families/):

    ct_candidates.jsonl          all surviving rungs, build_bank-ingestable
    ct_battery/<rung>.jsonl      the battery/witness subset for that rung
    ct_battery/structural.json   invariants + necessity sweep + predicate audit
    ct_battery/battery.json      kill table + witness verdicts (--with-battery only)

Row shape — `formal_statement` + `id` are what `build_bank.py` reads
(`PROP_FIELDS`/`ID_FIELDS`); every other column is a flat scalar so the measured
bank can be regressed back onto the knobs that produced each leaf:

    {"formal_statement": "∀ x : ℝ, …", "id": "r2_sum-k4-3", "preset": …, "k": …,
     "variant": …, "position": …, "problem_id": …, "statement_key": …,
     "leaf_pool": …, "leaf_chars": …, "max_abs_coeff": …, "log10_max_coeff": …,
     "width": …, "curvature": …, "offset": …, "slack": …, "cap": …, "pad": …,
     "outer_const": …, "band_lo": …, "band_hi": …, "vertex": …,
     "curvature2": …, "cap2": …, "pad2": …, "split_gap": …}

Seams: `rlmath.lean` is imported lazily inside `make_pool`, so this module
imports, and its staging + structural report run, with no Lean toolchain
present. Only `--with-battery` / `--validate` need one.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from rlmath.core.types import statement_key
from rlmath.families import case_tree as ct
from rlmath.families.leaf_split import leaf_split
from rlmath.families.types import GeneratedProblem

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_OUT_DIR = ROOT / "data" / "families"
CANDIDATES_NAME = "ct_candidates.jsonl"
BATTERY_DIR_NAME = "ct_battery"
# seed 5150 is the ladder's own seed: disjoint from 42/2026 (shipped family
# datasets), 4242 (the bridge_chain retune) and 7001-7004 (the v2 hardening
# sweeps), so no candidate leaf here is one the frozen prover has been measured on.
DEFAULT_SEED = 5150
DEFAULT_K_GRID = (2, 4, 8)
DEFAULT_PER_RUNG = 30
DEFAULT_BATTERY_N = 6
DEFAULT_RUNGS = ("v2", "r1_recip", "r2_prod", "r2_sum", "r3_floor")
# 2 workers, not 4: each holds a full Mathlib image (gen_families.py's note), and
# this box is shared with sibling agents.
DEFAULT_WORKERS = 2
BATTERY_TIMEOUT_S = 25.0     # families.validate.AUTOMATION_TIMEOUT_S
WITNESS_TIMEOUT_S = 120.0
AUDIT_RADIUS = 14            # integer points either side of the vertex, per piece


# ---------------------------------------------------------------------------
# staging (pure; no Lean)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    """One leaf, with the provenance needed to join a measured pass rate back
    onto the knobs that produced it."""
    rung: str
    k: int
    variant: str
    position: int              # 1-based index of the band in its tiling
    problem_id: str
    prop: str
    witness: str
    knobs: dict
    band: tuple[int, int]
    vertex: int
    max_abs_coeff: int

    @property
    def key(self) -> str:
        return statement_key(self.prop)


def _band_slots(k: int, quota: int) -> list[int]:
    """`quota` band indices spread evenly over the k bands.

    Taking the first few bands of every problem (what the bridge_chain stager
    did, where position was recorded and conditioned on) would confound the rung
    comparison here with band *absolute position*, which is this schema's only
    k-dependence and therefore R3′'s whole subject. Even spacing samples the
    coefficient range instead of its low end.
    """
    if quota >= k:
        return list(range(k))
    if quota <= 1:
        return [k // 2]
    return sorted({round(i * (k - 1) / (quota - 1)) for i in range(quota)})


def _variant_interleaved(rung: str, k: int, seed: int, n: int) -> list[tuple[int, GeneratedProblem]]:
    """`n` problems ordered max, min, max, min … as far as the draw allows.

    `variant` is the ONE knob F1 measured as a real separator on this family
    (max 0.872 vs min 0.988, Fisher p = 0.00094), and the variant is drawn once
    per problem — so a rung sourced from two problems can end up 100% one
    variant while the control is mixed, and the ladder would then be comparing
    variants as much as schemas. Interleaving costs nothing and removes it.
    """
    pool = [(idx, ct.build(k, seed, idx, preset=rung)) for idx in range(4 * n)]
    by_variant = {v: [x for x in pool if x[1].meta["variant"] == v] for v in ct.VARIANTS}
    out: list[tuple[int, GeneratedProblem]] = []
    while len(out) < n and any(by_variant.values()):
        for v in ct.VARIANTS:
            if by_variant[v] and len(out) < n:
                out.append(by_variant[v].pop(0))
    return out


def candidates_for_rung(
    rung: str, *, k_grid: Sequence[int] = DEFAULT_K_GRID, seed: int = DEFAULT_SEED,
    per_rung: int = DEFAULT_PER_RUNG, seen: set[str] | None = None,
) -> tuple[list[Candidate], list[GeneratedProblem], dict]:
    """`per_rung` leaves, split as evenly as the k-grid allows, deduped by key.

    Leaves are drawn from several problems per k (at least four), alternating
    variants and spreading the bands, rather than from the minimum number of
    problems: it costs nothing offline and it keeps the two confounds this
    schema actually has — variant and band position — balanced across rungs.

    Dedup is **global** when `seen` is passed, so the same statement cannot be
    measured twice under two rung labels (only `v2` and a rung could ever
    collide, and only if a rung degenerated — which would itself be the finding).
    """
    per_k = max(1, per_rung // len(k_grid))
    out: list[Candidate] = []
    problems: list[GeneratedProblem] = []
    seen = seen if seen is not None else set()
    dupes = 0
    for k in k_grid:
        n_problems = max(4, -(-per_k // k))
        quota = max(1, -(-per_k // n_problems))
        taken = 0
        for idx, p in _variant_interleaved(rung, k, seed, n_problems):
            if taken >= per_k:
                break
            problems.append(p)
            _, pieces = ct.layout(k, seed, idx, preset=rung)
            for pos in _band_slots(k, quota):
                if taken >= per_k:
                    break
                lemma = p.oracle_plan.lemmas[pos]
                piece = pieces[pos]
                cand = Candidate(
                    rung=rung, k=k, variant=p.meta["variant"], position=pos + 1,
                    problem_id=p.id, prop=lemma.prop, witness=p.witnesses[lemma.name].proof,
                    knobs=p.meta["knobs"][pos], band=(piece.lo, piece.hi), vertex=piece.m,
                    max_abs_coeff=max(abs(c) for at in piece.atoms for c in at.coeffs()),
                )
                if cand.key in seen:
                    dupes += 1
                    continue
                seen.add(cand.key)
                out.append(cand)
                taken += 1
    return out, problems, {"deduped": dupes, "requested": per_rung, "emitted": len(out)}


def candidate_rows(cands: Iterable[Candidate], *, gated: bool = False) -> list[dict]:
    """`gated` records whether the local Lean gate actually ran for these rows.

    Written into every row rather than only printed, because the one gate defect
    this project has already shipped twice was a *verdict reported without a
    measurement* (research/ct-hardening-survey-a.md's `--skip-battery` flag,
    retune-notes.md §8's silently-skipped R3). A file that cannot say whether it
    was vetted invites the same mistake one consumer downstream.
    """
    rows = []
    for i, c in enumerate(cands):
        row = {
            "formal_statement": c.prop, "id": f"{c.rung}-k{c.k}-{i}",
            "battery_gated": gated,
            "preset": c.rung, "k": c.k, "variant": c.variant, "position": c.position,
            "problem_id": c.problem_id, "statement_key": c.key,
            # informational: FAMILIES.md's split is a pure function of the key, so
            # the pod can report per-pool coverage without a manifest. These rows
            # are *candidates to measure*, not a dataset, so no pool filtering is
            # applied here (see research/case-tree-hardening.md §9).
            "leaf_pool": leaf_split(c.key),
            "leaf_chars": len(c.prop),
            "band_lo": c.band[0], "band_hi": c.band[1], "vertex": c.vertex,
            "max_abs_coeff": c.max_abs_coeff,
            "log10_max_coeff": round(math.log10(max(1, c.max_abs_coeff)), 3),
        }
        for field in ("width", "curvature", "offset", "slack", "cap", "pad",
                      "curvature2", "cap2", "pad2", "outer", "split_gap"):
            if field in c.knobs:
                row["outer_const" if field == "outer" else field] = c.knobs[field]
        rows.append(row)
    return rows


def battery_subset(cands: Sequence[Candidate], n: int = DEFAULT_BATTERY_N) -> list[Candidate]:
    """The leaves the local battery runs on: both ends of the coefficient range
    at every k, and both variants where the slice has them.

    Not a random sample. Battery risk lives at the *small-coefficient* end (least
    for a tactic to chew through) while witness risk lives at the far end, so per
    k we take the smallest and largest `max_abs_coeff`, which brackets the rest.
    """
    by_k: dict[int, list[Candidate]] = {}
    for c in cands:
        by_k.setdefault(c.k, []).append(c)
    ends: dict[int, list[Candidate]] = {}
    for k in sorted(by_k):
        ranked = sorted(by_k[k], key=lambda c: (c.max_abs_coeff, c.position))
        ends[k] = [c for c in (ranked[0], ranked[-1]) if c not in ends.get(k, [])]
    # round-robin across k, so a small --battery-n still covers the whole grid
    # instead of spending itself on k=2 (which the old head-truncation did)
    picked: list[Candidate] = []
    for rank in range(2):
        for k in sorted(ends):
            if rank < len(ends[k]) and len(picked) < n:
                picked.append(ends[k][rank])
    return picked


def goal_probe(problems: Sequence[GeneratedProblem]) -> GeneratedProblem | None:
    """The largest-k problem, whose GOAL gets a V0 spot check alongside the
    leaves. A goal that falls to the battery voids the whole problem, not one
    leaf, and V0 was only ever measured on v2's piece function."""
    return max(problems, key=lambda p: p.k) if problems else None


# ---------------------------------------------------------------------------
# offline structural report (no Lean)
# ---------------------------------------------------------------------------

def structural_report(rung: str, cands: Sequence[Candidate],
                      problems: Sequence[GeneratedProblem]) -> dict:
    """Everything that can be decided without Lean, per rung.

    `predicate_audit` is the load-bearing one: it re-checks the rung's exact
    integer predicate against 60-digit reference arithmetic in both directions.
    An `under` mismatch would mean the generator claims a necessity it does not
    have (a secretly-(k−1)-leaf plan); an `over` mismatch would mean a false
    theorem. Both must be zero, per rung, before anything is measured.
    """
    r = ct.resolve_preset(rung)
    under = over = points = 0
    for k in sorted({c.k for c in cands}):
        idx = 0
        _, pieces = ct.layout(k, DEFAULT_SEED, idx, preset=r)
        for piece in pieces:
            a = ct.predicate_mismatches(piece, radius=AUDIT_RADIUS)
            under += len(a["under"])
            over += len(a["over"])
            points += a["points"]
    violations = [
        f"{p.id} piece {i}: {v}"
        for p in problems
        for i, piece in enumerate(
            ct.layout(p.k, p.seed, int(p.id.rsplit("-", 1)[1]), preset=r)[1])
        for v in r.violations(piece)
    ]
    stats = ct.leaf_stats(list(problems))
    return {
        "rung": r.name,
        "schema": r.schema_id,
        "rationale": r.rationale,
        "n_atoms": r.n_atoms,
        "extra_knobs": list(r.extra_knobs),
        "necessity_sweep": ct.necessity_sweep(r),
        "predicate_audit": {"points": points, "under": under, "over": over,
                            "ok": under == 0 and over == 0},
        "violations": violations,
        "leaf_stats": {str(k): v for k, v in stats.items()},
    }


def structural_table(reports: dict[str, dict]) -> str:
    lines = [("| rung | atoms | leaves | leaf chars (min/med/max) | max|coef| by k "
              "| repaired | knob cells | distinct leaves | spill (max/limit) "
              "| predicate audit | violations |"),
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, rep in reports.items():
        st = rep["leaf_stats"]
        chars = sorted(int(v["leaf_len_min"]) for v in st.values()) + \
            sorted(int(v["leaf_len_max"]) for v in st.values())
        med = sorted(float(v["leaf_len_mean"]) for v in st.values())
        coef = "/".join(str(v["max_abs_coeff"]) for _, v in sorted(st.items()))
        rep_frac = max(float(v["repaired_frac"]) for v in st.values())
        cells = max(int(v["distinct_knob_tuples"]) for v in st.values())
        distinct = sum(int(v["distinct_leaf_props"]) for v in st.values())
        leaves = sum(int(v["leaves"]) for v in st.values())
        sw = rep["necessity_sweep"]
        aud = rep["predicate_audit"]
        lines.append(
            f"| {name} | {rep['n_atoms']} | {leaves} "
            f"| {chars[0]}/{med[len(med) // 2]:.0f}/{chars[-1]} | {coef} | {rep_frac} "
            f"| {cells} | {distinct} | {sw['max_spill']}/{sw['threshold']} "
            f"| {'ok' if aud['ok'] else f'**{aud[chr(117) + chr(110) + chr(100) + chr(101) + chr(114)]} UNDER**'} "
            f"({aud['points']} pts) | {len(rep['violations'])} |")
    return "\n".join(lines)


def staging_table(staged: dict[str, dict]) -> str:
    lines = [("| rung | leaves | k mix | variant mix | leaf chars (min/med/max) "
              "| log10 max|coef| (min/mean/max) | deduped |"),
             "|---|---|---|---|---|---|---|"]
    for name, s in staged.items():
        cands = s["candidates"]
        chars = sorted(len(c.prop) for c in cands)
        logs = sorted(math.log10(max(1, c.max_abs_coeff)) for c in cands)
        kmix = ",".join(f"k{k}:{sum(1 for c in cands if c.k == k)}"
                        for k in sorted({c.k for c in cands}))
        vmix = ",".join(f"{v}:{sum(1 for c in cands if c.variant == v)}"
                        for v in sorted({c.variant for c in cands}))
        lines.append(
            f"| {name} | {len(cands)} | {kmix} | {vmix} "
            f"| {chars[0]}/{chars[len(chars) // 2]}/{chars[-1]} "
            f"| {logs[0]:.2f}/{sum(logs) / len(logs):.2f}/{logs[-1]:.2f} "
            f"| {s['stats']['deduped']} |")
    return "\n".join(lines)


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

    "Survives the battery" is only interesting if the leaf is provable at all,
    and a False here is a **generator bug** (a knob cell the witness template
    does not cover), not evidence about difficulty. S1 found exactly that on two
    directions by running this check.
    """
    from rlmath.core import leancode

    codes = [leancode.proof_check(prop, proof) for prop, proof in pairs]
    return [r.ok and r.sorries == 0 for r in pool.check_many(codes, timeout_s=timeout_s)]


# Positive control for the gate itself: the v1-shape band claim, which died
# 70/70 to `intros; nlinarith` (case_tree module docstring) and which both
# hardening surveys ran as their planted control. Same geometry as a real leaf,
# only the opaque wrapper removed: `-2x² - 12x + 17 ≥ 3 ⟺ (x+7)(x-1) ≤ 0`.
CONTROL_PROP = "∀ x : ℝ, -7 ≤ x → x ≤ 1 → 3 ≤ -2 * x ^ 2 - 12 * x + 17"


class ControlFailed(RuntimeError):
    """The known-dead control survived: the battery gate is not measuring."""


def gate_rungs(pool, staged: dict[str, dict], *, battery_n: int) -> dict:
    """Battery + witness verdicts per rung, behind a live planted control.

    The control runs FIRST and aborts the whole gate if it survives. A rung
    "surviving the battery" is only a measurement if the battery can kill; a
    silently-dead gate waves everything through to the pod, which is
    `research/retune-notes.md` §8's failure mode one gate over.
    """
    control = run_battery(pool, [CONTROL_PROP])[0]
    if not control:
        raise ControlFailed(
            "the v1-shape planted control survived the battery — either Mathlib no longer "
            f"closes {CONTROL_PROP!r} with `intros; nlinarith` (then this control needs "
            "replacing and every rung needs re-measuring) or the pool is not executing "
            "proofs. Refusing to report battery verdicts."
        )
    report: dict[str, dict] = {"_control": {"probes": [
        {"kind": "control", "id": "v1-shape-control", "k": 0, "position": 0,
         "prop": CONTROL_PROP, "killers": control, "witness_ok": None}],
        "kills": [], "witness_failures": []}}
    for name, s in staged.items():
        probes = [{"kind": "leaf", "id": f"{name}-k{c.k}-p{c.position}-{c.key[:6]}", "k": c.k,
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


def validate_rungs(pool, rungs: Sequence[str], *, k_grid: Sequence[int],
                   seed: int, n_per_k: int, timeout_s: float) -> dict:
    """R0b: the full validator V0–V6 through the SHIPPED generator, per rung.

    Neither survey ran V3 (stage-1 plan check) or V4 (compose + sanitizer +
    axiom audit) for any candidate, and both built their instances in their own
    probe scripts rather than through `case_tree.build`. This closes both gaps.
    Slow (a full battery per leaf), so it is opt-in and small by default.
    """
    from rlmath.families import validate_problem

    out: dict[str, dict] = {}
    for name in rungs:
        rows = []
        for k in k_grid:
            for p in ct.generate(k, seed=seed, n=n_per_k, preset=name):
                r = validate_problem(p, pool, check_automation=True, timeout_s=timeout_s)
                rows.append({"id": p.id, "k": k, "ok": r.ok,
                             "failed": [(c.name, c.detail) for c in r.failed()]})
        out[name] = {"problems": rows, "ok": all(r["ok"] for r in rows)}
    return out


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

def kill_table(report: dict) -> str:
    lines = ["| rung | probe | kind | k | pos | battery | witness |",
             "|---|---|---|---|---|---|---|"]
    for name, r in report.items():
        for p in r["probes"]:
            killers = "; ".join(p["killers"]) if p["killers"] else "survives"
            wit = {True: "ok", False: "**FAILED**", None: "-"}[p["witness_ok"]]
            lines.append(f"| {name} | {p['id']} | {p['kind']} | {p['k']} | {p['position'] or '-'} "
                         f"| {'**DEAD** — ' + killers if p['killers'] else killers} | {wit} |")
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
    p.add_argument("--rungs", default=",".join(DEFAULT_RUNGS),
                   help=f"comma-separated (default: {', '.join(DEFAULT_RUNGS)}; "
                        f"all available: {', '.join(sorted(ct.RUNGS))})")
    p.add_argument("--k-grid", default=",".join(str(k) for k in DEFAULT_K_GRID), dest="k_grid")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--per-rung", type=int, default=DEFAULT_PER_RUNG, dest="per_rung")
    p.add_argument("--battery-n", type=int, default=DEFAULT_BATTERY_N, dest="battery_n",
                   help="leaves per rung handed to the local battery")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, dest="out_dir")
    p.add_argument("--out", type=Path, default=None,
                   help=f"candidates file (default: <out-dir>/{CANDIDATES_NAME})")
    p.add_argument("--with-battery", action="store_true", dest="with_battery",
                   help="run the local automation battery + witness kernel check (needs Lean)")
    p.add_argument("--validate", action="store_true",
                   help="also run the full validator V0-V6 per rung (R0b; slow, needs Lean)")
    p.add_argument("--validate-n", type=int, default=1, dest="validate_n",
                   help="problems per k for --validate (default 1)")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    names = [n.strip() for n in args.rungs.split(",") if n.strip()]
    for n in names:
        ct.resolve_preset(n)   # fail fast on a typo, before any generation
    k_grid = tuple(int(k) for k in args.k_grid.split(",") if k.strip())

    staged: dict[str, dict] = {}
    seen: set[str] = set()     # global dedup across rungs, by statement_key
    for name in names:
        cands, problems, stats = candidates_for_rung(
            name, k_grid=k_grid, seed=args.seed, per_rung=args.per_rung, seen=seen)
        staged[name] = {"candidates": cands, "problems": problems, "stats": stats}

    reports = {name: structural_report(name, s["candidates"], s["problems"])
               for name, s in staged.items()}

    print("## staged (offline)\n", file=sys.stderr)
    print(staging_table(staged), file=sys.stderr)
    print("\n## structural report (offline)\n", file=sys.stderr)
    print(structural_table(reports), file=sys.stderr)

    battery_dir = args.out_dir / BATTERY_DIR_NAME
    battery_dir.mkdir(parents=True, exist_ok=True)
    (battery_dir / "structural.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2))

    # An invariant violation, a failed predicate audit or a spill at the
    # necessity threshold is a GENERATOR bug, not a difficulty finding: staging
    # such a rung would put an unsound or secretly-(k-1)-leaf statement on the pod
    # under a hardening label. Refuse before any Lean runs.
    fatal = {n: {"violations": r["violations"][:5],
                 "predicate_audit": r["predicate_audit"],
                 "necessity_sweep": r["necessity_sweep"]}
             for n, r in reports.items()
             if r["violations"] or not r["predicate_audit"]["ok"]
             or not r["necessity_sweep"]["ok"]}
    if fatal:
        for n, why in fatal.items():
            print(f"FATAL {n}: {json.dumps(why, ensure_ascii=False)}", file=sys.stderr)
        return 2

    for name, s in staged.items():
        write_jsonl(battery_dir / f"{name}.jsonl",
                    candidate_rows(battery_subset(s["candidates"], args.battery_n),
                                   gated=args.with_battery))

    dropped: dict[str, dict] = {}
    if args.with_battery or args.validate:
        pool = make_pool(args.workers)
        try:
            pool.warm()
            if args.with_battery:
                report = gate_rungs(pool, staged, battery_n=args.battery_n)
                (battery_dir / "battery.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2))
                print("\n## local battery + witness gate\n", file=sys.stderr)
                print(kill_table(report), file=sys.stderr)
                dropped = {n: r for n, r in report.items()
                           if r["kills"] or r["witness_failures"]}
            if args.validate:
                vrep = validate_rungs(pool, list(staged), k_grid=k_grid, seed=args.seed,
                                      n_per_k=args.validate_n, timeout_s=180.0)
                (battery_dir / "validate.json").write_text(
                    json.dumps(vrep, ensure_ascii=False, indent=2))
                print("\n## validator V0-V6 (R0b)\n", file=sys.stderr)
                for n, r in vrep.items():
                    print(f"  {n}: {'ok' if r['ok'] else 'FAILED'} "
                          f"({sum(x['ok'] for x in r['problems'])}/{len(r['problems'])})",
                          file=sys.stderr)
                    if not r["ok"]:
                        dropped.setdefault(n, {"kills": [], "witness_failures": []})
        finally:
            pool.close()
        for n in dropped:
            staged.pop(n, None)

    rows = [r for s in staged.values()
            for r in candidate_rows(s["candidates"], gated=args.with_battery)]
    out = args.out or (args.out_dir / CANDIDATES_NAME)
    write_jsonl(out, rows)
    print(f"\nwrote {len(rows)} rows -> {out}", file=sys.stderr)
    print(f"rungs staged: {', '.join(staged) or '(none)'}", file=sys.stderr)
    if dropped:
        print(f"rungs DROPPED by the local gate: {', '.join(dropped)}", file=sys.stderr)
    elif not args.with_battery:
        print("battery gate NOT run (--with-battery); these rows are structurally "
              "checked but Lean-unvetted", file=sys.stderr)
    return 1 if dropped else 0


if __name__ == "__main__":
    sys.exit(main())
