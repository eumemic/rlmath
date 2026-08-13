# case_tree hardening ladder — staged schema rungs for the GPU session

Phase 1 is **open on case_tree for the opposite reason it is open on bridge_chain**
(HANDOFF.md §1). bridge_chain measures ~0.13–0.43 and sits *below* the corridor floor;
case_tree measures **pass@8 0.923** over 68 leaves × 8 DeepSeek-Prover-V2-7B attempts and sits
*above* the 0.9 ceiling, with **band-fit 18/68 = 0.265** against the required ≥0.60 and **50/68
leaves at a perfect 8/8**. bridge_chain's fix was a distribution retune. case_tree's cannot be:
`research/case-tree-forensics.md` (F1) shows there is no lever inside the knob support, because
the family measures **template recall**, and template recall has no knob.

This file is the case_tree analogue of `research/retune-notes.md` — same sections, same
discipline, one structural difference: **this is a schema ladder, not a preset ladder**, so
§1 has to say which of `case_tree.py`'s invariants are frozen and which move, and §3's rungs
each carry their own exact integer truth certificate rather than inheriting one.

**Nothing here measures pass@8.** Every number below is one of: a *battery floor* (measured
locally by S1/S2, definitive), a *self-certification* (witness kernel check, definitive), an
*exactness obligation* (predicate audit vs 60-digit arithmetic, definitive), a *free structural
computation* (run here off the shipped generator), or a *ceiling proxy* (idiom probe,
indicative and with a known calibration defect — §5). §6 registers the projections; the pod
decides.

Owned file: this one. `src/rlmath/families/case_tree.py` is **not** edited here — a later agent
implements §3 from this spec, and §9 is the order in which that must happen.

Sources carried forward, cited and not re-run:
`research/case-tree-forensics.md` (F1, measurement forensics),
`research/lever-model-refit.md` (F2, how well a projection of this kind scores out of sample),
`research/ct-hardening-survey-a.md` (S1, algebraic-depth directions),
`research/ct-hardening-survey-b.md` (S2, alternative-obligation directions),
`research/retune-notes.md` (the playbook and its §8 post-mortem).

---

## 0. What to run on the pod (TL;DR)

**Three steps, in this order. The first two are local and cost $0.**

**(0a) Implement the rungs** behind a schema dispatch in `case_tree.py` (§9 step 1) and re-run
the local gate through the *shipped* generator — battery + witness + planted control + full
`validate_problem` (V0–V6). S1/S2 gated hand-built probe instances; nothing has yet been gated
through the code that will materialize the dataset, and **V3/V4 have never been run for any
candidate** (§4). A rung that fails here is dropped before it spends GPU minutes.

**(0b) Stage the candidates** into `data/families/ct_ladder_candidates.jsonl` with a new
`scripts/stage_ct_ladder.py`, mirroring `scripts/stage_retune_candidates.py` row-for-row
(`formal_statement` + `id` are what `build_bank.py` reads; every other column is flat scalar
provenance so the measured bank can be regressed back onto the knobs — that regression is R3′
and R4 below):

```bash
uv run python scripts/stage_ct_ladder.py --with-battery \
  --rungs v2,r1_recip,r2_prod,r2_sum,r3_floor \
  --k-grid 2,4,8 --per-rung 30 --seed 5150
```

5 rungs × 30 deduped leaves, k ∈ {2,4,8} evenly (10 each), globally deduped by
`statement_key`. Seed **5150** is disjoint from 42 (families), 2026 and 4242 (retune).

**(0c) Measure on the pod** — one command, same recipe as `retune-notes.md` §0:

```bash
uv run python scripts/build_bank.py \
  --dataset json --data-files data/families/ct_ladder_candidates.jsonl \
  --out data/bank/ct_ladder_calibration.jsonl \
  --backend repl --workers 4 --concurrent 4 --k 8 \
  --leaf-base-url http://localhost:8000/v1 \
  --leaf-model deepseek-ai/DeepSeek-Prover-V2-7B \
  --leaf-template deepseek-prover-v2-non-cot
```

**Do not pass `--leaf-max-tokens` / `--leaf-temperature`.** The comparison baseline
(`data/bank/family_leaf_calibration.jsonl`, the 68 rows that produced the 0.923) was measured at
`deepseek-ai/DeepSeek-Prover-V2-7B|deepseek-prover-v2-non-cot|Mdef|Tdef`; `leaf_id` carries the
full sampling profile, a different profile is a different experiment, and build_bank's
provenance guard refuses to mix them in one file anyway. Write to a **fresh** `--out`;
`bank_dsv2.jsonl`, `family_leaf_calibration.jsonl` and `retune_measure.jsonl` are the measured
record and stay read-only.

**(0d) Then, in the same pod session, the flatness confirm** — this is not optional and it is
the lesson of `retune-notes.md` §8. Apply §7's R1/R2 to pick the winner, re-stage **60 fresh
leaves at k=2 and 60 at k=8 for that rung only**, and re-run the same command to a second
fresh `--out`. Reason: at the ladder's 10 leaves per k, the 2σ-resolvable per-k gap is **0.22–0.27**
(computed in §7/R3) — the ±0.05 gate cannot be passed *or* failed at that n. At 60 per k it is
**0.09–0.11**, which is a real test.

### Cost

| step | statements × attempts | wall | $ at $3.2/hr (H100 PCIe) |
|---|---|---|---|
| fresh-pod setup (models + Mathlib cache) | — | ~20 min | ~$1.07 |
| (0c) ladder, 5 rungs | 150 × 8 | ~20 min @ 430–480 rows/hr | ~$1.07 |
| (0d) flatness confirm, winner only | 120 × 8 | ~16 min | ~$0.85 |
| optional 6th rung `r4_floorprod` | +30 × 8 | +4 min | +$0.21 |
| **total** | **270–300 × 8** | **~56–60 min** | **~$3.0–3.2 estimated** |

HANDOFF §1: this project's wall-clock estimates ran **~27% low** against the wallet, and
`prime wallet` is the only real number. So **budget $4, cap $6**, and re-check the wallet after
terminating. The standing $30 GPU authorization was spent on the overnight run — **ask before
this pod**.

Then apply §7's decision rule, and only then re-materialize with `gen_families.py` (§9).

---

## 1. What is being hardened, and what is not

`generate(k, seed, n, preset="v2")`. For bridge_chain a "preset" was a `DifficultyPreset` —
coefficient ranges, δ choices, function mixture — over **one unchanged schema**. That is what
kept `research/family-v2-hardening.md`'s measured V0–V6 tables applicable across the whole
ladder, and it is why the retune could be argued from a fitted lever model.

**Here the piece function itself changes.** That is forced, not preferred (§2). The consequences
are three, and they are the reason this file exists rather than a §9 of `retune-notes.md`:

1. **Every rung needs its own truth certificate.** Coverage and necessity are re-derived per
   rung, and the soundness asymmetry (below) is re-checked per rung. S1 and S2 did this work;
   §3 carries the results forward.
2. **The measured V0–V6 tables do not transfer.** They were measured on `√`-capped quadratics.
   Each rung's battery and witness verdicts are S1/S2 measurements on that rung (§4), and V3/V4
   are still unmeasured for all of them (§9 step 2).
3. **Leaf statements change**, so every materialized case_tree artifact is invalidated (§9).

### The soundness asymmetry — get this right or the family becomes false

- **COVERAGE** ("the goal is true on the whole real band") is proven by the generator's witness
  on ℝ. A **sufficient** condition is fine here.
- **NECESSITY** (`_redundant`: piece *i* is needed because some integer point of band *i* is
  covered by no other piece) is exact integer arithmetic, and `holds_at` must **not
  under-approximate** the true super-level set. A predicate that believes a piece covers *less*
  than it truly does makes the generator claim a necessity it does not have and ship a k-leaf
  plan that is secretly (k−1)-leaf. This is exactly why `Real.log` pieces were rejected in the
  module docstring.

Every rung in §3 supplies an **exact (iff)** integer predicate. None needs an over-approximating
fallback. S1 and S2 each audited theirs numerically against 60-digit reference arithmetic
(0 under- and 0 over-approximating mismatches, ~9,600 integer points per direction for S1;
81-point integer windows × 12 instances plus a 401-point real coverage grid at tolerance 10⁻³⁰
for S2). I re-verified the four rung exemplars in §3 independently while writing this file —
predicate vs 60-digit `Decimal`, every integer x in [−12, 6]: exact agreement on all four.

### Frozen — a rung that breaks any of these is not a rung

| # | invariant | where it lives |
|---|---|---|
| F1 | coverage proven on ℝ by the generator's own witness; a *sufficient* certificate is allowed | `Piece.covers_band`, `leaf_proof` |
| F2 | necessity decided by **exact integer** arithmetic that never under-approximates | `Piece.holds_at`, `_redundant` |
| F3 | `_repair_necessity` stays a **no-op at every k** (`leaf_stats()["repaired_frac"] == 0.0`) — a repair firing at different rates per k is itself a flatness leak | `_repair_necessity` docstring |
| F4 | per-node difficulty flat in k: the knob support is k-independent; the **only** k-dependence is the band's absolute position (→ radicand constant). The outer constant must **not** grow with k | module docstring "Flatness in k", `leaf_stats` |
| F5 | balanced `max`/`min` extremum tree, depth ⌈log₂ k⌉, assembly Θ(k log k) | `_chain`, `_paths`, `_wrap` |
| F6 | flat k-way `rcases le_or_gt` assembly, depth 1 at every k | `_assembly` |
| F7 | V0 (goal resists the battery), V5 (every leaf resists it), V6 with `visible_lemmas = []` and no exemption | `validate.py` |
| F8 | `C_LEVEL = 3` — nonzero, so the goal never takes the `0 ≤ e` shape `positivity` attacks | `C_LEVEL` |
| F9 | even band widths (integral midpoints) and `min(WIDTHS) = 6` (the necessity margin F3 rests on) | `WIDTHS` |
| F10 | the radicand never degenerates to a perfect square or a bare `a·x²` (both leak the vertex — the thing the policy must invent); today enforced by `_cap`'s `e ≥ 1` | `_cap` docstring |
| F11 | determinism: output a pure function of `(k, seed, idx)`, extended to `(k, seed, idx, preset)`; `v2` output stays **byte-identical** and keeps the untagged id form | `_rng`, golden tests |

### Moving

`Piece.holds_at`, `covers_band`, `_tighten`, `radicand()`, `outer_const()`, `_piece_term` and
`leaf_proof` all become **per-schema**. `case_tree.Piece` is currently hard-wired to
`a(x−m)² ≤ d`; the dispatch is the first implementation step and S2 flags it as such. The knob
support may also widen (`r3_floor`'s pad interval, `r2_*`'s second atom) — and **every widening
re-opens F3's validity argument**, which must be re-established by the exhaustive knob-cell
sweep, never inherited.

---

## 2. The measured levers — there are none inside the knob support

This is the justification for a schema ladder, so it has to be tight. Three independent lines of
evidence, all measured.

### 2.1 Every knob marginal is flat, and it is not sampling noise

68 case_tree leaves × 8 DSV2 attempts (`data/bank/family_leaf_calibration.jsonl`), joined back
onto the generator knobs by regenerate-and-join on the prop string (F1 §1 — the id suffix is a
flat counter over a combined candidate list, **not** a generator index; all 68/68 rows matched):

| lever | cells | measured mean pass@8 |
|---|---|---|
| variant | max / min | 0.872 / 0.988 |
| curvature `a` | 1 / 2 / 3 | 0.933 / 0.910 / 0.925 |
| width | 6 / 8 | 0.905 / 0.939 |
| vertex offset | −1 / 0 / +1 | 0.890 / 0.940 / 0.944 |
| slack | 0 / 1 | 0.943 / 0.899 |
| cap `t` | 4 … 9 | 0.875 … 1.000 |
| \|vertex\| bucket | low / mid / high | 0.880 / 0.977 / 0.921 |
| max\|coef\| bucket | low / mid / high | 0.885 / 0.938 / 0.949 |
| k | 2 / 4 / 8 | 0.850 / 0.974 / 0.917 |

F1 tested this leaf-by-leaf rather than by eyeballing marginals: Mann-Whitney U on the 18 in-band
vs 50 saturated leaves over width, curvature, offset, slack, cap, pad, d, far, |vertex|,
max|own-coeff|, k and prop length gives **p > 0.4 on every one**, several p > 0.7. The single
significant separator is `variant` (Fisher exact **p = 0.00094**, OR ≈ 10.2), and its purest cell
still measures **0.872**; the hardest stacked cell F1 could find (max ∧ curvature 3 ∧ slack 1,
n=3) measures **0.79** — against a 0.45 target.

Saturation is real and not an artifact: a homogeneous Binomial(8, p̂) is rejected at
χ² = 36.17, df = 2, **p ≈ 1.4×10⁻⁸**; the Beta-Binomial fit (α = 2.48, β = 0.20) implies a true
per-leaf rate SD of **≈ 0.138** with LR = 47.6 vs homogeneous (**p ≈ 5×10⁻¹²**). So the leaves do
differ in true difficulty — **but nothing in the knob support explains the difference**, and at
n=8 an observed 8/8 has a 90% credible interval of [0.717, 0.994], a 0.27-wide band of invisible
difficulty. There is no measurement here to retune against.

### 2.2 The mechanism: one memorised idiom, which is the generator's own witness

Of the 68 leaves with ≥1 success: **68/68** use `nlinarith` **and** `sq_nonneg`; **62/68** name
`Real.sqrt_le_iff.mpr`; **59/68** name `Real.sqrt_nonneg`; mean 9.8 proof lines. F1's taxonomy
collapses all 68 first-proofs into **four signatures and one strategy family**, and the
non-default encodings appear only on already-saturated leaves. The modal emitted proof *is* the
generator's `leaf_proof` template with the cap `t` read straight off the goal as `A − C`.

### 2.3 The state space is small, which forecloses "just sample harder"

Distinct leaf props at k=8 grow sub-linearly with sampling — F1 measured 2194 → 2888 → 3398 →
3723 → 3974 over 500 → 8000 problems. Recomputed here off the shipped generator at seed 4242:
**683 distinct from 100 problems, 2192 from 500, 3385 from 2000** (16,000 leaves drawn). The
schema's true distinct-leaf content space is a bounded few-thousand-item set. The shipped
dataset shows the same thing at small n: `data/families/case_tree/DATASHEET.md` reports **5, 9 and
13 distinct leaf lengths** behind 10, 20 and 40 leaves at k = 2/4/8.

**Conclusion.** The corridor gap is not a distribution problem. `variant`, the one real lever,
caps 0.42 above the target. The piece function has to change.

---

## 3. The ladder

### 3.1 Shape: a one-step star with one join, not a chain

`retune-notes.md` §3 used a chain because bridge_chain's levers were commensurable knobs on one
schema, so "each rung adds one lever" was literally true and a flat result between adjacent rungs
localized the lever. Here the candidate mechanisms are **different kinds of invention** and are
not orderable a priori. So: every rung differs from the **control** by exactly one mechanism, and
one optional rung is the **join** of two of them. A flat result between any rung and the control
identifies that mechanism as inert; a flat result between the join and its two parents identifies
whether the mechanisms compose. This is strictly more mechanism-identification per cell than a
chain, at the same cost. Deviation from the brief's "chain" is deliberate and is this paragraph.

