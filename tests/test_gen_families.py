"""Unit tests for scripts/gen_families.py — offline, no Lean, no family modules.

The script keeps every rlmath import inside `load_registry` / `make_backend` /
`validate_one` precisely so this file can drive `main()` end to end against a
one-problem fake family and a scripted validator. What is pinned here is the
*contract*: CLI surface, JSONL row shape, resume semantics, and the datasheet's
three tables (validator, rejection, leaf-shape) — everything downstream reads.

The fake family builds real `GeneratedProblem`/`GoalSpec`/`LemmaSpec` objects, so
`problem_row` is exercised against the frozen dataclasses rather than a mock that
could drift from them.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from rlmath.core.types import DecompositionPlan, GoalSpec, LemmaSpec
from rlmath.families.types import GeneratedProblem, LeafWitness
from rlmath.families.validate import ValidationReport

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_script_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gf = _load("gen_families")

FAMILY = "fake_family"


# ---------------------------------------------------------------------------
# Fake family + stubs
# ---------------------------------------------------------------------------

def fake_problem(k: int, seed: int, idx: int) -> GeneratedProblem:
    """Deterministic in (k, seed, idx), like the real generators."""
    names = [f"h{i}" for i in range(1, k + 1)]
    lemmas = [LemmaSpec(n, f"LEAF {n} of k{k} s{seed} i{idx}") for n in names]
    return GeneratedProblem(
        id=f"{FAMILY}-k{k}-s{seed}-{idx}",
        family=FAMILY,
        k=k,
        seed=seed,
        goal=GoalSpec(id=f"{FAMILY}-k{k}-s{seed}-{idx}", prop=f"GOAL k{k}", name=f"g{k}_{idx}"),
        oracle_plan=DecompositionPlan(lemmas=lemmas, assembly="exact glue"),
        witnesses={n: LeafWitness(l.prop, f"by w{n}") for n, l in zip(names, lemmas)},
        meta={"visible_lemmas": [], "discards": idx, "resamples": 2 * idx,
              "knobs": [{"repaired": False} for _ in names]},
    )


class FakeGen:
    """Registry entry that records its calls (resume must not re-validate, but it
    may legitimately regenerate — generation is free and pure)."""

    def __init__(self):
        self.calls: list[tuple[int, int, int]] = []

    def __call__(self, *, k: int, seed: int, n: int) -> list[GeneratedProblem]:
        self.calls.append((k, seed, n))
        return [fake_problem(k, seed, i) for i in range(n)]


class StubBackend:
    closed = False

    def close(self) -> None:
        self.closed = True


def report_for(problem, *, fail: dict[str, str] | None = None) -> ValidationReport:
    """A full V0–V6 shaped report; `fail` maps check name -> detail."""
    fail = fail or {}
    r = ValidationReport(problem_id=problem.id)
    for name in ("structure", "V1_goal_elaborates", "V0_goal_resists_automation"):
        r.add(name, name not in fail, fail.get(name, ""))
    for l in problem.oracle_plan.lemmas:
        for tmpl in ("V2_stmt[{}]", "V2_proof[{}]", "V5_leaf_resists[{}]", "V6_hidden[{}]"):
            name = tmpl.format(l.name)
            r.add(name, name not in fail, fail.get(name, ""))
    for name in ("V3_plan_check", "V4_oracle_replay"):
        r.add(name, name not in fail, fail.get(name, ""))
    return r


def patch_main(monkeypatch, *, gen=None, validate=None, backend=None):
    """Wire the three lazy seams. Returns (gen, backend, validate_calls)."""
    gen = gen or FakeGen()
    backend = backend if backend is not None else StubBackend()
    calls: list[tuple[str, bool, float]] = []

    def _validate(problem, be, *, check_automation, timeout_s):
        assert be is backend, "validator must be handed the constructed backend"
        calls.append((problem.id, check_automation, timeout_s))
        return (validate or report_for)(problem)

    monkeypatch.setattr(gf, "load_registry", lambda: {FAMILY: gen})
    monkeypatch.setattr(gf, "make_backend", lambda args: backend)
    monkeypatch.setattr(gf, "validate_one", _validate)
    return gen, backend, calls


def run(monkeypatch, out: Path, *extra, **kw):
    gen, backend, calls = patch_main(monkeypatch, **kw)
    argv = ["--out-dir", str(out), "--backend", "fake", *extra]
    assert gf.main(argv) == 0
    return gen, backend, calls


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------

def test_defaults():
    a = gf.parse_args([])
    assert a.family == ["all"]
    assert a.k_grid == [2, 4, 8]
    assert (a.n, a.seed) == (5, 42)
    assert a.out_dir == gf.DEFAULT_OUT_DIR == ROOT / "data" / "families"
    assert a.validate is True and a.check_automation is True
    assert a.backend == "repl" and a.workers == 2   # 2 max: each worker holds Mathlib in RAM
    assert a.revalidate is False and a.datasheet is True


def test_overrides(tmp_path):
    a = gf.parse_args([
        "--family", "bridge_chain,case_tree", "--k-grid", "2,4,8,16,32", "--n", "3",
        "--seed", "7", "--out-dir", str(tmp_path), "--no-validate",
        "--no-check-automation", "--no-datasheet",
        "--backend", "kimina", "--workers", "1", "--timeout-s", "30",
    ])
    assert a.family == ["bridge_chain", "case_tree"]
    assert a.k_grid == [2, 4, 8, 16, 32]
    assert (a.n, a.seed, a.timeout_s, a.workers) == (3, 7, 30.0, 1)
    assert a.out_dir == tmp_path
    assert a.validate is False and a.check_automation is False
    assert a.revalidate is False and a.datasheet is False
    assert gf.parse_args(["--revalidate"]).revalidate is True


@pytest.mark.parametrize("spec", ["", "1,2", "0", "x", "2,,three"])
def test_bad_k_grid_rejected(spec):
    with pytest.raises(SystemExit):
        gf.parse_args(["--k-grid", spec])


def test_k_grid_dedupes_preserving_order():
    assert gf.parse_k_grid("8, 2,8 ,4") == [8, 2, 4]


def test_negative_n_rejected():
    with pytest.raises(SystemExit):
        gf.parse_args(["--n", "-1"])


def test_revalidate_without_validation_is_rejected():
    """It would drop every skipped row and rewrite it skipped — churn that reads
    like a measurement."""
    with pytest.raises(SystemExit):
        gf.parse_args(["--revalidate", "--no-validate"])


def test_resolve_families():
    reg = {"b": None, "a": None}
    assert gf.resolve_families(["all"], reg) == ["a", "b"]
    assert gf.resolve_families(["b"], reg) == ["b"]
    with pytest.raises(SystemExit, match="unknown family: nope"):
        gf.resolve_families(["nope"], reg)
    with pytest.raises(SystemExit, match="no families registered"):
        gf.resolve_families(["all"], {})


def test_load_registry_finds_the_shipped_families():
    """The one test that touches the real package: rlmath.families.__init__ does
    NOT import the family modules, so the entry point must walk the package."""
    reg = gf.load_registry()
    assert {"bridge_chain", "case_tree"} <= set(reg)


# ---------------------------------------------------------------------------
# Row shape
# ---------------------------------------------------------------------------

def test_row_shape(monkeypatch, tmp_path):
    run(monkeypatch, tmp_path, "--k-grid", "2", "--n", "1", "--seed", "9")
    path = tmp_path / FAMILY / "k2.jsonl"
    (row,) = gf.read_rows(path)

    assert set(row) == {"id", "family", "k", "seed", "goal", "oracle_plan",
                        "witnesses", "meta", "validation"}
    assert (row["id"], row["family"], row["k"], row["seed"]) == (f"{FAMILY}-k2-s9-0", FAMILY, 2, 9)
    assert set(row["goal"]) == {"id", "prop", "name"}
    assert set(row["oracle_plan"]) == {"lemmas", "assembly"}
    assert [l["name"] for l in row["oracle_plan"]["lemmas"]] == ["h1", "h2"]
    assert all(set(l) == {"name", "prop"} for l in row["oracle_plan"]["lemmas"])
    assert set(row["witnesses"]) == {"h1", "h2"}
    assert set(row["witnesses"]["h1"]) == {"prop", "proof"}
    # witness keys match plan lemma names exactly — the validator's `structure` precondition
    assert set(row["witnesses"]) == {l["name"] for l in row["oracle_plan"]["lemmas"]}
    assert row["meta"]["visible_lemmas"] == []
    assert row["validation"]["ok"] is True
    assert row["validation"]["failed"] == []
    assert row["validation"]["checks"]["V4_oracle_replay"] is True
    assert row["validation"]["automation_checked"] is True
    assert row["validation"]["infra_suspect"] is False
    # the file is one JSON object per line, ensure_ascii=False (Lean props are unicode)
    assert len(path.read_text().splitlines()) == 1


def test_failed_checks_land_in_the_row(monkeypatch, tmp_path):
    def bad(problem):
        return report_for(problem, fail={"V5_leaf_resists[h1]": "auto-closable by: aesop"})

    run(monkeypatch, tmp_path, "--k-grid", "2", "--n", "1", validate=bad)
    (row,) = gf.read_rows(tmp_path / FAMILY / "k2.jsonl")
    assert row["validation"]["ok"] is False
    assert row["validation"]["failed"] == [
        {"name": "V5_leaf_resists[h1]", "detail": "auto-closable by: aesop"}
    ]
    assert row["validation"]["checks"]["V5_leaf_resists[h1]"] is False
    assert row["validation"]["checks"]["V5_leaf_resists[h2]"] is True


def test_infra_failures_are_flagged_not_counted_as_evidence(monkeypatch, tmp_path):
    def broken(problem):
        return report_for(problem, fail={"V4_oracle_replay": "repl timeout/restart: worker died"})

    run(monkeypatch, tmp_path, "--k-grid", "2", "--n", "1", validate=broken)
    (row,) = gf.read_rows(tmp_path / FAMILY / "k2.jsonl")
    assert row["validation"]["infra_suspect"] is True
    sheet = (tmp_path / FAMILY / "DATASHEET.md").read_text()
    assert "infra-suspect rows" in sheet


def test_grid_writes_one_file_per_k(monkeypatch, tmp_path):
    gen, _, _ = run(monkeypatch, tmp_path, "--k-grid", "2,4", "--n", "3")
    assert gen.calls == [(2, 42, 3), (4, 42, 3)]
    for k in (2, 4):
        rows = gf.read_rows(tmp_path / FAMILY / f"k{k}.jsonl")
        assert len(rows) == 3
        assert all(r["k"] == k and len(r["oracle_plan"]["lemmas"]) == k for r in rows)


def test_all_expands_to_every_registered_family(monkeypatch, tmp_path):
    gen = FakeGen()
    monkeypatch.setattr(gf, "load_registry", lambda: {"a": gen, "b": gen})
    monkeypatch.setattr(gf, "make_backend", lambda args: StubBackend())
    monkeypatch.setattr(gf, "validate_one",
                        lambda p, b, **kw: report_for(p))
    assert gf.main(["--out-dir", str(tmp_path), "--backend", "fake",
                    "--family", "all", "--k-grid", "2", "--n", "1"]) == 0
    assert (tmp_path / "a" / "k2.jsonl").exists() and (tmp_path / "b" / "k2.jsonl").exists()


def test_unknown_family_is_a_hard_exit(monkeypatch, tmp_path):
    monkeypatch.setattr(gf, "load_registry", lambda: {FAMILY: FakeGen()})
    with pytest.raises(SystemExit):
        gf.main(["--out-dir", str(tmp_path), "--family", "nope", "--no-validate"])


# ---------------------------------------------------------------------------
# Validation switches
# ---------------------------------------------------------------------------

def test_no_validate_never_builds_a_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(gf, "load_registry", lambda: {FAMILY: FakeGen()})
    monkeypatch.setattr(gf, "make_backend",
                        lambda args: pytest.fail("backend built under --no-validate"))
    monkeypatch.setattr(gf, "validate_one",
                        lambda *a, **kw: pytest.fail("validated under --no-validate"))
    assert gf.main(["--out-dir", str(tmp_path), "--k-grid", "2", "--n", "1", "--no-validate"]) == 0
    (row,) = gf.read_rows(tmp_path / FAMILY / "k2.jsonl")
    assert row["validation"] == gf.SKIPPED_VALIDATION
    assert row["validation"]["ok"] is None   # null, never a bare False: nothing was measured


def test_check_automation_flag_reaches_the_validator(monkeypatch, tmp_path):
    _, _, calls = run(monkeypatch, tmp_path, "--k-grid", "2", "--n", "1",
                      "--no-check-automation", "--timeout-s", "17")
    assert calls == [(f"{FAMILY}-k2-s42-0", False, 17.0)]
    (row,) = gf.read_rows(tmp_path / FAMILY / "k2.jsonl")
    assert row["validation"]["automation_checked"] is False


def test_backend_is_closed(monkeypatch, tmp_path):
    _, backend, _ = run(monkeypatch, tmp_path, "--k-grid", "2", "--n", "1")
    assert backend.closed


def test_backend_is_closed_even_when_validation_raises(monkeypatch, tmp_path):
    backend = StubBackend()
    monkeypatch.setattr(gf, "load_registry", lambda: {FAMILY: FakeGen()})
    monkeypatch.setattr(gf, "make_backend", lambda args: backend)
    monkeypatch.setattr(gf, "validate_one",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        gf.main(["--out-dir", str(tmp_path), "--backend", "fake", "--k-grid", "2", "--n", "1"])
    assert backend.closed


# ---------------------------------------------------------------------------
# Resume (../rl existing_ids pattern)
# ---------------------------------------------------------------------------

def test_resume_skips_written_ids_and_revalidates_nothing(monkeypatch, tmp_path):
    run(monkeypatch, tmp_path, "--k-grid", "2", "--n", "2")
    _, _, calls = run(monkeypatch, tmp_path, "--k-grid", "2", "--n", "2")
    assert calls == []                                            # no Lean spent on a resume
    assert len(gf.read_rows(tmp_path / FAMILY / "k2.jsonl")) == 2  # and no duplicate rows


def test_resume_extends_a_partial_run(monkeypatch, tmp_path):
    run(monkeypatch, tmp_path, "--k-grid", "2", "--n", "1")
    _, _, calls = run(monkeypatch, tmp_path, "--k-grid", "2", "--n", "3")
    rows = gf.read_rows(tmp_path / FAMILY / "k2.jsonl")
    assert [r["id"] for r in rows] == [f"{FAMILY}-k2-s42-{i}" for i in range(3)]
    assert [c[0] for c in calls] == [f"{FAMILY}-k2-s42-1", f"{FAMILY}-k2-s42-2"]


def test_resume_keeps_failed_rows_instead_of_rerolling_them(monkeypatch, tmp_path):
    """A V-check failure is a measurement. Re-running must not quietly retry it —
    that would make the datasheet's pass rate depend on run history."""
    run(monkeypatch, tmp_path, "--k-grid", "2", "--n", "1",
        validate=lambda p: report_for(p, fail={"V3_plan_check": "assembly failed"}))
    _, _, calls = run(monkeypatch, tmp_path, "--k-grid", "2", "--n", "1")
    assert calls == []
    (row,) = gf.read_rows(tmp_path / FAMILY / "k2.jsonl")
    assert row["validation"]["ok"] is False


