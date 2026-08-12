"""Phase-2 zero-shot arms: one root completion in, one typed outcome out.

DIRECTION.md §5.5 Phase 2 runs
`{flat 1-shot, flat best-of-N compute-matched, flat-CoT-decomposition, isolated-RLM}`
× roots × k-grid. This module ships the two ends of that list — `direct`
(flat 1-shot) and `decomp` (isolated harness, single-shot) — behind one
signature, so the remaining two arms are a new entry in `ARMS` rather than a
new runner.

**No scoring lives here.** Both arms hand their completion to code that already
owns a verdict:

  * `decomp` -> `rlmath.envs.decomp_env.score_plan` (the same call the trained
    environment makes, so the zero-shot numbers and the Phase-3 rollout numbers
    come off one code path);
  * `direct` -> `rlmath.harness.episode.run_direct_close`, which is documented
    as *the flat-arm baseline* — proof_check -> sanitizer -> single-theorem gate
    -> kernel -> `#print axioms` audit, in one place.

The direct arm reaches `run_direct_close` by wrapping the root's completion in a
`rlmath.leaf.LeafProver` whose client replays that text (`_ReplayClient`). That
looks indirect and is deliberate: `LeafProver` already owns the two things the
direct arm needs and must not fork — the completion parser
(`leaf.prompts.extract_proof`, whose liberality is tuned against real model
output and tested) and the "verified means ok AND sorries == 0" rule. The root
is not a leaf; only the *verification half* of the class is used, the cache is
off (root proofs must never enter the leaf oracle's attempt cache), and the
attempt budget is pinned to 1 because one root completion is one attempt.

Status mapping (the taxonomy is fixed in core/types.py; nothing is invented):

| event                                    | direct              | decomp                |
|------------------------------------------|---------------------|-----------------------|
| completion has no proof-shaped content    | FORMAT_ERROR        | FORMAT_ERROR (parser) |
| banned token in the root's own text       | SANITIZER_REJECTED  | SANITIZER_REJECTED    |
| prover's proof fails the kernel           | LEAF_FAILED         | LEAF_FAILED (a lemma) |
| kernel ok, axiom audit dirty              | SANITIZER_REJECTED  | SANITIZER_REJECTED    |
| kernel ok, audit clean                    | VERIFIED            | VERIFIED              |

`LEAF_FAILED` in the direct arm means "the root's own proof did not check" —
the root *is* the prover there, and `run_direct_close` (the flat baseline) names
it that. Rows carry `arm`, so the two senses stay separable in analysis; a
dedicated `prover_failed` status would be a core/types.py change and is flagged
rather than taken unilaterally.

Infrastructure failures are never scored: backend explosions and root-API errors
propagate to the runner, which writes an `error` row (DIRECTION §6 — an
infrastructure failure scored as 0.0 is indistinguishable from a policy failure).
`status_for_exception` is the one exception: an over-window refusal from the API
is *feasibility* evidence (§5.7 P1) and gets `CONTEXT_WINDOW_EXCEEDED`.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from rlmath.core.backend import LeanBackend
from rlmath.core.types import Budgets, GoalSpec, Status
from rlmath.envs.decomp_env import build_prompt, score_plan
from rlmath.harness.episode import LeafProver as LeafProverProtocol
from rlmath.harness.episode import run_direct_close

Message = dict[str, str]

# ../rl/eval/run_eval.py's estimator, kept for the *fallback* only. DIRECTION §6:
# "Never trust token estimates. ../rl used chars/3.5 and was wrong by ~2× on
# hash-dense text." Lean statements are symbol-dense, so the same failure
# direction is expected — every row says which source its numbers came from, and
# the runner's budget guard inflates estimated counts before charging them.
CHARS_PER_TOKEN = 3.5


# ---------------------------------------------------------------------------
# Root model client (OpenAI-compatible)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Usage:
    """Root token usage for one completion, with its provenance attached.

    `source` is not decoration: a spend figure computed from `chars/3.5` and one
    computed from the provider's own accounting are different claims, and the
    budget guard treats them differently. Fields are per-direction because
    providers do omit one of the two.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    source: str = "none"          # "api" | "chars/3.5" | "api+chars/3.5" | "none"

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def estimated(self) -> bool:
        return self.source != "api"

    def as_row(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "source": self.source,
        }


@dataclass(frozen=True)
class RootCompletion:
    text: str
    usage: Usage
    finish_reason: str | None = None
    elapsed_s: float = 0.0