| rung | atoms | cap | prover's obligation | the ONE mechanism added vs `v2` |
|---|---|---|---|---|
| `v2` (control) | 1 | exact, loose | `√u ≤ t` | — (shipped; measured 0.923) |
| `r1_recip` | 1 | — (quotient) | `C·u ≤ c`, behind `le_div_iff₀` | **retarget the closing lemma** — `Real.sqrt_le_iff` no longer applies; one other standard lemma does, plus a positivity side goal `positivity` cannot discharge |
| `r2_prod` | 2, × | exact | `√u·√w ≤ T` | **a second atom** — one `sqrt_le_iff` cannot reach the goal; the visible budget `T` must be split multiplicatively and the two bounds recombined (`mul_le_mul`) |
| `r2_sum` | 2, + | exact | `√u₁ + √u₂ ≤ t` | **the combinator** — same two atoms as `r2_prod`, combined additively: the split is additive and *anchored* near `t/2`, and `linarith` finishes |
| `r3_floor` | 1 | **tight** floor | `⌊√u⌋ ≤ T`, with `√u ≤ T` **false** on ~29% of the band | **integrality + strictness** — the memorised sub-goal is not merely unfound, it is false; a strict bound (`Real.sqrt_lt'`) plus a floor/cast step (`Int.floor_lt`, `exact_mod_cast`) is forced |
| `r4_floorprod` *(optional 6th)* | 2, × | tight floor | `⌊√u·√w⌋ ≤ T` | **composition** — `r2_prod` ⊕ `r3_floor`; `Real.sqrt_mul` must be applied *before* the floor step, an ordering no probed adaptation found |

`r2_prod` and `r2_sum` are a **matched pair**: same atom count, and measured leaf lengths of
105–113 and 104–113 chars respectively. Whatever separates them is the combinator, not the text.

Rung names match `[a-z][a-z0-9_]*` and double as Lean identifier fragments; ids and declaration
names tag them the way bridge_chain does (`case_tree-r2_sum-k4-s5150-3`), while `v2` keeps the
untagged form byte-identical (F11).

### 3.2 `v2` — control

*Not a candidate.* It is the shipped schema, and it is in the run so the 0.923 is re-measured
**on the same pod, the same day, the same sampling profile** as the candidates. If it does not
reproduce, the comparison is void (§7/R0c).

- **piece** — max: `(C+t) − Real.sqrt (a x² + b x + c₀)`; min: `Real.sqrt (…) − (t−C)`, radicand
  `a(x−m)² + e` written expanded.
  Example: `∀ x : ℝ, -7 ≤ x → x ≤ 1 → 3 ≤ 9 - Real.sqrt (2 * x ^ 2 + 12 * x + 22)`
- **exact ℤ predicate** — `a*(x−m)**2 <= d`, `d = t² − e`. Iff because `√u ≤ t ⟺ u ≤ t²` for
  `t ≥ 0, u ≥ 0`.
- **witness** — the shipped `leaf_proof`: one `Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith
  [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]⟩`, then `linarith`.
- **mechanism** — none. This is the template DSV2 has memorised.

### 3.3 `r1_recip` — retarget the closing lemma

- **piece** — the piece *is* the quotient, so there is no outer subtraction. max:
  `C ≤ c / (a x² + b x + c₀)`; min: `2C − c/(…) ≤ C`. The denominator is the same
  positive-definite `a(x−m)² + e`, `e ≥ 1`.
  Example: `∀ x : ℝ, -7 ≤ x → x ≤ 1 → 3 ≤ 51 / (x ^ 2 + 6 * x + 10)`
  (`u = (x+3)² + 1`, band [−7, 1], far = 4, `c = C·(a·far² + e) = 3·17 = 51`).
- **exact ℤ predicate** — `C * (a*(x−m)**2 + e) <= c`. Iff **unconditionally**, because
  `u ≥ e ≥ 1 > 0`, so `le_div_iff₀` applies with no side condition on the truth side.
  Geometry is the baseline's: `a(x−m)² ≤ c/C − e`, so `covers_band` and `_tighten` port over with
  `d = a·far² + slack`. Measured spill 2.000, `_redundant` 0% at k = 2/4/8/16 (S2 §5.1).
- **witness** (S2, kernel-checked 12/12):
  ```lean
  by
    intro x hl hr
    have hu : (0:ℝ) < x ^ 2 + 6 * x + 10 := by nlinarith [sq_nonneg (x + 3)]
    rw [le_div_iff₀ hu]
    nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]
  ```
- **mechanism** — the obligation is still "one lemma, then the band product", but it is a
  *different* lemma and the memorised `Real.sqrt_le_iff` is inapplicable. This is the lightest
  possible schema change, and it is in the ladder precisely to test whether "one extra lemma" is
  a difficulty lever **at all**. If it measures ≈0.9, the idiom-distance model is wrong at the
  easy end and every projection in §6 loses its lower anchor.
- **invariant that must be asserted, not assumed** — `u > 0`. In Lean `x/0 = 0`, so a knob
  combination that let the denominator vanish would make the piece evaluate to `0 < C` while the
  predicate `C·u ≤ c` read `0 ≤ c` = true. That is **coverage-fatal** (a false theorem), not
  necessity-fatal. Negative discriminant plus `e ≥ 1` forecloses it.
- **bonus** — leaves are **shorter** than the control (58–64 chars vs 68–73), so a hardening
  effect here cannot be explained by statement length. See §6.4.

### 3.4 `r2_prod` — a second atom, multiplicatively

- **piece** — `(C+T) − Real.sqrt (u) * Real.sqrt (w)`, with `T = t₁t₂` and the two radicands'
  caps chosen so `u_max = t₁²` and `w_max = t₂²` **exactly**.
  Example: `∀ x : ℝ, -7 ≤ x → x ≤ 1 → 3 ≤ 33 - Real.sqrt (x ^ 2 + 6 * x + 18) * Real.sqrt (2 * x ^ 2 + 12 * x + 22)`
  (`u = (x+3)²+9 → 25 = 5²` at far = 4; `w = 2(x+3)²+4 → 36 = 6²`; `T = 30`).
- **exact ℤ predicate** — `u(x) * w(x) <= T**2`. Iff: `√u·√w = √(uw)` for `u, w ≥ 0`, then
  `√(uw) ≤ T ⟺ uw ≤ T²` for `T ≥ 0`. Note the generator's *witness* uses the weaker split bound
  (`√u ≤ t₁ ∧ √w ≤ t₂`), which is merely sufficient — correct for coverage — while `holds_at`
  uses the exact product form, which is what necessity requires. Because the caps are exact
  squares the super-level set is exactly `[m−far, m+far]`, with **equality at the band endpoint**
  (verified here to 60 digits: the product hits exactly 30 at x = −7). Spill 2.000; `_redundant`
  0% at k = 2/4/8/16.
- **witness** (S2, kernel-checked 12/12):
  ```lean
  by
    intro x hl hr
    have hb := mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)
    have h1 : Real.sqrt (x ^ 2 + 6 * x + 18) ≤ 5 := Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith⟩
    have h2 : Real.sqrt (2 * x ^ 2 + 12 * x + 22) ≤ 6 := Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith⟩
    have h3 : Real.sqrt (x ^ 2 + 6 * x + 18) * Real.sqrt (2 * x ^ 2 + 12 * x + 22) ≤ 5 * 6 :=
      mul_le_mul h1 h2 (Real.sqrt_nonneg _) (by norm_num)
    linarith
  ```
- **mechanism** — one `sqrt_le_iff` cannot reach the goal: the closing route composes **two
  already-memorised steps** with one ordinary one. S2's design rule (§5, and it is the right one)
  is *prefer a rung where a short route exists but is not the memorised one over a rung that is
  pass/fail on a single unfamiliar lemma name*, because the former should give graded per-leaf
  rates and the latter is bimodal. `r2_prod` is the cleanest instance of that rule in either
  survey, which is why it is a primary candidate.
- **caveat this file adds** — S2's cracking probe was **oracle-fed**: it supplied `t₁ = 5` and
  `t₂ = 6`. The prover must find them. Since `u_max = t₁²` and `w_max = t₂²` exactly, the split
  is **unique** — any `s₁ > t₁` forces `s₂ < t₂`, which is false, and any `s₁ < t₁` is false —
  so the target is a single divisor pair of `T`, over the ~4–12 divisor pairs a `T ∈ [16, 324]`
  admits. S1 ran exactly this sweep for `r2_sum` (run C) and S2 did not run it for `r2_prod`, so
  **`r2_prod`'s difficulty is the less well characterised of the matched pair**, in the direction
  of *harder than S2's probe suggests*. Registered accordingly in §6.
- **invariants** — `T ≥ 0` and `u, w ≥ 0` (the squaring step needs both); `T = t₁t₂ ≥ 16` and
  `e₁, e₂ ≥ 1` by construction.

### 3.5 `r2_sum` — the same two atoms, additively

- **piece** — max: `(C+t) − Real.sqrt (u₁) − Real.sqrt (u₂)`; min: `Real.sqrt (u₁) +
  Real.sqrt (u₂) − (t−C) ≤ C`. Both reduce to `√u₁ + √u₂ ≤ t` with `t = cap₁ + cap₂`.
  Example: `∀ x : ℝ, -7 ≤ x → x ≤ -1 → 3 ≤ 12 - Real.sqrt (x ^ 2 + 8 * x + 23) - Real.sqrt (2 * x ^ 2 + 16 * x + 39)`
  (`u₁ = (x+4)²+7 → 16 = 4²` at far = 3; `u₂ = 2(x+4)²+7 → 25 = 5²`; `t = 9`).
- **exact ℤ predicate** — with `s := t² − U₁ − U₂`:
  `holds ⟺ s >= 0 and 4*U₁*U₂ <= s**2`. Iff: square once (both sides ≥ 0) to get
  `U₁+U₂+2√(U₁U₂) ≤ t²`, i.e. `2√(U₁U₂) ≤ s`; square again, legal given `s ≥ 0`. All quantities
  are integers at integer x. Both atoms are convex in x, so the super-level set is an interval
  and the band geometry is unchanged. Mean spill **0.81** — *tighter* than v2's 1.33, because a
  second non-negative atom can only shrink the super-level set. Exhaustive 360-knob-cell sweep:
  max integer reach past a band **2 < width/2 = 3**, 0 cells at threshold (S1 §6.3).
- **witness** (S1, kernel-checked 8/8):
  ```lean
  by
    intro x hl hr
    have hb1 : Real.sqrt (x ^ 2 + 8 * x + 23) ≤ 4 :=
      Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]⟩
    have hb2 : Real.sqrt (2 * x ^ 2 + 16 * x + 39) ≤ 5 :=
      Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]⟩
    linarith
  ```
- **mechanism** — the memorised one-shot fails for a **logical** reason, not a search-budget one:
  `base` bounds `√u₁ ≤ t` and the goal needs `√u₁ + √u₂ ≤ t`, from which `√u₂ ≥ 0` yields
  nothing. The prover must invent a budget split. S1 swept **every** integer split in Lean:
  exactly **1 of 8 / 1 of 15 / 1 of 14 / 1 of 12** closes, always the generator's `cap₁`, and
  offline the feasible split is `cap₁` in **4,000/4,000** instances.
- **why this is the rung with a future** — it is the only direction in either survey that ships a
  **continuous, measured difficulty lever**: `|cap₁ − t/2|`, median 0.5, max 2.0 with two matched
  quadratics, tunable up to 9.0 with a quadratic + quartic second atom. The naive even split *is*
  the generator's split in **719/2000 = 35.9%** of instances. So the target is anchored, the
  anchoring is a per-leaf covariate the pod run will record, and a near-miss on level is
  correctable **within the rung** rather than by switching rungs. F1 proved v2 has no such
  property.
- **capacity caveat** — S1 draws the second atom deterministically from the first
  (`_second_atom_knobs`), which multiplies the *statement* space without multiplying the *knob*
  space. Given §2.3, the implementing agent should measure distinct-leaf capacity for the chosen
  draw and consider an independent second-atom draw if it binds (§10).

### 3.6 `r3_floor` — integrality and a false sub-goal

- **piece** — max: `(C+T) − (⌊Real.sqrt (a x² + b x + c₀)⌋ : ℝ)`; min: `(⌊Real.sqrt (…)⌋ : ℝ) −
  (T−C)`. The cap is **tight**: `T = t − 1` with the pad chosen so `u_max = t² − 1`.
  Example: `∀ x : ℝ, -7 ≤ x → x ≤ 1 → 3 ≤ 7 - (⌊Real.sqrt (x ^ 2 + 6 * x + 17)⌋ : ℝ)`
  (`u = (x+3)²+8 → 24 = 5²−1` at far = 4; `T = 4`).
- **exact ℤ predicate** — `a*(x−m)**2 + e < (T+1)**2`. Iff: `⌊r⌋ ≤ T ⟺ r < T+1` for `T ∈ ℤ`,
  then `√u < T+1 ⟺ u < (T+1)²` since both sides are non-negative; `u(x)` is an integer at
  integer x, so the comparison is pure integer arithmetic. Spill 2.062 — identical to the
  baseline; `_redundant` 0% at k = 2/4/8/16 over 40 tilings each.
- **the invariant that must be asserted** — **write the predicate as the integer comparison
  `u < (T+1)²`, never as `floor(sqrt(u)) ≤ T` in floating point.** At k=32 the radicand's
  constant reaches ~4×10⁴; a float `√` of a perfect square that rounds down reports coverage
  where there is none. That is **coverage-fatal** (a false theorem), not necessity-fatal, and the
  integer form makes it unreachable rather than merely unlikely.
- **witness** (S2, kernel-checked 12/12):
  ```lean
  by
    intro x hl hr
    have hs : Real.sqrt (x ^ 2 + 6 * x + 17) < 5 := (Real.sqrt_lt' (by norm_num)).mpr (by
      nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)])
    have hf : ⌊Real.sqrt (x ^ 2 + 6 * x + 17)⌋ < (5:ℤ) := Int.floor_lt.mpr (by push_cast; linarith)
    have hf2 : (⌊Real.sqrt (x ^ 2 + 6 * x + 17)⌋ : ℝ) ≤ 4 := by exact_mod_cast Int.lt_add_one_iff.mp hf
    linarith
  ```
- **mechanism** — qualitatively different from every other rung: the memorised sub-goal
  `√u ≤ T` is not merely unfound but **false**. Verified here at 60 digits on the exemplar: it
  fails on **29.5%** of the band. The bracket route (`⌊r⌋ ≤ r < ⌊r⌋+1` as raw hypotheses)
  provably cannot work either, because `nlinarith` cannot get `⌊r⌋ ≤ T` from `⌊r⌋ < T+1` without
  knowing `↑⌊r⌋` is an integer. **Integrality is a new obligation**, and S2's loose-vs-tight
  control isolates the cause exactly: the one-line `Int.floor_le` route closes **12/12 on the
  loose cap and 0/12 on the tight one** — same symbol, same lemma surface, one knob different.
  So the hardening is the **tightness calibration**; `⌊·⌋` is only the device that makes
  tightness expressible.
- **the pad knob, and a correction to S2** — the real constraints are `a·far² + e < (T+1)²`
  (coverage) and `a·far² + e > T²` (tightness), so for a chosen `T` the pad `e` ranges over ~2T
  integers instead of `SLACKS = (0,1)`: **5–9× more leaf capacity**, which directly addresses
  §2.3. But S2's further claim that this makes difficulty *continuously* tunable does not
  survive scrutiny: the memorised sub-goal is either false somewhere on the band or it is not, so
  difficulty is a **step function** of tightness, and the loose side of the step is
  `floor_sqrt_loose`, which S2 measured as necessity-degrading (spill 2.796; `_repair_necessity`
  fires at 3.1% / 0.6% / 2.3% at k = 4/8/16 — a k-varying repair rate, i.e. an F3 violation).
  **Spec:** sample `e` over the sub-interval that keeps the measured spill ≤ 2.24 (the shipped
  bound), verify with the exhaustive knob-cell sweep **and** a `_redundant` scan at
  k ∈ {2,4,8,16}, and fall back to the probe's pinned tight value if any repair fires. Capacity
  is the gain; difficulty tuning is not.
