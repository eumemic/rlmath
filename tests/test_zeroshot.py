"""Phase-2 zero-shot runner + arms (src/rlmath/eval, scripts/run_zeroshot.py).

Offline by default: a stub root client, `tests/conftest.py::FakeBackend`, and a
scripted leaf. No network, no Lean toolchain, no model server — the runner keeps
every heavy import inside make_root / make_backend / make_leaf precisely so this
file can exist, and the arms take their client/backend/leaf by injection.

The live-Lean check at the bottom is `@pytest.mark.integration` (deselected by
the default addopts); it exists because the direct arm's verdict is the kernel's
and a FakeBackend can only prove that the right strings were sent.

The script is loaded by path — scripts/ is not a package (tests/test_scripts.py
does the same, following ../rl/eval/run_eval.py's scorer loading).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from rlmath.core.types import Budgets, GoalSpec, LeanMessage, Status, VerifyResult
from rlmath.eval import arms

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_script_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    # Registered before exec: `@dataclass` resolves annotations through
    # `sys.modules[cls.__module__]`, which is absent for a path-loaded module and
    # raises during class creation (not at first use).
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


zs = _load("run_zeroshot")


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

GOAL = GoalSpec(id="p1", prop="P", name="thm")
NAT_GOAL = GoalSpec(id="n1", prop="∀ n : ℕ, n + 0 = n", name="zs_add_zero")


def fenced(body: str, goal: GoalSpec = NAT_GOAL, lang: str = "lean4") -> str:
    return (
        "Here is the proof.\n\n"
        f"```{lang}\n"
        f"theorem {goal.name} : {goal.prop} := {body}\n"
        "```\n"
    )


class StubRoot:
    """`arms.RootClient` returning canned completions, in call order.

    A single string is reused for every call; a list is consumed one per call
    (and exhausting it is an error, not a silent repeat).
    """

    def __init__(self, texts, model: str = "stub-root", usage: arms.Usage | None = None,
                 raises: dict[int, BaseException] | None = None):
        self.texts = [texts] if isinstance(texts, str) else list(texts)
        self.cycle = isinstance(texts, str)
        self.model = model
        self.usage = usage or arms.Usage(prompt_tokens=1000, completion_tokens=1000, source="api")
        self.raises = raises or {}
        self.calls: list[list[dict]] = []

    def complete(self, messages):
        i = len(self.calls)
        self.calls.append(list(messages))
        if i in self.raises:
            raise self.raises[i]
        text = self.texts[0] if self.cycle else self.texts[i]
        return arms.RootCompletion(text=text, usage=self.usage, finish_reason="stop",
                                   elapsed_s=0.01)


@dataclass
class FakeLeafResult:
    proof: str | None
    attempts: int


@dataclass
class FakeLeaf:
    """Scripted leaf (harness/episode.LeafProver shape), as in tests/test_harness.py."""

    proofs: dict[str, str]

    def prove(self, prop: str, *, k: int, backend) -> FakeLeafResult:
        proof = self.proofs.get(prop)
        return FakeLeafResult(proof=proof, attempts=1 if proof else k)


def audit_result(axioms: str = "propext, Classical.choice") -> VerifyResult:
    return VerifyResult(ok=True, sorries=0,
                        messages=[LeanMessage("info", f"'x' depends on axioms: [{axioms}]")])


def wire_direct(fb, *, proof_ok: bool = True, audit: VerifyResult | None = None) -> None:
    """The two snippet classes the direct arm sends, in match order."""
    fb.rule(lambda c: "#print axioms" in c, audit or audit_result())
    fb.rule(
        lambda c: c.startswith("theorem _proof_check"),
        VerifyResult(ok=proof_ok, sorries=0,
                     messages=[] if proof_ok else [LeanMessage("error", "unsolved goals")]),
    )


def wire_decomp(fb, *, stmt_ok=True, plan_ok=True, audit: VerifyResult | None = None) -> None:
    fb.rule(lambda c: "#print axioms" in c, audit or audit_result())
    fb.rule(lambda c: c.startswith("theorem _plan"),
            VerifyResult(ok=plan_ok, sorries=0,
                         messages=[] if plan_ok else [LeanMessage("error", "unsolved goals")]))
    fb.rule(lambda c: c.startswith("theorem _stmt_check"),
            VerifyResult(ok=stmt_ok, sorries=1 if stmt_ok else 0,
                         messages=[] if stmt_ok else [LeanMessage("error", "unknown id")]))


PLAN_TEXT = "#lemma h1 : A\n#assembly\nexact f h1\n#end\n"


def budgets(**kw) -> Budgets:
    return Budgets(**{"max_lemmas": 8, "leaf_attempts_per_lemma": 4,
                      "max_total_leaf_attempts": 64, **kw})


# ---------------------------------------------------------------------------
# Direct arm — the kernel path
# ---------------------------------------------------------------------------

def test_direct_verified(fake_backend):
    wire_direct(fake_backend)
    root = StubRoot(fenced("by\n  simp"))
    out = arms.run_direct(NAT_GOAL, root=root, backend=fake_backend, budgets=budgets())

    assert out.status is Status.VERIFIED
    assert out.reward == 1.0
    assert out.arm == "direct"
    assert out.plan_stats is None          # no plan exists in this arm
    assert out.leaf_attempts_used == 1     # one completion is one attempt
    assert out.artifact is not None and NAT_GOAL.name in out.artifact
    # the FULL completion is kept (§5.7 P2 reads the emitted tokens)
    assert out.completion == root.texts[0]
    assert out.usage.source == "api"


def test_direct_kernel_rejection_is_not_a_format_error(fake_backend):
    """A proof that parses but does not check is prover failure, not format
    failure — the two must not share a bucket (DIRECTION §6)."""
    wire_direct(fake_backend, proof_ok=False)
    out = arms.run_direct(NAT_GOAL, root=StubRoot(fenced("by\n  simp")),
                          backend=fake_backend, budgets=budgets())
    assert out.status is Status.LEAF_FAILED
    assert out.reward == 0.0
    assert out.artifact is None


def test_direct_unparsable_completion_is_format_error(fake_backend):
    """../rl lost whole cells to silent format failure; here it is counted and
    costs no kernel call."""
    out = arms.run_direct(NAT_GOAL, root=StubRoot("I am sorry, I cannot help with that."),
                          backend=fake_backend, budgets=budgets())
    assert out.status is Status.FORMAT_ERROR
    assert out.reward == 0.0
    assert fake_backend.calls == []


def test_direct_echoed_skeleton_is_format_error(fake_backend):
    """`:= by sorry` echoed back is a non-attempt, not a sanitizer hit."""
    out = arms.run_direct(NAT_GOAL, root=StubRoot(fenced("by\n  sorry")),
                          backend=fake_backend, budgets=budgets())
    assert out.status is Status.FORMAT_ERROR
    assert fake_backend.calls == []


def test_direct_banned_token_is_sanitizer_rejected_before_the_kernel(fake_backend):
    """A `sorry` smuggled inside a real proof is a reward hack
    (SANITIZER_REJECTED), never prover weakness (LEAF_FAILED)."""
    out = arms.run_direct(
        NAT_GOAL,
        root=StubRoot(fenced("by\n  have h : True := sorry\n  simp")),
        backend=fake_backend,
        budgets=budgets(),
    )
    assert out.status is Status.SANITIZER_REJECTED
    assert "sorry" in out.detail
    assert fake_backend.calls == []


def test_direct_native_decide_is_sanitizer_rejected(fake_backend):
    out = arms.run_direct(NAT_GOAL, root=StubRoot(fenced("by\n  native_decide")),
                          backend=fake_backend, budgets=budgets())
    assert out.status is Status.SANITIZER_REJECTED
    assert fake_backend.calls == []


def test_direct_dirty_axiom_audit_is_rejected_even_though_the_kernel_passed(fake_backend):
    wire_direct(fake_backend, audit=audit_result("propext, myAxiom"))
    out = arms.run_direct(NAT_GOAL, root=StubRoot(fenced("by\n  simp")),
                          backend=fake_backend, budgets=budgets())
    assert out.status is Status.SANITIZER_REJECTED
    assert "myAxiom" in out.detail


def test_direct_unrecognized_audit_output_is_rejected(fake_backend):
    """Refusing to pass unaudited: the same rule sanitize.audit_axiom_output states."""
    wire_direct(fake_backend, audit=VerifyResult(ok=True, sorries=0, messages=[]))
    out = arms.run_direct(NAT_GOAL, root=StubRoot(fenced("by\n  simp")),
                          backend=fake_backend, budgets=budgets())
    assert out.status is Status.SANITIZER_REJECTED


def test_direct_sends_one_proof_check_and_one_audited_artifact(fake_backend):
    wire_direct(fake_backend)
    arms.run_direct(NAT_GOAL, root=StubRoot(fenced("by\n  simp")),
                    backend=fake_backend, budgets=budgets())
    checks = fake_backend.calls
    assert sum(c.startswith("theorem _proof_check") for c in checks) == 1
    audits = [c for c in checks if "#print axioms" in c]
    assert len(audits) == 1
    # the audit rides along with the artifact in ONE snippet (fresh environments)
    assert audits[0].startswith(f"theorem {NAT_GOAL.name}")
    assert audits[0].rstrip().endswith(f"#print axioms {NAT_GOAL.name}")


def test_direct_budget_is_pinned_to_one_attempt(fake_backend):
    """A k>1 episode config must not make the replay client re-serve the same
    completion as several attempts."""
    wire_direct(fake_backend, proof_ok=False)
    out = arms.run_direct(NAT_GOAL, root=StubRoot(fenced("by\n  simp")),
                          backend=fake_backend, budgets=budgets(leaf_attempts_per_lemma=8))
    assert out.leaf_attempts_used == 1
    assert sum(c.startswith("theorem _proof_check") for c in fake_backend.calls) == 1


def test_direct_prover_never_touches_the_leaf_attempt_cache():
    """The AttemptCache is the leaf oracle's record (bank pass rates, leaf_id
    provenance); root proofs must not enter it."""
    prover = arms._one_shot_prover("whatever", "root-model")
    assert prover.cache is None
    assert prover.model == "root-model"


# ---------------------------------------------------------------------------
# Direct prompt — the symmetry contract
# ---------------------------------------------------------------------------

def test_direct_prompt_states_the_task_the_scorer_and_nothing_strategic():
    msgs = arms.direct_prompt(NAT_GOAL)
    assert [m["role"] for m in msgs] == ["system", "user"]
    user = msgs[1]["content"]
    # facts about the task and the scorer: carried over from the harness prompt
    assert NAT_GOAL.prop in user
    assert NAT_GOAL.name in user and NAT_GOAL.id in user
    assert "lean4" in user and "Mathlib is imported" in user
    for banned in ("sorry", "native_decide", "set_option", "#exit"):
        assert banned in user
    assert "axiom audit" in user
    # strategy content: must NOT be there (see the comment block in arms.py)
    low = user.lower()
    for nudge in ("decompos", "step by step", "lemma", "sub-goal", "subgoal", "first prove"):
        assert nudge not in low


def test_direct_prompt_pins_the_declaration_the_scorer_will_check():
    """Measured 2026-08-12: handed a bare proposition, the root restates it with
    named binders and the extracted body then refers to binders that do not
    exist in `theorem _proof_check : <∀-prop> := <body>`. The skeleton is the
    format fix; losing it silently handicaps the flat arm."""
    user = arms.direct_prompt(NAT_GOAL)[1]["content"]
    assert f"theorem {NAT_GOAL.name} : {NAT_GOAL.prop} := by" in user
    assert "sorry` replaced by a real proof" in user
    assert "different binders" in user


def test_direct_prompt_is_a_pure_function_of_the_goal():
    a = arms.direct_prompt(NAT_GOAL)
    b = arms.direct_prompt(NAT_GOAL)
    assert a == b
    assert arms.direct_prompt(GOAL) != a


# ---------------------------------------------------------------------------
# Decomp arm — score_plan, unmodified
# ---------------------------------------------------------------------------

def test_decomp_verified_carries_plan_stats(fake_backend):
    wire_decomp(fake_backend)
    out = arms.run_decomp(GOAL, root=StubRoot(PLAN_TEXT), backend=fake_backend,
                          leaf=FakeLeaf({"A": "pa"}), budgets=budgets())
    assert out.status is Status.VERIFIED
    assert out.reward == 1.0
    assert out.plan_stats is not None
    assert out.plan_stats["n_lemmas"] == 1
    assert out.plan_stats["is_direct"] is False
    assert out.leaf_attempts_used == 1
    assert out.artifact and "have h1 : A := pa" in out.artifact


def test_decomp_plan_invalid_keeps_its_own_status(fake_backend):
    wire_decomp(fake_backend, plan_ok=False)
    out = arms.run_decomp(GOAL, root=StubRoot(PLAN_TEXT), backend=fake_backend,
                          leaf=FakeLeaf({"A": "pa"}), budgets=budgets())
    assert out.status is Status.PLAN_INVALID
    assert out.reward == 0.0
    assert out.plan_stats is not None          # a plan existed; only the assembly failed


def test_decomp_leaf_failure_is_attributed_to_the_leaf(fake_backend):
    wire_decomp(fake_backend)
    out = arms.run_decomp(GOAL, root=StubRoot(PLAN_TEXT), backend=fake_backend,
                          leaf=FakeLeaf({}), budgets=budgets())
    assert out.status is Status.LEAF_FAILED


def test_decomp_format_error_has_no_plan_stats(fake_backend):
    out = arms.run_decomp(GOAL, root=StubRoot("no plan here"), backend=fake_backend,
                          leaf=FakeLeaf({}), budgets=budgets())
    assert out.status is Status.FORMAT_ERROR
    assert out.plan_stats is None
    assert fake_backend.calls == []


def test_decomp_uses_the_environment_prompt(fake_backend):
    """Zero-shot cells and Phase-3 rollouts must share one prompt, or the
    numbers are not comparable."""
    from rlmath.envs.decomp_env import build_prompt

    wire_decomp(fake_backend)
    root = StubRoot(PLAN_TEXT)
    arms.run_decomp(GOAL, root=root, backend=fake_backend, leaf=FakeLeaf({"A": "pa"}),
                    budgets=budgets())
    assert root.calls[0] == build_prompt(GOAL)


def test_decomp_without_a_leaf_is_a_configuration_error(fake_backend):
    with pytest.raises(ValueError, match="leaf"):
        arms.run_decomp(GOAL, root=StubRoot(PLAN_TEXT), backend=fake_backend, leaf=None,
                        budgets=budgets())


def test_run_arm_dispatch_and_unknown_arm(fake_backend):
    wire_direct(fake_backend)
    out = arms.run_arm("direct", NAT_GOAL, root=StubRoot(fenced("by\n  simp")),
                       backend=fake_backend, budgets=budgets())
    assert out.arm == "direct"
    with pytest.raises(KeyError):
        arms.run_arm("nope", NAT_GOAL, root=StubRoot(""), backend=fake_backend,
                     budgets=budgets())


def test_arms_registry_declares_which_arms_need_a_leaf():
    assert set(arms.ARMS) == {"direct", "decomp"}
    assert arms.ARMS_NEEDING_LEAF == {"decomp"}


# ---------------------------------------------------------------------------
# Usage accounting
# ---------------------------------------------------------------------------

class _Usage:
    def __init__(self, p=None, c=None):
        if p is not None:
            self.prompt_tokens = p
        if c is not None:
            self.completion_tokens = c


class _Resp:
    def __init__(self, usage=None):
        self.usage = usage


def test_usage_from_api_is_taken_verbatim():
    u = arms.usage_from_response(_Resp(_Usage(11, 7)), prompt_chars=999, completion_chars=999)
    assert (u.prompt_tokens, u.completion_tokens, u.source) == (11, 7, "api")
    assert u.estimated is False
    assert u.total_tokens == 18


def test_usage_absent_falls_back_to_chars_over_3_5_and_says_so():
    u = arms.usage_from_response(_Resp(None), prompt_chars=350, completion_chars=70)
    assert (u.prompt_tokens, u.completion_tokens) == (100, 20)
    assert u.source == "chars/3.5"
    assert u.estimated is True
    assert u.as_row()["source"] == "chars/3.5"


def test_usage_partially_reported_is_labelled_mixed():
    u = arms.usage_from_response(_Resp(_Usage(p=11)), prompt_chars=1, completion_chars=350)
    assert (u.prompt_tokens, u.completion_tokens, u.source) == (11, 100, "api+chars/3.5")


def test_estimated_usage_reaches_the_row(fake_backend):
    wire_direct(fake_backend)
    root = StubRoot(fenced("by\n  simp"),
                    usage=arms.Usage(prompt_tokens=10, completion_tokens=5, source="chars/3.5"))
    out = arms.run_direct(NAT_GOAL, root=root, backend=fake_backend, budgets=budgets())
    assert out.usage.as_row() == {"prompt_tokens": 10, "completion_tokens": 5,
                                  "total_tokens": 15, "source": "chars/3.5"}


# ---------------------------------------------------------------------------
# Root client: headers, base url, usage — over a mock transport
# ---------------------------------------------------------------------------

def _mock_openai(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _chat_response(content: str = "hi", usage: dict | None = None) -> httpx.Response:
    body = {
        "id": "c1", "object": "chat.completion", "created": 0, "model": "m",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                     "finish_reason": "stop"}],
    }
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


def test_extra_headers_reach_the_wire():
    """Prime Inference bills the team through X-Prime-Team-ID: assert it on the
    actual request, not on the constructor argument."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return _chat_response(usage={"prompt_tokens": 11, "completion_tokens": 7,
                                     "total_tokens": 18})

    client = arms.make_root_client(
        "some/root-model",
        base_url="http://root.test/v1",
        api_key="sk-test",
        extra_headers={"X-Prime-Team-ID": "team_x", "X-Other": "1"},
        temperature=0.3,
        max_tokens=64,
        http_client=_mock_openai(handler),
    )
    out = client.complete([{"role": "user", "content": "hello"}])

    assert seen["headers"]["x-prime-team-id"] == "team_x"
    assert seen["headers"]["x-other"] == "1"
    assert seen["headers"]["authorization"] == "Bearer sk-test"
    assert seen["url"] == "http://root.test/v1/chat/completions"
    assert seen["body"]["model"] == "some/root-model"
    assert seen["body"]["temperature"] == 0.3
    assert seen["body"]["max_tokens"] == 64
    assert out.text == "hi"
    assert out.finish_reason == "stop"
    assert (out.usage.prompt_tokens, out.usage.completion_tokens, out.usage.source) == (
        11, 7, "api")


