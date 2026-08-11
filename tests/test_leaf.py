"""Leaf adapter tests. Offline: a stub client stands in for the prover model,
`FakeBackend` (conftest) for the Lean kernel.

The extract_proof cases are the point of this file. In ../rl a parser that
silently failed on one model's output shape zeroed whole eval cells
(REPORT_NOTES accommodation 3), so every shape here is one that a prover or a
generic instruct model actually emits.
"""
from __future__ import annotations

import pytest

from rlmath.core.types import VerifyResult, statement_key
from rlmath.leaf import AttemptCache, LeafProver, extract_proof, render
from rlmath.leaf.adapter import OpenAIChatClient

PROP = "2 ∣ 4 + 6"
PROOF = "by\n  norm_num"


class StubClient:
    """Scripted leaf model: returns queued completions, records every call."""

    def __init__(self, *completions: str) -> None:
        self.queue = list(completions)
        self.calls: list[tuple[list[dict], int]] = []

    def __call__(self, messages: list[dict], n: int) -> list[str]:
        self.calls.append((messages, n))
        out, self.queue = self.queue[:n], self.queue[n:]
        return out

    @property
    def n_requested(self) -> list[int]:
        return [n for _, n in self.calls]


def fenced(body: str, tag: str = "lean4") -> str:
    return f"```{tag}\n{body}\n```"


# ---------------------------------------------------------------------------
# prompts / templates
# ---------------------------------------------------------------------------

def test_deepseek_non_cot_template_is_verbatim():
    (msg,) = render("deepseek-prover-v2-non-cot", PROP)
    assert msg["role"] == "user"
    assert msg["content"] == (
        "Complete the following Lean 4 code:\n"
        "\n"
        "```lean4\n"
        "import Mathlib\n"
        "import Aesop\n"
        "\n"
        "set_option maxHeartbeats 0\n"
        "\n"
        "open BigOperators Real Nat Topology Rat\n"
        "\n"
        "theorem leaf_goal : 2 ∣ 4 + 6 := by\n"
        "  sorry\n"
        "```"
    )


def test_cot_is_non_cot_plus_two_sentences():
    non_cot = render("deepseek-prover-v2-non-cot", PROP)[0]["content"]
    cot = render("deepseek-prover-v2-cot", PROP)[0]["content"]
    assert cot.startswith(non_cot)
    assert cot[len(non_cot):] == (
        "\n\nBefore producing the Lean 4 code to formally prove the given theorem, provide a"
        " detailed proof plan outlining the main proof steps and strategies.\nThe plan should"
        " highlight key ideas, intermediate lemmas, and proof structures that will guide the"
        " construction of the final formal proof."
    )
    # Goedel's card publishes DeepSeek's CoT template verbatim (research/models-datasets.md §2).
    assert render("goedel-prover-v2", PROP)[0]["content"] == cot


def test_plain_template_is_a_system_plus_user_pair():
    msgs = render("plain", PROP)
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert "Lean 4" in msgs[0]["content"]
    assert PROP in msgs[1]["content"] and "```lean4" in msgs[1]["content"]


def test_unknown_template_names_the_known_ones():
    with pytest.raises(KeyError, match="deepseek-prover-v2-non-cot"):
        render("no-such-template", PROP)


# ---------------------------------------------------------------------------
# extract_proof — realistic completion shapes
# ---------------------------------------------------------------------------

def test_extract_fenced_full_skeleton():
    """DeepSeek non-CoT's canonical output: the prompt's file, sorry replaced."""
    out = fenced(
        "import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 0\n\n"
        "open BigOperators Real Nat Topology Rat\n\n"
        "theorem leaf_goal : 2 ∣ 4 + 6 := by\n  decide"
    )
    assert extract_proof(out) == "by\n  decide"


def test_extract_fenced_plain_tag_and_chatter_around_it():
    out = (
        "Sure! Here is the completed proof.\n\n"
        + fenced("theorem leaf_goal : 2 ∣ 4 + 6 := by\n  norm_num", tag="lean")
        + "\n\nThis works because 4 + 6 = 10 is even."
    )
    assert extract_proof(out) == "by\n  norm_num"


def test_extract_prefers_the_last_lean_block():
    """CoT models sketch first and answer last."""
    out = (
        "Plan:\n" + fenced("theorem leaf_goal : 2 ∣ 4 + 6 := by\n  sorry")
        + "\nFinal:\n" + fenced("theorem leaf_goal : 2 ∣ 4 + 6 := by\n  omega")
    )
    assert extract_proof(out) == "by\n  omega"


