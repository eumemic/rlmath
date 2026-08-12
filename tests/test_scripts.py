"""Unit tests for the two Phase 0 CLIs (scripts/build_bank.py, scripts/bench_throughput.py).

Pure logic only: statement extraction, resume/repair bookkeeping, suite shape,
throughput arithmetic, and both `main()`s driven end-to-end against stubs. No
network, no Lean toolchain, no model server — the scripts keep every such
import inside make_backend / make_leaf / load_rows precisely so this file can
exist. Tests inject stubs by monkeypatching those three functions (the
documented seam; `--backend fake` + FAKE_*_FACTORY is the other one).

The scripts are loaded by path because scripts/ is not a package — the same
trick ../rl/eval/run_eval.py uses for its per-benchmark scorers.
"""
from __future__ import annotations

import importlib.util
import json
import threading
import time
from pathlib import Path

import pytest

from rlmath.core.types import AttemptRecord, LeanMessage, Status, VerifyResult, statement_key

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_script_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build_bank = _load("build_bank")
bench = _load("bench_throughput")


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class StubLeaf:
    """Leaf-prover stand-in honoring harness/episode.LeafProver:
    `prove(prop, *, k, backend)`, k attempts, the first `n_verified` verified."""

    def __init__(self, n_verified: int = 1):
        self.n_verified = n_verified
        self.calls: list[tuple[str, int]] = []

    def prove(self, prop: str, *, k: int = 8, backend=None, early_stop: bool = True,
              timeout_s: float = 120.0) -> list[AttemptRecord]:
        assert backend is not None, "leaf must be handed the backend to verify with"
        self.calls.append((prop, k))
        return [
            AttemptRecord(
                statement_key=statement_key(prop),
                model="stub",
                index=i,
                proof=f"by proof{i}",
                verified=i < self.n_verified,
            )
            for i in range(k)
        ]


def _elaborating_backend(fake_backend):
    """FakeBackend that accepts every statement_check (ok + exactly one sorry)."""
    fake_backend.rule(lambda c: "_stmt_check" in c, VerifyResult(ok=True, sorries=1))
    return fake_backend


# ---------------------------------------------------------------------------
# build_bank: argument parsing
# ---------------------------------------------------------------------------

def test_build_bank_defaults():
    a = build_bank.parse_args([])
    assert a.dataset == build_bank.DEFAULT_DATASET
    assert a.split == "train"
    # pinned to the canonical file, not HF's smaller auto-converted parquet
    # (research/models-datasets.md §3)
    assert a.data_files == "lean_workbook.json"
    assert a.k == build_bank.DEFAULT_K
    assert a.backend == "repl"
    assert (a.limit, a.seed) == (None, None)
    assert a.out == ROOT / "data" / "bank" / "bank.jsonl"
    assert not a.elaborate_only and not a.repair


def test_build_bank_overrides(tmp_path):
    a = build_bank.parse_args(
        [
            "--dataset", "foo/bar", "--limit", "5", "--seed", "7", "--k", "3",
            "--backend", "kimina", "--kimina-url", "http://k:9",
            "--leaf-base-url", "http://l:1/v1", "--leaf-model", "m", "--leaf-template", "t",
            "--out", str(tmp_path / "b.jsonl"), "--elaborate-only", "--repair",
        ]
    )
    assert (a.dataset, a.limit, a.seed, a.k) == ("foo/bar", 5, 7, 3)
    assert (a.backend, a.kimina_url) == ("kimina", "http://k:9")
    assert (a.leaf_base_url, a.leaf_model, a.leaf_template) == ("http://l:1/v1", "m", "t")
    assert a.out == tmp_path / "b.jsonl"
    assert a.elaborate_only and a.repair


# ---------------------------------------------------------------------------
# build_bank: statement extraction
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "src,want",
    [
        # Lean-Workbook's shape: binders become a ∀-telescope so statement_check parses.
        ("theorem lean_workbook_1 (x : ℝ) (hx : 0 < x) : x / x = 1 := by sorry",
         "∀ (x : ℝ) (hx : 0 < x), x / x = 1"),
        ("theorem foo : 2 + 2 = 4 := by sorry", "2 + 2 = 4"),
        ("theorem foo : ∀ x : ℝ, x = x := by sorry", "∀ x : ℝ, x = x"),
        ("lemma bar (n : ℕ) : n + 0 = n := by\n  simp", "∀ (n : ℕ), n + 0 = n"),
        ("theorem baz (n : ℕ) : n = n", "∀ (n : ℕ), n = n"),          # no `:=` at all
        ("theorem q {α : Type*} [Fintype α] : True := by sorry", "∀ {α : Type*} [Fintype α], True"),
        ("2 + 2 = 4", "2 + 2 = 4"),                                    # already a bare prop
        ("theorem c (x : ℕ) /- note -/ : x = x := by sorry", "∀ (x : ℕ), x = x"),  # comments stripped
        # verbatim lean_workbook_0 (research/models-datasets.md §3 example row)
        ("theorem lean_workbook_0 (a b c : ℝ) (ha : 0 < a) (hb : 0 < b) (hc : 0 < c) : "
         "(b + c) / Real.sqrt (a ^ 2 + 8 * b * c) ≥ 2  :=  by sorry",
         "∀ (a b c : ℝ) (ha : 0 < a) (hb : 0 < b) (hc : 0 < c), "
         "(b + c) / Real.sqrt (a ^ 2 + 8 * b * c) ≥ 2"),
        ("theorem s : ∑ i in Finset.range 3, i = 3 := by sorry", "∑ i in Finset.range 3, i = 3"),
    ],
)
def test_theorem_to_prop(src, want):
    assert build_bank.theorem_to_prop(src) == want


@pytest.mark.parametrize("src", ["", "   ", "def f := 1", "theorem"])
def test_theorem_to_prop_rejects(src):
    assert build_bank.theorem_to_prop(src) is None


def test_extract_prop_field_fallback():
    assert build_bank.extract_prop({"formal_statement": "theorem a : P := by sorry"}) == "P"
    assert build_bank.extract_prop({"statement": "theorem a : Q := by sorry"}) == "Q"
    assert build_bank.extract_prop({"nope": "theorem a : P := by sorry"}) is None
    # explicit --prop-field wins and does not fall back
    assert build_bank.extract_prop({"formal_statement": "theorem a : P := by sorry"}, "statement") is None


def test_source_id():
    assert build_bank.source_id({"id": "lw-3"}, "ds", 0) == "ds#lw-3"
    assert build_bank.source_id({"problem_id": 12}, "ds", 0) == "ds#12"
    assert build_bank.source_id({}, "ds", 4) == "ds#4"


# ---------------------------------------------------------------------------
# build_bank: resume + repair bookkeeping (../rl/eval/run_eval.py patterns)
# ---------------------------------------------------------------------------

