"""Unit tests for scripts/roster_analyze.py — the rung-1.5 roster reader.

Entirely offline against synthetic rows: the analyzer reads JSONL that
`scripts/run_zeroshot.py` already wrote, so there is no model, no kernel and no
network anywhere in this file, and no GPU leaf is required (none exists today).

What is actually being pinned here is the *verdict logic*, because that is the
thing that gets quoted into DIRECTION.md: a "no root decomposed" line is
registered evidence that forces rung 3, so the tests assert that it can only be
produced from complete, unambiguous cells — and that the three near-misses
(missing cells, straddling statuses, direct-close "decompositions") each land in
their own bucket instead.

The script is loaded by path because scripts/ is not a package (same trick as
tests/test_scripts.py).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_script_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    # Registered before exec (tests/test_zeroshot.py's note): `@dataclass`
    # resolves annotations through `sys.modules[cls.__module__]`, which is
    # absent for a path-loaded module and raises during class creation.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


ra = _load("roster_analyze")

QWEN = "qwen/qwen3-30b-a3b-instruct-2507"      # the RL target
BIG = "Qwen/Qwen3.5-122B-A10B"
HAIKU = "anthropic/claude-haiku-4.5"
OPUS = "anthropic/claude-opus-5"

# eval/exemplars.exemplar_provenance shape (what --few-shot writes on each row)
EXEMPLAR = {
    "arm": "decomp", "family": "bridge_chain", "k": 2, "seed": 999,
    "problem_id": "bridge_chain-k2-s999-0", "goal_statement_key": "86514aa7879eb3dd",
    "goal_name": "bridge_k2_s999_0", "chars": 1003,
}


# ---------------------------------------------------------------------------
# Row builders (shaped exactly like run_zeroshot.base_row + outcome_row)
# ---------------------------------------------------------------------------

def row(
    *,
    root=QWEN,
    arm="decomp",
    status="plan_invalid",
    reward=0.0,
    k=2,
    family="bridge_chain",
    problem_set="bridge_chain",
    restatement=0.87,
    n_lemmas=2,
    is_direct=False,
    plan_stats="auto",
    n_lemma_outcomes=0,
    leaf_attempts_used=0,
    prompt_tokens=700,
    completion_tokens=120,
    cost_usd=0.0002,
    rid="p0",
    **extra,
):
    if plan_stats == "auto":
        plan_stats = (
            None if arm != "decomp" or status == "format_error"
            else {
                "n_lemmas": n_lemmas,
                "mean_prop_chars": 130.0,
                "max_prop_chars": 137,
                "restatement_max": restatement,
                "is_direct": is_direct,
            }
        )
    r = {
        "id": rid,
        "problem_set": problem_set,
        "k": k,
        "k_cell": str(k),
        "family": family,
        "arm": arm,
        "root_model": root,
        "status": status,
        "reward": reward,
        "plan_stats": plan_stats,
        "n_lemma_outcomes": n_lemma_outcomes,
        "leaf_attempts_used": leaf_attempts_used,
        "cost_usd": cost_usd,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "source": "api",
        },
    }
    r.update(extra)
    return r


def write_cell(dirpath: Path, name: str, rows) -> Path:
    path = Path(dirpath) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def cells_for(rows, *, family="bridge_chain", k="2"):
    """Group synthetic rows with no file on disk (path-free path of `collect`)."""
    grouped: dict[tuple[str, str, str], ra.Cell] = {}
    for r in rows:
        if not ra.in_scope(r, family=family, k=k):
            continue
        key = (r["root_model"], r["arm"], ra.shot_of(r))
        c = grouped.setdefault(key, ra.Cell(root=key[0], arm=key[1], shot=key[2]))
        c.add(r)
    return list(grouped.values())


# ---------------------------------------------------------------------------
# fs / zs identification
# ---------------------------------------------------------------------------

def test_shot_from_the_runners_few_shot_column():
    """The contract run_zeroshot.py actually writes: `few_shot` on every row."""
    assert ra.shot_of(row(few_shot=True, exemplar=EXEMPLAR)) == "fs"
    assert ra.shot_of(row(few_shot=False, exemplar=None)) == "zs"


def test_shot_from_problem_set_token():
    assert ra.shot_of(row(problem_set="bridge_chain_fs")) == "fs"
    assert ra.shot_of(row(problem_set="bridge_chain")) == "zs"


def test_shot_from_filename_when_row_is_silent():
    """The runner's marker sits on the arm segment: `..._k2_fs-decomp_<root>`."""
    marked = Path("results/zeroshot/bridge_chain_k2_fs-decomp_qwen-qwen3-30b.jsonl")
    assert ra.shot_of({"problem_set": None}, marked) == "fs"
    assert ra.shot_of({}, Path("results/zeroshot/bridge_chain_k2_decomp_qwen.jsonl")) == "zs"
    # a set-name marker (what a hand-run cell might use) still works
    assert ra.shot_of({}, Path("bridge_chain_fs_k2_decomp_qwen.jsonl")) == "fs"


