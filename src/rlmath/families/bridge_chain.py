"""Family A — bridge chains: prove `R(a₀, a_k)` through k hidden intermediates.

Schema (v2, "named-function monomial ladder over ℝ")
----------------------------------------------------
Every problem is a chain `a₀ ≤ a₁ ≤ … ≤ a_k` of real terms

    aᵢ  =  cᵢ * Mᵢ  +  dᵢ * Fᵢ(Mᵢ)  +  oᵢ        Mᵢ = x ^ pᵢ * y ^ qᵢ * z ^ rᵢ

with `cᵢ ∈ [2,9]`, `dᵢ ∈ [1,9]`, `oᵢ ∈ [1,9]` and `Fᵢ ∈ {Real.sqrt, Real.log}` drawn iid
per term, under the shared side conditions `3 ≤ x`, `3 ≤ y`, `3 ≤ z`. One step multiplies
the monomial by `v ^ δ` for a randomly chosen `v ∈ {x,y,z}` and `δ ∈ {1,2}`, and resamples
`(c, d, o, F)`. Exponents start at `(1,1,1)`.

    goal    ∀ x y z : ℝ, 3 ≤ x → 3 ≤ y → 3 ≤ z → a₀ ≤ a_k
    hᵢ      ∀ x y z : ℝ, 3 ≤ x → 3 ≤ y → 3 ≤ z → aᵢ₋₁ ≤ aᵢ            (i = 1..k)
    assembly    intro x y z hx hy hz
                exact (le_trans (h1 x y z hx hy hz) (le_trans (h2 …) … ))

Only `a₀` and `a_k` occur in the goal; every intermediate's coefficients, offset,
named function and exponent triple are what a policy has to invent.

**Step form, not cumulative form.** The alternative plan shape `hᵢ : R(a₀, aᵢ)` was
rejected on two counts, both structural: (1) `h_k` *is* the goal, so the last lemma is a
restatement — it fails V6 unless exempted, and a policy emitting it has decomposed
nothing; (2) a cumulative witness redoes the whole prefix, so leaf difficulty grows with
i and per-node flatness (DIRECTION §5.4a) dies by construction.

Why v1 died, and what v2 changes (measured, 2026-08-12)
-------------------------------------------------------
v1 terms were `cᵢ Mᵢ + dᵢ`. Under the *strengthened* V0/V5 battery (10 tactics × {bare,
intros-first}) **16 of its leaves fell to `intros; gcongr <;> linarith`** — the combo v1
gated at the endpoints but never ran against individual steps. `gcongr` anti-unifies the
two sides, so a step whose every coefficient is non-decreasing (`c₁ ≤ c₂`, `d₁ ≤ d₂`,
`M ≤ M'`) is pure relational congruence and closes in one line.

v2 closes that hole twice over, and both halves were measured before shipping
(`research/family-v2-hardening.md` §2):

1. **Named-function content.** Each term carries `dᵢ * Fᵢ(Mᵢ)` with `Fᵢ` drawn from
   `{Real.sqrt, Real.log}`. When consecutive terms disagree on `F` there is no common
   wrapper to anti-unify, so `gcongr` cannot even build a template; `linarith`/`nlinarith`
   see `Real.sqrt (…)`/`Real.log (…)` as opaque atoms with no connecting hypothesis.
   Measured: `4M + 2 log M ≤ 9M' + 7 √M'` survives the whole battery *even with every
   coefficient rising*, while the same step with `√` on both sides dies to
   `intros; gcongr <;> linarith`.
2. **A per-step congruence gate** (`step_resists_congruence`): at least one of `c`, `d`,
   `o` must strictly *decrease* across every step. That is exactly the negation of
   gcongr's success condition, so it holds regardless of which functions were drawn.
   The multiplicative gain `M' ≥ 3^δ M` pays for the drop.

The gate is applied unconditionally, i.e. it is stricter than the measurement demands
(only `√|√` steps needed it). Making it conditional on the function pair would make the
`(c,d,o)` distribution depend on the function draw for no measured benefit.

Why the step is sound and why its witness needs no search
---------------------------------------------------------
With `M ≥ 1`, `F(M) ≤ M` (for `√`: `Real.sqrt_le_self_iff`; for `log`:
`Real.log_le_sub_one_of_pos`), `F(M') ≥ 0`, and `M' ≥ 3^δ M`, the step
`c₁M + d₁F₁(M) + o₁ ≤ c₂M' + d₂F₂(M') + o₂` is a *linear* consequence over the four
atoms `M, M', F₁(M), F₂(M')` provided

    c₂ · 3^δ − (c₁ + d₁)  ≥  max(0, o₁ − o₂)                     (SAMPLING CONSTRAINT)

which the sampler enforces by rejection. Everything else in the witness is the `1 ≤ M`
scaffold, unchanged from v1 (search-free `gcongr` on a one-variable numeric bound, no
`nlinarith` anywhere — that is what kept the composed k=32 artifact inside PREAMBLE's
`maxHeartbeats`).

Residual, stated plainly and unchanged from v1: bridge chains over an *ordered numeric*
domain are collapsible in principle (`≤` is transitive **and** total), so what the k-axis
stresses here is plan length and intermediate invention. DIRECTION §5.4(d) (flat-prover
decay) is a Phase-2 measurement, not a schema property.

Determinism: output is a pure function of `(k, seed)`; problem i, attempt a uses the
derived seed string `bridge_chain|{k}|{seed}|{i}|{a}`.
"""
from __future__ import annotations

