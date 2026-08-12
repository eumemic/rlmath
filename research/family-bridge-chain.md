# Family A — bridge chains (`bridge_chain`): design log

Phase 1 of DIRECTION.md §5.5, built against the FAMILIES.md contract. Everything below
was **measured** on the local `ReplPool` (Mathlib @ lean v4.34.0-rc1, `n_workers=2`,
standard PREAMBLE), never argued. Started and finished 2026-08-11.

Module: `src/rlmath/families/bridge_chain.py` · tests: `tests/test_family_bridge_chain.py`

---

## 1. What the family has to be

`R(a₀, a_k)` composed by the generator through k hidden intermediates; only the
endpoints appear in the statement; the assembly is transitivity; the **intermediates are
the invented content**. On top of that, FAMILIES.md demands V0–V6 pass for ≥90% of
emitted problems and DIRECTION §5.4(a) demands per-node difficulty flat in k.

### Step form vs cumulative form (design fork, settled on structure)

| | `hᵢ : R(aᵢ₋₁, aᵢ)` (**chosen**) | `hᵢ : R(a₀, aᵢ)` |
|---|---|---|
| last lemma | a genuine step | **is the goal** → V6 fails unless exempted; a policy emitting it has decomposed nothing |
| leaf difficulty | identical at every i | grows with i (the witness must redo the whole prefix) → per-node flatness dead by construction |
| assembly | `le_trans` fold, mentions no term text | `le_trans` fold, same |
| what is invented | every intermediate term | every intermediate term |

Cumulative form loses on both structural counts, so the family is step form. Note the
consequence for the assembly: it is *pure* transitivity and contains no term text at all
(asserted in `test_assembly_is_pure_transitivity`), which forces all invented content
into the lemma statements where V6 can see it.

---

## 2. Schemas tried, and the battery kill-list per schema

Battery = the V0/V5 constant in `validate.py`: `simp, aesop, norm_num, omega, decide,
linarith, positivity`, 20 s each, **any** success kills the schema. Each row below is one
`theorem _proof_check : <prop> := by <tactic>` per tactic (7 Lean calls per prop; the
whole 98-call probe took 2 s wall — these tactics fail fast on this material).

| # | candidate step prop | closed by | verdict |
|---|---|---|---|
| S9 | `∀ n : ℕ, (n^2+3n+2) ∣ (n^2+3n+2)*(n+4)` | **simp, aesop, norm_num** | dead — direction 2's "symbolic multiplier" step is pure `dvd_mul_right` |
| S7 | `∀ x : ℝ, 1 ≤ x → Real.sqrt x ≤ x` | **aesop** | dead |
| S6 | `∀ x : ℝ, 0 < x → Real.log x ≤ x - 1` | — | survives, but see §3 |
| S8 | `∀ x : ℝ, x + 1 ≤ Real.exp x` | — | survives, but see §3 |
| S10 | `∀ x : ℕ, x^6 - 1 ∣ x^12 - 1` | — | survives; rejected in §3 |
| S11 | `∀ (s t u : Set ℕ), s ∩ t ⊆ s ∪ u` | — | survives (surprising: bare `aesop` did **not** close it) |
| S12 | `∀ (f : ℕ → ℕ) (s t : Set ℕ), f '' (s ∩ t) ⊆ f '' s` | — | survives; rejected in §3 |
| S13 | `∀ (u : ℕ → ℝ) (c : ℝ), (∀ n, u (n+1) = c * u n) → u 3 = c^3 → u 4 = c^4` | — | survives; rejected in §3 |
| S1 | `… 3 * x^2*y^1*z^3 ≤ 5 * x^3*y^1*z^3` (ℝ, no offset) | — | survives |
| S2 | `… 3 * x^2*y^1*z^3 + 7 ≤ 5 * x^3*y^1*z^3 + 2` (ℝ, offsets) | — | survives — **chosen** |
| S3/S4 | same two over ℕ | — | survive (`omega` refuses the nonlinear atoms) |
| T1 | tight ℝ step `5*M + 9 ≤ 2*(M·x) + 8` | — | survives |
| T3 | δ=2 step `8*M + 9 ≤ 2*(M·x²) + 1` | — | survives |
| T8 | large-exponent leaf `5*x^11 y^9 z^12 + 9 ≤ 2*x^12 y^9 z^12 + 8` | — | survives (leaves stay resistant deep in a k=32 chain) |
| T5/T6/T7 | composed **goals** at k≈2 / 8 / 32 | — | survive |