def test_exemplar_block_alone_marks_a_row_few_shot():
    assert ra.shot_of({"exemplar": EXEMPLAR}) == "fs"
    assert ra.shot_of({"exemplar": None}) == "zs"


def test_explicit_row_field_beats_the_filename():
    """A field the runner wrote is a measurement; a filename is a convention."""
    p = Path("bridge_chain_fs_k2_decomp_qwen.jsonl")
    assert ra.shot_of({"few_shot": False, "problem_set": "bridge_chain_fs"}, p) == "zs"
    assert ra.shot_of({"few_shot": True}, Path("bridge_chain_k2_decomp_qwen.jsonl")) == "fs"


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("n_exemplars", 1, "fs"),
        ("n_exemplars", 0, "zs"),
        ("num_exemplars", 2, "fs"),
        ("exemplars", ["one worked decomposition"], "fs"),
        ("exemplars", [], "zs"),
        ("exemplar_ids", ["bridge_chain-k2-s7-0"], "fs"),
        ("few_shot_enabled", True, "fs"),
    ],
)
def test_shot_from_the_various_flag_shapes_the_sibling_might_write(field, value, expected):
    assert ra.shot_of({field: value}) == expected


def test_base_set_name_strips_only_the_shot_marker():
    assert ra.base_set_name("bridge_chain_fs") == "bridge_chain"
    assert ra.base_set_name("bridge_chain") == "bridge_chain"
    assert ra.base_set_name("case_tree_fewshot") == "case_tree"
    assert ra.base_set_name(None) == ""


# ---------------------------------------------------------------------------
# Cell-name parsing (fallback only — rows normally carry arm/root_model)
# ---------------------------------------------------------------------------

def test_parse_cell_name_roundtrips_the_runners_layout():
    got = ra.parse_cell_name("bridge_chain_k2_decomp_qwen-qwen3-30b-a3b-instruct-2507")
    assert got == {
        "problem_set": "bridge_chain",
        "k": "2",
        "arm": "decomp",
        "few_shot": False,
        "root_slug": "qwen-qwen3-30b-a3b-instruct-2507",
    }


def test_parse_cell_name_strips_the_fs_marker_off_the_arm():
    """`--few-shot` marks the arm segment; the arm itself is still `decomp`."""
    got = ra.parse_cell_name("bridge_chain_k2_fs-decomp_anthropic-claude-opus-5")
    assert got["arm"] == "decomp" and got["few_shot"] is True
    assert got["problem_set"] == "bridge_chain"
    assert got["root_slug"] == "anthropic-claude-opus-5"
    assert ra.parse_cell_name("bridge_chain_k2_decomp_m")["few_shot"] is False


def test_parse_cell_name_handles_underscored_sets_and_arms():
    fs = ra.parse_cell_name("bridge_chain_fs_k2_direct_anthropic-claude-opus-5")
    assert fs["problem_set"] == "bridge_chain_fs" and fs["arm"] == "direct"
    assert fs["root_slug"] == "anthropic-claude-opus-5"
    # a future multi-token arm must not be truncated to its first token
    future = ra.parse_cell_name("bridge_chain_k4_flat_best_of_n_some-model")
    assert future["arm"] == "flat_best_of_n" and future["root_slug"] == "some-model"
    marked = ra.parse_cell_name("bridge_chain_k4_fs-flat_best_of_n_some-model")
    assert marked["arm"] == "flat_best_of_n" and marked["few_shot"] is True


def test_parse_cell_name_accepts_mix_and_na_k_labels():
    assert ra.parse_cell_name("bank_kna_direct_m")["k"] == "na"
    assert ra.parse_cell_name("bank_kmix_direct_m")["k"] == "mix"
    assert ra.parse_cell_name("no-k-marker-here")["k"] is None


