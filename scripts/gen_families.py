#!/usr/bin/env python
"""Materialize the Phase-1 family datasets + datasheets (FAMILIES.md, DIRECTION.md §5.5).

Walks the family REGISTRY over a k-grid, writes one JSONL row per generated
problem, optionally self-certifies each row through `families.validate_problem`
against a real Lean backend, and emits a per-family `DATASHEET.md`.

Usage:
  uv run python scripts/gen_families.py --family all --k-grid 2,4,8 --n 5 --seed 42 --validate
  uv run python scripts/gen_families.py --family case_tree --k-grid 2,4,8,16,32 --n 3 --no-validate
  uv run python scripts/gen_families.py --revalidate            # re-run rows written with --no-validate

Layout (`--out-dir`, default data/families/):

    data/families/<family>/k<k>.jsonl      one row per problem
    data/families/<family>/DATASHEET.md    counts, validator table, rejection stats,
                                           leaf-length distribution per k

Row shape (the datasheet is rebuilt from these rows alone, so a resumed run still
produces a complete datasheet):

    {id, family, k, seed,
     goal: {id, prop, name},
     oracle_plan: {lemmas: [{name, prop}], assembly},
     witnesses: {<lemma>: {prop, proof}},
     meta: {...},                       # whatever the generator recorded
     validation: {ok, failed: [{name, detail}], checks: {name: bool},
                  automation_checked, infra_suspect, elapsed_s}}

Resumability is `../rl/eval/run_eval.py`'s `existing_ids`, keyed on the problem
id — which is safe here precisely because generators are pure functions of
`(k, seed, idx)`: re-running the same command reproduces the same ids, so
already-written rows are skipped and a crashed run resumes exactly where it
stopped. Rows are skipped **including failed validations**: a V0–V6 failure is a
*measurement*, and silently re-rolling it on the next run would make the
datasheet's pass rate depend on run history (DIRECTION §6 evidence discipline).
`--revalidate` is the narrow escape hatch, the analog of build_bank's
`--repair`: it re-runs only rows whose validation was *skipped* (`ok: null`),
never rows that were actually measured.

`validation.ok == false` is not the same event as a broken Lean worker. The REPL
pool returns infra failures as failed results rather than raising, so any row
whose failure detail carries the pool's restart marker is flagged
`infra_suspect` and counted on its own datasheet line instead of being buried in
the V-table (same "never share a bucket" rule as core/types.Status).

Seams: every rlmath import lives inside `load_registry` / `make_backend` /
`validate_one`, so this module imports — and its logic unit-tests — with no Lean
toolchain and no family modules present. Tests stub those three functions
(tests/test_gen_families.py registers a tiny fake family and never touches Lean).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_OUT_DIR = ROOT / "data" / "families"
DEFAULT_K_GRID = "2,4,8"
DEFAULT_N = 5
DEFAULT_SEED = 42
# 2 workers, not 4: each holds a full Mathlib image in RAM and the dev box is shared.
DEFAULT_WORKERS = 2
DEFAULT_TIMEOUT_S = 120.0

ALL = "all"

# ReplWorker.check reports a dead/wedged worker as a failed VerifyResult carrying
# this prefix (rlmath.lean.repl_pool._failure). Rows tainted by it are infra, not evidence.
INFRA_MARKER = "repl timeout/restart"

# Per-problem integer counters the shipped families expose in `meta` for the
# datasheet's rejection table. Unknown families simply report no counters.
DISCARD_COUNTERS = ("discards", "resamples")

_GROUP = re.compile(r"\[.*\]$")   # "V5_leaf_resists[hb3]" -> "V5_leaf_resists"

# Test seam (see module docstring); left None in production.
FAKE_BACKEND_FACTORY: Callable[[], object] | None = None


# ---------------------------------------------------------------------------
# Lazy construction seams
# ---------------------------------------------------------------------------

def load_registry() -> dict[str, Callable[..., list]]:
    """Import every `rlmath.families` submodule so its `register()` runs, then
    snapshot REGISTRY.

    `rlmath.families.__init__` deliberately does *not* import the family modules
    (importing the package must not drag in every schema), so the registry is
    empty until someone walks the package — that walk belongs to the entry point.
    """
    import importlib
    import pkgutil

    from rlmath import families

    for mod in pkgutil.iter_modules(families.__path__):
        if not mod.name.startswith("_"):
            importlib.import_module(f"{families.__name__}.{mod.name}")
    return dict(families.REGISTRY)


def make_backend(args):
    """Construct the Lean backend (only ever called when validation is on)."""
    if args.backend == "fake":
        if FAKE_BACKEND_FACTORY is None:
            raise SystemExit("--backend fake requires FAKE_BACKEND_FACTORY (tests only)")
        return FAKE_BACKEND_FACTORY()
    from rlmath.lean import get_backend

    kw = {"n_workers": args.workers} if args.backend == "repl" else {"base_url": args.kimina_url}
    return get_backend(args.backend, **kw)


def validate_one(problem, backend, *, check_automation: bool, timeout_s: float):
    """One V0–V6 pass. Separate function so tests can stub the whole Lean side."""
    from rlmath.families import validate_problem

    return validate_problem(
        problem, backend, check_automation=check_automation, timeout_s=timeout_s
    )


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_k_grid(spec: str) -> list[int]:
    out: list[int] = []
    for part in str(spec).replace(" ", "").split(","):
        if not part:
            continue
        try:
            k = int(part)
        except ValueError:
            raise argparse.ArgumentTypeError(f"--k-grid wants integers, got {part!r}") from None
        if k < 2:
            # k=1 makes the single lemma the goal — both families reject it, and a
            # 1-leaf "decomposition" would silently pollute the size axis.
            raise argparse.ArgumentTypeError(f"--k-grid entries must be >= 2, got {k}")
        if k not in out:
            out.append(k)
    if not out:
        raise argparse.ArgumentTypeError("--k-grid is empty")
    return out


def parse_families(spec: str) -> list[str]:
    names = [p for p in str(spec).replace(" ", "").split(",") if p]
    if not names:
        raise argparse.ArgumentTypeError("--family is empty")
    return list(dict.fromkeys(names))


def resolve_families(names: Sequence[str], registry: dict) -> list[str]:
    known = sorted(registry)
    if not known:
        raise SystemExit("no families registered — is rlmath.families importable?")
    if ALL in names:
        return known
    unknown = [n for n in names if n not in registry]
    if unknown:
        raise SystemExit(f"unknown famil{'y' if len(unknown) == 1 else 'ies'}: "
                         f"{', '.join(unknown)}; registered: {', '.join(known)}")
    return list(names)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Materialize task-family datasets + datasheets (FAMILIES.md).",
    )
    p.add_argument("--family", type=parse_families, default=[ALL],
                   help=f"comma-separated family names, or {ALL!r} (default)")
    p.add_argument("--k-grid", type=parse_k_grid, default=parse_k_grid(DEFAULT_K_GRID),
                   dest="k_grid", help=f"comma-separated leaf counts (default {DEFAULT_K_GRID})")
    p.add_argument("--n", type=int, default=DEFAULT_N, help="problems per (family, k)")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED,
                   help="generator seed; output is a pure function of (k, seed)")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, dest="out_dir")
    p.add_argument("--validate", action=argparse.BooleanOptionalAction, default=True,
                   help="run V0-V6 against the Lean backend (--no-validate: generate only)")
    p.add_argument("--check-automation", action=argparse.BooleanOptionalAction, default=True,
                   dest="check_automation",
                   help="include the V0/V5 automation battery (--no-check-automation is the "
                        "fast structural pass used during schema iteration)")
    p.add_argument("--revalidate", action="store_true",
                   help="re-run rows whose validation was skipped (ok=null); measured rows "
                        "are never re-rolled")
    p.add_argument("--datasheet", action=argparse.BooleanOptionalAction, default=True,
                   help="write <family>/DATASHEET.md from the rows on disk")
    p.add_argument("--backend", choices=["repl", "kimina", "fake"], default="repl")
    p.add_argument("--kimina-url", default=None, help="default: the client default")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                   help=f"REPL pool size (default {DEFAULT_WORKERS}; each worker holds Mathlib in RAM)")
    p.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S, dest="timeout_s")
    args = p.parse_args(argv)
    if args.n < 0:
        p.error("--n must be >= 0")
    if args.revalidate and not args.validate:
        # Otherwise the run drops every skipped row and rewrites it skipped again:
        # a no-op that churns the file and reads as if something was measured.
        p.error("--revalidate re-runs skipped rows, so it needs validation on (drop --no-validate)")
    return args


# ---------------------------------------------------------------------------
# JSONL I/O and resume bookkeeping (../rl/eval/run_eval.py)
# ---------------------------------------------------------------------------

def read_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn last line from a killed run must not abort the resume
    return rows


def existing_ids(path: Path) -> set[str]:
    """Problem ids already written — failed validations INCLUDED (see module docstring)."""
    return {r["id"] for r in read_rows(path) if isinstance(r.get("id"), str)}


def append_row(path: Path, row: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def rewrite_rows(path: Path, rows: Sequence[dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def drop_unvalidated(path: Path) -> int:
    """--revalidate partition: drop rows with `validation.ok is None` so the main
    loop regenerates exactly those. Returns how many were dropped."""
    rows = read_rows(path)
    keep = [r for r in rows if (r.get("validation") or {}).get("ok") is not None]
    if len(keep) != len(rows):
        rewrite_rows(path, keep)
    return len(rows) - len(keep)


# ---------------------------------------------------------------------------
# Row construction
# ---------------------------------------------------------------------------

SKIPPED_VALIDATION: dict = {
    "ok": None, "failed": [], "checks": {}, "automation_checked": False,
    "infra_suspect": False, "elapsed_s": 0.0,
}


def validation_record(report, *, automation_checked: bool, elapsed_s: float) -> dict:
    """Flatten a ValidationReport into the row. `checks` keeps every individual
    check (V2/V5/V6 are per-lemma) because the datasheet's validator table is
    built from the rows, not from a live report."""
    failed = [{"name": c.name, "detail": c.detail} for c in report.failed()]
    return {
        "ok": bool(report.ok),
        "failed": failed,
        "checks": {c.name: bool(c.ok) for c in report.checks},
        "automation_checked": automation_checked,
        "infra_suspect": any(INFRA_MARKER in f["detail"] for f in failed),
        "elapsed_s": round(elapsed_s, 3),
    }


def problem_row(problem, validation: dict) -> dict:
    """GeneratedProblem -> JSONL row (the shape in the module docstring)."""
    return {
        "id": problem.id,
        "family": problem.family,
        "k": problem.k,
        "seed": problem.seed,
        "goal": {"id": problem.goal.id, "prop": problem.goal.prop, "name": problem.goal.name},
        "oracle_plan": {
            "lemmas": [{"name": l.name, "prop": l.prop} for l in problem.oracle_plan.lemmas],
            "assembly": problem.oracle_plan.assembly,
        },
        "witnesses": {n: {"prop": w.prop, "proof": w.proof}
                      for n, w in problem.witnesses.items()},
        "meta": problem.meta,
        "validation": validation,
    }


# ---------------------------------------------------------------------------
# Datasheet (FAMILIES.md: counts, validator table, rejection stats, leaf shapes)
# ---------------------------------------------------------------------------

def check_group(name: str) -> str:
    """`V2_proof[h3]` -> `V2_proof`: per-lemma checks aggregate into one table row."""
    return _GROUP.sub("", name)


def _table(header: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    body = [f"| {' | '.join(header)} |", f"|{'|'.join(['---'] * len(header))}|"]
    body += [f"| {' | '.join(str(c) for c in r)} |" for r in rows]
    return "\n".join(body)


def _dist(values: Sequence[int]) -> dict:
    v = sorted(values)
    return {
        "n": len(v), "min": v[0], "median": int(statistics.median(v)),
        "mean": round(sum(v) / len(v), 1), "max": v[-1], "distinct": len(set(v)),
    }


def validator_table(rows_by_k: dict[int, list[dict]]) -> tuple[list[str], list[list[str]]]:
    """(header, rows) of `passed/run` counts per check group per k.

    Counted at *check* granularity, so V5 contributes k entries per problem: the
    question FAMILIES.md asks is what fraction of leaves resist automation, not
    what fraction of problems had all their leaves resist.
    """
    ks = sorted(rows_by_k)
    groups: list[str] = []
    tally: dict[tuple[str, int], list[int]] = {}
    for k in ks:
        for row in rows_by_k[k]:
            for name, ok in (row.get("validation") or {}).get("checks", {}).items():
                g = check_group(name)
                if g not in groups:
                    groups.append(g)
                cell = tally.setdefault((g, k), [0, 0])
                cell[0] += bool(ok)
                cell[1] += 1
    header = ["check"] + [f"k={k}" for k in ks]
    out: list[list[str]] = []
    for g in sorted(groups):
        row = [g]
        for k in ks:
            n_ok, n = tally.get((g, k), (0, 0))
            row.append(f"{n_ok}/{n}" if n else "-")
        out.append(row)
    # problem-level bottom line
    row = ["problems ok"]
    for k in ks:
        rs = rows_by_k[k]
        measured = [r for r in rs if (r.get("validation") or {}).get("ok") is not None]
        row.append(f"{sum(bool(r['validation']['ok']) for r in measured)}/{len(measured)}"
                   if measured else f"0/0 (not validated, {len(rs)} rows)")
    out.append(row)
    return header, out


def rejection_stats(rows: Sequence[dict]) -> dict:
    """Generator-reported discard/rejection counters for one k.

    Families with a discard/regenerate loop record per-problem integer counters in
    `meta` (`discards` = candidates thrown away for this slot, `resamples` = inner
    constraint rejections); families whose sampler cannot fail report none, and
    that absence is itself reported rather than shown as a zero.
    """
    out: dict = {}
    for key in DISCARD_COUNTERS:
        vals = [r["meta"][key] for r in rows if isinstance(r.get("meta"), dict) and key in r["meta"]]
        if vals:
            out[key] = {"total": sum(vals), "max": max(vals), "mean": round(sum(vals) / len(vals), 2)}
    if "discards" in out:
        emitted = len(rows)
        discarded = out["discards"]["total"]
        out["candidates"] = emitted + discarded
        out["discard_rate"] = round(discarded / (emitted + discarded), 3) if emitted else 0.0
    knobs = [kb for r in rows if isinstance(r.get("meta"), dict)
             for kb in r["meta"].get("knobs", []) if isinstance(kb, dict) and "repaired" in kb]
    if knobs:
        out["repaired_frac"] = round(sum(bool(kb["repaired"]) for kb in knobs) / len(knobs), 3)
    return out


def datasheet(family: str, rows_by_k: dict[int, list[dict]], *, context: dict) -> str:
    """Render DATASHEET.md from the rows on disk (never from in-memory run state,
    so a resumed or partial materialization still documents the whole directory)."""
    ks = sorted(rows_by_k)
    all_rows = [r for k in ks for r in rows_by_k[k]]
    measured = [r for r in all_rows if (r.get("validation") or {}).get("ok") is not None]
    # Cost is summed from the rows, not taken from this process's clock: a resume
    # writes no rows and would otherwise stamp the datasheet with a 0.0s cost for
    # data that took minutes to produce.
    validation_s = sum(float((r.get("validation") or {}).get("elapsed_s") or 0.0) for r in all_rows)
    lines = [
        f"# `{family}` — dataset datasheet",
        "",
        (f"Generated by `scripts/gen_families.py` (FAMILIES.md Phase-1 contract); "
         f"datasheet rendered at {context['timestamp']} from the rows in this directory."),
        "",
        f"- seed: `{context['seed']}` (output is a pure function of `(k, seed)`)",
        (f"- validation: {'on' if context['validate'] else 'off'}"
         f" · automation battery (V0/V5): {'on' if context['check_automation'] else 'off'}"
         f" · backend: `{context['backend']}`"),
        (f"- validation cost: {validation_s:.1f}s summed over {len(measured)}/{len(all_rows)} "
         f"measured rows (this figure comes from the rows, so it survives a resume)"),
        f"- last run: `{context['command']}` ({context['elapsed_s']:.1f}s wall)",
        "",
        "## Counts",
        "",
    ]
    counts = []
    for k in ks:
        rs = rows_by_k[k]
        leaves = sum(len(r["oracle_plan"]["lemmas"]) for r in rs)
        infra = sum(bool((r.get("validation") or {}).get("infra_suspect")) for r in rs)
        counts.append([k, len(rs), leaves,
                       "yes" if all(len(r["oracle_plan"]["lemmas"]) == r["k"] for r in rs) else "NO",
                       infra])
    lines += [_table(["k", "problems", "leaves", "leaves==k", "infra-suspect rows"], counts), ""]

    lines += ["## Validator table (checks passed / checks run)", ""]
    header, vrows = validator_table(rows_by_k)
    lines += [_table(header, vrows), "",
              ("Per-lemma checks (`V2_*`, `V5_*`, `V6_*`) are counted once per lemma, so a k=8 "
               "problem contributes 8 rows to each. `problems ok` counts problems passing every "
               "check."), ""]

    lines += ["## Discard / rejection stats (generator-side, no Lean)", ""]
    stat_rows = []
    for k in ks:
        s = rejection_stats(rows_by_k[k])
        if not s:
            stat_rows.append([k, "-", "-", "-", "-", "-"])
            continue
        d = s.get("discards", {})
        rr = s.get("resamples", {})
        stat_rows.append([
            k,
            s.get("candidates", "-"),
            d.get("total", "-"),
            f"{s['discard_rate']:.1%}" if "discard_rate" in s else "-",
            rr.get("total", "-"),
            s.get("repaired_frac", "-"),
        ])
    lines += [_table(["k", "candidates", "discarded", "discard rate", "step resamples",
                      "repaired leaf frac"], stat_rows), "",
              "`-` = the family exposes no such counter (its sampler cannot fail that way).", ""]

    lines += ["## Leaf prop length distribution per k (structural flatness)", ""]
    flat_rows = []
    for k in ks:
        lens = [len(l["prop"]) for r in rows_by_k[k] for l in r["oracle_plan"]["lemmas"]]
        goals = [len(r["goal"]["prop"]) for r in rows_by_k[k]]
        if not lens:
            continue
        d = _dist(lens)
        flat_rows.append([k, d["n"], d["min"], d["median"], d["mean"], d["max"], d["distinct"],
                          _dist(goals)["mean"]])
    lines += [_table(["k", "leaves", "min", "median", "mean", "max", "distinct", "goal chars (mean)"],
                     flat_rows), "",
              ("FAMILIES.md 'Scaling requirements': leaf statements at every k must come from the "
               "same step-schema distribution — k changes how many leaves compose, not how hard "
               "one leaf is. A leaf-length distribution that drifts with k is the visible symptom "
               "of a flatness leak."), ""]

    failures: list[list[str]] = []
    for k in ks:
        for r in rows_by_k[k]:
            for f in (r.get("validation") or {}).get("failed", []):
                failures.append([k, r["id"], f["name"], (f.get("detail") or "")[:120]])
    lines += ["## Failed checks", ""]
    lines += [_table(["k", "problem", "check", "detail"], failures) if failures
              else "None — every materialized row passed every check that was run.", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _gen(registry, family: str, k: int, seed: int, n: int) -> list:
    return registry[family](k=k, seed=seed, n=n)


def main(argv=None) -> int:
    t0 = time.perf_counter()
    args = parse_args(argv)
    registry = load_registry()
    families = resolve_families(args.family, registry)
    out_dir: Path = args.out_dir
    command = "gen_families.py " + " ".join(sys.argv[1:] if argv is None else argv)

    backend = make_backend(args) if args.validate else None
    totals = {"written": 0, "skipped": 0, "ok": 0, "failed": 0, "unvalidated": 0}
    try:
        for family in families:
            fdir = out_dir / family
            fdir.mkdir(parents=True, exist_ok=True)
            for k in args.k_grid:
                path = fdir / f"k{k}.jsonl"
                if args.revalidate:
                    dropped = drop_unvalidated(path)
                    if dropped:
                        print(f"revalidate: {family} k={k}: dropped {dropped} unvalidated rows",
                              file=sys.stderr)
                done = existing_ids(path)
                problems = _gen(registry, family, k, args.seed, args.n)
                for p in problems:
                    if p.id in done:
                        totals["skipped"] += 1
                        continue
                    if backend is None:
                        record = dict(SKIPPED_VALIDATION)
                        totals["unvalidated"] += 1
                    else:
                        t1 = time.perf_counter()
                        report = validate_one(p, backend,
                                              check_automation=args.check_automation,
                                              timeout_s=args.timeout_s)
                        record = validation_record(report,
                                                   automation_checked=args.check_automation,
                                                   elapsed_s=time.perf_counter() - t1)
                        totals["ok" if record["ok"] else "failed"] += 1
                    append_row(path, problem_row(p, record))
                    totals["written"] += 1
                    print(f"[{totals['written']}] {p.id} ok={record['ok']} "
                          f"failed={[f['name'] for f in record['failed']]} "
                          f"elapsed={record['elapsed_s']}s", file=sys.stderr)
    finally:
        if backend is not None:
            backend.close()

    elapsed = time.perf_counter() - t0
    if args.datasheet:
        ctx = {
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "command": command, "seed": args.seed, "validate": args.validate,
            "check_automation": args.check_automation, "backend": args.backend,
            "elapsed_s": elapsed,
        }
        for family in families:
            fdir = out_dir / family
            rows_by_k = {}
            for path in sorted(fdir.glob("k*.jsonl")):
                rows = read_rows(path)
                if rows:
                    rows_by_k[int(path.stem[1:])] = rows
            if rows_by_k:
                (fdir / "DATASHEET.md").write_text(datasheet(family, rows_by_k, context=ctx))
                print(f"datasheet: {fdir / 'DATASHEET.md'}", file=sys.stderr)

    print(
        f"done in {elapsed:.1f}s: " + ", ".join(f"{k}={v}" for k, v in totals.items())
        + f"\nout: {out_dir}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
