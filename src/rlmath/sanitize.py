"""Source sanitizer — the layer that makes the terminal reward unhackable.

DIRECTION.md §5.6 makes kernel-verified closure the *only* reward signal, so
every cheap way to make the kernel say "ok" without proving anything is a direct
attack on the objective. Under GRPO the policy does not need to *understand* the
hole to find it: it only needs the hole to correlate with reward once. So this
module is deliberately strict and deliberately dumb — a lexical scan plus an
axiom audit, no elaboration, no I/O, no heuristics that could be argued with.

Three independent gates, all cheap, all pure:

  1. `scan_source`            — banned tokens (sorry, axiom, native_decide, ...)
  2. `enforce_single_theorem` — the final artifact is exactly one theorem, named
  3. `parse_axiom_output` + `audit_axioms` — what the kernel *actually* trusted

Gate 3 is the backstop: 1 and 2 are lexical and can in principle be evaded
(see "Known limitations"), but the axiom audit reads Lean's own accounting of
the proof term. A `sorry` that slips past the scanner still shows up as
`sorryAx`; a `native_decide` still shows up as `Lean.ofReduceBool`.

Deliberate false positives (v1 accepts these; strictness is the right default
when the alternative is a silently hacked reward):

  - Occurrences inside **string literals** flag. `theorem t : P := by
    trace "sorry"` is rejected. Nobody needs that; the scanner does not parse
    Lean, and teaching it to would add a parser to the trust boundary.
  - Occurrences inside **comments** flag. Comments should have been stripped
    upstream (`core.types.normalize_statement` strips them for cache keys);
    a comment surviving into an artifact is itself anomalous.
  - A dot is a token boundary, so `Foo.sorry` flags. No Mathlib name ends in a
    component equal to a banned keyword.

What does *not* flag: identifier-embedded occurrences. `sorryFree`, `mysorry`,
`sorry_free`, `sorryAx` (as a bare word), `infer_instance`, `induction` (vs
`inductive`), `decide` (vs `native_decide`) are all clean — Lean identifier
characters (`\\w` plus `'`) on either side suppress the match.

Known limitations (documented, not solved in v1):

  - **Unicode homoglyphs.** `sоrry` with a Cyrillic `о` does not flag. Not
    solved because NFKC-folding Lean source would create false positives (Lean
    identifiers legitimately use `α`, `ℕ`, `₁`, and Mathlib is full of them),
    and because it is not actually exploitable: Lean's lexer is not homoglyph
    tolerant either, so the homoglyph spelling is not the `sorry` keyword and
    the snippet fails to elaborate. The gap is in the scanner, not the reward.
  - **`where` clauses.** Considered and excluded from the declaration-keyword
    set: `where` appears in legitimate term-mode structure syntax, and a
    `where`-bound auxiliary declaration cannot introduce an axiom (and cannot
    contain `sorry`/`partial` without tripping `scan_source`).
  - **Whole-file evasion via a hidden namespace** is caught by the axiom audit
    rather than lexically: renaming the artifact's declaration makes
    `#print axioms <name>` fail, which `audit_axiom_output` reports as a
    violation instead of a vacuous pass.
"""
from __future__ import annotations

import re

from .core.leancode import ALLOWED_AXIOMS

# Banned anywhere in submitted Lean source. Value = the one-line justification;
# it travels into the violation message and thence into EpisodeResult.detail,
# so an operator reading a `sanitizer_rejected` row knows why without grepping.
BANNED_TOKENS: dict[str, str] = {
    "sorry": "closes any goal — the canonical proof hole",
    "admit": "the `admit` tactic is `exact sorry` under another name",
    "axiom": "asserts an unproved proposition; §5.2's two-stage check never needs one",
    "native_decide": "trusts the compiler instead of the kernel (adds Lean.ofReduceBool)",
    "implemented_by": "swaps a declaration's compiled implementation — kernel/runtime divergence",
    "extern": "same divergence, via a foreign function",
    "unsafe": "bypasses termination and type-safety checking",
    "macro": "arbitrary syntax rewriting can make the source read differently than it elaborates",
    "macro_rules": "worse: extends *existing* syntax, so even unmodified-looking tactics can be reteached",
    "elab": "runs an arbitrary metaprogram at elaboration time",
    "notation": "silently rebinds symbols, so the stated theorem need not mean what it reads",
    "notation3": "Mathlib's variant of `notation`; identical hazard",
    "syntax": "declares new parser syntax — the front half of a macro/elab attack",
    "set_option": "submitters must not raise maxHeartbeats or disable kernel checks",
    "initialize": "runs arbitrary IO at import time",
    "builtin_initialize": "same, and not covered by the `initialize` token (underscore is an identifier char)",
    "opaque": "a constant with no definition — an axiom wearing a different keyword",
    "partial": "can hide nontermination in a def smuggled into the assembly",
    "#exit": "stops elaboration of the rest of the file: everything after it silently 'compiles'",
}