# ---------------------------------------------------------------------------
# Restatement bins
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value,bucket",
    [
        (None, "no_plan"), (0.0, "<0.5"), (0.4999, "<0.5"), (0.5, "0.5-0.8"),
        (0.79, "0.5-0.8"), (0.8, "0.8-0.95"), (0.9499, "0.8-0.95"),
        (0.95, ">=0.95"), (1.0, ">=0.95"),
    ],
)
def test_restatement_buckets(value, bucket):
    assert ra.restatement_bucket(value) == bucket


def test_restatement_max_reads_plan_stats_and_tolerates_absence():
    assert ra.restatement_max(row(restatement=0.42)) == pytest.approx(0.42)
    assert ra.restatement_max(row(arm="direct", plan_stats=None)) is None
    assert ra.restatement_max({"plan_stats": {"restatement_max": None}}) is None


# ---------------------------------------------------------------------------
# Stage-1 classification — the heart of the diagnostic
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "status,expected",
    [
        ("verified", "pass"),
        ("leaf_failed", "pass"),          # plan valid, the LEAF is what failed
        ("compose_failed", "pass"),
        ("plan_invalid", "fail"),         # the measured smoke failure (12/12)
        ("format_error", "fail"),
        ("statement_ill_formed", "fail"),
        ("error", "not_evidence"),
        ("context_window_exceeded", "not_evidence"),
    ],
)
def test_stage1_class_by_status(status, expected):
    assert ra.stage1_class(row(status=status)) == expected


def test_direct_close_is_not_a_decomposition():
    """A no-lemma plan that proves the goal outright answers a different question."""
    r = row(status="verified", reward=1.0, is_direct=True, n_lemmas=0)
    assert ra.stage1_class(r) == "direct_close"


def test_straddling_statuses_resolve_on_evidence_of_leaf_work():
    # budget_exhausted at stage 3 (too many lemmas): stage 1 never ran
    assert ra.stage1_class(row(status="budget_exhausted")) == "ambiguous"
    # budget_exhausted at stage 6: leaves were attempted, so stage 1 had passed
    assert ra.stage1_class(row(status="budget_exhausted", n_lemma_outcomes=1)) == "pass"
    assert ra.stage1_class(row(status="budget_exhausted", leaf_attempts_used=4)) == "pass"
    # sanitizer_rejected: stage 2 (the plan text) vs stage 7/8 (the artifact)
    assert ra.stage1_class(row(status="sanitizer_rejected")) == "ambiguous"
    assert ra.stage1_class(row(status="sanitizer_rejected", n_lemma_outcomes=2)) == "pass"


def test_direct_arm_rows_are_never_classified():
    """`leaf_failed` in the direct arm means the ROOT's own proof failed."""
    assert ra.stage1_class(row(arm="direct", status="leaf_failed")) == "not_applicable"
    assert ra.stage1_class(row(arm="direct", status="verified")) == "not_applicable"


# ---------------------------------------------------------------------------
# Cell aggregation
# ---------------------------------------------------------------------------

def test_cell_counts_rewards_statuses_and_tokens():
    c = ra.Cell(root=QWEN, arm="decomp", shot="fs")
    c.add(row(status="verified", reward=1.0, completion_tokens=100, cost_usd=0.01))
    c.add(row(status="leaf_failed", completion_tokens=200, cost_usd=0.02))
    c.add(row(status="plan_invalid", completion_tokens=300, cost_usd=0.03))
    s = c.summary()
    assert s["n"] == 3 and s["n_scored"] == 3
    assert s["reward_sum"] == 1.0 and s["mean_reward"] == pytest.approx(1 / 3, abs=1e-4)
    assert s["by_status"] == {"leaf_failed": 1, "plan_invalid": 1, "verified": 1}
    assert s["stage1"] == {"pass": 2, "fail": 1}
    assert s["median_completion_tokens"] == 200
    assert s["median_total_tokens"] == 900
    assert s["cost_usd"] == pytest.approx(0.06)


