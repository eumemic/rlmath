#!/usr/bin/env python
"""Roster table + rung-1.5 verdict over `results/zeroshot/*.jsonl`.

DIRECTION.md §5.5, cold-start ladder rung 1.5 (registered 2026-08-12):

    "Root-roster diagnostic before any escalation past this rung: qwen3-30b
     few-shot re-run, haiku few-shot, one 100B-class open model, opus as
     ceiling — a handful of episodes each. If NO root decomposes few-shot at
     k=2, that is registered evidence rung 3 is unavoidable; if qwen few-shot
     assembles, the cold-start problem was a prompt gap and priors barely move."

This file answers exactly that question and nothing else. It is the read side of
`scripts/run_roster.sh`; every number comes off rows that
`scripts/run_zeroshot.py` already wrote, so the analyzer never talks to a model,
a kernel or a network.

    uv run python scripts/roster_analyze.py                 # scoped table + verdict
    uv run python scripts/roster_analyze.py --k any --family any
    uv run python scripts/roster_analyze.py results/zeroshot/*.jsonl

The affordance question, made mechanical
----------------------------------------
"Did this root decompose?" is not "did it score 1.0" — at k=2 with a leaf
measured at pass@8 ≈ 0.13 (OVERNIGHT.md flatness verdict), a *correct*
decomposition usually still ends `leaf_failed`. What rung 1.5 asks is whether
the root can emit an assembly that **passes stage 1** — the plan check that
`harness/episode.py` runs before any leaf is called, granting the lemmas as
hypotheses. So the affordance signal is:

    VERIFIED  or  LEAF_FAILED  or  COMPOSE_FAILED   (stage 5 passed)

and the failure signal is the one the smoke actually produced:

    FORMAT_ERROR / STATEMENT_ILL_FORMED / PLAN_INVALID (stage 5 never passed)

`BUDGET_EXHAUSTED` and `SANITIZER_REJECTED` straddle stage 5 (episode.py stages
3 and 2 sit before it; stages 6 and 7–8 sit after), so they are resolved by
evidence of leaf work on the row — `n_lemma_outcomes` / `leaf_attempts_used`
> 0 means the plan check had already passed — and counted as **ambiguous** when
that evidence is absent. Ambiguity blocks the negative verdict rather than
being quietly rounded into it.

Two exclusions that keep the verdict honest, both mandated by §6's evidence
discipline:

  * a `verified` episode whose plan was *direct* (`plan_stats.is_direct`, no
    lemmas) is the root proving the goal outright. It decomposed nothing, so it
    cannot answer the decomposition question; it is counted and reported as
    `direct_close`, never as a stage-1-passing decomposition.
  * `error` and `context_window_exceeded` rows are infrastructure and
    feasibility evidence, never scores (same rule as the runner's `Totals`), and
    a root with *no* evidence rows makes the verdict `insufficient_data` — "no
    root decomposed" must never be reportable from cells that never ran.

Cell naming (`fs` vs `zs`)
--------------------------
`run_zeroshot.py --few-shot` writes `few_shot` (and an `exemplar` provenance
block) on every row and marks the cell filename's arm segment
(`<set>_k2_fs-decomp_<root>.jsonl`). This reader prefers the column — a field
the runner wrote is a measurement of what the prompt contained, a filename is a
convention — and falls back to the name (`fs-` arm marker, or an `fs` token
anywhere in the stem) so hand-run and older cells still classify.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RESULTS_DIR = ROOT / "results" / "zeroshot"
DEFAULT_OUT = ROOT / "analysis" / "roster.json"

# --- the pre-registered roster (mirrors scripts/run_roster.sh ROSTER) -------
# Kept as data here so a missing cell is *named* in the verdict instead of
# silently shrinking the denominator.
ROSTER_ROOTS = (
    "qwen/qwen3-30b-a3b-instruct-2507",
    "Qwen/Qwen3.5-122B-A10B",
    "anthropic/claude-haiku-4.5",
    "anthropic/claude-opus-5",
)
# The root Phase 3 would actually train. DIRECTION §5.5: "if qwen few-shot
# assembles, the cold-start problem was a prompt gap and priors barely move."
RL_TARGET_ROOT = "qwen/qwen3-30b-a3b-instruct-2507"
# The ceiling root ("opus as ceiling"): the negative finding is only strong
# because a frontier model failed too, so the line says so only when it ran.
CEILING_ROOT = "anthropic/claude-opus-5"

DEFAULT_FAMILY = "bridge_chain"
DEFAULT_K = "2"

# --- status classes (core/types.py Status; stages from harness/episode.py) --
STAGE1_PASSING = frozenset({"verified", "leaf_failed", "compose_failed"})
STAGE1_STRADDLING = frozenset({"budget_exhausted", "sanitizer_rejected"})
NOT_EVIDENCE = frozenset({"error", "context_window_exceeded"})

# Reporting bins for `plan_stats.restatement_max` (§5.7 P4). Heuristic bins over
# a heuristic detector (`harness/detectors.py` is explicit that it is not
# α-normalized): use them for shape across cells, never to judge one episode.
RESTATEMENT_BINS = ((0.5, "<0.5"), (0.8, "0.5-0.8"), (0.95, "0.8-0.95"))
RESTATEMENT_TOP = ">=0.95"

KNOWN_ARMS = ("flat_cot_decomposition", "flat_best_of_n", "direct", "decomp")
FS_TOKENS = frozenset({"fs", "fewshot"})


# ---------------------------------------------------------------------------
# Row-level readers (pure)
# ---------------------------------------------------------------------------

def read_rows(path: Path) -> list[dict]:
    """JSONL, tolerant of a torn last line (same rule as the runner's reader)."""
    rows: list[dict] = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def cell_tokens(path: Path | str) -> list[str]:
    return str(Path(path).stem).split("_")


def parse_cell_name(stem: str) -> dict:
    """Inverse of `run_zeroshot.cell_path`: `<set>_k<k>_[fs-]<arm>_<root-slug>`.

    Only a fallback — rows carry `arm`/`root_model`/`few_shot` directly. The set
    name may contain underscores, so the `_k<label>_` marker is the anchor; the
    `fs-` few-shot marker is stripped off the arm segment (the runner puts it
    there rather than adding a fifth field); and the arm is matched against
    `KNOWN_ARMS` longest-first because a future arm (`flat_best_of_n`) has
    underscores of its own.
    """
    tokens = stem.split("_")
    for i, tok in enumerate(tokens):
        if len(tok) > 1 and tok[0] == "k" and (tok[1:].isdigit() or tok[1:] in ("mix", "na")):
            rest = tokens[i + 1:]
            few_shot = bool(rest) and rest[0].startswith("fs-")
            if few_shot:
                rest = [rest[0][len("fs-"):]] + rest[1:]
            arm = next(
                (a for a in KNOWN_ARMS if rest[: len(a.split("_"))] == a.split("_")),
                rest[0] if rest else "",
            )
            n = len(arm.split("_")) if arm else 0
            return {
                "problem_set": "_".join(tokens[:i]),
                "k": tok[1:],
                "arm": arm,
                "few_shot": few_shot,
                "root_slug": "_".join(rest[n:]),
            }
    return {"problem_set": stem, "k": None, "arm": "", "few_shot": False, "root_slug": ""}


def base_set_name(problem_set: str | None) -> str:
    """`bridge_chain_fs` -> `bridge_chain` (the few-shot marker is not a family)."""
    toks = [t for t in str(problem_set or "").split("_") if t not in FS_TOKENS]
    return "_".join(toks)


def _truthy_int(v) -> bool:
    try:
        return int(v) > 0
    except (TypeError, ValueError):
        return False


def name_says_few_shot(path: Path | str) -> bool:
    """`..._k2_fs-decomp_<root>.jsonl` (the runner's marker) or a bare `fs` token."""
    tokens = cell_tokens(path)
    return bool(FS_TOKENS & set(tokens)) or any(t.startswith("fs-") for t in tokens)


def shot_of(row: dict, path: Path | str | None = None) -> str:
    """`"fs"` or `"zs"` — was this episode run with few-shot exemplars?

    Explicit row fields beat names: `few_shot` is what the runner recorded about
    the prompt it actually sent, a filename is a convention. The `exemplar`
    provenance block is checked too, so a row from a runner that recorded the
    block but not the boolean still classifies.
    """
    for key in ("few_shot", "fewshot", "few_shot_enabled"):
        if key in row:
            return "fs" if bool(row[key]) else "zs"
    for key in ("n_exemplars", "n_few_shot", "num_exemplars"):
        if key in row:
            return "fs" if _truthy_int(row[key]) else "zs"
    if isinstance(row.get("exemplar"), dict):
        return "fs"
    for key in ("exemplars", "exemplar_ids"):
        v = row.get(key)
        if isinstance(v, (list, tuple)):
            return "fs" if v else "zs"
    if FS_TOKENS & set(str(row.get("problem_set") or "").split("_")):
        return "fs"
    if path is not None and name_says_few_shot(path):
        return "fs"
    return "zs"


def row_k(row: dict) -> str | None:
    for key in ("k", "k_cell"):
        v = row.get(key)
        if v is not None:
            return str(v)
    return None


def row_family(row: dict) -> str:
    return str(row.get("family") or base_set_name(row.get("problem_set")) or "")


def in_scope(row: dict, *, family: str | None, k: str | None) -> bool:
    """`--family`/`--k` scope. `None` (CLI `any`) disables that half."""
    if family is not None and row_family(row) != family:
        return False
    return not (k is not None and (row_k(row) or "") != str(k))


def plan_is_direct(row: dict) -> bool:
    stats = row.get("plan_stats")
    return bool(isinstance(stats, dict) and stats.get("is_direct"))


def restatement_max(row: dict) -> float | None:
    stats = row.get("plan_stats")
    if not isinstance(stats, dict):
        return None
    v = stats.get("restatement_max")
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def restatement_bucket(v: float | None) -> str:
    if v is None:
        return "no_plan"
    for edge, label in RESTATEMENT_BINS:
        if v < edge:
            return label
    return RESTATEMENT_TOP


def did_leaf_work(row: dict) -> bool:
    """Evidence the episode reached stage 6 — i.e. stage 5 had already passed."""
    return _truthy_int(row.get("n_lemma_outcomes")) or _truthy_int(row.get("leaf_attempts_used"))


def stage1_class(row: dict) -> str:
    """`pass` | `direct_close` | `fail` | `ambiguous` | `not_evidence`.

    Decomposition-arm semantics only; the direct arm has no plan and its
    `leaf_failed` means "the root's own proof did not check" (eval/arms.py).
    """
    if row.get("arm") != "decomp":
        return "not_applicable"
    status = str(row.get("status") or "")
    if status in NOT_EVIDENCE:
        return "not_evidence"
    if status in STAGE1_PASSING:
        return "direct_close" if plan_is_direct(row) else "pass"
    if status in STAGE1_STRADDLING:
        if did_leaf_work(row):
            return "direct_close" if plan_is_direct(row) else "pass"
        return "ambiguous"
    return "fail"


def root_tokens(row: dict) -> tuple[int, int]:
    """(completion, total) tokens for one root call; (0, 0) when absent."""
    u = row.get("usage")
    if not isinstance(u, dict):
        return (0, 0)
    def _i(key: str) -> int:
        try:
            return int(u.get(key) or 0)
        except (TypeError, ValueError):
            return 0
    total = _i("total_tokens") or (_i("prompt_tokens") + _i("completion_tokens"))
    return (_i("completion_tokens"), total)


# ---------------------------------------------------------------------------
# Cell aggregation
# ---------------------------------------------------------------------------

@dataclass
class Cell:
    """One (root, arm, shot) group. `n` counts rows; `n_scored` counts the rows
    a mean reward may be taken over (the runner's `Totals` rule: `error` and
    `context_window_exceeded` are excluded)."""

    root: str
    arm: str
    shot: str
    n: int = 0
    n_scored: int = 0
    reward_sum: float = 0.0
    cost_usd: float = 0.0
    by_status: dict[str, int] = field(default_factory=dict)
    restatement_buckets: dict[str, int] = field(default_factory=dict)
    restatement_values: list[float] = field(default_factory=list)
    stage1: dict[str, int] = field(default_factory=dict)
    completion_tokens: list[int] = field(default_factory=list)
    total_tokens: list[int] = field(default_factory=list)
    ks: set[str] = field(default_factory=set)
    families: set[str] = field(default_factory=set)
    files: set[str] = field(default_factory=set)
    exemplars: list[dict] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.root, self.arm, self.shot)

    def add(self, row: dict, *, path: Path | str | None = None) -> None:
        self.n += 1
        status = str(row.get("status") or "unknown")
        self.by_status[status] = self.by_status.get(status, 0) + 1
        if path is not None:
            self.files.add(str(path))
        k = row_k(row)
        if k:
            self.ks.add(k)
        fam = row_family(row)
        if fam:
            self.families.add(fam)
        # Which worked example this cell was run with (rung 1.5 is only a
        # registrable result if the exemplar it used is on the record). A cell
        # with more than one distinct provenance was run twice with different
        # exemplars and is not one experiment — hence a list, not a scalar.
        ex = row.get("exemplar")
        if isinstance(ex, dict) and ex not in self.exemplars:
            self.exemplars.append(ex)

        cls = stage1_class(row)
        if cls != "not_applicable":
            self.stage1[cls] = self.stage1.get(cls, 0) + 1

        try:
            self.cost_usd += float(row.get("cost_usd") or 0.0)
        except (TypeError, ValueError):
            pass

        if status in NOT_EVIDENCE:
            return   # no reward, no tokens: not a measurement of the policy
        self.n_scored += 1
        try:
            self.reward_sum += float(row.get("reward") or 0.0)
        except (TypeError, ValueError):
            pass
        comp, total = root_tokens(row)
        self.completion_tokens.append(comp)
        self.total_tokens.append(total)
        if self.arm == "decomp":
            v = restatement_max(row)
            b = restatement_bucket(v)
            self.restatement_buckets[b] = self.restatement_buckets.get(b, 0) + 1
            if v is not None:
                self.restatement_values.append(v)

    def summary(self) -> dict:
        return {
            "root_model": self.root,
            "arm": self.arm,
            "shot": self.shot,
            "n": self.n,
            "n_scored": self.n_scored,
            "reward_sum": round(self.reward_sum, 4),
            "mean_reward": (round(self.reward_sum / self.n_scored, 4)
                            if self.n_scored else None),
            "cost_usd": round(self.cost_usd, 6),
            "by_status": dict(sorted(self.by_status.items())),
            "stage1": dict(sorted(self.stage1.items())),
            "restatement_max": {
                "buckets": dict(sorted(self.restatement_buckets.items())),
                "median": (round(median(self.restatement_values), 4)
                           if self.restatement_values else None),
                "max": (round(max(self.restatement_values), 4)
                        if self.restatement_values else None),
                "n": len(self.restatement_values),
            },
            "median_completion_tokens": (int(median(self.completion_tokens))
                                         if self.completion_tokens else None),
            "median_total_tokens": (int(median(self.total_tokens))
                                    if self.total_tokens else None),
            "k": sorted(self.ks),
            "family": sorted(self.families),
            "files": sorted(self.files),
            "exemplars": list(self.exemplars),
        }