import random
from collections.abc import Iterable, Sequence

from rlmath.core.types import DecompositionPlan, GoalSpec, LemmaSpec, normalize_statement
from rlmath.families import register
from rlmath.families.types import GeneratedProblem, LeafWitness

FAMILY = "bridge_chain"
SCHEMA = "named_function_monomial_ladder_R"

# --- schema knobs (identical at every k — this is what makes per-node difficulty flat)
VARS: tuple[str, str, str] = ("x", "y", "z")
HYP_NAMES: tuple[str, str, str] = ("hx", "hy", "hz")   # side-condition names in every proof
LOWER = 3                      # side condition `LOWER ≤ v` on every variable
COEF_RANGE = (2, 9)            # cᵢ — multiplier of the monomial
FCOEF_RANGE = (1, 9)           # dᵢ — multiplier of the named-function term
OFFSET_RANGE = (1, 9)          # oᵢ — additive offset
DELTAS = (1, 2)                # exponent increment per step
START_EXPONENTS = (1, 1, 1)
FUNCS: tuple[str, str] = ("sqrt", "log")   # named function wrapping the monomial
_MAX_REJECTS = 512             # sampler safety valve; the constraint is always satisfiable
_MAX_DISCARDS = 400            # offline regeneration attempts per slot

# The one `(c,d,o)` state with no legal successor under the congruence gate: nothing can
# strictly decrease below the floor of all three ranges. Excluded from the sample space
# so `_sample_chain` can never paint itself into a corner.
_CORNER = (COEF_RANGE[0], FCOEF_RANGE[0], OFFSET_RANGE[0])

BINDER = f"∀ x y z : ℝ, {LOWER} ≤ x → {LOWER} ≤ y → {LOWER} ≤ z → "

Term = tuple[int, tuple[int, int, int], int, int, str]   # (c, exponents, d, o, func)
Step = tuple[int, int]                                   # (variable index, δ)


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _mono(exps: Sequence[int]) -> str:
    """`x ^ 2 * y ^ 1 * z ^ 3` — exponent 1 stays explicit so that leaf prop text has
    the same shape at every position in the chain (flatness is measured on this text)."""
    return " * ".join(f"{v} ^ {e}" for v, e in zip(VARS, exps))


def _fn(func: str, arg: str) -> str:
    """Fully qualified: PREAMBLE opens both `Real` and `Nat`, so bare `log`/`sqrt`
    would be ambiguous."""
    return f"Real.{func} ({arg})"


def render_term(t: Term) -> str:
    c, exps, d, o, func = t
    mono = _mono(exps)
    return f"{c} * {mono} + {d} * {_fn(func, mono)} + {o}"


def _prop(lo: Term, hi: Term) -> str:
    return f"{BINDER}{render_term(lo)} ≤ {render_term(hi)}"


# --------------------------------------------------------------------------
# sampling
# --------------------------------------------------------------------------

