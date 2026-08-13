# case_tree hardening — survey B: **alternative-obligation** directions

Companion to `research/ct-hardening-survey-a.md` (survey A: algebraic depth — two-atom sums,
quartic radicands, nested radicals). This file covers the other axis: hold the algebra roughly
where it is and change **the kind of proof obligation** a leaf poses.

Everything below was measured on the live local toolchain on 2026-08-12 (Mathlib @ lean
v4.34.0-rc1, stock `PREAMBLE`, `ReplPool(n_workers=3)`). The probe is
`scripts/probes/probe_ct_functional.py`; one command reproduces every number:

```bash
uv run python scripts/probes/probe_ct_functional.py --goals --out <path>.json
```

**4,286 Lean checks in 142.8 s wall** (one batch, `n_workers=3`; the run that produced every
number in this file). No GPU, no LM, no pass@8 — this file establishes the
*battery floor* and an *idiom-ceiling proxy*, which is exactly what `research/retune-notes.md`
§7.1 says a local staging pass can and cannot establish.

---

## 0. TL;DR

| | |
|---|---|
| **Directions probed** | 12 = 9 candidates + `baseline` (shipped schema, same-session control) + `floor_sqrt_loose` (mechanism control) + `floor_product` (combination rung) |
| **Soundness** | 144/144 instances: `holds_at` is an **exact iff** against 60-digit evaluation. 0 under-approximations, 0 over-approximations, 0 coverage failures on a 401-point real grid per band. Nothing was rejected on soundness |
| **Witness** | 144/144 kernel-check (12 directions × 6 knob settings × both variants) |
| **Battery floor** | 144/144 leaves survive the full 20-proof battery; 22/22 assembled k=4 goals elaborate and survive (V0 holds). The planted control **died** to `by intros; nlinarith`, as required |
| **Idiom calibration** | the templated DSV2 idiom closes **68/68** of the measured case_tree leaves (measured pass@8 mean 0.923) — the probe reproduces the measured situation exactly, which is the precondition for reading its *failure* as evidence |
| **Headline** | two directions resist every probed adaptation of the memorised idiom: **`floor_product`** (0/4) and, uniquely, **`floor_sqrt` (tight)** — where the memorised sub-goal `√u ≤ T` is not merely unfound but **false on ~29 % of the band**. `sqrt_product` needs a genuine 2-step composition. Everything else falls to a one-lemma mechanical adaptation |
| **Rejected** | `two_var` (the verbatim idiom closes it **and** necessity collapses as k grows), `abs_v` and `abs_quad` (one-liners), `ceil_sqrt` (one lemma, and its truth certificate is literally the baseline's) |
| **Recommended rungs** | `sqrt_product` (primary, predicted nearest 0.45), `floor_sqrt` (upper rung), `floor_product` (top rung / k=32 reserve), `reciprocal` (lower rung), `baseline` as the same-session control |

The orchestrator's expectation that **abs is easier** is **confirmed** — §4.4.

---

## 1. Why an obligation change rather than a depth change

`research/case-tree-forensics.md` established that case_tree's 0.923 is not a calibration
problem: every knob marginal is flat (0.87–0.99), 50/68 leaves measure a perfect 8/8, and 68/68
successful DSV2-7B proofs run one memorised idiom (`Real.sqrt_le_iff` + `nlinarith [sq_nonneg …]`)
which is essentially the generator's own witness template.

This survey asks whether the *shape* of the obligation can change while keeping the four things
the family stands on: (1) generator self-certification with an **exact integer** truth
certificate; (2) the coverage/necessity machinery; (3) per-node difficulty flat in k; (4) V0/V5/V6.

---

## 2. Soundness first — the exact integer predicates

This is the part that can silently make the family **false**, so it comes before any difficulty
claim. The asymmetry (`case_tree.py` module docstring, and the reason `Real.log` was rejected):

* **coverage** — "the goal is true on the whole real band" — is proven by the generator's witness
  on ℝ, so a *sufficient* condition is fine;
* **necessity** — `_redundant`: piece *i* is needed because some integer point of band *i* is
  covered by no other piece — is exact integer arithmetic, and `holds_at` must **not
  under-approximate** the true super-level set. A predicate that believes a piece covers *less*
  than it does makes the generator claim a necessity it does not have, and ship a k-leaf plan
  that is secretly (k−1)-leaf.

`C = 3` throughout; a piece's obligation is always `atom ≤ T`, because the two variants render as
`C ≤ (C+T) − atom` and `atom − (T−C) ≤ C`.

| direction | piece (max variant) | **exact integer predicate** | why it is an iff |
|---|---|---|---|
| `baseline` | `N − √u`, `u = a(x−m)²+e` | `a(x−m)² ≤ d`, `d = t²−e` | `√u ≤ t ⟺ u ≤ t²` for `t ≥ 0, u ≥ 0` |
| `floor_sqrt` | `N − ↑⌊√u⌋`, cap `T = t−1` | `a(x−m)² + e < (T+1)²` | `⌊r⌋ ≤ T ⟺ r < T+1` (T ∈ ℤ), then `√u < T+1 ⟺ u < (T+1)²` |
| `floor_sqrt_loose` | same, cap `T = t` | `a(x−m)² + e < (t+1)²` | same |
| `floor_product` | `N − ↑⌊√u·√w⌋` | `u(x)·w(x) < (T+1)²` | as floor, after `√u·√w = √(uw)` |
| `ceil_sqrt` | `N − ↑⌈√u⌉` | `a(x−m)² ≤ d` | `⌈r⌉ ≤ t ⟺ r ≤ t` (t ∈ ℤ) — *literally the baseline predicate* |
| `abs_quad` | `N − \|a(x−m)²+e\|` | `a(x−m)² + e ≤ T` | `\|q\| ≤ T ⟺ −T ≤ q ≤ T`; `q ≥ e ≥ 1 > −T` |
| `abs_v` | `N − a·\|x−m\|` | `a·\|x−m\| ≤ T` | direct; both sides integral at integer x |
| `two_var` | `N − √Q`, `Q = a(x−mx)²+b(y−my)²+e` | `a(x−mx)² + b(y−my)² ≤ dq` | as baseline, over ℤ² |
| `sqrt_product` | `N − √u·√w` | `u(x)·w(x) ≤ T²` | `√u·√w = √(uw)` (u,w ≥ 0), then `√(uw) ≤ T ⟺ uw ≤ T²` |
| `reciprocal` | `c / u` (the piece **is** the quotient) | `C·u(x) ≤ c` | `u ≥ e ≥ 1 > 0`, so `le_div_iff₀` applies unconditionally |
| `recip_sqrt` | `c / √u` | `C²·u(x) ≤ c²` | `u > 0 ⇒ √u > 0`; both sides positive, squaring is an iff |
| `min_inside` | `min (A₁−√u₁) (A₂−√u₂)` | conjunction of two baseline predicates | intersection of two exact sets |

### 2.1 Measured, not argued

`check_exactness` re-derives each piece **numerically at 60 decimal digits (mpmath)** from the
same parameters that produced the rendered Lean text, then

* compares `holds_at(x)` against the numeric truth at **every integer of an 81-point window**
  around the vertex (a 41×41 lattice for `two_var`), classifying any disagreement as
  **under-** (disqualifying) or **over-**approximating (safe);
* checks coverage on a **401-point real grid** across the band (20×20 for `two_var`) at tolerance
  10⁻³⁰ — tight enough that the tangency cases are verified rather than waved through
  (`sqrt_product` sits at *exact equality* at the band endpoint by construction);
* measures the real **spill** past the band by 200-step bisection — the quantity the necessity
  repair has to survive.

| direction | under | over | coverage failures | max real spill past band |
|---|---|---|---|---|
| baseline | 0 | 0 | 0 | 2.062 |
| floor_sqrt | 0 | 0 | 0 | 2.062 |
| floor_sqrt_loose | 0 | 0 | 0 | **2.796** |
| floor_product | 0 | 0 | 0 | 2.015 |
| ceil_sqrt | 0 | 0 | 0 | 2.062 |
| abs_quad | 0 | 0 | 0 | 2.000 |
| abs_v | 0 | 0 | 0 | **2.500** |
| two_var | 0 | 0 | 0 | n/a (2-D; §5.3) |
| sqrt_product | 0 | 0 | 0 | 2.000 |
| reciprocal | 0 | 0 | 0 | 2.000 |
| recip_sqrt | 0 | 0 | 0 | 2.132 |
| min_inside | 0 | 0 | 0 | **0.082** |

`min_inside`'s 0.082 is notable: intersecting two capped quadratics all but removes the spill, so
it has the largest necessity margin here (§5.1).

### 2.2 Where each predicate would break — invariants that must be asserted, not assumed

None of these can occur under the shipped knob support. Each must be an *asserted invariant*:

1. **`floor_sqrt` / `floor_product`: the predicate must be written in integers as
   `u(x) < (T+1)²`, never as `floor(sqrt(u)) ≤ T` in floating point.** At k=32 the radicand's
   constant reaches ≈4·10⁴, so `u·w` reaches ≈10⁹–10¹⁸; a float `sqrt` of a perfect square near
   the precision limit can round down and report `⌊√u⌋ = T` where the truth is `T+1`. That is an
   **under-approximation of the complement** — the generator would believe a piece covers a point
   it does not, which breaks **coverage** (a false theorem), not necessity. Writing it as an
   integer comparison makes the failure mode unreachable rather than merely unlikely.
2. **`reciprocal` / `recip_sqrt`: `u > 0` is load-bearing.** In Lean `x/0 = 0`, so if a knob
   combination let the radicand vanish, the piece would evaluate to `0 < C` while the predicate
   `C·u ≤ c` would read `0 ≤ c` = true. Same class as (1): coverage-fatal, necessity-safe.
   `e ≥ 1` plus a negative discriminant gives `u ≥ e ≥ 1`.
3. **`abs_quad`: positive-definiteness is load-bearing.** If `q` could go below `−T`, `|q| ≤ T`
   would fail while the predicate `q ≤ T` would hold — coverage-fatal again.
4. **`sqrt_product` / `floor_product`: `T ≥ 0` and `u, w ≥ 0`.** The squaring step needs both;
   `T = t₁t₂ ≥ 16` and `e₁, e₂ ≥ 1` by construction.
5. **`ceil_sqrt`'s certificate is *identical* to the baseline's.** Worth stating: as a truth
   argument it is a no-op, so it can be added or removed without re-deriving anything.

**No direction here needed an over-approximating fallback, and none was rejected on soundness.**
The one rejection below (`two_var`) is on *necessity dynamics*, which is a different failure.

---

## 3. Method and the four controls

12 instances per direction: 6 knob settings × both variants. The grid spans
`WIDTHS × VERTEX_OFFSETS × CURVATURES × SLACKS` and four vertex magnitudes (|m| from 3 to 20),
because the band's absolute position is the family's single k-dependence.

| check | what runs |
|---|---|
| (a) exactness | §2.1, free |
| (b) witness | the generator-known template, kernel-checked, per instance |
| (c) battery | `families.validate.battery_proofs()` — 10 tactics × {bare, intros-first}, 25 s cap, any success kills — per leaf, **plus** V0 (elaborates + battery) on an assembled k=4 goal per variant |
| (d) idiom ceiling | the templated DSV2 idiom + 2–6 mechanical adaptations per direction |

Four controls, because "everything survives / nothing closes" is only informative if the
instrument can produce the other answer:

1. **Planted positive control** (brief): `∀ x : ℝ, -7 ≤ x → x ≤ 1 → 3 ≤ -2x² - 12x + 17`. Ran in
   the same batch as everything else and **died to `by intros; nlinarith`**. The script raises
   `ControlFailed` and aborts the run if it ever survives.
2. **Same-session `baseline` direction** — the shipped schema through the identical harness, so
   every candidate has a control on the same Mathlib, same day.
3. **Idiom calibration on the measured bank** — before the idiom probe is used as evidence about
   candidates, it is aimed at the 68 measured case_tree leaves in
   `data/bank/family_leaf_calibration.jsonl` (measured pass@8 mean 0.923). It closes **68/68**
   (`I0_verbatim` 68/68, `I1_sq_sqrt` 68/68, `I2_sqrt_le_iff` 68/68; 68/68 parsed, 0 unparsed).
4. **A mechanism control for the headline** — `floor_sqrt_loose`, §4.3.

### 3.1 The idiom template

Read off the emitted proof in the brief and generalised over (band, radicand, cap, vertex) — the
same three things a prover reads off the goal, with the vertex recovered by completing the square
(`m = −c₁/2c₂`), which is exactly the step the expanded rendering is designed to force:

```lean
by
  intro x hx1 hx2
  have h₁ : 0 ≤ Real.sqrt (U) := by apply Real.sqrt_nonneg
  have h₂ : Real.sqrt (U) ≤ T := by
    apply Real.sqrt_le_iff.mpr
    constructor <;> nlinarith [sq_nonneg (x - m), sq_nonneg (x - lo), sq_nonneg (x - hi)]
  nlinarith [sq_nonneg (x - m), sq_nonneg (x - lo), sq_nonneg (x - hi)]
```

`constructor <;> nlinarith [hints]` rather than two bullets makes the probe robust to the
conjunct order of `Real.sqrt_le_iff` (`0 ≤ y ∧ x ≤ y ^ 2` in this Mathlib) — a *strengthening* of
the measured idiom, which is the conservative direction for a ceiling probe.

### 3.2 One probe confound, found and removed — and it moved a headline

The first full pass used `by positivity` for the "`0 ≤ radicand`" side goal inside several
adaptations. **Measured: `positivity` cannot prove `0 ≤ x² + 6x + 17`** — a positive-definite
quadratic is not a sum of syntactically non-negative terms. Seven probes were therefore failing
for a reason with nothing to do with the direction under test, **including the one adaptation
that actually cracks `floor_sqrt`**. Before the fix `floor_sqrt` read 0/12 on all six probes;
after it, `I4_floor_le_iff` reads 12/12. All side goals now use
`nlinarith [sq_nonneg (x − m)]` and the whole run was repeated; §4 is the corrected pass.

Two things follow. (i) The instrument, not the direction, produced the first headline — the kind
of error that would have shipped a wrong recommendation, and the reason the probe now carries a
`positivity`-free invariant in its docstring. (ii) Incidental but reusable: `positivity` in the
V0/V5 battery can never touch these goals, whatever the piece shape.

---

## 4. Results

**Witness and battery: 12/12 and 12/12 for every one of the 12 directions.** Zero kills, zero
witness failures. The 22 assembled k=4 goals (11 directions × 2 variants; `two_var` is excluded
because it has a different case structure) all elaborate and all survive the battery — **V0 holds
everywhere**. The discriminating measurement is therefore (d) alone.

### 4.1 The idiom ceiling

Instances closed, out of 12 (6 knob settings × 2 variants):

| direction | verbatim idiom | probes closing | best closing route | is the memorised sub-goal `√· ≤ T` still **true**? |
|---|---|---|---|---|
| `baseline` (control) | **12/12** | 3/3 | — | yes |
| `two_var` | **12/12** | 3/3 | — | yes |
| `abs_v` | 0/12 | 2/4 | `abs_le.mpr ⟨by linarith, by linarith⟩` | n/a (no √) |
| `abs_quad` | 0/12 | 2/4 | `abs_le` / `abs_of_nonneg` | n/a |
| `ceil_sqrt` | 0/12 | 1/3 | `Int.ceil_le` + `exact_mod_cast` | yes |
| `reciprocal` | 0/12 | 1/4 | `le_div_iff₀` + nlinarith | n/a |
| `min_inside` | 0/12 | 3/4 | `le_min_iff` then the idiom twice | yes (twice) |
| `recip_sqrt` | 0/12 | 1.5/3 (`I1` 12/12, `I2` 6/12) | `Real.sqrt_pos` + `le_div_iff₀` | yes |
| `sqrt_product` | 0/12 | 1/4 | two `sqrt_le_iff` bounds + `mul_le_mul` | yes, but for **two** atoms that must then be multiplied |
| `floor_sqrt_loose` (control) | 0/12 | 1/4 | `Int.floor_le` (⌊r⌋ ≤ r) then bound r | **yes** |
| **`floor_sqrt`** | 0/12 | **1/7** | `Int.floor_le_iff` + `sq_sqrt`-fed nlinarith + cast | **NO — false on ~29 % of the band** |
| **`floor_product`** | 0/12 | **0/4** | none found (witness needs `Real.sqrt_mul` first) | **NO** |

### 4.2 The one qualitative difference: `floor_sqrt` makes the memorised sub-goal *false*

For every other direction the memorised inequality `√u ≤ T` is still **true** on the band and the
work is re-plumbing: reach the atom through `abs_le`, `Int.ceil_le`, `le_div_iff₀`, `le_min`, or
apply the idiom twice and multiply. `floor_sqrt` is tuned so that it is **false**: with
`slack = 1`, `u_max = t² − 1` and the cap is `T = t − 1`, so on the example instance
`u = (x+3)² + 8` over `[−7, 1]`, `√u ≤ 4` fails wherever `|x+3| > 2√2 ≈ 2.83` — about **29 % of
the band** — while `⌊√u⌋ ≤ 4` holds throughout. A prover running the idiom does not merely fail
to find a route; its habitual `have h₂ : √u ≤ T` step is *unprovable*, and it has to notice that
and reach for a strict bound instead.

Six of the seven probed adaptations fail. The one that works needs three ingredients at once:

```lean
by
  intro x hx1 hx2
  have hu : (0:ℝ) ≤ U := by nlinarith [sq_nonneg (x - m)]      -- (positivity does NOT do this)
  have h : (⌊Real.sqrt U⌋ : ℝ) ≤ T := by
    have hz : ⌊Real.sqrt U⌋ ≤ (T : ℤ) := Int.floor_le_iff.mpr (by      -- (i) STRICT floor form
      push_cast
      nlinarith [Real.sq_sqrt hu, Real.sqrt_nonneg U, sq_nonneg (x - m), …])  -- (ii) sq_sqrt, not sqrt_le_iff
    exact_mod_cast hz                                                   -- (iii) ℤ→ℝ cast
  linarith
```

The floor **bracket** route (`⌊r⌋ ≤ r < ⌊r⌋+1` as raw hypotheses, handed to `nlinarith`) is
0/12, and provably must be: with those two facts in context nlinarith still cannot conclude
`⌊r⌋ ≤ T` from `⌊r⌋ < T+1`, because it does not know `↑⌊r⌋` is an integer. **Integrality is the
new obligation**, and the measured idiom contains nothing of that kind.

**Route multiplicity — hard, not knife-edge.** A second generator-known route
(`W1_floor_le_iff_sqrt_lt`: `Int.floor_le_iff` + `Real.sqrt_lt'`, structurally different from the
shipped witness's `Int.floor_lt` + `Int.lt_add_one_iff`) also closes **12/12**. Short proofs
exist; what no probe reached was a short proof *adjacent to the memorised idiom*.

`floor_product` composes the two resistant features (product atom + tight floor) and closes
**0/4** — including `I2_floor_le_iff`, the very route that cracks plain `floor_sqrt`. The witness
has to pass through `Real.sqrt_mul` to turn `√u·√w` into `√(uw)` *before* the floor step, which
no adaptation did.

### 4.3 Mechanism control: it is the calibration, not the `⌊·⌋`

`floor_sqrt_loose` is the same symbol, the same lemma surface, the same rendering, with `T = t`
so that `√u ≤ T` already holds on the band:

| | `Int.floor_le` adaptation (`⌊r⌋ ≤ r`, then bound `r`) |
|---|---|
| `floor_sqrt` (tight) | **0/12** |
| `floor_sqrt_loose` | **12/12** |

One knob, a complete flip. `⌊·⌋` is the device that makes tightness *expressible*; the tightness
is what hardens. This also makes the rung **continuously tunable** — see §6.3.

### 4.4 The orchestrator's abs prediction: confirmed

> "The orchestrator expects this to be EASIER (`abs_le` is as memorised as `sqrt_le_iff`) — test
> it and say so either way."

Confirmed, and worse than expected. Both abs forms fall to a **one-line** adaptation (`abs_v`:
`abs_le.mpr ⟨by linarith, by linarith⟩`; `abs_quad`: `abs_le` or `abs_of_nonneg`), 12/12 each.
`abs_v` is additionally the *shortest* leaf in the survey (44–47 chars vs the baseline's 68–73)
and one of only two directions that degrade necessity (§5.1) — wrong on every axis at once.
**Reject both.**

One non-obvious datum: the verbatim idiom closes **0/12** on abs, because it hard-codes
`Real.sqrt_le_iff`. That is *not* evidence of difficulty. "The verbatim idiom fails" is a
necessary but nowhere near sufficient condition, which is exactly why the adaptation probes exist
and why §3.2's confound mattered.

---

## 5. Structural cost: necessity and flatness

Free checks (no Lean), over real k-band tilings built with each direction's own `holds_at` and
`case_tree._redundant`'s exact integer test.

### 5.1 Necessity — does the repair stay dormant?

`_repair_necessity`'s docstring is explicit that a repair firing at *different rates per k* is
itself a flatness leak. Redundant-piece fraction, 40 tilings per k:

| direction | k=2 | k=4 | k=8 | k=16 | min private points |
|---|---|---|---|---|---|
| baseline | 0 | 0 | 0 | 0 | 1 |
| floor_sqrt | 0 | 0 | 0 | 0 | 1 |
| floor_product | 0 | 0 | 0 | 0 | 1 |
| ceil_sqrt | 0 | 0 | 0 | 0 | 1 |
| abs_quad | 0 | 0 | 0 | 0 | 1 |
| sqrt_product | 0 | 0 | 0 | 0 | 1 |
| reciprocal | 0 | 0 | 0 | 0 | 1 |
| recip_sqrt | 0 | 0 | 0 | 0 | 1 |
| **min_inside** | 0 | 0 | 0 | 0 | **5** |
| `abs_v` | 0 | 0.019 | 0.019 | **0.027** | 0 |
| `floor_sqrt_loose` | 0 | 0.031 | 0.006 | 0.023 | 0 |

`min_inside` leaves each band **five** private integer points instead of one — necessity is not
merely structural but comfortable. `abs_v` and the loose floor both spill far enough (2.5 and 2.8
vs the baseline's 2.06) for two greedy neighbours to swallow a band; a second reason to reject
`abs_v`, and a reminder that the tight floor's smaller spill is a *side benefit* of the same knob
that hardens it.

### 5.2 Flatness in k

Per-k leaf shape, 8 tilings per k. The **outer constant must not grow with k** (only the
radicand's constant may, because the band's absolute position does):

| direction | leaf chars k=2 → k=32 | outer const k=2/4/8/16/32 | max abs coeff at k=32 |
|---|---|---|---|
| baseline | 67.7 → 72.8 | 9/9/9/9/9 | 37,637 |
| floor_sqrt | 75.6 → 80.9 | 8/8/8/8/8 | 35,658 |
| floor_product | 113.1 → 120.9 | 62/62/62/62/62 | 38,308 |
| ceil_sqrt | 75.7 → 80.8 | 9/9/9/9/9 | 37,637 |
| abs_quad | 58.1 → 63.4 | 76/77/77/77/77 | 37,634 |
| abs_v | 44.3 → 47.4 | 15/15/16/16/16 | 111 |
| sqrt_product | 105.4 → 112.9 | 72/72/72/72/72 | 38,308 |
| reciprocal | 58.5 → 63.8 | 228/231/231/231/231 | 37,634 |
| recip_sqrt | 68.1 → 73.4 | 27/27/27/27/27 | 37,634 |
| min_inside | 115.4 → 122.7 | 8/8/8/8/8 | 38,994 |

Every direction keeps the outer constant flat in k, and none changes the coefficient-growth law
(a property of the 1-D tiling, not of the piece). `abs_quad`'s 76→77 and `abs_v`'s 15→16 are the
max over a finite sample drifting up as the sample grows, not growth in k — the *support* of the
outer constant is bounded by the knob support in every case. Two notes:

* `sqrt_product`, `floor_product` and `min_inside` have **~1.6–1.8× longer leaves** (105–123 chars
  vs 68–73). Leaf length is flat *in k*, so this is no flatness leak — but `retune-notes.md` §3
  deliberately held leaf length constant across its ladder so that a measurement would be the
  knob change and not a text-length effect. Across *these* rungs that control is unavailable and
  the pod write-up must say so (§8.5).
* `reciprocal`'s outer constant is large (231) but flat: it is `C·(a·far² + e)`, bounded by the
  knob support.

### 5.3 `two_var`: rejected — the necessity repair does not survive the rectangle

Assessed in full because the brief asks what it costs the assembly, the necessity repair, and
flatness.

**Assembly — cheap either way.** (i) *Strips*: split only in x and let each piece cover the whole
y-range; the assembly is byte-identical to today's, and y is a decoration that adds an obligation
to the leaf without changing the case structure. (ii) *Grid* (kx × ky = k): nested `rcases`,
depth 2, Θ(k) assembly lines; `_paths`/`_chain`'s balanced tree is unchanged (every leaf still at
depth ⌈log₂ k⌉).

**Flatness — the one thing 2-D buys.** A square grid puts the domain at ≈7√k on a side instead of
≈7k, so the radicand's constant grows *linearly* in k instead of quadratically. Measured
`max |coeff|` at k=32: **2,097** on a 4×8 grid against **37,637** for the 1-D tiling — 18×
smaller. If 1-D coefficient growth ever becomes the binding problem, this is the fix.

**Necessity — where it dies.** A piece must cover its cell's **corner**, so its super-level set is
an ellipse `a(x−mx)² + b(y−my)² ≤ dq` with `dq ≥ a·farx² + b·fary²`; any axis-aligned ellipse
containing a rectangle extends √2× past that rectangle's edge midpoints, so with neighbours on all
four sides the union of the neighbours covers the cell. Measured, 12 tilings per grid:

| grid | k | redundant cells | interior cells redundant | edge/corner cells redundant |
|---|---|---|---|---|
| 2×2 | 4 | 0/48 | (no interior cells) | 0/48 |
| 2×4 | 8 | 3/96 (3.1 %) | — | — |
| 3×3 | 9 | 4/108 | **4/12 (33 %)** | 4/96 (4 %) |
| 4×4 | 16 | 32/192 (16.7 %) | **21/48 (44 %)** | 6/144 (4 %) |
| 4×8 | 32 | 64/384 (16.7 %) | — | — |

Redundancy concentrates in **interior** cells, and the interior fraction → 1 as k grows, so the
repair rate is **k-dependent by construction** — the exact flatness leak `_repair_necessity`
warns about. Splitting by the axis "energy ratio" `(b·fary²)/(a·farx²)` does **not** explain it
(balanced 17.4 % vs lopsided 14.6 % at k=16), so this is not a knob-support problem a constraint
could fix. The 1-D `_tighten` (vertex → midpoint, zero slack) has no 2-D analogue that preserves
coverage, because covering the corner is what forces the bulge.

**And the leaf is not harder anyway**: the verbatim idiom closes 12/12 — `nlinarith` finds both
band products by itself, exactly as it finds one today. **Reject.**

---

## 6. The ladder, and the registered predictions

### 6.1 Registered before any GPU measurement (DIRECTION §4 evidence discipline)

The local instrument for the *ceiling* is "does a short route adjacent to the memorised idiom
close it". Two anchors exist for turning that into a number, and they come from two different
families, so the interpolation between them is a prior, not a fit:

| anchor | probe closure | measured mean pass@8 | source |
|---|---|---|---|
| case_tree, current schema | verbatim idiom 68/68 | **0.923** | `data/bank/family_leaf_calibration.jsonl` (n=68) |
| bridge_chain v2 / e1 / e2 / e4 | hand routes 0/6 | **0.196 / 0.283 / 0.267 / 0.312** | `retune-notes.md` §5 + §8 (n=30 each) |
| bridge_chain e3_lowdeg | hand routes 4/6 | **0.429** | same |

The bridge_chain rows carry the single most useful datum here: **a direction where no local probe
closes still measured 0.20–0.31, not 0** — eight samples from a 7B prover find things three
hand-written probes do not. That is why the floor rungs are predicted low-but-not-dead.

Registered predictions, mean pass@8 under the frozen
`deepseek-ai/DeepSeek-Prover-V2-7B | deepseek-prover-v2-non-cot | Mdef | Tdef` profile:

| direction | idiom distance | **predicted mean pass@8** |
|---|---|---|
| baseline | 0 (verbatim closes) | 0.92 *(measured)* |
| two_var | 0 | 0.88 |
| abs_v | 1, one-liner | 0.88 |
| abs_quad | 1 | 0.82 |
| ceil_sqrt | 1 + cast | 0.78 |
| min_inside | 1 + two sub-bounds | 0.66 |
| reciprocal | 1 + a side goal `positivity` cannot do | 0.64 |
| recip_sqrt | 2 + that side goal | 0.52 |
| **sqrt_product** | 2, composed | **0.48** |
| **floor_sqrt** | 3, and the memorised sub-goal is false | **0.25** |
| **floor_product** | ≥4, no probe closes | **0.15** |

**The primary registered claim is the rank order**, which is more robust than the levels:

> `floor_product` < `floor_sqrt` < `sqrt_product` < `recip_sqrt` < `reciprocal` ≈ `min_inside` <
> `ceil_sqrt` < `abs_quad` < `abs_v` ≈ `two_var` ≈ `baseline`

If the pod contradicts the *order*, the "idiom distance" model of this family's difficulty is
wrong, and that contradiction is the finding.

### 6.2 The bimodality risk — why `sqrt_product` is primary and not `floor_sqrt`

The corridor is not only a mean: FAMILIES.md wants **band-fit ≥ 0.60 in [0.25, 0.9]** with
**zero-rate ≤ 0.20**. A rung whose difficulty reduces to "does the model know this one lemma
name" is **bimodal** — leaves land at 8/8 or 0/8 — and a bimodal distribution can hit mean 0.45
with band-fit near zero. Knob retunes gave unimodal distributions almost for free; schema rungs
do not, and nothing in the contract currently covers that case (§8.3).

The design rule that follows:

> **Prefer a rung where a short route exists but is not the memorised one, over a rung that is
> pass/fail on a single unfamiliar lemma name.**

* `sqrt_product` fits: its route composes two *already-memorised* steps (`Real.sqrt_le_iff`
  twice) with one ordinary one (`mul_le_mul`). Whether a given attempt finds it should vary
  attempt to attempt → graded per-leaf rates.
* `floor_sqrt` is the opposite: it turns on `Int.floor_le_iff`/`Real.sqrt_lt'` plus a cast idiom.
  Expect a low mean **with high variance across leaves** — plausibly a good k=16/32 reserve rung
  and a poor corridor centre.
* Mixing rungs inside one family is **not** a fix: a 50/50 mixture of a 0.9 rung and a 0.2 rung
  has mean 0.55 and band-fit ≈ 0.

### 6.3 The continuous knob (and F1's leaf-capacity flag)

`case-tree-forensics.md` flagged that the schema's distinct-leaf capacity is only a few thousand
at k=8 and saturating. The probe's `floor_sqrt` pins `slack = 1`, which would *halve* one knob —
but that is an artifact of deriving the cap through the existing `_cap(d)` pipeline, not a
requirement. The real constraints are

```
coverage:   a·far² + e < (T+1)²          tightness:   a·far² + e > T²
```

so for a chosen `T ≥ max(4, ⌈far·√a⌉)` the pad `e` is free over an interval of **2T** integers
(≈ 8–18 values at the shipped knob support) against the current `SLACKS = (0, 1)`. Sampling `e`
there **increases** leaf capacity roughly 5–9× *and* makes the rung's difficulty continuously
tunable: `e` near the top of the interval is the tight/hard end, near the bottom approaches the
loose control. Given §6.2, a continuous difficulty knob is the most valuable single follow-up in
this survey — it is the mechanism by which a bimodal rung could be pushed toward the corridor
centre.

### 6.4 What to stage for the pod

Five cells × 30 deduped leaves, k ∈ {2,4,8} evenly, on a fresh seed disjoint from 42 / 2026 /
4242:

| cell | why |
|---|---|
| `baseline` | same-session control — the 0.923 must reproduce or the comparison is void |
| `sqrt_product` | primary candidate (predicted nearest 0.45) |
| `floor_sqrt` | upper rung; also the bimodality test |
| `floor_product` | top rung / k=32 reserve; measures whether "no probe closes" bottoms out at ≈0.2 as bridge_chain suggests |
| `reciprocal` | lower rung — identifies whether "one extra lemma" is a real lever at all |

150 statements × 8 attempts ≈ 20 min ≈ $1–2 at the measured 430–480 rows/hr. Report **per-k**
means (R3 is not optional — `retune-notes.md` §8), band-fit, and zero-rate for **every** cell
including the ones that measure badly: a rung that measures 0.05 is as informative about the
idiom-distance model as one that measures 0.45.

---

## 7. What this does **not** establish

1. **No pass@8 was measured.** Everything here is the battery floor (local, definitive) or a proxy
   for the ceiling (idiom probes, indicative). `retune-notes.md` §7.1's caveat applies verbatim:
   a handful of hand probes are not eight DSV2 samples.
2. **The idiom probe is a *sufficiency* test, not a search.** "No adaptation closes it" means the
   memorised route does not generalise; it does not mean a 7B prover cannot find something else.
   The bridge_chain anchor (0/6 probes → 0.20–0.31 measured) puts a number on that gap — and
   §3.2 shows the probe set itself can be wrong in the pessimistic direction.
3. **V3/V4 were not run.** The assembly is unchanged for every 1-D direction and V0/V1 were
   measured on assembled k=4 goals, so the stage-1 plan check and the full oracle compose *should*
   pass — but "should" is not measured. Run `validate_problem` on a real generated problem before
   any direction ships.
4. **Battery resistance is a property of *this* Mathlib.** Same caveat as every previous family
   log. The gate is re-runnable with the planted control attached, so a Mathlib upgrade that
   softens a direction fails loudly rather than silently.
5. **The predictions in §6.1 are anchored on two points from two families.** They rank; they do
   not estimate.
6. **`two_var`'s rejection is on necessity dynamics, not soundness.** Its integer predicate is
   exact. A 2-D piece whose super-level set is a *rectangle* (e.g. a `max` of two 1-D conditions —
   which is `min_inside` in disguise) would dissolve the objection and make the 18×
   coefficient-growth benefit available.
7. **The 6-knob × 2-variant instance grid is deliberate coverage, not a sample.** 12 instances per
   direction detect "this route closes / does not close"; they do not estimate a rate, and a
   direction that closed 6/12 (only `recip_sqrt`'s `I2`) should be read as "variant-dependent",
   not as "50 % likely".

---

## 8. Contract friction (reported, not worked around)

1. **This task owns two files, so the probe's JSON report defaults to `/tmp`.** Other agents are
   working in the tree and writing under `data/` is outside the ownership list. The consequence is
   that the raw per-instance record is **not durable**: whoever picks this up should re-run with
   `--out data/families/ct_functional_probe.json` (or wherever the owner of `data/` wants it).
   Every number in this file is reproducible from the single command in the header.
2. **No staged candidate JSONL was produced**, for the same reason —
   `scripts/stage_retune_candidates.py` is bridge_chain-specific and writes into `data/families/`.
   §6.4 specifies the cells; staging is a follow-up for whoever owns the generator.
3. **FAMILIES.md's corridor gives no guidance for a *bimodal* leaf distribution** (§6.2). The
   band-fit ≥ 0.60 / zero-rate ≤ 0.20 pair was calibrated against knob retunes, where per-leaf
   rates vary continuously. A schema rung can hit the mean and miss both other criteria, and the
   contract does not say what to do then. One sentence in FAMILIES.md would settle it.
4. **`case_tree.Piece` is hard-wired to `a(x−m)² ≤ d`.** Every direction here needs `holds_at`,
   `covers_band` and `_tighten` to become per-schema (a small protocol, or a `schema` field on
   `Piece`). That is a change to a file this task does not own; it is the first implementation
   step for whichever rung is chosen.
5. **`retune-notes.md`'s "hold leaf length constant across the ladder" control is not available
   across schemas** (§5.2): `sqrt_product`, `floor_product` and `min_inside` leaves are 1.6–1.8×
   longer than the baseline's by construction. Flat *in k*, so no flatness leak — but a measured
   difference between those rungs and the baseline is confounded with statement length, and the
   pod write-up must say so.
6. **`positivity` cannot discharge `0 ≤ (positive-definite quadratic)`** (§3.2). Not friction with
   a contract, but a fact that bit this probe and will bite the next one: any witness or probe in
   this family must use `nlinarith [sq_nonneg (x − m)]` for that side goal.

---

## Appendix — the generator witnesses, verbatim

Every template below kernel-checked on 12/12 instances (6 knob settings × both variants). Shown
at the `lo=-7, w=8, off=0, a=1, slack=0/1` instance, max variant; the min variant differs only in
the final `linarith`'s context. These are the `leaf_proof` templates a chosen rung would need.

**`sqrt_product`** — primary recommendation.

```lean
-- ∀ x : ℝ, -7 ≤ x → x ≤ 1 → 3 ≤ 33 - Real.sqrt (x ^ 2 + 6 * x + 18) * Real.sqrt (2 * x ^ 2 + 12 * x + 22)
by
  intro x hl hr
  have hb := mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)
  have h1 : Real.sqrt (x ^ 2 + 6 * x + 18) ≤ 5 := Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith⟩
  have h2 : Real.sqrt (2 * x ^ 2 + 12 * x + 22) ≤ 6 := Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith⟩
  have h3 : Real.sqrt (x ^ 2 + 6 * x + 18) * Real.sqrt (2 * x ^ 2 + 12 * x + 22) ≤ 5 * 6 :=
    mul_le_mul h1 h2 (Real.sqrt_nonneg _) (by norm_num)
  linarith
```

**`floor_sqrt`** — upper rung.

```lean
-- ∀ x : ℝ, -7 ≤ x → x ≤ 1 → 3 ≤ 7 - (⌊Real.sqrt (x ^ 2 + 6 * x + 17)⌋ : ℝ)
by
  intro x hl hr
  have hs : Real.sqrt (x ^ 2 + 6 * x + 17) < 5 := (Real.sqrt_lt' (by norm_num)).mpr (by
    nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)])
  have hf : ⌊Real.sqrt (x ^ 2 + 6 * x + 17)⌋ < (5:ℤ) := Int.floor_lt.mpr (by push_cast; linarith)
  have hf2 : (⌊Real.sqrt (x ^ 2 + 6 * x + 17)⌋ : ℝ) ≤ 4 := by exact_mod_cast Int.lt_add_one_iff.mp hf
  linarith
```

**`floor_product`** — top rung. Note the `Real.sqrt_mul` step: the product must become a single
radical *before* the floor step, which is what no idiom adaptation did.

```lean
-- ∀ x : ℝ, -7 ≤ x → x ≤ 1 →
--   3 ≤ 26 - (⌊Real.sqrt (x ^ 2 + 6 * x + 10) * Real.sqrt (2 * x ^ 2 + 12 * x + 19)⌋ : ℝ)
by
  intro x hl hr
  have hb := mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)
  have hu0 : (0:ℝ) ≤ x ^ 2 + 6 * x + 10 := by nlinarith [sq_nonneg (x + 3)]
  have hw0 : (0:ℝ) ≤ 2 * x ^ 2 + 12 * x + 19 := by nlinarith [sq_nonneg (x + 3)]
  have hu : x ^ 2 + 6 * x + 10 ≤ 17 := by nlinarith
  have hw : 2 * x ^ 2 + 12 * x + 19 ≤ 33 := by nlinarith
  have hp : (x ^ 2 + 6 * x + 10) * (2 * x ^ 2 + 12 * x + 19) < 576 := by nlinarith
  have heq : Real.sqrt (x ^ 2 + 6 * x + 10) * Real.sqrt (2 * x ^ 2 + 12 * x + 19) =
      Real.sqrt ((x ^ 2 + 6 * x + 10) * (2 * x ^ 2 + 12 * x + 19)) :=
    (Real.sqrt_mul hu0 (2 * x ^ 2 + 12 * x + 19)).symm
  have hs : Real.sqrt ((x ^ 2 + 6 * x + 10) * (2 * x ^ 2 + 12 * x + 19)) < 24 :=
    (Real.sqrt_lt' (by norm_num)).mpr (by nlinarith)
  have hlt : Real.sqrt (x ^ 2 + 6 * x + 10) * Real.sqrt (2 * x ^ 2 + 12 * x + 19) < 24 := by
    rw [heq]; exact hs
  have hf : ⌊Real.sqrt (x ^ 2 + 6 * x + 10) * Real.sqrt (2 * x ^ 2 + 12 * x + 19)⌋ < (24:ℤ) :=
    Int.floor_lt.mpr (by push_cast; linarith)
  have hf2 : (⌊Real.sqrt (x ^ 2 + 6 * x + 10) * Real.sqrt (2 * x ^ 2 + 12 * x + 19)⌋ : ℝ) ≤ 23 := by
    exact_mod_cast Int.lt_add_one_iff.mp hf
  linarith
```

**`reciprocal`** — lower rung. Three lines; the whole obligation is the positivity side goal plus
one division lemma.

```lean
-- ∀ x : ℝ, -7 ≤ x → x ≤ 1 → 3 ≤ 51 / (x ^ 2 + 6 * x + 10)
by
  intro x hl hr
  have hu : (0:ℝ) < x ^ 2 + 6 * x + 10 := by nlinarith [sq_nonneg (x + 3)]
  rw [le_div_iff₀ hu]
  nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]
```

**`min_inside`** — not recommended as a rung, but the best necessity margin in the survey (five
private integer points per band vs the baseline's one), so worth keeping if the family ever needs
margin rather than difficulty.

```lean
-- ∀ x : ℝ, -7 ≤ x → x ≤ 1 →
--   3 ≤ min (9 - Real.sqrt (x ^ 2 + 8 * x + 27)) (11 - Real.sqrt (2 * x ^ 2 + 8 * x + 22))
by
  intro x hl hr
  have hb := mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)
  have h1 : Real.sqrt (x ^ 2 + 8 * x + 27) ≤ 6 := Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith⟩
  have h2 : Real.sqrt (2 * x ^ 2 + 8 * x + 22) ≤ 8 := Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith⟩
  exact le_min (by linarith) (by linarith)
```

Mathlib names this survey depends on, all verified present in this toolchain:
`Real.sqrt_le_iff` (`√x ≤ y ↔ 0 ≤ y ∧ x ≤ y^2`), `Real.sqrt_lt'`, `Real.sq_sqrt`,
`Real.sqrt_nonneg`, `Real.sqrt_pos`, `Real.sqrt_mul`, `Int.floor_lt`, `Int.floor_le_iff`,
`Int.floor_le`, `Int.lt_floor_add_one`, `Int.ceil_le`, `Int.lt_add_one_iff`, `abs_le`,
`abs_of_nonneg`, `abs_cases`, `le_min`, `max_le`, `mul_le_mul`, **`le_div_iff₀`** (note: plain
`le_div_iff` / `div_le_iff` are **unknown identifiers** in this Mathlib — the `₀` forms are the
live names).
