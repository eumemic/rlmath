"""Leaf-prover prompt templates and completion parsing.

The leaf prover is *frozen* (DIRECTION.md §5.3), so it is a fixed oracle whose
measured pass rate defines delegability (§5.4). Two consequences drive this
module:

  1. **The prompt must match what the model was trained on, verbatim.** A
     prover model's pass rate is prompt-sensitive; a paraphrased template
     silently moves the oracle, and every calibration number downstream
     (leaf bank pass rates, the flat-vs-harness comparison) shifts with it.
     Templates are therefore transcribed from primary sources and cited.
  2. **Parsing the completion is a first-order failure surface.** In ../rl a
     model emitting its own native format instead of the harness's fences
     silently zeroed whole eval cells (REPORT_NOTES.md, accommodation 3 —
     11/14 samples in one cell). The fix there, and the discipline here: be
     liberal in what shapes are accepted, but return `None` — never garbage —
     when nothing proof-shaped is found, so the failure is countable rather
     than a mysterious kernel error.

Templates are keyed by name and registered in `TEMPLATES`; `render(name, prop)`
returns OpenAI-style chat messages.
"""
from __future__ import annotations

import re
import textwrap
from collections.abc import Callable

Message = dict[str, str]
Renderer = Callable[[str], list[Message]]

# ---------------------------------------------------------------------------
# Statement skeleton
# ---------------------------------------------------------------------------

# Verbatim header of the `lean4` block in DeepSeek-Prover-V2's prompt (paper
# arXiv:2504.21801v2 Appendix A.1; identical on the HF card's Quick Start and
# reused verbatim by Goedel-Prover-V2). Both prover models were trained with
# exactly these five lines, so they stay byte-for-byte even though `import
# Aesop` is redundant under Mathlib and `set_option maxHeartbeats 0` is a
# token `rlmath.sanitize` bans in submitted source. That ban is not a conflict:
# `extract_proof` returns only the proof body (everything after `:=`), so no
# part of this skeleton can reach a composed artifact.
STATEMENT_HEADER = (
    "import Mathlib\n"
    "import Aesop\n"
    "\n"
    "set_option maxHeartbeats 0\n"
    "\n"
    "open BigOperators Real Nat Topology Rat"
)

# Fixed declaration name: the prompt must be a pure function of the statement
# or the cache key (which hashes the statement only) would not identify it.
LEAF_THEOREM_NAME = "leaf_goal"


def formal_statement(prop: str, *, name: str = LEAF_THEOREM_NAME, docstring: str | None = None) -> str:
    """The `lean4`-block payload: preamble + a theorem whose proof is `sorry`.

    The docstring line is optional and defaults to absent — generated goals
    (DIRECTION.md §5.4 families) have no natural-language statement, and
    inventing one would put non-reproducible text in the cache key's shadow.
    """
    doc = f"/-- {docstring} -/\n" if docstring else ""
    return f"{STATEMENT_HEADER}\n\n{doc}theorem {name} : {prop} := by\n  sorry"


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

# Verbatim, paper arXiv:2504.21801v2 Appendix A.1 ("Examples of Non-CoT and CoT
# Prompting for Proof Generation"), cross-checked against the HF Quick Start
# for `deepseek-ai/DeepSeek-Prover-V2-7B`. See research/models-datasets.md §1.
# Non-CoT = this; CoT = this plus the two trailing proof-plan sentences.
_DEEPSEEK_NON_COT = "Complete the following Lean 4 code:\n\n```lean4\n{}\n```"

# Verbatim continuation published as executable Python on the DeepSeek-Prover-V2
# HF card and copied unchanged onto the Goedel-Prover-V2 card (research/models-datasets.md §1–2).
_COT_SUFFIX = (
    "\n\nBefore producing the Lean 4 code to formally prove the given theorem, provide a detailed"
    " proof plan outlining the main proof steps and strategies.\nThe plan should highlight key"
    " ideas, intermediate lemmas, and proof structures that will guide the construction of the"
    " final formal proof."
)

_PLAIN_SYSTEM = "You are an expert in Lean 4 and Mathlib. You reply with Lean 4 code only."
_PLAIN_USER = (
    "Prove the following Lean 4 theorem. Mathlib is imported.\n\n"
    "```lean4\n{}\n```\n\n"
    "Reply with ONLY the completed Lean 4 code in a single ```lean4 block: the theorem with"
    " `sorry` replaced by a real proof. No explanation, no commentary."
)


def _deepseek_non_cot(prop: str) -> list[Message]:
    """DeepSeek-Prover-V2 non-CoT: the fast, high-throughput mode (§5.3's default)."""
    return [{"role": "user", "content": _DEEPSEEK_NON_COT.format(formal_statement(prop))}]


def _deepseek_cot(prop: str) -> list[Message]:
    """DeepSeek-Prover-V2 CoT: asks for a proof plan first. Needs a far larger
    `max_tokens` than non-CoT (the card generates 8192)."""
    return [{"role": "user", "content": _DEEPSEEK_NON_COT.format(formal_statement(prop)) + _COT_SUFFIX}]