# Rejected anywhere in a *final artifact* (`enforce_single_theorem`), the one
# `theorem` with the expected name excepted. Mostly legal Lean that simply has
# no business in a composed proof: the artifact is
# `theorem <goal.name> : <prop> := by <body>` and nothing else (core.leancode.
# compose). `namespace`/`section` are here because they rename the declaration,
# which would point the axiom audit at a name that no longer exists.
DECLARATION_KEYWORDS: frozenset[str] = frozenset({
    # declarations proper
    "theorem", "lemma", "def", "abbrev", "example", "instance", "structure",
    "inductive", "class", "axiom", "opaque", "constant", "noncomputable", "mutual",
    # commands that declare, rename, or reprogram
    "attribute", "namespace", "section", "universe", "variable", "import",
    "macro", "macro_rules", "elab", "notation", "notation3", "syntax",
    "initialize", "builtin_initialize",
})

# Axioms that are not merely un-whitelisted but *diagnostic*: seeing one tells
# us which hack was attempted, so the message says so. Keyed by final component.
DENY_AXIOMS: dict[str, str] = {
    "sorryAx": "the proof contains a sorry",
    "ofReduceBool": "native_decide — trusts the compiler, not the kernel",
    "ofReduceNat": "native_decide — trusts the compiler, not the kernel",
    "trustCompiler": "native_decide — trusts the compiler, not the kernel",
}

_IDENT_CHAR = r"[\w']"  # Lean identifier body: unicode word chars plus the prime


def _bounded(tok: str) -> re.Pattern[str]:
    """Whole-token matcher. Boundaries are applied only on the ends that are
    identifier characters, so `#exit` still matches at the start of a line."""
    pat = re.escape(tok)
    if re.match(_IDENT_CHAR, tok[0]):
        pat = rf"(?<!{_IDENT_CHAR}){pat}"
    if re.match(_IDENT_CHAR, tok[-1]):
        pat = rf"{pat}(?!{_IDENT_CHAR})"
    return re.compile(pat)


_BANNED_RES = [(tok, why, _bounded(tok)) for tok, why in BANNED_TOKENS.items()]
_DECL_RE = re.compile(
    rf"(?<!{_IDENT_CHAR})("
    # longest-first, then alphabetical: a stable pattern across interpreter runs
    + "|".join(re.escape(k) for k in sorted(DECLARATION_KEYWORDS, key=lambda k: (-len(k), k)))
    + rf")(?!{_IDENT_CHAR})"
)
_NAME_AFTER = re.compile(r"[ \t]+([^\s:({\[]+)")


def _line(code: str, pos: int) -> int:
    return code.count("\n", 0, pos) + 1


def scan_source(code: str) -> list[str]:
    """Banned-token scan. Empty list = clean; anything else ⇒ SANITIZER_REJECTED.

    Applied to *every* model-authored string: lemma props, assembly blocks, leaf
    proofs, and the composed artifact (DIRECTION.md §5.6). One violation per
    distinct token, reported at its first occurrence and ordered by position, so
    the message stays readable when a completion is uniformly full of `sorry`.
    """
    hits = []
    for tok, why, rx in _BANNED_RES:
        m = rx.search(code)
        if m is not None:
            hits.append((m.start(), tok, why))
    hits.sort()
    return [f"line {_line(code, pos)}: banned token {tok!r} ({why})" for pos, tok, why in hits]


def enforce_single_theorem(code: str, expected_name: str) -> list[str]:
    """The final artifact must be exactly one theorem, named `expected_name`.

    Only for composed artifacts — lemma props and assembly blocks get
    `scan_source` alone, since they are fragments by construction. Two things
    are being prevented: (a) an auxiliary `def`/`instance` doing the real work
    (or defining the goal's own predicate to be trivially true), and (b) a
    second declaration that makes `#print axioms <expected_name>` audit
    something other than the theorem we scored.
    """
    found: list[tuple[int, str]] = []
    theorems: list[re.Match[str]] = []
    for m in _DECL_RE.finditer(code):
        kw = m.group(1)
        if kw == "theorem":
            theorems.append(m)
            continue
        found.append((
            m.start(),
            f"line {_line(code, m.start())}: declaration keyword {kw!r} — the artifact "
            f"must contain only the theorem {expected_name!r}",
        ))

    if not theorems:
        found.append((-1, f"no theorem declaration found (expected exactly one named {expected_name!r})"))
    else:
        if len(theorems) > 1:
            lines = ", ".join(str(_line(code, m.start())) for m in theorems)
            found.append((-1, f"expected exactly one theorem, found {len(theorems)} (lines {lines})"))
        for m in theorems:
            nm = _NAME_AFTER.match(code, m.end())
            name = nm.group(1) if nm else ""
            if name != expected_name:
                found.append((
                    m.start(),
                    f"line {_line(code, m.start())}: theorem name {name!r}, expected {expected_name!r}",
                ))

    found.sort(key=lambda t: t[0])
    return [msg for _, msg in found]


