"""Family A — bridge chains: prove `R(a₀, a_k)` through k hidden intermediates.

Schema (v1, "monomial ladder over ℝ")
------------------------------------
Every problem is a chain `a₀ ≤ a₁ ≤ … ≤ a_k` of real terms

    aᵢ  =  cᵢ * x ^ pᵢ * y ^ qᵢ * z ^ rᵢ + dᵢ           cᵢ ∈ [2,9], dᵢ ∈ [1,9]

under the shared side conditions `3 ≤ x`, `3 ≤ y`, `3 ≤ z`. One step multiplies the
monomial by `v ^ δ` for a randomly chosen variable `v ∈ {x,y,z}` and `δ ∈ {1,2}`, and
*resamples* the coefficient and the additive offset. Exponents start at `(1,1,1)`.

    goal    ∀ x y z : ℝ, 3 ≤ x → 3 ≤ y → 3 ≤ z → a₀ ≤ a_k
    hᵢ      ∀ x y z : ℝ, 3 ≤ x → 3 ≤ y → 3 ≤ z → aᵢ₋₁ ≤ aᵢ            (i = 1..k)
    assembly    intro x y z hx hy hz
                exact le_trans (h1 x y z hx hy hz) (le_trans (h2 …) … )

Only `a₀` and `a_k` occur in the goal; `a₁ … a_{k-1}` — the coefficient, the offset and
the exponent triple of every intermediate — are exactly what a policy has to invent.

**Step form, not cumulative form.** The alternative plan shape `hᵢ : R(a₀, aᵢ)` was
rejected on two counts, both structural rather than aesthetic: (1) `h_k` *is* the goal,
so the last lemma is a restatement — it fails V6 unless exempted, and a policy that
emits it has decomposed nothing; (2) the witness for a cumulative `hᵢ` has to redo the
whole prefix, so leaf difficulty grows linearly in i and per-node flatness (the validity
metric for the entire size axis, DIRECTION §5.4a) is lost by construction. Step form
gives k leaves that are pairwise interchangeable in difficulty, and transitivity — the
one thing the assembly is allowed to know — is what glues them.

Why the step is sound and why the witness is a two-liner
--------------------------------------------------------
With `M = x^p y^q z^r ≥ 1` and `v ≥ 3`, the step `c₁M + d₁ ≤ c₂ (v^δ M) + d₂` follows
from `v^δ M ≥ 3^δ M` by *linear* reasoning over the two monomial atoms, provided

    c₂ · 3^δ − c₁  ≥  max(0, d₁ − d₂)                            (SAMPLING CONSTRAINT)

which the sampler enforces by rejection (see `_sample_chain`; measured rejection rate is
reported in `meta["resamples"]`). Everything else in the witness is the `1 ≤ M` scaffold.

Empirical findings that shaped this schema (all measured on the local ReplPool,
Mathlib @ lean 4.34.0-rc1; kill-lists are the V0/V5 battery = simp, aesop, norm_num,
omega, decide, linarith, positivity):

* `n ∣ n * (n+4)`-style **divisibility steps with symbolic multipliers die instantly**
  (`simp`, `aesop`, `norm_num` all close `∀ n : ℕ, (n^2+3n+2) ∣ (n^2+3n+2)*(n+4)`).
  Thickening to `x^6 - 1 ∣ x^12 - 1` survives the battery, but the divisor chain grows
  the exponent multiplicatively (2^k by k=32) and the composed goal is one
  `Nat.sub_dvd_pow_sub_pow` application away — collapsible, so it was dropped.
* **`Real.sqrt` steps die to `aesop`** (`∀ x : ℝ, 1 ≤ x → √x ≤ x`). `Real.log x ≤ x - 1`
  and `x + 1 ≤ Real.exp x` both survive, but log/exp/sqrt terms *nest*: the term grows a
  wrapper per step, so leaf size is linear in k and flatness dies. Function-bound chains
  are usable only at small k; not the backbone.
* **Set/subset steps survived the battery** (`s ∩ t ⊆ s ∪ u`, `f '' (s ∩ t) ⊆ f '' s`
  were *not* closed by bare `aesop` here) but the reachable state space is tiny, so the
  intermediates repeat and stop being invented content past k≈4.
* **Monomial ladders over ℝ and over ℕ both survive the full battery**, with and without
  the additive offsets, at every k tested (leaf, k=2 goal, k=8 goal, k=32 goal: 0/7
  tactics closed each). ℝ was chosen over ℕ only because the leaf bank is ℝ-heavy.
* The **additive offsets are load-bearing against collapse**: with them, the obvious
  k-independent flat route (`have : M₀ ≤ M_k := by gcongr <;> linarith` then
  `nlinarith`) *fails* — measured on the k=8 and k=32 goals — because the offsets force
  the prover to also establish `1 ≤ M₀`, which `nlinarith` does not get from `3 ≤ x`
  alone. Without offsets that route is much closer to working.
* Known residual (reported, not argued away): a prover that reconstructs the full
  `1 ≤ M`/`3^δ ≤ v^δ` scaffold can close the endpoint goal in a k-independent number of
  lines. Bridge chains over an *ordered numeric* domain are collapsible in principle —
  the k-axis here stresses plan length and intermediate invention, and DIRECTION §5.4(d)
  (flat-prover decay) must be measured in Phase 2 rather than assumed.

Determinism: output is a pure function of `(k, seed)`; problem i uses the derived seed
string `bridge_chain|{k}|{seed}|{i}`.
"""
from __future__ import annotations