def test_error_and_window_rows_are_excluded_from_scores_and_token_medians():
    """The runner's own rule (Totals): infra failure and feasibility evidence
    are counted, never averaged (DIRECTION §6)."""
    c = ra.Cell(root=QWEN, arm="decomp", shot="fs")
    c.add(row(status="plan_invalid", completion_tokens=100))
    c.add(row(status="error", plan_stats=None, completion_tokens=0,
              prompt_tokens=0, cost_usd=0.0))
    c.add(row(status="context_window_exceeded", plan_stats=None, completion_tokens=0,
              prompt_tokens=0, cost_usd=0.0))
    s = c.summary()
    assert s["n"] == 3 and s["n_scored"] == 1
    assert s["median_completion_tokens"] == 100      # not dragged to 0 by the two
    assert s["by_status"]["error"] == 1 and s["by_status"]["context_window_exceeded"] == 1
    assert s["stage1"] == {"fail": 1, "not_evidence": 2}


def test_restatement_distribution_only_for_decomp_cells():
    d = ra.Cell(root=QWEN, arm="decomp", shot="fs")
    d.add(row(restatement=0.99))
    d.add(row(restatement=0.30))
    d.add(row(status="format_error", plan_stats=None))
    s = d.summary()
    assert s["restatement_max"]["buckets"] == {">=0.95": 1, "<0.5": 1, "no_plan": 1}
    assert s["restatement_max"]["median"] == pytest.approx(0.645)
    assert s["restatement_max"]["max"] == pytest.approx(0.99)
    assert s["restatement_max"]["n"] == 2

    f = ra.Cell(root=QWEN, arm="direct", shot="fs")
    f.add(row(arm="direct", status="leaf_failed", plan_stats=None))
    assert f.summary()["restatement_max"] == {"buckets": {}, "median": None, "max": None, "n": 0}


def test_collect_groups_by_root_arm_shot_and_honors_scope(tmp_path):
    write_cell(tmp_path, "bridge_chain_k2_fs-decomp_qwen.jsonl", [
        row(few_shot=True, exemplar=EXEMPLAR, rid="a"),
        row(few_shot=True, exemplar=EXEMPLAR, rid="b", status="leaf_failed"),
    ])
    write_cell(tmp_path, "bridge_chain_k2_decomp_qwen.jsonl", [
        row(rid="c"), row(rid="d"),
    ])
    write_cell(tmp_path, "bridge_chain_k4_fs-decomp_qwen.jsonl", [
        row(few_shot=True, exemplar=EXEMPLAR, k=4, rid="e"),
    ])
    write_cell(tmp_path, "case_tree_k2_fs-decomp_qwen.jsonl", [
        row(few_shot=True, exemplar=EXEMPLAR, family="case_tree", rid="f"),
    ])
    cells, counts = ra.collect(sorted(tmp_path.glob("*.jsonl")), family="bridge_chain", k="2")
    assert counts == {"rows": 6, "in_scope": 4, "out_of_scope": 2, "files": 4}
    assert {(c.root, c.arm, c.shot, c.n) for c in cells} == {
        (QWEN, "decomp", "fs", 2), (QWEN, "decomp", "zs", 2),
    }

    every, counts_any = ra.collect(sorted(tmp_path.glob("*.jsonl")), family=None, k=None)
    assert counts_any["in_scope"] == 6
    assert sum(c.n for c in every) == 6


def test_read_rows_survives_a_torn_last_line(tmp_path):
    p = tmp_path / "cell.jsonl"
    p.write_text(json.dumps(row(rid="ok")) + '\n{"id": "torn", "sta', encoding="utf-8")
    assert [r["id"] for r in ra.read_rows(p)] == ["ok"]
    assert ra.read_rows(tmp_path / "missing.jsonl") == []


def test_root_and_arm_fall_back_to_the_filename(tmp_path):
    write_cell(tmp_path, "bridge_chain_k2_fs-decomp_anthropic-claude-opus-5.jsonl",
               [{"id": "x", "status": "plan_invalid", "k": 2, "family": "bridge_chain"}])
    cells, _ = ra.collect(sorted(tmp_path.glob("*.jsonl")), family="bridge_chain", k="2")
    assert (cells[0].root, cells[0].arm, cells[0].shot) == (
        "anthropic-claude-opus-5", "decomp", "fs")


# ---------------------------------------------------------------------------
# Verdict rules
# ---------------------------------------------------------------------------

def fs_rows(root, statuses, **kw):
    """Few-shot rows exactly as run_zeroshot.py writes them (`few_shot` + provenance)."""
    return [row(root=root, few_shot=True, exemplar=EXEMPLAR, status=s, rid=f"{root}-{i}", **kw)
            for i, s in enumerate(statuses)]


def full_roster(status_by_root, **kw):
    rows = []
    for r, statuses in status_by_root.items():
        rows += fs_rows(r, statuses, **kw)
    return cells_for(rows)


