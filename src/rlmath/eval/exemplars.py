"""Few-shot worked exemplars for the Phase-2 arms (DIRECTION.md §5.5, rung 1.5).

The escalation ladder's rung 1.5: *"few-shot exemplars in the root prompt — one
complete worked decomposition (statements + assembly) as inference-time context;
none of OPD's symmetry/attribution costs since it is trivially matched across
arms and roots."* Motivated by the 2026-08-12 smoke (OVERNIGHT.md): 12/12
zero-shot decomp failures were `plan_invalid` at **stage 1** — the root spoke the
wire format and emitted well-formed lemma statements, and the *assembly* failed.
That localizes the gap to a missing affordance (what a working assembly block
looks like), which is exactly what a worked example supplies.

The exemplar is inference-time context only. Nothing here trains, warms up, or
distills; there is no gradient and no teacher completion. The two costs that
made warm-up a scientific decision (§5.5 Phase-3 cold start) are therefore both
paid in full here:

**Symmetry.** One `GeneratedProblem` produces *both* arms' exemplars, and they
share their entire question half (`envs.decomp_env.user_message` renders it for
both). The arms differ in exactly one place — the reply:

    decomp  ->  the problem's ORACLE PLAN in the exact wire format
                (`#lemma`/`#assembly`/`#end`). The oracle plan *is* a perfect
                worked decomposition; nothing is invented here.
    direct  ->  the composed oracle artifact (`core.leancode.compose` with the
                generator's witness proofs) as one complete fenced Lean proof.

Neither is a hint the other lacks: they are the same solution rendered into the
two arms' respective action spaces, so a few-shot cell keeps the "matched
effort" property the Phase-2 gate rests on (`arms.py`, DIRECT_SYSTEM comment).

Matched in *content*, not in tokens, and the difference is measured rather than
assumed: at k=2 the bridge-chain example is ~1.0k chars as a plan and ~3.3k as a
proof (case_tree: ~0.8k / ~1.3k), because a whole proof is simply longer than the
plan it composes — the same asymmetry the arms themselves have. Every row carries
the exemplar's `chars` and the prompt's own `prompt_chars`/`usage`, so
compute-matching arguments can be made from the numbers instead of the intent.

**Attribution.** The content comes from the generator's own oracle, not from a
frontier teacher, so nothing a root does with it can be teacher priors surviving
into the measurement.

Source hygiene
--------------
`load_exemplar_problem` generates a FRESH problem through
`rlmath.families.REGISTRY` at a dedicated seed (999 by default). It never reads
`data/families/*.jsonl` or any other materialized dataset — an exemplar lifted
out of an eval set would turn the cell into a recall measurement. The seed is
dedicated rather than merely "different" so that a dataset regenerated at some
future seed cannot silently collide; the runner
(`scripts/run_zeroshot.py::assert_exemplar_is_not_an_eval_problem`) closes the
remaining hole by refusing, loudly, an exemplar whose goal proposition matches
any problem in the cell.

Sanitizer-clean
---------------
Every rendered exemplar is scanned with `sanitize.scan_source` and a violation
raises. The worked reply is the thing a root is most likely to imitate verbatim,
so a banned token in it would be an instruction to hack the reward. This is also
why the direct exemplar does **not** reproduce the arm's `sorry`-skeleton
presentation of the goal (`arms.DIRECT_USER`): the skeleton contains `sorry`,
and a worked example is not the place for it. The real user turn still carries
the skeleton, unchanged — the exemplar shows the completed theorem, which pins
the same declaration and proposition anyway.

Determinism: `build_exemplar` is a pure function of `(problem, arm)`, and the
problem is a pure function of `(family, k, seed)` — so a few-shot cell is
reproducible from its recorded provenance alone.
"""
from __future__ import annotations

from rlmath import sanitize
from rlmath.core.leancode import compose
from rlmath.core.types import DecompositionPlan
from rlmath.envs.decomp_env import user_message
from rlmath.families import REGISTRY
from rlmath.families.types import GeneratedProblem