def collect(paths: Iterable[Path], *, family: str | None, k: str | None) -> tuple[list[Cell], dict]:
    """Group every in-scope row into (root, arm, shot) cells."""
    cells: dict[tuple[str, str, str], Cell] = {}
    counts = {"rows": 0, "in_scope": 0, "out_of_scope": 0, "files": 0}
    for path in paths:
        rows = read_rows(path)
        if not rows:
            continue
        counts["files"] += 1
        parsed = parse_cell_name(Path(path).stem)
        for row in rows:
            counts["rows"] += 1
            if not in_scope(row, family=family, k=k):
                counts["out_of_scope"] += 1
                continue
            counts["in_scope"] += 1
            root = str(row.get("root_model") or parsed["root_slug"] or "unknown")
            arm = str(row.get("arm") or parsed["arm"] or "unknown")
            key = (root, arm, shot_of(row, path))
            cell = cells.get(key)
            if cell is None:
                cell = cells[key] = Cell(root=root, arm=arm, shot=key[2])
            cell.add(row, path=path)
    ordered = sorted(
        cells.values(),
        key=lambda c: (_root_order(c.root), c.root, c.arm != "decomp", c.shot != "fs"),
    )
    return ordered, counts


def _root_order(root: str) -> int:
    """Roster order first (cheapest-first, as run), then anything else."""
    return ROSTER_ROOTS.index(root) if root in ROSTER_ROOTS else len(ROSTER_ROOTS)


