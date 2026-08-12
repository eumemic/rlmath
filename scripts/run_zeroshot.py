#!/usr/bin/env python
"""Phase-2 zero-shot eval runner — one (problem-set, k, arm, root-model) cell.

DIRECTION.md §5.5 Phase 2 (the zero-shot study) and §6 ("Reuse from ../rl":
*`eval/run_eval.py` cell structure — one JSONL per (family, k, arm, system),
resumability that skips ids including error rows*). This is that runner, ported:
same cell-per-file layout, same resume rule, same evidence discipline.

    uv run python scripts/run_zeroshot.py --problems data/families/bridge_chain/k2.jsonl \\
        --arm direct --root-model qwen/qwen3-30b-a3b-instruct-2507 \\
        --extra-header X-Prime-Team-ID=$PRIME_TEAM_ID --max-usd 1.50 \\
        --price-in 0.20 --price-out 0.80

    uv run python scripts/run_zeroshot.py --problems data/families/bridge_chain/k2.jsonl \\
        --arm decomp --root-model claude-haiku-4.5 --leaf-model deepseek-ai/DeepSeek-Prover-V2-7B \\
        --leaf-base-url http://gpu:8000/v1 --max-usd 2 --price-in 1 --price-out 5

    uv run python scripts/run_zeroshot.py --problems data/families/bridge_chain/k2.jsonl \\
        --arm decomp --root-model qwen/qwen3-30b-a3b-instruct-2507 --few-shot \\
        --leaf-model deepseek-ai/DeepSeek-Prover-V2-7B --max-usd 0.5 --price-in 0.2 --price-out 0.8

Output: `results/zeroshot/<set>_k<k>_[fs-]<arm>_<root-slug>.jsonl`, one row per
problem. Nothing else writes there, so a cell file is a complete, re-runnable
unit of evidence.

Resumability (../rl `existing_ids`): problem ids already in the file are
skipped **including `status: "error"` rows**. Silent retry of errors would make
a cell's numbers depend on run history; retrying them is a separate, deliberate
act — `--repair`, the analog of ../rl's `repair_errors.py` and build_bank's
`--repair`, which drops error rows and nothing else.

Statuses come from `core.types.Status` only; the arms map to it
(`rlmath.eval.arms`) and this file adds exactly one thing on top: an infra
failure becomes an `error` row instead of killing the run, and an over-window
refusal becomes `context_window_exceeded` (feasibility evidence, §5.7 P1, which
must never be averaged in as a score-0).

Budget guard
------------
`--max-usd` with `--price-in/--price-out` ($/Mtok) stops the run **between
rows**, never mid-row: a half-scored problem would either be lost or written as
a fake failure. The stop is conservative — it triggers when the accumulated
spend plus the most expensive row seen so far would exceed the cap — and the
estimate itself is conservative when the provider omits `usage`: chars/3.5 is
the ../rl estimator that DIRECTION §6 records as wrong by ~2× on dense text, so
estimated token counts are multiplied by ESTIMATE_SAFETY_FACTOR before being
charged (the row keeps the raw estimate and says `"source": "chars/3.5"`).

Problem sources (`--problems`, auto-detected per row)
-----------------------------------------------------
  * **family rows** — `scripts/gen_families.py` output (`GeneratedProblem`):
    the goal is the nested `goal` object, and `k`/`family` come off the row.
  * **goal/bank rows** — `scripts/build_bank.py` output or any
    `{id?, prop, name?}` JSONL: `prop` at top level, id from
    `id`/`source_id`/`statement_key`, no `k`.

Leaf-disjointness (FAMILIES.md, binding): this runner **draws no bank leaves** —
it consumes problems somebody else materialized — so there is no mixed draw to
refuse here. What it does instead is record the pool: family rows carry
`meta["leaf_pool"]` when their generator drew from the bank, and bank-goal rows
get `families.leaf_split(statement_key)` computed. The pool histogram is printed
at startup and `--leaf-pool` filters, so an eval cell contaminated with
train-pool leaves is visible in the row data rather than discovered later.

Few-shot (`--few-shot`, DIRECTION §5.5 escalation rung 1.5)
-----------------------------------------------------------
Off by default; a cell is zero-shot unless asked otherwise. When on, one worked
example (`rlmath.eval.exemplars`) is prepended to every root prompt in the cell:
the decomp arm sees an oracle plan in the wire format, the direct arm sees the
same problem's composed oracle proof — matched, so the arms stay comparable.

Three properties are enforced here rather than trusted:

  * **Provenance.** Every row carries `few_shot` and an `exemplar` block
    (family, k, seed, problem id, goal statement key, size). A few-shot cell is
    regenerable from its own rows.
  * **No contamination.** The exemplar is generated fresh from the family
    REGISTRY at a dedicated seed — never read from a materialized dataset — and
    a run whose exemplar goal matches ANY problem in the cell aborts loudly
    (`assert_exemplar_is_not_an_eval_problem`). A worked example that is also an
    eval item measures recall, and silently skipping the collision would hide
    that a cell had been quietly reduced.
  * **No collision with zero-shot cells.** The cell filename gains an `fs-`
    marker on the arm segment (`..._k2_fs-decomp_<root>.jsonl`), so a few-shot
    run can never resume into, or append to, its zero-shot twin.

Seams: every heavy import (Lean backend, leaf prover, OpenAI SDK) lives inside
`make_backend` / `make_leaf` / `make_root`, so this module imports — and its
logic unit-tests — with no toolchain, no server and no network. Tests
monkeypatch those three (tests/test_zeroshot.py).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from rlmath.core.types import Budgets, GoalSpec, Status, statement_key
from rlmath.eval.arms import (
    ARMS,
    ARMS_NEEDING_LEAF,
    ArmOutcome,
    Usage,
    model_slug,
    parse_extra_headers,
    run_arm,
    status_for_exception,
)
from rlmath.eval.exemplars import (
    DEFAULT_EXEMPLAR_K,
    DEFAULT_EXEMPLAR_SEED,
    build_exemplar,
    exemplar_provenance,
    load_exemplar_problem,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = ROOT / "results" / "zeroshot"

# 2, not 4: each REPL worker holds a full Mathlib image in RAM (gen_families.py).
DEFAULT_WORKERS = 2
DEFAULT_ROOT_TIMEOUT_S = 900.0
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 4096

# Multiplier applied to *estimated* token counts before charging them against
# --max-usd. DIRECTION §6: chars/3.5 was wrong by ~2× on dense text in ../rl, and
# a budget guard that under-charges is not a guard. API-reported usage is charged
# as-is.
ESTIMATE_SAFETY_FACTOR = 2.0


# ---------------------------------------------------------------------------
# Problems
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Problem:
    """One eval item: a goal plus the cell coordinates the row must carry."""

    id: str
    goal: GoalSpec
    k: int | None = None
    family: str | None = None
    leaf_pool: str | None = None


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
                continue  # a torn last line from a killed run must not abort a resume
    return rows


def row_shape(row: dict) -> str:
    """`"family"` or `"goals"` — the two `--problems` shapes, per row.

    Detection is on structure, not on filename: a `goal` object means the
    generator's `GeneratedProblem` row (FAMILIES.md), a top-level `prop` means a
    bank/goal row. Anything else raises, because guessing which field is the
    proposition is how a run silently evaluates the wrong text.
    """
    if isinstance(row.get("goal"), dict) and (row["goal"].get("prop") or "").strip():
        return "family"
    if isinstance(row.get("prop"), str) and row["prop"].strip():
        return "goals"
    raise ValueError(
        "unrecognized problem row: expected a family row (nested 'goal' with 'prop') "
        f"or a goal/bank row (top-level 'prop'); got keys {sorted(row)[:8]}"
    )


def _goal_name_for(row: dict, key: str) -> str:
    """A Lean declaration name for a bank row, which has none.

    Derived from the statement key so it is stable across runs and unique per
    statement; `zs_` prefixed so it can never collide with the harness's
    reserved names (`core.leancode.RESERVED_NAMES`).
    """
    name = str(row.get("name") or "").strip()
    return name if name else f"zs_{key}"


def problem_from_row(row: dict, index: int) -> Problem:
    shape = row_shape(row)
    if shape == "family":
        g = row["goal"]
        pid = str(row.get("id") or g.get("id") or f"p{index}")
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        pool = row.get("leaf_pool") or meta.get("leaf_pool") or meta.get("pool")
        k = row.get("k")
        return Problem(
            id=pid,
            goal=GoalSpec(id=str(g.get("id") or pid), prop=g["prop"],
                          name=str(g.get("name") or "goal")),
            k=int(k) if isinstance(k, int) else None,
            family=str(row["family"]) if row.get("family") else None,
            leaf_pool=str(pool) if pool else None,
        )

    prop = row["prop"]
    key = str(row.get("statement_key") or statement_key(prop))
    pid = str(row.get("id") or row.get("source_id") or key)
    # The pool is computed, not read: leaf_split is a pure function of the key
    # (FAMILIES.md — membership must not depend on a manifest anyone can re-roll).
    from rlmath.families.leaf_split import leaf_split

    return Problem(
        id=pid,
        goal=GoalSpec(id=pid, prop=prop, name=_goal_name_for(row, key)),
        k=int(row["k"]) if isinstance(row.get("k"), int) else None,
        family=str(row["family"]) if row.get("family") else None,
        leaf_pool=leaf_split(key),
    )


def load_problems(path: Path, *, require_elaborates: bool = True) -> tuple[list[Problem], dict]:
    """Read `--problems` into `Problem`s. Returns (problems, skip counts).

    Bank rows that failed elaboration (or errored) are skipped by default and
    *counted*: running an arm against a statement the kernel already rejected
    measures nothing, but dropping rows silently is exactly the kind of quiet
    dataset change that makes two cells incomparable, so the count is printed.
    """
    rows = read_rows(path)
    if not rows:
        raise SystemExit(f"no problem rows in {path}")
    skipped = {"not_elaborating": 0}
    problems: list[Problem] = []
    for i, row in enumerate(rows):
        if require_elaborates and row.get("elaborates") is False:
            skipped["not_elaborating"] += 1
            continue
        problems.append(problem_from_row(row, i))
    dupes = len(problems) - len({p.id for p in problems})
    if dupes:
        # Duplicate ids would collide in the resume set: the second row would be
        # skipped as "already done" and never evaluated.
        raise SystemExit(f"{path}: {dupes} duplicate problem id(s); ids must be unique")
    return problems, skipped


def derive_set_name(path: Path) -> str:
    """`data/families/bridge_chain/k2.jsonl` -> `bridge_chain`; else the stem."""
    stem = path.stem
    if len(stem) > 1 and stem[0] == "k" and stem[1:].isdigit():
        return path.parent.name
    return stem


def derive_k(problems: Sequence[Problem]) -> str:
    """The cell's k label: the shared k, `mix`, or `na` when rows carry none."""
    ks = {p.k for p in problems if p.k is not None}
    if not ks:
        return "na"
    return str(next(iter(ks))) if len(ks) == 1 else "mix"