import random
from collections.abc import Iterable, Sequence

from rlmath.core.types import DecompositionPlan, GoalSpec, LemmaSpec, normalize_statement
from rlmath.families import register
from rlmath.families.types import GeneratedProblem, LeafWitness

FAMILY = "bridge_chain"

# --- schema knobs (identical at every k — this is what makes per-node difficulty flat)
VARS: tuple[str, str, str] = ("x", "y", "z")
HYP_NAMES: tuple[str, str, str] = ("hx", "hy", "hz")
LOWER = 3                      # side condition `LOWER ≤ v` on every variable
COEF_RANGE = (2, 9)            # cᵢ
OFFSET_RANGE = (1, 9)          # dᵢ
DELTAS = (1, 2)                # exponent increment per step
START_EXPONENTS = (1, 1, 1)
_MAX_REJECTS = 512             # sampler safety valve; the constraint is always satisfiable
_MAX_DISCARDS = 16             # offline regeneration attempts per problem slot

_BINDER = f"∀ x y z : ℝ, {LOWER} ≤ x → {LOWER} ≤ y → {LOWER} ≤ z → "

Term = tuple[int, tuple[int, int, int], int]      # (coefficient, exponents, offset)
Step = tuple[int, int]                            # (variable index, δ)


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _mono(exps: Sequence[int]) -> str:
    """`x ^ 2 * y ^ 1 * z ^ 3` — exponent 1 stays explicit so that leaf prop text has
    the same shape at every position in the chain (flatness is measured on this text)."""
    return " * ".join(f"{v} ^ {e}" for v, e in zip(VARS, exps))


def render_term(t: Term) -> str:
    c, exps, d = t
    return f"{c} * {_mono(exps)} + {d}"


def _prop(lo: Term, hi: Term) -> str:
    return f"{_BINDER}{render_term(lo)} ≤ {render_term(hi)}"


# --------------------------------------------------------------------------
# sampling
# --------------------------------------------------------------------------

def _valid(c_prev: int, d_prev: int, c_new: int, d_new: int, delta: int) -> bool:
    """SAMPLING CONSTRAINT (see module docstring): what makes the leaf witness a
    `linarith` over two monomial atoms rather than a nonlinear search."""
    return c_new * (LOWER ** delta) - c_prev >= max(0, d_prev - d_new)