def _goedel(prop: str) -> list[Message]:
    """Goedel-Prover-V2: the card publishes exactly DeepSeek's CoT template and
    no separate non-CoT variant, so this is a distinct *name* over identical
    text — the name is what selects the model's sampling budget upstream
    (card generates 32768) and what appears in the cache's sampling key."""
    return _deepseek_cot(prop)


def _plain(prop: str) -> list[Message]:
    """Fallback for a generic instruct model (no prover post-training).

    Used for the local smoke path (qwen3 via ollama, PHASE0_NOTES) and as the
    control when asking whether a result depends on the prover model at all.
    """
    return [
        {"role": "system", "content": _PLAIN_SYSTEM},
        {"role": "user", "content": _PLAIN_USER.format(formal_statement(prop))},
    ]


TEMPLATES: dict[str, Renderer] = {
    "deepseek-prover-v2-non-cot": _deepseek_non_cot,
    "deepseek-prover-v2-cot": _deepseek_cot,
    "goedel-prover-v2": _goedel,
    "plain": _plain,
}


def render(template: str, prop: str) -> list[Message]:
    """Chat messages for `prop` under the named template."""
    try:
        fn = TEMPLATES[template]
    except KeyError:
        raise KeyError(f"unknown leaf template {template!r}; known: {sorted(TEMPLATES)}") from None
    return fn(prop)


# ---------------------------------------------------------------------------
# Completion parsing
# ---------------------------------------------------------------------------

# Fenced block. The closing fence is optional (`\Z`) on purpose: hitting
# max_tokens mid-proof is the single most common malformed shape, and the
# truncated proof is a real attempt that should fail *at the kernel*, loudly,
# rather than vanish here as a parse failure.
_FENCE = re.compile(r"```([A-Za-z0-9_+.-]*)[ \t]*\r?\n(.*?)(?:\r?\n[ \t]*```|\Z)", re.DOTALL)

# A restated declaration, at the start of a line. Models routinely echo the
# whole skeleton (that is what the prompt asks for), so the common case is that
# the proof must be cut out of a full file.
_DECL = re.compile(r"^[ \t]*(?:theorem|lemma|example)\b", re.MULTILINE)

# First-token tactic vocabulary. A completion that is a bare tactic block (no
# `by`, no restated theorem) is wrapped in `by`; the alternative — passing
# tactics where `leancode.proof_check` expects a term — is a guaranteed
# elaboration error. Deliberately excludes `rfl`, which is a valid *term*.
_TACTICS = frozenset({
    "abel", "aesop", "all_goals", "any_goals", "apply", "assumption", "bound", "by_cases",
    "by_contra", "calc", "case", "cases", "cases'", "change", "congr", "constructor", "contrapose",
    "contrapose!", "conv", "convert", "decide", "delta", "exact", "exact?", "exfalso", "ext",
    "field_simp", "fin_cases", "first", "focus", "funext", "gcongr", "have", "induction",
    "induction'", "infer_instance", "interval_cases", "intro", "intros", "left", "let",
    "linarith", "linear_combination", "next", "nlinarith", "norm_cast", "norm_num",
    "obtain", "omega", "peel", "polyrith", "positivity", "push_cast", "push_neg", "rcases",
    "refine", "refine'", "repeat", "rewrite", "right", "rintro", "ring", "ring_nf", "rotate_left",
    "rw", "rwa", "set", "show", "simp", "simp_all", "simp_arith", "simpa", "specialize", "split",
    "split_ifs", "subst", "suffices", "symm", "tauto", "trans", "trivial", "try", "unfold", "use",
    "with_unfolding_all", "zify",
})

# Term-mode openers that are unambiguous enough to accept without a `by`.
_TERM_OPENERS = ("⟨", "(", "@", "fun ", "fun\n", "λ", "if ", "let ", "match ", "⦃")

_IDENT_TOKEN = re.compile(r"[^\s(),\[\]{}]+")
_QUALIFIED = re.compile(r"[A-Za-z_][A-Za-z0-9_.'!?₀-₉]*\.[A-Za-z0-9_.'!?₀-₉]+")
_SORRY_ONLY = re.compile(r"^(?:by\s+)?sorry$")