def test_root_client_estimates_usage_when_the_api_omits_it():
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response("x" * 35, usage=None)

    client = arms.make_root_client("m", base_url="http://root.test/v1", api_key="k",
                                   http_client=_mock_openai(handler))
    out = client.complete([{"role": "user", "content": "y" * 70}])
    assert out.usage.source == "chars/3.5"
    assert out.usage.completion_tokens == 10
    assert out.usage.prompt_tokens == 20


def test_root_client_reads_base_url_and_key_from_the_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://from-env.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    client = arms.make_root_client("m")
    assert str(client.oai.base_url).rstrip("/") == "http://from-env.test/v1"
    assert client.oai.api_key == "sk-env"


def test_parse_extra_headers():
    assert arms.parse_extra_headers(["A=1", "B=x=y"]) == {"A": "1", "B": "x=y"}
    assert arms.parse_extra_headers(None) == {}
    with pytest.raises(ValueError, match="KEY=VALUE"):
        arms.parse_extra_headers(["oops"])
    with pytest.raises(ValueError):
        arms.parse_extra_headers(["=v"])


def test_status_for_exception_separates_feasibility_from_infrastructure():
    window = RuntimeError("This model's maximum context length is 4096 tokens, however you...")
    assert arms.status_for_exception(window) is Status.CONTEXT_WINDOW_EXCEEDED
    assert arms.status_for_exception(RuntimeError("prompt is too long: 300000 tokens")) is (
        Status.CONTEXT_WINDOW_EXCEEDED)
    assert arms.status_for_exception(RuntimeError("connection reset")) is Status.ERROR