def test_revalidate_reruns_only_unvalidated_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(gf, "load_registry", lambda: {FAMILY: FakeGen()})
    assert gf.main(["--out-dir", str(tmp_path), "--k-grid", "2", "--n", "2",
                    "--no-validate"]) == 0
    # measure only the first problem, leaving the second at ok=null
    path = tmp_path / FAMILY / "k2.jsonl"
    rows = gf.read_rows(path)
    rows[0]["validation"] = {**gf.SKIPPED_VALIDATION, "ok": False,
                             "failed": [{"name": "V0_goal_resists_automation", "detail": "simp"}]}
    gf.rewrite_rows(path, rows)

    _, _, calls = run(monkeypatch, tmp_path, "--k-grid", "2", "--n", "2", "--revalidate")
    assert [c[0] for c in calls] == [f"{FAMILY}-k2-s42-1"]     # only the ok=null row
    rows = gf.read_rows(path)
    assert [r["id"] for r in rows] == [f"{FAMILY}-k2-s42-0", f"{FAMILY}-k2-s42-1"]
    assert rows[0]["validation"]["ok"] is False                # measured row untouched
    assert rows[1]["validation"]["ok"] is True


def test_read_rows_survives_a_torn_last_line(tmp_path):
    p = tmp_path / "k2.jsonl"
    p.write_text(json.dumps({"id": "a"}) + "\n" + '{"id": "b", "goa')
    assert gf.read_rows(p) == [{"id": "a"}]
    assert gf.existing_ids(p) == {"a"}
    assert gf.existing_ids(tmp_path / "missing.jsonl") == set()