def _write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_existing_keys_includes_error_rows_and_survives_torn_lines(tmp_path):
    p = tmp_path / "bank.jsonl"
    p.write_text(
        json.dumps({"statement_key": "aaa", "status": "verified"}) + "\n"
        + "\n"
        + json.dumps({"statement_key": "bbb", "status": "error"}) + "\n"
        + '{"statement_key": "ccc", "sta'  # killed mid-write
    )
    # error rows are skipped too: retry is explicit (--repair), never implicit
    assert build_bank.existing_keys(p) == {"aaa", "bbb"}
    assert build_bank.existing_keys(tmp_path / "missing.jsonl") == set()


def test_split_error_rows_only_targets_infrastructure_failures():
    rows = [
        {"statement_key": "a", "status": Status.VERIFIED},
        {"statement_key": "b", "status": Status.ERROR},
        {"statement_key": "c", "status": Status.STATEMENT_ILL_FORMED},
        {"statement_key": "d", "status": Status.LEAF_FAILED},
    ]
    keep, errs = build_bank.split_error_rows(rows)
    assert [r["statement_key"] for r in keep] == ["a", "c", "d"]
    assert [r["statement_key"] for r in errs] == ["b"]


def test_rewrite_rows_roundtrip(tmp_path):
    p = tmp_path / "bank.jsonl"
    _write_rows(p, [{"statement_key": "a"}, {"statement_key": "b"}])
    build_bank.rewrite_rows(p, [{"statement_key": "a"}])
    assert build_bank.read_rows(p) == [{"statement_key": "a"}]
    assert not (tmp_path / "bank.jsonl.tmp").exists()


def test_repair_targets_drops_error_rows_and_returns_their_props(tmp_path):
    p = tmp_path / "bank.jsonl"
    _write_rows(p, [
        {"statement_key": "a", "prop": "P", "source_id": "ds#1", "status": Status.VERIFIED},
        {"statement_key": "b", "prop": "Q", "source_id": "ds#2", "status": Status.ERROR},
    ])
    assert build_bank._repair_targets(p) == [("Q", "ds#2")]
    assert build_bank.existing_keys(p) == {"a"}


# ---------------------------------------------------------------------------
# build_bank: per-statement measurement
# ---------------------------------------------------------------------------

def test_summarize_leaf_from_attempt_records():
    attempts = [
        AttemptRecord("k", "m", 0, "bad", verified=False),
        AttemptRecord("k", "m", 1, "good", verified=True),
        AttemptRecord("k", "m", 2, "also good", verified=True),
    ]
    assert build_bank.summarize_leaf(attempts, 8) == (3, 2, pytest.approx(2 / 3), "good")
    assert build_bank.summarize_leaf([], 8) == (0, 0, None, None)
    # generated-but-unchecked (verified=None) never counts as a pass
    assert build_bank.summarize_leaf([AttemptRecord("k", "m", 0, "p")], 8) == (1, 0, 0.0, None)


class _Res:
    def __init__(self, **kw):
        self.__dict__.update(kw)


@pytest.mark.parametrize(
    "res,want",
    [
        (None, (8, 0, 0.0, None)),                                    # unknown count charged as k
        ("by omega", (1, 1, 1.0, "by omega")),
        (("by omega", 3), (3, 1, pytest.approx(1 / 3), "by omega")),
        ((None, 4), (4, 0, 0.0, None)),
        (_Res(proof="by ring", attempts_used=2), (2, 1, 0.5, "by ring")),
        (_Res(proof="by ring", verified=False, attempts_used=2), (2, 0, 0.0, None)),
        (_Res(attempts=[AttemptRecord("k", "m", 0, "p", verified=True)]), (1, 1, 1.0, "p")),
    ],
)
def test_summarize_leaf_accepts_the_harness_shapes(res, want):
    """Same duck typing as harness/episode._leaf_result, plus the verified count."""
    assert build_bank.summarize_leaf(res, 8) == want


def test_process_one_verified(fake_backend):
    leaf = StubLeaf(n_verified=2)
    row = build_bank.process_one("P", "ds#1", _elaborating_backend(fake_backend), leaf, k=4)
    assert row["status"] == Status.VERIFIED
    assert (row["elaborates"], row["n_attempts"], row["n_verified"]) == (True, 4, 2)
    assert row["pass_rate"] == 0.5 and row["first_proof"] == "by proof0"
    assert row["statement_key"] == statement_key("P") and row["source_id"] == "ds#1"
    assert leaf.calls == [("P", 4)]


def test_process_one_leaf_failed(fake_backend):
    row = build_bank.process_one("P", "ds#1", _elaborating_backend(fake_backend), StubLeaf(0), k=2)
    assert row["status"] == Status.LEAF_FAILED
    assert (row["n_verified"], row["pass_rate"], row["first_proof"]) == (0, 0.0, None)


def test_process_one_ill_formed_skips_the_leaf(fake_backend):
    fake_backend.rule(
        lambda c: True, VerifyResult(ok=False, messages=[LeanMessage("error", "unknown identifier")])
    )
    leaf = StubLeaf()
    row = build_bank.process_one("bogus", "ds#1", fake_backend, leaf)
    assert row["status"] == Status.STATEMENT_ILL_FORMED
    assert row["elaborates"] is False and row["n_attempts"] == 0
    assert "unknown identifier" in row["detail"]
    assert leaf.calls == []  # never pay for a leaf run on a statement that does not elaborate


def test_process_one_requires_exactly_one_sorry(fake_backend):
    """ok with 0 sorries means the snippet is not the statement check we asked for
    (leancode.statement_check contract) — treat as ill-formed, not as evidence."""
    fake_backend.rule(lambda c: True, VerifyResult(ok=True, sorries=0))
    row = build_bank.process_one("P", "ds#1", fake_backend, StubLeaf())
    assert row["status"] == Status.STATEMENT_ILL_FORMED


def test_process_one_elaborate_only(fake_backend):
    row = build_bank.process_one("P", "ds#1", _elaborating_backend(fake_backend), None)
    assert row["status"] == build_bank.STATUS_ELABORATED
    assert row["elaborates"] is True and row["pass_rate"] is None


def test_process_one_backend_exception_is_an_error_row(fake_backend):
    class Boom:
        def check(self, code, timeout_s=120.0):
            raise RuntimeError("repl died")

    row = build_bank.process_one("P", "ds#1", Boom(), StubLeaf())
    assert row["status"] == Status.ERROR
    assert "repl died" in row["detail"]


# ---------------------------------------------------------------------------
# build_bank: main() over the stub seam
# ---------------------------------------------------------------------------

def _patch_bank_main(monkeypatch, fake_backend, rows, leaf=None):
    monkeypatch.setattr(build_bank, "load_rows", lambda args: iter(rows))
    monkeypatch.setattr(build_bank, "make_backend", lambda args: _elaborating_backend(fake_backend))
    monkeypatch.setattr(build_bank, "make_leaf", lambda args: leaf or StubLeaf())