def test_model_slug_is_filesystem_safe():
    assert arms.model_slug("qwen/qwen3-30b-a3b-instruct-2507") == "qwen-qwen3-30b-a3b-instruct-2507"
    assert arms.model_slug("claude-haiku-4.5") == "claude-haiku-4-5"
    assert "/" not in arms.model_slug("a/b/c")


# ---------------------------------------------------------------------------
# Runner: problem-source autodetect
# ---------------------------------------------------------------------------

FAMILY_ROW = {
    "id": "bridge_chain-k2-s42-0",
    "family": "bridge_chain",
    "k": 2,
    "seed": 42,
    "goal": {"id": "bridge_chain-k2-s42-0", "prop": "∀ x : ℝ, 0 ≤ x ^ 2", "name": "bridge_k2"},
    "oracle_plan": {"lemmas": [], "assembly": "positivity"},
    "witnesses": {},
    "meta": {"leaf_pool": "eval"},
    "validation": {"ok": True},
}

BANK_ROW = {
    "statement_key": "2142ecb6fe060fdd",
    "prop": "∀ (a : ℝ), 0 ≤ a ^ 2",
    "source_id": "internlm/Lean-Workbook#0",
    "elaborates": True,
    "pass_rate": 0.5,
    "status": "leaf_failed",
}