def cell_path(out_dir: Path, problem_set: str, k: str, arm: str, root_model: str,
              *, few_shot: bool = False) -> Path:
    """`<set>_k<k>_[fs-]<arm>_<root-slug>.jsonl`.

    The `fs-` marker sits on the arm segment rather than becoming a fifth field,
    so the four-field cell-name shape every analysis script splits on is
    unchanged and the arm column simply reads `fs-decomp`. Without a marker a
    few-shot run would resume into the zero-shot cell of the same coordinates
    and produce one file containing two different experiments.
    """
    marker = "fs-" if few_shot else ""
    return out_dir / f"{problem_set}_k{k}_{marker}{arm}_{model_slug(root_model)}.jsonl"


# ---------------------------------------------------------------------------
# Few-shot exemplar (DIRECTION §5.5 rung 1.5) — see the module docstring
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Exemplar:
    """The worked example this cell prepends, plus what the rows must record."""

    text: str
    provenance: dict


def resolve_exemplar_family(args, problems: Sequence[Problem]) -> str:
    """`--exemplar-family`, else the family the cell's problems come from.

    Defaulting to the cell's own family is the rung-1.5 design (the example is
    "a different goal from the same task family"); a cross-family exemplar is
    legal but must be asked for, since it changes what the cell measures. Rows
    that carry no family (bank goals) have nothing to default to, and guessing
    would silently pick one — so that is an error naming the fix.
    """
    if args.exemplar_family:
        return str(args.exemplar_family)
    families = sorted({p.family for p in problems if p.family})
    if len(families) == 1:
        return families[0]
    what = (f"the rows carry {len(families)} families ({', '.join(families)})"
            if families else "the rows carry no family (bank/goal rows)")
    raise SystemExit(f"--few-shot cannot pick an exemplar family: {what}; "
                     "pass --exemplar-family")