class RootClient(Protocol):
    """Anything that turns chat messages into one root completion.

    Same dependency-injection seam as `leaf.LeafClient`: the unit suite passes a
    stub, a live run passes `OpenAIRootClient`. Nothing below this line imports
    an SDK.
    """

    model: str

    def complete(self, messages: Sequence[Message]) -> RootCompletion: ...


def estimate_tokens(n_chars: int) -> int:
    return int(n_chars / CHARS_PER_TOKEN)


def usage_from_response(resp: Any, *, prompt_chars: int, completion_chars: int) -> Usage:
    """Read `usage` off an OpenAI-shaped response, estimating only what is absent.

    Per-field rather than all-or-nothing, because a provider that reports
    `prompt_tokens` and omits `completion_tokens` should still contribute its
    real number. The estimated half is announced in `source` and never silently
    upgraded to "api".
    """
    u = getattr(resp, "usage", None)
    p = _int_or_none(getattr(u, "prompt_tokens", None)) if u is not None else None
    c = _int_or_none(getattr(u, "completion_tokens", None)) if u is not None else None
    if p is not None and c is not None:
        return Usage(prompt_tokens=p, completion_tokens=c, source="api")
    est_p = estimate_tokens(prompt_chars)
    est_c = estimate_tokens(completion_chars)
    if p is None and c is None:
        return Usage(prompt_tokens=est_p, completion_tokens=est_c, source="chars/3.5")
    return Usage(
        prompt_tokens=p if p is not None else est_p,
        completion_tokens=c if c is not None else est_c,
        source="api+chars/3.5",
    )


def _int_or_none(v: Any) -> int | None:
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class OpenAIRootClient:
    """`RootClient` over any OpenAI-compatible chat endpoint.

    Constructed with a live SDK object rather than a URL so the whole class is
    testable against `httpx.MockTransport` (see `make_root_client`, which is the
    place that reads the environment).
    """

    def __init__(
        self,
        oai: Any,
        model: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        extra_body: Mapping[str, Any] | None = None,
    ) -> None:
        self.oai = oai
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.extra_body = dict(extra_body or {})

    def complete(self, messages: Sequence[Message]) -> RootCompletion:
        t0 = time.perf_counter()
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=list(messages),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        if self.extra_body:
            kwargs["extra_body"] = dict(self.extra_body)
        resp = self.oai.chat.completions.create(**kwargs)
        choices = getattr(resp, "choices", None) or []
        text = (getattr(choices[0].message, "content", "") or "") if choices else ""
        finish = getattr(choices[0], "finish_reason", None) if choices else None
        prompt_chars = sum(len(m.get("content") or "") for m in messages)
        return RootCompletion(
            text=text,
            usage=usage_from_response(resp, prompt_chars=prompt_chars,
                                      completion_chars=len(text)),
            finish_reason=finish,
            elapsed_s=time.perf_counter() - t0,
        )


def parse_extra_headers(pairs: Sequence[str] | None) -> dict[str, str]:
    """`["X-Prime-Team-ID=team_x", ...]` -> dict. Split on the FIRST `=` only.

    Prime Inference bills a team through `X-Prime-Team-ID`; without it a run
    either fails or is billed to the wrong account, so a malformed pair is a
    hard error rather than a dropped header.
    """
    out: dict[str, str] = {}
    for raw in pairs or ():
        key, sep, value = str(raw).partition("=")
        key = key.strip()
        if not sep or not key:
            raise ValueError(f"--extra-header wants KEY=VALUE, got {raw!r}")
        out[key] = value.strip()
    return out


def make_root_client(
    model: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    extra_headers: Mapping[str, str] | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout_s: float = 900.0,
    http_client: Any = None,
) -> OpenAIRootClient:
    """Build the root client. `base_url`/`api_key` default to the env vars.

    `default_headers` is the SDK's per-client header channel and is what carries
    `X-Prime-Team-ID`. `http_client` exists so the offline test can hand in an
    `httpx.MockTransport` and assert the header actually reaches the wire —
    asserting on the constructor argument would only test the test.
    """
    import os

    import openai

    base = base_url or os.environ.get("OPENAI_BASE_URL") or None
    key = api_key or os.environ.get("OPENAI_API_KEY") or "EMPTY"
    kwargs: dict[str, Any] = {"api_key": key, "timeout": timeout_s}
    if base:
        kwargs["base_url"] = base
    if extra_headers:
        kwargs["default_headers"] = dict(extra_headers)
    if http_client is not None:
        kwargs["http_client"] = http_client
    return OpenAIRootClient(
        openai.OpenAI(**kwargs), model, temperature=temperature, max_tokens=max_tokens
    )


