"""Mutation breeding: rlmath.families.mutate + scripts/breed_mutants.py.

Offline by default — the only Lean in this file is conftest's FakeBackend, and
the one live-toolchain test is `@pytest.mark.integration` (deselected by the
pyproject addopts). The parent statements below are verbatim in-band rows from
`data/bank/bank_dsv2.jsonl` (pass_rate ∈ [0.25, 0.9]); that file is READ-ONLY
here and one test asserts the script never writes to it.

What is actually being pinned (FAMILIES.md corridor-widening source 2):
determinism in (prop, seed), parse-level structure preservation, key freshness
=> independent leaf_split membership, replayable provenance, and elaboration
gating.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from rlmath.core.types import Status, VerifyResult, normalize_statement, statement_key
from rlmath.families.leaf_split import leaf_split
from rlmath.families.mutate import (
    GUARD_HEADS,
    MAG_HI,
    MAG_LO,
    MAX_EXPONENT,
    MIN_EXPONENT,
    OP_KINDS,
    MutationOp,
    apply_ops,
    assert_structure_preserved,
    binder_names,
    identifiers,
    mutants,
    numeral_sites,
    relation_tokens,
    site_candidates,
    skeleton,
)

ROOT = Path(__file__).resolve().parent.parent
BANK = ROOT / "data" / "bank" / "bank_dsv2.jsonl"


def _load_script(name: str):
    """scripts/ is not a package (tests/test_scripts.py uses the same loader)."""
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_script_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


breed = _load_script("breed_mutants")


# Real band rows (bank_dsv2.jsonl, DSV2-7B pass@8 ∈ [0.25, 0.9]).
P_INEQ = (
    "∀ (a b c : ℝ) (hab : a > 0 ∧ b > 0 ∧ c > 0) (habc : a * b + b * c + c * a = 3), "
    "3 * (a + b + c) + a * b * c ≥ 10"
)
P_IFF = "p ^ 6 - 27 * q ^ 2 * p ^ 2 + 54 * q ^ 3 ≥ 0 ↔ (p ^ 2 - 3 * q) ^ 2 ≥ 0"
P_SQRT = (
    "∀ (a b c : ℝ), 2 * (1 + a * b * c) + 2 * Real.sqrt (2 * (1 + a ^ 2) * (1 + b ^ 2) * "
    "(1 + c ^ 2)) ≥ (1 + a) * (1 + b) * (1 + c)"
)
P_SUM = (
    "∑ k ∈ Finset.filter (λ x => ¬ (4 ∣ x ∨ 7 ∣ x)) (Finset.range 100), 1 = 64"
)
P_FRAC = "∀ (a b : ℝ) (ha : 0 ≤ a) (hb : 0 ≤ b) (hab : a + b = 3), 3*a^3*b^2 + a*b^4 ≤ 243/8"
CORPUS = [P_INEQ, P_IFF, P_SQRT, P_SUM, P_FRAC]


# ---------------------------------------------------------------------------
# Determinism (deterministic in (prop, seed))
# ---------------------------------------------------------------------------

def test_corpus_is_really_in_band_bank_rows():
    """Pins the "verbatim band rows" claim: if the bank is re-swept and these
    statements stop being in band, this file is testing fiction."""
    band = {r["prop"] for r in breed.band_parents(breed.read_rows(BANK))}
    assert band, "no band rows in the bank"
    missing = [p[:60] for p in CORPUS if p not in band]
    assert not missing, f"no longer in-band bank rows: {missing}"


def test_deterministic_in_prop_and_seed():
    for p in CORPUS:
        a = [m.prop for m in mutants(p, seed=7, n=6)]
        b = [m.prop for m in mutants(p, seed=7, n=6)]
        assert a == b and a, p


def test_determinism_survives_whitespace_normalization():
    """The seed material is the NORMALIZED prop, so a reformatted parent breeds
    the same children (core.types.normalize_statement is the cache-key rule)."""
    spaced = "  ∀ (a b c : ℝ) (hab : a > 0 ∧ b > 0 ∧ c > 0)   (habc : a * b + b * c + c * a = 3),\n" \
             "3 * (a + b + c) + a * b * c ≥ 10 "
    assert normalize_statement(spaced) == P_INEQ
    assert [m.prop for m in mutants(spaced, seed=1, n=5)] == [m.prop for m in mutants(P_INEQ, seed=1, n=5)]


def test_seed_changes_the_population():
    a = [m.prop for m in mutants(P_INEQ, seed=1, n=6)]
    b = [m.prop for m in mutants(P_INEQ, seed=2, n=6)]
    assert a != b


def test_prefix_stable_in_n():
    """Raising n on a re-run extends the population instead of re-rolling it."""
    for p in CORPUS:
        long = [m.prop for m in mutants(p, seed=3, n=8)]
        assert [m.prop for m in mutants(p, seed=3, n=3)] == long[:3]


def test_rng_is_not_process_salted():
    """Determinism must hold ACROSS processes, not just within one.

    A `hash()`-seeded RNG passes every in-process determinism test above and
    still breaks reproduction on another machine (PYTHONHASHSEED is random by
    default). Two subprocesses with different hash seeds must agree with each
    other and with this process.
    """
    src = (
        "import hashlib\n"
        "from rlmath.families.mutate import mutants\n"
        f"p = {P_IFF!r}\n"
        "print(hashlib.sha256('\\n'.join(m.prop for m in mutants(p, seed=42, n=5))"
        ".encode()).hexdigest())\n"
    )
    here = hashlib.sha256(
        "\n".join(m.prop for m in mutants(P_IFF, seed=42, n=5)).encode()
    ).hexdigest()
    outs = []
    for hashseed in ("0", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": hashseed}
        proc = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, env=env)
        assert proc.returncode == 0, proc.stderr
        outs.append(proc.stdout.strip())
    assert outs[0] == outs[1] == here


# ---------------------------------------------------------------------------
# Structure preservation (parse-level)
# ---------------------------------------------------------------------------

def test_binders_functions_and_relations_are_frozen():
    for p in CORPUS:
        ms = mutants(p, seed=11, n=8)
        assert ms
        for m in ms:
            assert skeleton(m.prop) == skeleton(p)
            assert binder_names(m.prop) == binder_names(p)
            assert identifiers(m.prop) == identifiers(p)
            assert relation_tokens(m.prop) == relation_tokens(p)
            assert m.prop != p
            assert_structure_preserved(p, m.prop)


def test_structure_guard_is_not_vacuous():
    """The invariant that gates every emitted mutant must actually reject the
    three forbidden edits (module docstring), or it certifies nothing."""
    cases = [
        (P_INEQ, P_INEQ.replace("≥ 10", "≤ 10")),                 # direction flipped
        (P_SQRT, P_SQRT.replace("Real.sqrt", "Real.log")),        # function identity
        (P_INEQ, P_INEQ.replace("∀ (a b c : ℝ)", "∀ (a b c d : ℝ)")),   # binder added
        (P_INEQ, P_INEQ.replace("(hab : a > 0 ∧ b > 0 ∧ c > 0) ", "")),  # binder dropped
    ]
    for parent, bad in cases:
        assert bad != parent, "the edit under test did not change anything"
        with pytest.raises(ValueError):
            assert_structure_preserved(parent, bad)
    # ...and it accepts a legal numeral-only edit
    assert_structure_preserved(P_INEQ, P_INEQ.replace("≥ 10", "≥ 11"))


def test_binder_names_are_actually_parsed():
    """Guard against the invariant being vacuous (an empty tuple would compare
    equal for every mutant)."""
    assert binder_names(P_INEQ) == ("a", "b", "c", "hab", "habc")
    assert binder_names(P_SQRT) == ("a", "b", "c")
    assert binder_names(P_IFF) == ()          # no leading ∀-telescope


def test_identifiers_include_function_symbols():
    assert "Real.sqrt" in identifiers(P_SQRT)
    assert "Finset.filter" in identifiers(P_SUM) and "Finset.range" in identifiers(P_SUM)


def test_inequality_direction_never_flips():
    """v1 rule: `≤` never becomes `≥`. Checked as a per-symbol count so a swap
    that preserved the multiset would still be caught by the ordered tuple."""
    for p in CORPUS:
        base = relation_tokens(p)
        for m in mutants(p, seed=5, n=8):
            got = relation_tokens(m.prop)
            assert got == base
            for sym in ("≤", "≥", "<", ">", "↔", "→", "="):
                assert got.count(sym) == base.count(sym)


def test_no_sign_flip_and_no_new_numerals():
    for p in CORPUS:
        for m in mutants(p, seed=9, n=8):
            assert m.prop.count("-") == p.count("-")
            assert skeleton(m.prop).count("#") == skeleton(p).count("#")


# ---------------------------------------------------------------------------
# Site classification and value windows
# ---------------------------------------------------------------------------

def test_identifier_digits_are_not_numerals():
    """`h1`, `hx1`, `p.2` must never be seen as mutable constants."""
    prop = "∀ (x : ℝ) (h1 : 0 < x) (hx1 : x ≠ 1), x ^ 2 > 0"
    sites = numeral_sites(prop)
    # h1's "1" and hx1's "1" are absent entirely; the four found are the real
    # literals `0 <`, `≠ 1`, `^ 2`, `> 0`.
    assert [(s.text, s.kind) for s in sites] == [
        ("0", "bound"), ("1", "bound"), ("2", "exponent"), ("0", "bound"),
    ]
    assert all(s.mutable for s in sites)
    assert "h1" in identifiers(prop) and "hx1" in identifiers(prop)


def test_index_set_and_type_level_numerals_are_guarded():
    sites = {s.text: s for s in numeral_sites(P_SUM)}
    assert sites["100"].mutable is False and "Finset.range" in sites["100"].reason
    assert sites["64"].mutable is True and sites["64"].kind == "bound"
    for head in ("Fin", "ZMod", "Finset.Icc"):
        assert head in GUARD_HEADS
    both = numeral_sites("∀ n : ℕ, ∑ i ∈ Finset.Icc 1 5, (i : ℝ) ≤ 20")
    assert [(s.text, s.mutable) for s in both] == [("1", False), ("5", False), ("20", True)]


def test_bound_classification_is_the_whole_operand():
    """A numeral welded to an arithmetic operator is a coefficient even when it
    sits next to the relation: `≥ (1 + a) * (1 + b)` has no bound at all."""
    kinds = [(s.text, s.kind) for s in numeral_sites("∀ a b : ℝ, a * b ≥ (1 + a) * (1 + b)")]
    assert kinds == [("1", "const"), ("1", "const")]
    frac = [(s.text, s.kind) for s in numeral_sites("∀ a : ℝ, a ≤ 243/8")]
    assert frac == [("243", "bound"), ("8", "const")]     # one rational bound, not two terms
    assert [(s.text, s.kind) for s in numeral_sites("∀ x : ℝ, x - 1 ≤ x ∧ 0 < x")] == [
        ("1", "const"), ("0", "bound"),
    ]


def test_decimal_literals_are_not_split_or_mutated():
    sites = numeral_sites("∀ x : ℝ, 0.5 * x ≤ x")
    assert [s.text for s in sites] == ["0.5"]
    assert sites[0].mutable is False and "decimal" in sites[0].reason


def test_exponent_window():
    for p in CORPUS:
        for m in mutants(p, seed=13, n=12):
            for op in m.ops:
                if op.kind == "exponent_delta":
                    old, new = int(op.old), int(op.new)
                    assert MIN_EXPONENT <= new <= MAX_EXPONENT
                    assert abs(new - old) <= 2 and new != old


def test_magnitude_preserving_jitter():
    for p in CORPUS:
        for m in mutants(p, seed=17, n=12):
            for op in m.ops:
                if op.kind in ("const_jitter", "bound_shift"):
                    old, new = int(op.old), int(op.new)
                    assert new != 0, "a zero constant deletes a term (shape change)"
                    if old == 0:
                        assert op.kind == "bound_shift" and new in (1, 2)
                    else:
                        assert MAG_LO * old <= new <= MAG_HI * old


def test_zero_coefficient_is_never_conjured():
    """A const-position 0 stays put: turning `0` into `3` invents a term."""
    site = next(s for s in numeral_sites("∀ x : ℝ, x * 0 + x ≥ x") if s.text == "0")
    assert site.kind == "const"
    assert site_candidates(site) == []


def test_op_kinds_are_the_declared_three():
    seen = set()
    for p in CORPUS:
        for m in mutants(p, seed=23, n=12):
            seen.update(o.kind for o in m.ops)
    assert seen and seen <= set(OP_KINDS)


def test_max_ops_is_respected():
    for p in CORPUS:
        assert all(len(m.ops) == 1 for m in mutants(p, seed=4, n=8, max_ops=1))
        assert all(1 <= len(m.ops) <= 2 for m in mutants(p, seed=4, n=8, max_ops=2))


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

def test_ops_replay_to_the_mutant():
    for p in CORPUS:
        for m in mutants(p, seed=19, n=8):
            assert apply_ops(m.parent_prop, m.ops) == m.prop
            assert apply_ops(p, [o.as_dict() for o in m.ops]) == m.prop


def test_op_positions_point_at_the_old_text():
    base = normalize_statement(P_FRAC)
    for m in mutants(P_FRAC, seed=21, n=8):
        for op in m.ops:
            assert base[op.pos : op.pos + len(op.old)] == op.old


def test_apply_ops_rejects_mismatched_provenance():
    with pytest.raises(ValueError):
        apply_ops(P_INEQ, [MutationOp("const_jitter", 0, "999", "1000")])
    with pytest.raises(ValueError):
        apply_ops(P_INEQ, [MutationOp("const_jitter", 80, "3", "4"),
                           MutationOp("bound_shift", 80, "3", "5")])


def test_row_shape():
    m = mutants(P_INEQ, seed=42, n=1)[0]
    row = m.as_row()
    assert set(row) == {"statement_key", "prop", "source_id", "parent_key", "mutation_ops"}
    assert row["source_id"] == f"mutant:{statement_key(P_INEQ)}"
    assert row["parent_key"] == statement_key(P_INEQ)
    assert row["statement_key"] == statement_key(row["prop"])
    assert all(set(o) == {"kind", "pos", "old", "new"} for o in row["mutation_ops"])


# ---------------------------------------------------------------------------
# Key freshness -> independent leaf_split membership
# ---------------------------------------------------------------------------

def test_keys_are_fresh():
    """families/leaf_split.py: membership is a pure function of statement_key, so
    a fresh key is exactly what buys independent membership."""
    for p in CORPUS:
        pk = statement_key(p)
        keys = {m.statement_key for m in mutants(p, seed=31, n=8)}
        assert pk not in keys
        assert len(keys) == len(mutants(p, seed=31, n=8))   # distinct props -> distinct keys


def test_membership_is_independent_of_the_parent():
    """Not merely "a different key": the derived pool must actually differ for
    some mutants, or the near-duplicate channel the script flags would not exist."""
    pairs = [
        (leaf_split(statement_key(p)), leaf_split(m.statement_key))
        for p in CORPUS
        for m in mutants(p, seed=42, n=8)
    ]
    assert any(a != b for a, b in pairs), "no mutant crossed pools — split not independent"
    assert any(a == b for a, b in pairs)


# ---------------------------------------------------------------------------
# scripts/breed_mutants.py
# ---------------------------------------------------------------------------

class _StubBackend:
    """Elaboration oracle: every statement_check passes unless its prop contains
    a poisoned substring. Automation battery closes nothing unless told to."""

    def __init__(self, reject: tuple[str, ...] = (), battery_closes: tuple[str, ...] = ()):
        self.reject, self.battery = reject, battery_closes
        self.codes: list[str] = []

    def check(self, code: str, *, timeout_s: float = 120.0) -> VerifyResult:
        self.codes.append(code)
        if "_stmt_check" in code:
            bad = any(tok in code for tok in self.reject)
            return VerifyResult(ok=not bad, sorries=0 if bad else 1)
        return VerifyResult(ok=any(tok in code for tok in self.battery), sorries=0)

    def check_many(self, codes, *, timeout_s: float = 120.0):
        return [self.check(c, timeout_s=timeout_s) for c in codes]

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def stub_backend(monkeypatch):
    holder: dict[str, _StubBackend] = {}

    def install(**kw) -> _StubBackend:
        b = _StubBackend(**kw)
        holder["b"] = b
        monkeypatch.setattr(breed, "FAKE_BACKEND_FACTORY", lambda: b)
        return b

    return install


def _run(tmp_path: Path, *extra: str) -> tuple[int, list[dict]]:
    out = tmp_path / "mutants_candidates.jsonl"
    rc = breed.main(["--backend", "fake", "--out", str(out), *extra])
    text = out.read_text() if out.exists() else ""    # gating everything writes no file
    return rc, [json.loads(line) for line in text.splitlines() if line.strip()]


def test_band_parents_uses_measured_rates_only():
    rows = [
        {"prop": "a", "pass_rate": 0.5},
        {"prop": "b", "pass_rate": None},      # unmeasured is not 0.0
        {"prop": "c", "pass_rate": 0.0},
        {"prop": "d", "pass_rate": 1.0},
        {"prop": "e", "pass_rate": 0.9},
        {"prop": "", "pass_rate": 0.5},        # no statement
        {"prop": "g", "pass_rate": True},      # bool is not a rate
    ]
    assert [r["prop"] for r in breed.band_parents(rows)] == ["a", "e"]


def test_script_emits_gated_rows(tmp_path, stub_backend):
    stub_backend()
    rc, rows = _run(tmp_path, "--limit-parents", "4", "--per-parent", "3", "--seed", "42")
    assert rc == 0 and len(rows) == 12
    for r in rows:
        assert r["source_id"] == f"mutant:{r['parent_key']}"
        assert r["statement_key"] == statement_key(r["prop"])
        assert r["parent_split"] == leaf_split(r["parent_key"])
        # membership is INHERITED (strategist catch 2026-08-12); own-key rolls are gone
        assert r["leaf_pool"] == r["parent_split"]
        assert "split" not in r
        assert 0.25 <= r["parent_pass_rate"] <= 0.9
        assert r["mutation_ops"] and all(o["kind"] in OP_KINDS for o in r["mutation_ops"])
    assert len({r["statement_key"] for r in rows}) == len(rows)


def test_elaboration_gating_drops_failures(tmp_path, stub_backend):
    """FakeBackend rejects any statement containing `≥ 11`; those mutants must
    not reach the file, and the parent must still fill its quota from the rest."""
    b = stub_backend(reject=("≥ 11",))
    _rc, rows = _run(tmp_path, "--limit-parents", "1", "--per-parent", "3", "--seed", "42")
    assert rows and all("≥ 11" not in r["prop"] for r in rows)
    assert any("_stmt_check" in c for c in b.codes)
    # the gate ran on more candidates than were emitted (oversample did its job)
    assert sum("_stmt_check" in c for c in b.codes) > len(rows)


def test_elaboration_gate_is_not_bypassable(tmp_path, stub_backend):
    """If nothing elaborates, nothing is written — no unchecked row ever lands."""
    stub_backend(reject=("∀", "^", "∑"))
    _rc, rows = _run(tmp_path, "--limit-parents", "3", "--per-parent", "2")
    assert rows == []


def test_battery_filter_drops_auto_closable(tmp_path, stub_backend):
    b = stub_backend(battery_closes=("≥ 11",))
    _rc, rows = _run(tmp_path, "--limit-parents", "1", "--per-parent", "3",
                     "--seed", "42", "--battery-filter")
    assert rows and all("≥ 11" not in r["prop"] for r in rows)
    assert any("_proof_check" in c for c in b.codes)


def test_battery_filter_skips_trivial_parents(tmp_path, stub_backend):
    """The corridor floor applies to the parent too: a band row the battery
    closes breeds nothing (measured 2026-08-12: 6/37 DSV2 band rows are)."""
    from rlmath.families.validate import battery_proofs

    parent = breed.band_parents(breed.read_rows(BANK))[0]
    b = stub_backend(battery_closes=(parent["prop"][-24:],))   # closes the parent
    _rc, rows = _run(tmp_path, "--limit-parents", "1", "--per-parent", "3", "--battery-filter")
    assert rows == []
    # exactly ONE battery run happened: the parent's. No mutant was ever checked,
    # which is the whole point (12 skipped checks per trivial lineage).
    assert sum("_proof_check" in c for c in b.codes) == len(battery_proofs())

    b = stub_backend()                            # nothing closes -> the lineage breeds normally
    _rc, rows = _run(tmp_path / "b", "--limit-parents", "1", "--per-parent", "3", "--battery-filter")
    assert len(rows) == 3
    assert sum("_proof_check" in c for c in b.codes) == 4 * len(battery_proofs())  # parent + 3


def test_battery_filter_off_by_default(tmp_path, stub_backend):
    b = stub_backend()
    _run(tmp_path, "--limit-parents", "1", "--per-parent", "2")
    assert not any("_proof_check" in c for c in b.codes)


def _rejects(tmp_path: Path) -> list[dict]:
    p = tmp_path / "mutants_candidates.jsonl.rejects.jsonl"
    text = p.read_text() if p.exists() else ""
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_rejections_are_logged_with_reasons(tmp_path, stub_backend):
    """FAMILIES.md wants rejection reasons logged, not just counted — the
    op-kind → reason table is what designs the next mutation schema."""
    stub_backend(reject=("≥ 11",), battery_closes=("≥ 12",))
    _rc, rows = _run(tmp_path, "--limit-parents", "1", "--per-parent", "3",
                     "--seed", "42", "--battery-filter")
    rej = _rejects(tmp_path)
    assert rej, "nothing was rejected — the fixture no longer poisons any mutant"
    reasons = {r["reject_reason"].split(":")[0] for r in rej}
    assert reasons <= {"elaboration", "battery"}
    for r in rej:
        assert r["parent_key"] and r["mutation_ops"]
        assert "statement" not in r and "id" not in r   # never ingestable as a candidate
    assert {r["statement_key"] for r in rej}.isdisjoint({r["statement_key"] for r in rows})


def test_rejected_candidates_are_not_re_gated_on_resume(tmp_path, stub_backend):
    stub_backend(reject=("≥ 11",))
    argv = ["--limit-parents", "1", "--per-parent", "3", "--seed", "42"]
    _run(tmp_path, *argv)
    first = len(_rejects(tmp_path))
    assert first
    stub_backend(reject=("≥ 11",))
    _run(tmp_path, *argv)
    assert len(_rejects(tmp_path)) == first


def test_build_bank_ingest_aliases(tmp_path, stub_backend):
    """Match build_bank's extract path rather than needing a flag: `statement`
    is in PROP_FIELDS and `id` is in ID_FIELDS, so the prop is found and the
    parent linkage survives into the bank row's source_id."""
    build_bank = _load_script("build_bank")
    stub_backend()
    _rc, rows = _run(tmp_path, "--limit-parents", "3", "--per-parent", "2")
    assert rows
    assert "statement" in build_bank.PROP_FIELDS and "id" in build_bank.ID_FIELDS
    for i, r in enumerate(rows):
        assert r["statement"] == r["prop"]
        extracted = build_bank.extract_prop(r)
        assert extracted == r["prop"]
        assert statement_key(extracted) == r["statement_key"]
        sid = build_bank.source_id(r, "json", i)
        assert r["parent_key"] in sid and "mutant:" in sid
    # ...and the same with the documented explicit flag
    assert build_bank.extract_prop(rows[0], "prop") == rows[0]["prop"]