def test_no_root_decomposes_is_the_registered_negative():
    cells = full_roster({r: ["plan_invalid"] * 3 for r in ra.ROSTER_ROOTS})
    v = ra.verdict(cells)
    assert v["status"] == "no_stage1"
    assert v["roots_with_stage1"] == [] and v["roots_missing_cells"] == []
    assert "rung 3" in v["line"] and "12 episodes" in v["line"]
    assert "at k=2" in v["line"]
    assert "frontier ceiling" in v["line"]         # opus ran, so the claim is earned
    assert all(pr["pre_stage1_fail"] == 3 for pr in v["per_root"].values())


def test_the_ceiling_claim_is_dropped_when_the_ceiling_did_not_run():
    """"Even opus failed" is the load-bearing half — never implied by default."""
    roots = tuple(r for r in ra.ROSTER_ROOTS if r != OPUS)
    v = ra.verdict(full_roster({r: ["plan_invalid"] for r in roots}), expected_roots=roots)
    assert v["status"] == "no_stage1" and "frontier ceiling" not in v["line"]


def test_verdict_wording_follows_the_k_in_scope():
    cells = full_roster({r: ["plan_invalid"] for r in ra.ROSTER_ROOTS})
    assert "at k=4" in ra.verdict(cells, k_label="4")["line"]
    assert "at the k in scope" in ra.verdict(cells, k_label="")["line"]


def test_missing_cells_never_produce_the_negative_verdict():
    """The failure mode this guards: a roster that half-ran reading as evidence."""
    partial = {r: ["plan_invalid"] * 3 for r in ra.ROSTER_ROOTS[:2]}
    v = ra.verdict(full_roster(partial))
    assert v["status"] == "insufficient_data"
    assert v["roots_missing_cells"] == [HAIKU, OPUS]
    assert "only evidence when every root actually ran" in v["line"]


def test_a_root_with_only_infra_errors_counts_as_missing():
    statuses = {r: ["plan_invalid"] for r in ra.ROSTER_ROOTS}
    statuses[OPUS] = ["error", "error"]
    v = ra.verdict(full_roster(statuses))
    assert v["status"] == "insufficient_data" and v["roots_missing_cells"] == [OPUS]
    assert v["per_root"][OPUS] == {
        "n": 2, "n_evidence": 0, "stage1_pass": 0, "verified": 0, "direct_close": 0,
        "ambiguous": 0, "pre_stage1_fail": 0, "not_evidence": 2,
    }


def test_rl_target_assembling_is_the_prompt_gap_verdict():
    statuses = {r: ["plan_invalid"] * 2 for r in ra.ROSTER_ROOTS}
    statuses[QWEN] = ["plan_invalid", "leaf_failed"]
    v = ra.verdict(full_roster(statuses))
    assert v["status"] == "stage1_observed"
    assert v["roots_with_stage1"] == [QWEN]
    assert "prompt gap" in v["line"] and "priors" in v["line"]


def test_ceiling_only_pass_does_not_register_the_negative_but_names_the_gap():
    statuses = {r: ["plan_invalid"] * 2 for r in ra.ROSTER_ROOTS}
    statuses[OPUS] = ["verified", "leaf_failed"]
    v = ra.verdict(full_roster(statuses))
    assert v["status"] == "stage1_observed" and v["roots_with_stage1"] == [OPUS]
    assert "NOT" in v["line"] and QWEN in v["line"] and "rung-2" in v["line"]
    assert v["per_root"][OPUS]["stage1_pass"] == 2
    assert v["per_root"][OPUS]["verified"] == 1


def test_direct_close_verified_does_not_count_as_decomposing():
    statuses = {r: ["plan_invalid"] for r in ra.ROSTER_ROOTS}
    cells = cells_for(
        [r for root, ss in statuses.items() for r in fs_rows(root, ss)]
        + fs_rows(OPUS, ["verified"], reward=1.0, is_direct=True, n_lemmas=0)
    )
    v = ra.verdict(cells)
    assert v["status"] == "no_stage1"
    assert v["per_root"][OPUS]["direct_close"] == 1 and v["per_root"][OPUS]["stage1_pass"] == 0
    assert v["per_root"][OPUS]["verified"] == 1     # still visible, just not as evidence