# Provider phrasings for "this prompt does not fit" (../rl matched Anthropic's
# "prompt is too long"; vLLM and Prime Inference use the OpenAI phrasings).
# §5.7 P1 is a feasibility claim, so this class of failure must never land in
# the same bucket as a 500 — nor be scored as a policy failure.
_WINDOW_PATTERNS = (
    "context length",
    "context_length_exceeded",
    "context window",
    "maximum context",
    "prompt is too long",
    "too many tokens",
    "reduce the length of the messages",
    "string too long",
)


def status_for_exception(exc: BaseException) -> Status:
    """CONTEXT_WINDOW_EXCEEDED for an over-window refusal, else ERROR."""
    text = f"{type(exc).__name__}: {exc}".lower()
    return (
        Status.CONTEXT_WINDOW_EXCEEDED
        if any(p in text for p in _WINDOW_PATTERNS)
        else Status.ERROR
    )


# ---------------------------------------------------------------------------
# Arm outcome
# ---------------------------------------------------------------------------

@dataclass
class ArmOutcome:
    """What one arm produced for one goal. Everything the row needs.

    `completion` is the FULL root text, never truncated: DIRECTION §5.7 P2
    (content-masked trajectory isomorphism) is measured over exactly the tokens
    the root emitted, and a truncated log makes that analysis unreproducible
    after the run.

    `plan_stats` is `None` for arms with no plan and for a completion that never
    parsed — absence is the representation, as in `envs.decomp_env.episode_info`
    (zeros would make a FORMAT_ERROR look like a direct-close plan in the P4
    restatement rates).
    """

    arm: str
    status: Status
    reward: float
    completion: str
    usage: Usage
    prompt_chars: int
    root_elapsed_s: float
    score_elapsed_s: float
    detail: str = ""
    plan_stats: dict | None = None
    leaf_attempts_used: int = 0
    artifact: str | None = None
    finish_reason: str | None = None
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Arm 1: direct (flat 1-shot)
# ---------------------------------------------------------------------------

# Why this prompt is minimal — and stays minimal (DIRECTION §5.5 Phase 2).
#
# The Phase-2 gate is "isolated must beat flat-CoT somewhere real **at matched
# compute**". The threat to that claim is not a weak flat arm losing; it is a
# weak flat arm losing *for a reason that is about prompt effort*. So the direct
# prompt is built by symmetry with the harness prompt
# (`envs.decomp_env.SYSTEM_PROMPT`) rather than by tuning:
#
#   carried over, because they are facts about the task and the scorer, not
#   strategy — the goal, its declaration name, "Mathlib is imported", the exact
#   banned-token list, and the statement that reward is kernel + axiom audit.
#   Withholding the banned list would be a trap, not a control: the sanitizer
#   applies identically to both arms.
#
#   The goal is presented as a `sorry`-skeleton to complete (the shape
#   `leaf.prompts.formal_statement` uses, minus its model-specific header) for a
#   measured reason: on the first live smoke (qwen3-30b, 2026-08-12) the root
#   restated the goal with named binders — `theorem g (x y z : ℝ) (hx : 3 ≤ x)
#   ... : ...` — instead of the ∀-telescope it was given. `extract_proof`
#   correctly returns the body, but that body then refers to binders that do not
#   exist in `theorem _proof_check : <∀-prop> := <body>`, so a fine proof fails
#   to elaborate. That is ../rl's accommodation-3 failure exactly: a format
#   mismatch silently scoring the arm zero. Pinning the declaration is a format
#   fix, not a hint — the decomp arm gets the same service from its wire-format
#   spec, and the fix must stay in place or the flat arm is handicapped for a
#   reason that has nothing to do with proving.
#
#   NOT carried over — anything that would teach a proof strategy: no
#   "decompose first", no "think step by step", no worked proof, no
#   few-shot example. The harness prompt's one example exists solely to pin a
#   bespoke wire format (`#lemma/#assembly/#end`); the direct arm's format is
#   the universal fenced code block, so an example there would buy format
#   compliance we already get and smuggle in strategy content we must not add.
#
# The asymmetry that remains is inherent and is the experiment: the harness
# prompt describes an action space the direct arm does not have. Any future
# edit here must be mirrored by an equivalent edit to the harness prompt, or the
# comparison stops being at matched effort. `flat-CoT-decomposition` — the arm
# that *is* allowed to talk about decomposition — is a separate ARMS entry, not
# a rewrite of this one.
DIRECT_SYSTEM = (
    "You are an expert in Lean 4 and Mathlib. You produce complete, "
    "kernel-checkable Lean 4 proofs."
)