# k=2 is the smallest legal size for every family and the rung-1.5 diagnostic's
# operating point ("if qwen few-shot assembles at k=2, the cold-start problem was
# a prompt gap"). It deliberately does NOT track the cell's k: an exemplar at
# matched k would grow with the size axis (a k=8 bridge-chain proof is ~10.8k
# chars) and would eat the very window §5.4(e)'s beyond-window tier is built to
# stress — the worked example would then be *causing* the feasibility failures it
# is supposed to be measured against. `--exemplar-k` exists for the ablation.
# Seed 999 is reserved for exemplars: no dataset in data/families is materialized
# at it, and `scripts/gen_families.py` runs are seeded from the 42-family.
# Changing either default changes what every few-shot cell saw, so both are
# recorded on every row.
DEFAULT_EXEMPLAR_K = 2
DEFAULT_EXEMPLAR_SEED = 999

# Identical for both arms, on purpose: any framing that differed per arm would be
# an asymmetry in prompt effort, which is precisely what the Phase-2 comparison
# cannot afford. It states what the example is and what it is not; it teaches no
# proof strategy beyond the example itself.
EXEMPLAR_INTRO = (
    "Worked example. Below is a DIFFERENT goal from the same task family, "
    "together with a correct reply to it. It shows the required reply shape and "
    "nothing more: none of its statements, names or facts exist in the goal you "
    "are asked about afterwards."
)

_GOAL_LABEL = "Example goal:"
_REPLY_LABEL = "Correct reply:"


# ---------------------------------------------------------------------------
# The problem an exemplar is built from
# ---------------------------------------------------------------------------

def load_exemplar_problem(
    family: str,
    k: int = DEFAULT_EXEMPLAR_K,
    seed: int = DEFAULT_EXEMPLAR_SEED,
) -> GeneratedProblem:
    """Generate the exemplar problem fresh, through the family REGISTRY.

    NOT a dataset read. `data/families/<family>/k<k>.jsonl` is the eval material;
    drawing the worked example from it would put an eval item in the prompt and
    make the cell measure recall. This function touches no file: it calls the
    same generator `scripts/gen_families.py` calls, at a seed reserved for
    exemplars, and the result is deterministic in `(family, k, seed)`.

    The problem is self-certifying by the FAMILIES.md contract (oracle plan +
    kernel-checkable witness for every leaf), which is what makes it usable as a
    worked answer with no model and no kernel in the loop here. Validity itself
    is the family's contract, enforced by `families.validate` at materialization
    time and re-checked live by the integration test in tests/test_exemplars.py.
    """
    try:
        generate = REGISTRY[family]
    except KeyError:
        raise ValueError(
            f"unknown family {family!r}; known: {sorted(REGISTRY)}"
        ) from None
    problems = generate(k=k, seed=seed, n=1)
    if not problems:
        raise ValueError(f"{family}: generator returned no problem for k={k}, seed={seed}")
    problem = problems[0]
    # Cheap identity guard: a generator that ignored k or seed would produce an
    # exemplar whose recorded provenance is a lie, and provenance is the only
    # thing that makes a few-shot cell reproducible.
    if (problem.family, problem.k, problem.seed) != (family, k, seed):
        raise ValueError(
            f"{family}: generator returned {problem.family}/k{problem.k}/s{problem.seed} "
            f"for a request of {family}/k{k}/s{seed}"
        )
    return problem


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_plan(plan: DecompositionPlan) -> str:
    """A `DecompositionPlan` in the exact wire format (`core.plan_format`).

    The inverse of `parse_plan`, and tested as such: an exemplar that does not
    parse back into the plan it was rendered from would be teaching a format the
    scorer rejects. The two structural preconditions the wire format imposes are
    checked loudly rather than silently truncating the example — `parse_plan`
    stops at `#end` and reads one lemma per line, so a multi-line prop or a
    `#`-leading assembly line would produce a *valid-looking* but wrong example.
    """
    lines: list[str] = []
    for lemma in plan.lemmas:
        if "\n" in lemma.prop:
            raise ValueError(f"lemma {lemma.name!r}: prop must be one line for the wire format")
        lines.append(f"#lemma {lemma.name} : {lemma.prop}")
    lines.append("#assembly")
    for line in plan.assembly.splitlines():
        if line.strip().startswith("#"):
            raise ValueError(f"assembly line would be read as a marker: {line!r}")
        lines.append(line)
    lines.append("#end")
    return "\n".join(lines)