def test_rewrite_rows_is_atomic(tmp_path):
    p = tmp_path / "k2.jsonl"
    gf.rewrite_rows(p, [{"id": "a"}, {"id": "b"}])
    assert gf.existing_ids(p) == {"a", "b"}
    assert not (tmp_path / "k2.jsonl.tmp").exists()


# ---------------------------------------------------------------------------
# Datasheet
# ---------------------------------------------------------------------------

def test_check_group_collapses_per_lemma_checks():
    assert gf.check_group("V5_leaf_resists[hb12]") == "V5_leaf_resists"
    assert gf.check_group("V4_oracle_replay") == "V4_oracle_replay"


def test_validator_table_counts_per_check_per_k(monkeypatch, tmp_path):
    run(monkeypatch, tmp_path, "--k-grid", "2,4", "--n", "1",
        validate=lambda p: report_for(p, fail={"V5_leaf_resists[h1]": "aesop"}))
    rows_by_k = {k: gf.read_rows(tmp_path / FAMILY / f"k{k}.jsonl") for k in (2, 4)}
    header, rows = gf.validator_table(rows_by_k)
    assert header == ["check", "k=2", "k=4"]
    table = {r[0]: r[1:] for r in rows}
    # per-lemma granularity: one entry per leaf, so k=4 runs 4 V5 checks
    assert table["V5_leaf_resists"] == ["1/2", "3/4"]
    assert table["V0_goal_resists_automation"] == ["1/1", "1/1"]
    assert table["V2_proof"] == ["2/2", "4/4"]
    assert table["problems ok"] == ["0/1", "0/1"]