def test_build_bank_streams_the_candidate_file(tmp_path, stub_backend):
    """The ingest command in the module docstring, executed for real (local file,
    no network) — `--dataset json --data-files <out> --split train`."""
    pytest.importorskip("datasets")
    build_bank = _load_script("build_bank")
    stub_backend()
    out = tmp_path / "mutants_candidates.jsonl"
    breed.main(["--backend", "fake", "--out", str(out), "--limit-parents", "2", "--per-parent", "2"])
    args = build_bank.parse_args(
        ["--dataset", "json", "--data-files", str(out), "--split", "train"]
    )
    streamed = list(build_bank.load_rows(args))
    emitted = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    assert len(streamed) == len(emitted) == 4
    for row, want in zip(streamed, emitted):
        assert statement_key(build_bank.extract_prop(row, args.prop_field)) == want["statement_key"]


def test_bank_file_is_read_only(tmp_path, stub_backend):
    stub_backend()
    before = BANK.read_bytes()
    _run(tmp_path, "--limit-parents", "2", "--per-parent", "2")
    assert BANK.read_bytes() == before


def test_refuses_to_write_into_a_measured_bank(tmp_path, stub_backend):
    stub_backend()
    with pytest.raises(SystemExit, match="refusing to write mutants"):
        breed.main(["--backend", "fake", "--out", str(BANK), "--limit-parents", "1"])