def _sample_chain(rng: random.Random, k: int) -> tuple[list[Term], list[Step], int]:
    exps = list(START_EXPONENTS)
    c = rng.randint(*COEF_RANGE)
    d = rng.randint(*OFFSET_RANGE)
    terms: list[Term] = [(c, tuple(exps), d)]  # type: ignore[arg-type]
    steps: list[Step] = []
    rejects = 0
    for _ in range(k):
        j = rng.randrange(len(VARS))
        delta = rng.choice(DELTAS)
        for _attempt in range(_MAX_REJECTS):
            c_new = rng.randint(*COEF_RANGE)
            d_new = rng.randint(*OFFSET_RANGE)
            if _valid(c, d, c_new, d_new, delta):
                break
            rejects += 1
        else:  # pragma: no cover - unreachable: c_new=9, δ=1 always satisfies it
            raise RuntimeError("bridge_chain: sampling constraint unsatisfiable")
        exps[j] += delta
        steps.append((j, delta))
        c, d = c_new, d_new
        terms.append((c, tuple(exps), d))  # type: ignore[arg-type]
    return terms, steps, rejects


# --------------------------------------------------------------------------
# witnesses
# --------------------------------------------------------------------------

def _witness_proof(prev: Term, cur: Term, step: Step) -> str:
    """Generator-known proof of `_prop(prev, cur)`.

    Fully deterministic: no `nlinarith` search on the main inequality. The only
    non-elementary step is `hpow`, a one-variable numeric bound `3^δ ≤ v ^ δ`.
    """
    j, delta = step
    v, hv = VARS[j], HYP_NAMES[j]
    _, exps, _ = prev
    mono = _mono(exps)
    mono_next = _mono(cur[1])
    factor = LOWER ** delta
    lines = [
        "by",
        "  intro x y z hx hy hz",
    ]
    for idx, (var, e) in enumerate(zip(VARS, exps)):
        lines.append(f"  have hp{idx} : (1:ℝ) ≤ {var} ^ {e} := one_le_pow₀ (by linarith)")
    lines += [
        f"  have hA : (1:ℝ) ≤ {VARS[0]} ^ {exps[0]} * {VARS[1]} ^ {exps[1]} :="
        " le_trans hp0 (le_mul_of_one_le_right (by linarith) hp1)",
        f"  have hM : (1:ℝ) ≤ {mono} := le_trans hA (le_mul_of_one_le_right (by linarith) hp2)",
        f"  have hpow : ({factor}:ℝ) ≤ {v} ^ {delta} := by nlinarith [{hv}]",
        f"  have hstep : {factor} * ({mono}) ≤ {v} ^ {delta} * ({mono}) :="
        " mul_le_mul_of_nonneg_right hpow (by linarith)",
        f"  have hring : {v} ^ {delta} * ({mono}) = {mono_next} := by ring",
        "  rw [hring] at hstep",
        "  linarith [hM, hstep]",
    ]
    return "\n".join(lines)


def _assembly(k: int) -> str:
    """`le_trans` fold. Deliberately mentions no term text: the assembly is pure
    transitivity, so all invented content lives in the lemma statements."""
    apply = [f"h{i} x y z hx hy hz" for i in range(1, k + 1)]
    expr = f"({apply[-1]})"
    for a in reversed(apply[:-1]):
        expr = f"(le_trans ({a}) {expr})"
    return f"intro x y z hx hy hz\nexact {expr}"


# --------------------------------------------------------------------------
# offline self-checks (a V6 pre-check that needs no Lean)
# --------------------------------------------------------------------------

def hidden_intermediate_violations(problem: GeneratedProblem) -> list[str]:
    """Stricter than V6: V6 only asks that a *lemma prop* is not a substring of the
    goal, which any binder prefix defeats. Here we also require that no intermediate
    *term* text `a₁ … a_{k-1}` occurs anywhere in the goal — the property the family
    actually claims (a policy cannot copy an intermediate out of the statement)."""
    out: list[str] = []
    goal_norm = normalize_statement(problem.goal.prop)
    visible = set(problem.meta.get("visible_lemmas", ()))
    for lemma in problem.oracle_plan.lemmas:
        if lemma.name not in visible and normalize_statement(lemma.prop) in goal_norm:
            out.append(f"lemma {lemma.name} prop is a substring of the goal")
    for i, term in enumerate(problem.meta["intermediate_terms"], start=1):
        if term in goal_norm:
            out.append(f"intermediate term a{i} ({term!r}) occurs in the goal")
    return out