# ---------------------------------------------------------------------------
# The rung-1.5 verdict
# ---------------------------------------------------------------------------

def verdict(cells: Sequence[Cell], *, expected_roots: Sequence[str] = ROSTER_ROOTS,
            rl_target: str = RL_TARGET_ROOT, k_label: str = DEFAULT_K) -> dict:
    """Which roots produced a stage-1-passing decomposition few-shot?

    Statuses: `stage1_observed` | `no_stage1` | `inconclusive` |
    `insufficient_data`. The last three are all "not the positive result", and
    they are kept apart on purpose — only `no_stage1` is the registered evidence
    DIRECTION §5.5 says forces the next rung.
    """
    fs_decomp = {c.root: c for c in cells if c.arm == "decomp" and c.shot == "fs"}
    zs_decomp = {c.root: c for c in cells if c.arm == "decomp" and c.shot == "zs"}

    per_root: dict[str, dict] = {}
    observed = list(dict.fromkeys(list(expected_roots) + sorted(fs_decomp)))
    for root in observed:
        c = fs_decomp.get(root)
        s = dict(c.stage1) if c else {}
        per_root[root] = {
            "n": c.n if c else 0,
            "n_evidence": (c.n - s.get("not_evidence", 0)) if c else 0,
            "stage1_pass": s.get("pass", 0),
            "verified": (c.by_status.get("verified", 0) if c else 0),
            "direct_close": s.get("direct_close", 0),
            "ambiguous": s.get("ambiguous", 0),
            "pre_stage1_fail": s.get("fail", 0),
            "not_evidence": s.get("not_evidence", 0),
        }

    roots_with_stage1 = [r for r in observed if per_root[r]["stage1_pass"] > 0]
    roots_missing = [r for r in expected_roots if per_root.get(r, {}).get("n_evidence", 0) == 0]
    n_ambiguous = sum(per_root[r]["ambiguous"] for r in observed)

    control = None
    if rl_target in fs_decomp or rl_target in zs_decomp:
        fs_c, zs_c = fs_decomp.get(rl_target), zs_decomp.get(rl_target)
        control = {
            "root": rl_target,
            "fs_stage1_pass": fs_c.stage1.get("pass", 0) if fs_c else 0,
            "fs_n": fs_c.n if fs_c else 0,
            "zs_stage1_pass": zs_c.stage1.get("pass", 0) if zs_c else 0,
            "zs_n": zs_c.n if zs_c else 0,
        }
        control["delta_stage1_pass"] = control["fs_stage1_pass"] - control["zs_stage1_pass"]

    at_k = f"at k={k_label}" if k_label else "at the k in scope"
    if roots_with_stage1:
        status = "stage1_observed"
        who = ", ".join(roots_with_stage1)
        if rl_target in roots_with_stage1:
            line = (f"STAGE-1-PASSING DECOMPOSITIONS few-shot {at_k} from: {who}. "
                    f"The RL target ({rl_target}) is among them — per DIRECTION §5.5 the "
                    "cold-start problem was a prompt gap; rung 1.5 suffices and priors "
                    "barely move. Do not escalate to warm-up.")
        else:
            line = (f"STAGE-1-PASSING DECOMPOSITIONS few-shot {at_k} from: {who} — but NOT "
                    f"from the RL target ({rl_target}). The affordance exists and is "
                    "learnable-in-principle at this k, so the negative rung-1.5 finding is "
                    "NOT registered; the gap is at the trainable root, which is a rung-2 "
                    "(format warm-up) question, not yet rung 3.")
    elif roots_missing:
        status = "insufficient_data"
        line = ("NO VERDICT: the roster is incomplete — no few-shot decomp evidence rows for "
                + ", ".join(roots_missing)
                + ". 'No root decomposed' is only evidence when every root actually ran.")
    elif n_ambiguous:
        status = "inconclusive"
        line = (f"INCONCLUSIVE: no clean stage-1 pass, but {n_ambiguous} episode(s) ended in a "
                "status that straddles the stage-1 check (budget_exhausted / "
                "sanitizer_rejected) with no leaf work recorded. Read those rows' `detail` "
                "before registering anything.")
    elif not any(per_root[r]["n_evidence"] for r in observed):
        status = "insufficient_data"
        line = "NO VERDICT: no few-shot decomp episodes found in scope."
    else:
        status = "no_stage1"
        n = sum(per_root[r]["n_evidence"] for r in observed)
        # Naming the ceiling only when it actually ran: "even opus failed" is the
        # load-bearing half of this finding and must not be implied by default.
        ran_ceiling = bool(per_root.get(CEILING_ROOT, {}).get("n_evidence"))
        ceiling = ", incl. the frontier ceiling" if ran_ceiling else ""
        line = (f"NO ROOT produced a stage-1-passing decomposition few-shot {at_k} "
                f"({n} episodes across {len(observed)} roots{ceiling}). "
                "Per DIRECTION §5.5 this is registered evidence that rung 1.5 does not clear "
                "the cold start and rung 3 (strategy distillation) is unavoidable — "
                "re-register the affected §4 priors before acting on it.")

    if status == "stage1_observed" and roots_missing:
        line += " PROVISIONAL — missing roster cells: " + ", ".join(roots_missing) + "."

    return {
        "question": ("DIRECTION §5.5 rung 1.5: does any root emit a stage-1-passing "
                     "decomposition (VERIFIED or plan-valid-but-leaf_failed) few-shot at k=2?"),
        "stage1_passing_statuses": sorted(STAGE1_PASSING),
        "status": status,
        "line": line,
        "roots_with_stage1": roots_with_stage1,
        "roots_missing_cells": roots_missing,
        "n_ambiguous": n_ambiguous,
        "rl_target": rl_target,
        "paired_control": control,
        "per_root": per_root,
    }


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def _fmt(v, nd: int = 3) -> str:
    if v is None:
        return "-"
    return f"{v:.{nd}f}" if isinstance(v, float) else str(v)


