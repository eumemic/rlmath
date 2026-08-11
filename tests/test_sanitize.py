"""Sanitizer tests (DIRECTION.md §5.6).

Structured as an attack list, not a coverage list: each test names the reward
hack it forecloses. The false-positive tests matter just as much — a sanitizer
that rejects valid proofs zeroes real signal, which is the ../rl format-compliance
failure mode wearing a different hat.
"""
import pytest

from rlmath.core.leancode import ALLOWED_AXIOMS, compose
from rlmath.core.types import DecompositionPlan, GoalSpec, LemmaSpec
from rlmath.sanitize import (
    BANNED_TOKENS,
    DECLARATION_KEYWORDS,
    audit_axiom_output,
    audit_axioms,
    axiom_report_present,
    enforce_single_theorem,
    parse_axiom_output,
    scan_source,
)

GOAL = GoalSpec(id="t1", prop="2 ∣ 4 + 6", name="goal_t1")
PLAN = DecompositionPlan(
    lemmas=[LemmaSpec("h1", "2 ∣ 4"), LemmaSpec("h2", "2 ∣ 6")],
    assembly="exact Dvd.dvd.add h1 h2",
)


# --------------------------------------------------------------------------
# scan_source — banned tokens
# --------------------------------------------------------------------------

def test_clean_source_is_clean():
    assert scan_source("theorem goal_t1 : 2 ∣ 4 + 6 := by\n  norm_num") == []
    assert scan_source("") == []


@pytest.mark.parametrize("tok", sorted(BANNED_TOKENS))
def test_every_banned_token_is_detected(tok):
    """Whatever is in the table must actually be enforced — no dead entries."""
    v = scan_source(f"theorem t : P := by\n  {tok} foo\n")
    assert len(v) >= 1
    assert any(repr(tok) in m for m in v)


@pytest.mark.parametrize(
    "code",
    [
        "exact sorry",
        "theorem t : P := sorry",
        "  sorry",
        "by\n  first\n  | simp\n  | sorry",
        "exact (sorry)",
        "refine ⟨sorry, sorry⟩",
    ],
)
def test_sorry_in_proof_position_flags(code):
    assert scan_source(code)


@pytest.mark.parametrize(
    "code",
    [
        "exact sorryFree",                      # identifier prefix
        "exact mysorry",                        # identifier suffix
        "exact sorry_free h",                   # underscore is an identifier char
        "exact h.sorryAx_elim",                 # embedded, both sides
        "have sorry' := h",                     # prime is an identifier char
        "exact decide",                         # `decide` is fine; `native_decide` is not
        "induction n with | zero => rfl",       # `induction` is not `inductive`
        "exact inferInstance",                  # not `instance`
        "simp [Nat.add_def]",                   # not `def`
        "exact infer_instance",                 # not `instance`
        "rw [isOpen_iff]",                      # not `open`
        "exact Classical.byContradiction h",    # `Classical` is fine
        "apply partialOrder.le_refl",           # not `partial`
        "exact macroscopic",                    # not `macro`
        "exact externalize h",                  # not `extern`
    ],
)
def test_identifier_embedded_occurrences_do_not_flag(code):
    assert scan_source(code) == [], code


def test_sorry_in_a_comment_flags_by_design():
    """Comments should have been stripped upstream; a surviving one is anomalous,
    and the scanner does not parse Lean. Strictness is the right default (§5.6)."""
    assert scan_source("theorem t : P := by\n  norm_num -- sorry, this is a hack\n")
    assert scan_source("/- sorry -/\ntheorem t : P := by norm_num")


def test_string_literal_occurrence_flags_by_design():
    # Documented v1 false positive: no Lean parsing in the trust boundary.
    assert scan_source('theorem t : P := by\n  trace "sorry"\n  norm_num')


def test_unicode_homoglyph_is_a_known_limitation():
    """Cyrillic `о` in `sоrry` evades the scan. Documented, not solved: NFKC
    folding Lean source would misfire on legitimate α/ℕ/₁ identifiers, and the
    homoglyph is not exploitable — Lean's lexer rejects it too, so the snippet
    never elaborates. Asserting current behavior so a future fix is a visible
    change, not an accident."""
    assert scan_source("exact sоrrry") == []
    assert scan_source("exact sоrry") == []


def test_native_decide_flags_but_decide_does_not():
    assert scan_source("exact by native_decide")
    assert scan_source("exact by decide") == []


def test_macro_rules_reported_once_not_twice():
    """`macro` must not double-report inside `macro_rules` — noisy detail fields
    train operators to skim them."""
    v = scan_source("macro_rules | `(tactic| trivial) => `(tactic| sorry)")
    toks = [m for m in v if "'macro_rules'" in m]
    assert len(toks) == 1
    assert not any("'macro'" in m and "macro_rules" not in m for m in v)