def test_validator_table_marks_unvalidated_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(gf, "load_registry", lambda: {FAMILY: FakeGen()})
    gf.main(["--out-dir", str(tmp_path), "--k-grid", "2", "--n", "2", "--no-validate"])
    rows_by_k = {2: gf.read_rows(tmp_path / FAMILY / "k2.jsonl")}
    _, rows = gf.validator_table(rows_by_k)
    assert rows[-1] == ["problems ok", "0/0 (not validated, 2 rows)"]


def test_rejection_stats_reads_generator_counters():
    rows = [{"meta": {"discards": 3, "resamples": 1,
                      "knobs": [{"repaired": True}, {"repaired": False}]}},
            {"meta": {"discards": 1, "resamples": 0, "knobs": [{"repaired": False}]}}]
    s = gf.rejection_stats(rows)
    assert s["discards"] == {"total": 4, "max": 3, "mean": 2.0}
    assert s["resamples"]["total"] == 1
    assert s["candidates"] == 6 and s["discard_rate"] == round(4 / 6, 3)
    assert s["repaired_frac"] == round(1 / 3, 3)


def test_rejection_stats_absent_counters_report_nothing():
    """A family whose sampler cannot fail must show `-`, not a fabricated 0%."""
    assert gf.rejection_stats([{"meta": {"variant": "max"}}]) == {}