def test_straddling_statuses_alone_are_inconclusive_not_negative():
    statuses = {r: ["plan_invalid"] for r in ra.ROSTER_ROOTS}
    statuses[HAIKU] = ["plan_invalid", "budget_exhausted"]
    v = ra.verdict(full_roster(statuses))
    assert v["status"] == "inconclusive" and v["n_ambiguous"] == 1
    assert "detail" in v["line"]


def test_provisional_when_a_pass_coexists_with_missing_cells():
    v = ra.verdict(full_roster({QWEN: ["leaf_failed"], BIG: ["plan_invalid"]}))
    assert v["status"] == "stage1_observed"
    assert "PROVISIONAL" in v["line"] and HAIKU in v["line"]


def test_paired_control_reports_the_few_shot_delta():
    cells = cells_for(
        fs_rows(QWEN, ["leaf_failed", "verified", "plan_invalid"])
        + [row(root=QWEN, rid=f"zs{i}") for i in range(3)]        # zero-shot control
    )
    v = ra.verdict(cells)
    assert v["paired_control"] == {
        "root": QWEN, "fs_stage1_pass": 2, "fs_n": 3,
        "zs_stage1_pass": 0, "zs_n": 3, "delta_stage1_pass": 2,
    }


def test_empty_scope_is_insufficient_not_negative():
    v = ra.verdict([])
    assert v["status"] == "insufficient_data"
    assert v["roots_missing_cells"] == list(ra.ROSTER_ROOTS)


def test_expected_roots_and_rl_target_are_overridable():
    v = ra.verdict(full_roster({BIG: ["leaf_failed"]}), expected_roots=(BIG,), rl_target=BIG)
    assert v["status"] == "stage1_observed" and "prompt gap" in v["line"]
    assert v["roots_missing_cells"] == [] and "PROVISIONAL" not in v["line"]


def test_direct_arm_rows_do_not_enter_the_verdict():
    cells = cells_for(
        [row(root=r, arm="direct", status="verified", reward=1.0, plan_stats=None,
             few_shot=True, exemplar={**EXEMPLAR, "arm": "direct"}, rid=f"d{i}")
         for i, r in enumerate(ra.ROSTER_ROOTS)]
    )
    v = ra.verdict(cells)
    assert v["status"] == "insufficient_data"     # no decomp evidence anywhere
    assert v["roots_with_stage1"] == []


# ---------------------------------------------------------------------------
# Rendering + CLI
# ---------------------------------------------------------------------------

def test_table_marks_stage1_only_for_decomp_cells():
    cells = cells_for(
        fs_rows(QWEN, ["leaf_failed", "plan_invalid", "error"])
        + [row(root=QWEN, arm="direct", status="leaf_failed", plan_stats=None,
               few_shot=True, exemplar={**EXEMPLAR, "arm": "direct"}, rid="d0")]
    )
    text = ra.format_table([c.summary() for c in cells])
    lines = [line for line in text.splitlines() if QWEN in line]
    decomp = next(line for line in lines if " decomp " in line)
    direct = next(line for line in lines if " direct " in line)
    assert decomp.split()[-1] == "1/2"     # 1 pass out of 2 evidence rows (error excluded)
    assert direct.split()[-1] == "-"


def test_warnings_name_the_cells_that_are_not_one_experiment():
    mixed_k = ra.Cell(root=QWEN, arm="decomp", shot="fs")
    mixed_k.add(row(few_shot=True, exemplar=EXEMPLAR, k=2))
    mixed_k.add(row(few_shot=True, exemplar={**EXEMPLAR, "seed": 1234}, k=4))
    warns = ra.warnings_for([mixed_k.summary()])
    assert any("mixes k=2,4" in w for w in warns)
    assert any("2 distinct exemplars" in w for w in warns)

    unprovenanced = ra.Cell(root=QWEN, arm="decomp", shot="fs")
    unprovenanced.add(row(problem_set="bridge_chain_fs"))     # shot from the name only
    assert any("no exemplar provenance" in w for w in ra.warnings_for(
        [unprovenanced.summary()]))

    clean = ra.Cell(root=QWEN, arm="decomp", shot="fs")
    clean.add(row(few_shot=True, exemplar=EXEMPLAR))
    clean.add(row(few_shot=True, exemplar=dict(EXEMPLAR), status="leaf_failed"))
    assert ra.warnings_for([clean.summary()]) == []