def test_parent_pool_filter_refuses_mixed_draws(tmp_path, stub_backend):
    stub_backend()
    for pool in ("train", "eval"):
        _rc, rows = _run(tmp_path / pool, "--parent-pool", pool, "--per-parent", "1")
        assert rows
        assert {r["parent_split"] for r in rows} == {pool}


def test_membership_is_inherited_unconditionally(tmp_path, stub_backend):
    """Inheritance replaced the old optional --coherent-split drop: every mutant
    carries its PARENT's pool, and no mutant is discarded for its own key's roll.
    The sample must contain at least one mutant whose own-key roll differs from
    its inherited pool — proof the inheritance actually did something."""
    stub_backend()
    _rc, rows = _run(tmp_path / "a", "--per-parent", "4", "--seed", "42")
    assert all(r["leaf_pool"] == r["parent_split"] for r in rows)
    assert any(leaf_split(r["statement_key"]) != r["leaf_pool"] for r in rows), \
        "no own-roll disagreement in sample; inheritance untested"


def test_resume_does_not_duplicate(tmp_path, stub_backend):
    stub_backend()
    out = tmp_path / "mutants_candidates.jsonl"
    argv = ["--backend", "fake", "--out", str(out), "--limit-parents", "3", "--per-parent", "2"]
    breed.main(argv)
    first = out.read_text()
    breed.main(argv)
    rows = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    assert out.read_text().startswith(first)
    assert len({r["statement_key"] for r in rows}) == len(rows)