def test_datasheet_has_every_required_section(monkeypatch, tmp_path):
    run(monkeypatch, tmp_path, "--k-grid", "2,4", "--n", "2")
    sheet = (tmp_path / FAMILY / "DATASHEET.md").read_text()
    for section in ("# `fake_family` — dataset datasheet", "## Counts",
                    "## Validator table", "## Discard / rejection stats",
                    "## Leaf prop length distribution per k", "## Failed checks"):
        assert section in sheet, sheet
    assert "| check | k=2 | k=4 |" in sheet
    assert "seed: `42`" in sheet
    assert "None — every materialized row passed every check that was run." in sheet


def test_datasheet_cost_is_summed_from_rows_not_from_the_clock(monkeypatch, tmp_path):
    """A resume writes no rows and takes ~0s; stamping that on the datasheet would
    claim the data was free to produce. The cost line comes from the rows."""
    run(monkeypatch, tmp_path, "--k-grid", "2", "--n", "2")
    path = tmp_path / FAMILY / "k2.jsonl"
    rows = gf.read_rows(path)
    for r, secs in zip(rows, (12.5, 7.5)):
        r["validation"]["elapsed_s"] = secs
    gf.rewrite_rows(path, rows)

    run(monkeypatch, tmp_path, "--k-grid", "2", "--n", "2")     # pure resume
    sheet = (tmp_path / FAMILY / "DATASHEET.md").read_text()
    assert "- validation cost: 20.0s summed over 2/2 measured rows" in sheet
    assert "0.0s wall)" in sheet     # the run's own wall time is reported separately


