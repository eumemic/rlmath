"""The frozen leaf prover: statement in, kernel-checked proof out.

DIRECTION.md §5.3 fixes the leaf as a *frozen* model, and §5.4 makes its
measured pass rate the delegability oracle the root is calibrated against.
Everything here follows from that: the adapter must be cheap to call repeatedly
(cache), honest about what it produced (attempt records with separated
verdicts), and swappable without touching callers (the client is injected).

Dependency injection, not a hard-wired SDK: `client` is any
`callable(messages, n) -> list[str]`. The unit tests pass a stub, the local
smoke path passes ollama, a rented GPU passes vLLM — all through
`from_openai`, since both speak the OpenAI chat API. This is the same narrow
seam that let ../rl run one runner over two model backends.

Not done here, on purpose: **sanitization**. `prove` reports what the kernel
says (ok and zero sorries) and nothing more. The banned-token scan and axiom
audit belong to the harness, which owns the composed artifact
(`rlmath.sanitize`, DIRECTION.md §5.6); a leaf proof that passes the kernel via
`native_decide` must still be rejected upstream.
"""
from __future__ import annotations

from typing import Any, Protocol

from ..core.backend import LeanBackend
from ..core.leancode import proof_check
from ..core.types import AttemptRecord, statement_key
from .cache import AttemptCache
from .prompts import TEMPLATES, Message, extract_proof, render

DEFAULT_TEMPLATE = "deepseek-prover-v2-non-cot"
# Prover defaults. temperature > 0 is not optional: pass@k over k identical
# greedy samples is pass@1 with k times the bill.
DEFAULT_TEMPERATURE = 1.0
DEFAULT_MAX_TOKENS = 2048  # non-CoT proofs are short; CoT templates need ~8-32k


class LeafClient(Protocol):
    """Any callable that turns chat messages into `n` raw completions."""

    def __call__(self, messages: list[Message], n: int) -> list[str]: ...


class AttemptList(list):
    """The attempt log `prove` returns — a plain list, plus `int()` = its length.

    Compatibility, not cleverness. `harness/episode._leaf_result` and
    `scripts/build_bank._single_result` were written against a
    `(proof, attempts_spent)` pair and do `int(res[1])` on any 2-tuple, which
    raises on a list. The number they want *is* the number of attempts spent,
    so making the log convert to its own length lets both contracts hold at
    once instead of failing at the first live run (unit tests on either side
    use their own stub leaves and would not have caught it). Remove once those
    two call sites take a `len()` of a sequence.
    """

    def __int__(self) -> int:
        return len(self)

    def __index__(self) -> int:
        return len(self)