def test_cell_records_distinct_exemplar_provenance():
    c = ra.Cell(root=QWEN, arm="decomp", shot="fs")
    c.add(row(few_shot=True, exemplar=EXEMPLAR))
    c.add(row(few_shot=True, exemplar=dict(EXEMPLAR)))        # same example, new dict
    assert c.summary()["exemplars"] == [EXEMPLAR]
    assert ra.Cell(root=QWEN, arm="decomp", shot="zs").summary()["exemplars"] == []


def test_format_helpers_survive_an_empty_roster():
    assert ra.format_table([]).splitlines()[0].startswith("ROOT")
    assert "no decomp cells in scope" in ra.format_details([])
    assert "VERDICT" in ra.format_verdict(ra.verdict([]))


def test_main_writes_the_report_and_prints_the_table(tmp_path, capsys):
    results = tmp_path / "zeroshot"
    write_cell(results, "bridge_chain_k2_fs-decomp_qwen.jsonl",
               fs_rows(QWEN, ["leaf_failed", "plan_invalid"]))
    write_cell(results, "bridge_chain_k2_decomp_qwen.jsonl",
               [row(root=QWEN, rid="zs0"), row(root=QWEN, rid="zs1")])
    write_cell(results, "bridge_chain_k2_fs-direct_qwen.jsonl",
               [row(root=QWEN, arm="direct", status="sanitizer_rejected", plan_stats=None,
                    few_shot=True, exemplar={**EXEMPLAR, "arm": "direct"}, rid="d0")])
    out = tmp_path / "roster.json"

    rc = ra.main(["--results-dir", str(results), "--out", str(out)])
    assert rc == 0

    printed = capsys.readouterr().out
    assert "VERDICT" in printed and "STAGE1" in printed
    assert "paired control" in printed

    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["scope"]["family"] == "bridge_chain" and report["scope"]["k"] == "2"
    assert report["expected_roots"] == list(ra.ROSTER_ROOTS)
    assert {(c["arm"], c["shot"], c["n"]) for c in report["cells"]} == {
        ("decomp", "fs", 2), ("decomp", "zs", 2), ("direct", "fs", 1),
    }
    v = report["verdict"]
    assert v["status"] == "stage1_observed"          # qwen assembled once
    assert v["paired_control"]["delta_stage1_pass"] == 1
    assert v["roots_missing_cells"] == [BIG, HAIKU, OPUS]
    # every cell records which files it came from, so a number can be traced back
    assert all(c["files"] for c in report["cells"])
    # ...and every few-shot cell records WHICH worked example it was run with
    fs_cell = next(c for c in report["cells"] if c["shot"] == "fs" and c["arm"] == "decomp")
    assert fs_cell["exemplars"] == [EXEMPLAR]
    assert report["warnings"] == []


def test_main_respects_no_write_and_scope_flags(tmp_path, capsys):
    results = tmp_path / "zeroshot"
    write_cell(results, "case_tree_k4_fs-decomp_opus.jsonl",
               [row(root=OPUS, family="case_tree", k=4, few_shot=True,
                    exemplar={**EXEMPLAR, "family": "case_tree", "k": 4},
                    status="leaf_failed", rid="x")])
    out = tmp_path / "roster.json"

    assert ra.main(["--results-dir", str(results), "--out", str(out), "--no-write"]) == 0
    assert not out.exists()
    assert "0 rows in scope" in capsys.readouterr().out    # default scope is bridge_chain/k2

    assert ra.main(["--results-dir", str(results), "--out", str(out),
                    "--family", "any", "--k", "any", "--expect-root", OPUS,
                    "--rl-target", OPUS]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["scope"]["in_scope"] == 1
    assert report["verdict"]["status"] == "stage1_observed"
    assert report["expected_roots"] == [OPUS]


def test_explicit_paths_override_the_results_dir(tmp_path, capsys):
    results = tmp_path / "zeroshot"
    a = write_cell(results, "bridge_chain_k2_fs-decomp_qwen.jsonl", fs_rows(QWEN, ["leaf_failed"]))
    write_cell(results, "bridge_chain_k2_fs-decomp_opus.jsonl", fs_rows(OPUS, ["plan_invalid"]))
    assert ra.main([str(a), "--no-write"]) == 0
    printed = capsys.readouterr().out
    table = printed.split("status distribution")[0]
    assert "1 file(s)" in printed
    assert OPUS not in table       # the un-named file contributes no cell
    assert OPUS in printed         # ...but is still named as a missing roster cell