def test_extract_bare_restated_theorem_strips_statement_and_assign():
    out = "theorem foo (x : ℝ) : x ^ 2 ≥ 0 := by\n  positivity\n"
    assert extract_proof(out) == "by\n  positivity"


def test_extract_bare_theorem_with_trailing_prose():
    out = (
        "Here you go:\n"
        "theorem leaf_goal : 2 ∣ 4 + 6 := by\n"
        "  norm_num\n"
        "\n"
        "That completes the proof.\n"
    )
    assert extract_proof(out) == "by\n  norm_num"


def test_extract_by_on_its_own_line_after_assign():
    out = "theorem leaf_goal : 2 ∣ 4 + 6 :=\n  by\n    decide\n"
    assert extract_proof(out) == "by\n  decide"


def test_extract_bare_tactic_block_gets_wrapped_in_by():
    """Completion-style models continue the prompt and emit tactics only."""
    assert extract_proof(fenced("nlinarith [sq_nonneg (x - y)]\nlinarith")) == (
        "by\n  nlinarith [sq_nonneg (x - y)]\n  linarith"
    )


def test_extract_indented_bare_tactic_block_keeps_its_shape():
    out = fenced("  intro n\n  induction n with\n  | zero => simp\n  | succ k ih => simp [ih]")
    assert extract_proof(out) == (
        "by\n  intro n\n  induction n with\n  | zero => simp\n  | succ k ih => simp [ih]"
    )


def test_extract_term_proof_is_left_as_a_term():
    assert extract_proof("theorem leaf_goal : 2 ∣ 4 + 6 := Nat.dvd_of_mod_eq_zero rfl") == (
        "Nat.dvd_of_mod_eq_zero rfl"
    )
    assert extract_proof(fenced("⟨5, by norm_num⟩")) == "⟨5, by norm_num⟩"


def test_extract_undotted_term_inside_a_fence_survives():
    """Mathlib lemma names are not all dotted; inside a fence the model has
    already told us it is Lean, so an unrecognized body passes through."""
    assert extract_proof(fenced("dvd_add h1 h2")) == "dvd_add h1 h2"
    assert extract_proof(fenced("rfl")) == "rfl"
    assert extract_proof("theorem t : n = n := rfl") == "rfl"
    # ...but the same text unfenced and undeclared stays a format failure.
    assert extract_proof("dvd_add h1 h2") is None


def test_extract_ignores_a_prose_plan_in_an_untagged_fence():
    """CoT models put the plan in a bare ``` block; only a lean tag or a
    declaration buys pass-through."""
    assert extract_proof("```\nStep 1: induct on n. Step 2: simplify.\n```") is None
    assert extract_proof(
        "```\nStep 1: induct.\n```\n\n```lean4\ntheorem t : P := by\n  induction n <;> simp\n```"
    ) == "by\n  induction n <;> simp"


def test_extract_unclosed_fence_is_a_truncated_attempt_not_a_parse_failure():
    """max_tokens cut mid-proof: keep the attempt, let the kernel reject it."""
    out = "```lean4\ntheorem leaf_goal : 2 ∣ 4 + 6 := by\n  have h : (10 : ℕ) = 4 + 6 := by"
    assert extract_proof(out) == "by\n  have h : (10 : ℕ) = 4 + 6 := by"


def test_extract_normalizes_crlf():
    """A stray \\r is legal Lean but poisons cache and similarity comparisons."""
    assert extract_proof("theorem t : P := by\r\n  simp\r\n  ring\r\n") == "by\n  simp\n  ring"


def test_extract_helper_lemma_before_the_goal_takes_the_last_declaration():
    out = fenced(
        "lemma aux : (10 : ℕ) = 4 + 6 := by norm_num\n\n"
        "theorem leaf_goal : 2 ∣ 4 + 6 := by\n  rw [← aux]"
    )
    # The composed artifact must be a single theorem, so the helper is dropped
    # and the proof fails loudly at the kernel rather than silently half-working.
    assert extract_proof(out) == "by\n  rw [← aux]"


@pytest.mark.parametrize(
    "garbage",
    [
        None,
        "",
        "   \n\n  ",
        "I'm sorry, I cannot prove this theorem.",
        "This statement appears to be false for n = 0.",
        fenced("theorem leaf_goal : 2 ∣ 4 + 6 := by\n  sorry"),  # echoed skeleton
        "sorry",
        fenced("theorem leaf_goal : 2 ∣ 4 + 6"),  # statement only, no :=
    ],
)
def test_extract_returns_none_rather_than_garbage(garbage):
    assert extract_proof(garbage) is None