def test_already_measured_keys_are_skipped(tmp_path, stub_backend):
    """A mutant whose key already sits in a measured bank is a re-measurement."""
    stub_backend()
    _rc, rows = _run(tmp_path / "a", "--limit-parents", "1", "--per-parent", "2", "--seed", "42")
    prior = tmp_path / "prior.jsonl"
    prior.write_text("".join(json.dumps({"statement_key": r["statement_key"], "prop": r["prop"],
                                         "status": Status.LEAF_FAILED}) + "\n" for r in rows))
    stub_backend()
    _rc, again = _run(tmp_path / "b", "--limit-parents", "1", "--per-parent", "2", "--seed", "42",
                      "--exclude-bank", str(prior))
    assert {r["statement_key"] for r in again}.isdisjoint({r["statement_key"] for r in rows})


def test_backend_is_closed(tmp_path, stub_backend):
    b = stub_backend()
    _run(tmp_path, "--limit-parents", "1", "--per-parent", "1")
    assert getattr(b, "closed", False)


# ---------------------------------------------------------------------------
# Live Lean (integration)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_battery_floor_finding_is_real():
    """Pins the 2026-08-12 measurement that motivates `--battery-filter`: the
    bank's [0.25, 0.9] band is the corridor's CEILING only, and some band rows
    sit below its floor. `999 + 10 = 1009` is a real DSV2 band row (pass@8 0.875)
    that bare `simp` closes."""
    from rlmath.lean import ReplConfig, ReplPool

    cfg = ReplConfig(n_workers=2)
    if not cfg.available():
        pytest.skip("no Lean toolchain (scripts/setup_lean.sh)")
    band = {r["prop"] for r in breed.band_parents(breed.read_rows(BANK))}
    trivial = "999 + 10 = 1009"
    assert trivial in band, "the bank no longer contains this row; re-derive the finding"
    pool = ReplPool(cfg)
    try:
        hits = breed.battery_closes([trivial, P_INEQ], pool, 20.0)
    finally:
        pool.close()
    assert hits[0] is not None, "a battery-trivial band row stopped being trivial"
    assert hits[1] is None, "P_INEQ was supposed to be above the corridor floor"


@pytest.mark.integration
def test_mutants_of_band_statements_elaborate():
    """The real gate: mutants of real band rows must mostly elaborate against
    Mathlib. Not a truth claim — elaboration only (measurement is build_bank's)."""
    from rlmath.lean import ReplConfig, ReplPool

    cfg = ReplConfig(n_workers=2)
    if not cfg.available():
        pytest.skip("no Lean toolchain (scripts/setup_lean.sh)")
    rows = breed.band_parents(breed.read_rows(BANK))
    assert rows, "no band rows to breed from"
    props = [m.prop for r in rows[:4] for m in mutants(r["prop"], seed=42, n=2)]
    pool = ReplPool(cfg)
    try:
        ok = breed.elaborates(props, pool, 120.0)
    finally:
        pool.close()
    assert sum(ok) >= max(1, int(0.7 * len(props))), f"{sum(ok)}/{len(props)} elaborated"