class LeafProver:
    """Frozen leaf prover behind an attempt cache.

    `generate` produces proof candidates; `prove` runs them past the kernel.
    They are split because the leaf bank (§5.4) wants attempts in bulk before
    verification, while an episode wants first-success-and-stop.
    """

    def __init__(
        self,
        client: LeafClient,
        model: str,
        template: str = DEFAULT_TEMPLATE,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        cache: AttemptCache | None = None,
    ) -> None:
        if template not in TEMPLATES:
            # Fail at construction, not at the first generation an hour into a run.
            raise KeyError(f"unknown leaf template {template!r}; known: {sorted(TEMPLATES)}")
        self.client = client
        self.model = model
        self.template = template
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.cache = cache
        # Instrumentation, not bookkeeping: DIRECTION.md §3.3 objection 6 says
        # measure the format-failure rate from day one, and §5.6's caching claim
        # is only checkable if hits are counted.
        self.stats: dict[str, int] = {"cache_hits": 0, "generated": 0, "unparsed": 0, "checked": 0}

    # -- identity ------------------------------------------------------------

    @property
    def sampling_key(self) -> str:
        """Cache dimension for everything that changes the sampled distribution.

        Model is a separate column; the template is in here because two
        templates over the same statement are two different questions.
        """
        return f"{self.template}|T={self.temperature:g}|M={self.max_tokens}"

    # -- generation ----------------------------------------------------------

    def generate(self, prop: str, n: int) -> list[str]:
        """Up to `n` parsed proof candidates for `prop`, cache first.

        Fewer than `n` may come back: a completion that does not parse is a
        *failed* attempt, kept in the cache as an empty proof and never
        regenerated. Regenerating it would quietly raise the effective k and
        make pass@k denominators lie — the ../rl accommodation-3 lesson
        (format failures must be counted, not papered over).
        """
        return [proof for _, proof, _ in self._attempts(prop, n)]

    def _attempts(self, prop: str, n: int) -> list[tuple[int, str, bool | None]]:
        """(index, proof, known verdict) for usable attempts, ascending by index."""
        key = statement_key(prop)
        have: dict[int, tuple[str, bool | None]] = {}
        if self.cache is not None:
            for rec in self.cache.get_attempts(key, self.model, self.sampling_key):
                if rec.index < n:
                    have[rec.index] = (rec.proof, rec.verified)
            self.stats["cache_hits"] += len(have)

        missing = [i for i in range(n) if i not in have]
        if missing:
            outputs = self.client(render(self.template, prop), len(missing))
            self.stats["generated"] += len(outputs)
            for idx, raw in zip(missing, outputs):
                proof = extract_proof(raw) or ""
                verified: bool | None = None
                if not proof:
                    self.stats["unparsed"] += 1
                    verified = False  # an empty proof cannot pass; do not re-check it
                have[idx] = (proof, verified)
                if self.cache is not None:
                    self.cache.put_attempt(key, self.model, self.sampling_key, idx, proof, verified)

        return [(i, have[i][0], have[i][1]) for i in sorted(have) if have[i][0]]

    # -- verification --------------------------------------------------------

    def prove(
        self,
        prop: str,
        k: int,
        backend: LeanBackend,
        early_stop: bool = True,
        *,
        timeout_s: float = 120.0,
    ) -> tuple[str | None, AttemptList]:
        """Kernel-check up to `k` attempts; return the first proof that checks.

        Success is `ok and sorries == 0` — `VerifyResult.ok` alone is not
        enough, since the backend is deliberately sorry-policy-free
        (core/types.py) and a `sorry`-containing proof compiles cleanly.

        Verdicts are written back to the cache, so a re-run of the same episode
        (a GRPO group repeating a statement, a resumed bank build) does no
        kernel work at all. The returned records are the audit trail: one per
        attempt actually considered, with `verified` never left ambiguous.
        """
        key = statement_key(prop)
        records = AttemptList()
        winner: str | None = None

        for idx, proof, verdict in self._attempts(prop, k):
            if verdict is None:
                res = backend.check(proof_check(prop, proof), timeout_s=timeout_s)
                verdict = bool(res.ok and res.sorries == 0)
                self.stats["checked"] += 1
                if self.cache is not None:
                    self.cache.mark_verified(key, self.model, self.sampling_key, idx, verdict)
            records.append(
                AttemptRecord(
                    statement_key=key, model=self.model, index=idx, proof=proof, verified=verdict
                )
            )
            if verdict and winner is None:
                winner = proof
                if early_stop:
                    break

        return winner, records

    # -- construction --------------------------------------------------------

    @classmethod
    def from_openai(
        cls,
        base_url: str,
        api_key: str,
        model: str,
        *,
        template: str = DEFAULT_TEMPLATE,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        cache: AttemptCache | None = None,
        timeout_s: float = 1800.0,
        extra_body: dict[str, Any] | None = None,
    ) -> LeafProver:
        """Build a prover over any OpenAI-compatible server (vLLM, ollama).

        `base_url` is the `/v1` root — `http://localhost:11434/v1` for ollama,
        `http://<host>:8000/v1` for vLLM. `api_key` is ignored by both but the
        SDK requires a non-empty string (../rl passed the literal "ollama").
        The import is local so `import rlmath.leaf` stays free of the SDK and
        the unit suite never touches it.
        """
        import openai

        oai = openai.OpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s)
        client = OpenAIChatClient(
            oai, model, temperature=temperature, max_tokens=max_tokens, extra_body=extra_body
        )
        return cls(
            client=client,
            model=model,
            template=template,
            temperature=temperature,
            max_tokens=max_tokens,
            cache=cache,
        )


class OpenAIChatClient:
    """`LeafClient` over an OpenAI-compatible chat endpoint.

    Handles the one portability wart that matters: **ollama ignores `n`** and
    returns a single choice, while vLLM honours it. Rather than branching on
    the server, keep requesting until `n` completions have accumulated — one
    batched call on vLLM, `n` serial calls on ollama, no configuration.
    """

    def __init__(
        self,
        oai: Any,
        model: str,
        *,
        temperature: float,
        max_tokens: int,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self.oai = oai
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.extra_body = dict(extra_body or {})

    def __call__(self, messages: list[Message], n: int) -> list[str]:
        out: list[str] = []
        while len(out) < n:
            want = n - len(out)
            kwargs: dict[str, Any] = dict(
                model=self.model,
                messages=messages,
                n=want,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            if self.extra_body:
                kwargs["extra_body"] = self.extra_body
            resp = self.oai.chat.completions.create(**kwargs)
            got = [(c.message.content or "") for c in (resp.choices or [])]
            if not got:
                break  # server returned nothing: report short rather than spin
            out.extend(got[:want])
        return out