def test_set_option_flags():
    v = scan_source("set_option maxHeartbeats 4000000 in\ntheorem t : P := by decide")
    assert len(v) == 1 and "set_option" in v[0]
    assert "maxHeartbeats" in BANNED_TOKENS["set_option"]


def test_partial_flags_with_nontermination_justification():
    v = scan_source("partial def loop (n : ℕ) : ℕ := loop n")
    assert v and "partial" in v[0]
    assert "nontermination" in BANNED_TOKENS["partial"]


def test_kernel_bypass_family_flags():
    for code in [
        "@[implemented_by evilImpl] def f : ℕ := 0",
        '@[extern "c_impl"] opaque f : ℕ',
        "unsafe def f : ℕ := f",
        "initialize registerSomething",
        "opaque mystery : P",
        "axiom cheat : P",
        "elab \"cheat\" : tactic => do pure ()",
        "notation:max \"P\" => True",
        "#exit\ntheorem goal_t1 : False := by norm_num",
    ]:
        assert scan_source(code), code


def test_exit_command_flags():
    """`#exit` makes everything after it silently 'compile' — ok=True, sorries=0,
    zero proving. It is not a declaration keyword, so only scan_source stops it."""
    code = "#exit\ntheorem goal_t1 : 2 ∣ 4 + 6 := by\n  norm_num"
    assert enforce_single_theorem(code, "goal_t1") == []   # lexically well-formed...
    assert scan_source(code)                               # ...and still rejected


def test_violations_carry_line_numbers_and_are_position_ordered():
    code = "line one\nadmit\nline three\nsorry\n"
    v = scan_source(code)
    assert len(v) == 2
    assert v[0].startswith("line 2:") and "admit" in v[0]
    assert v[1].startswith("line 4:") and "sorry" in v[1]


def test_repeated_token_reported_once_at_first_occurrence():
    v = scan_source("sorry\nsorry\nsorry\n")
    assert len(v) == 1 and v[0].startswith("line 1:")


def test_violation_messages_include_the_justification():
    v = scan_source("exact sorry")
    assert BANNED_TOKENS["sorry"] in v[0]


def test_axiom_smuggled_mid_assembly():
    """The classic: a valid-looking plan whose assembly opens a new declaration."""
    assembly = "have hx : 2 ∣ 4 := by norm_num\naxiom cheat : 2 ∣ 6\nexact Dvd.dvd.add hx cheat"
    v = scan_source(assembly)
    assert len(v) == 1 and "'axiom'" in v[0]
    assert v[0].startswith("line 2:")


def test_composed_artifact_carrying_a_smuggled_sorry():
    code = compose(GOAL, PLAN, {"h1": "by norm_num", "h2": "by sorry"})
    assert scan_source(code)


def test_clean_composed_artifact_passes_both_gates():
    code = compose(GOAL, PLAN, {"h1": "by norm_num", "h2": "by norm_num"})
    assert scan_source(code) == []
    assert enforce_single_theorem(code, "goal_t1") == []


# --------------------------------------------------------------------------
# enforce_single_theorem
# --------------------------------------------------------------------------

def test_single_theorem_ok():
    assert enforce_single_theorem("theorem goal_t1 : P := by norm_num", "goal_t1") == []


def test_theorem_name_must_match():
    v = enforce_single_theorem("theorem other : P := by norm_num", "goal_t1")
    assert len(v) == 1 and "'other'" in v[0] and "'goal_t1'" in v[0]


def test_missing_theorem():
    v = enforce_single_theorem("example : P := by norm_num", "goal_t1")
    assert any("no theorem declaration" in m for m in v)
    assert any("'example'" in m for m in v)


def test_extra_def_in_artifact():
    """An auxiliary `def` can define the goal's own predicate to be trivially
    true; the artifact must be self-contained *and* single-declaration."""
    code = (
        "def cheat : Prop := True\n"
        "theorem goal_t1 : cheat := by\n"
        "  trivial\n"
    )
    v = enforce_single_theorem(code, "goal_t1")
    assert len(v) == 1
    assert v[0].startswith("line 1:") and "'def'" in v[0]


def test_two_theorems_rejected_even_if_one_has_the_right_name():
    code = "theorem goal_t1 : P := by norm_num\ntheorem helper : Q := by simp"
    v = enforce_single_theorem(code, "goal_t1")
    assert any("found 2" in m for m in v)
    assert any("'helper'" in m for m in v)