def test_main_writes_rows_then_resumes_without_redoing_them(monkeypatch, fake_backend, tmp_path):
    out = tmp_path / "bank.jsonl"
    rows = [
        {"formal_statement": "theorem a : 1 = 1 := by sorry", "id": "a"},
        {"formal_statement": "theorem b : 2 = 2 := by sorry", "id": "b"},
        {"formal_statement": "theorem a2 : 1 = 1 := by sorry", "id": "a2"},  # duplicate statement
        {"nope": "unextractable"},
    ]
    leaf = StubLeaf(n_verified=1)
    _patch_bank_main(monkeypatch, fake_backend, rows, leaf)

    assert build_bank.main(["--out", str(out), "--backend", "fake", "--k", "2"]) == 0
    written = build_bank.read_rows(out)
    ds = build_bank.DEFAULT_DATASET
    # 4 dataset rows -> 2 bank rows: one duplicate statement, one unextractable
    assert [r["source_id"] for r in written] == [f"{ds}#a", f"{ds}#b"]
    assert all(r["status"] == Status.VERIFIED for r in written)

    assert build_bank.main(["--out", str(out), "--backend", "fake", "--k", "2"]) == 0
    assert len(build_bank.read_rows(out)) == 2  # nothing re-run
    assert len(leaf.calls) == 2


def test_main_repair_reruns_only_error_rows(monkeypatch, fake_backend, tmp_path):
    out = tmp_path / "bank.jsonl"
    _write_rows(out, [
        {"statement_key": "keep", "prop": "K", "source_id": "ds#k", "status": Status.LEAF_FAILED},
        {"statement_key": statement_key("E"), "prop": "E", "source_id": "ds#e", "status": Status.ERROR},
    ])
    leaf = StubLeaf(n_verified=1)
    # load_rows must never be touched in repair mode: error rows carry their own prop
    monkeypatch.setattr(build_bank, "load_rows", lambda args: (_ for _ in ()).throw(AssertionError("streamed")))
    monkeypatch.setattr(build_bank, "make_backend", lambda args: _elaborating_backend(fake_backend))
    monkeypatch.setattr(build_bank, "make_leaf", lambda args: leaf)

    assert build_bank.main(["--out", str(out), "--backend", "fake", "--repair", "--k", "2"]) == 0
    rows = build_bank.read_rows(out)
    assert [r["source_id"] for r in rows] == ["ds#k", "ds#e"]
    assert rows[0]["status"] == Status.LEAF_FAILED  # untouched
    assert rows[1]["status"] == Status.VERIFIED     # repaired
    assert leaf.calls == [("E", 2)]


def test_main_elaborate_only_never_builds_a_leaf(monkeypatch, fake_backend, tmp_path):
    out = tmp_path / "bank.jsonl"
    monkeypatch.setattr(build_bank, "load_rows", lambda args: iter([{"formal_statement": "theorem a : P := by sorry"}]))
    monkeypatch.setattr(build_bank, "make_backend", lambda args: _elaborating_backend(fake_backend))
    monkeypatch.setattr(build_bank, "make_leaf", lambda args: pytest.fail("leaf built in --elaborate-only"))

    assert build_bank.main(["--out", str(out), "--backend", "fake", "--elaborate-only"]) == 0
    assert build_bank.read_rows(out)[0]["status"] == build_bank.STATUS_ELABORATED


# ---------------------------------------------------------------------------
# bench_throughput
# ---------------------------------------------------------------------------

def test_bench_defaults_and_overrides(tmp_path):
    a = bench.parse_args([])
    assert (a.suite, a.n, a.workers, a.backend) == ("trivial", 60, 4, "repl")
    assert a.from_bank is None and a.timestamp is None
    assert a.out == ROOT / "analysis" / "throughput.json"
    b = bench.parse_args(
        ["--from-bank", str(tmp_path / "b.jsonl"), "--n", "10", "--workers", "8",
         "--backend", "kimina", "--timestamp", "2026-08-11T00:00:00Z", "--out", str(tmp_path / "t.json")]
    )
    assert (b.n, b.workers, b.backend, b.timestamp) == (10, 8, "kimina", "2026-08-11T00:00:00Z")
    assert b.from_bank == tmp_path / "b.jsonl"


def test_trivial_suite_shape():
    suite = bench.TRIVIAL_SUITE
    assert len(suite) >= 18
    props = [p for p, _ in suite]
    assert len(set(props)) == len(props)
    for prop, proof in suite:
        assert isinstance(prop, str) and prop.strip() and "\n" not in prop
        assert isinstance(proof, str) and proof.strip() and proof.startswith("by ")
        assert ":=" not in prop  # props, not declarations — proof_check supplies the `:=`
        assert "sorry" not in proof and "native_decide" not in proof


def test_build_codes_cycles_and_uses_proof_check():
    codes = bench.build_codes([("P", "by trivial"), ("Q", "by rfl")], 5)
    assert len(codes) == 5
    assert codes[0].startswith("theorem _proof_check : P :=") and "by trivial" in codes[0]
    assert codes[4] == codes[0]  # cycled
    with pytest.raises(SystemExit):
        bench.build_codes([], 3)


def test_suite_from_bank_filters_and_is_seed_deterministic(tmp_path):
    p = tmp_path / "bank.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in [
        {"prop": "A", "first_proof": "by norm_num"},
        {"prop": "B", "first_proof": None},      # leaf never closed it
        {"prop": "C", "first_proof": "by omega"},
        {"prop": "", "first_proof": "by rfl"},
    ]) + "not json\n")
    assert bench.suite_from_bank(p) == [("A", "by norm_num"), ("C", "by omega")]
    assert bench.suite_from_bank(p, seed=1) == bench.suite_from_bank(p, seed=1)


def test_percentile():
    xs = [float(i) for i in range(1, 11)]
    assert bench.percentile(xs, 0.5) == 5.0
    assert bench.percentile(xs, 0.95) == 10.0
    assert bench.percentile([3.0], 0.5) == 3.0
    assert bench.percentile([], 0.5) is None


def test_throughput_stats_math():
    lat = [0.1, 0.2, 0.3, 0.4]
    s = bench.throughput_stats(lat, wall_s=2.0, n=40, failures=3)
    assert s["attempts_per_hr"] == 72000.0        # 40 checks / 2s
    assert s["verified_per_hr"] == 66600.0        # the gate nets out the 3 failures
    assert s["p50_s"] == 0.2 and s["p95_s"] == 0.4
    assert s["mean_s"] == pytest.approx(0.25)
    assert (s["n"], s["failures"], s["wall_s"]) == (40, 3, 2.0)