def format_table(summaries: Sequence[dict]) -> str:
    """The roster table: one line per (root, arm, shot) cell."""
    head = (f"{'ROOT':34} {'ARM':7} {'SHOT':4} {'N':>3} {'SCD':>3} {'REW':>5} {'COST$':>7} "
            f"{'MEDout':>6} {'MEDtot':>6} {'RSTmed':>6} {'RSTmax':>6} {'STAGE1':>8}")
    lines = [head, "-" * len(head)]
    for s in summaries:
        st = s["stage1"]
        stage1 = ("-" if s["arm"] != "decomp"
                  else f"{st.get('pass', 0)}/{s['n'] - st.get('not_evidence', 0)}")
        lines.append(
            f"{s['root_model'][:34]:34} {s['arm'][:7]:7} {s['shot']:4} "
            f"{s['n']:>3} {s['n_scored']:>3} {_fmt(s['reward_sum'], 1):>5} "
            f"{_fmt(s['cost_usd'], 4):>7} "
            f"{_fmt(s['median_completion_tokens']):>6} {_fmt(s['median_total_tokens']):>6} "
            f"{_fmt(s['restatement_max']['median'], 2):>6} "
            f"{_fmt(s['restatement_max']['max'], 2):>6} {stage1:>8}"
        )
    return "\n".join(lines)