def _valid(prev: tuple[int, int, int], new: tuple[int, int, int], delta: int) -> bool:
    """SAMPLING CONSTRAINT (see module docstring): what makes the leaf witness a
    `linarith` over four atoms rather than a nonlinear search.

    `F(M) ≤ M` and `F(M') ≥ 0` reduce the step to `(c₁+d₁)M + o₁ ≤ c₂M' + o₂`, and
    `M' ≥ 3^δ M ≥ 3^δ` closes it exactly when the inequality below holds.
    """
    c1, d1, o1 = prev
    c2, _d2, o2 = new
    return c2 * (LOWER ** delta) - (c1 + d1) >= max(0, o1 - o2)


def step_resists_congruence(prev: tuple[int, int, int], new: tuple[int, int, int]) -> bool:
    """Per-step gate against `gcongr <;> linarith` — the tactic that killed 16 v1 leaves.

    `gcongr` anti-unifies the two sides of `≤` and emits one side goal per differing
    position. For `c₁M + d₁F(M) + o₁ ≤ c₂M' + d₂F(M') + o₂` those are `c₁ ≤ c₂`,
    `M ≤ M'`, `d₁ ≤ d₂`, `o₁ ≤ o₂` (plus the monotonicity of `F`), all of which the
    `<;> linarith` discharger closes when the coefficients rise together. Forcing **one
    of the three coefficients strictly down** makes a side goal false, so no template
    succeeds, while the multiplicative gain `M' ≥ 3^δ M` keeps the step true.

    Measured (research/family-v2-hardening.md §2): with every coefficient rising and the
    same function on both sides the step dies to `intros; gcongr <;> linarith` in ~1 s;
    with one coefficient dropping it survives all 20 battery proofs.
    """
    return any(n < p for n, p in zip(new, prev))


def endpoints_resist_naive_collapse(first: Term, last: Term) -> bool:
    """Endpoint gate: reject chains the *endpoints alone* give away.

    The k-independent flat route on the goal is `have hj : M₀ ≤ M_k := by gcongr <;>
    linarith` plus a lower bound `t ≤ M₀`, then `linarith`. Its strongest form closes the
    goal iff `(c_k − c₀)·t ≥ o₀ − o_k` for the best available `t`. Demanding

        c_k < c₀   and   o_k ≤ o₀   and   d_k ≤ d₀

    makes the left side *negative* and the right side non-negative, so **no** lower bound
    on `M₀`, however sharp, can rescue it: a flat prover must instead establish a
    quantitative ratio `M_k ≥ r·M₀` with `r ≥ c₀/c_k > 1`, which is exactly the
    multiplicative content the chain carries and which `gcongr` cannot produce. The
    `d_k ≤ d₀` conjunct extends the same argument to the named-function term (whose
    coefficient a prover could otherwise trade against, since `F(M) ≤ M`).

    Measured for v1 (§4 of research/family-bridge-chain.md): before the gate a k=8 goal
    fell to that route in 8 lines; after it, all five flat routes we know of close 0/3
    goals at every k ∈ {2,4,8,16,32}. The gate touches only the endpoints, so leaf
    difficulty is untouched. It defeats a *family* of routes, not collapse in general.
    """
    c0, _exps0, d0, o0, _f0 = first
    ck, _expsk, dk, ok, _fk = last
    return ck < c0 and ok <= o0 and dk <= d0


def _sample_knobs(rng: random.Random) -> tuple[int, int, int]:
    return (rng.randint(*COEF_RANGE), rng.randint(*FCOEF_RANGE), rng.randint(*OFFSET_RANGE))


def _sample_chain(rng: random.Random, k: int) -> tuple[list[Term], list[Step], int]:
    exps = list(START_EXPONENTS)
    rejects = 0
    knobs = _sample_knobs(rng)
    while knobs == _CORNER:
        knobs = _sample_knobs(rng)
        rejects += 1
    func = rng.choice(FUNCS)
    terms: list[Term] = [(knobs[0], tuple(exps), knobs[1], knobs[2], func)]  # type: ignore[arg-type]
    steps: list[Step] = []
    for _ in range(k):
        j = rng.randrange(len(VARS))
        delta = rng.choice(DELTAS)
        for _attempt in range(_MAX_REJECTS):
            new = _sample_knobs(rng)
            if new != _CORNER and _valid(knobs, new, delta) and step_resists_congruence(knobs, new):
                break
            rejects += 1
        else:  # pragma: no cover - unreachable: the corner is excluded, so a legal
               # successor always exists (see _CORNER and the gate's docstring)
            raise RuntimeError("bridge_chain: step constraints unsatisfiable")
        exps[j] += delta
        steps.append((j, delta))
        knobs = new
        terms.append((knobs[0], tuple(exps), knobs[1], knobs[2], rng.choice(FUNCS)))  # type: ignore[arg-type]
    return terms, steps, rejects