def test_throughput_stats_without_latencies_reports_null_not_zero():
    s = bench.throughput_stats([], wall_s=0.0, n=0, failures=0)
    assert s["attempts_per_hr"] is None and s["p50_s"] is None and s["mean_s"] is None


def test_bench_main_writes_json(monkeypatch, fake_backend, tmp_path):
    fake_backend.rule(lambda c: True, VerifyResult(ok=True, sorries=0, elapsed_s=0.05))
    monkeypatch.setattr(bench, "make_backend", lambda args: fake_backend)
    out = tmp_path / "throughput.json"

    assert bench.main(["--backend", "fake", "--n", "7", "--workers", "3",
                       "--timestamp", "2026-08-11T00:00:00Z", "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert set(data) >= {"timestamp", "backend", "n", "workers", "attempts_per_hr",
                         "p50_s", "p95_s", "failures"}
    assert (data["timestamp"], data["backend"], data["n"], data["workers"]) == (
        "2026-08-11T00:00:00Z", "fake", 7, 3)
    assert data["failures"] == 0 and data["p50_s"] == 0.05
    assert len(fake_backend.calls) == 7


def test_bench_main_counts_failures_and_omits_timestamp(monkeypatch, fake_backend, tmp_path):
    # a snippet left with a sorry is a failed check even though ok=True
    fake_backend.rule(lambda c: True, VerifyResult(ok=True, sorries=1, elapsed_s=0.01))
    monkeypatch.setattr(bench, "make_backend", lambda args: fake_backend)
    out = tmp_path / "throughput.json"

    assert bench.main(["--backend", "fake", "--n", "4", "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["failures"] == 4 and data["timestamp"] is None


def test_bench_main_from_bank(monkeypatch, fake_backend, tmp_path):
    bank = tmp_path / "bank.jsonl"
    bank.write_text(json.dumps({"prop": "2 = 2", "first_proof": "by norm_num"}) + "\n")
    fake_backend.rule(lambda c: True, VerifyResult(ok=True, sorries=0, elapsed_s=0.02))
    monkeypatch.setattr(bench, "make_backend", lambda args: fake_backend)
    out = tmp_path / "t.json"

    assert bench.main(["--backend", "fake", "--from-bank", str(bank), "--n", "2", "--out", str(out)]) == 0
    assert json.loads(out.read_text())["suite"] == "bank:bank.jsonl"
    assert "2 = 2" in fake_backend.calls[0]


def test_bench_main_rejects_bank_with_no_proofs(monkeypatch, tmp_path):
    bank = tmp_path / "bank.jsonl"
    bank.write_text(json.dumps({"prop": "P", "first_proof": None}) + "\n")
    with pytest.raises(SystemExit):
        bench.main(["--backend", "fake", "--from-bank", str(bank), "--out", str(tmp_path / "t.json")])


def test_fake_backend_seam_errors_without_a_registered_factory():
    """--backend fake is a test seam, not a silent no-op backend."""
    with pytest.raises(SystemExit):
        bench.make_backend(bench.parse_args(["--backend", "fake"]))
    with pytest.raises(SystemExit):
        build_bank.make_backend(build_bank.parse_args(["--backend", "fake"]))
    with pytest.raises(SystemExit):
        build_bank.make_leaf(build_bank.parse_args(["--backend", "fake"]))


def test_make_backend_routes_through_the_lean_factory(monkeypatch):
    """Both CLIs go through rlmath.lean.get_backend (the single name->backend
    switch) and spend --workers as pool size on either backend. Imported inside
    the test so sibling churn can never break collection of this module."""
    import rlmath.lean as lean

    seen: dict[str, dict] = {}
    monkeypatch.setattr(lean, "get_backend", lambda name, **kw: seen.setdefault(name, kw))
    build_bank.make_backend(build_bank.parse_args(["--backend", "repl", "--workers", "3"]))
    bench.make_backend(bench.parse_args(["--backend", "kimina", "--workers", "5", "--kimina-url", "http://k"]))
    assert seen == {"repl": {"n_workers": 3}, "kimina": {"base_url": "http://k", "max_workers": 5}}


def test_fake_factory_hooks_drive_both_clis(monkeypatch, fake_backend, tmp_path):
    """The other documented seam: register the factories, then run unpatched mains."""
    fake_backend.rule(lambda c: "_stmt_check" in c, VerifyResult(ok=True, sorries=1))
    fake_backend.rule(lambda c: True, VerifyResult(ok=True, sorries=0, elapsed_s=0.01))
    monkeypatch.setattr(bench, "FAKE_BACKEND_FACTORY", lambda: fake_backend)
    monkeypatch.setattr(build_bank, "FAKE_BACKEND_FACTORY", lambda: fake_backend)
    monkeypatch.setattr(build_bank, "FAKE_LEAF_FACTORY", lambda: StubLeaf(1))
    monkeypatch.setattr(build_bank, "load_rows", lambda args: iter([{"formal_statement": "theorem a : P := by sorry"}]))

    assert bench.main(["--backend", "fake", "--n", "2", "--out", str(tmp_path / "t.json")]) == 0
    assert build_bank.main(["--backend", "fake", "--k", "1", "--out", str(tmp_path / "b.jsonl")]) == 0
    assert build_bank.read_rows(tmp_path / "b.jsonl")[0]["status"] == Status.VERIFIED


def test_modernize_bigops():
    """Lean-Workbook big-operator binders predate the Mathlib `in`→`∈` migration
    (measured 2/12 elaboration failures on the first bank smoke, both this cause)."""
    f = build_bank.modernize_bigops
    assert f("∀ m, (∑ k in Finset.range m, k!) ≠ 0") == "∀ m, (∑ k ∈ Finset.range m, k!) ≠ 0"
    assert f("∏ i in s, f i = ∑ j in t, g j") == "∏ i ∈ s, f i = ∑ j ∈ t, g j"
    # integral syntax legitimately uses `in` and must survive untouched
    assert f("∫ x in Set.Icc 0 1, f x = 1") == "∫ x in Set.Icc 0 1, f x = 1"
    # mixed: sum rewritten, integral preserved
    assert f("∑ k in s, ∫ x in a..b, f k x") == "∑ k ∈ s, ∫ x in a..b, f k x"
    # already-modern statements are fixed points
    assert f("∑ k ∈ Finset.range m, k = 0") == "∑ k ∈ Finset.range m, k = 0"


def test_leaf_provenance_guard(tmp_path, monkeypatch, fake_backend):
    """Bank rows record leaf_id; appending with a different leaf model is a hard
    refusal — stand-in pass rates must never silently mix into the oracle bank
    (advisor review 2026-08-11; DIRECTION.md §5.4: the bank IS the delegability oracle)."""
    out = tmp_path / "bank.jsonl"
    _elaborating_backend(fake_backend)
    monkeypatch.setattr(build_bank, "make_backend", lambda a: fake_backend)
    monkeypatch.setattr(build_bank, "make_leaf", lambda a: StubLeaf(n_verified=1))
    monkeypatch.setattr(build_bank, "_candidates", lambda a: [("2 + 2 = 4", "ds#0")])

    args = ["--out", str(out), "--leaf-model", "prover-A", "--leaf-template", "plain"]
    assert build_bank.main(args) == 0
    rows = list(build_bank.read_rows(out))
    # leaf_id carries the full sampling profile (M/T default markers included)
    assert rows and all(r["leaf_id"] == "prover-A|plain|Mdef|Tdef" for r in rows)

    # same leaf: resume runs fine (nothing new to do, no refusal)
    assert build_bank.main(args) == 0

    # different leaf against the same file: hard refusal before any work
    monkeypatch.setattr(build_bank, "_candidates", lambda a: [("1 + 1 = 2", "ds#1")])
    with pytest.raises(SystemExit, match="refusing to mix leaf models"):
        build_bank.main(["--out", str(out), "--leaf-model", "prover-B", "--leaf-template", "plain"])

    # elaborate-only runs carry no leaf_id and are exempt from the guard
    assert build_bank.main(["--out", str(out), "--elaborate-only"]) == 0


# ===========================================================================
# build_bank: statement-level concurrency (--concurrent N)
#
# The wide candidate sweep (FAMILIES.md "corridor widening" (1)) is bounded by
# leaf inference, not by Lean: PHASE0_NOTES measured 16.3 s/statement end-to-end
# against a 36.8k checks/hr verification ceiling. So the thing these tests
# protect is narrow and specific — N statements generating at once, every
# sqlite touch serialized, exactly one appender, and every invariant the
# sequential path already had (resume including errors, --repair, the leaf_id
# provenance guard) surviving out-of-order completion.
# ===========================================================================


class RecordingLock:
    """A lock that remembers who holds it.

    Two things a plain Lock cannot tell a test: whether a guarded call really
    ran *inside* the lock (`held_here`), and how many times the lock was taken
    (`n_acquires`, i.e. the number of serialized sections). `violations` is the
    tripwire — anything that should have been guarded and was not.
    """

    def __init__(self, name: str):
        self.name = name
        self._lock = threading.Lock()
        self._meta = threading.Lock()
        self.holder: int | None = None
        self.n_acquires = 0
        self.violations: list[str] = []

    def __enter__(self):
        self._lock.acquire()
        with self._meta:
            if self.holder is not None:
                self.violations.append(f"{self.name}: entered while held by {self.holder}")
            self.holder = threading.get_ident()
            self.n_acquires += 1
        return self

    def __exit__(self, *exc):
        with self._meta:
            self.holder = None
        self._lock.release()
        return False

    def held_here(self) -> bool:
        with self._meta:
            return self.holder == threading.get_ident()


class RecordingCache:
    """AttemptCache stand-in that asserts the serialization contract itself.

    Every call records (a) whether the shared cache lock was held by the calling
    thread and (b) how many cache calls were in flight at that moment. The
    single-writer claim of leaf/cache.py is then a pair of assertions —
    `violations` empty and `peak_in_flight == 1` — rather than a hope. Each call
    sleeps a hair so an unlocked implementation would overlap reliably instead
    of only under load.
    """

    def __init__(self, locks: dict):
        self.locks = locks
        self.path = ":memory:"           # non-callable attribute: must pass through
        self.ops: list[tuple[str, str]] = []
        self.violations: list[str] = []
        self.peak_in_flight = 0
        self._n = 0
        self._meta = threading.Lock()

    def _enter(self, op: str, key: str) -> None:
        lock = self.locks.get("cache")
        with self._meta:
            self._n += 1
            self.peak_in_flight = max(self.peak_in_flight, self._n)
            self.ops.append((op, key))
            if lock is None or not lock.held_here():
                self.violations.append(f"{op} ran outside the cache lock")
        time.sleep(0.005)

    def _exit(self) -> None:
        with self._meta:
            self._n -= 1

    def get_attempts(self, statement_key, model, sampling_key):
        self._enter("get_attempts", statement_key)
        try:
            return []
        finally:
            self._exit()

    def put_attempt(self, statement_key, model, sampling_key, idx, proof, verified=None):
        self._enter("put_attempt", statement_key)
        self._exit()

    def mark_verified(self, statement_key, model, sampling_key, idx, verified):
        self._enter("mark_verified", statement_key)
        self._exit()
        return True


class Rendezvous:
    """Blocks each generation until a second one joins, so "generation runs in
    parallel" is asserted rather than sampled. Serialized generation fails the
    peak assertion instead of merely being slow (each call costs `timeout`)."""

    def __init__(self, want: int = 2, timeout: float = 2.0):
        self.want, self.timeout = want, timeout
        self._lock = threading.Lock()
        self._ev = threading.Event()
        self._n = 0
        self.peak = 0

    def wait(self) -> None:
        with self._lock:
            self._n += 1
            self.peak = max(self.peak, self._n)
            if self._n >= self.want:
                self._ev.set()
        self._ev.wait(self.timeout)
        with self._lock:
            self._n -= 1


class StubCachingLeaf:
    """Leaf stand-in with `LeafProver.prove`'s real call shape (leaf/adapter.py):
    read the cache, generate (the slow HTTP phase — outside every lock), write
    the attempts, then kernel-check each attempt and write its verdict back.

    Only that shape makes the cache-serialization test meaningful: the whole
    point of the chosen seam is that the model call sits *between* cache calls,
    never inside one.
    """

    def __init__(self, cache=None, *, n_verified: int = 1, hook=None):
        self.cache = cache
        self.n_verified = n_verified
        self.hook = hook
        self.calls: list[tuple[str, int]] = []
        self.peak_in_flight = 0
        self._n = 0
        self._meta = threading.Lock()

    def prove(self, prop, k=8, backend=None, early_stop=True, timeout_s=120.0):
        assert backend is not None, "leaf must be handed the backend to verify with"
        assert early_stop is False, "the bank measures a rate: all k attempts must be checked"
        key = statement_key(prop)
        with self._meta:
            self._n += 1
            self.peak_in_flight = max(self.peak_in_flight, self._n)
        try:
            if self.cache is not None:
                self.cache.get_attempts(key, "stub", "s")
            if self.hook is not None:
                self.hook(prop)                      # stands in for the HTTP generation
            self.calls.append((prop, k))
            records = []
            for i in range(k):
                if self.cache is not None:
                    self.cache.put_attempt(key, "stub", "s", i, f"by proof{i}", None)
            for i in range(k):
                backend.check(f"theorem _proof_check : {prop} :=\n  by proof{i}")
                verified = i < self.n_verified
                if self.cache is not None:
                    self.cache.mark_verified(key, "stub", "s", i, verified)
                records.append(AttemptRecord(key, "stub", i, f"by proof{i}", verified))
            return (records[0].proof if self.n_verified else None), records
        finally:
            with self._meta:
                self._n -= 1


def _recording_locks(monkeypatch) -> dict:
    """Swap build_bank's lock factory for recording locks, keyed by name."""
    locks: dict[str, RecordingLock] = {}

    def factory(name):
        locks[name] = RecordingLock(name)
        return locks[name]

    monkeypatch.setattr(build_bank, "LOCK_FACTORY", factory)
    return locks


def _verifying_backend(fake_backend):
    """Elaborates every statement AND accepts every proof check."""
    _elaborating_backend(fake_backend)
    fake_backend.rule(lambda c: "_proof_check" in c, VerifyResult(ok=True, sorries=0))
    return fake_backend


def _props(n: int) -> list[dict]:
    return [{"formal_statement": f"theorem t{i} : P{i} := by sorry", "id": f"s{i}"} for i in range(n)]


# --- the flag ---------------------------------------------------------------

def test_concurrent_defaults_to_sequential_and_rejects_non_positive():
    assert build_bank.parse_args([]).concurrent == 1
    assert build_bank.parse_args(["--concurrent", "8"]).concurrent == 8
    with pytest.raises(SystemExit, match="--concurrent must be >= 1"):
        build_bank.main(["--concurrent", "0"])


# --- _SerializedCache -------------------------------------------------------

def test_serialized_cache_locks_calls_and_passes_attributes_through():
    """The proxy delegates totally (a method added to AttemptCache by another
    agent must not escape the lock) but only *calls* take the lock."""
    lock = RecordingLock("cache")
    cache = RecordingCache({"cache": lock})
    proxy = build_bank._SerializedCache(cache, lock)

    assert proxy.path == ":memory:"        # non-callable: no lock, no wrapper
    assert lock.n_acquires == 0
    proxy.put_attempt("k", "m", "s", 0, "by rfl", None)
    proxy.mark_verified("k", "m", "s", 0, True)
    assert lock.n_acquires == 2
    assert cache.violations == []          # both ran with the lock held
    assert [op for op, _ in cache.ops] == ["put_attempt", "mark_verified"]


# --- slice_index ------------------------------------------------------------

def test_sequential_rows_carry_slice_index_in_write_order(monkeypatch, fake_backend, tmp_path):
    """N=1 is unchanged apart from the new field, which there is just the write
    order — the reference the concurrent path has to reproduce as a permutation."""
    out = tmp_path / "bank.jsonl"
    _patch_bank_main(monkeypatch, _verifying_backend(fake_backend), _props(4),
                     StubCachingLeaf(n_verified=1))
    assert build_bank.main(["--out", str(out), "--backend", "fake", "--k", "2"]) == 0
    rows = build_bank.read_rows(out)
    assert [r["slice_index"] for r in rows] == [0, 1, 2, 3]
    ds = build_bank.DEFAULT_DATASET
    assert [r["source_id"] for r in rows] == [f"{ds}#s{i}" for i in range(4)]


def test_slice_index_counts_dispatched_statements_not_dataset_rows():
    """Skipped keys (resume) and duplicates must not create gaps: slice_index is
    the sequential *write* order, which is what makes it a reconstruction key."""
    targets = [("A", "ds#0"), ("B", "ds#1"), ("A", "ds#2"), ("C", "ds#3")]
    done = {statement_key("B")}
    assert list(build_bank._dispatch(targets, done)) == [(0, "A", "ds#0"), (1, "C", "ds#3")]


# --- the pipeline -----------------------------------------------------------

def test_concurrent_writes_every_row_even_when_completion_is_out_of_order(
    monkeypatch, fake_backend, tmp_path
):
    """Ordering independence, forced rather than hoped for: statement 0 blocks
    inside generation until three later rows are on disk, so its row provably
    lands after theirs. Completeness is asserted as a set + a slice_index
    bijection, never as a sequence."""
    out = tmp_path / "bank.jsonl"

    def hook(prop):
        if not prop.endswith("0"):
            return
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and len(build_bank.read_rows(out)) < 3:
            time.sleep(0.01)

    leaf = StubCachingLeaf(n_verified=1, hook=hook)
    _patch_bank_main(monkeypatch, _verifying_backend(fake_backend), _props(5), leaf)
    assert build_bank.main(
        ["--out", str(out), "--backend", "fake", "--k", "2", "--concurrent", "2"]
    ) == 0

    rows = build_bank.read_rows(out)
    ds = build_bank.DEFAULT_DATASET
    assert len(rows) == 5
    assert sorted(r["slice_index"] for r in rows) == [0, 1, 2, 3, 4]
    assert {r["source_id"] for r in rows} == {f"{ds}#s{i}" for i in range(5)}
    # slice_index still identifies the statement it was dispatched with
    assert {r["slice_index"]: r["source_id"] for r in rows} == {
        i: f"{ds}#s{i}" for i in range(5)
    }
    assert all(r["status"] == Status.VERIFIED for r in rows)
    # the point of the test: file order is a permutation of dispatch order
    assert [r["slice_index"] for r in rows[:3]] == [1, 2, 3]
    assert [r["slice_index"] for r in rows].index(0) >= 3


def test_concurrent_serializes_every_cache_call_while_generation_stays_parallel(
    monkeypatch, fake_backend, tmp_path
):
    """The load-bearing test for the seam choice (build_bank module docstring).

    Cache access: one lock, never two calls in flight — the single-writer
    contract of leaf/cache.py. Generation: genuinely concurrent, which is the
    only reason --concurrent exists (inference is ~99% of the wall clock).
    Writer: exactly one appender, one lock acquisition per row.
    """
    out = tmp_path / "bank.jsonl"
    locks = _recording_locks(monkeypatch)
    rv = Rendezvous(want=2)
    cache = RecordingCache(locks)
    leaf = StubCachingLeaf(cache=cache, n_verified=1, hook=lambda prop: rv.wait())
    _patch_bank_main(monkeypatch, _verifying_backend(fake_backend), _props(4), leaf)

    assert build_bank.main(
        ["--out", str(out), "--backend", "fake", "--k", "2", "--concurrent", "2"]
    ) == 0

    assert set(locks) == {"cache", "writer"}
    # every sqlite touch happened under the one cache lock, one at a time
    assert cache.violations == []
    assert cache.peak_in_flight == 1
    assert locks["cache"].violations == []
    # 4 statements x (1 get + 2 put + 2 mark) = 20 serialized sections
    assert len(cache.ops) == 20 and locks["cache"].n_acquires == 20
    # ...while generation overlapped: the whole reason for the flag
    assert rv.peak == 2
    assert leaf.peak_in_flight == 2
    # one appender, one lock acquisition per row, four intact rows
    assert locks["writer"].violations == []
    assert locks["writer"].n_acquires == 4
    assert len(build_bank.read_rows(out)) == 4


def test_sequential_run_does_not_wrap_the_cache(monkeypatch, fake_backend, tmp_path):
    """N=1 keeps today's path exactly: no proxy, no locks taken around sqlite."""
    out = tmp_path / "bank.jsonl"
    locks = _recording_locks(monkeypatch)
    cache = RecordingCache(locks)
    leaf = StubCachingLeaf(cache=cache, n_verified=1)
    _patch_bank_main(monkeypatch, _verifying_backend(fake_backend), _props(2), leaf)

    assert build_bank.main(["--out", str(out), "--backend", "fake", "--k", "2"]) == 0
    assert leaf.cache is cache                       # never replaced by the proxy
    assert set(locks) == {"writer"}                  # no cache lock is even created
    assert len(cache.ops) == 10                      # calls still happened, just unguarded
    assert cache.violations                          # ...which is exactly what "unguarded" means
    assert locks["writer"].n_acquires == 2           # the appender is locked in both modes


def test_concurrent_keeps_at_most_n_statements_in_flight(monkeypatch, fake_backend, tmp_path):
    """Bounded pipeline: the dataset is streamed (140k rows), so the submission
    window — not the row count — must cap memory and in-flight leaf calls."""
    out = tmp_path / "bank.jsonl"
    leaf = StubCachingLeaf(n_verified=1, hook=lambda prop: time.sleep(0.01))
    _patch_bank_main(monkeypatch, _verifying_backend(fake_backend), _props(12), leaf)

    assert build_bank.main(
        ["--out", str(out), "--backend", "fake", "--k", "1", "--concurrent", "3"]
    ) == 0
    assert len(build_bank.read_rows(out)) == 12
    assert leaf.peak_in_flight <= 3


def test_concurrent_error_rows_are_written_and_then_skipped_on_resume(
    monkeypatch, fake_backend, tmp_path
):
    """resume-including-errors (../rl run_eval.existing_ids) under concurrency:
    an infrastructure failure is a row, and a plain re-run must not retry it —
    silent retry would make a measured pass rate depend on run history."""
    out = tmp_path / "bank.jsonl"

    class HalfBrokenBackend:
        """Thread-safe by construction: no shared mutable state but a counter."""

        def __init__(self):
            self.lock = threading.Lock()
            self.checked: list[str] = []

        def check(self, code, timeout_s=120.0):
            with self.lock:
                self.checked.append(code)
            if "P1" in code:
                raise RuntimeError("repl died")
            return VerifyResult(ok=True, sorries=1 if "_stmt_check" in code else 0)

        def close(self):
            pass

    backend = HalfBrokenBackend()
    leaf = StubCachingLeaf(n_verified=1)
    monkeypatch.setattr(build_bank, "load_rows", lambda args: iter(_props(3)))
    monkeypatch.setattr(build_bank, "make_backend", lambda args: backend)
    monkeypatch.setattr(build_bank, "make_leaf", lambda args: leaf)

    argv = ["--out", str(out), "--backend", "fake", "--k", "1", "--concurrent", "2"]
    assert build_bank.main(argv) == 0
    rows = {r["slice_index"]: r for r in build_bank.read_rows(out)}
    assert len(rows) == 3
    assert rows[1]["status"] == Status.ERROR and "repl died" in rows[1]["detail"]
    assert {rows[0]["status"], rows[2]["status"]} == {Status.VERIFIED}

    n_before = len(backend.checked)
    assert build_bank.main(argv) == 0                 # resume: error row NOT retried
    assert len(build_bank.read_rows(out)) == 3
    assert len(backend.checked) == n_before


def test_concurrent_repair_reruns_only_error_rows(monkeypatch, fake_backend, tmp_path):
    """--repair under concurrency (the 222-row recovery path, PHASE0_NOTES
    2026-08-12): measurements survive untouched, error rows are re-measured, and
    slice_index numbers the repair batch."""
    out = tmp_path / "bank.jsonl"
    _write_rows(out, [
        {"statement_key": "keep", "prop": "K", "source_id": "ds#k", "status": Status.LEAF_FAILED},
        {"statement_key": statement_key("E1"), "prop": "E1", "source_id": "ds#e1",
         "status": Status.ERROR},
        {"statement_key": "keep2", "prop": "K2", "source_id": "ds#k2",
         "status": Status.STATEMENT_ILL_FORMED},
        {"statement_key": statement_key("E2"), "prop": "E2", "source_id": "ds#e2",
         "status": Status.ERROR},
    ])
    leaf = StubCachingLeaf(n_verified=1)
    monkeypatch.setattr(
        build_bank, "load_rows",
        lambda args: (_ for _ in ()).throw(AssertionError("repair must not stream the dataset")),
    )
    monkeypatch.setattr(build_bank, "make_backend", lambda args: _verifying_backend(fake_backend))
    monkeypatch.setattr(build_bank, "make_leaf", lambda args: leaf)

    assert build_bank.main(
        ["--out", str(out), "--backend", "fake", "--repair", "--k", "2", "--concurrent", "2"]
    ) == 0
    rows = build_bank.read_rows(out)
    kept = [r for r in rows if r.get("slice_index") is None]
    repaired = {r["source_id"]: r for r in rows if r.get("slice_index") is not None}
    assert [r["source_id"] for r in kept] == ["ds#k", "ds#k2"]      # rewritten first, in order
    assert [r["status"] for r in kept] == [Status.LEAF_FAILED, Status.STATEMENT_ILL_FORMED]
    assert set(repaired) == {"ds#e1", "ds#e2"}
    assert all(r["status"] == Status.VERIFIED for r in repaired.values())
    assert sorted(r["slice_index"] for r in repaired.values()) == [0, 1]
    assert sorted(p for p, _ in leaf.calls) == ["E1", "E2"]


def test_concurrent_preserves_the_leaf_provenance_guard(monkeypatch, fake_backend, tmp_path):
    """The guard is a refusal *before any work* — concurrency must not turn it
    into a race that lets one thread's row land first (DIRECTION.md §5.4: the
    bank IS the delegability oracle)."""
    out = tmp_path / "bank.jsonl"
    _verifying_backend(fake_backend)
    monkeypatch.setattr(build_bank, "make_backend", lambda a: fake_backend)
    monkeypatch.setattr(build_bank, "make_leaf", lambda a: StubCachingLeaf(n_verified=1))
    monkeypatch.setattr(
        build_bank, "_candidates", lambda a: [("2 + 2 = 4", "ds#0"), ("1 + 1 = 2", "ds#1")]
    )

    base = ["--out", str(out), "--concurrent", "2", "--k", "1", "--leaf-template", "plain"]
    assert build_bank.main([*base, "--leaf-model", "prover-A"]) == 0
    rows = build_bank.read_rows(out)
    assert len(rows) == 2
    assert all(r["leaf_id"] == "prover-A|plain|Mdef|Tdef" for r in rows)

    monkeypatch.setattr(build_bank, "_candidates", lambda a: [("3 + 3 = 6", "ds#2")])
    with pytest.raises(SystemExit, match="refusing to mix leaf models"):
        build_bank.main([*base, "--leaf-model", "prover-B"])
    assert len(build_bank.read_rows(out)) == 2       # refused before writing anything


def test_concurrent_resume_only_measures_the_new_statements(monkeypatch, fake_backend, tmp_path):
    """Resume mid-pipeline: a killed sweep restarts on the rows it never wrote,
    and re-numbers slice_index from 0 for the new batch (per-run, by contract)."""
    out = tmp_path / "bank.jsonl"
    leaf = StubCachingLeaf(n_verified=1)
    _patch_bank_main(monkeypatch, _verifying_backend(fake_backend), _props(3), leaf)
    assert build_bank.main(
        ["--out", str(out), "--backend", "fake", "--k", "1", "--concurrent", "2"]
    ) == 0
    assert len(build_bank.read_rows(out)) == 3

    # same three statements plus two new ones, as a resumed sweep would see
    monkeypatch.setattr(build_bank, "load_rows", lambda args: iter(_props(5)))
    assert build_bank.main(
        ["--out", str(out), "--backend", "fake", "--k", "1", "--concurrent", "2"]
    ) == 0
    rows = build_bank.read_rows(out)
    ds = build_bank.DEFAULT_DATASET
    assert len(rows) == 5
    assert {r["source_id"] for r in rows} == {f"{ds}#s{i}" for i in range(5)}
    assert sorted(p for p, _ in leaf.calls) == [f"P{i}" for i in range(5)]   # each measured once
    assert sorted(r["slice_index"] for r in rows[3:]) == [0, 1]


def test_concurrent_keeps_the_elaboration_gate_in_front_of_generation(
    monkeypatch, fake_backend, tmp_path
):
    """Per-statement, before any leaf work, exactly as in the sequential path:
    a statement that does not elaborate must never cost a generation."""
    out = tmp_path / "bank.jsonl"
    fake_backend.rule(
        lambda c: "_stmt_check" in c and "P2" in c,
        VerifyResult(ok=False, messages=[LeanMessage("error", "unknown identifier")]),
    )
    leaf = StubCachingLeaf(n_verified=1)
    _patch_bank_main(monkeypatch, _verifying_backend(fake_backend), _props(4), leaf)

    assert build_bank.main(
        ["--out", str(out), "--backend", "fake", "--k", "2", "--concurrent", "2"]
    ) == 0
    rows = {r["slice_index"]: r for r in build_bank.read_rows(out)}
    assert rows[2]["status"] == Status.STATEMENT_ILL_FORMED
    assert rows[2]["n_attempts"] == 0 and rows[2]["pass_rate"] is None
    assert sorted(p for p, _ in leaf.calls) == ["P0", "P1", "P3"]


def test_concurrent_elaborate_only_never_builds_a_leaf(monkeypatch, fake_backend, tmp_path):
    """Offline twin of the live N=2 sanity run below (that one needs Mathlib)."""
    out = tmp_path / "bank.jsonl"
    monkeypatch.setattr(build_bank, "load_rows", lambda args: iter(_props(6)))
    monkeypatch.setattr(build_bank, "make_backend", lambda args: _elaborating_backend(fake_backend))
    monkeypatch.setattr(build_bank, "make_leaf", lambda args: pytest.fail("leaf built"))

    assert build_bank.main(
        ["--out", str(out), "--backend", "fake", "--elaborate-only", "--concurrent", "3"]
    ) == 0
    rows = build_bank.read_rows(out)
    assert len(rows) == 6
    assert sorted(r["slice_index"] for r in rows) == list(range(6))
    assert all(r["status"] == build_bank.STATUS_ELABORATED and r["leaf_id"] is None for r in rows)


# --- integration: real ReplPool ---------------------------------------------

@pytest.mark.integration
@pytest.mark.timeout(1800)
def test_live_concurrent_elaborate_only_over_workbook_statements(monkeypatch, tmp_path):
    """N=2 over 8 Lean-Workbook-shaped rows against a real 2-worker ReplPool.

    Sanity, not benchmark: the concurrent path must drive a genuinely shared,
    thread-safe backend (ReplPool hands one worker to one caller at a time) and
    come back with 8 complete, correctly-indexed rows. Elaborate-only keeps it
    off any model server — the leaf half is covered offline above.
    """
    from rlmath.lean.repl_pool import ReplConfig

    cfg = ReplConfig()
    if not cfg.available():
        pytest.skip(f"no lean project/repl binary at {cfg.project_dir} / {cfg.repl_bin}")

    rows = [
        {"formal_statement": s, "id": f"lw{i}"}
        for i, s in enumerate([
            "theorem lw_a (x : ℝ) (hx : 0 < x) : x / x = 1 := by sorry",
            "theorem lw_b (n : ℕ) : n + 0 = n := by sorry",
            "theorem lw_c (a b : ℝ) : (a + b) ^ 2 = a ^ 2 + 2 * a * b + b ^ 2 := by sorry",
            "theorem lw_d (x : ℝ) : Real.sin x ^ 2 + Real.cos x ^ 2 = 1 := by sorry",
            "theorem lw_e (n : ℕ) (hn : 0 < n) : 1 ≤ n := by sorry",
            "theorem lw_f (a b c : ℝ) (ha : 0 < a) (hb : 0 < b) (hc : 0 < c) : 0 < a * b * c := by sorry",
            "theorem lw_g (x : ℝ) (hx : 0 ≤ x) : Real.sqrt x ^ 2 = x := by sorry",
            "theorem lw_h (n : ℕ) : ∑ i in Finset.range n, (1 : ℕ) = n := by sorry",
        ])
    ]
    monkeypatch.setattr(build_bank, "load_rows", lambda args: iter(rows))
    out = tmp_path / "bank.jsonl"

    # main() owns the pool's lifecycle and closes it in its finally block.
    assert build_bank.main([
        "--out", str(out), "--backend", "repl", "--workers", "2",
        "--concurrent", "2", "--elaborate-only", "--timeout-s", "300",
    ]) == 0

    written = build_bank.read_rows(out)
    assert len(written) == 8
    assert sorted(r["slice_index"] for r in written) == list(range(8))
    assert {r["source_id"] for r in written} == {f"{build_bank.DEFAULT_DATASET}#lw{i}" for i in range(8)}
    assert all(r["leaf_id"] is None for r in written)
    bad = [(r["source_id"], r["status"], r["detail"][:200]) for r in written
           if r["status"] != build_bank.STATUS_ELABORATED]
    assert not bad, bad