def assert_exemplar_is_not_an_eval_problem(problem, problems: Sequence[Problem]) -> None:
    """Refuse an exemplar that IS one of the cell's problems. Loud, never a skip.

    Matching is by `core.types.statement_key` (normalized prop), not raw string
    equality: an exemplar differing from an eval item only in whitespace is the
    same contamination. The exemplar is generated fresh at a dedicated seed
    precisely so this never fires — which is why, if it ever does, the right
    response is to stop the run and look, not to quietly drop the example (the
    cell would then be silently zero-shot while its filename and rows claimed
    otherwise) and not to quietly drop the problem (a cell whose contents depend
    on the exemplar is not comparable with anything).
    """
    key = statement_key(problem.goal.prop)
    clashes = [p.id for p in problems if statement_key(p.goal.prop) == key]
    if clashes:
        shown = ", ".join(clashes[:5]) + (" ..." if len(clashes) > 5 else "")
        raise SystemExit(
            f"few-shot exemplar {problem.id} (family={problem.family}, k={problem.k}, "
            f"seed={problem.seed}) has the same goal proposition as {len(clashes)} problem(s) "
            f"in this cell [{shown}]. A worked example that is also an eval item makes the "
            "cell measure recall, not decomposition. Move the exemplar (--exemplar-seed / "
            "--exemplar-k / --exemplar-family) or drop --few-shot."
        )