- **the risk that puts this rung third, not first** — bimodality. A rung gated on "does the model
  know `Real.sqrt_lt'` / `Int.floor_lt`" lands leaves at 8/8 or 0/8, and a bimodal distribution
  can hit mean 0.45 with band-fit near 0. Registered in §6 as a *predicted R2 failure even if R1
  passes*.

### 3.7 `r4_floorprod` — the join (optional 6th cell)

- **piece** — `(C+T) − (⌊Real.sqrt (u) * Real.sqrt (w)⌋ : ℝ)`, pad bumped until
  `P = u_max·w_max` is not a perfect square, so `T² < P < (T+1)²`.
  Example: `∀ x : ℝ, -7 ≤ x → x ≤ 1 → 3 ≤ 26 - (⌊Real.sqrt (x ^ 2 + 6 * x + 10) * Real.sqrt (2 * x ^ 2 + 12 * x + 19)⌋ : ℝ)`
- **exact ℤ predicate** — `u(x) * w(x) < (T+1)**2`. Same derivation as `r3_floor` after
  `√u·√w = √(uw)`. **The integer form is mandatory, not a preference**: `u·w` reaches ~10¹⁸ at
  k=32, past double precision entirely. Spill 2.015; `_redundant` 0% at all k.
- **witness** — S2's 13-line route through `Real.sqrt_mul` then the floor step; kernel-checked
  12/12 (verbatim in `research/ct-hardening-survey-b.md` §Appendix).
- **mechanism** — composition. `r2_prod`'s cracking route (two bounds + `mul_le_mul`) does **not**
  crack it, and `r3_floor`'s cracking route (`Int.floor_le_iff` + `sq_sqrt`-fed `nlinarith`) does
  **not** crack it either: **0 of 4** probed adaptations close. The witness has to apply
  `Real.sqrt_mul` *before* the floor step, an ordering no adaptation found.
- **why optional** — it is the hardest cell in either survey and is projected below the floor. It
  earns its place only if the run needs a reserve rung for k = 16/32, or if the join estimate is
  worth $0.21. Include it if the budget allows; drop it first if it does not.

### 3.8 Directions considered and NOT staged, with the reason

| direction | source | why not |
|---|---|---|
| `H2_quartic` (√ of a quartic) | S1 | Projected **0.60** — the natural easy rung, and clean on predicate, witness (after S1's degree-staircase fix), battery and necessity. **Rejected for this run on flatness:** its sole k-dependence grows **45,394×** across k = 2→32 (max\|coef\| median 324 → 14,707,723; worst k=32 leaf 4.7×10⁸) vs v2's 134×. F1 measured coefficient magnitude as difficulty-neutral, but only over the range 1–2,200. Shipping it before R3′ measures that axis would be bridge_chain's R3 failure with a different variable name. Reinstate after R3′. |
| `H4_twoatom_quartic` | S1 | Same flatness leak (**52,488×**), plus projected 0.05 and every non-oracle route 0/8; the even split is the generator's split in **0 of 2,000** instances. Top-of-ladder reserve only. |
| `H3_nested` (`√(u + √v)`) | S1 | Projected 0.30 — legitimate, exact, battery-surviving, spill 0.87. Omitted for **budget**: it occupies the same band as `r3_floor` and adds no mechanism the ladder does not already have. First reserve if a k=16/32 rung is needed. |
| `two_var` | S2 | **Rejected on measurement, twice.** The verbatim memorised idiom closes it **12/12** (no hardening at all — `nlinarith` finds both band products by itself), *and* necessity collapses with k: redundant-piece fraction 0 → 3.1% → **16.7%** → 16.7% at k = 4/8/16/32, concentrated in interior cells (21/48 interior vs 6/144 edge). Interior fraction → 1 as k grows, so the repair rate is k-dependent **by construction** — an F3 violation. Residual value: a 2-D piece whose super-level set is a *rectangle* would dissolve the objection and buy an 18× reduction in coefficient growth. |
| `abs_quad`, `abs_v` | S2 | **Easier**, as the orchestrator predicted — 2 of 4 adaptations close 12/12 for each, and `abs_v`'s closing proof is three lines of `linarith`. `abs_v` additionally spills 2.500 and fires the repair at 1.9–2.7%, k-varying (F3). Reported as a measured negative. |
| `ceil_sqrt` | S2 | Predicate is **literally the baseline's** (`⌈r⌉ ≤ t ⟺ r ≤ t` composes with `√u ≤ t ⟺ u ≤ t²`), so as a truth argument the ceiling is a no-op; one lemma (`Int.ceil_le`) closes 12/12; projected 0.78. Retained as the **explanatory control for `r3_floor`** — same symbol class, opposite verdict, because ceiling needs `≤` and a tight floor needs strict + integrality. |
| `min_inside` | S2 | Too easy as a rung (3 of 4 adaptations close; projected 0.66) — conjunctive obligations turn out to be a routing change, not a difficulty change. **Retained as the necessity-margin tool:** it leaves **5** private integer points per band vs the baseline's 1, spill 0.082. This is the construction to reach for if a widened knob support ever threatens F3. |
| `recip_sqrt` | S2 | Projected 0.52, in band, sound — but it occupies `r2_prod`'s slot with one more positivity side goal and no measured advantage. Add as a 7th cell only if budget is free. |
| `floor_sqrt_loose` | S2 | Mechanism control, never a candidate. Its 0/12-vs-12/12 flip against `r3_floor` on one knob is the cleanest causal isolation in either survey. |

---

## 4. Local gate — carried over from S1 and S2, not re-run here

All measured 2026-08-12 on local `ReplPool`, Mathlib @ lean v4.34.0-rc1, stock `PREAMBLE`.
Battery = `families.validate.battery_proofs()`, 10 tactics × {bare, intros-first}, 25 s cap,
**any** success kills.

| rung | instances | battery | witness kernel-checks | exact-predicate audit | `_redundant` at k = 2/4/8/16 | source |
|---|---|---|---|---|---|---|
| `v2` | 8 (S1) + 12 (S2) | survives, 0 kills | 8/8, 12/12 | 0 under / 0 over | 0% (min 1 private pt) | S1 §3, S2 §4 |
| `r1_recip` | 12 | survives 12/12, 0 kills | 12/12 | 0 under / 0 over | 0% | S2 |
| `r2_prod` | 12 | survives 12/12, 0 kills | 12/12 | 0 under / 0 over | 0% | S2 |
| `r2_sum` | 8 | survives 8/8 (160 checks) | 8/8 | 0 under / 0 over over 9,644 pts | 0%, exhaustive 360-cell sweep: max reach 2 < 3 | S1 |
| `r3_floor` | 12 | survives 12/12, 0 kills | 12/12 | 0 under / 0 over | 0% (0/640 pieces at k=16) | S2 |
| `r4_floorprod` | 12 | survives 12/12, 0 kills | 12/12 | 0 under / 0 over | 0% | S2 |

**The planted control was live in both surveys.** S1 ran the known-dead v1-shape leaf
(`∀ x : ℝ, -7 ≤ x → x ≤ 1 → 3 ≤ -2x² - 12x + 17`) through the same pool and it **died to
`by intros; nlinarith`**; S2's planted positive control died the same way in the same batch. So
"everything survives" is a measurement, not a dead gate. S2 additionally assembled k=4 goals for
each direction in both variants and confirmed **V0 holds** (goal resists the battery).

**Two methodological findings from those runs that this ladder inherits:**

1. **`positivity` cannot prove `0 ≤ (positive-definite quadratic)`** — a positive-definite
   quadratic is not a sum of syntactically non-negative terms. Every witness and probe in this
   family must use `nlinarith [sq_nonneg (x − m)]` for that side goal. S2's first full pass
   produced a **wrong headline** because seven probes used `by positivity` there and failed for
   a reason unrelated to the direction under test — including the one route that actually cracks
   `r3_floor`. An idiom-ceiling probe can be wrong in the **pessimistic** direction, and the only
   defence is reading each failure's error text rather than counting failures.
2. **`le_div_iff` / `div_le_iff` are unknown identifiers in this Mathlib**; the live names are
   `le_div_iff₀` / `div_le_iff₀`. And `Real.sqrt_le_iff` is `√x ≤ y ↔ 0 ≤ y ∧ x ≤ y^2` —
   non-negativity **first**, which is why the generator's `⟨by norm_num, by nlinarith […]⟩`
   works.

### What was NOT gated, and must be before the pod

- **V3 (stage-1 plan check) and V4 (full oracle compose + sanitizer + axiom audit) have never
  been run for any candidate.** The assembly is unchanged for every rung and V0/V1/V2/V5 were
  measured, so they *should* pass — but "should" is not measured, and bridge_chain already hit a
  k=32 V3 elaboration wall once. §9 step 2 makes this a blocking pre-flight.
- **Nothing was gated through the shipped generator.** S1 and S2 built instances in their own
  probe scripts. The battery/witness verdicts are about the *props*, which will be
  byte-identical if the implementation is faithful — but that is exactly what a re-run of the
  gate through `case_tree.build` checks, and it is free.
- **`r3_floor`'s widened pad support was not gated** (the probe pinned the tight value). §3.6.

---

## 5. The idiom probe as the corridor-ceiling instrument

### What it is

Both surveys templated the *measured* DSV2 idiom over the things a prover reads off the goal —
band, radicand, cap, and the vertex recovered by completing the square (`m = −c₁/2c₂`), which is
exactly the step the expanded rendering is designed to force. The hint bag is the measured one:
`sq_nonneg` at the vertex plus both band endpoints (the bank's proofs pass
`sq_nonneg (x + 2), sq_nonneg (x - 1), sq_nonneg (x + 7)` for band [−7, 1] with vertex −2). S1
probed `Real.sqrt_le_iff`'s conjunct order at runtime rather than guessing it; S2 used
`constructor <;> nlinarith [hints]` so the probe is robust to that order. Both are deliberately
**generous**: the model has to find the vertex and the template is handed it, so a direction the
oracle-hinted idiom cannot close is one the model certainly cannot close by copying.

### Its calibration on the control rung

| calibration | result |
|---|---|
| S2, all 68 measured case_tree leaves regex-parsed back to (lo, hi, radicand, cap, vertex) | 68/68 parsed; **verbatim idiom closes 68/68** against measured mean 0.923 |
| S2, 12 freshly generated baseline instances | 12/12 — the calibration is not an artifact of the bank's particular leaves |
| S1, stratified sample: all 18 leaves with pass@8 < 1.0 (including the single 0.25 leaf) + 10 at 1.0 | **28/28**, i.e. **18/18 of the hard stratum** |

### What it predicts, and what it does not

**Does:** whether the memorised one-shot *applies* to a piece shape. That is a binary, per-schema
property, and it is measured with a live planted control on both sides.

**Does not:** graded difficulty. S1's stratified re-calibration is decisive and is the biggest
caveat in this file: the base idiom **closes the 0.25 leaf**. A deterministic single-shot proof
has no sampling variance to model, so the instrument reproduces the 0.923 only in the weak sense
that the prover's real route exists and the template is it. It does **not** reproduce the
0.25→1.0 spread and it cannot.

**Consequence for §6.** "Base fails" licenses only *"the memorised one-shot stops applying at the
schema level"*. The ordering among rungs is carried entirely by (i) the **adaptation ladder** —
which second-attempt route closes, and how far it is from the template — and (ii) the **offline
target-width measurements** (how many candidate splits are feasible, and whether the obvious
guess is one of them). Both are hand-constructed routes, and `retune-notes.md` §7.1's disclaimer
applies verbatim: three hand routes are not eight DSV2 samples, and the measured bank later
produced a 20-line chained proof no hand probe would have found.

### The adaptation ladder, per rung (the actual ranking signal)

| rung | verbatim idiom | adaptations probed | first route that closes | distance |
|---|---|---|---|---|
| `v2` | **8/8, 12/12, 68/68** | — | base | 0 |
| `r1_recip` | 0/12 | 4 | `le_div_iff₀` + `nlinarith` → 12/12 | 1 + a side goal `positivity` cannot do |
| `r2_prod` | 0/12 | 4 | two `Real.sqrt_le_iff` + `mul_le_mul` → 12/12 | 2, composed of memorised steps |
| `r2_sum` | 0/8 | 5 | oracle split → 8/8; **even split 4/8**; both-full 0/8; sq_sqrt 0/8 | 1 `have` + 1 invented integer, anchored |
| `r3_floor` | 0/12 | 7 | only `Int.floor_le_iff` + `sq_sqrt`-fed `nlinarith` + `exact_mod_cast` → 12/12 (a 2nd structurally different route also 12/12) | 3, and the memorised sub-goal is **false** |
| `r4_floorprod` | 0/12 | 4 | **none** | ≥ 4 |

---

## 6. Registered predictions — written before the GPU run

### 6.1 The reasoning chain (there is no fitted model, so this is the whole basis)

F1's finding is that no lever exists inside the knob support, which is the same as saying **no
model can be fitted** for this ladder. So each projection is an explicit interpolation between
three anchors and a mechanism argument, and it is stated as such.

**The anchors — all of them:**

| anchor | local probe result | measured mean pass@8 | n |
|---|---|---|---|
| case_tree `v2` | verbatim idiom closes 68/68 | **0.923** | 68 leaves × 8 |
| bridge_chain `e3_lowdeg` | short hand route closes 4/6 | **0.429** | 30 × 8 |
| bridge_chain `v2` / `e1` / `e2` / `e4` | hand routes close **0/6** | **0.196 / 0.283 / 0.267 / 0.312** | 30 × 8 each |

**The single most load-bearing regularity: probe-fails does NOT mean zero.** Four bridge_chain
presets where no local probe closed still measured **0.20–0.31**. Eight samples from a 7B prover
find things three hand routes do not. Both surveys' sub-0.20 projections (S1's H4 at 0.05, S2's
`floor_product` at 0.15) sit **below the only measured floor that exists for "no probe closes"**,
and I shade them upward accordingly.

**The competing consideration, which widens the intervals rather than moving the centres:**
DSV2 is *extraordinarily* templated on this family — 68/68 successes, one strategy. bridge_chain's
0.2–0.3 floor came from a family where sampling found long chained proofs; if case_tree's prover
has literally one route, any schema change could collapse it toward 0.05–0.15 across the board.
That world is registered explicitly as L3 below.

**How much to trust this.** F2 scored bridge_chain's §5 projections at **MAE 0.044, Pearson
r = 0.83, Spearman ρ = 0.70**, with one adjacent rank flip and the R1 decision correct under both
projected and measured numbers. That is encouraging but it is **not** the right reference class:
that projection was a *fitted three-factor cell model within one schema on 58 measured leaves*.
Here there is no fit, the rungs are outside any measured support (F1: there is **no** measured
case_tree leaf for which the base idiom fails), and the anchors come from two different families.
**Expect MAE ≈ 0.15–0.20, not 0.044.** The intervals below are ±0.20–0.25 wide on purpose, and
the **rank order is the primary registered claim** because it is far more robust than any level.

### 6.2 Per-rung projections

Band-fit is projected from an explicit leaf-level mixture, not guessed. At n=8 attempts the band
[0.25, 0.9] excludes exactly the outcomes 0/8, 1/8 and 8/8, so for a leaf of true rate p,
band-fit probability is `1 − (1−p)⁸ − 8p(1−p)⁷ − p⁸`: 0.34 at p=0.15, 0.63 at 0.25, 0.94 at 0.45,
0.97 at 0.62, 0.57 at 0.90, 0.34 at 0.95. The killer is **heterogeneity**, not the mean — which
is why each row below states the assumed leaf-rate mixture.