def test_lemma_keyword_is_not_an_acceptable_theorem():
    """`lemma` is a Mathlib macro for `theorem`; the artifact contract says
    `theorem <name>` (core.leancode.compose), so accepting `lemma` would mean
    accepting a declaration form the composer never emits."""
    v = enforce_single_theorem("lemma goal_t1 : P := by norm_num", "goal_t1")
    assert any("no theorem declaration" in m for m in v)
    assert any("'lemma'" in m for m in v)


@pytest.mark.parametrize(
    "smuggled",
    [
        "instance : Foo ℕ := ⟨0⟩",
        "structure S where\n  x : ℕ",
        "inductive I | a | b",
        "class C (α : Type) where\n  f : α",
        "abbrev A := ℕ",
        "axiom cheat : P",
        "opaque mystery : P",
        "namespace Hidden",
        "attribute [instance] foo",
        "import Mathlib.Tactic",
        "noncomputable def f := Classical.choice",
        "macro \"x\" : term => `(0)",
        "variable (n : ℕ)",
        "section",
        "universe u",
    ],
)
def test_declaration_keywords_rejected_in_artifact(smuggled):
    code = f"theorem goal_t1 : P := by\n  norm_num\n{smuggled}\n"
    v = enforce_single_theorem(code, "goal_t1")
    assert v, smuggled


@pytest.mark.parametrize(
    "proof",
    [
        "  induction n with\n  | zero => rfl\n  | succ k ih => simp [ih]",
        "  simp [Nat.add_def, Function.funext_iff]",
        "  exact inferInstance",
        "  refine ⟨?_, ?_⟩ <;> norm_num",
        "  rcases h with ⟨x, hx⟩\n  exact absurd hx (by simp)",
        "  have h' : 2 ∣ 4 := by norm_num\n  exact h'.trans (by simp)",
        "  classical\n  by_cases hc : p <;> simp [hc]",
    ],
)
def test_legitimate_tactic_text_is_not_a_declaration(proof):
    """False positives here silently zero valid proofs — the expensive direction."""
    code = f"theorem goal_t1 : P := by\n{proof}\n"
    assert enforce_single_theorem(code, "goal_t1") == [], proof
    assert scan_source(code) == [], proof


def test_indented_smuggled_declaration_is_caught():
    """`compose` indents the whole body, so a smuggled declaration arrives at
    column 2 — a column-0-only scan would miss it."""
    plan = DecompositionPlan(lemmas=[], assembly="norm_num\n\ndef cheat : Prop := True")
    code = compose(GOAL, plan, {})
    assert "  def cheat" in code
    assert enforce_single_theorem(code, "goal_t1")


def test_declaration_keyword_table_is_nonempty_and_includes_theorem():
    assert "theorem" in DECLARATION_KEYWORDS
    assert {"def", "axiom", "instance", "example"} <= DECLARATION_KEYWORDS


# --------------------------------------------------------------------------
# parse_axiom_output
# --------------------------------------------------------------------------

def test_parse_standard_output():
    text = "'goal_t1' depends on axioms: [propext, Classical.choice, Quot.sound]"
    assert parse_axiom_output(text) == {"propext", "Classical.choice", "Quot.sound"}


@pytest.mark.parametrize(
    "text,expected",
    [
        # verbatim from research/lean-repl.md §5 (confirmed against the Lean docs)
        ("'excluded_middle' depends on axioms: [propext, Classical.choice, Quot.sound]",
         {"propext", "Classical.choice", "Quot.sound"}),
        ("'simple_equality' depends on axioms: [propext]", {"propext"}),
        ("'addThree' does not depend on any axioms", set()),
        ("'lazy' depends on axioms: [sorryAx]", {"sorryAx"}),
    ],
)
def test_parse_documented_repl_formats(text, expected):
    assert parse_axiom_output(text) == expected
    assert axiom_report_present(text)


def test_parse_unquoted_name():
    text = "goal_t1 depends on axioms: [propext]"
    assert parse_axiom_output(text) == {"propext"}


def test_parse_no_axioms_case():
    for text in [
        "'goal_t1' does not depend on any axioms",
        "goal_t1 does not depend on any axioms\n",
    ]:
        assert parse_axiom_output(text) == set()
        assert axiom_report_present(text)


def test_parse_multiline_list():
    text = (
        "'goal_t1' depends on axioms: [propext,\n"
        " Classical.choice,\n"
        " Quot.sound,\n"
        " sorryAx]\n"
    )
    assert parse_axiom_output(text) == {"propext", "Classical.choice", "Quot.sound", "sorryAx"}