def format_details(summaries: Sequence[dict]) -> str:
    """Status and restatement distributions — the §6 separation, per cell."""
    lines = ["", "status distribution (§6: feasibility / policy / infra never share a bucket)"]
    for s in summaries:
        dist = ", ".join(f"{k}={v}" for k, v in s["by_status"].items()) or "none"
        lines.append(f"  {s['shot']} {s['arm']:7} {s['root_model'][:34]:34} {dist}")
    lines += ["", "restatement_max distribution (decomp cells; §5.7 P4 instrument)"]
    any_r = False
    for s in summaries:
        if s["arm"] != "decomp":
            continue
        any_r = True
        dist = ", ".join(f"{k}={v}" for k, v in s["restatement_max"]["buckets"].items()) or "none"
        lines.append(f"  {s['shot']} {s['root_model'][:34]:34} {dist}")
    if not any_r:
        lines.append("  (no decomp cells in scope)")
    return "\n".join(lines)


def warnings_for(summaries: Sequence[dict]) -> list[str]:
    """Cell-level "this is not one experiment" checks, reported, never fixed."""
    out: list[str] = []
    for s in summaries:
        who = f"{s['shot']} {s['arm']} {s['root_model']}"
        if len(s["k"]) > 1:
            out.append(f"{who}: mixes k={','.join(s['k'])} in one cell")
        if len(s["family"]) > 1:
            out.append(f"{who}: mixes families {','.join(s['family'])} in one cell")
        if len(s["exemplars"]) > 1:
            out.append(f"{who}: {len(s['exemplars'])} distinct exemplars — the cell was run "
                       "with more than one worked example")
        if s["shot"] == "fs" and not s["exemplars"]:
            out.append(f"{who}: few-shot cell with no exemplar provenance on its rows "
                       "(pre-rung-1.5 runner, or the shot label came from the filename)")
    return out