DIRECT_USER = """\
Goal id: {goal_id}

Complete the following Lean 4 code:

```lean4
theorem {decl_name} : {prop} := by
  sorry
```

Reply with ONLY the completed code in a single ```lean4 block: the same theorem, \
stated exactly as above, with `sorry` replaced by a real proof. Mathlib is \
imported. Do not restate the theorem with different binders, and do not add any \
other declaration — only this one theorem is checked.

Banned anywhere in your output: sorry, admit, axiom, native_decide, set_option, \
macro, macro_rules, elab, notation, syntax, unsafe, partial, opaque, #exit.

Reward is 1 only when the proof passes the Lean kernel and the axiom audit; \
everything else is 0.\
"""


def direct_prompt(goal: GoalSpec) -> list[Message]:
    """Chat messages for the direct arm. See the comment block above."""
    return [
        {"role": "system", "content": DIRECT_SYSTEM},
        {
            "role": "user",
            "content": DIRECT_USER.format(
                goal_id=goal.id, decl_name=goal.name, prop=goal.prop
            ),
        },
    ]


class _ReplayClient:
    """A `leaf.LeafClient` that replays one already-fetched completion.

    The root has already been called (with the direct-arm prompt) by the time
    scoring starts, so the messages `LeafProver` renders are discarded — the
    class is used for its verification half only. `n` is always 1 here; the loop
    is kept so a misconfigured budget produces identical attempts rather than a
    silent IndexError.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def __call__(self, messages: list[Message], n: int) -> list[str]:
        self.calls += 1
        return [self.text] * n


def _one_shot_prover(text: str, model: str) -> LeafProverProtocol:
    """A LeafProver over `text`, with the cache off.

    `cache=None` is load-bearing: `AttemptCache` is the *leaf oracle's* record
    (bank pass rates, the `leaf_id` provenance guard in scripts/build_bank.py),
    and writing root proofs into it would corrupt an artifact that Phase-1
    calibration depends on.
    """
    from rlmath.leaf import LeafProver

    return LeafProver(client=_ReplayClient(text), model=model, cache=None)


def run_direct(
    goal: GoalSpec,
    *,
    root: RootClient,
    backend: LeanBackend,
    leaf: Any = None,          # unused: in this arm the root IS the prover
    budgets: Budgets,
) -> ArmOutcome:
    """Flat 1-shot: the root emits a whole proof; the kernel judges it."""
    from rlmath import sanitize
    from rlmath.leaf.prompts import extract_proof

    messages = direct_prompt(goal)
    completion = root.complete(messages)
    prompt_chars = sum(len(m["content"]) for m in messages)

    def out(status: Status, *, detail: str = "", score_elapsed_s: float = 0.0,
            reward: float = 0.0, **kw) -> ArmOutcome:
        return ArmOutcome(
            arm="direct", status=status, reward=reward, completion=completion.text,
            usage=completion.usage, prompt_chars=prompt_chars,
            root_elapsed_s=round(completion.elapsed_s, 4),
            score_elapsed_s=round(score_elapsed_s, 4), detail=detail,
            finish_reason=completion.finish_reason, **kw,
        )

    t0 = time.perf_counter()
    # Format first, and countably: ../rl lost whole cells to a model emitting its
    # own format, silently scored 0 (DIRECTION §6). `extract_proof` is pure, so
    # the prover below re-derives exactly this string.
    proof = extract_proof(completion.text)
    if proof is None:
        return out(
            Status.FORMAT_ERROR,
            detail="no proof-shaped content in the completion (no fenced Lean block, "
                   "no restated declaration, no bare tactic block)",
            score_elapsed_s=time.perf_counter() - t0,
        )

    # The stage-2 analog of `run_episode`: the policy's OWN text is scanned
    # before it reaches the kernel. Without it a `sorry`-bearing proof would come
    # back LEAF_FAILED (prover weakness) when it is really a reward hack
    # (SANITIZER_REJECTED) — the exact bucket collision §6 forbids. Same gate
    # function the harness uses; no policy is duplicated here.
    violations = sanitize.scan_source(proof)
    if violations:
        return out(
            Status.SANITIZER_REJECTED,
            detail="root proof: " + "; ".join(violations)[:400],
            score_elapsed_s=time.perf_counter() - t0,
        )

    # One completion is one attempt. Budgets are pinned rather than inherited so
    # a k>1 episode config cannot make the replay client hand the same proof to
    # the kernel repeatedly and report it as several attempts.
    direct_budgets = Budgets(
        max_lemmas=budgets.max_lemmas,
        leaf_attempts_per_lemma=1,
        max_total_leaf_attempts=1,
        verify_timeout_s=budgets.verify_timeout_s,
    )
    result = run_direct_close(
        goal, _one_shot_prover(completion.text, root.model), backend, direct_budgets
    )
    return out(
        result.status,
        reward=result.reward,
        detail=result.detail,
        score_elapsed_s=time.perf_counter() - t0,
        leaf_attempts_used=result.leaf_attempts_used,
        artifact=result.artifact,
        extra={"proof_chars": len(proof)},
    )


# ---------------------------------------------------------------------------
# Arm 2: decomp (isolated harness, single-shot)
# ---------------------------------------------------------------------------

def run_decomp(
    goal: GoalSpec,
    *,
    root: RootClient,
    backend: LeanBackend,
    leaf: Any,
    budgets: Budgets,
) -> ArmOutcome:
    """One single-shot decomposition episode (§5.6: one completion, no retries).

    The prompt is `envs.decomp_env.build_prompt` and the verdict is
    `envs.decomp_env.score_plan` — the identical pair the verifiers environment
    uses — so a zero-shot cell and a Phase-3 rollout differ in who calls them,
    not in what they measure.
    """
    if leaf is None:
        raise ValueError("the decomp arm needs a leaf prover (it dispatches lemmas)")

    messages = build_prompt(goal)
    completion = root.complete(messages)
    prompt_chars = sum(len(m["content"]) for m in messages)

    t0 = time.perf_counter()
    score = score_plan(
        goal, completion.text, backend=backend, leaf=leaf, budgets=budgets
    )
    info = score.info
    return ArmOutcome(
        arm="decomp",
        status=Status(info["status"]),
        reward=score.reward,
        completion=completion.text,
        usage=completion.usage,
        prompt_chars=prompt_chars,
        root_elapsed_s=round(completion.elapsed_s, 4),
        score_elapsed_s=round(time.perf_counter() - t0, 4),
        detail=info["detail"],
        plan_stats=info["plan_stats"],
        leaf_attempts_used=int(info["leaf_attempts_used"]),
        artifact=score.result.artifact,
        finish_reason=completion.finish_reason,
        extra={"n_lemma_outcomes": info["n_lemma_outcomes"]},
    )


Arm = Callable[..., ArmOutcome]

# The §5.5 arm list, as far as it is built. `flat_best_of_n` and
# `flat_cot_decomposition` land here next; the runner takes its --arm choices
# from this dict so a new arm needs no CLI change.
ARMS: dict[str, Arm] = {
    "direct": run_direct,
    "decomp": run_decomp,
}

# Arms that dispatch lemmas to the frozen leaf; the runner only builds a leaf
# client (and only requires --leaf-model) for these.
ARMS_NEEDING_LEAF = frozenset({"decomp"})


def run_arm(
    arm: str,
    goal: GoalSpec,
    *,
    root: RootClient,
    backend: LeanBackend,
    leaf: Any = None,
    budgets: Budgets,
) -> ArmOutcome:
    try:
        fn = ARMS[arm]
    except KeyError:
        raise KeyError(f"unknown arm {arm!r}; known: {sorted(ARMS)}") from None
    return fn(goal, root=root, backend=backend, leaf=leaf, budgets=budgets)


_SLUG = re.compile(r"[^a-z0-9]+")


def model_slug(model: str) -> str:
    """`qwen/qwen3-30b-a3b-instruct-2507` -> `qwen-qwen3-30b-a3b-instruct-2507`.

    Cell filenames embed the root model, and a `/` in a model id would silently
    create a directory (or fail); a stable, lowercase, filesystem-safe slug is
    also what keeps a resumed run pointing at the same file.
    """
    return _SLUG.sub("-", str(model).lower()).strip("-") or "unknown"


__all__ = [
    "ARMS",
    "ARMS_NEEDING_LEAF",
    "CHARS_PER_TOKEN",
    "DIRECT_SYSTEM",
    "DIRECT_USER",
    "ArmOutcome",
    "OpenAIRootClient",
    "RootClient",
    "RootCompletion",
    "Usage",
    "direct_prompt",
    "estimate_tokens",
    "make_root_client",
    "model_slug",
    "parse_extra_headers",
    "run_arm",
    "run_decomp",
    "run_direct",
    "status_for_exception",
    "usage_from_response",
]