def _write(tmp_path: Path, rows, name="probs.jsonl") -> Path:
    p = tmp_path / name
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return p


def test_row_shape_autodetect():
    assert zs.row_shape(FAMILY_ROW) == "family"
    assert zs.row_shape(BANK_ROW) == "goals"
    assert zs.row_shape({"id": "x", "prop": "P", "name": "thm"}) == "goals"
    with pytest.raises(ValueError, match="unrecognized problem row"):
        zs.row_shape({"id": "x", "text": "P"})
    with pytest.raises(ValueError):
        zs.row_shape({"goal": {"name": "thm"}})     # nested goal, no prop


def test_family_row_becomes_a_problem():
    p = zs.problem_from_row(FAMILY_ROW, 0)
    assert p.id == "bridge_chain-k2-s42-0"
    assert p.k == 2 and p.family == "bridge_chain"
    assert p.goal.prop == FAMILY_ROW["goal"]["prop"]
    assert p.goal.name == "bridge_k2"
    assert p.leaf_pool == "eval"


def test_bank_row_becomes_a_problem_with_a_computed_leaf_pool():
    from rlmath.families.leaf_split import leaf_split

    p = zs.problem_from_row(BANK_ROW, 3)
    assert p.goal.prop == BANK_ROW["prop"]
    assert p.k is None
    assert p.id == "internlm/Lean-Workbook#0"
    # a Lean-legal declaration name, derived from the key so it is stable
    assert p.goal.name == "zs_2142ecb6fe060fdd"
    # membership is the pure function of the key, never a stored manifest
    assert p.leaf_pool == leaf_split(BANK_ROW["statement_key"]) == "eval"
    train = zs.problem_from_row({**BANK_ROW, "statement_key": "0000000000000001"}, 4)
    assert train.leaf_pool == "train"


def test_bank_row_without_a_recorded_key_hashes_its_own_statement():
    from rlmath.core.types import statement_key
    from rlmath.families.leaf_split import leaf_split

    row = {"prop": "∀ (a : ℝ), 0 ≤ a ^ 2"}
    p = zs.problem_from_row(row, 0)
    key = statement_key(row["prop"])
    assert p.id == key and p.goal.name == f"zs_{key}"
    assert p.leaf_pool == leaf_split(key)


def test_load_problems_skips_and_counts_non_elaborating_rows(tmp_path):
    rows = [BANK_ROW, {**BANK_ROW, "statement_key": "aaaa", "prop": "junk",
                       "source_id": "internlm/Lean-Workbook#1", "elaborates": False}]
    problems, skipped = zs.load_problems(_write(tmp_path, rows))
    assert len(problems) == 1
    assert skipped["not_elaborating"] == 1
    keep_all, _ = zs.load_problems(_write(tmp_path, rows, "b.jsonl"), require_elaborates=False)
    assert len(keep_all) == 2


def test_load_problems_refuses_duplicate_ids(tmp_path):
    with pytest.raises(SystemExit, match="duplicate"):
        zs.load_problems(_write(tmp_path, [FAMILY_ROW, FAMILY_ROW]))


def test_load_problems_survives_a_torn_last_line(tmp_path):
    p = tmp_path / "torn.jsonl"
    p.write_text(json.dumps(FAMILY_ROW) + "\n{" + '"id": "half')
    problems, _ = zs.load_problems(p)
    assert len(problems) == 1


def test_cell_naming():
    assert zs.derive_set_name(Path("data/families/bridge_chain/k2.jsonl")) == "bridge_chain"
    assert zs.derive_set_name(Path("data/bank/band_goals.jsonl")) == "band_goals"
    assert zs.derive_k([zs.problem_from_row(FAMILY_ROW, 0)]) == "2"
    assert zs.derive_k([zs.problem_from_row(BANK_ROW, 0)]) == "na"
    assert zs.derive_k([zs.problem_from_row(FAMILY_ROW, 0),
                        zs.problem_from_row({**FAMILY_ROW, "id": "b", "k": 4}, 1)]) == "mix"
    assert zs.cell_path(Path("/r"), "bridge_chain", "2", "direct",
                        "qwen/qwen3-30b").name == "bridge_chain_k2_direct_qwen-qwen3-30b.jsonl"


# ---------------------------------------------------------------------------
# Runner: resume + budget guard
# ---------------------------------------------------------------------------

def test_existing_ids_includes_error_rows(tmp_path):
    p = _write(tmp_path, [{"id": "a", "status": "verified"}, {"id": "b", "status": "error"}])
    assert zs.existing_ids(p) == {"a", "b"}