def format_verdict(v: dict) -> str:
    lines = ["", "== VERDICT (DIRECTION §5.5 rung 1.5)", f"   {v['status'].upper()}: {v['line']}",
             "", "   per root (few-shot decomp cells):",
             f"   {'root':34} {'n':>3} {'pass':>4} {'verif':>5} {'direct':>6} "
             f"{'ambig':>5} {'pre-s1':>6} {'infra':>5}"]
    for root, r in v["per_root"].items():
        lines.append(
            f"   {root[:34]:34} {r['n']:>3} {r['stage1_pass']:>4} {r['verified']:>5} "
            f"{r['direct_close']:>6} {r['ambiguous']:>5} {r['pre_stage1_fail']:>6} "
            f"{r['not_evidence']:>5}"
        )
    c = v.get("paired_control")
    if c:
        lines += ["", f"   paired control ({c['root']}): "
                      f"few-shot {c['fs_stage1_pass']}/{c['fs_n']} stage-1 passes vs "
                      f"zero-shot {c['zs_stage1_pass']}/{c['zs_n']} "
                      f"(delta {c['delta_stage1_pass']:+d})"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def resolve_paths(args) -> list[Path]:
    if args.paths:
        out: list[Path] = []
        for p in args.paths:
            expanded = sorted(glob.glob(p)) or [p]     # already-expanded by the shell, usually
            out.extend(Path(x) for x in expanded)
        return [p for p in out if p.suffix == ".jsonl" or p.exists()]
    return sorted(Path(args.results_dir).glob("*.jsonl"))


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Roster table + rung-1.5 verdict over results/zeroshot cells "
                    "(DIRECTION.md §5.5 cold-start ladder).",
    )
    p.add_argument("paths", nargs="*", help="cell JSONLs (default: every file in --results-dir)")
    p.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR, dest="results_dir")
    p.add_argument("--family", default=DEFAULT_FAMILY,
                   help=f"scope to one family, or 'any' (default {DEFAULT_FAMILY})")
    p.add_argument("--k", default=DEFAULT_K,
                   help=f"scope to one k, or 'any' (default {DEFAULT_K})")
    p.add_argument("--expect-root", action="append", default=None, dest="expect_roots",
                   metavar="MODEL",
                   help="roster root that must have run before a negative verdict is "
                        "registered (repeatable; defaults to the four pre-registered roots)")
    p.add_argument("--rl-target", default=RL_TARGET_ROOT, dest="rl_target",
                   help="the root Phase 3 would train (its result drives the verdict wording)")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="JSON report path")
    p.add_argument("--no-write", action="store_true", dest="no_write",
                   help="print only; do not write the JSON report")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    family = None if str(args.family).lower() == "any" else args.family
    k = None if str(args.k).lower() == "any" else str(args.k)
    expected = tuple(args.expect_roots) if args.expect_roots else ROSTER_ROOTS

    paths = resolve_paths(args)
    cells, counts = collect(paths, family=family, k=k)
    summaries = [c.summary() for c in cells]
    v = verdict(cells, expected_roots=expected, rl_target=args.rl_target, k_label=k or "")
    warns = warnings_for(summaries)

    scope = (f"scope: family={family or 'any'} k={k or 'any'} | "
             f"{counts['in_scope']} rows in scope, {counts['out_of_scope']} out, "
             f"{counts['files']} file(s)")
    print(scope)
    print(format_table(summaries))
    print(format_details(summaries))
    if warns:
        print("\ncell warnings")
        for w in warns:
            print(f"  ! {w}")
    print(format_verdict(v))

    report = {
        "generated_by": "scripts/roster_analyze.py",
        "direction_ref": "DIRECTION.md §5.5 cold-start ladder, rung 1.5",
        "scope": {
            "family": family, "k": k,
            "results": [str(p) for p in paths],
            **counts,
        },
        "expected_roots": list(expected),
        "cells": summaries,
        "warnings": warns,
        "verdict": v,
    }
    if not args.no_write:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