**Concrete arithmetic is not the failure mode here — trivial structure is.** The one
schema that died outright (S9) died because the step *was* a single Mathlib lemma;
`simp`/`aesop` recognise `a ∣ a * b` instantly. Everything with two monomial atoms and a
symbolic side condition survived every tactic in the battery, including `linarith`
(which normalises to linear combinations of *monomials* and so cannot multiply `3 ≤ x`
into `3M ≤ xM`) and `positivity` (which only ever proves `0 ≤ e` / `0 < e` / `e ≠ 0`).

---

## 3. Why the survivors that were not chosen were rejected

Surviving the battery is necessary, not sufficient. Three further filters killed the rest:

**(a) Term growth kills flatness.** `Real.log`/`Real.exp`/`Real.sqrt` chains grow a
*wrapper per step*: `a₃ = Real.exp (Real.log (…))`. Leaf prop length is then linear in k,
so leaves at k=32 are visibly not drawn from the k=2 distribution — DIRECTION §5.4(a) is
violated at the level of the statement text, before any prover sees it. Same for
`x^a - 1 ∣ x^b - 1`, where the exponent grows *multiplicatively* (≈2^k by k=32).
Growth of *some* measure is unavoidable in any transitive chain of distinct terms; the
design question is the rate, and a monomial ladder is the flattest available: the
exponent grows linearly in k, so its **decimal length** grows like log k (measured: +3
characters from k=2 to k=32, §6).

**(b) A small reachable state space stops the intermediates from being invented.**
Subset chains (S11/S12) survived the battery, but with a bounded alphabet of symbolic
sets and operations the walk revisits terms after ~4 steps, so the intermediates stop
being new content and the family degenerates at exactly the k where it should get hard.

**(c) An unrolled recurrence is not a transitive bridge.** S13
(`(∀ n, u (n+1) = c * u n) → u 3 = c^3 → u 4 = c^4`) is the most attractive
*non-collapsible* candidate found — a flat prover genuinely has to unroll k times — and
it survived the battery. It was rejected because the composition is implication chaining
over an indexed family, not `R(a₀,a_k)` closed by transitivity: the goal has no two
endpoints, the "intermediates" are indices rather than invented terms, and with concrete
values instead of the opaque `c` the numerals grow (doubly so for nonlinear recurrences),
taking flatness with them. It is the right seed for a *different* family, not this one.

**(d) Restating the hypothesis pool is not a leaf.** The "opaque relation pool" variants
(goal `∀ (a : ℕ → ℕ), a 0 ∣ a 3 → a 3 ∣ a 7 → … → a 0 ∣ a 40`) are genuinely
non-collapsible — you must find the path — but each leaf must be a *closed* prop, so it
has to restate the whole pool. Leaf length is then O(k). Rejected for the same reason
as (a). This is a real tension worth recording: **hidden-path non-collapsibility and
closed flat leaves pull against each other.**

---

## 4. Collapsibility probes (the honest part)

FAMILIES.md's V0 only asks the goal to resist the *battery*. DIRECTION §5.4(d) asks for
more — flat-prover solve rate must decay in k — so the composed goals were also attacked
with tactics deliberately **outside** the battery (`gcongr`, `nlinarith`). This is where
the schema changed twice, both times because a measurement said so.

### 4.1 First measurement: the offsets are load-bearing

| flat attempt on the composed goal | result |
|---|---|
| `gcongr <;> linarith` on the **offset-free** k=8 goal | **closes it — one line** |
| `nlinarith [hx, hy, hz, mul_pos …]`, k=8, with offsets | fails |
| `have h : M₀ ≤ M_k := by gcongr <;> linarith; nlinarith [h, …]`, k=8 | fails |
| same at k=32 (`have hM : 1 ≤ M₀ := by nlinarith` first) | fails — `nlinarith` cannot even get `1 ≤ x^1*y^1*z^1` from `3 ≤ x, 3 ≤ y, 3 ≤ z` |
| `have hM : 1 ≤ M₀ := …` (hand-proved) `; have hj : M₀ ≤ M_k := by gcongr <;> linarith; linarith`, k=8 | **closes it — 8 lines, k-independent** |

Strip the additive offsets and the whole family is a one-liner at any k. Keep them and
the automation fails — but the last row shows a hand-built 8-line route that still works
and does not grow with k. That row is what forced the second change.

### 4.2 Second measurement: an endpoint gate that kills the whole route family