| rung | projected mean pass@8 | interval | assumed leaf mixture | projected band-fit | projected zero-rate | corridor verdict |
|---|---|---|---|---|---|---|
| `v2` (control) | **0.92** | 0.86 – 0.98 | reproduce the measured distribution | **0.27** | 0.00 | above the ceiling (as measured) |
| `r1_recip` | **0.62** | 0.40 – 0.85 | 40% @ 0.95, 60% @ 0.40 | **0.65** | ≤ 0.05 | in band, high side |
| `r2_prod` | **0.42** | 0.20 – 0.70 | 25% @ 0.80, 50% @ 0.45, 25% @ 0.15 | **0.72** | 0.08 | **in band, near target** |
| `r2_sum` | **0.48** | 0.25 – 0.72 | 30% @ 0.80, 45% @ 0.45, 25% @ 0.20 | **0.78** | 0.06 | **in band, near target** |
| `r3_floor` | **0.28** | 0.05 – 0.55 | **bimodal**: 45% @ 0.60, 55% @ 0.02 | **0.44** | **0.47** | level may pass R1; **predicted to FAIL R2 on zero-rate** |
| `r4_floorprod` *(opt)* | **0.15** | 0.02 – 0.40 | 25% @ 0.50, 75% @ 0.03 | **0.26** | **0.59** | **below the floor; predicted to fail R2** |

Notes on the two centre rungs. `r2_sum` is placed marginally above `r2_prod` because its numeric
target is **anchored** (the even split is right 35.9% of the time; `|cap₁ − t/2|` median 0.5) and
its closing step is `linarith`, whereas `r2_prod`'s split is a divisor pair with no measured
anchor and its closing step is `mul_le_mul` with non-negativity side conditions — **and** because
S2's `r2_prod` probe was oracle-fed while S1 ran the split sweep for `r2_sum` (§3.4). That gap is
0.06 and it is **inside the noise**: no confident ordering is registered within the pair. The
pair exists to measure the combinator, not to be ranked.

### 6.3 Ladder-level registered claims

| id | claim | confidence |
|---|---|---|
| **L1** | Rank order holds exactly: `v2 > r1_recip > {r2_sum ≈ r2_prod} > r3_floor > r4_floorprod` | 0.55 |
| **L1c** | Coarse order holds: `v2 > {r2_prod, r2_sum} > r3_floor` | 0.85 |
| **L2** | At least one of `r2_prod` / `r2_sum` passes **both** R1-relevance (mean ∈ [0.25, 0.9]) and R2 (band-fit ≥ 0.60, zeros ≤ 0.20) | 0.55 |
| **L3** | **Overshoot:** all four non-control rungs measure **< 0.25** (the "DSV2 has exactly one route" world) | 0.20 |
| **L4** | **Undershoot:** all four measure **> 0.9** (no rung hardens anything) | 0.05 |
| **L5** | The `v2` control reproduces inside [0.86, 0.98] | 0.90 |
| **L6** | `r3_floor` is measurably bimodal: > 40% of its leaves land at exactly 0/8 or 8/8 | 0.65 |
| **L7** | `r2_sum`'s continuous lever is real: pass@8 regressed on `\|cap₁ − t/2\|` has a negative slope at \|z\| ≥ 2 | 0.45 (n=30 is thin for a covariate with median 0.5, max 2.0) |
| **L8** | No rung shows a significant coefficient-magnitude gradient (R3′ pooled slope \|z\| < 2) | 0.70 |

**Overshoot is as much a failure as undershoot** and L3 is registered at 0.20, which is not
small. The ladder brackets 0.45 from both sides on purpose: `r1_recip` at 0.62 and the `v2`
control at 0.92 above it, `r3_floor` at 0.28 and (optionally) `r4_floorprod` at 0.15 below it.
If the pod contradicts any of this, **the contradiction is the finding** and it should be written
up as such rather than patched.

### 6.4 The one confound this ladder cannot hold constant, and its partial control

`retune-notes.md` §3 deliberately held leaf length flat at 176–178 chars across its whole ladder,
so a measured difference was the knob change and not a text-length effect. **That control is
unavailable across schemas.** Measured leaf lengths (k=2 → k=32): `v2` 68→73, `r1_recip` 58→64,
`r3_floor` 76→81, `r2_sum` 104→113, `r2_prod` 105→113, `r4_floorprod` 113→121. All flat *in k*,
so there is no flatness leak — but they differ across rungs by up to 1.8×.

Two designed partial controls:

1. **`r2_prod` vs `r2_sum` is length-matched** (105–113 vs 104–113), so the combinator comparison
   is clean.
2. **`r1_recip` is SHORTER than the control and predicted HARDER.** If it measures below `v2`,
   statement length cannot be the explanation for that rung — which weakens the length story for
   the whole ladder. This is the main reason `r1_recip` earned a cell over the algebraic-axis
   alternative `H3_nested`.

The pod write-up must state the confound regardless.

---

## 7. Decision rule for the GPU session

Applied to `data/bank/ct_ladder_calibration.jsonl` after the run, in order. Adaptations from
`retune-notes.md` §6 are flagged with **[adapted]** and carry a stated reason, per the brief.

**R0 — validity.** Ignore rows with `status == "error"` (re-run with `--repair`). A row with
`elaborates == false` is a generator bug and blocks its rung outright.

**R0b — full validation, per rung. [new]** Before *any* rung is eligible, `validate_problem`
(V0–V6, automation battery on) must pass on ≥3 freshly generated problems at each of
k ∈ {2, 4, 8} for that rung, plus one k=32 problem for V1/V3 elaboration cost. Reason: this is a
**schema** ladder, V3 and V4 have never been run for any candidate (§4), and the piece function
is exactly what V4's compose/sanitize/axiom-audit path exercises. This is local and free and
belongs in step (0a), not after the pod — a rung that fails it should never have been measured.

**R0c — control reproduction, blocking. [new]** If the same-pod `v2` cell does not measure a
mean inside **[0.85, 0.98]**, the whole comparison is void: report that, and do not select a
rung. Reason: every projection in §6 is anchored on 0.923; a control that does not reproduce
means the sampling profile, the prover build, or the harness differs from the run that produced
the anchor, and no candidate number is interpretable against it.

**R1 — level (primary).** Pick the rung whose **mean measured pass@8 is nearest 0.45**.

> **R1 tie rule (added 2026-08-13 after the science review; blocking fix).** R1 as written has no
> tolerance, so at this n it decides the shipped schema by sampling noise. At 30 leaves × 8
> attempts the SD of a rung's measured mean is 0.041–0.057 and the SE of a pairwise difference is
> ~0.07–0.08, while the two primary candidates are projected only 0.06 apart. Monte Carlo over
> §6.2's *own* registered mixtures (20,000 reps) makes R1 a coin flip between them — `r2_prod`
> wins 58.6%, `r2_sum` 39.2%, and P(measured `r2_prod` > `r2_sum`) = 0.323 despite the projection
> ordering them the other way. §6.2 explicitly registers **no** ordering inside the pair, so R1
> as written converts an unregistered ordering into a shipping decision.
> **Rule: R1 declares a TIE when two rungs' means differ by less than 0.08 (1 SE of the
> difference at n=30); ties fall through to R4.** The write-up must then say "the pair was
> statistically indistinguishable; X was chosen on R4.n", never "X is the harder combinator".

**R2 — band fit.** Require **band-fit ≥ 0.60** (share of the rung's 30 leaves with measured
pass@8 ∈ [0.25, 0.9]) **and zero-rate ≤ 0.20** (share measured 0/8). Unchanged from
`retune-notes.md` §6, including its arithmetic justification: a leaf whose true rate is 0.5 lands
outside [0.25, 0.9] about 3.9% of the time, so a literal "all 30 in band" rejects a
perfectly-centred rung ~70% of the time.

**R2b — bimodality diagnostic, reported not gated. [new]** Also report, per rung, the share of
leaves at exactly 0/8 **or** 8/8. Reason: FAMILIES.md's corridor was calibrated against knob
retunes, which give unimodal leaf distributions almost for free; schema rungs do not (§3.6, S2
§6.2). If that share exceeds 0.40, say so explicitly — R2's band-fit clause is then doing the work
it was designed for, and the rung should not be described as "mean 0.45" without the qualifier. A
50/50 mixture of a 0.9 rung and a 0.2 rung has mean 0.55 and band-fit ≈ 0; mixing rungs is
therefore **not** a fix for a rung that misses the corridor.

**R3 — flatness must not regress. [adapted — and this is the rule that was silently skipped last
time]**

- **Report per-k means (k = 2/4/8) and the max pairwise gap for EVERY rung, shipped or not.**
  This is non-negotiable. `retune-notes.md` §8: R1 and R2 were applied at the session close, R3
  was never evaluated, and that is how a failing family got written up as DONE.