def test_extract_output_feeds_proof_check_unchanged():
    """The contract with core.leancode: a term or `by` block, never a `:=`."""
    from rlmath.core.leancode import proof_check

    proof = extract_proof(fenced("theorem leaf_goal : 2 ∣ 4 + 6 := by\n  decide"))
    assert proof is not None and not proof.startswith(":=")
    assert proof_check(PROP, proof) == "theorem _proof_check : 2 ∣ 4 + 6 :=\n  by\n    decide"


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------

@pytest.fixture
def cache(tmp_path) -> AttemptCache:
    c = AttemptCache(tmp_path / "sub" / "leaf.sqlite")  # also checks parent mkdir
    yield c
    c.close()


def test_cache_roundtrip_and_ordering(cache):
    for idx in (2, 0, 1):
        cache.put_attempt("k1", "m", "s", idx, f"proof{idx}")
    recs = cache.get_attempts("k1", "m", "s")
    assert [r.index for r in recs] == [0, 1, 2]
    assert [r.proof for r in recs] == ["proof0", "proof1", "proof2"]
    assert all(r.verified is None for r in recs)  # generated, not yet checked
    assert cache.get_attempts("other", "m", "s") == []


def test_cache_partitions_by_model_and_sampling_key(cache):
    cache.put_attempt("k1", "m1", "s1", 0, "a")
    cache.put_attempt("k1", "m2", "s1", 0, "b")
    cache.put_attempt("k1", "m1", "s2", 0, "c")
    assert [r.proof for r in cache.get_attempts("k1", "m1", "s1")] == ["a"]
    assert [r.proof for r in cache.get_attempts("k1", "m2", "s1")] == ["b"]
    assert [r.proof for r in cache.get_attempts("k1", "m1", "s2")] == ["c"]


def test_cache_mark_verified_and_missing_row_is_loud(cache):
    cache.put_attempt("k1", "m", "s", 0, "a")
    assert cache.mark_verified("k1", "m", "s", 0, True) is True
    assert cache.get_attempts("k1", "m", "s")[0].verified is True
    assert cache.mark_verified("k1", "m", "s", 0, False) is True
    assert cache.get_attempts("k1", "m", "s")[0].verified is False
    assert cache.mark_verified("k1", "m", "s", 9, True) is False  # no such attempt


def test_cache_persists_across_reopen(tmp_path):
    path = tmp_path / "leaf.sqlite"
    with AttemptCache(path) as c:
        c.put_attempt("k1", "m", "s", 0, "a", verified=True)
    with AttemptCache(path) as c:
        (rec,) = c.get_attempts("k1", "m", "s")
        assert (rec.proof, rec.verified) == ("a", True)
        assert c.count() == 1


# ---------------------------------------------------------------------------
# generate: cache hit / miss / top-up
# ---------------------------------------------------------------------------

def prover(client, cache=None, **kw) -> LeafProver:
    return LeafProver(client=client, model="prover-x", cache=cache, **kw)


def test_generate_miss_calls_client_once_for_n(cache):
    client = StubClient(fenced("theorem t : P := by\n  simp"), fenced("by\n  ring"))
    p = prover(client, cache)
    assert p.generate(PROP, 2) == ["by\n  simp", "by\n  ring"]
    assert client.n_requested == [2]
    assert p.stats["generated"] == 2


def test_generate_hit_does_not_call_the_client(cache):
    client = StubClient(fenced("by\n  simp"))
    p = prover(client, cache)
    p.generate(PROP, 1)
    p2 = prover(StubClient(), cache)  # empty queue: any call would return short
    assert p2.generate(PROP, 1) == ["by\n  simp"]
    assert p2.stats["cache_hits"] == 1


def test_generate_tops_up_only_the_missing_indices(cache):
    p = prover(StubClient(fenced("by\n  simp"), fenced("by\n  ring")), cache)
    p.generate(PROP, 2)
    client = StubClient(fenced("by\n  omega"), fenced("by\n  decide"))
    p2 = prover(client, cache)
    assert p2.generate(PROP, 4) == ["by\n  simp", "by\n  ring", "by\n  omega", "by\n  decide"]
    assert client.n_requested == [2]  # only indices 2 and 3 were generated
    key = statement_key(PROP)
    assert [r.index for r in cache.get_attempts(key, "prover-x", p2.sampling_key)] == [0, 1, 2, 3]


def test_generate_below_cached_count_returns_a_prefix(cache):
    p = prover(StubClient(fenced("by\n  simp"), fenced("by\n  ring")), cache)
    p.generate(PROP, 2)
    p2 = prover(StubClient(), cache)
    assert p2.generate(PROP, 1) == ["by\n  simp"]


