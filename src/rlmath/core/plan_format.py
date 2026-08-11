"""Wire format for single-shot decomposition completions (DIRECTION.md §5.1).

Line-oriented and deliberately rigid. Format compliance is a first-order
failure surface — in ../rl, unparsed model output silently zeroed whole eval
cells until a parser patch (REPORT_NOTES.md, accommodation 3). Here the
failure must be loud (Status.FORMAT_ERROR) and *measured*, never silent.

Grammar (chatter allowed before the first marker and after #end, strict inside):

    #lemma <name> : <prop>        0..N lines, names unique valid identifiers
    #assembly                     required, exactly once, after all lemmas
    <tactic lines>                verbatim until #end
    #end                          required

Zero #lemma lines = a direct-close plan: the assembly must prove the goal outright.
"""
from __future__ import annotations

import re

from .leancode import RESERVED_NAMES
from .types import DecompositionPlan, LemmaSpec

MAX_LEMMAS_HARD = 64          # parser cap; Budgets.max_lemmas enforces the real limit
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_']*$")
_LEMMA_LINE = re.compile(r"^#lemma\s+(\S+)\s*:\s*(.+?)\s*$")


class PlanFormatError(ValueError):
    """Completion did not parse; message says why (it lands in EpisodeResult.detail)."""


def parse_plan(text: str) -> DecompositionPlan:
    lines = text.splitlines()
    lemmas: list[LemmaSpec] = []
    assembly: list[str] = []
    seen: set[str] = set()
    state = "preamble"  # -> lemmas -> assembly -> done

    for line in lines:
        stripped = line.strip()
        if state == "preamble":
            if not stripped.startswith("#"):
                continue  # model chatter before the first marker is tolerated
            state = "lemmas"
            # fall through to marker handling
        if state == "done":
            break  # everything after #end is ignored

        if state == "lemmas":
            if not stripped:
                continue
            if stripped == "#assembly":
                state = "assembly"
                continue
            m = _LEMMA_LINE.match(stripped)
            if not m:
                raise PlanFormatError(f"expected '#lemma <name> : <prop>' or '#assembly', got: {stripped!r}")
            name, prop = m.group(1), m.group(2)
            if not _NAME.match(name):
                raise PlanFormatError(f"invalid lemma name: {name!r}")
            if name in RESERVED_NAMES or name.startswith("_"):
                raise PlanFormatError(f"reserved lemma name: {name!r}")
            if name in seen:
                raise PlanFormatError(f"duplicate lemma name: {name!r}")
            if len(lemmas) >= MAX_LEMMAS_HARD:
                raise PlanFormatError(f"more than {MAX_LEMMAS_HARD} lemmas")
            seen.add(name)
            lemmas.append(LemmaSpec(name=name, prop=prop))
        elif state == "assembly":
            if stripped == "#end":
                state = "done"
                continue
            if stripped.startswith("#lemma"):
                raise PlanFormatError("#lemma after #assembly")
            assembly.append(line)

    if state in ("preamble",):
        raise PlanFormatError("no plan markers found in completion")
    if state == "lemmas":
        raise PlanFormatError("missing #assembly section")
    if state == "assembly":
        raise PlanFormatError("missing #end")
    body = "\n".join(assembly).strip("\n")
    if not body.strip():
        raise PlanFormatError("empty assembly")
    return DecompositionPlan(lemmas=lemmas, assembly=body)