- **The literal ±0.05 tolerance is not resolvable at this n, and that is arithmetic, not
  opinion.** With 10 leaves per k and 8 attempts each, the leaf-clustered SE of a per-k mean is
  0.079–0.095 (leaf-rate SD 0.25–0.30), so the 2σ-detectable pairwise gap is **0.22–0.27**.
  Resolving ±0.05 at 2σ needs **~288 leaves per k** (≈ 6× this session's entire budget, per rung).
  Detecting 0.10 needs 72/k; 0.15 needs 32/k. bridge_chain's R3 failure was detectable only
  because the spread was 0.325.
- **Operational form:**
  - **FAIL** if any pairwise per-k gap ≥ **0.20**, or any pairwise difference is ≥ 2 SE on the
    leaf-clustered SE.
  - **UNRESOLVED** if the winning rung's max gap is in (0.05, 0.20) and not 2σ — which is the
    likely outcome. UNRESOLVED **blocks Phase-1 close** and triggers step (0d): 60 fresh leaves
    at each of k=2 and k=8 for the winner, where the detectable gap falls to 0.09–0.11.
  - **PASS** only if the max gap is ≤ 0.05, and even then record that at this n a pass is a point
    estimate, not a demonstration.
- **Pool for power. [new]** Also fit `pass_rate ~ C(k) + C(rung)` over all 150 rows and report the
  k contrasts with SEs: at 50 leaves per k the detectable gap falls to ~0.12, which is a real
  test of whether *the schema family* is flat, as distinct from whether one rung is. Test the
  rung × k interaction first; if it is significant, fall back to per-rung means only.

**R3′ — coefficient magnitude. [new axis]** Regress measured pass@8 on `log10(max|coef|)`,
pooled over all rows with rung fixed effects, and report the slope with its SE. Reason and power:
the schema's *only* k-dependence is the band's absolute position, which drives the radicand's
constant — so coefficient magnitude is the mechanistically correct flatness variable, and a
continuous covariate on 150 leaves is a **more powerful** test than three bins of ten. Computed
here off the shipped generator: `log10(max|coef|)` has mean 2.12 and SD **0.65** pooled over
k ∈ {2,4,8} (per-k medians 28 / 99 / 333, rising to 1,380 at k=16 and 5,336 at k=32 — a 2.05-decade
shift from k=2 to k=32). With SD 0.65 and 150 rows, SE(slope) ≈ 0.04/decade, so a gradient large
enough to move the mean by 0.16 across the full k-grid is detectable. F1 measured this axis as
flat (0.885/0.938/0.949) but only over the range 1–2,200 and only at the saturated ceiling, where
nothing is detectable. **R3′ is a prerequisite for ever staging a quartic rung** (§3.8), and it
protects the staged rungs too.

**R4 — tie-break**, in order:
1. flatter per-k profile (R3's max gap);
2. **graded over bimodal** (R2b's share at 0/8 or 8/8);
3. larger distinct-leaf capacity — FAMILIES.md's GRPO-correlation note asks datasheets for
   distinct-leaf counts, and §2.3 shows this schema's capacity is only a few thousand at k=8;
4. shorter leaf statement (§6.4's confound);
5. for `r2_sum` specifically, the presence of a working continuous lever: regress pass@8 on
   `|cap₁ − t/2|` (shipped on every candidate row). A significant negative slope means a
   near-miss on level is correctable **within** the rung, which no other rung offers.

**R5 — oracle ceiling (added 2026-08-13; blocking fix, $0).** The corridor is a **per-leaf**
statement; Phase 1's gate (DIRECTION §5.5b) is a **per-episode** one — oracle replay must close
*all* k leaves at ≥70%. These are not the same number and R1–R4 never touched the second.
From each rung's measured per-leaf rates compute `(1 − (1−p)^a)^k` at k ∈ {2,4,8,16,32}, for the
shipped `Budgets` (`a = min(4, 64//k)`) **and** for a raised flat `a = 8`, and report it beside
R1/R2. Three lines of arithmetic on the calibration file.

Why it is blocking: at the R1 target of 0.45 the shipped budget yields **0.825 / 0.681 / 0.464 /
0.215 / 0.000** — the ≥70% gate fails **from k=4 upward**. The shipped `v2` passes it only by
being too easy, i.e. by failing requirement (c). At a flat 8 attempts/leaf the same 0.45 yields
0.983 / 0.967 / 0.935 / 0.874 / 0.764 and the gate holds. So **a rung is not disqualified by a low
oracle ceiling under the shipped budget** — the budget is the free variable (task #22,
DIRECTION §5.4(b′)) — but the write-up must state the ceiling explicitly rather than let "mean
0.45" imply Phase 1 is satisfied.

**Report every rung's numbers, including the ones that measure badly.** A rung that measures 0.05
is as informative about the mechanism model as one that measures 0.45.

### 7.1 EASING ladder — if NO rung lands in the corridor because all are too hard

(The brief calls this the escalation case; naming it by direction avoids ambiguity, since this
family is being made *harder* and "escalate" could mean either.)

Trigger: every non-control rung measures mean < 0.25, i.e. L3.

1. **Read `r1_recip` first.** It is by construction the lightest schema change in either survey
   (one lemma retarget, shorter statements). If even `r1_recip` is below 0.25, the finding is
   *"any schema change collapses this prover"* — a real and publishable result about how narrow
   DSV2's route repertoire is on synthetic families — and the correct next move is **not** more
   schema search. Go to FAMILIES.md direction 1: **bank-drawn leaves** from the 401 in-band
   statements in `bank_dsv2.jsonl` (299 train / 102 eval), through `families/leaf_split.py`.
2. **If only the two-atom rungs are low**, tune *within* `r2_sum` using its measured lever:
   restrict to `|cap₁ − t/2| ≤ 0.5` (the anchored end, where the even split is the answer). This
   is the reason `r2_sum` is in the run at all and it costs one knob-range change, not a schema
   change.
3. **`min_inside`** (S2) as an easier two-atom conjunction — projected 0.66, already locally
   gated, and it carries the best necessity margin in either survey (5 private integer points per
   band). It is the natural rung between `v2` and the two-atom pair.
4. **`ceil_sqrt`** (projected 0.78) as the minimal legal change, if even `min_inside` is too hard.

### 7.2 HARDENING ladder — if EVERY rung overshoots the other way (nothing bites)

Trigger: every non-control rung measures mean > 0.9, i.e. L4 — the schema changes are cosmetic
to this prover.

1. **Add `r4_floorprod`** — already staged and locally gated; 0 of 4 adaptations close it; it is
   the composition of the two mechanisms that individually failed to bite.
2. **`H3_nested`** (S1, projected 0.30) — exact, battery-surviving, spill 0.87, and in 2 of 4
   probe cells the generator's inner cap **exceeds the visible budget `t`**, so the numeric target
   is not even bounded by what the goal shows.
3. **`H2_quartic` / `H4_twoatom_quartic`** — *only after R3′ has returned a null slope*. They are
   the highest-leverage remaining directions (H2 projected 0.60 and it is otherwise clean on every
   axis) but their coefficient growth is 45,000×/52,000× over the k-grid, and shipping either
   before R3′ repeats bridge_chain's exact mistake.
4. **Composition beyond the surveys** — e.g. `r2_sum` ⊕ `r3_floor` (tight floor over a two-atom
   sum). Unmeasured; would need a fresh local gate with a live planted control before staging.

---

## 8. What this does NOT establish

1. **No pass@8 was measured, here or in either survey.** Everything is a battery floor (local,
   definitive), a self-certification (definitive), an exactness audit (definitive), a free
   structural computation (definitive), or a ceiling proxy (indicative).
2. **The idiom probe does not discriminate within a schema.** It closes 18/18 of the sub-ceiling
   stratum including the single 0.25 leaf. "Base fails" is a statement about route applicability,
   not about difficulty. Every ordering in §6 rests on the adaptation ladder and the offline
   target widths — hand-constructed routes, not samples.
3. **The projections are extrapolations off the measured support.** There is no measured
   case_tree leaf for which the base idiom fails. The anchors are two families and six points.
   They rank; they do not estimate a value. Expected MAE ≈ 0.15–0.20 (§6.1).
4. **Battery resistance is a property of *this* Mathlib** (lean v4.34.0-rc1, stock PREAMBLE), and
   `nlinarith`'s pair-product preprocessing in particular. S1 showed how thin some of these
   barriers are: `H2_quartic`'s base failure is a hint-repertoire artifact — supplying a product
   `nlinarith` could in principle synthesise from context turns 0/8 into 8/8. The mitigation is
   that the gate is re-runnable with its planted control attached, so a Mathlib upgrade that
   softens a rung fails loudly.
5. **The `_repair_necessity` no-op (F3) is exhaustive over the CURRENT knob support, not an
   analytic bound.** `r3_floor`'s pad widening and `r2_*`'s second atom both change that support.
   Re-run the sweep; do not inherit the result.
6. **V3 and V4 remain unmeasured for every rung** until §9 step 2 runs.
7. **Leaf length is not held constant across rungs** (§6.4). Two partial controls exist; neither
   is a substitute.
8. **R3 as literally written (±0.05) is not attainable at any budget this project will spend**
   (~288 leaves per k per rung). §7's operational form is what will actually be evaluated, and
   the honest reading of a passing rung is "no gap larger than 0.09–0.11 was detected at k=2 vs
   k=8", not "flat to ±0.05".
9. **Nothing here says anything about k=16 or k=32.** The whole ladder is measured at
   k ∈ {2,4,8}, and case_tree's coefficient magnitude keeps growing past that (median 1,380 at
   k=16, 5,336 at k=32). R3′ is the instrument that would catch a problem there; it is not a
   measurement at those k.

---

## 9. ORDER OF OPERATIONS — the chosen rung invalidates every existing case_tree artifact

**This is a hard constraint, not a cleanup note.** A rung changes leaf *statements*. Statements
are what `statement_key` hashes, what `leaf_split` derives membership from, and what the measured
bank is keyed on. Nothing downstream survives a rung change untouched.

**Step 1 — implement, do not materialize.** Add a schema dispatch to `case_tree.py`.
`Piece` is hard-wired to `a(x−m)² ≤ d`, so `holds_at`, `covers_band`, `_tighten`, `radicand`,
`outer_const`, `_piece_term` and `leaf_proof` must become per-schema (a `PieceSchema` protocol,
or a `schema` field with dispatch). Mirror `bridge_chain.PRESETS`: a module-level dict keyed by
rung name, each entry carrying its rationale, its knob support, and its own witness renderer.
**Use the kwarg name `preset`** even though these are schemas — `gen_families.py --preset` already
passes `preset=` through to the registry generator, and reusing it avoids touching a file this
work does not own. `v2` stays the default and byte-identical (F11), pinned by a golden test.

**Step 2 — local pre-flight, blocking (R0b).** Re-run the battery + witness + **planted control**
through the shipped generator for every rung, and run `validate_problem` (V0–V6) on ≥3 problems
per k ∈ {2,4,8} per rung plus one k=32 for elaboration cost. Free; ~78 s bought 15 validated rows
last time. Drop any rung that fails.

**Step 3 — stage.** `scripts/stage_ct_ladder.py` → `data/families/ct_ladder_candidates.jsonl`,
seed 5150, 30 deduped leaves per rung, k ∈ {2,4,8} evenly, globally deduped by `statement_key`.
Emit the per-leaf covariates R3′ and R4 need: `max_abs_coeff`, `leaf_chars`, `cap`, `pad`,
`width`, `curvature`, `offset`, and for `r2_sum` the lever `abs(cap1 - t/2)`.

**Step 4 — measure** (§0c), **then decide** (§7), **then the flatness confirm** (§0d).

**Step 5 — re-materialize, and only now.** These artifacts are **v2 output at seed 42** and become
stale the moment a non-`v2` rung is chosen:

- `data/families/case_tree/k2.jsonl`, `k4.jsonl`, `k8.jsonl` — 15 problems, 70 leaves;
- `data/families/case_tree/DATASHEET.md` — its V0–V6 table, its leaf-length distribution and its
  `repaired_frac` all describe the old piece function;
- any downstream episode/eval config that reads those files.

Regenerate with `gen_families.py --family case_tree --preset <rung> --k-grid 2,4,8 --n 5
--validate` and **re-run the full validator**, not a structural pass: V0/V5 verdicts do not
transfer across piece functions.

The 68 measured rows in `data/bank/family_leaf_calibration.jsonl` are **not** deleted or
regenerated — they remain the measured record of the v2 state and the anchor for the 0.923. They
simply stop being *this family's* calibration once a rung ships.

### Leaf-disjointness (FAMILIES.md) applies to the regenerated leaves — and it does not currently work here

FAMILIES.md's contract is binding "before any v2 dataset": membership is a pure function of
`statement_key` via `families/leaf_split.py` (last hex nibble, 25% eval); **TRAIN problems at any
k draw leaves exclusively from the train pool, EVAL problems exclusively from the eval pool**;
datasets record the pool per problem and the gen CLI must refuse mixed draws.

Three facts the implementing agent needs, in order of severity:

1. **It is not implemented for family-generated leaves at all.** `leaf_pool` is written by
   `breed_mutants.py` and read by `run_zeroshot.py` "when their generator drew from the bank";
   `gen_families.py` has no pool logic whatsoever, so today's case_tree rows are `unrecorded`.
   The regeneration in step 5 is where this first bites, because it is the first case_tree dataset
   materialized *after* the contract became binding.
2. **Problem-level rejection sampling is infeasible and must not be attempted.** A case_tree
   problem has k leaves, each with its own key. P(all k leaves land in train) = 0.75^k =
   **0.56 / 0.32 / 0.10 / 0.010 / 0.0001** at k = 2/4/8/16/32; for eval it is 0.25^k, i.e.
   1.5×10⁻⁵ at k=8. The correct implementation is **leaf-level** rejection: resample each piece
   until its statement's key nibble matches the problem's target pool (expected 1.33 draws for
   train, 4.0 for eval). This is legitimate because `statement_key` is a sha256 prefix, so the
   last nibble is independent of the knob values — but that independence should be *checked*
   (χ² of the knob marginals by pool) rather than assumed, and it must be done inside the
   deterministic RNG stream so F11 survives.
3. **The eval pool is capacity-thin, and this ladder makes it thinner.** §2.3 measures the
   schema's distinct-leaf space at ~3.4k at k=8; the eval pool is 25% of that, ≈850 distinct
   leaves. `r2_sum`'s second atom is drawn deterministically from the first, so it multiplies the
   statement space without multiplying the knob space. The datasheet must report distinct-leaf
   counts **and leaf-reuse distribution per pool** (FAMILIES.md's GRPO-correlation note), and if
   the eval pool binds, an independent second-atom draw is the fix.

---

## 10. Contract friction (reported, not worked around — none of these files are owned here)

1. **`FAMILIES.md` gives no operational guidance for a BIMODAL leaf distribution.** band-fit
   ≥ 0.60 / zero-rate ≤ 0.20 was calibrated against knob retunes, which vary continuously. A
   schema rung whose difficulty reduces to "does the model know this lemma name" lands leaves at
   8/8 or 0/8 and can hit mean 0.45 with band-fit ≈ 0 (§6.2's `r3_floor` row is exactly this).
   Mixing rungs is not a fix. **One sentence in FAMILIES.md would settle what to do.** Carried
   forward from S2's flag; restated because this ladder is the first run where it will bite.
2. **R3's ±0.05 tolerance is unattainable at any realistic n** (~288 leaves per k per rung;
   §7/R3). Implemented as the three-way FAIL / UNRESOLVED / PASS rule with a budgeted 60-per-k
   confirm for the winner. Same class of friction as `retune-notes.md` §8.1's R2 arithmetic, one
   gate over. If the strategist wants the literal form, it costs ~6× this session per rung.
3. **`case_tree` has no written R-rules of its own until this file.** §7 is the first. It should
   be referenced from `FAMILIES.md` alongside `retune-notes.md` §6, or the next agent will adopt
   bridge_chain's informally again — which is how R3 got skipped.
4. **`FAMILIES.md`'s leaf-disjointness contract is unimplementable as literally written for a
   synthetic k-leaf generator** (§9: P(all k leaves in one pool) → 0). The leaf-level rejection
   reading is the only feasible one and should be written into the contract explicitly, together
   with the requirement that the datasheet report per-pool distinct-leaf counts.
5. **`gen_families.py --preset` is a `preset=` kwarg passthrough**, so a case_tree *schema* has to
   masquerade as a preset to be materializable from the CLI. Workable and recommended (§9 step 1),
   but the naming will mislead: a bridge_chain preset does not change the schema and a case_tree
   "preset" does. A `--schema` alias, or one line of help text, would fix it.
6. **`data/families/case_tree/DATASHEET.md` and its `k*.jsonl` predate the ladder** and carry no
   `preset` field. They remain valid *v2* artifacts (v2 output stays byte-identical); consumers
   should read `meta.get("preset", "v2")` from here on.
7. **S2's probe report defaults to `/tmp/ct_functional_probe/report.json`** because that task owned
   only two files, so survey B's per-instance raw records are **not durable** while survey A's
   (`data/families/ct_probe_a/*.json`) are. Re-running S2's probe with
   `--out data/families/ct_probe_b/report.json` before the pod session would make §4's table
   reproducible from artifacts rather than from a note. Cheap and worth doing.
8. **No staged candidate file exists yet**, so §0's pod command references a path that step (0b)
   creates. `scripts/stage_retune_candidates.py` is bridge_chain-specific. This is the one place
   where this file is weaker than `retune-notes.md` §0, which could quote a file that already
   existed — stated plainly rather than papered over.
9. **HANDOFF §1's money correction applies to §0's cost table.** Every pre-2026-08-12 estimate in
   this repo ran ~27% low against `prime wallet`, and the overnight pod overran its authorized cap.
   §0 quotes the estimate *and* a budget with headroom; quote the wallet afterwards, not the
   estimate.

---

## 11. Local gate results (measured 2026-08-13)

**Headline: the gate killed nothing, and the gate can kill.** The planted control died to
`by intros; nlinarith` in the same pool, on its own, before any rung was measured; then
**7,920 automation-battery proof attempts over 316 distinct propositions produced exactly one
kill, and it was the control.** All six rungs — `v2`, `r1_recip`, `r2_prod`, `r2_sum`,
`r3_floor`, `r4_floorprod` — survive V0/V5, kernel-check **1,315 of 1,315** generator witnesses,
audit 0-under/0-over against 60-digit `Decimal` over 10,788 integer points, hold
`repaired_frac == 0.0` at every k ∈ {2,4,8,16,32}, and pass the **full validator V0–V6 on 9
problems each (54/54)** — which closes §4's "V3/V4 have never been run for any candidate" gap and
§9 step 2's blocking pre-flight.

**One rung has a defect, and it is not a battery kill: `r4_floorprod` fails V4 at k = 32** —
3 of 3 seeds, `maxHeartbeats` exhausted while elaborating the composed artifact. §11.8 shows this
is an elaboration-budget wall shared by the whole family (the **shipped `v2` control fails the
same way at k = 128**), that every rung's wall moves out by ≥ 1 doubling of k when
`maxHeartbeats` is raised 4×, and that `r4_floorprod` is the only rung whose wall lands *inside*
the k-grid FAMILIES.md ships.

Everything below was measured on this box, local `ReplPool(n_workers=4)`, Mathlib @
lean v4.34.0-rc1, stock `PREAMBLE` (`maxHeartbeats 400000`), **$0 of GPU**, ~42 minutes wall.
Nothing here measures pass@8; §6's projections are untouched and remain registered as written.
Where a measurement contradicts §3/§6's *reasoning* it is called out in §11.10 — the registered
numbers themselves are left alone on purpose.

### 11.1 What ran

| phase | what | Lean checks | wall |
|---|---|---|---|
| offline | staging + structural report + necessity sweep + predicate audit + capacity/target-width/tightness | 0 | ~30 s |
| stager gate | planted control → battery on 6 coefficient-extreme leaves + 1 goal per rung → witness on those → **`validate_problem` V0–V6 × 54 problems** | ~7,700 | 337 s |
| extended gate | control (again, alone) → battery on a **knob-spanning** subset + goal per rung → **witness on all 179 staged leaves** → idiom probe → k=32 structural validation | ~1,600 | 232 s |
| scaling probe | V1–V4/V6 (automation off) at k = 16 / 32 / 64, 3 seeds where it mattered | ~1,400 | 697 s |
| heartbeat diagnostic | recompose the failing artifacts with `set_option maxHeartbeats` raised | 12 | 1,050 s |

Reproduce — the stager phase is one command:

```bash
uv run python scripts/stage_ct_candidates.py \
  --rungs v2,r1_recip,r2_prod,r2_sum,r3_floor,r4_floorprod \
  --k-grid 2,4,8 --per-rung 30 --seed 5150 \
  --battery-n 6 --with-battery --validate --validate-n 3 --workers 4
```

and the other four phases are the drivers in
`data/families/ct_battery/gate_scripts/` (`offline.py`, `extended.py`, `k32.py`,
`heartbeat.py`+`hb2.py`, `rowmap.py`; each is `uv run python <file>` and takes no arguments).
They sit under `data/` only because this agent owned `data/families/ct_battery/**` and not
`scripts/**` — their home is `scripts/probes/`, and moving them is a no-op apart from the import
shim at the top of each file. Recorded so §10.7's "survey B's raw records were not durable"
failure does not repeat one gate later; flagged in §11.13.

**Deviation from §0b, deliberate:** six rungs, not five. The optional `r4_floorprod` costs +$0.21
on the pod (§0), the local gate is free, and §7.2's escalation ladder opens with exactly that
rung — staging it now means the overshoot branch needs no re-stage. The pod drops it with
`grep -v '"preset": "r4_floorprod"'`; the first five rungs' rows are byte-identical either way
(global dedupe runs in rung order and `r4_floorprod` is last).

Also noted for the record: the file name is `scripts/stage_ct_candidates.py` →
`data/families/ct_candidates.jsonl`, not §0b's `stage_ct_ladder.py` →
`ct_ladder_candidates.jsonl`. §0b's quoted pod command therefore still points at a path that does
not exist; §10.8 predicted this friction and it is now real. **The pod command in §0c must read
`--data-files data/families/ct_candidates.jsonl`.**

### 11.2 The planted control — first, and on its own

Run before any rung was touched, in the same pool, with the same 20-proof battery:

| prop | verdict | killed by | wall |
|---|---|---|---|
| `∀ x : ℝ, -7 ≤ x → x ≤ 1 → 3 ≤ -2 * x ^ 2 - 12 * x + 17` | **DEAD** | `by intros; nlinarith` | 0.14 s |

Run twice (once inside `stage_ct_candidates.py --with-battery`, once standalone in the extended
gate); both died. **The gate can kill, so "everything survives" below is a measurement.** Had it
survived, the whole gate would have been aborted and reported as void — that branch was
implemented and did not fire.

### 11.3 Offline structural table (per rung)

179 rows staged, seed 5150, k ∈ {2,4,8}, globally deduped by `statement_key`.

| rung | leaves | k mix (2/4/8) | variant (max/min) | leaf chars min/med/max | log10 max\|coef\| min/mean/max | distinct knob cells | distinct statements | deduped | invariant violations |
|---|---|---|---|---|---|---|---|---|---|
| `v2` | 30 | 10/10/10 | 18/12 | 63/69/75 | 1.23/2.04/3.34 | 20 | 30 | 0 | **0** |
| `r1_recip` | **29** | 9/10/10 | 17/12 | 53/62/71 | 0.70/1.95/3.27 | 22 | 29 | **1** | **0** |
| `r2_prod` | 30 | 10/10/10 | 18/12 | 85/107/117 | 1.00/2.14/3.28 | 23 | 30 | 0 | **0** |
| `r2_sum` | 30 | 10/10/10 | 18/12 | 100/108/116 | 1.11/2.17/3.34 | 27 | 30 | 0 | **0** |
| `r3_floor` | 30 | 10/10/10 | 18/12 | 71/77/84 | 1.04/2.04/3.28 | 21 | 30 | 0 | **0** |
| `r4_floorprod` | 30 | 10/10/10 | 18/12 | 110/115/125 | 1.11/2.18/3.34 | 26 | 30 | 0 | **0** |

`r1_recip` emits 29, not 30: one k=2 statement collided with an earlier one and was dropped by the
global dedupe. That is the schema's small state space (§2.3) showing up at n=30, not a bug — and
it slightly under-powers that rung's k=2 cell (9 leaves, not 10). The variant mix is identical
(18/12, or 17/12) across every rung, which is the stager's interleaving doing the job it was added
for: `variant` is the one knob F1 measured as a real separator, and it is now balanced by
construction rather than by luck.

**Necessity and exactness, per rung** (F2/F3, re-established never inherited):

| rung | knob cells swept | max spill | threshold `min(WIDTHS)/2` | cells at threshold | predicate audit (k ∈ 2/4/8/16/32) | `repaired_frac` at k = 2/4/8/16/32 |
|---|---|---|---|---|---|---|
| `v2` | 36 | 2 | 3 | 0 | 1,798 pts, **0 under / 0 over** | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 |
| `r1_recip` | 36 | 2 | 3 | 0 | 1,798 pts, **0 under / 0 over** | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 |
| `r2_prod` | 72 | 2 | 3 | 0 | 1,798 pts, **0 under / 0 over** | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 |
| `r2_sum` | 72 | 2 | 3 | 0 | 1,798 pts, **0 under / 0 over** | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 |
| `r3_floor` | 36 | 2 | 3 | 0 | 1,798 pts, **0 under / 0 over** | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 |
| `r4_floorprod` | 72 | 2 | 3 | 0 | 1,798 pts, **0 under / 0 over** | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 |

10,788 audited integer points, 0 mismatches in **either** direction. F3 holds exhaustively over
every rung's whole widened knob support (the two-atom rungs sweep 72 cells, not 36), and
`_repair_necessity` fired **zero times** in every problem generated during this gate.

**Flatness structurals** (10 problems per cell, seed 7777; the numbers F4 constrains):

| rung | leaf chars k=2 → k=32 | median \|coef\| k=2 → k=32 | max `outer_const` over the FULL knob support (max/min variant) |
|---|---|---|---|
| `v2` | 67.2 → 72.9 | 36 → 32,449 | 12 / 6 |
| `r1_recip` | 59.6 → 65.6 | 33 → 33,709 | 231 / 231 |
| `r2_prod` | 104.0 → 112.7 | 54 → 34,993 | 75 / 69 |
| `r2_sum` | 103.8 → 112.3 | 53 → 35,007 | 20 / 14 |
| `r3_floor` | 75.1 → 80.5 | 48 → 34,371 | 12 / 6 |
| `r4_floorprod` | 111.6 → 120.7 | 51 → 33,077 | 65 / 59 |

`knob_support_ok` is `True` for every rung at every k. Leaf length grows 6–9 characters across a
16× change in k — flat. The outer constant is **exactly** k-independent: the right-hand column is
an exhaustive maximum over the rung's whole knob support (36 or 72 cells), and it does not depend
on band position, so F4 is verified rather than sampled. The **only** k-dependence is the
radicand constant, ~1,000× from k=2 to k=32, which is precisely what R3′ exists to test.

**R3′ power, computed on the staged rows:** `log10(max|coef|)` has mean 2.088 and SD **0.722**
over the 179 rows, so `SE(slope) ≈ 0.031` per decade at a residual SD of 0.30 — slightly better
than §7/R3′'s projected 0.04, and the k=2→32 span is 2.05 decades, so a gradient large enough to
move the mean by 0.13 across the full grid is 2σ-detectable.

**Distinct-leaf capacity** (300 problems at k=8, seed 4242 — FAMILIES.md's GRPO-correlation note,
§7/R4.3's tie-break):

| rung | distinct leaf props / 2,400 leaves | distinct knob tuples |
|---|---|---|
| `v2` | 1,628 | 36 |
| `r1_recip` | 1,631 | 36 |
| `r2_prod` | **1,976** | **72** |
| `r2_sum` | **1,984** | **72** |
| `r3_floor` | 1,560 | 36 |
| `r4_floorprod` | 1,929 | 72 |

The two-atom rungs buy **+22% distinct leaves and 2× the knob cells** over the control — the
independent second-atom draw the implementation chose over S1's derived one (§3.5's capacity
caveat) is measurably doing what it was meant to. `r3_floor` is the **only rung below the
control** on capacity (1,560 vs 1,628, −4%), which is the measured cost of §3.6's pad being pinned
rather than widened; it also confirms the implementer's flag that r3_floor's capacity concern
(§2.3) is unaddressed.

### 11.4 Kill table — the automation battery (V0/V5)

`families.validate.battery_proofs()`, 10 tactics × {bare, intros-first}, 25 s cap, **any** success
kills. The subset is not random: per rung it is the coefficient extremes at each k **plus** a
greedy cover of every observed knob value, so each rung's probe set covers **k ∈ {2,4,8}, both
variants, both widths, all three curvatures, all three offsets, both slacks** (and all three
`curvature2` values on the two-atom rungs) — printed per rung in `gate_battery_ext.json`.

| rung | leaf probes | knob cells covered | goal probe (V0) | **kills** |
|---|---|---|---|---|
| `v2` | 7 | k 2/4/8 · max,min · w 6,8 · a 1,2,3 · off −1,0,1 · slack 0,1 | k=8 | **0** |
| `r1_recip` | 6 | same | k=8 | **0** |
| `r2_prod` | 7 | same + `curvature2` 1,2,3 | k=8 | **0** |
| `r2_sum` | 6 | same + `curvature2` 1,2,3 | k=8 | **0** |
| `r3_floor` | 7 | same | k=8 | **0** |
| `r4_floorprod` | 7 | same + `curvature2` 1,2,3 | k=8 | **0** |
| **planted control** | 1 | — | — | **1 — `by intros; nlinarith`** |

Pooling every battery run in this gate (extended spanning subset, the stager's coefficient-extreme
subset, all 54 validator problems' V0 + V5, and the control):

> **7,920 battery proof attempts · 316 distinct propositions · 1 kill · the kill is the control.**

**No rung is DEAD by battery.** V0 holds on every probed goal and V5 holds on every probed leaf,
now measured through the *shipped generator* rather than a survey's own probe script — which is
what §4 said had never been done.

### 11.5 Witness kernel checks — every staged leaf, not a subset

| rung | staged leaves checked | pass | failures |
|---|---|---|---|
| `v2` | 30 | **30** | 0 |
| `r1_recip` | 29 | **29** | 0 |
| `r2_prod` | 30 | **30** | 0 |
| `r2_sum` | 30 | **30** | 0 |
| `r3_floor` | 30 | **30** | 0 |
| `r4_floorprod` | 30 | **30** | 0 |

Adding the witnesses checked inside V2 of the 54 validator problems (252), the k=32 structural
runs (192), the stager's own subset (36) and the k=16/32/64 scaling probe (656):

> **1,315 witness kernel checks · 1,315 pass · 0 failures, at every k up to 64.**

Every rung's witness template therefore covers its whole knob support, including the structurally
special cells the implementer flagged (`r3_floor`'s `T = C_LEVEL` and `e = 0` floors,
`r4_floorprod`'s perfect-square pad bump). A witness failure here would have been a generator bug
reaching the GPU; there is none.

### 11.6 The idiom probe (the corridor-ceiling proxy)

The measured DSV2 idiom, mechanically retargeted at each rung's primary `√` atom with the cap the
goal exposes, plus the hint bag read off the goal (`sq_nonneg` at the vertex and both band
endpoints), plus the rung's adaptations. 4 instances per rung = both variants at k=2 and k=8, run
against the **shipped generator's own props**.

| rung | `I0_verbatim` (the memorised idiom) | other probes | first route that closes | distance |
|---|---|---|---|---|
| `v2` **(calibration)** | **4/4** | `I1_sq_sqrt` 4/4 | base | **0** |
| `r1_recip` | **0/4** | `A2_div_nonneg_only` 0/4 | `A1_le_div_iff₀` **4/4** | 1 + a side goal `positivity` cannot do |
| `r2_prod` | **0/4** | `I1_sq_sqrt` 0/4; `A2_balanced_split` **2/4** | `A1_oracle_split` **4/4** | 2 memorised steps + the right divisor pair |
| `r2_sum` | **0/4** | `I1_sq_sqrt` 0/4; `A2_even_split` **2/4** | `A1_oracle_split` **4/4** | 1 `have` + 1 invented integer |
| `r3_floor` | **0/4** | `I1_floor_le` 0/4; `A2_bracket` 0/4 | `A1_floor_le_iff` **4/4** | 3, and the memorised sub-goal is **false** |
| `r4_floorprod` | **0/4** | `A1_prod_then_floor` 0/4; `A2_floor_le_iff` 0/4; **`A3_sqrt_mul_first` 0/4** | **none** | **≥ 4** |

**The control calibrates.** `I0_verbatim` closes 4/4 on `v2` — consistent with S2's 68/68 on the
measured bank and 12/12 on fresh instances — and 0/4 on every candidate rung. So "the memorised
one-shot stops applying at the schema level" is measured for all five candidates, through the
shipped generator, with a live planted control on the other side of the gate.

Three things this run adds beyond §5's table:

1. **`r3_floor`'s failure mode is exactly the advertised one, read off the error text rather than
   the pass/fail bit.** `I0_verbatim` fails on the *right* conjunct of `Real.sqrt_le_iff` with
   `⊢ False` from `5 ^ 2 < x ^ 2 + 6 * x + 28` — i.e. `nlinarith` is being asked to prove
   `u ≤ T²`, which is **false** on part of the band. Not "unfound": false. §11.9 quantifies it.
2. **`r4_floorprod` resists even the correct route ordering.** `A3_sqrt_mul_first` applies
   `Real.sqrt_mul` before the floor step — the ordering §3.7 says no adaptation found — and still
   closes 0/4 when the arithmetic is fed only goal-readable hints, while the generator's own
   13-line witness closes 30/30 (§11.5). So the barrier is the *arithmetic staging inside* the
   route, not just knowledge of the route. That is a strictly stronger result than S2's 0-of-4 and
   it supports §6.2's placement of this rung below the corridor floor.
3. **The `positivity` trap is still live** (§4's methodological finding 1): `A2_div_nonneg_only`
   uses `by positivity` for `0 ≤ c / u` and fails 0/4 for a reason unrelated to the rung. Kept in
   the table as a negative control on the probe itself.

**What it still does not predict.** Graded difficulty. §5 and §8.2 stand unchanged: the base
idiom closes the 0.25 leaf on `v2`, and every ordering in §6 rests on the adaptation ladder plus
the offline target widths, not on samples.

### 11.7 Full validator V0–V6 (R0b), through the shipped generator

`validate_problem(..., check_automation=True)`, 3 freshly generated problems at **each** of
k ∈ {2,4,8}, per rung — R0b's requirement, exactly:

| rung | k=2 | k=4 | k=8 | total | verdict |
|---|---|---|---|---|---|
| `v2` | 3/3 | 3/3 | 3/3 | **9/9** | pass |
| `r1_recip` | 3/3 | 3/3 | 3/3 | **9/9** | pass |
| `r2_prod` | 3/3 | 3/3 | 3/3 | **9/9** | pass |
| `r2_sum` | 3/3 | 3/3 | 3/3 | **9/9** | pass |
| `r3_floor` | 3/3 | 3/3 | 3/3 | **9/9** | pass |
| `r4_floorprod` | 3/3 | 3/3 | 3/3 | **9/9** | pass |

**54 problems, 54 pass, every check green** — V0 (goal resists), V1 (elaborates), V2 (252
witnesses), **V3 (stage-1 plan check)**, **V4 (compose + sanitizer + axiom audit)**, V5 (252 leaf
battery runs), V6 with `visible_lemmas = []` and no exemption. §4's "V3 and V4 have never been run
for any candidate" is closed, and it closed clean: 0 sanitizer violations and 0 disallowed axioms
anywhere.

### 11.8 The k-scaling wall — a real finding, and it is not the ladder's fault

R0b also asks for "one k=32 problem for V1/V3 elaboration cost". Running the full structural
validator (V1, V2, V3, V4, V6; automation off) at k = 32 found a failure — and chasing it produced
the cleanest new result of this gate.

**At the shipped `PREAMBLE` (`maxHeartbeats 400000`), V4 compose passes up to:**

Cells marked **[F]** are full `validate_problem` runs (V1, V2, V3, V4, V6); **[C]** are
compose-and-kernel checks of the identical artifact V4 builds, minus the sanitizer and axiom audit
(neither of which ever failed anywhere in this gate). "not run" means exactly that — no cell here
is inferred from monotonicity.

| rung | k=8 (V0–V6) | k=16 | k=32 | k=64 | k=128 | first failing k | k=32 wall |
|---|---|---|---|---|---|---|---|
| `v2` (control) | ok 9/9 | not run | ok 3/3 **[F]** | ok 1/1 **[F]** | **FAIL [C]** | **128** | 10 s |
| `r1_recip` | ok 9/9 | not run | ok 3/3 **[F]** | ok **[C]** | **FAIL [C]** | **128** | 11 s |
| `r3_floor` | ok 9/9 | not run | ok 3/3 **[F]** | ok **[C]** | not run | **> 64** | 18 s |
| `r2_prod` | ok 9/9 | not run | ok 3/3 **[F]** | **FAIL [C]** | not run | **64** | 41 s |
| `r2_sum` | ok 9/9 | not run | ok 3/3 **[F]** | **FAIL 1/1 [F]** (V3+V4) | not run | **64** | 36 s |
| `r4_floorprod` | ok 9/9 | **ok 3/3 [F]** | **FAIL 3/3 [F]** (V4) | **FAIL 1/1 [F]** (V3+V4) | not run | **32** | 73 s |

Every failure is `(deterministic) timeout … maximum number of heartbeats (400000)` at `whnf`,
`isDefEq`, `«synthesize pending MVars»` or `«tactic execution»`. **V1 and V2 pass in every one of
these cases, and V3 passes in all of them except at k=64** — the goal elaborates, all 32
witnesses kernel-check individually, the plan closes granting the lemmas; it is the single
composed artifact that exhausts the budget.

**Raising the budget clears it, which is what makes this a harness limit rather than a schema
defect:**

| case | `maxHeartbeats` 400,000 (shipped) | 1,600,000 | 6,400,000 |
|---|---|---|---|
| `r4_floorprod` k=32 (58 KB artifact) | **FAIL**, 48 s | **ok**, 87 s | ok, 87 s |
| `r2_prod` k=64 (58 KB) | **FAIL**, 31 s | **ok**, 123 s | — |
| `r2_sum` k=64 (51 KB) | **FAIL** | **ok**, 96 s | — |
| `r4_floorprod` k=64 (118 KB) | **FAIL** | — | **ok**, 348 s |
| `v2` k=128 (73 KB) | **FAIL**, 22 s | **ok**, 103 s | — |

Three consequences, in order of how much they should change behaviour:

1. **FAMILIES.md's scaling requirement is already violated by the SHIPPED family, not by the
   ladder.** "The schema should not break at k=128 even if Phase 1 only ships k≤32" —
   `case_tree` `v2` at k=128 fails V4 today at the shipped `PREAMBLE`, and passes at 4× the
   heartbeat budget. This is a pre-existing defect the ladder merely made visible by pushing
   bigger artifacts through the same path.
2. **`r4_floorprod` is the only rung whose wall lands inside the shipped k-grid.** Under a literal
   reading of R0b ("one k=32 problem for **V1/V3** elaboration cost") it passes: V1 and V3 are
   green at k=32. Under the natural reading (full `validate_problem` at k=32) it fails, 3 seeds
   out of 3. Both readings are recorded; §11.11 takes the conservative one.
3. **A `maxHeartbeats` bump is a one-line fix in `core/leancode.py`'s `PREAMBLE` — and it is NOT
   free.** The same constant governs the V0/V5 battery: more heartbeats means `nlinarith`,
   `aesop` and `polyrith`-adjacent tactics get more budget to *close* a leaf. **Any bump
   invalidates every battery verdict in this file and in §4, and V0/V5 must be re-measured with
   the planted control attached.** That file is not owned here; flagged in §11.13.

### 11.9 Offline target-width and tightness measurements

Free, exact, computed over the 30 staged leaves of each rung — these are §5's "offline
target-width measurements", which §5 says carry the ranking together with the adaptation ladder.

**How wide is the numeric target the prover must hit?**

| rung | candidate splits per leaf (min/median/max) | leaves with **exactly one** feasible split | the obvious guess is the answer | \|cap₁ − t/2\| median / max |
|---|---|---|---|---|
| `r2_sum` | 8 / 11 / 16 (every integer split of t) | **30/30** | even split feasible in **9/30 = 30.0%** | **0.5 / 1.5** (≤ 0.5 on 17/30) |
| `r2_prod` | 4 / 8 / 12 (divisor pairs of T) | **30/30** | balanced divisor pair feasible in **17/30 = 56.7%** | n/a (multiplicative) |

Both rungs' feasible split is **unique**, over 30/30 leaves, confirming §3.4's argument
analytically and §3.5's Lean sweep empirically. The 30.0% even-split rate reproduces S1's 35.9%
on independent draws.

**How tight is the tight cap — i.e. how much of the band actually falsifies the memorised
sub-goal `√u ≤ T`?** (1,001-point grid per leaf, 30 leaves per rung)

| rung | min | median | max | leaves where the sub-goal is false somewhere |
|---|---|---|---|---|
| `r3_floor` | 0.071 | **0.166** | **1.000** | **30/30** |
| `r4_floorprod` | 0.001 | **0.004** | 0.032 | **30/30** |

§3.6's exemplar measured 29.5%; the shipped distribution's median is 16.6%, with one staged leaf
where `√u > T` on the **entire** band (`⌊√u⌋ = T` everywhere — the tightest configuration the
knob support can produce). The mechanism is present on every leaf, and the *degree* of tightness
is a per-leaf covariate the pod can condition on — it is not currently written into
`ct_candidates.jsonl`, and it would be the natural R4.5-style lever for `r3_floor` if that rung
lands near the corridor (§11.13).

`r4_floorprod` inherits the same logical blocker with three orders of magnitude less margin —
false on ~0.4% of the band. Since falsity is a binary blocker for the route, this does not soften
the rung; but it does mean any future *loosening* of `r4_floorprod` is a knife-edge, and §3.7's
"pad bumped until P is not a perfect square" is doing more work than its dead-code status
suggests.

### 11.10 Where the measurements contradict §3/§6's reasoning

Per §6's own instruction ("if the pod contradicts any of this, the contradiction is the finding"),
applied one gate early. **No registered number in §6 is edited.**

1. **§6.2's stated reason for placing `r2_sum` marginally above `r2_prod` does not survive
   measurement.** The note argues `r2_sum` is *anchored* (even split right 35.9% of the time)
   while `r2_prod`'s divisor pair has "no measured anchor". Measured here on the shipped
   generator: the obvious guess is right **30.0%** of the time for `r2_sum` and **56.7%** for
   `r2_prod`. If anchoring is what makes a rung easier, the ordering inside the matched pair
   should be `r2_prod` **easier** than `r2_sum`, not harder. §6.2 already declines to register an
   ordering inside the pair ("that gap is 0.06 and it is inside the noise") — so the registered
   claim survives; the *argument* for it does not. **L1's exact rank order is now the less likely
   of the two; L1c (coarse order) is untouched.**
2. **`r2_prod`'s search space is narrower than `r2_sum`'s, not wider.** §3.4 estimates "~4–12
   divisor pairs"; measured 4–12, median 8, against `r2_sum`'s 8–16, median 11. Combined with (1),
   the pair is less matched on target width than §3.5's length-matching suggests — the combinator
   comparison is clean on *text*, not on *search*.
3. **`r4_floorprod` is harder than §5's "≥ 4" says, in a specific way.** The correct route
   ordering, hand-supplied, still closes 0/4 (§11.6). The distance is not "the model must find
   `Real.sqrt_mul` first"; it is "even with `Real.sqrt_mul` first, the degree-4 product bound must
   be staged by hand". This strengthens the case for §6.2's 0.15 projection and for keeping the
   rung last.
4. **`r3_floor`'s capacity is *below* the control**, 1,560 vs 1,628 distinct leaves at k=8. §3.6's
   pad-widening was supposed to buy "5–9× more leaf capacity" and address §2.3; the implementation
   correctly refused it under F3, and the measured consequence is a small capacity *loss*. R4.3
   (larger distinct-leaf capacity) therefore ranks `r2_sum` ≈ `r2_prod` > `r4_floorprod` >
   `r1_recip` ≈ `v2` > `r3_floor`.
5. **§6.4's length confound is confirmed as stated and is now quantified across the whole grid**
   (§11.3): the rungs differ by up to 1.9× in leaf length (`r1_recip` 60 chars → `r4_floorprod`
   112 at k=2) and every rung is flat in k. `r1_recip` remains the designed partial control —
   shorter than `v2` and predicted harder.

### 11.11 Readiness verdict — which rungs go to the GPU, and in what order

**Nothing died to the battery. Nothing died to the validator at k ∈ {2,4,8}. One rung has a
k=32 elaboration defect.** So this is not §7.1's escalation case and not §7.2's — it is the
ordinary case, and the ladder ships.

| # | rung | status | why this position |
|---|---|---|---|
| 1 | **`v2`** | **READY — mandatory, blocking** | R0c: if the same-pod control does not reproduce inside [0.85, 0.98] the whole comparison is void. Never drop this cell. |
| 2 | **`r2_sum`** | **READY** | Primary candidate. Carries the ladder's only continuous, per-leaf lever (`split_gap`, shipped on every row, median 0.5 / max 1.5), the least-anchored obvious guess (30.0%), and the joint-best distinct-leaf capacity. A near-miss on level is correctable *within* the rung. |
| 3 | **`r2_prod`** | **READY** | Primary candidate and the matched-pair partner: dropping it forfeits the combinator measurement, which is the one mechanism-identification this star design buys over a chain. Measured to be *more* anchored than `r2_sum` (§11.10.1), so the pair now brackets rather than duplicates. |
| 4 | **`r3_floor`** | **READY** | Mechanism confirmed strongest locally (memorised sub-goal false on 30/30 leaves, median 16.6% of the band). Registered to fail R2 on zero-rate even if R1 passes (L6) — measure it precisely *because* that prediction is falsifiable. |
| 5 | **`r1_recip`** | **READY** | The upper bracket, and the model's falsification test: §3.3 says if this measures ≈0.9 the idiom-distance model loses its lower anchor. Also the length confound's partial control (shorter than `v2`, predicted harder). Only 29 leaves, and 9 at k=2. |
| 6 | **`r4_floorprod`** | **READY FOR THE LADDER CELL ONLY — NOT SHIPPABLE AS THE CHOSEN RUNG** | Leaf statements are sound and gated at k ∈ {2,4,8}: 30/30 witnesses, 0 battery kills, V0–V6 9/9. But **V4 fails at k=32 on 3 of 3 seeds** at the shipped `maxHeartbeats`, so §9 step 5's re-materialization (which runs the full validator across the k-grid) cannot complete for this rung until the `PREAMBLE` bump lands and V0/V5 are re-measured. **Drop this cell first if budget binds** (§0: −$0.21). |

**Order to drop under budget pressure: 6, then 4, then 3** (corrected 2026-08-13 after the science
review; was "6, then 5, then 4"). Never 1 or 2 — 1 is R0c, 2 is half the matched pair.
**Never drop 5 (`r1_recip`) while §7.1 step 1 depends on it**: that branch reads "read `r1_recip`
first … if even `r1_recip` is below 0.25, the finding is that any schema change collapses this
prover", so `r1_recip` is the cell carrying the ladder's only *upper* bracket and its escalation
trigger. Dropping it leaves v2 + the matched pair + `r3_floor`, which brackets 0.45 from below
only. The collapse world is not remote: the sole measured anchor for "the memorised route no
longer applies" is bridge_chain's four probe-fail presets at 0.196–0.312, and four of this
ladder's five projections sit at or above the top of that band.

`OVERNIGHT-2.md`'s Pod A plan names **five** cells, so dropping `r4_floorprod` is also the
plan-conforming default; the 179-row file measures 6 cells for ~+$0.21 over the 149-row
five-cell run (~23 min vs ~20 min at 430–480 rows/hr), and the filter is one line:

```bash
grep -v '"preset": "r4_floorprod"' data/families/ct_candidates.jsonl > /tmp/ct5.jsonl
```

The case for spending the $0.21: `r4_floorprod` is §6.2's only rung projected *below* the corridor
floor (0.15), so it is the lower anchor that distinguishes **L3** ("all four non-control rungs
collapse") from "one rung overshot", and it is §7.2's first escalation rung already gated. The
case against: it cannot ship as the chosen rung until the `PREAMBLE` bump lands (§11.13.1).

**The pod command must change in one place.** §0c's `--data-files` path is
`data/families/ct_candidates.jsonl` (§11.1). Everything else in §0c stands, including the
prohibition on `--leaf-max-tokens` / `--leaf-temperature` and the fresh `--out`.

**R0b's main clause is satisfied for all six rungs** (V0–V6 on 3 freshly generated problems at
each of k ∈ {2,4,8}); **R0b's k=32 clause is satisfied for five**, and is the reason rung 6
carries a condition. R0c, R1, R2, R2b, R3, R3′ and R4 are pod-side and untouched.

### 11.12 Artifacts

Written by this gate, all regenerable from the stager command plus the drivers in §11.1:

| path | contents |
|---|---|
| `data/families/ct_candidates.jsonl` | **179 rows**, 6 rungs, `build_bank`-ingestable, `battery_gated: true` |
| `data/families/ct_battery/structural.json` | per-rung invariants, necessity sweep, predicate audit, `leaf_stats` |
| `data/families/ct_battery/<rung>.jsonl` | the stager's coefficient-extreme battery subset per rung |
| `data/families/ct_battery/battery.json` | stager kill table + witness verdicts (control first) |
| `data/families/ct_battery/validate.json` | V0–V6, 9 problems per rung |
| `data/families/ct_battery/gate_control.json` | the planted control, run alone |
| `data/families/ct_battery/gate_battery_ext.json` | knob-spanning battery subset, per-probe killers, covered cells |
| `data/families/ct_battery/gate_witness_all.json` | witness kernel check, all 179 staged leaves |
| `data/families/ct_battery/gate_idiom.json` | idiom probe, per instance, with failure texts |
| `data/families/ct_battery/gate_validate_k32.json` | k=32 structural validation |
| `data/families/ct_battery/gate_validate_scaling.json` | k = 16/32/64 walls, 3 seeds where it mattered |
| `data/families/ct_battery/gate_heartbeat.json` | the `maxHeartbeats` diagnostic |
| `data/families/ct_battery/gate_offline.json` | target width, tightness, capacity, flatness structurals, R3′ power |
| `data/families/ct_battery/gate_rows.jsonl` | **per-staged-row verdicts**: `witness_kernel_ok`, `battery_probed`, `battery_killers` |
| `data/families/ct_battery/gate_scripts/` | the five drivers that produced the `gate_*` artifacts, plus a README (misplaced by ownership, see §11.13.7) |

`ct_candidates.jsonl` was deliberately **not** hand-edited, so it stays byte-reproducible from the
single documented command; the per-row gate verdicts live in the `gate_rows.jsonl` sidecar
instead. Read `battery_gated: true` on a candidate row as *"the local Lean gate ran for this
staging run"* — the field the implementer defined — **not** as *"this statement was itself
battery-probed"*. Per-statement truth: **179/179 witness-checked, 40/179 battery-probed,
0 killed**; the battery additionally ran on 275 further generator propositions (the validator's
V0/V5 across 54 problems, plus the per-rung goal probes).

### 11.13 Contract friction found by this gate (reported, not worked around)

1. **`core/leancode.py`'s `PREAMBLE` heartbeat budget is the binding constraint on the k-axis, and
   it is not owned by any family agent.** `maxHeartbeats 400000` fails V4 for shipped `v2` at
   k=128 and for `r4_floorprod` at k=32; 1,600,000 clears every wall observed up to k=64 (except
   `r4_floorprod` at k=64, which needed 6,400,000 — 1,600,000 untested there) and clears `v2` at
   k=128. **A bump also strengthens the V0/V5 battery** (same constant), so it
   retroactively invalidates every battery verdict in §4 and §11.4 and must be followed by a
   re-run of this gate with the planted control attached. This is a repo-level decision, not a
   family one, and it blocks FAMILIES.md's k=128 scaling clause today.
2. **§0b/§9's file names do not match the shipped script** (`stage_ct_ladder.py` /
   `ct_ladder_candidates.jsonl` vs `stage_ct_candidates.py` / `ct_candidates.jsonl`). §10.8
   predicted it; §11.1 records the working command. One of the two must move before the pod
   session — this note's §0/§9 is the cheaper edit.
3. **`r3_floor` has no per-leaf difficulty covariate in the staged rows.** The measured tightness
   fraction (§11.9, median 0.166, range 0.071–1.000) is the natural analogue of `r2_sum`'s
   `split_gap` and would give that rung an R4.5-style within-rung lever, which is exactly what §7
   values. It is computable offline from the existing knobs; adding it means touching
   `case_tree.py`'s `knobs()` and the stager, neither owned here.
4. ~~`scripts/probes/probe_ct_functional.py:309` is broken.~~ **Fixed upstream in `724b70f`**
   (`ct.Piece(ct.RUNGS["v2"], …)`) while this gate ran; verified against the working tree. Not
   exercised here either way — the idiom probe in §11.6 builds props from the shipped generator
   rather than from that script — so §10.7's "re-run S2's probe with a durable `--out`" is now
   unblocked and remains worth doing.
5. **FAMILIES.md's leaf-disjointness contract is still unimplemented for family leaves.** The
   staged rows carry `leaf_pool` from `leaf_split(statement_key)` for information only —
   measured **137 train / 42 eval (23.5%)** across the 179 rows, consistent with the 25% design —
   but there is no leaf-level rejection sampling, so §9's regeneration step still cannot honour
   the contract. Unchanged by this gate; restated because §9 step 5 is the next step after the
   pod.
6. **§7/R3 remains unresolvable at the ladder's n**, exactly as §7 and §10.2 state. This gate
   changes nothing there except to sharpen R3′'s power estimate (SE ≈ 0.031/decade, §11.3).
7. **The gate's own drivers had nowhere to live.** Four of the five phases are scripts this agent
   wrote but could not commit to `scripts/probes/`, because the owned-files list was
   `research/case-tree-hardening.md` plus `data/families/ct_candidates.jsonl` and
   `data/families/ct_battery/**`. They are parked at
   `data/families/ct_battery/gate_scripts/` with a README rather than left in `/tmp`, which is
   §10.7's failure mode. **Move them to `scripts/probes/` at the next commit that owns that
   directory** — otherwise a data directory carries executable code, which is exactly the kind of
   thing that rots.

---

# §12. MEASURED — the ladder result (2026-08-13, pod `ct-ladder`, invoice $6.51)

254 statements × 8 DSV2 attempts, 239 ladder + 15 anchor, **0 errors**, leaf profile
`deepseek-ai/DeepSeek-Prover-V2-7B|deepseek-prover-v2-non-cot|Mdef|Tdef` on both files.

## R0c — no drift (the paired test earned its $0.11)

15 already-measured statements, re-run on the same pod/profile: mean Δ **+0.025**, sd 0.202,
SE 0.052, **t = +0.48**. Anchor mean 0.767 → 0.792. No drift, so every candidate number below is
interpretable. Individual leaf deltas ranged ±0.375 — which is exactly why this had to be a paired
test over 15 statements and not an eyeball of a redrawn control.

## R1/R2/R3 — measured

| rung | n | mean | SE | band-fit | zero-rate | k=2 | k=4 | k=8 | k=32 | spread | R2 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `v2` (control) | 40 | **0.847** | 0.040 | 0.38 | 0.00 | 0.887 | 0.738 | 0.850 | 0.912 | 0.175 | FAIL |
| `r2_prod` | 40 | **0.219** | 0.028 | 0.53 | 0.25 | 0.188 | 0.212 | 0.250 | 0.225 | **0.062** | FAIL |
| `r3_floor` | 40 | 0.169 | 0.033 | 0.30 | 0.42 | 0.175 | 0.113 | 0.237 | 0.150 | 0.125 | FAIL |
| `r2_sum` | 40 | 0.091 | 0.028 | 0.17 | 0.68 | 0.000 | 0.200 | 0.062 | 0.100 | 0.200 | FAIL |
| `r4_floorprod` | 40 | 0.025 | 0.009 | 0.03 | 0.82 | 0.037 | 0.037 | 0.013 | 0.013 | 0.025 | FAIL |
| **`r1_recip`** | 39 | **0.000** | 0.000 | 0.00 | **1.00** | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | FAIL |

**No rung passes R2.** `r2_prod` is nearest on every axis and still misses both clauses
(band-fit 0.53 vs ≥0.60; zero-rate 0.25 vs ≤0.20). R1 nearest-0.45 selects `r2_prod` (0.219),
with `r3_floor` inside the 0.08 tie band — so the tie rule added last night does fire, and the
choice would have fallen through to R4, where `r2_prod` also wins on flatness (spread 0.062, the
flattest of all six including the control).

## The actual finding: the corridor sits in a GAP

Measured levels are **0.847, then 0.219, 0.169, 0.091, 0.025**. Nothing lands between 0.22 and
0.85 — and the corridor is [0.25, 0.9]. Six schemas, four decades of coefficient magnitude, four
k values, and **not one leaf distribution in the corridor**.

Difficulty with respect to this frozen prover is not a continuum that a schema knob slides along.
It is a **step function of idiom match**: either the memorised route applies (≈0.85) or it does
not (≤0.22). §11.6's idiom probe measured exactly this binary and was right to be binary; what the
design got wrong was believing the *distance* to the first closing route would order the drop.

**`r1_recip` is the proof, and it is the projection's worst failure.** Projected **0.62** — the
highest of any candidate — on the strength of being idiom-distance 1 (`le_div_iff₀` closes it
12/12 locally). Measured **0.000: 0 of 312 attempts**, all 39 leaves at 0/8. Diagnosed, not
assumed: `elaborates = True` on all 39, `n_attempts = 8` on all 39, status `leaf_failed` (not
`format_error`, not `error`), so the statements are well-formed and the prover really was called
and really failed. A goal one lemma from DSV2's memorised route is *completely* unreachable when
that lemma lives in a different family — division rather than `√`. The prover's competence is
idiom-shaped, not difficulty-shaped.

*Residual uncertainty, stated:* `first_proof` is only populated on success, so we have the failed
count but not the failed text. We know DSV2 emitted proof-shaped output (else the status would be
`format_error`); we do not know what it tried. Harvesting failed attempts would settle it.

## R3′ — flatness PASSES, and it settles a question that was blocking two families

`pass@8 ~ log10 max|coef| + rung fixed effects`, n=239, support **0.60–4.59 decades**:
**slope +0.0053/decade, SE 0.0098, z = +0.55.** Restricted to the three rungs with variance
(n=120): −0.0007/decade, z = −0.04. **Coefficient magnitude is measured difficulty-neutral over
four decades** — the first real measurement of this, and it is why staging k=32 mattered.

Two consequences beyond this ladder:
1. **§3.8's exclusion of the quartic rungs was over-cautious.** They were dropped for 45,394×
   growth (≈4.7 decades) as "bridge_chain's flatness failure with a different variable name." The
   slope is flat with a tight SE across essentially that whole range. On this evidence a quartic
   rung is a legitimate candidate — and `H2_quartic` carried the highest projection of anything.
2. **`retune-notes.md` §8.2's consistency question is answered in the direction that mechanism
   arguments *are* licensed here** — for coefficient magnitude specifically, and now with data
   rather than an argument. bridge_chain's 3^k multiplier is still ~10 decades past the measured
   support, so this does not rehabilitate it; it does mean the objection to it must be restated as
   "unmeasured at 10¹⁵", not "known to break flatness".

## R5 — oracle ceiling: decisive, and it disqualifies the whole ladder independently

`(1 − (1−p)^a)^k`, shipped `Budgets` | flat a=8:

| rung | k=2 | k=4 | k=8 | k=32 |
|---|---|---|---|---|
| `v2` 0.847 | 0.999 \| 1.000 | 0.998 \| 1.000 | 0.996 \| 1.000 | 0.468 \| 1.000 |
| `r2_prod` 0.219 | 0.394 \| 0.742 | 0.155 \| 0.550 | 0.024 \| 0.303 | 0.000 \| 0.008 |
| `r3_floor` 0.169 | 0.273 \| 0.596 | 0.075 \| 0.355 | 0.006 \| 0.126 | 0.000 \| 0.000 |

**No candidate satisfies DIRECTION §5.5(b) (≥70% at every k) at any k > 2, even with the attempt
budget raised to 8.** R5 was added last night as a reporting requirement; it turns out to be an
independent disqualification. Had the ladder been read on R1/R2 alone, `r2_prod` would have been
selected and the oracle ceiling discovered later — the failure mode §5.4(b′) was written to prevent.

## Projections: MAE 0.253, and biased in one direction

| rung | projected | measured | error |
|---|---|---|---|
| `v2` | 0.92 | 0.847 | −0.073 |
| `r1_recip` | 0.62 | 0.000 | **−0.620** |
| `r2_sum` | 0.48 | 0.091 | −0.389 |
| `r2_prod` | 0.42 | 0.219 | −0.201 |
| `r3_floor` | 0.28 | 0.169 | −0.111 |
| `r4_floorprod` | 0.15 | 0.025 | −0.125 |

MAE **0.253** against a registered expectation of 0.15–0.20 — and **all six errors are negative**.
That is systematic optimism, not noise: every rung was harder than predicted. Rank order also
failed (`r1_recip` projected first among candidates, measured last of six), so **L1 and L1c are both
refuted**. The registered down-weighting relative to bridge_chain's fitted projections (MAE 0.044)
was correct in direction and insufficient in size.

## Verdict: escalate to bank-drawn leaves — the registered rule fires, now with a mechanism

§7.1 step 1 registered: "read `r1_recip` first … if even `r1_recip` is below 0.25, the finding is
that any schema change collapses this prover" → escalate to **FAMILIES.md direction 1 (bank-drawn
leaves)**. `r1_recip` measured 0.000. The rule fires as written.

It is worth being precise that the world is *not* quite the registered L3 ("all rungs collapse"):
the schema axis clearly *does* move difficulty (0.847 → 0.025 is a real, ordered range) and
`r2_prod` is both the best-levelled and the flattest thing this family has ever produced. What
fails is that the range **skips the corridor**. Synthetic schema variation gives a binary because
one template generates one idiom; real competition statements have a continuum precisely because
they were not generated by a template. That is the mechanistic case for direction 1, and it is now
measured rather than argued.

**Phase 1 does not close for case_tree on this ladder.** Recommended next: the wide candidate
sweep (#12) to turn the 401 in-band statements into a real bank, then bank-drawn leaves for both
families. Reinstating `H2_quartic` (§3.8) is the one cheap synthetic option R3′ has re-opened, and
it is the only one worth a further pod before direction 1.

## §12.1 CORRECTION — the corridor is reachable; I applied the wrong statistic

§12 concluded "the corridor sits in a gap" and recommended escalating to bank-drawn leaves. Both
claims need correcting, and the second is wrong for two independent reasons.

**The corridor criterion was applied to the wrong object.** R1/R2 read the *unfiltered generated*
distribution. But the leaf bank's whole design is **measure-then-filter**: generate a surplus,
measure pass@8, keep what lands in band (that is how `bank_dsv2.jsonl`'s 401 in-band statements
were produced from 4,085 measured). The families were being held to a stricter standard than the
bank — "everything you generate must be in band" versus "keep what is." Applying the bank's own
discipline to these same synthetic leaves:

| rung | in band | surplus needed | **filtered mean** | band-fit | zero-rate | attempts for oracle ≥0.70 (k=8 / k=32) |
|---|---|---|---|---|---|---|
| `v2` | 15/40 | 2.7× | 0.708 | 1.00 | 0.00 | 3 / 4 |
| **`r3_floor`** | 12/40 | 3.3× | **0.448** | 1.00 | 0.00 | 6 / 8 |
| `r2_sum` | 7/40 | 5.7× | 0.411 | 1.00 | 0.00 | 6 / 9 |
| `r2_prod` | 21/40 | 1.9× | 0.363 | 1.00 | 0.00 | 7 / 10 |

`r3_floor`'s filtered pool lands at **0.448 against a 0.45 target**, with band-fit 1.00 and
zero-rate 0.00 *by construction*, and it clears DIRECTION §5.5(b) at every k up to 32 with **8
attempts per leaf** — a modest raise from the shipped 4, far short of the 19 the unfiltered mean
implied. R5 does not disqualify the ladder; it disqualifies shipping *unfiltered* leaves.

**Caveats, stated because this is a lead and not a closed result:**
1. **n is small.** The filtered means rest on 12 (`r3_floor`) to 21 (`r2_prod`) leaves; ~±0.04.
2. **Per-k structure is unresolvable.** Filtered cells hold 1–7 leaves, so the apparent per-k
   spreads (0.219 / 0.104 / 0.219) are noise. Keep rates also swing by k (`r3_floor`
   40/10/50/20%) at ±15% SE. Flatness of the *filtered* pool is untested, and R3′ on the filtered
   subset has no power at this n.
3. **Filtering at n=8 selects on noise.** A leaf whose true rate is 0.95 can measure 0.875 and be
   kept; one at 0.5 can measure 1.0 and be dropped. The filtered pool's *true* rates are therefore
   regression-biased toward the band edges, so band-fit 1.00 is a property of the measurement, not
   of the leaves. The bank carries the same bias — FAMILIES.md already notes ~32 attempts are
   needed for per-leaf claims. Re-measuring a filtered pool at n=32 would shrink apparent band-fit.

**And the escalation I recommended does not work as written, independently of the above.**
FAMILIES.md direction 1 says "draw leaf content from the calibrated bank." Inspected: the 401
in-band statements are **self-contained competition inequalities with their own bound variables and
hypotheses**, e.g. `∀ (a b c : ℝ) (ha : 0 < a) … (habc : a + b + c = 1), 10*(a³+b³+c³) − 9*(a⁵+b⁵+c⁵) ≥ 1`
(272 of 401 are `∀`-over-ℝ of this shape). Neither shipped family can host them:
- `bridge_chain` leaves are **relational steps over shared variables** — transitivity is what
  composes them into the goal. Independent statements do not chain.
- `case_tree` leaves are **band claims over the goal's shared `x`**. Independent statements have no
  common domain.

So direction 1 needs a *new assembly* able to compose structurally independent statements — and the
obvious one (a conjunctive goal `L₁ ∧ … ∧ L_k`) fails **V6 by construction**, because every leaf
prop is then a substring of the goal and nothing is invented. **Leaf content and assembly are
coupled: what makes a leaf battery-resistant and difficulty-calibrated (independence) is what makes
it uncomposable.** That tension is the real obstacle, and it was not visible in FAMILIES.md's
"directions in preference order," which assumed leaf content is swappable.

**Revised recommendation.** The wide sweep (#12) should **not** be the next spend — it buys
calibrated *statements*, not usable *leaves*, until a family exists that can host them. The cheap,
high-information next measurement is instead: generate surplus `r3_floor` and `r2_prod` leaves,
measure, filter, and re-measure the filtered pool at **n=32** to test whether the corridor survives
the selection bias — plus reinstating `H2_quartic`, which R3′ has re-legitimised. That is one pod
and it tests the thing everything now rests on.

## §12.2 REGISTERED before the n=32 run (2026-08-13, pod `ct-n32` provisioning)

Written before any n=32 datum exists. 49 leaves × 32 attempts, three strata.

**Why two-sided.** Re-measuring only the 33 in-band leaves would confirm nothing — it cannot
separate "the filter works" from "a noisy sample regressed toward the middle." Adding 8 leaves
measured 0/8 and 8 measured 8/8 turns the run from a re-check of a selection into an estimate of
the underlying true-rate distribution.

**Predictions.** The n=8 keepers came from populations with unfiltered means ~0.22 (`r2_prod`) and
~0.17 (`r3_floor`) carrying heavy mass at zero, so Bayes pulls a leaf measured 2/8 *up* and one
measured 7/8 *down* — both toward the middle, i.e. toward the band. That is why I expect the filter
to mostly hold rather than mostly collapse:

| stratum | n | registered prediction at n=32 |
|---|---|---|
| in_band (measured 0.25–0.9) | 33 | **70–85% stay in band**; filtered mean within 0.10 of its n=8 value (0.448 `r3_floor` / 0.363 `r2_prod`) |
| zero (measured 0/8) | 8 | **1–2 of 8** come out ≥0.25 — a true rate of 0.15 still yields 0/8 about 27% of the time |
| saturated (measured 8/8) | 8 | **1–2 of 8** come out ≤0.9 — `p⁸` is 0.43 at p=0.9, so most 8/8 leaves really are ≥0.85 |

**Decision rule, fixed now.**
- **PASS** — ≥70% of in-band leaves stay in band **and** the filtered mean moves <0.10.
  Measure-and-filter is a real instrument; **Phase 1 closes for case_tree** and the pipeline is
  n=8-filter + surplus, which is affordable.
- **MARGINAL** — 50–70% stay. The filter works but leaks; the pool needs n=16 filtering (2× cost)
  and the corridor claim must carry an explicit selection-bias caveat wherever it is cited.
- **FAIL** — <50% stay. The n=8 filter is mostly noise. Then either filter at n=32 (4× cost, which
  makes a large pool unaffordable at this budget) or accept that the corridor is not practically
  reachable for synthetic leaves — and that is a genuine Phase-1 negative result, not a setback to
  engineer around.

Whatever it returns, **the next move is Phase 2 on case_tree alone**, because the project's real
risk is having no measurement of the actual research question rather than an imperfect task family.
A FAIL changes what the leaves are, not whether the transfer slope gets measured.