def build_cell_exemplar(args, problems: Sequence[Problem]) -> Exemplar:
    """Generate the exemplar, check it against the cell, package its provenance.

    Pure Python: no network, no kernel, no dataset read — so `--dry-run` runs
    this too and a contaminated or misconfigured exemplar is caught before a
    single token is bought.
    """
    family = resolve_exemplar_family(args, problems)
    try:
        problem = load_exemplar_problem(family, k=args.exemplar_k, seed=args.exemplar_seed)
    except ValueError as e:
        raise SystemExit(f"--few-shot: {e}") from None
    assert_exemplar_is_not_an_eval_problem(problem, problems)
    try:
        text = build_exemplar(problem, args.arm)
    except KeyError as e:
        # An arm with no matched exemplar must not run few-shot at all: the
        # comparison it feeds is the whole point of building one.
        raise SystemExit(f"--few-shot: {e}") from None
    return Exemplar(text=text, provenance=exemplar_provenance(problem, args.arm, text))


# ---------------------------------------------------------------------------
# Resume + append (../rl/eval/run_eval.py)
# ---------------------------------------------------------------------------

def existing_ids(path: Path) -> set[str]:
    """Problem ids already written — ERROR ROWS INCLUDED.

    ../rl's rule, and DIRECTION §6's: an infrastructure error is a recorded
    event, not a hole to be quietly refilled on the next run.
    """
    return {r["id"] for r in read_rows(path) if isinstance(r.get("id"), str)}


