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