def extract_proof(model_output: str | None) -> str | None:
    """Pull a proof body out of a raw model completion.

    Returns a Lean *term or `by` block* — exactly what
    `core.leancode.proof_check` splices after `:=` — never including the `:=`
    itself, and never a restated theorem header.

    Accepted shapes, in preference order:
      1. a ```lean4 / ```lean fenced block (last one wins; CoT models emit the
         final answer last), closed or truncated;
      2. any other fenced block;
      3. the bare text, with a restated `theorem/lemma/example ... := <proof>`
         cut down to `<proof>`, trailing prose dropped by indentation;
      4. a bare `by ...` block or bare tactic block (wrapped in `by`).

    Returns `None` for: empty input, prose with no proof-shaped content, and a
    body that is only `sorry` (the model echoed the prompt skeleton — that is a
    non-attempt, and recording it as a proof would burn a kernel check and
    inflate the attempt count).

    Liberality is graded by evidence. Inside a fence, or after a restated
    declaration, the model has told us "this is Lean" and an unrecognized body
    is passed through as a term (`dvd_add h1 h2`, `rfl` — Mathlib lemma names
    are not all dotted, and no keyword list would cover them). In bare text
    with neither marker we are guessing, so only unambiguous shapes are
    accepted and an apology comes back as None.
    """
    if not model_output or not model_output.strip():
        return None
    # Normalize line endings once: a stray \r inside a proof is legal Lean but
    # poisons every downstream string comparison (cache equality, the
    # restatement detector, trajectory-similarity metrics).
    model_output = model_output.replace("\r\n", "\n").replace("\r", "\n")

    matches = list(_FENCE.finditer(model_output))
    lean_blocks = [m.group(2) for m in matches if m.group(1).lower().startswith("lean")]
    other_blocks = [m.group(2) for m in matches if not m.group(1).lower().startswith("lean")]

    # (region, strict). A ```lean4 tag is the model asserting "this is Lean";
    # an untagged or ```text block is usually a CoT plan, so it is held to the
    # same bar as bare prose unless it contains a declaration.
    candidates: list[tuple[str, bool]] = [(b, False) for b in reversed(lean_blocks)]
    candidates += [(b, True) for b in reversed(other_blocks)]
    # Bare fallback last, and strict: prose outside a fence is the likeliest
    # source of garbage, so it only gets a look when no fence produced anything.
    candidates.append((_FENCE.sub("\n", model_output) if matches else model_output, True))

    for cand, strict in candidates:
        proof = _proof_from_code(cand, strict=strict)
        if proof:
            return proof
    return None


def _proof_from_code(code: str, *, strict: bool) -> str | None:
    """Extract the proof body from one candidate region of Lean-ish text."""
    if not code or not code.strip():
        return None

    decls = list(_DECL.finditer(code))
    if decls:
        strict = False  # a restated declaration is evidence enough that this is Lean
        # Last declaration = the goal itself; anything before it is a helper
        # lemma the model invented. Helpers are dropped deliberately: the
        # composed artifact must be a single theorem (sanitize.enforce_single_theorem),
        # so a proof that depends on one cannot be used and must fail loudly.
        start = code.find(":=", decls[-1].end())
        if start == -1:
            return None
        body = _clean_after_assign(code[start + 2:])
    else:
        body = textwrap.dedent(code).strip("\n").rstrip()

    return _as_proof(body, strict=strict)


def _clean_after_assign(text: str) -> str:
    """Take the proof that follows `:=`, dropping trailing non-Lean prose.

    Layout is the only signal available: a proof body either continues on the
    `:=` line and is indented afterwards, or starts on the next line. Either
    way, a line at column 0 after the body has begun ends it — which is exactly
    what separates `  nlinarith` from `This completes the proof.`.
    """
    lines = text.split("\n")
    head, rest = lines[0], lines[1:]

    if not head.strip():
        i = 0
        while i < len(rest) and not rest[i].strip():
            i += 1
        if i == len(rest):
            return ""
        head, rest = rest[i], rest[i + 1:]
        base = len(head) - len(head.lstrip())
    else:
        base = 0

    out = [head]
    for ln in rest:
        if not ln.strip():
            out.append(ln)
            continue
        indent = len(ln) - len(ln.lstrip())
        if indent > base:
            out.append(ln)
        else:
            break

    first = out[0].strip()
    tail = textwrap.dedent("\n".join(out[1:])).strip("\n").rstrip()
    if not first:
        return tail
    if not tail:
        return first
    return first + "\n" + textwrap.indent(tail, "  ")


def _as_proof(text: str, *, strict: bool) -> str | None:
    """Classify a cleaned body as a `by` block, a tactic block, or a term.

    This is the "liberal but not credulous" gate: under `strict` (bare text, no
    fence, no declaration) unrecognized content — an apology, a plan paragraph,
    an English sentence — returns None so the caller can count a format failure
    instead of shipping prose to the kernel.
    """
    t = text.strip("\n").rstrip()
    if t[:1] in (" ", "\t"):
        t = textwrap.dedent(t).strip("\n").rstrip()
    if not t.strip():
        return None
    if _SORRY_ONLY.match(" ".join(t.split())):
        return None  # the echoed skeleton: a non-attempt, not a failed proof

    if t.startswith(":="):
        return _as_proof(_clean_after_assign(t[2:]), strict=strict)

    if re.match(r"by\b", t):
        return t

    first_tok = _IDENT_TOKEN.match(t)
    first = first_tok.group(0) if first_tok else ""
    if first in _TACTICS or first.rstrip("!?") in _TACTICS or t.startswith("·"):
        return "by\n" + textwrap.indent(t, "  ")
    if t.startswith(_TERM_OPENERS) or _QUALIFIED.fullmatch(first):
        return t
    return None if strict else t
