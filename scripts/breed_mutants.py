#!/usr/bin/env python
"""Breed mutants of in-band bank statements — corridor-widening source 2 (FAMILIES.md).

FAMILIES.md, "Corridor widening (v2 leaf sources)": *(2) mutation breeding —
perturb constants/exponents/bounds of known in-band statements and re-measure
every mutant's pass@8 (mutants inherit the corridor's neighborhood, never
membership; measurement is mandatory).*

This script is the "in-band statements → candidate file" half; the perturbation
rules and their justification live in `rlmath.families.mutate`. It reads band
rows (`pass_rate ∈ [--band-lo, --band-hi]`, DIRECTION.md §5.4) out of a bank
JSONL **read-only**, generates mutants, gates each one on Lean elaboration, and
writes `data/bank/mutants_candidates.jsonl` — a candidate file whose only
purpose is to be measured by `scripts/build_bank.py`. Nothing here produces a
pass rate, and no row it writes may be treated as an in-band statement.

Usage:
  uv run python scripts/breed_mutants.py --per-parent 4 --seed 42
  uv run python scripts/breed_mutants.py --parent-pool train --coherent-split
  uv run python scripts/breed_mutants.py --limit-parents 3 --workers 2   # smoke

Then measure (this is the whole point — mutants are candidates, not leaves):

  uv run python scripts/build_bank.py \\
      --dataset json --data-files data/bank/mutants_candidates.jsonl --split train \\
      --out data/bank/bank_mutants.jsonl --k 8 \\
      --leaf-base-url ... --leaf-model deepseek-ai/DeepSeek-Prover-V2-7B \\
      --leaf-template deepseek-prover-v2-non-cot

`build_bank` ingest (checked against its `extract_prop`/`source_id`, not assumed):
rows carry two alias fields on top of the canonical schema so **no new flags are
needed** — `statement` (second entry of `build_bank.PROP_FIELDS`; its
`theorem_to_prop` passes an already-closed proposition through unchanged) and
`id` (first entry of `ID_FIELDS`, so the bank row's `source_id` becomes
`json#mutant:<parent_key>#<key>` instead of a positional `json#7` that would
destroy the parent linkage). `--prop-field prop` also works if the aliases are
ever dropped. The aliases are asserted equal to the canonical fields at write
time, so the two cannot drift.

Why elaboration-gate here when build_bank elaborates anyway: a mutant that fails
to elaborate is a wasted *bank row* and, on a GPU run, a wasted scheduling slot.
The gate is local CPU Lean, which is the cheap resource.

Truth and triviality are NOT gated, by design. Jitter breaks truth (false mutant
→ measured `pass_rate` 0.0) and can make a hypothesis contradictory (vacuous
mutant → trivially provable → measured `pass_rate` 1.0). The [0.25, 0.9] band is
two-sided, so the two dominant mutation pathologies land on opposite sides of it
and the mandatory re-measurement filters both. `--battery-filter` optionally
spends local Lean time to kill the trivial half before it costs GPU time (it
runs the V0/V5 automation battery from `families.validate` — the corridor's
floor, FAMILIES.md).

Measured on this box, 2026-08-12 (ReplPool n_workers=2, Mathlib @ 4.34.0-rc1):
elaboration gate **421/421 candidates passed** over all 37 DSV2 band parents —
numeral-for-numeral substitution essentially never breaks elaboration, so that
gate is insurance rather than a filter. The battery is where the yield is:
~12 s/prop (20 checks), killing 43/176 elaborating mutants (`by simp` 24,
`by norm_num` 12, `by intros; linarith` 6, `by aesop` 1 — the `linarith` ones are
the predicted vacuity pathology, e.g. a `bound_shift` turning `0 < d ∧ d < 1`
into `2 < d ∧ d < 1`). It also finds that **6 of the 37 band parents are
themselves battery-closable** (`999 + 10 = 1009`, `(10:ℝ)^(Real.logb 10 7) = 7`,
…): the bank's band filter is the corridor's ceiling only, so `--battery-filter`
applies the floor to parents as well and skips those lineages. Rejections and
their reasons go to `<out>.rejects.jsonl` (FAMILIES.md: rejection reasons
logged, not just counted).

Leaf-split contract (FAMILIES.md "Leaf-disjointness contract", BINDING): every
pool decision in this file goes through `families.leaf_split.leaf_split`, never
a manifest. Mutants get fresh `statement_key`s and therefore *independent*
membership, which is what that module's docstring specifies — and which leaves a
near-duplicate channel open (a one-constant mutant of a TRAIN leaf can land in
EVAL). Rows record `parent_split` and `split` so either policy can be applied
downstream without re-measuring; `--parent-pool` refuses mixed parent draws and
`--coherent-split` drops cross-pool mutants for callers who want the intersection
of both policies. See the run's flag block for the open decision.

Seams: every `rlmath.lean` import lives inside `make_backend`, so this module
imports — and its logic unit-tests — with no Lean toolchain present. Tests inject
a stub through `--backend fake` + `FAKE_BACKEND_FACTORY` (same seam as
scripts/build_bank.py).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path

from rlmath.core.leancode import proof_check, statement_check
from rlmath.families.leaf_split import leaf_split
from rlmath.families.mutate import Mutant, mutants

ROOT = Path(__file__).resolve().parent.parent

# DIRECTION.md §5.4: the delegability band the bank is mined at.
BAND_LO, BAND_HI = 0.25, 0.9
DEFAULT_BANK = ROOT / "data" / "bank" / "bank_dsv2.jsonl"
DEFAULT_OUT = ROOT / "data" / "bank" / "mutants_candidates.jsonl"

# Test seam (see module docstring). None in production; --backend fake errors out.
FAKE_BACKEND_FACTORY: Callable[[], object] | None = None


# ---------------------------------------------------------------------------
# Bank I/O (read-only) and parent selection
# ---------------------------------------------------------------------------

def read_rows(path: Path) -> list[dict]:
    """Tolerant JSONL read — a torn last line from a killed run must not abort
    a resume (build_bank.read_rows, same rule)."""
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
                continue
    return rows


def band_parents(rows: Sequence[dict], lo: float = BAND_LO, hi: float = BAND_HI) -> list[dict]:
    """Rows whose MEASURED pass rate sits in the band.

    `pass_rate is None` means unmeasured (build_bank.summarize_leaf keeps that
    distinction deliberately) and is never treated as 0.0.
    """
    out = []
    for r in rows:
        pr = r.get("pass_rate")
        if isinstance(pr, (int, float)) and not isinstance(pr, bool) and lo <= pr <= hi:
            if r.get("prop"):
                out.append(r)
    return out


def all_keys(paths: Sequence[Path]) -> set[str]:
    """Every statement_key already measured anywhere — a mutant equal to one of
    them is a re-measurement, not a new candidate."""
    keys: set[str] = set()
    for p in paths:
        for r in read_rows(p):
            k = r.get("statement_key")
            if isinstance(k, str):
                keys.add(k)
    return keys


# ---------------------------------------------------------------------------
# Row construction
# ---------------------------------------------------------------------------

def candidate_row(m: Mutant, parent: dict, seed: int) -> dict:
    """The emitted row: canonical fields + the two build_bank ingest aliases.

    `parent_split`/`split` are recorded rather than enforced — see the
    leaf-split note in the module docstring.
    """
    row = m.as_row()
    parent_key = row["parent_key"]
    row.update(
        parent_pass_rate=parent.get("pass_rate"),
        parent_source_id=parent.get("source_id"),
        parent_leaf_id=parent.get("leaf_id"),
        parent_split=leaf_split(parent_key),
        split=leaf_split(row["statement_key"]),
        seed=seed,
        # build_bank ingest aliases (module docstring). Asserted, not assumed.
        statement=row["prop"],
        id=f"{row['source_id']}#{row['statement_key']}",
    )
    assert row["statement"] == row["prop"]
    assert row["id"].startswith(row["source_id"])
    return row


def reject_row(m: Mutant, parent: dict, seed: int, reason: str) -> dict:
    """A gated-out candidate, with its reason.

    FAMILIES.md requires rejection reasons to be logged, not just counted: the
    op-kind → rejection-reason table is how the next iteration of the mutation
    schema gets designed, and a silently-dropped candidate is a measurement you
    cannot redo. Written to a sidecar so the candidate file itself stays a clean
    build_bank input.
    """
    row = candidate_row(m, parent, seed)
    row.pop("statement", None)   # not a build_bank input; do not let it be ingested
    row.pop("id", None)
    row["reject_reason"] = reason
    return row


def append_row(path: Path, row: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _display_path(p: Path) -> str:
    """Repo-relative when it is inside the repo, absolute otherwise — a
    `../../../tmp/...` in a copy-pasteable command line is a footgun."""
    try:
        return str(p.resolve().relative_to(ROOT))
    except ValueError:
        return str(p.resolve())


# ---------------------------------------------------------------------------
# Lean gates
# ---------------------------------------------------------------------------

def make_backend(args):
    """Lazy construction through rlmath.lean's factory — the one place a backend
    name becomes a LeanBackend (scripts/build_bank.py, same pattern)."""
    if args.backend == "fake":
        if FAKE_BACKEND_FACTORY is None:
            raise SystemExit("--backend fake requires FAKE_BACKEND_FACTORY (tests only)")
        return FAKE_BACKEND_FACTORY()
    from rlmath.lean import get_backend

    kw = {"n_workers": args.workers} if args.backend == "repl" else {"base_url": args.kimina_url}
    return get_backend(args.backend, **kw)


def elaborates(props: Sequence[str], backend, timeout_s: float) -> list[bool]:
    """statement_check policy verbatim (core/leancode): ok AND exactly one sorry."""
    if not props:
        return []
    results = backend.check_many([statement_check(p) for p in props], timeout_s=timeout_s)
    return [bool(r.ok and r.sorries == 1) for r in results]


def battery_closes(props: Sequence[str], backend, timeout_s: float) -> list[str | None]:
    """First automation tactic that closes each prop, or None.

    Reuses `families.validate`'s battery so extending that list strengthens this
    filter retroactively too (FAMILIES.md: the battery is one constant). One
    prop's 20 attempts go out as a single `check_many`, which is what makes the
    measured cost ~12 s/prop on a 2-worker pool.
    """
    from rlmath.families.validate import battery_proofs

    proofs = battery_proofs()
    out: list[str | None] = []
    for p in props:
        results = backend.check_many([proof_check(p, b) for b in proofs], timeout_s=timeout_s)
        hit = next((b for b, r in zip(proofs, results) if r.ok and r.sorries == 0), None)
        out.append(hit)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--bank", type=Path, default=DEFAULT_BANK, help="READ-ONLY source bank")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--band-lo", type=float, default=BAND_LO)
    p.add_argument("--band-hi", type=float, default=BAND_HI)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--per-parent", type=int, default=4, help="mutants EMITTED per parent")
    p.add_argument("--oversample", type=int, default=3,
                   help="generate per-parent × this many candidates before gating")
    p.add_argument("--max-ops", type=int, default=2, help="numerals changed per mutant (v1: 1-2)")
    p.add_argument("--parent-pool", choices=["both", "train", "eval"], default="both",
                   help="restrict parents by leaf_split; refuses mixed draws when not 'both'")
    p.add_argument("--coherent-split", action="store_true",
                   help="drop mutants whose own leaf_split differs from their parent's "
                        "(closes the near-duplicate channel; costs ~37%% of mutants)")
    p.add_argument("--exclude-bank", type=Path, action="append", default=None,
                   help="extra JSONL whose statement_keys are already measured (repeatable); "
                        "the source bank is always excluded")
    p.add_argument("--limit-parents", type=int, default=None)
    p.add_argument("--backend", choices=["repl", "kimina", "fake"], default="repl")
    p.add_argument("--kimina-url", default=None)
    p.add_argument("--workers", type=int, default=2, help="REPL pool size")
    p.add_argument("--timeout-s", type=float, default=120.0)
    p.add_argument("--battery-filter", action="store_true",
                   help="enforce the V0/V5 corridor floor with local Lean instead of GPU: skip "
                        "parents the automation battery closes (6/37 DSV2 band rows are) and drop "
                        "mutants it closes; ~20 extra checks per prop, ~12 s each on 2 workers")
    p.add_argument("--battery-timeout-s", type=float, default=25.0)
    p.add_argument("--rejects-out", type=Path, default=None,
                   help="gated-out candidates + reasons (default: <out>.rejects.jsonl)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    out: Path = args.out
    bank: Path = args.bank
    excludes = [bank] + list(args.exclude_bank or [])

    # The oracle bank is read-only (task contract + FAMILIES.md): refuse to write
    # anywhere it lives rather than trust the caller's --out.
    written = {out.resolve()}
    if args.rejects_out is not None:
        written.add(args.rejects_out.resolve())
    for p in excludes:
        if p.exists() and p.resolve() in written:
            raise SystemExit(f"refusing to write mutants into a measured bank file: {p}")

    rows = read_rows(bank)
    if not rows:
        raise SystemExit(f"no rows in {bank}")
    parents = band_parents(rows, args.band_lo, args.band_hi)
    if args.parent_pool != "both":
        parents = [r for r in parents if leaf_split(r["statement_key"]) == args.parent_pool]
    if args.limit_parents is not None:
        parents = parents[: args.limit_parents]
    if not parents:
        raise SystemExit(
            f"no band parents in {bank} for pass_rate ∈ [{args.band_lo}, {args.band_hi}]"
            + (f" and pool {args.parent_pool}" if args.parent_pool != "both" else "")
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    rejects: Path = args.rejects_out or out.with_suffix(out.suffix + ".rejects.jsonl")
    # Rejected keys are "already decided", so a resume must not re-gate them.
    known = all_keys(excludes) | all_keys([out, rejects])
    n_resumed = len(all_keys([out]))

    backend = make_backend(args)
    stats: Counter[str] = Counter()
    op_kinds: Counter[str] = Counter()
    splits: Counter[str] = Counter()
    n_emitted = 0
    try:
        for parent in parents:
            want = args.per_parent
            # Corridor floor on the PARENT, not just its children. Measured
            # 2026-08-12: 6/37 DSV2 band rows are closed by one bare battery
            # tactic (`999 + 10 = 1009` by simp, `(10:ℝ)^(Real.logb 10 7) = 7` by
            # simp, ...) — the bank's band filter is the corridor's *ceiling*
            # only. All three such lineages that were bred produced zero
            # surviving mutants, so skipping the parent saves ~12 battery checks
            # and every downstream pass@8 those mutants would have cost.
            if args.battery_filter:
                hit = battery_closes([parent["prop"]], backend, args.battery_timeout_s)[0]
                if hit is not None:
                    stats["parent_trivial"] += 1
                    print(f"skip parent {parent['statement_key']} "
                          f"(pass_rate={parent.get('pass_rate')}): battery closes it with {hit!r}",
                          file=sys.stderr)
                    continue
            cands = mutants(
                parent["prop"],
                seed=args.seed,
                n=max(want * max(1, args.oversample), want),
                max_ops=args.max_ops,
            )
            stats["generated"] += len(cands)
            parent_pool = leaf_split(parent["statement_key"])
            if args.parent_pool != "both" and parent_pool != args.parent_pool:
                raise AssertionError("parent pool filter leaked a mixed draw")

            fresh: list[Mutant] = []
            for m in cands:
                key = m.statement_key
                if key in known:
                    stats["dup_or_measured"] += 1
                    continue
                if args.coherent_split and leaf_split(key) != parent_pool:
                    stats["cross_pool_dropped"] += 1
                    continue
                known.add(key)          # dedupe within this run too
                fresh.append(m)

            ok = elaborates([m.prop for m in fresh], backend, args.timeout_s)
            gated = []
            for m, good in zip(fresh, ok):
                if good:
                    gated.append(m)
                else:
                    stats["elab_failed"] += 1
                    append_row(rejects, reject_row(m, parent, args.seed, "elaboration"))

            if args.battery_filter:
                # One prop at a time, stopping at `want` survivors: the battery is
                # ~20 Lean checks per prop, and with oversample=3 most candidates
                # are never emitted anyway. Rejections are still recorded.
                kept: list[Mutant] = []
                for m in gated:
                    if len(kept) >= want:
                        break
                    hit = battery_closes([m.prop], backend, args.battery_timeout_s)[0]
                    if hit is None:
                        kept.append(m)
                    else:
                        stats["battery_closed"] += 1
                        append_row(rejects, reject_row(m, parent, args.seed, f"battery:{hit}"))
                gated = kept

            for m in gated[:want]:
                row = candidate_row(m, parent, args.seed)
                append_row(out, row)
                n_emitted += 1
                op_kinds.update(o.kind for o in m.ops)
                splits[f"{row['parent_split']}->{row['split']}"] += 1
                print(f"[{n_emitted}] {row['statement_key']} <- {row['parent_key']} "
                      f"ops={[o.kind for o in m.ops]} {row['parent_split']}->{row['split']}",
                      file=sys.stderr)
            stats["surplus_unemitted"] += max(0, len(gated) - want)
    finally:
        backend.close()

    cross = sum(v for k, v in splits.items() if k.split("->")[0] != k.split("->")[1])

    def tally(c: Counter) -> str:
        return ", ".join(f"{k}={v}" for k, v in sorted(c.items())) or "none"

    lines = [
        "",
        f"done: {n_emitted} mutants -> {out} ({n_resumed} rows already present, skipped)",
        f"rejects (with reasons) -> {rejects}",
        f"parents: {len(parents)} band rows from {bank} "
        f"(pass_rate ∈ [{args.band_lo}, {args.band_hi}], pool={args.parent_pool})",
        f"gating: {tally(stats)}",
        f"op kinds: {tally(op_kinds)}",
        f"splits (parent->mutant): {tally(splits)}  [cross-pool={cross}]",
    ]
    if cross:
        lines += [
            "",
            f"WARNING: {cross}/{n_emitted} mutants landed in the OPPOSITE leaf_split pool from",
            "their parent. Fresh keys give independent membership (families/leaf_split.py) but",
            "NOT independent content: a one-constant mutant of a TRAIN leaf sitting in the EVAL",
            "pool is a near-duplicate — the contamination the FAMILIES.md leaf-disjointness",
            "contract exists to close. Rows carry parent_split/split so a policy can be applied",
            "after measurement; --coherent-split drops these up front, which is cheaper because",
            "a mutant discarded before measurement costs no GPU.",
        ]
    lines += [
        "",
        "NEXT (mandatory — mutants inherit the neighborhood, never membership):",
        f"  uv run python scripts/build_bank.py --dataset json "
        f"--data-files {_display_path(out)} --split train \\",
        "      --out data/bank/bank_mutants.jsonl --k 8 --leaf-model <frozen leaf> "
        "--leaf-template <template>",
        "",
    ]
    print("\n".join(lines), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