def append_row(path: Path, row: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def rewrite_rows(path: Path, rows: Sequence[dict]) -> None:
    """Atomically replace the cell file (only --repair does this)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def drop_error_rows(path: Path) -> int:
    """`--repair`: drop `status == "error"` rows so the resume re-runs exactly
    those. Returns how many were dropped.

    ../rl's `repair_errors.py`, as DIRECTION §6 lifts it. ONLY infrastructure
    errors go: `format_error`, `leaf_failed`, `plan_invalid` and
    `context_window_exceeded` are *measurements* (the last one is feasibility
    evidence, §5.7 P1), and silently re-rolling a measurement would make a
    cell's numbers depend on how many times it was run.
    """
    rows = read_rows(path)
    keep = [r for r in rows if r.get("status") != Status.ERROR.value]
    if len(keep) != len(rows):
        rewrite_rows(path, keep)
    return len(rows) - len(keep)


# ---------------------------------------------------------------------------
# Budget guard
# ---------------------------------------------------------------------------

@dataclass
class BudgetGuard:
    """Spend accounting and the clean-stop decision (see the module docstring).

    `max_row_cost` is the headroom the next row is assumed to need. Using the
    worst row seen rather than the mean is the conservative choice: root
    completions are long-tailed (a CoT-ish root can emit 10× the tokens of a
    terse one), and the failure this guard exists to prevent is an overshoot.
    """

    max_usd: float | None = None
    price_in: float = 0.0        # $ per 1M prompt tokens
    price_out: float = 0.0       # $ per 1M completion tokens
    spend: float = 0.0
    max_row_cost: float = 0.0
    n_charged: int = 0

    def cost_of(self, usage: Usage) -> float:
        factor = ESTIMATE_SAFETY_FACTOR if usage.estimated else 1.0
        return (
            usage.prompt_tokens * factor * self.price_in
            + usage.completion_tokens * factor * self.price_out
        ) / 1_000_000

    def charge(self, cost: float) -> None:
        self.spend += cost
        self.max_row_cost = max(self.max_row_cost, cost)
        self.n_charged += 1

    def should_stop(self) -> str | None:
        """Reason to stop before starting another row, or None."""
        if self.max_usd is None:
            return None
        if self.spend >= self.max_usd:
            return f"estimated spend ${self.spend:.4f} reached --max-usd ${self.max_usd:.4f}"
        projected = self.spend + self.max_row_cost
        if projected > self.max_usd:
            return (
                f"estimated spend ${self.spend:.4f} + worst observed row "
                f"${self.max_row_cost:.4f} would exceed --max-usd ${self.max_usd:.4f}"
            )
        return None


# ---------------------------------------------------------------------------
# Lazy construction seams (tests monkeypatch these three)
# ---------------------------------------------------------------------------

def make_backend(args):
    """The Lean backend. Both arms need one — the kernel is the judge."""
    from rlmath.lean import get_backend

    kw = {"n_workers": args.workers} if args.backend == "repl" else {"base_url": args.kimina_url}
    return get_backend(args.backend, **kw)


def make_leaf(args):
    """The frozen leaf prover (DIRECTION §5.3). Only the decomp arm needs it.

    The attempt cache is ON here (unlike the direct arm's one-shot prover): leaf
    calls are the expensive part of a decomposition episode and §5.6 makes
    caching explicit policy — repeated statements across a cell cost nothing.
    """
    from rlmath.leaf import LeafProver
    from rlmath.leaf.cache import AttemptCache

    kw = {}
    if args.leaf_max_tokens is not None:
        kw["max_tokens"] = args.leaf_max_tokens
    if args.leaf_temperature is not None:
        kw["temperature"] = args.leaf_temperature
    return LeafProver.from_openai(
        base_url=args.leaf_base_url,
        api_key=os.environ.get("LEAF_API_KEY", "EMPTY"),
        model=args.leaf_model,
        template=args.leaf_template,
        cache=AttemptCache(),
        **kw,
    )


def make_root(args):
    """The root policy client (OpenAI-compatible; Prime Inference by default)."""
    from rlmath.eval.arms import make_root_client

    return make_root_client(
        args.root_model,
        base_url=args.base_url,
        api_key=os.environ.get(args.api_key_env) or None,
        extra_headers=parse_extra_headers(args.extra_header),
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        timeout_s=args.root_timeout_s,
    )


# ---------------------------------------------------------------------------
# One row
# ---------------------------------------------------------------------------

def base_row(problem: Problem, args, *, problem_set: str, k_label: str,
             exemplar: Exemplar | None = None) -> dict:
    return {
        "id": problem.id,
        "problem_set": problem_set,
        "k": problem.k,
        "k_cell": k_label,
        "family": problem.family,
        "leaf_pool": problem.leaf_pool,
        "arm": args.arm,
        "root_model": args.root_model,
        "leaf_model": args.leaf_model if args.arm in ARMS_NEEDING_LEAF else None,
        "goal_id": problem.goal.id,
        "goal_name": problem.goal.name,
        "goal_prop": problem.goal.prop,
        # Rung 1.5 provenance. Present on every row (as false/None when the cell
        # is zero-shot) so a mixed results/ directory is analysable by column
        # rather than by filename convention.
        "few_shot": exemplar is not None,
        "exemplar": exemplar.provenance if exemplar is not None else None,
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def outcome_row(outcome: ArmOutcome, *, cost_usd: float) -> dict:
    """The measured half of a row. `completion` is stored in full, on purpose
    (§5.7 P2 trajectory analysis reads exactly the tokens the root emitted).

    `cost_basis` names how `cost_usd` was derived, because the two are not the
    same claim: an estimated row's cost carries ESTIMATE_SAFETY_FACTOR and must
    not be summed as if it were a provider invoice.
    """
    return {
        "cost_basis": ("api" if not outcome.usage.estimated
                       else f"estimated_x{ESTIMATE_SAFETY_FACTOR:g}"),
        "status": outcome.status.value,
        "reward": outcome.reward,
        "plan_stats": outcome.plan_stats,
        "detail": outcome.detail,
        "completion": outcome.completion,
        "artifact": outcome.artifact,
        "finish_reason": outcome.finish_reason,
        "usage": outcome.usage.as_row(),
        "cost_usd": round(cost_usd, 6),
        "prompt_chars": outcome.prompt_chars,
        "leaf_attempts_used": outcome.leaf_attempts_used,
        "root_elapsed_s": outcome.root_elapsed_s,
        "score_elapsed_s": outcome.score_elapsed_s,
        **outcome.extra,
    }


def error_row(exc: BaseException) -> dict:
    """Infra failure -> a recorded row, never a score (DIRECTION §6).

    `context_window_exceeded` is split out here because it is *feasibility*
    evidence (§5.7 P1): the flat arm being unable to fit a k=128 proof is the
    result, not a bug.

    Known hole in the spend accounting: a call that raises returns no usage, so
    the row charges $0 even when the provider generated (and bills for) tokens
    before the failure — a timeout mid-generation is the realistic case. The cap
    is therefore a cap on *successful* spend; a cell that errors repeatedly can
    exceed it. Watch the provider's own dashboard on long runs.
    """
    status = status_for_exception(exc)
    return {
        "cost_basis": "none",
        "status": status.value,
        "reward": 0.0,
        "plan_stats": None,
        "detail": f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-2000:]}",
        "completion": "",
        "artifact": None,
        "finish_reason": None,
        "usage": Usage().as_row(),
        "cost_usd": 0.0,
        "prompt_chars": 0,
        "leaf_attempts_used": 0,
        "root_elapsed_s": 0.0,
        "score_elapsed_s": 0.0,
    }


def run_one(problem: Problem, args, *, root, backend, leaf, budgets: Budgets,
            guard: BudgetGuard, problem_set: str, k_label: str,
            exemplar: Exemplar | None = None) -> dict:
    """Score one problem into a row. Never raises: infra failure becomes a row."""
    row = base_row(problem, args, problem_set=problem_set, k_label=k_label,
                   exemplar=exemplar)
    t0 = time.perf_counter()
    try:
        outcome = run_arm(
            args.arm, problem.goal, root=root, backend=backend, leaf=leaf, budgets=budgets,
            exemplar=exemplar.text if exemplar is not None else None,
        )
        row.update(outcome_row(outcome, cost_usd=guard.cost_of(outcome.usage)))
    except Exception as e:
        row.update(error_row(e))
    row["elapsed_s"] = round(time.perf_counter() - t0, 3)
    return row


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Run one (problem-set, k, arm, root-model) zero-shot cell "
                    "(DIRECTION.md §5.5 Phase 2).",
    )
    p.add_argument("--problems", type=Path, required=True,
                   help="JSONL of family rows (gen_families.py) or goal/bank rows (build_bank.py)")
    p.add_argument("--arm", required=True, choices=sorted(ARMS))
    p.add_argument("--root-model", required=True, dest="root_model")

    # --- root client -------------------------------------------------------
    p.add_argument("--base-url", default=None, dest="base_url",
                   help="OpenAI-compatible root endpoint (default: $OPENAI_BASE_URL)")
    p.add_argument("--api-key-env", default="OPENAI_API_KEY", dest="api_key_env",
                   help="env var holding the root API key (default OPENAI_API_KEY)")
    p.add_argument("--extra-header", action="append", default=[], metavar="KEY=VALUE",
                   help="extra HTTP header, repeatable (Prime Inference needs "
                        "X-Prime-Team-ID=<team>)")
    p.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    p.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, dest="max_tokens",
                   help="root output cap")
    p.add_argument("--root-timeout-s", type=float, default=DEFAULT_ROOT_TIMEOUT_S,
                   dest="root_timeout_s")

    # --- few-shot exemplar (DIRECTION §5.5 rung 1.5) -----------------------
    p.add_argument("--few-shot", action="store_true", dest="few_shot",
                   help="prepend one worked example to every root prompt (default off). "
                        "The example is generated fresh from the family registry, matched "
                        "across arms, and recorded on every row")
    p.add_argument("--exemplar-family", default=None, dest="exemplar_family",
                   help="family to draw the worked example from (default: the family the "
                        "--problems rows come from)")
    p.add_argument("--exemplar-k", type=int, default=DEFAULT_EXEMPLAR_K, dest="exemplar_k",
                   help=f"k of the worked example (default {DEFAULT_EXEMPLAR_K})")
    p.add_argument("--exemplar-seed", type=int, default=DEFAULT_EXEMPLAR_SEED,
                   dest="exemplar_seed",
                   help=f"seed of the worked example (default {DEFAULT_EXEMPLAR_SEED}, "
                        "reserved for exemplars; it is never a dataset seed)")

    # --- Lean backend ------------------------------------------------------
    p.add_argument("--backend", choices=["repl", "kimina"], default="repl")
    p.add_argument("--kimina-url", default=None, dest="kimina_url")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                   help=f"REPL pool size (default {DEFAULT_WORKERS}; each holds Mathlib in RAM)")

    # --- leaf (decomp arm only) -------------------------------------------
    p.add_argument("--leaf-base-url", default="http://localhost:8000/v1", dest="leaf_base_url")
    p.add_argument("--leaf-model", default=None, dest="leaf_model")
    p.add_argument("--leaf-template", default=None, dest="leaf_template",
                   help="template name from rlmath.leaf.prompts.TEMPLATES")
    p.add_argument("--leaf-max-tokens", type=int, default=None, dest="leaf_max_tokens")
    p.add_argument("--leaf-temperature", type=float, default=None, dest="leaf_temperature")

    # --- budgets (§5.6 hard caps) -----------------------------------------
    d = Budgets()
    p.add_argument("--max-lemmas", type=int, default=d.max_lemmas, dest="max_lemmas")
    p.add_argument("--leaf-attempts-per-lemma", type=int, default=d.leaf_attempts_per_lemma,
                   dest="leaf_attempts_per_lemma")
    p.add_argument("--max-total-leaf-attempts", type=int, default=d.max_total_leaf_attempts,
                   dest="max_total_leaf_attempts")
    p.add_argument("--verify-timeout-s", type=float, default=d.verify_timeout_s,
                   dest="verify_timeout_s")

    # --- spend -------------------------------------------------------------
    p.add_argument("--max-usd", type=float, default=None, dest="max_usd",
                   help="stop cleanly (between rows) once estimated spend reaches this")
    p.add_argument("--price-in", type=float, default=0.0, dest="price_in",
                   help="root price, $ per 1M prompt tokens")
    p.add_argument("--price-out", type=float, default=0.0, dest="price_out",
                   help="root price, $ per 1M completion tokens")

    # --- selection / output ------------------------------------------------
    p.add_argument("--problem-set", default=None, dest="problem_set",
                   help="cell name (default: derived from --problems)")
    p.add_argument("--k", default=None, dest="k_label",
                   help="cell k label (default: derived from the rows)")
    p.add_argument("--out", type=Path, default=None, help="explicit cell file")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, dest="out_dir")
    p.add_argument("--n", type=int, default=None, help="max problems to run")
    p.add_argument("--offset", type=int, default=0, help="skip the first K problems")
    p.add_argument("--leaf-pool", choices=["train", "eval"], default=None, dest="leaf_pool",
                   help="keep only problems whose recorded leaf pool matches (FAMILIES.md "
                        "leaf-disjointness contract)")
    p.add_argument("--require-elaborates", action=argparse.BooleanOptionalAction, default=True,
                   dest="require_elaborates",
                   help="skip bank rows with elaborates=false (default on; the count is printed)")
    p.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="resolve the cell, print what would run, touch no model and no kernel")
    p.add_argument("--repair", action="store_true",
                   help="drop status=='error' rows from the cell first, so the resume re-runs "
                        "exactly those (../rl repair_errors.py); measured rows are never re-rolled")

    args = p.parse_args(argv)
    if args.arm in ARMS_NEEDING_LEAF and not args.leaf_model and not args.dry_run:
        p.error(f"--arm {args.arm} dispatches lemmas to the frozen leaf: --leaf-model is required")
    if args.max_usd is not None and args.price_in <= 0 and args.price_out <= 0:
        # A cap with no prices is a cap that never fires — worse than no cap,
        # because it reads like protection.
        p.error("--max-usd needs a price table: pass --price-in and/or --price-out ($/Mtok)")
    if args.max_usd is not None and args.max_usd <= 0:
        p.error("--max-usd must be > 0")
    if args.offset < 0:
        p.error("--offset must be >= 0")
    # An --exemplar-* flag without --few-shot would be silently ignored, and the
    # cell would come out zero-shot while its operator believed otherwise.
    tuned = [
        name for name, value, default in (
            ("--exemplar-family", args.exemplar_family, None),
            ("--exemplar-k", args.exemplar_k, DEFAULT_EXEMPLAR_K),
            ("--exemplar-seed", args.exemplar_seed, DEFAULT_EXEMPLAR_SEED),
        ) if value != default
    ]
    if tuned and not args.few_shot:
        p.error(f"{', '.join(tuned)} has no effect without --few-shot")
    return args


def budgets_from_args(args) -> Budgets:
    return Budgets(
        max_lemmas=args.max_lemmas,
        leaf_attempts_per_lemma=args.leaf_attempts_per_lemma,
        max_total_leaf_attempts=args.max_total_leaf_attempts,
        verify_timeout_s=args.verify_timeout_s,
    )


def pool_histogram(problems: Iterable[Problem]) -> dict[str, int]:
    hist: dict[str, int] = {}
    for p in problems:
        key = p.leaf_pool or "unrecorded"
        hist[key] = hist.get(key, 0) + 1
    return hist


@dataclass
class Totals:
    by_status: dict[str, int] = field(default_factory=dict)
    reward_sum: float = 0.0
    scored: int = 0          # rows whose status is a policy verdict, not infra/feasibility

    def add(self, row: dict) -> None:
        s = row["status"]
        self.by_status[s] = self.by_status.get(s, 0) + 1
        # ../rl's rule, kept here so the printed mean matches the analysis:
        # error and context_window_exceeded are excluded from mean score
        # (infrastructure failure and feasibility evidence, DIRECTION §6).
        if s not in (Status.ERROR.value, Status.CONTEXT_WINDOW_EXCEEDED.value):
            self.reward_sum += float(row.get("reward") or 0.0)
            self.scored += 1

    @property
    def mean_reward(self) -> float | None:
        return self.reward_sum / self.scored if self.scored else None


def main(argv=None) -> int:
    args = parse_args(argv)

    problems, skipped = load_problems(args.problems,
                                      require_elaborates=args.require_elaborates)
    if args.leaf_pool:
        kept = [p for p in problems if p.leaf_pool == args.leaf_pool]
        skipped["wrong_leaf_pool"] = len(problems) - len(kept)
        problems = kept
    problem_set = args.problem_set or derive_set_name(args.problems)
    # Derived BEFORE --offset/--n: the cell a problem belongs to must not depend
    # on how many of it you happened to run in one invocation, or a resumed run
    # would append to a differently-named file.
    k_label = args.k_label or derive_k(problems)

    # Before --offset/--n, for the same reason k_label is: the contamination
    # check must see the whole cell, not the slice this invocation happens to run.
    exemplar = build_cell_exemplar(args, problems) if args.few_shot else None

    problems = problems[args.offset:]
    if args.n is not None:
        problems = problems[: args.n]
    if not problems:
        raise SystemExit(f"no problems selected from {args.problems}")

    out_path: Path = args.out or cell_path(
        args.out_dir, problem_set, k_label, args.arm, args.root_model,
        few_shot=args.few_shot,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # not under --dry-run: that flag promises to touch nothing.
    repaired = drop_error_rows(out_path) if (args.repair and not args.dry_run) else 0
    if repaired:
        print(f"repair: dropped {repaired} error row(s) from {out_path}", file=sys.stderr)
    done = existing_ids(out_path)
    todo = [p for p in problems if p.id not in done]
    guard = BudgetGuard(max_usd=args.max_usd, price_in=args.price_in, price_out=args.price_out)

    print(
        f"cell: {problem_set}/k{k_label}/{args.arm}/{args.root_model} -> {out_path}\n"
        f"problems: {len(problems)} selected, {len(problems) - len(todo)} already done "
        f"(errors included), {len(todo)} to run\n"
        f"leaf pools: {pool_histogram(problems)}\n"
        + ("few-shot: off (zero-shot cell)" if exemplar is None else
           "few-shot: " + ", ".join(f"{k}={v}" for k, v in exemplar.provenance.items()))
        + (f"\nskipped at load: {skipped}" if any(skipped.values()) else "")
        + (f"\nbudget: ${args.max_usd:.4f} cap at "
           f"${args.price_in}/${args.price_out} per Mtok in/out"
           if args.max_usd is not None else "\nbudget: no --max-usd cap"),
        file=sys.stderr,
    )
    if args.dry_run:
        print("dry-run: no root call, no kernel, nothing written", file=sys.stderr)
        return 0
    if not todo:
        return 0

    budgets = budgets_from_args(args)
    root = make_root(args)
    backend = make_backend(args)

    totals = Totals()
    stop_reason: str | None = None
    n_run = 0
    try:
        # inside the try: a REPL pool holds child processes, and a leaf-client
        # construction error must not leak them.
        leaf = make_leaf(args) if args.arm in ARMS_NEEDING_LEAF else None
        for i, problem in enumerate(todo):
            stop_reason = guard.should_stop()
            if stop_reason:
                print(f"budget stop before [{i + 1}/{len(todo)}] {problem.id}: {stop_reason}",
                      file=sys.stderr)
                break
            row = run_one(problem, args, root=root, backend=backend, leaf=leaf,
                          budgets=budgets, guard=guard, problem_set=problem_set,
                          k_label=k_label, exemplar=exemplar)
            append_row(out_path, row)
            guard.charge(float(row.get("cost_usd") or 0.0))
            totals.add(row)
            n_run += 1
            print(
                f"[{i + 1}/{len(todo)}] {problem.id}: status={row['status']} "
                f"reward={row['reward']} elapsed={row['elapsed_s']}s "
                f"tok={row['usage']['total_tokens']}({row['usage']['source']}) "
                f"spend=${guard.spend:.4f}",   # already charged for this row
                file=sys.stderr,
            )
    finally:
        backend.close()

    mean = totals.mean_reward
    print(
        f"done: {n_run} run"
        + (f", stopped early ({stop_reason})" if stop_reason else "")
        + "\nstatuses: " + (", ".join(f"{k}={v}" for k, v in sorted(totals.by_status.items()))
                            or "none")
        + f"\nmean reward over {totals.scored} scored rows (error + "
          f"context_window_exceeded excluded): "
        + ("n/a" if mean is None else f"{mean:.3f}")
        + f"\nestimated spend: ${guard.spend:.4f}"
        + (f" of ${args.max_usd:.4f}" if args.max_usd is not None else " (no cap set)")
        + f"\nout: {out_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