The surviving route is "`M₀ ≤ M_k` (easy: `gcongr`) plus some lower bound `t ≤ M₀`, then
`linarith`". It closes `c₀M₀ + d₀ ≤ c_k M_k + d_k` iff `(c_k − c₀)·t ≥ d₀ − d_k`. So the
generator now **discards any chain whose endpoints satisfy `c_k ≥ c₀ or d_k > d₀`**
(`endpoints_resist_naive_collapse`). With `c_k < c₀` the left side is negative and gets
*more* negative as `t` improves: no lower bound on `M₀`, however sharp, can rescue it.

Measured after the gate, on freshly emitted problems (n=3 per k, seed 2026):

| flat route | k=2 | k=4 | k=8 | k=16 | k=32 |
|---|---|---|---|---|---|
| `gcongr` + hand `1 ≤ M₀` + `linarith` | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| `gcongr` + `nlinarith` | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| bare `nlinarith` with positivity hints | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| expert: hand-proved `27 ≤ M₀` + `gcongr` + `linarith` | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| expert: `9·M₀ ≤ M_k` by `nlinarith`, then `linarith` | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 |

Step-by-step isolation on one k=8 goal
(`6·xyz + 8 ≤ 2·x⁶y⁵z⁴ + 2`) shows exactly where each dies:

* `gcongr <;> linarith` proves `M₀ ≤ M_k` **fine** — that half was never the obstacle;
* `nlinarith` cannot prove `27 ≤ x^1·y^1·z^1` from `3 ≤ x,y,z` (it multiplies hypothesis
  *pairs*, and this needs a triple product), nor `9·M₀ ≤ M_k`;
* and *granting* `hM : 27 ≤ M₀` outright, the final `linarith` still fails, because
  `c_k = 2 < 6 = c₀` makes `2·M_k + 2 ≥ 6·M₀ + 8` unreachable from `M₀ ≤ M_k` at any
  value of `M₀`.

### 4.3 Residual, stated plainly

The gate kills the "`M₀ ≤ M_k` + a bound on `M₀`" family. It does **not** prove
non-collapsibility: a prover that establishes a *quantitative ratio* `M_k ≥ r·M₀` with
`r ≥ c₀/c_k` closes the goal in a k-independent number of lines, and that ratio is true
by a wide margin (`M_k / M₀ ≥ 3^k`). Bridge chains over an ordered numeric domain are
collapsible in principle: `≤` is transitive **and** total, so every sub-chain is a valid
proof and the shortest one has length 1. What the k-axis stresses in this family is
**plan length and intermediate invention**, not per-goal proof difficulty. §5.4(d) must
therefore be *measured* against the real flat prover in Phase 2, not assumed from the
schema — and if it fails, Family B (case trees, where the split is genuinely forced) is
where the decay has to come from.

---

## 5. Final schema

    aᵢ = cᵢ * x ^ pᵢ * y ^ qᵢ * z ^ rᵢ + dᵢ        cᵢ ∈ [2,9], dᵢ ∈ [1,9], (p,q,r)₀ = (1,1,1)

    goal  ∀ x y z : ℝ, 3 ≤ x → 3 ≤ y → 3 ≤ z → a₀ ≤ a_k
    hᵢ    ∀ x y z : ℝ, 3 ≤ x → 3 ≤ y → 3 ≤ z → aᵢ₋₁ ≤ aᵢ
    asm   intro x y z hx hy hz
          exact (le_trans (h1 x y z hx hy hz) (le_trans (h2 …) … ))

One step picks `v ∈ {x,y,z}` and `δ ∈ {1,2}` uniformly, multiplies the monomial by `v^δ`,
and **resamples both `c` and `d`** subject to

    c_new · 3^δ − c_prev ≥ max(0, d_prev − d_new)                        (SAMPLING CONSTRAINT)

and the whole chain is discarded unless its endpoints satisfy

    c_k < c₀   and   d_k ≤ d₀                                            (ENDPOINT GATE, §4.2)

The sampling constraint is exactly the condition under which the leaf is provable by
`linarith` over the two monomial atoms `M` and `v^δ·M` given `1 ≤ M`, which is why the
witness is search-free:

```
intro x y z hx hy hz
have hbase : (3:ℝ) ^ δ ≤ v ^ δ := by gcongr <;> linarith
have hpow  : (3^δ:ℝ) ≤ v ^ δ := by linarith [hbase]
have hp0 : (1:ℝ) ≤ x ^ p := one_le_pow₀ (by linarith)      -- ×3
have hA  : (1:ℝ) ≤ x ^ p * y ^ q := le_trans hp0 (le_mul_of_one_le_right (by linarith) hp1)
have hM  : (1:ℝ) ≤ x ^ p * y ^ q * z ^ r := le_trans hA (le_mul_of_one_le_right (by linarith) hp2)
have hstep : 3^δ * (M) ≤ v ^ δ * (M) := mul_le_mul_of_nonneg_right hpow (by linarith)
have hring : v ^ δ * (M) = M' := by ring
rw [hring] at hstep
linarith [hM, hstep]
```

`hbase` is deliberately **first**, while the context is still just `hx/hy/hz`. The first
version proved it with `nlinarith [hv]` *after* the `1 ≤ M` scaffold, which dragged every
big-monomial hypothesis into the nonlinear search; at k=32 one of three composed oracle
artifacts then blew PREAMBLE's `maxHeartbeats 400000` at `whnf` — with all 32 leaves
still checking individually (V2 96/96, V4 2/3). Reordering plus dropping `nlinarith`
entirely fixed it. Sampling-constraint violations cost a resample, not a failed Lean
check, which is what keeps V2 at 100%.

**Hidden-intermediate sampling (V6 and stronger).** V6 as `validate.py` computes it is a
substring test on the *whole lemma prop*, which any binder prefix defeats — it is a
tripwire against literal restatement, not a guarantee. The family therefore enforces the
stronger property offline, in `hidden_intermediate_violations()`: **no intermediate
term text `a₁ … a_{k-1}` occurs anywhere in the goal.** This holds by construction
because exponent sums strictly increase along the chain, so no intermediate can share a
monomial with either endpoint; the check is a tripwire that fires if the schema ever
drifts, and `test_pre_check_catches_a_planted_restatement` proves the tripwire works.
The intermediates are still *reinventable*: any ladder satisfying the constraint proves
the goal, so a competent prover reconstructs a valid chain rather than guessing the
generator's.

**Flatness by construction.** Exponent 1 is rendered explicitly (`y ^ 1`, not `y`) so
leaf text has the same shape at every position; the knobs (`LOWER`, `COEF_RANGE`,
`OFFSET_RANGE`, `DELTAS`) are module constants, identical at every k. k changes only how
many steps compose.

---

## 6. Measured results

### 6.1 Validator table — n=3 problems per k, `check_automation=True`, real `ReplPool(2)`

Seed 2026, final schema (endpoint gate on, search-free witness). Counts are **passing
checks / total checks** (V2/V5/V6 are per-leaf, so their totals are `n·k`). Wall clock:
5 s (k=2), 8 s (k=4), 32 s (k=8) on 2 workers.

| check | k=2 | k=4 | k=8 | k=16 † | k=32 † |
|---|---|---|---|---|---|
| structure | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| V1_goal_elaborates | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| V0_goal_resists_automation | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| V2_stmt[leaf] | 6/6 | 12/12 | 24/24 | 48/48 | 96/96 |
| V2_proof[leaf] | 6/6 | 12/12 | 24/24 | 48/48 | 96/96 |
| V3_plan_check | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| V4_oracle_replay | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| V5_leaf_resists[leaf] | 6/6 | 12/12 | 24/24 | 48/48 | 96/96 |
| V6_hidden[leaf] | 6/6 | 12/12 | 24/24 | 48/48 | 96/96 |
| **problems fully passing V0–V6** | **3/3 (100%)** | **3/3 (100%)** | **3/3 (100%)** | **3/3** | **3/3** |

† beyond the required grid, run as scaling evidence (82 s and 299 s respectively).

Target was ≥90% of emitted problems passing every check; measured **100% at every k in
{2,4,8}** and, as a bonus, at k=16 and k=32 too — 468 + 1,764 individual Lean checks with
**zero** failures.

The one failure ever observed in this family was on an *earlier* witness: at k=32,
1 of 3 `V4_oracle_replay` checks died with `maximum number of heartbeats (400000) has
been reached` at `whnf`, while V2 was 96/96 — i.e. every leaf proved on its own and only
the 451-line composed artifact was too expensive. That drove the search-free witness
rewrite in §5; after it, k=32 V4 is 3/3.

### 6.2 Discard / regeneration rate

Three loops, all offline (the generator signature takes no backend, so no Lean-in-the-loop
discard is possible — see the flags in the handoff):