def test_unparsed_completion_is_a_failed_attempt_not_a_missing_one(cache):
    client = StubClient("I cannot prove this.", fenced("by\n  ring"))
    p = prover(client, cache)
    assert p.generate(PROP, 2) == ["by\n  ring"]   # short by one, deliberately
    assert p.stats["unparsed"] == 1

    key = statement_key(PROP)
    stored = cache.get_attempts(key, "prover-x", p.sampling_key)
    assert (stored[0].proof, stored[0].verified) == ("", False)

    p2 = prover(StubClient(fenced("by\n  omega")), cache)
    assert p2.generate(PROP, 2) == ["by\n  ring"]  # slot 0 is NOT regenerated
    assert p2.stats["generated"] == 0


def test_generate_works_without_a_cache():
    client = StubClient(fenced("by\n  simp"))
    p = prover(client, None)
    assert p.generate(PROP, 1) == ["by\n  simp"]
    assert p.generate(PROP, 1) == []  # no cache, no memory: the queue is empty now
    assert client.n_requested == [1, 1]


def test_sampling_key_covers_template_temperature_and_max_tokens():
    a = prover(StubClient(), temperature=1.0, max_tokens=2048)
    b = prover(StubClient(), temperature=0.7, max_tokens=2048)
    c = prover(StubClient(), temperature=1.0, max_tokens=4096)
    d = prover(StubClient(), template="plain", temperature=1.0, max_tokens=2048)
    assert len({a.sampling_key, b.sampling_key, c.sampling_key, d.sampling_key}) == 4
    assert a.sampling_key == "deepseek-prover-v2-non-cot|T=1|M=2048"


def test_unknown_template_fails_at_construction():
    with pytest.raises(KeyError):
        prover(StubClient(), template="nope")


# ---------------------------------------------------------------------------
# prove: kernel check, early stop, verdict marking
# ---------------------------------------------------------------------------

def test_prove_early_stops_at_the_first_success(cache, fake_backend):
    fake_backend.rule_contains("norm_num", ok=False, errtext="linarith failed")
    fake_backend.rule_contains("decide", ok=True)
    client = StubClient(fenced("by\n  norm_num"), fenced("by\n  decide"), fenced("by\n  omega"))
    p = prover(client, cache)

    proof, records = p.prove(PROP, 3, fake_backend)
    assert proof == "by\n  decide"
    assert [r.verified for r in records] == [False, True]   # third never checked
    assert len(fake_backend.calls) == 2
    assert fake_backend.calls[0] == "theorem _proof_check : 2 ∣ 4 + 6 :=\n  by\n    norm_num"


def test_prove_without_early_stop_checks_every_attempt(cache, fake_backend):
    fake_backend.rule_contains("norm_num", ok=False)
    fake_backend.rule_contains("decide", ok=True)
    fake_backend.rule_contains("omega", ok=True)
    client = StubClient(fenced("by\n  norm_num"), fenced("by\n  decide"), fenced("by\n  omega"))
    p = prover(client, cache)

    proof, records = p.prove(PROP, 3, fake_backend, early_stop=False)
    assert proof == "by\n  decide"  # first success wins even when all are checked
    assert [r.verified for r in records] == [False, True, True]
    assert len(fake_backend.calls) == 3


def test_prove_rejects_a_compiling_proof_that_still_has_a_sorry(cache, fake_backend):
    """`ok` alone is not success — the backend is sorry-policy-free by design."""
    fake_backend.rule(lambda c: True, VerifyResult(ok=True, sorries=1))
    p = prover(StubClient(fenced("by\n  have h : 2 ∣ 4 := by sorry\n  omega")), cache)
    proof, records = p.prove(PROP, 1, fake_backend)
    assert proof is None
    assert records[0].verified is False


def test_prove_writes_verdicts_to_the_cache_and_reuses_them(cache, fake_backend):
    fake_backend.rule_contains("norm_num", ok=False)
    fake_backend.rule_contains("decide", ok=True)
    p = prover(StubClient(fenced("by\n  norm_num"), fenced("by\n  decide")), cache)
    p.prove(PROP, 2, fake_backend)

    stored = cache.get_attempts(statement_key(PROP), "prover-x", p.sampling_key)
    assert [r.verified for r in stored] == [False, True]

    # Re-running the same statement is free: no generation, no kernel calls.
    fake_backend.calls.clear()
    p2 = prover(StubClient(), cache)
    proof, records = p2.prove(PROP, 2, fake_backend)
    assert proof == "by\n  decide"
    assert fake_backend.calls == []
    assert p2.stats["checked"] == 0
    assert [(r.index, r.verified) for r in records] == [(0, False), (1, True)]