def leaf_shape_stats(problems: Iterable[GeneratedProblem]) -> dict:
    """Structural flatness evidence for the datasheet: leaf prop length distribution
    and step-kind mix, grouped by k (FAMILIES.md 'Scaling requirements')."""
    by_k: dict[int, dict] = {}
    for p in problems:
        s = by_k.setdefault(p.k, {"n_problems": 0, "leaf_chars": [], "deltas": [], "vars": []})
        s["n_problems"] += 1
        s["leaf_chars"].extend(len(l.prop) for l in p.oracle_plan.lemmas)
        s["deltas"].extend(d for _, d in p.meta["step_kinds"])
        s["vars"].extend(VARS[j] for j, _ in p.meta["step_kinds"])
    out = {}
    for k, s in sorted(by_k.items()):
        chars = sorted(s["leaf_chars"])
        out[k] = {
            "n_problems": s["n_problems"],
            "n_leaves": len(chars),
            "leaf_prop_chars": {
                "min": chars[0], "median": chars[len(chars) // 2], "max": chars[-1],
                "mean": round(sum(chars) / len(chars), 1),
            },
            "delta_mix": {d: s["deltas"].count(d) for d in DELTAS},
            "var_mix": {v: s["vars"].count(v) for v in VARS},
        }
    return out


# --------------------------------------------------------------------------
# generator
# --------------------------------------------------------------------------

def generate(k: int, seed: int, n: int = 1) -> list[GeneratedProblem]:
    """`k` bridge steps, `n` problems, deterministic in `(k, seed)`."""
    if k < 2:
        raise ValueError(f"bridge_chain needs k >= 2 (k=1 makes the single lemma the goal); got {k}")
    if n < 0:
        raise ValueError(f"n must be >= 0; got {n}")

    problems: list[GeneratedProblem] = []
    for idx in range(n):
        problems.append(_one(k, seed, idx))
    return problems


def _one(k: int, seed: int, idx: int) -> GeneratedProblem:
    """Discard/regenerate loop: a candidate that fails the offline hidden-intermediate
    pre-check is thrown away and resampled under the next attempt seed. The count lands
    in `meta["discards"]` so the datasheet can report a real discard rate rather than an
    assumed one (it is 0 in every run measured so far — the check is a tripwire, not a
    filter, because distinct exponent sums already make collisions impossible)."""
    for attempt in range(_MAX_DISCARDS + 1):
        rng = random.Random(f"{FAMILY}|{k}|{seed}|{idx}|{attempt}")
        terms, steps, rejects = _sample_chain(rng, k)
        pid = f"{FAMILY}-k{k}-s{seed}-{idx}"

        goal = GoalSpec(id=pid, prop=_prop(terms[0], terms[-1]), name=f"bridge_k{k}_s{seed}_{idx}")
        lemmas, witnesses = [], {}
        for i in range(1, k + 1):
            prop = _prop(terms[i - 1], terms[i])
            name = f"h{i}"
            lemmas.append(LemmaSpec(name=name, prop=prop))
            witnesses[name] = LeafWitness(prop=prop, proof=_witness_proof(terms[i - 1], terms[i],
                                                                         steps[i - 1]))
        plan = DecompositionPlan(lemmas=lemmas, assembly=_assembly(k))

        problem = GeneratedProblem(
            id=pid, family=FAMILY, k=k, seed=seed, goal=goal, oracle_plan=plan,
            witnesses=witnesses,
            meta={
                "visible_lemmas": [],
                "schema": "monomial_ladder_R",
                "lower_bound": LOWER,
                "vars": list(VARS),
                "step_kinds": steps,
                "intermediate_terms": [render_term(t) for t in terms[1:-1]],
                "endpoint_terms": [render_term(terms[0]), render_term(terms[-1])],
                "exponent_sums": [sum(t[1]) for t in terms],
                "leaf_prop_chars": [len(l.prop) for l in lemmas],
                "goal_prop_chars": len(goal.prop),
                "resamples": rejects,
                "discards": attempt,
            },
        )
        if not hidden_intermediate_violations(problem):
            return problem
    raise RuntimeError(  # pragma: no cover - unreachable with distinct exponent sums
        f"{FAMILY}-k{k}-s{seed}-{idx}: no candidate passed the hidden-intermediate pre-check"
    )


register(FAMILY, generate)