| loop | what it rejects | measured rate |
|---|---|---|
| sampling-constraint rejection (`_sample_chain`) | `(c,d)` pairs violating the step constraint | **10 / 186 steps = 5.4%** (seed 2026, k ∈ {2,4,8,16,32}); 0/42 on the k ≤ 8 slice |
| **endpoint gate** (`endpoints_resist_naive_collapse`) | whole chains whose endpoints give the goal away (§4.2) | **43 / 52 candidates = 82.7%** on the headline k ∈ {2,4,8} run · **56 / 71 = 78.9%** over k ≤ 32 · 51/66 = 77% at seed 11. Worst single slot: 12 retries (cap is 400) |
| hidden-intermediate pre-check | candidates where an intermediate term appears in the goal | **0 / 15 problems (0%)** on every run — structurally impossible, kept as a tripwire |

So ~80% of *candidates* are discarded, essentially all of it by the endpoint gate, and
all of it offline and free (no Lean call — sampling a k=32 chain is microseconds). Of the
problems actually **emitted**, 100% pass V0–V6. The discarding buys collapse-resistance,
not validator pass rate: the pre-gate schema also passed V0–V6 at 100%.

### 6.3 Per-node flatness (leaf prop length distribution per k)

`leaf_shape_stats()`, n=3 problems per k, seed 11:

| k | leaves | min | median | mean | max | δ mix (1 : 2) |
|---|---|---|---|---|---|---|
| 2 | 6 | 98 | 98 | 98.0 | 98 | 4 : 2 |
| 4 | 12 | 98 | 98 | 98.0 | 98 | 6 : 6 |
| 8 | 24 | 98 | 98 | 98.0 | 98 | 14 : 10 |
| 16 | 48 | 98 | 98 | 98.6 | 100 | 28 : 20 |
| 32 | 96 | 98 | 101 | 101.0 | 104 | 40 : 56 |

Leaf statements are **character-identical in length up to k=8**, and the +3 characters at
k=32 are exactly the extra digits in two-digit exponents. The step-kind mix (which
variable moves, δ ∈ {1,2}) is drawn from the same uniform distribution at every k. This
is the structural half of §5.4(a); the prover-facing half (bank pass rate flat in k) is a
post-bake-off measurement.

### 6.4 Scaling headroom

Measured composed-artifact size (seed 3, one problem per k):

| k | max leaf prop chars | goal chars | assembly chars | artifact lines | artifact chars |
|---|---|---|---|---|---|
| 2 | 98 | 98 | 77 | 31 | 2,043 |
| 8 | 98 | 98 | 263 | 115 | 7,725 |
| 32 | 104 | 101 | 1,030 | 451 | 30,867 |
| 128 | 104 | 101 | 4,131 | 1,795 | 124,518 |

The goal and the leaves stay ~100 characters at every k while the *full proof* grows to
125 kB at k=128 (≈30k tokens) — which is exactly the §5.4(e) regime where the flat arm
must run out of window while the isolated arm never sees more than one ~100-character
leaf at a time. The schema does not break above the Phase-1 grid, but note §6.1's k=32
caveat: the *checking* side has its own ceiling (PREAMBLE's `maxHeartbeats`), and it is
the composed oracle artifact, not the statements, that hits it first.

---

## 7. Open items

1. **§5.4(d) flat-prover decay is unproven** (§4). Measure it in Phase 2; if the flat
   arm does not decay, this family measures plan-length capacity rather than difficulty,
   and the transfer claim must lean on Family B.
2. **Leaf pass-rate flatness against the real leaf prover** is a bake-off-time
   measurement; only the structural half is done here.
3. The step schema is a single kind with knobs. A second, genuinely different step kind
   that stays size-bounded would make the intermediates harder to pattern-match; nothing
   in §2's survivor list qualifies without breaking flatness, so it is left open.
4. **PREAMBLE's `maxHeartbeats 400000` is the binding ceiling on the top of the k-grid,
   not the schema.** It is what the first witness version hit at k=32 (§5), and it lives
   in `core/leancode.py` — outside this family's ownership. If Phase 1 wants k=64/128
   oracle replays, that constant (or a per-check `set_option` in `leancode.compose`) has
   to move; the statements themselves stay ~100 characters forever.
5. The endpoint gate is tuned against one family of flat routes (§4.2). It should be
   re-run whenever the automation baseline changes — the probe driver is small and the
   whole sweep costs under two minutes on two workers.