def test_repair_drops_only_error_rows(tmp_path):
    """`format_error`, `leaf_failed` and `context_window_exceeded` are
    measurements (the last is feasibility evidence); only infra errors go."""
    p = _write(tmp_path, [
        {"id": "a", "status": "verified"},
        {"id": "b", "status": "error"},
        {"id": "c", "status": "leaf_failed"},
        {"id": "d", "status": "context_window_exceeded"},
        {"id": "e", "status": "format_error"},
    ])
    assert zs.drop_error_rows(p) == 1
    assert [r["id"] for r in _rows(p)] == ["a", "c", "d", "e"]
    assert zs.drop_error_rows(p) == 0        # idempotent


def test_main_repair_reruns_exactly_the_error_rows(tmp_path, fake_backend, monkeypatch):
    wire_direct(fake_backend)
    probs = _write(tmp_path, _problem_rows(3))
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    out = out_dir / "probs_k2_direct_stub-root.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in [
        {"id": "prob-0", "status": "verified", "reward": 1.0},
        {"id": "prob-1", "status": "error", "reward": 0.0},
        {"id": "prob-2", "status": "leaf_failed", "reward": 0.0},
    ]))
    root = _direct_root()
    _install_stubs(monkeypatch, fake_backend, root)

    assert zs.main(_direct_argv(probs, out_dir, "--repair")) == 0
    rows = _rows(out)
    assert [r["id"] for r in rows] == ["prob-0", "prob-2", "prob-1"]  # repaired row re-appended
    assert len(root.calls) == 1
    assert rows[-1]["status"] == "verified"


def test_dry_run_does_not_repair(tmp_path, fake_backend, monkeypatch):
    probs = _write(tmp_path, _problem_rows(1))
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    out = out_dir / "probs_k2_direct_stub-root.jsonl"
    out.write_text(json.dumps({"id": "prob-0", "status": "error"}) + "\n")
    monkeypatch.setattr(zs, "make_root", lambda args: pytest.fail("dry-run built a client"))
    assert zs.main(_direct_argv(probs, out_dir, "--repair", "--dry-run")) == 0
    assert _rows(out) == [{"id": "prob-0", "status": "error"}]


def test_budget_guard_charges_api_usage_verbatim_and_inflates_estimates():
    g = zs.BudgetGuard(max_usd=1.0, price_in=1.0, price_out=2.0)
    api = arms.Usage(prompt_tokens=1_000_000, completion_tokens=1_000_000, source="api")
    est = arms.Usage(prompt_tokens=1_000_000, completion_tokens=1_000_000, source="chars/3.5")
    assert g.cost_of(api) == pytest.approx(3.0)
    assert g.cost_of(est) == pytest.approx(3.0 * zs.ESTIMATE_SAFETY_FACTOR)


def test_budget_guard_stops_before_the_row_that_would_overshoot():
    g = zs.BudgetGuard(max_usd=0.35, price_in=100.0, price_out=100.0)
    assert g.should_stop() is None            # nothing spent, no observed row cost yet
    g.charge(0.2)
    assert "would exceed" in (g.should_stop() or "")
    g2 = zs.BudgetGuard(max_usd=1.0, price_in=1.0, price_out=1.0)
    g2.charge(1.0)
    assert "reached" in (g2.should_stop() or "")
    assert zs.BudgetGuard(max_usd=None).should_stop() is None


# ---------------------------------------------------------------------------
# Runner: main() end to end against stubs
# ---------------------------------------------------------------------------

def _problem_rows(n: int) -> list[dict]:
    return [
        {**FAMILY_ROW, "id": f"prob-{i}",
         "goal": {"id": f"prob-{i}", "prop": "∀ x : ℝ, 0 ≤ x ^ 2", "name": f"thm_{i}"}}
        for i in range(n)
    ]


def _install_stubs(monkeypatch, fake_backend, root, leaf=None):
    monkeypatch.setattr(zs, "make_root", lambda args: root)
    monkeypatch.setattr(zs, "make_backend", lambda args: fake_backend)
    monkeypatch.setattr(zs, "make_leaf", lambda args: leaf)


def _direct_argv(problems: Path, out_dir: Path, *extra: str) -> list[str]:
    return ["--problems", str(problems), "--arm", "direct", "--root-model", "stub/root",
            "--out-dir", str(out_dir), *extra]


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _direct_root(n: int = 8) -> StubRoot:
    return StubRoot([fenced("by\n  positivity", GoalSpec(id=f"prob-{i}", prop="∀ x : ℝ, 0 ≤ x ^ 2",
                                                         name=f"thm_{i}"))
                     for i in range(n)])


def test_main_writes_one_row_per_problem(tmp_path, fake_backend, monkeypatch, capsys):
    wire_direct(fake_backend)
    probs = _write(tmp_path, _problem_rows(3))
    _install_stubs(monkeypatch, fake_backend, _direct_root())

    assert zs.main(_direct_argv(probs, tmp_path / "out")) == 0
    out = tmp_path / "out" / "probs_k2_direct_stub-root.jsonl"
    rows = _rows(out)
    assert [r["id"] for r in rows] == ["prob-0", "prob-1", "prob-2"]
    r = rows[0]
    assert r["status"] == "verified" and r["reward"] == 1.0
    assert r["arm"] == "direct" and r["root_model"] == "stub/root"
    assert r["problem_set"] == "probs" and r["k"] == 2 and r["k_cell"] == "2"
    assert r["family"] == "bridge_chain" and r["leaf_pool"] == "eval"
    assert r["usage"]["source"] == "api" and r["usage"]["total_tokens"] == 2000
    assert r["cost_basis"] == "api" and r["cost_usd"] == 0.0   # no price table given
    assert r["completion"].startswith("Here is the proof.")
    assert r["plan_stats"] is None
    assert r["leaf_model"] is None
    assert "elapsed_s" in r and "ts" in r
    assert "mean reward over 3 scored rows" in capsys.readouterr().err


def test_main_resumes_and_skips_ids_including_error_rows(tmp_path, fake_backend, monkeypatch):
    wire_direct(fake_backend)
    probs = _write(tmp_path, _problem_rows(3))
    out_dir = tmp_path / "out"
    out = out_dir / "probs_k2_direct_stub-root.jsonl"
    out_dir.mkdir()
    out.write_text(json.dumps({"id": "prob-0", "status": "verified"}) + "\n"
                   + json.dumps({"id": "prob-1", "status": "error"}) + "\n")

    root = _direct_root()
    _install_stubs(monkeypatch, fake_backend, root)
    assert zs.main(_direct_argv(probs, out_dir)) == 0

    rows = _rows(out)
    assert [r["id"] for r in rows] == ["prob-0", "prob-1", "prob-2"]
    assert len(root.calls) == 1      # only the unseen problem was run