# `#print axioms foo` prints either
#   'foo' depends on axioms: [propext, Classical.choice, Quot.sound]
# or
#   'foo' does not depend on any axioms
# (format confirmed in research/lean-repl.md §5; the REPL delivers it as the
# `data` string of a single info-severity message, with no structured field —
# parsing this text is the only option). The list wraps across lines when long,
# quoting of the declaration name varies by Lean version, and the REPL may
# prefix position/severity info — so match on the phrases, never line structure.
_DEPENDS = re.compile(r"depends\s+on\s+axioms\s*:\s*")
_NO_AXIOMS = re.compile(r"does\s+not\s+depend\s+on\s+any\s+axioms|depends\s+on\s+no\s+axioms")
_SEP = re.compile(r"[,\s]+")


def parse_axiom_output(text: str) -> set[str]:
    """Parse `#print axioms` output into the set of axiom names it reports.

    Handles the bracketed list (including multiline wrapping), the no-axioms
    phrasing, fully-qualified names, several declarations reported in one blob
    (their axioms are unioned), and the unbracketed `...: a, b` variant.

    NOTE: an empty result is ambiguous — it means "no axioms" *or* "this text
    was not an axiom report at all" (unknown declaration, REPL error, `#exit`
    swallowing the command). Callers that treat empty as a pass are re-opening
    the hole this module exists to close; use `audit_axiom_output`, which
    distinguishes the two.
    """
    names: set[str] = set()
    for m in _DEPENDS.finditer(text):
        rest = text[m.end():]
        if rest.startswith("["):
            end = rest.find("]")
            body = rest[1:end] if end != -1 else rest[1:]  # unterminated: take what we have
        else:
            body = rest.split("\n", 1)[0]
        for raw in _SEP.split(body):
            tok = raw.strip().strip("'\"`,")
            if tok:
                names.add(tok)
    return names


def axiom_report_present(text: str) -> bool:
    """True iff `text` actually looks like `#print axioms` output."""
    return bool(_DEPENDS.search(text) or _NO_AXIOMS.search(text))


def audit_axioms(axioms: set[str]) -> list[str]:
    """Check reported axioms against `core.leancode.ALLOWED_AXIOMS`.

    Matching is on the **final name component** (`Classical.choice`,
    `_root_.Classical.choice`, and a bare `choice` all match the whitelist
    entry) because qualification varies with Lean version and REPL settings.
    That leniency costs nothing: a user-declared `MyNs.choice` would have needed
    an `axiom`/`opaque` declaration, which `scan_source` and
    `enforce_single_theorem` reject before the kernel ever sees it.

    Whitelist, not denylist — and that is load-bearing. `Lean.collectAxioms`
    (which backs `#print axioms`) does *not* collect axioms transitively, so a
    `native_decide` proof reports `Lean.ofReduceBool` without the
    `Lean.trustCompiler` it rests on (research/lean-repl.md §5). A denylist
    would have to enumerate every such hole; a whitelist rejects the whole
    unknown remainder by construction. `DENY_AXIOMS` only improves the message.
    """
    allowed = {a.rsplit(".", 1)[-1] for a in ALLOWED_AXIOMS}
    out = []
    for name in sorted(axioms):
        leaf = name.rsplit(".", 1)[-1]
        if leaf in allowed:
            continue
        why = DENY_AXIOMS.get(leaf)
        out.append(f"disallowed axiom: {name}" + (f" ({why})" if why else ""))
    return out


def audit_axiom_output(text: str) -> list[str]:
    """`parse_axiom_output` + `audit_axioms`, with the ambiguity closed.

    Prefer this at the call site: unrecognized output is a violation, not a
    pass. Otherwise any failure of the audit command itself (unknown
    declaration after a namespace rename, a REPL hiccup, `#exit`) reads as
    "depends on no axioms" and the artifact is scored VERIFIED unaudited.
    """
    if not axiom_report_present(text):
        snippet = " ".join(text.split())[:120]
        return [f"axiom audit output not recognized (refusing to pass unaudited): {snippet!r}"]
    return audit_axioms(parse_axiom_output(text))