# --------------------------------------------------------------------------
# witnesses
# --------------------------------------------------------------------------

def _fn_bounds(prev: Term, cur: Term) -> list[str]:
    """The two named-function facts the final `linarith` needs, per function pair.

    Upper bound on the *left* term's function (`F₁(M) ≤ M`) and non-negativity of the
    *right* one (`0 ≤ F₂(M')`). Both are single lemma applications — no search — which
    is what keeps the composed artifact cheap at large k.
    """
    mono, mono_next = _mono(prev[1]), _mono(cur[1])
    left, right = prev[4], cur[4]
    lines = []
    if left == "sqrt":
        lines.append(f"  have hfu : Real.sqrt ({mono}) ≤ {mono} :="
                     " Real.sqrt_le_self_iff.mpr (Or.inr hM)")
    else:
        lines.append(f"  have hfu : Real.log ({mono}) ≤ {mono} - 1 :="
                     " Real.log_le_sub_one_of_pos (by linarith)")
    if right == "sqrt":
        lines.append(f"  have hfl : (0:ℝ) ≤ Real.sqrt ({mono_next}) := Real.sqrt_nonneg _")
    else:
        lines.append(f"  have hfl : (0:ℝ) ≤ Real.log ({mono_next}) :="
                     " Real.log_nonneg (by linarith [hM, hstep])")
    return lines


def _witness_proof(prev: Term, cur: Term, step: Step) -> str:
    """Generator-known proof of `_prop(prev, cur)`.

    Search-free: `gcongr` on a one-variable numeric bound, two named-function lemma
    applications, then `linarith` over the four atoms `M, M', F₁(M), F₂(M')`. No
    `nlinarith` anywhere — it is what made the composed artifact expensive at large k.
    """
    j, delta = step
    v = VARS[j]
    exps = prev[1]
    mono = _mono(exps)
    mono_next = _mono(cur[1])
    factor = LOWER ** delta
    # `hbase` comes first, while the context is still just hx/hy/hz: proved later it
    # would drag every big-monomial hypothesis into the search, and the composed k=32
    # artifact then blows PREAMBLE's maxHeartbeats budget (measured — see the design log).
    lines = [
        "by",
        "  intro x y z hx hy hz",
        f"  have hbase : ({LOWER}:ℝ) ^ {delta} ≤ {v} ^ {delta} := by gcongr <;> linarith",
        f"  have hpow : ({factor}:ℝ) ≤ {v} ^ {delta} := by linarith [hbase]",
    ]
    for idx, (var, e) in enumerate(zip(VARS, exps)):
        lines.append(f"  have hp{idx} : (1:ℝ) ≤ {var} ^ {e} := one_le_pow₀ (by linarith)")
    lines += [
        f"  have hA : (1:ℝ) ≤ {VARS[0]} ^ {exps[0]} * {VARS[1]} ^ {exps[1]} :="
        " le_trans hp0 (le_mul_of_one_le_right (by linarith) hp1)",
        f"  have hM : (1:ℝ) ≤ {mono} := le_trans hA (le_mul_of_one_le_right (by linarith) hp2)",
        f"  have hstep : {factor} * ({mono}) ≤ {v} ^ {delta} * ({mono}) :="
        " mul_le_mul_of_nonneg_right hpow (by linarith)",
        f"  have hring : {v} ^ {delta} * ({mono}) = {mono_next} := by ring",
        "  rw [hring] at hstep",
    ]
    lines += _fn_bounds(prev, cur)
    lines.append("  linarith [hM, hstep, hfu, hfl]")
    return "\n".join(lines)