def test_prove_records_carry_the_statement_key_and_model(cache, fake_backend):
    fake_backend.rule_contains("decide", ok=True)
    p = prover(StubClient(fenced("by\n  decide")), cache)
    _, (rec,) = p.prove(PROP, 1, fake_backend)
    assert (rec.statement_key, rec.model, rec.index) == (statement_key(PROP), "prover-x", 0)


def test_prove_with_no_usable_attempts_never_touches_the_backend(cache, fake_backend):
    p = prover(StubClient("nope, sorry, cannot help"), cache)
    proof, records = p.prove(PROP, 1, fake_backend)
    assert (proof, records) == (None, [])
    assert fake_backend.calls == []


def test_prove_return_is_readable_by_the_sibling_pair_contract(cache, fake_backend):
    """harness/episode._leaf_result and scripts/build_bank._single_result read a
    2-tuple's second element as the attempt *count* via int(). See AttemptList."""
    fake_backend.rule_contains("norm_num", ok=False)
    fake_backend.rule_contains("decide", ok=True)
    p = prover(StubClient(fenced("by\n  norm_num"), fenced("by\n  decide")), cache)
    res = p.prove(PROP, 2, fake_backend)
    assert int(res[1]) == 2 == len(res[1])

    # Cross-module check, kept skippable: the sibling is developed concurrently
    # and its normalizer is private, so this documents the seam without making
    # this suite hostage to it.
    episode = pytest.importorskip("rlmath.harness.episode")
    normalize = getattr(episode, "_leaf_result", None)
    if normalize is not None:
        assert normalize(res, k=2) == ("by\n  decide", 2)


# ---------------------------------------------------------------------------
# OpenAI-compatible client wrapper (no network: a fake SDK object)
# ---------------------------------------------------------------------------

class _Msg:
    def __init__(self, content): self.content = content


class _Choice:
    def __init__(self, content): self.message = _Msg(content)


class FakeOpenAI:
    """Mimics `openai.OpenAI`. `choices_per_call` emulates ollama (1) vs vLLM (n)."""

    def __init__(self, choices_per_call: int | None = None):
        self.choices_per_call = choices_per_call
        self.requests: list[dict] = []
        self.chat = type("chat", (), {"completions": self})()

    def create(self, **kwargs):
        self.requests.append(kwargs)
        n = kwargs["n"] if self.choices_per_call is None else min(self.choices_per_call, kwargs["n"])
        return type("resp", (), {"choices": [_Choice(f"by\n  tac{i}") for i in range(n)]})()


def test_openai_client_batches_when_the_server_honours_n():
    oai = FakeOpenAI()
    client = OpenAIChatClient(oai, "m", temperature=0.9, max_tokens=64)
    assert client([{"role": "user", "content": "x"}], 4) == [f"by\n  tac{i}" for i in range(4)]
    assert len(oai.requests) == 1
    assert oai.requests[0]["temperature"] == 0.9 and oai.requests[0]["max_tokens"] == 64


def test_openai_client_loops_when_the_server_ignores_n():
    oai = FakeOpenAI(choices_per_call=1)  # ollama
    client = OpenAIChatClient(oai, "m", temperature=1.0, max_tokens=64)
    assert len(client([{"role": "user", "content": "x"}], 3)) == 3
    assert [r["n"] for r in oai.requests] == [3, 2, 1]


def test_from_openai_wires_the_sampling_settings_through(cache):
    """Constructs the SDK client only — no request is made."""
    pytest.importorskip("openai")
    p = LeafProver.from_openai(
        base_url="http://localhost:11434/v1",
        api_key="ollama",
        model="hf.co/unsloth/DeepSeek-Prover-V2-7B-GGUF:UD-Q6_K_XL",
        temperature=0.8,
        max_tokens=1024,
        cache=cache,
    )
    assert isinstance(p.client, OpenAIChatClient)
    assert (p.client.temperature, p.client.max_tokens) == (0.8, 1024)
    assert p.client.model == p.model and p.cache is cache
    assert p.sampling_key.endswith("|T=0.8|M=1024")


def test_openai_client_gives_up_when_the_server_returns_nothing():
    oai = FakeOpenAI(choices_per_call=0)
    client = OpenAIChatClient(oai, "m", temperature=1.0, max_tokens=64)
    assert client([{"role": "user", "content": "x"}], 3) == []
    assert len(oai.requests) == 1  # no spin