def test_datasheet_is_rebuilt_from_the_rows_on_disk(monkeypatch, tmp_path):
    """Resume writes no new rows, but the datasheet must still cover the whole
    directory — it is a function of the files, not of this run's in-memory state."""
    run(monkeypatch, tmp_path, "--k-grid", "2,4", "--n", "2")
    (tmp_path / FAMILY / "DATASHEET.md").unlink()
    run(monkeypatch, tmp_path, "--k-grid", "2", "--n", "2")     # k=4 not even in the grid
    sheet = (tmp_path / FAMILY / "DATASHEET.md").read_text()
    assert "| check | k=2 | k=4 |" in sheet


def test_datasheet_leaf_length_row_reports_the_distribution(monkeypatch, tmp_path):
    run(monkeypatch, tmp_path, "--k-grid", "2", "--n", "2")
    rows = gf.read_rows(tmp_path / FAMILY / "k2.jsonl")
    lens = [len(l["prop"]) for r in rows for l in r["oracle_plan"]["lemmas"]]
    d = gf._dist(lens)
    assert d["n"] == 4
    sheet = (tmp_path / FAMILY / "DATASHEET.md").read_text()
    assert f"| 2 | 4 | {d['min']} | {d['median']} | {d['mean']} | {d['max']} |" in sheet


def test_no_datasheet_flag(monkeypatch, tmp_path):
    run(monkeypatch, tmp_path, "--k-grid", "2", "--n", "1", "--no-datasheet")
    assert not (tmp_path / FAMILY / "DATASHEET.md").exists()


def test_datasheet_lists_failed_checks(monkeypatch, tmp_path):
    run(monkeypatch, tmp_path, "--k-grid", "2", "--n", "1",
        validate=lambda p: report_for(p, fail={"V6_hidden[h2]": "lemma prop is a substring"}))
    sheet = (tmp_path / FAMILY / "DATASHEET.md").read_text()
    assert "V6_hidden[h2]" in sheet and "lemma prop is a substring" in sheet