def _assembly(k: int) -> str:
    """**Balanced** `le_trans` fold. Deliberately mentions no term text: the assembly is
    pure transitivity, so all invented content lives in the lemma statements.

    Balanced rather than right-nested for elaboration cost, and this was measured, not
    assumed: v1's right-nested fold `le_trans h1 (le_trans h2 (…))` puts step i at depth
    i, so the elaborator propagates postponed metavariables through k levels. v2's leaf
    props carry two extra function applications each, and at k=32 the right-nested fold
    tipped V3 (`plan_check`) over PREAMBLE's `maxHeartbeats 400000` —
    `(deterministic) timeout at «synthesize pending MVars»` — while every leaf still
    checked individually. A balanced fold puts every step at depth ⌈log₂ k⌉; same k−1
    `le_trans` applications, same absence of term text, k=32 back inside budget.
    """
    apply = [f"h{i} x y z hx hy hz" for i in range(1, k + 1)]

    def rec(lo: int, hi: int) -> str:
        if hi - lo == 1:
            return f"({apply[lo]})"
        mid = (lo + hi) // 2
        return f"(le_trans {rec(lo, mid)} {rec(mid, hi)})"

    return f"intro x y z hx hy hz\nexact {rec(0, k)}"


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
    """Structural flatness evidence for the datasheet: leaf prop length distribution,
    step-kind mix and named-function mix, grouped by k (FAMILIES.md 'Scaling
    requirements')."""
    by_k: dict[int, dict] = {}
    for p in problems:
        s = by_k.setdefault(p.k, {"n_problems": 0, "leaf_chars": [], "deltas": [],
                                  "vars": [], "funcs": [], "fn_pairs": []})
        s["n_problems"] += 1
        s["leaf_chars"].extend(len(l.prop) for l in p.oracle_plan.lemmas)
        s["deltas"].extend(d for _, d in p.meta["step_kinds"])
        s["vars"].extend(VARS[j] for j, _ in p.meta["step_kinds"])
        s["funcs"].extend(p.meta["funcs"])
        s["fn_pairs"].extend(p.meta["fn_pairs"])
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
            "func_mix": {f: s["funcs"].count(f) for f in FUNCS},
            "fn_pair_mix": {f"{a}|{b}": s["fn_pairs"].count(f"{a}|{b}")
                            for a in FUNCS for b in FUNCS},
        }
    return out


# --------------------------------------------------------------------------
# generator
# --------------------------------------------------------------------------

def generate(k: int, seed: int, n: int = 1) -> list[GeneratedProblem]:
    """`k` bridge steps, `n` problems, deterministic in `(k, seed)`."""
    if k < 2:
        raise ValueError(f"bridge_chain needs k >= 2 (k=1 makes the lemma the goal); got {k}")
    if n < 0:
        raise ValueError(f"n must be >= 0; got {n}")

    problems: list[GeneratedProblem] = []
    for idx in range(n):
        problems.append(_one(k, seed, idx))
    return problems


def _one(k: int, seed: int, idx: int) -> GeneratedProblem:
    """Discard/regenerate loop, on two offline gates:

    * `endpoints_resist_naive_collapse` — the binding one;
    * `hidden_intermediate_violations` — a tripwire, 0% in every run measured (distinct
      exponent sums already make an intermediate/endpoint collision impossible).

    The realised count lands in `meta["discards"]`, so the datasheet reports a measured
    discard rate rather than an assumed one."""
    for attempt in range(_MAX_DISCARDS + 1):
        rng = random.Random(f"{FAMILY}|{k}|{seed}|{idx}|{attempt}")
        terms, steps, rejects = _sample_chain(rng, k)
        if not endpoints_resist_naive_collapse(terms[0], terms[-1]):
            continue
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
                "schema": SCHEMA,
                "lower_bound": LOWER,
                "vars": list(VARS),
                "step_kinds": steps,
                "funcs": [t[4] for t in terms],
                "fn_pairs": [f"{terms[i - 1][4]}|{terms[i][4]}" for i in range(1, k + 1)],
                "intermediate_terms": [render_term(t) for t in terms[1:-1]],
                # consumed by validate.py V6b: these strings must not occur in the goal
                "hidden_terms": [render_term(t) for t in terms[1:-1]],
                "endpoint_terms": [render_term(terms[0]), render_term(terms[-1])],
                "exponent_sums": [sum(t[1]) for t in terms],
                "knobs": [{"c": t[0], "d": t[2], "o": t[3], "func": t[4]} for t in terms],
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