def test_parse_tolerates_repl_prefix_and_trailing_output():
    text = (
        "<stdin>:3:0: information:\n"
        "'goal_t1' depends on axioms: [propext, Classical.choice]\n"
        "some other message\n"
    )
    assert parse_axiom_output(text) == {"propext", "Classical.choice"}


def test_parse_unions_multiple_declarations():
    text = (
        "'a' depends on axioms: [propext]\n"
        "'b' does not depend on any axioms\n"
        "'c' depends on axioms: [Quot.sound, sorryAx]\n"
    )
    assert parse_axiom_output(text) == {"propext", "Quot.sound", "sorryAx"}


def test_parse_unbracketed_variant():
    text = "'goal_t1' depends on axioms: propext, Classical.choice\nnext line"
    assert parse_axiom_output(text) == {"propext", "Classical.choice"}


def test_parse_fully_qualified_and_root_prefixed_names():
    text = "'x' depends on axioms: [_root_.Classical.choice, Lean.ofReduceBool]"
    assert parse_axiom_output(text) == {"_root_.Classical.choice", "Lean.ofReduceBool"}


def test_parse_empty_list():
    assert parse_axiom_output("'x' depends on axioms: []") == set()


def test_parse_unterminated_list_still_reports_names():
    """Truncated REPL output must not silently become 'no axioms'."""
    assert parse_axiom_output("'x' depends on axioms: [propext, sorryAx") == {"propext", "sorryAx"}


def test_unrecognized_text_is_not_an_axiom_report():
    for text in ["", "unknown identifier 'goal_t1'", "error: unknown constant"]:
        assert parse_axiom_output(text) == set()
        assert not axiom_report_present(text)


# --------------------------------------------------------------------------
# audit_axioms
# --------------------------------------------------------------------------

def test_whitelisted_axioms_pass():
    assert audit_axioms({"propext", "Classical.choice", "Quot.sound"}) == []
    assert audit_axioms(set()) == []
    assert audit_axioms(set(ALLOWED_AXIOMS)) == []


def test_final_component_matching():
    assert audit_axioms({"_root_.Classical.choice", "choice", "Quot.sound"}) == []


def test_sorry_ax_rejected_with_diagnosis():
    v = audit_axioms({"sorryAx"})
    assert len(v) == 1 and "sorryAx" in v[0] and "sorry" in v[0]


@pytest.mark.parametrize(
    "ax", ["Lean.ofReduceBool", "Lean.ofReduceNat", "ofReduceBool", "Lean.trustCompiler"]
)
def test_native_decide_axioms_rejected(ax):
    v = audit_axioms({ax})
    assert len(v) == 1 and "native_decide" in v[0]


def test_whitelist_covers_the_non_transitive_collect_axioms_gap():
    """`#print axioms` reports `Lean.ofReduceBool` without the
    `Lean.trustCompiler` beneath it (research/lean-repl.md §5). A denylist would
    have to know about every such hole; the whitelist rejects the remainder."""
    assert audit_axioms({"propext", "Lean.SomeFutureAxiom"}) == [
        "disallowed axiom: Lean.SomeFutureAxiom"
    ]


def test_unknown_axiom_rejected():
    v = audit_axioms({"MyCheat.axiom1"})
    assert v == ["disallowed axiom: MyCheat.axiom1"]


def test_audit_reports_every_offender_sorted():
    v = audit_axioms({"sorryAx", "propext", "Lean.ofReduceBool", "Zzz"})
    assert len(v) == 3
    assert v == sorted(v)  # deterministic ordering for the detail field


def test_audit_axiom_output_end_to_end():
    ok = "'goal_t1' depends on axioms: [propext, Classical.choice, Quot.sound]"
    assert audit_axiom_output(ok) == []
    assert audit_axiom_output("'goal_t1' does not depend on any axioms") == []
    assert audit_axiom_output("'goal_t1' depends on axioms: [sorryAx]")


def test_audit_axiom_output_refuses_unrecognized_text():
    """The vacuous-pass hole: a failed `#print axioms` (unknown declaration after
    a namespace rename, REPL hiccup, `#exit`) must not read as 'no axioms'."""
    v = audit_axiom_output("error: unknown identifier 'goal_t1'")
    assert len(v) == 1 and "not recognized" in v[0]
    assert audit_axiom_output("")


def test_sanitizer_functions_are_pure():
    """No I/O, no mutation of inputs (§5.6: these run inside the GRPO loop on
    every rollout, and they must be safe to call from worker threads)."""
    code = "theorem goal_t1 : P := by sorry"
    axioms = {"sorryAx"}
    scan_source(code)
    enforce_single_theorem(code, "goal_t1")
    audit_axioms(axioms)
    assert code == "theorem goal_t1 : P := by sorry"
    assert axioms == {"sorryAx"}