def _question_half(problem: GeneratedProblem) -> str:
    """How the goal is presented. Shared by both arms — the symmetry anchor.

    `envs.decomp_env.user_message` is the renderer, read-only: one rendering of
    "here is a goal", so the two arms' exemplars cannot drift apart in how much
    of the task they restate.
    """
    return f"{_GOAL_LABEL}\n\n{user_message(problem.goal).rstrip()}"


def _decomp_reply(problem: GeneratedProblem) -> str:
    return render_plan(problem.oracle_plan)


def _direct_reply(problem: GeneratedProblem) -> str:
    """The matched flat rendering: the whole composed artifact in one fence.

    `core.leancode.compose` is the same function the harness uses to build the
    artifact it sends to the kernel, so the worked flat proof is literally the
    decomposition's own composition — the two arms see one solution, twice.
    """
    artifact = compose(problem.goal, problem.oracle_plan, problem.witness_proofs())
    return f"```lean4\n{artifact}\n```"


_REPLIES = {
    "decomp": _decomp_reply,
    "direct": _direct_reply,
}


def build_exemplar(problem: GeneratedProblem, arm: str) -> str:
    """The worked-example block for `arm`, built from `problem`. Deterministic.

    An arm with no renderer here is a loud `KeyError`, never a silent zero-shot
    fallback: a few-shot cell whose arm quietly got no example would break the
    matched-effort property while still being labelled few-shot in its filename
    and rows. Adding an arm to `arms.ARMS` therefore forces an explicit decision
    about its matched exemplar.
    """
    try:
        reply = _REPLIES[arm]
    except KeyError:
        raise KeyError(
            f"no exemplar renderer for arm {arm!r}; known: {sorted(_REPLIES)}"
        ) from None
    text = "\n\n".join([
        EXEMPLAR_INTRO,
        _question_half(problem),
        f"{_REPLY_LABEL}\n\n{reply(problem)}",
    ])
    violations = sanitize.scan_source(text)
    if violations:
        # Unreachable for a valid family (a witness carrying `sorry` would have
        # failed V2 at materialization). Loud anyway: the worked reply is the
        # text a root is most likely to copy verbatim.
        raise ValueError(
            f"exemplar for {problem.id} ({arm}) is not sanitizer-clean: "
            + "; ".join(violations)[:400]
        )
    return text


def exemplar_provenance(problem: GeneratedProblem, arm: str, text: str) -> dict:
    """What a row must carry to make a few-shot cell reproducible.

    `(family, k, seed)` regenerates the problem; `goal_statement_key` is the
    contamination check's own key, so a later audit can re-run it against any
    dataset without regenerating anything.
    """
    from rlmath.core.types import statement_key

    return {
        "arm": arm,
        "family": problem.family,
        "k": problem.k,
        "seed": problem.seed,
        "problem_id": problem.id,
        "goal_statement_key": statement_key(problem.goal.prop),
        "goal_name": problem.goal.name,
        "chars": len(text),
    }


__all__ = [
    "DEFAULT_EXEMPLAR_K",
    "DEFAULT_EXEMPLAR_SEED",
    "EXEMPLAR_INTRO",
    "build_exemplar",
    "exemplar_provenance",
    "load_exemplar_problem",
    "render_plan",
]