def test_main_stops_cleanly_on_the_budget_cap(tmp_path, fake_backend, monkeypatch, capsys):
    """Row 1 costs $0.20; the cap is $0.35, so row 2 must not start — and the
    stop happens BETWEEN rows, leaving no partial row behind."""
    wire_direct(fake_backend)
    probs = _write(tmp_path, _problem_rows(3))
    root = _direct_root()
    _install_stubs(monkeypatch, fake_backend, root)

    argv = _direct_argv(probs, tmp_path / "out", "--max-usd", "0.35",
                        "--price-in", "100", "--price-out", "100")
    assert zs.main(argv) == 0

    rows = _rows(tmp_path / "out" / "probs_k2_direct_stub-root.jsonl")
    assert [r["id"] for r in rows] == ["prob-0"]
    assert rows[0]["cost_usd"] == pytest.approx(0.2)
    assert len(root.calls) == 1
    err = capsys.readouterr().err
    assert "budget stop before" in err
    assert "estimated spend: $0.2000 of $0.3500" in err


def test_main_records_an_error_row_and_keeps_going(tmp_path, fake_backend, monkeypatch):
    wire_direct(fake_backend)
    probs = _write(tmp_path, _problem_rows(3))
    root = _direct_root()
    root.raises = {1: RuntimeError("connection reset by peer")}
    _install_stubs(monkeypatch, fake_backend, root)

    assert zs.main(_direct_argv(probs, tmp_path / "out")) == 0
    rows = _rows(tmp_path / "out" / "probs_k2_direct_stub-root.jsonl")
    assert [r["status"] for r in rows] == ["verified", "error", "verified"]
    assert "connection reset" in rows[1]["detail"]
    # the failed call reported no usage, so the guard charges nothing for it
    assert rows[1]["cost_usd"] == 0.0 and rows[1]["cost_basis"] == "none"


def test_main_records_over_window_as_feasibility_evidence(tmp_path, fake_backend, monkeypatch,
                                                          capsys):
    wire_direct(fake_backend)
    probs = _write(tmp_path, _problem_rows(1))
    root = _direct_root()
    root.raises = {0: RuntimeError("This model's maximum context length is 4096 tokens")}
    _install_stubs(monkeypatch, fake_backend, root)

    assert zs.main(_direct_argv(probs, tmp_path / "out")) == 0
    rows = _rows(tmp_path / "out" / "probs_k2_direct_stub-root.jsonl")
    assert rows[0]["status"] == "context_window_exceeded"
    # excluded from the mean, exactly as ../rl did (DIRECTION §6)
    assert "mean reward over 0 scored rows" in capsys.readouterr().err


def test_main_decomp_cell_runs_the_episode(tmp_path, fake_backend, monkeypatch):
    wire_decomp(fake_backend)
    rows_in = [{**FAMILY_ROW, "id": "prob-0",
                "goal": {"id": "prob-0", "prop": "P", "name": "thm"}}]
    probs = _write(tmp_path, rows_in)
    _install_stubs(monkeypatch, fake_backend, StubRoot(PLAN_TEXT), leaf=FakeLeaf({"A": "pa"}))

    argv = ["--problems", str(probs), "--arm", "decomp", "--root-model", "stub/root",
            "--leaf-model", "stub/leaf", "--out-dir", str(tmp_path / "out")]
    assert zs.main(argv) == 0
    rows = _rows(tmp_path / "out" / "probs_k2_decomp_stub-root.jsonl")
    assert rows[0]["status"] == "verified"
    assert rows[0]["plan_stats"]["n_lemmas"] == 1
    assert rows[0]["leaf_model"] == "stub/leaf"
    assert rows[0]["leaf_attempts_used"] == 1


def test_main_leaf_pool_filter_and_selection(tmp_path, fake_backend, monkeypatch):
    wire_direct(fake_backend)
    rows_in = _problem_rows(3)
    rows_in[1]["meta"] = {"leaf_pool": "train"}
    probs = _write(tmp_path, rows_in)
    root = _direct_root()
    _install_stubs(monkeypatch, fake_backend, root)

    assert zs.main(_direct_argv(probs, tmp_path / "out", "--leaf-pool", "eval")) == 0
    rows = _rows(tmp_path / "out" / "probs_k2_direct_stub-root.jsonl")
    assert [r["id"] for r in rows] == ["prob-0", "prob-2"]


def test_main_offset_and_n(tmp_path, fake_backend, monkeypatch):
    wire_direct(fake_backend)
    probs = _write(tmp_path, _problem_rows(4))
    _install_stubs(monkeypatch, fake_backend, _direct_root())
    assert zs.main(_direct_argv(probs, tmp_path / "out", "--offset", "1", "--n", "2")) == 0
    rows = _rows(tmp_path / "out" / "probs_k2_direct_stub-root.jsonl")
    assert [r["id"] for r in rows] == ["prob-1", "prob-2"]


def test_dry_run_touches_nothing(tmp_path, fake_backend, monkeypatch, capsys):
    probs = _write(tmp_path, _problem_rows(2))

    def boom(args):
        raise AssertionError("dry-run must not construct clients")

    monkeypatch.setattr(zs, "make_root", boom)
    monkeypatch.setattr(zs, "make_backend", boom)
    assert zs.main(_direct_argv(probs, tmp_path / "out", "--dry-run")) == 0
    assert not (tmp_path / "out" / "probs_k2_direct_stub-root.jsonl").exists()
    assert "dry-run" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Runner: argument validation
# ---------------------------------------------------------------------------

def _args(*extra: str):
    return zs.parse_args(["--problems", "p.jsonl", "--arm", "direct",
                          "--root-model", "m", *extra])


def test_budget_cap_without_a_price_table_is_refused():
    with pytest.raises(SystemExit):
        _args("--max-usd", "1.0")
    a = _args("--max-usd", "1.0", "--price-in", "0.2")
    assert a.max_usd == 1.0 and a.price_in == 0.2


def test_decomp_requires_a_leaf_model():
    with pytest.raises(SystemExit):
        zs.parse_args(["--problems", "p.jsonl", "--arm", "decomp", "--root-model", "m"])
    a = zs.parse_args(["--problems", "p.jsonl", "--arm", "decomp", "--root-model", "m",
                       "--leaf-model", "L"])
    assert a.leaf_model == "L"


def test_budgets_come_from_the_cli_hard_caps():
    a = _args("--max-lemmas", "32", "--leaf-attempts-per-lemma", "2",
              "--max-total-leaf-attempts", "16", "--verify-timeout-s", "60")
    b = zs.budgets_from_args(a)
    assert (b.max_lemmas, b.leaf_attempts_per_lemma, b.max_total_leaf_attempts,
            b.verify_timeout_s) == (32, 2, 16, 60.0)


def test_extra_header_is_repeatable():
    a = _args("--extra-header", "X-Prime-Team-ID=t", "--extra-header", "X-B=2")
    assert arms.parse_extra_headers(a.extra_header) == {"X-Prime-Team-ID": "t", "X-B": "2"}


def test_arm_choices_come_from_the_registry():
    with pytest.raises(SystemExit):
        zs.parse_args(["--problems", "p.jsonl", "--arm", "flat_best_of_n", "--root-model", "m"])


# ---------------------------------------------------------------------------
# Few-shot exemplars (DIRECTION §5.5 rung 1.5) — insertion, marker, provenance
#
# What the exemplar *is* lives in tests/test_exemplars.py; this section is about
# the two things the runner and the arms own: where the block goes in the prompt,
# and that a few-shot cell can never be confused with its zero-shot twin.
# ---------------------------------------------------------------------------

EXEMPLAR = "Worked example.\n\n#lemma h1 : A\n#assembly\nexact f h1\n#end"


def test_with_exemplar_is_a_no_op_when_there_is_none():
    """The zero-shot path must be byte-identical to what it was before few-shot
    existed, or every cell already run becomes incomparable."""
    msgs = arms.direct_prompt(NAT_GOAL)
    assert arms.with_exemplar(msgs, None) == msgs
    assert arms.with_exemplar(msgs, "   ") == msgs


def test_with_exemplar_prepends_a_delimited_block_to_the_last_user_turn():
    msgs = arms.with_exemplar(arms.direct_prompt(NAT_GOAL), EXEMPLAR)
    assert [m["role"] for m in msgs] == ["system", "user"]      # same shape, one user turn
    user = msgs[1]["content"]
    assert user.startswith(arms.EXEMPLAR_OPEN)
    assert arms.EXEMPLAR_CLOSE in user
    assert EXEMPLAR in user
    # the zero-shot user turn survives verbatim, after the block
    assert user.endswith(arms.direct_prompt(NAT_GOAL)[1]["content"])
    # and the caller's messages are not mutated in place
    assert arms.EXEMPLAR_OPEN not in arms.direct_prompt(NAT_GOAL)[1]["content"]


def test_with_exemplar_never_touches_the_frozen_system_prompts():
    """`envs.decomp_env.SYSTEM_PROMPT` is the contract shared with the Phase-3
    trainer; DIRECT_SYSTEM is its flat-arm counterpart. Few-shot rides on the
    user turn precisely so neither moves."""
    from rlmath.envs.decomp_env import SYSTEM_PROMPT, build_prompt

    decomp = arms.with_exemplar(build_prompt(GOAL), EXEMPLAR)
    direct = arms.with_exemplar(arms.direct_prompt(NAT_GOAL), EXEMPLAR)
    assert decomp[0]["content"] == SYSTEM_PROMPT
    assert direct[0]["content"] == arms.DIRECT_SYSTEM


def test_with_exemplar_refuses_a_prompt_with_no_user_turn():
    with pytest.raises(ValueError, match="no user message"):
        arms.with_exemplar([{"role": "system", "content": "s"}], EXEMPLAR)


def test_both_arms_send_the_exemplar_and_run_unchanged_otherwise(fake_backend):
    wire_direct(fake_backend)
    root = StubRoot(fenced("by\n  simp"))
    out = arms.run_direct(NAT_GOAL, root=root, backend=fake_backend, budgets=budgets(),
                          exemplar=EXEMPLAR)
    assert out.status is Status.VERIFIED
    assert EXEMPLAR in root.calls[0][1]["content"]
    assert out.prompt_chars > sum(len(m["content"]) for m in arms.direct_prompt(NAT_GOAL))

    fb2 = fake_backend.__class__()
    wire_decomp(fb2)
    droot = StubRoot(PLAN_TEXT)
    dout = arms.run_decomp(GOAL, root=droot, backend=fb2, leaf=FakeLeaf({"A": "pa"}),
                           budgets=budgets(), exemplar=EXEMPLAR)
    assert dout.status is Status.VERIFIED
    assert EXEMPLAR in droot.calls[0][1]["content"]


def test_run_arm_forwards_the_exemplar(fake_backend):
    wire_direct(fake_backend)
    root = StubRoot(fenced("by\n  simp"))
    arms.run_arm("direct", NAT_GOAL, root=root, backend=fake_backend, budgets=budgets(),
                 exemplar=EXEMPLAR)
    assert EXEMPLAR in root.calls[0][1]["content"]


def test_cell_filename_marks_a_few_shot_cell():
    """A few-shot run must never resume into, or append to, the zero-shot cell
    of the same coordinates."""
    zero = zs.cell_path(Path("/r"), "bridge_chain", "2", "decomp", "qwen/qwen3-30b")
    few = zs.cell_path(Path("/r"), "bridge_chain", "2", "decomp", "qwen/qwen3-30b",
                       few_shot=True)
    assert zero.name == "bridge_chain_k2_decomp_qwen-qwen3-30b.jsonl"
    assert few.name == "bridge_chain_k2_fs-decomp_qwen-qwen3-30b.jsonl"
    assert few != zero


def test_zero_shot_rows_say_so(tmp_path, fake_backend, monkeypatch):
    wire_direct(fake_backend)
    probs = _write(tmp_path, _problem_rows(1))
    _install_stubs(monkeypatch, fake_backend, _direct_root())
    assert zs.main(_direct_argv(probs, tmp_path / "out")) == 0
    row = _rows(tmp_path / "out" / "probs_k2_direct_stub-root.jsonl")[0]
    assert row["few_shot"] is False and row["exemplar"] is None


def test_main_few_shot_writes_the_fs_cell_and_records_provenance(tmp_path, fake_backend,
                                                                 monkeypatch, capsys):
    from rlmath.core.types import statement_key
    from rlmath.eval.exemplars import build_exemplar, load_exemplar_problem

    wire_direct(fake_backend)
    probs = _write(tmp_path, _problem_rows(2))
    root = _direct_root()
    _install_stubs(monkeypatch, fake_backend, root)

    assert zs.main(_direct_argv(probs, tmp_path / "out", "--few-shot")) == 0

    out = tmp_path / "out" / "probs_k2_fs-direct_stub-root.jsonl"
    assert out.exists()
    assert not (tmp_path / "out" / "probs_k2_direct_stub-root.jsonl").exists()

    # the exemplar family defaulted to the family the problems came from
    exemplar_problem = load_exemplar_problem("bridge_chain")
    text = build_exemplar(exemplar_problem, "direct")
    rows = _rows(out)
    assert len(rows) == 2
    for r in rows:
        assert r["few_shot"] is True
        assert r["exemplar"] == {
            "arm": "direct",
            "family": "bridge_chain",
            "k": 2,
            "seed": 999,
            "problem_id": exemplar_problem.id,
            "goal_statement_key": statement_key(exemplar_problem.goal.prop),
            "goal_name": exemplar_problem.goal.name,
            "chars": len(text),
        }
    # and the example actually reached the model
    assert text in root.calls[0][1]["content"]
    assert "few-shot: arm=direct" in capsys.readouterr().err


def test_main_few_shot_honours_the_exemplar_knobs(tmp_path, fake_backend, monkeypatch):
    wire_direct(fake_backend)
    probs = _write(tmp_path, _problem_rows(1))
    _install_stubs(monkeypatch, fake_backend, _direct_root())
    argv = _direct_argv(probs, tmp_path / "out", "--few-shot",
                        "--exemplar-family", "case_tree", "--exemplar-k", "4",
                        "--exemplar-seed", "1234")
    assert zs.main(argv) == 0
    prov = _rows(tmp_path / "out" / "probs_k2_fs-direct_stub-root.jsonl")[0]["exemplar"]
    assert (prov["family"], prov["k"], prov["seed"]) == ("case_tree", 4, 1234)


def test_main_refuses_an_exemplar_that_is_also_an_eval_problem(tmp_path, fake_backend,
                                                               monkeypatch):
    """Loud, not a silent skip: a worked example that IS an eval item turns the
    cell into a recall measurement."""
    from rlmath.eval.exemplars import load_exemplar_problem

    contaminated = load_exemplar_problem("bridge_chain")
    rows_in = _problem_rows(2)
    rows_in[1]["goal"] = {"id": "prob-1", "prop": contaminated.goal.prop, "name": "thm_1"}
    probs = _write(tmp_path, rows_in)
    monkeypatch.setattr(zs, "make_root", lambda args: pytest.fail("ran despite contamination"))
    monkeypatch.setattr(zs, "make_backend", lambda args: pytest.fail("ran despite contamination"))

    with pytest.raises(SystemExit, match="same goal proposition"):
        zs.main(_direct_argv(probs, tmp_path / "out", "--few-shot"))
    assert not (tmp_path / "out").exists()


def test_contamination_is_matched_modulo_whitespace(tmp_path):
    """`statement_key` normalization, not raw equality: an exemplar differing
    from an eval item only in spacing is the same contamination."""
    from rlmath.eval.exemplars import load_exemplar_problem

    problem = load_exemplar_problem("bridge_chain")
    spaced = zs.Problem(id="p", goal=GoalSpec(id="p", prop=problem.goal.prop + "  ", name="t"))
    with pytest.raises(SystemExit, match="same goal proposition"):
        zs.assert_exemplar_is_not_an_eval_problem(problem, [spaced])
    other = zs.Problem(id="q", goal=GoalSpec(id="q", prop="1 + 1 = 2", name="t"))
    zs.assert_exemplar_is_not_an_eval_problem(problem, [other])   # no clash, no raise


def test_dry_run_still_builds_and_checks_the_exemplar(tmp_path, capsys):
    """Free and offline, so a misconfigured or contaminated exemplar is caught
    before any token is bought."""
    probs = _write(tmp_path, _problem_rows(1))
    assert zs.main(_direct_argv(probs, tmp_path / "out", "--few-shot", "--dry-run")) == 0
    assert "few-shot: arm=direct, family=bridge_chain" in capsys.readouterr().err


def test_few_shot_needs_a_family_it_can_default_to(tmp_path):
    """Bank/goal rows carry no family; guessing one would silently change what
    the cell measures."""
    probs = _write(tmp_path, [BANK_ROW])
    with pytest.raises(SystemExit, match="--exemplar-family"):
        zs.main(_direct_argv(probs, tmp_path / "out", "--few-shot", "--dry-run"))


def test_few_shot_rejects_an_unknown_family(tmp_path):
    probs = _write(tmp_path, _problem_rows(1))
    with pytest.raises(SystemExit, match="unknown family"):
        zs.main(_direct_argv(probs, tmp_path / "out", "--few-shot", "--dry-run",
                             "--exemplar-family", "nope"))


def test_exemplar_flags_without_few_shot_are_refused():
    """Silently ignoring them would leave an operator believing a cell was
    few-shot when it was not."""
    for flag, value in (("--exemplar-family", "case_tree"), ("--exemplar-k", "4"),
                        ("--exemplar-seed", "7")):
        with pytest.raises(SystemExit):
            _args(flag, value)
    a = _args("--few-shot", "--exemplar-k", "4")
    assert a.few_shot is True and a.exemplar_k == 4
    assert _args().few_shot is False
    assert (_args().exemplar_k, _args().exemplar_seed) == (2, 999)


# ---------------------------------------------------------------------------
# integration — needs scripts/setup_lean.sh to have completed
# ---------------------------------------------------------------------------

_HAS_LEAN = False
try:  # pragma: no cover - depends on the box
    from rlmath.lean.repl_pool import ReplConfig, ReplPool

    _HAS_LEAN = ReplConfig().available()
except Exception:  # pragma: no cover
    ReplPool = None  # type: ignore[assignment]

needs_lean = pytest.mark.skipif(not _HAS_LEAN, reason="no lean project/repl binary")


@pytest.mark.integration
@needs_lean
@pytest.mark.timeout(900)
def test_live_direct_arm_against_the_real_kernel():
    """The direct arm's verdict is the kernel's: one true goal, one false one.

    A FakeBackend can only show the right strings were sent; this shows the
    proof_check -> sanitizer -> kernel -> `#print axioms` chain actually rules.
    """
    good = GoalSpec(id="live-ok", prop="∀ n : ℕ, n + 0 = n", name="zs_live_ok")
    bad = GoalSpec(id="live-bad", prop="∀ n : ℕ, n + 1 = n", name="zs_live_bad")
    pool = ReplPool(n_workers=2)
    try:
        pool.warm()
        ok = arms.run_direct(good, root=StubRoot(fenced("by\n  simp", good)),
                             backend=pool, budgets=budgets())
        assert ok.status is Status.VERIFIED, ok.detail
        assert ok.reward == 1.0
        assert ok.artifact and ok.artifact.startswith("theorem zs_live_ok")

        no = arms.run_direct(bad, root=StubRoot(fenced("by\n  simp", bad)),
                             backend=pool, budgets=budgets())
        assert no.status is Status.LEAF_FAILED, no.detail
        assert no.reward == 0.0
    finally:
        pool.close()
