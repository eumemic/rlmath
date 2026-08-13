# case_tree hardening — survey A: ALGEBRAIC DEPTH

Four schema candidates that change the **piece function** so the memorised DSV2 idiom stops
closing the leaf, probed in live Lean on four axes: exact integer predicate, generator witness,
battery floor, idiom ceiling. Sibling survey B (`research/ct-hardening-survey-b.md`, agent S2)
covers the functional directions.

**Nothing here measures pass@8.** This is the local gate, mirroring
`scripts/stage_retune_candidates.py` and `research/retune-notes.md` §4–5. Every number below is
either a *floor* (battery, measured, definitive), a *self-certification* (witness kernel check,
definitive), an *exactness proof obligation* (audit, definitive), or a *ceiling proxy* (idiom
probe, indicative). §7 registers projections; the pod decides.

- Harness: `scripts/probes/probe_ct_algebraic.py` (owned by this task)
- Data: `data/families/ct_probe_a/{audit,lean,lean_b,lean_c,audit_c,structural}.json`
- Reproduce the free offline tables (§6.1–6.3) with `--audit --structural`; the Lean runs are
  the three command lines in the harness docstring
- Toolchain: local `ReplPool`, Mathlib @ lean v4.34.0-rc1, stock `PREAMBLE`, 2026-08-12
- Runs: **A** (5 directions × 8 instances, full battery + planted control),
  **B** (H2/H4 witness re-probe + stratified idiom calibration, battery skipped),
  **C** (budget-guess width sweep, H1/H3)

---

## 0. TL;DR

| direction | piece | exact ℤ predicate | witness | battery | base idiom | first route that closes | verdict |
|---|---|---|---|---|---|---|---|
| `v2` (control) | `A − √u` | **EXACT** | 8/8 | survives 8/8 | **8/8** | — (base) | control — measured 0.923, above the ceiling |
| `H1_twoatom` | `A − √u₁ − √u₂` | **EXACT** | 8/8 | survives 8/8 | **0/8** | oracle split 8/8 (even split 4/8) | **ladder rung — primary** |
| `H3_nested` | `A − √(u + √v)` | **EXACT** | 8/8 | survives 8/8 | **0/8** | oracle inner 8/8 (lazy inner 3/8) | **ladder rung — harder** |
| `H2_quartic` | `A − √(a(x−m)⁴+e)` | **EXACT** | 1/8 → **8/8** (fixed) | survives 8/8 | **0/8** | +band-product hint 8/8 | needs more work — **flatness leak** |
| `H4_twoatom_quartic` | `A − √u₁ − √(quartic)` | **EXACT** | 3/8 → **8/8** (fixed) | survives 8/8 | **0/8** | oracle split **+** band product 8/8 | needs more work — top rung, projected below the floor |

Three results carry the survey:

1. **The soundness gate is clean.** All five directions supply an *exact* (iff) integer
   characterisation of the piece's super-level set — 0 under-approximating and 0
   over-approximating mismatches against 60-digit reference arithmetic over ~9,600 points each.
   The `Real.log` failure mode that the module docstring rejects does not recur. §2.
2. **The instrument is a route detector, not a difficulty meter.** Re-calibrated on a
   *stratified* sample of measured leaves — the 18 case_tree leaves with pass@8 < 1.0, including
   the single 0.25 leaf, plus 10 at 1.0 — the base idiom closes **28/28**, i.e. **18/18** of the
   hard stratum. Run A's 10/10 was ceiling-only and this replaces it. Consequence: `base fails`
   licenses "the memorised one-shot does not apply", nothing quantitative. §5. **This is the
   biggest caveat in the survey and it narrows every claim in §7.**
3. **H1's numeric target is provably a single integer.** `√u₁ + √u₂ ≤ t` hands the prover a
   budget but not its split; sweeping every integer split in Lean, exactly **1 of 8 / 1 of 15 /
   1 of 14 / 1 of 12** closes, always the generator's own — and offline, over 4,000 instances,
   the feasible split is `cap₁` in **4,000/4,000** cases. That is the corridor mechanism, stated
   as an arithmetic fact rather than a hope. §4.2, §6.

---

## 1. Why a schema ladder and not a retune

Established before this task (`research/case-tree-forensics.md`, and the orchestrator's marginals):
case_tree measures pass@8 **0.923** over 68 leaves × 8 DSV2-7B attempts, with **50/68 at a perfect
8/8** and **band-fit 18/68** against the corridor's ≥0.60. Every knob marginal inside the shipped
support is flat (variant, the only significant separator at Fisher p=0.0009, still caps at 0.872;
its hardest stacked cell measures 0.79). 68/68 successful proofs run one idiom —
`Real.sqrt_le_iff` + `nlinarith [sq_nonneg …]` — which *is* the generator's own witness template
with the cap `t` read straight off the goal as `A − C`. There is no lever inside the knob support
because the family measures template recall, and template recall has no knob.

So the piece function has to change. What must survive the change, from `FAMILIES.md` and the
module docstring:

- **(a)** generator self-certification with an **exact integer** truth certificate — no floating
  point anywhere in the truth argument;
- **(b)** the coverage/necessity machinery (`covers_band`, `_redundant`, `_repair_necessity`);
- **(c)** per-node difficulty flat in k;
- **(d)** V0 (goal resists the battery), V5 (leaves resist it), V6 (no leakage).

Each direction is scored against all four. (d)'s leaf half is §3; (a) and (b) are §2 and §6;
(c) is §6.2 and is where the quartic directions fail.

---

## 2. The exact integer predicates (axis a) — and the soundness asymmetry

`case_tree` proves **coverage** on the reals with its witness (a *sufficient* condition is fine)
and checks **necessity** on the integers with `holds_at` (an *exact or over-approximating*
predicate is required). The asymmetry is not symmetric in its consequences: if `holds_at`
believes a piece covers **less** than it truly does, `_redundant` returns False when it should
return True and the generator ships a k-leaf plan that is secretly (k−1)-leaf. That is exactly
why `Real.log` is rejected. Every direction here therefore has to come with a derivation.

All four reduce to `Σᵢ √Uᵢ(x) ≤ t`, because both variants are algebraically the same claim
(`max`: `C ≤ (C+t) − Σ√Uᵢ`; `min`: `Σ√Uᵢ − (t−C) ≤ C`).

**H1 / H4 — two atoms.** For `U₁, U₂ ≥ 0` and `t ≥ 0`, with `s := t² − U₁ − U₂`:

```
√U₁ + √U₂ ≤ t  ⟺  U₁ + U₂ + 2√(U₁U₂) ≤ t²        (both sides ≥ 0, square)
               ⟺  2√(U₁U₂) ≤ s
               ⟺  s ≥ 0  ∧  4·U₁·U₂ ≤ s²          (both sides ≥ 0, square)
```

**EXACT (iff).** Integer-only: `U₁, U₂, s` are integers at integer `x`.

**H2 — quartic radicand.** `√(a(x−m)⁴ + e) ≤ t ⟺ a(x−m)⁴ + e ≤ t²`. **EXACT**; the radicand is
`≥ e ≥ 1 > 0` on the whole line so Lean's `√(negative) = 0` convention is never reached.

**H3 — nested radical.** With `U := a(x−m)² + g ≥ g ≥ 1` and `s := t² − U`:

```
√(U + √V) ≤ t  ⟺  U + √V ≤ t²  ⟺  √V ≤ s  ⟺  s ≥ 0 ∧ V ≤ s²
```

**EXACT.** Both squarings are between non-negative quantities.

### Audit (run A: 300 random instances per direction, k ∈ {2,4,8}, band ±12 grid)

Each integer predicate is compared against a 60-digit `Decimal` evaluation of the *same*
inequality. Ties can only occur at algebraic-integer coincidences (a sum of square roots of
integers is an integer only when each root is), where the `Decimal` values are exact, so no
comparison is a float race.

| direction | points | under-approx | over-approx | status | int spill max/mean | cap range | max\|coef\| |
|---|---|---|---|---|---|---|---|
| v2 | 9640 | **0** | **0** | EXACT | 2 / 1.33 | 4–9 | 2,193 |
| H1_twoatom | 9644 | **0** | **0** | EXACT | 2 / 0.81 | 9–18 | 2,202 |
| H2_quartic | 9608 | **0** | **0** | EXACT | 2 / 1.39 | 10–44 | 1,594,384 |
| H3_nested | 9602 | **0** | **0** | EXACT | 2 / 0.87 | 4–10 | 2,037 |
| H4_twoatom_quartic | 9572 | **0** | **0** | EXACT | 2 / 0.89 | 15–53 | 1,594,339 |

The audit also asserts, per instance, that the piece holds at every integer point of its own band
— the integer shadow of the coverage claim the witness proves on the reals. No violations.

**The disqualifying failure mode is ruled out for all five directions.**

---

## 3. Battery floor (axis c → V0/V5)

`families.validate.battery_proofs()`: 10 tactics × {bare, intros-first} = 20 attempts per prop,
25 s cap, **any** success kills. Run A, 8 instances per direction = 800 proof checks.

| | verdict |
|---|---|
| **planted control** (`∀ x : ℝ, -7 ≤ x → x ≤ 1 → 3 ≤ -2x² - 12x + 17`, the v1 shape) | **DEAD — `by intros; nlinarith`** |
| v2 (negative control) | survives 20/20 on all 8 |
| H1_twoatom | survives 20/20 on all 8 |
| H2_quartic | survives 20/20 on all 8 |
| H3_nested | survives 20/20 on all 8 |
| H4_twoatom_quartic | survives 20/20 on all 8 |

**Kill table: nothing was killed.** The control is what makes that sentence mean anything — the
harness raises `ControlFailed` and aborts if the known-dead v1 shape survives. Every direction
inherits v2's mechanism (`Real.sqrt (…)` is an opaque atom to `linarith`/`nlinarith`, `positivity`
only sees `0 ≤ e` shapes, `gcongr` has no relational template) and adds structure on top, so
survival is expected; it is measured anyway because battery resistance is a property of *this*
Mathlib, not a theorem.

> **Correction, recorded.** Run B was launched with `--skip-battery` and the harness printed a
> vacuous `battery survives 8/8` for H2/H4 — a verdict for a battery that never ran, with the
> planted control also skipped. The harness now prints `SKIPPED (not measured)` and stores
> `battery_killers: null`; `lean_b.json` carries a `_correction` field. **The battery numbers
> above are run A's**, which did execute the control. This is the same class of defect as
> `retune-notes.md` §8's silently-skipped R3, caught this time by writing the gate down before
> reading it.

---

## 4. Witness (axis b) — the generator must prove its own leaves

A direction whose generator cannot prove its own leaf is not a rung. Run A found two:
**H2 1/8** and **H4 3/8**. Both were template bugs, both are fixed, both now kernel-check 8/8.

### 4.1 The bug and the fix

The failing conjunct is `a(x−m)⁴ + e ≤ t²`. `nlinarith` preprocesses by multiplying *pairs* of
hypotheses; the band product `(x−lo)(hi−x) ≥ 0` is a degree-2 certificate and no pair of the
available facts is a degree-4 upper bound on `(x−m)⁴`. The flat degree-2 witness simply had no
step for it. Naming the intermediate fixes it in two lines:

```
have hs : (x−m)² ≤ far²          -- linear consequence of the band product
have hq : (x−m)⁴ ≤ far⁴          -- pair (far² − u ≥ 0, u ≥ 0) → far²u − u² ≥ 0,
                                 -- then u² ≤ far²u ≤ far⁴ by pure linarith
```

No extra oracle knowledge: the generator already knows `m` and `far = max(|lo−m|, |hi−m|)`.

**Registered prediction P1 (before the run): H2 ≥ 7/8 and H4 ≥ 7/8 after the fix. Measured 8/8
and 8/8. Confirmed.**

**Registered prediction P2: numeral size is not the obstacle.** The probe cells reach
`max|coef| = 663,598` (band `[-29,-21]`, `a(x+24)⁴`) and the fixed witness closes there too.
Degree, not numeral magnitude, was the failure. Confirmed — *for the kernel*. It says nothing
about whether numeral magnitude affects the **model**; see §6.2, where it becomes the reason to
hold the quartic directions back.

### 4.2 The five witness templates, verbatim (all kernel-checked)

`Real.sqrt_le_iff`'s conjunct order is probed at runtime, not guessed: this Mathlib is **`nt`**
(non-negativity first), determined by two throwaway proofs whose conjuncts need different tactics.

**v2 — 8/8**
```lean
∀ x : ℝ, -7 ≤ x → x ≤ -1 → 3 ≤ 7 - Real.sqrt (x ^ 2 + 8 * x + 23)
by
  intro x hl hr
  have hb1 : Real.sqrt (x ^ 2 + 8 * x + 23) ≤ 4 :=
    Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]⟩
  linarith
```

**H1_twoatom — 8/8**
```lean
∀ x : ℝ, -7 ≤ x → x ≤ -1 → 3 ≤ 12 - Real.sqrt (x ^ 2 + 8 * x + 23) - Real.sqrt (2 * x ^ 2 + 16 * x + 39)
by
  intro x hl hr
  have hb1 : Real.sqrt (x ^ 2 + 8 * x + 23) ≤ 4 :=
    Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]⟩
  have hb2 : Real.sqrt (2 * x ^ 2 + 16 * x + 39) ≤ 5 :=
    Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]⟩
  linarith
```

**H2_quartic — 8/8 (fixed)**
```lean
∀ x : ℝ, -7 ≤ x → x ≤ -1 → 3 ≤ 13 - Real.sqrt (x ^ 4 + 16 * x ^ 3 + 96 * x ^ 2 + 256 * x + 275)
by
  intro x hl hr
  have hs1 : (x + 4) ^ 2 ≤ 9 := by nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]
  have hq1 : (x + 4) ^ 4 ≤ 81 := by nlinarith [hs1, sq_nonneg (x + 4)]
  have hb1 : Real.sqrt (x ^ 4 + 16 * x ^ 3 + 96 * x ^ 2 + 256 * x + 275) ≤ 10 :=
    Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr), hs1, hq1]⟩
  linarith
```

**H3_nested — 8/8**
```lean
∀ x : ℝ, -7 ≤ x → x ≤ -1 → 3 ≤ 7 - Real.sqrt (x ^ 2 + 8 * x + 18 + Real.sqrt (2 * x ^ 2 + 16 * x + 39))
by
  intro x hl hr
  have hv1 : Real.sqrt (2 * x ^ 2 + 16 * x + 39) ≤ 5 :=
    Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]⟩
  have hb1 : Real.sqrt (x ^ 2 + 8 * x + 18 + Real.sqrt (2 * x ^ 2 + 16 * x + 39)) ≤ 4 :=
    Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr), hv1]⟩
  linarith
```

**H4_twoatom_quartic — 8/8 (fixed)**
```lean
∀ x : ℝ, -7 ≤ x → x ≤ -1 → 3 ≤ 20 - Real.sqrt (x ^ 2 + 8 * x + 23) - Real.sqrt (2 * x ^ 4 + 32 * x ^ 3 + 192 * x ^ 2 + 512 * x + 519)
by
  intro x hl hr
  have hb1 : Real.sqrt (x ^ 2 + 8 * x + 23) ≤ 4 :=
    Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]⟩
  have hs2 : (x + 4) ^ 2 ≤ 9 := by nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]
  have hq2 : (x + 4) ^ 4 ≤ 81 := by nlinarith [hs2, sq_nonneg (x + 4)]
  have hb2 : Real.sqrt (2 * x ^ 4 + 32 * x ^ 3 + 192 * x ^ 2 + 512 * x + 519) ≤ 13 :=
    Real.sqrt_le_iff.mpr ⟨by norm_num, by nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr), hs2, hq2]⟩
  linarith
```

Witness length is itself informative: v2 needs 3 lines, H1/H3 need 4, H2 needs 5, H4 needs 6.

---

## 5. Idiom ceiling (axis d) — and the instrument audit that narrows it

The probe templates the **measured** DSV2 shape (`sqrt_nonneg` per atom, then
`apply Real.sqrt_le_iff.mpr / constructor / nlinarith / nlinarith [hints]` per bounded atom, then a
final `nlinarith [hints]`) with the *generous* hint bag `sq_nonneg` at every vertex and both band
endpoints — generous because the model would have to complete the square to find a vertex and the
probe is handed it. A direction the oracle-hinted idiom cannot close is one the model certainly
cannot close by copying.

### 5.1 Calibration: does the instrument discriminate? **No — and that matters.**

Run A calibrated on the first 10 measured leaves by `statement_key`; all 10 happened to have
measured pass@8 = **1.000**. That proves the template *fits* and proves nothing about whether it
*separates*. Run B re-calibrated on a stratified sample: the **18** case_tree leaves with
pass@8 < 1.0 (the full sub-ceiling tail: 0.25, 0.375, 0.5, 3×0.625, 6×0.75, 6×0.875) plus **10**
at 1.0. Leaves are recovered by regenerate-and-join on the prop string, per the F1 forensics
lesson that the id suffix is a flat counter and not a generator index; 28/28 recovered.

| stratum | n | recovered | base idiom closes |
|---|---|---|---|
| measured pass@8 < 1.0 | 18 | 18 | **18/18** |
| measured pass@8 = 1.0 | 10 | 10 | **10/10** |
| — of which the single 0.25 leaf | 1 | 1 | **closes** |

**Registered prediction P3 was ≥ 15/18. Measured 18/18. Confirmed, in the direction that weakens
the instrument.**

**What this licenses, and what it does not.** The base-idiom probe is a *route detector*: it
answers "does the memorised one-shot apply to this piece shape at all?" — binary, per schema. It
is **not** a difficulty meter: within a schema where the route applies, closing tells you nothing
about whether DSV2 lands it 2 times in 8 or 8 times in 8. So:

- `base fails` on H1/H2/H3/H4 is a real, strong signal — the memorised route stops applying at the
  schema level. That is the whole reason a schema ladder can move a number that no knob could.
- **Every landing-point estimate in §7 is carried by the adaptation ladder and the offline target
  widths in §6, never by the base probe.** The base probe supplies the ordering's zero point only.

### 5.2 The ladder, per direction (n = 8 instances each)

`base` = one-shot copy of the measured proof. Everything else is an ADAPTATION — something the
model would have to *think of*, not copy.

| variant | v2 | H1 | H2 | H3 | H4 |
|---|---|---|---|---|---|
| `base` | **8/8** | 0/8 | 0/8 | 0/8 | 0/8 |
| `adapt_evensplit` (naive `t//2`) | — | **4/8** | — | — | 0/8 |
| `adapt_oraclesplit` (generator's `cap₁,cap₂`) | — | **8/8** | — | — | 0/8 |
| `adapt_bothfull` (both atoms at `t`) | — | 0/8 | — | — | 0/8 |
| `adapt_oraclesplit_band` (+ band product) | — | — | — | — | **8/8** |
| `adapt_oraclesplit_deg4` (+ band product + quartic square) | — | — | — | — | **8/8** |
| `adapt_innerfull` (inner root ≤ visible `t`) | — | — | — | **3/8** | — |
| `adapt_oracleinner` (inner root ≤ its own cap) | — | — | — | **8/8** | — |
| `adapt_degreehint` (band product + quartic square) | 8/8 | — | **8/8** | — | — |
| `adapt_bandprod` (band product only) | — | — | **8/8** | — | — |
| `adapt_vertexquartic` (quartic square only) | — | — | **0/8** | — | — |
| `adapt_sqsqrt` (materialise `√u ^ 2 = u`) | 5/8 | 0/8 | 0/8 | 0/8 | 0/8 |

**Registered prediction P4 was: `adapt_bandprod` 2–6/8 and `adapt_vertexquartic` ≥ 6/8.
Measured 8/8 and 0/8 — refuted, with the sign flipped.** The degree-lifting square is useless on
its own; the *band product* is the entire lever for H2. Two readings, and the honest one is the
second:

- H2's base failure is **not** a logical gap. The one-have-step route is logically sufficient for
  H2; it fails only because `nlinarith`'s pair search does not reach the right product from the
  context hypotheses `hx1, hx2` inside its budget. Handing it `mul_nonneg (sub_nonneg.mpr hx1)
  (sub_nonneg.mpr hx2)` — a standard, widely-emitted Lean idiom — closes all 8.
- So H2's barrier is a **hint-repertoire** barrier, not a structural one, and it is the weakest
  barrier in this survey. It is also the one most likely to be an artifact of `nlinarith`'s search
  budget rather than of the mathematics, which makes its projection the least trustworthy.

By contrast H1's base failure **is** a logical gap: `base` bounds `√u₁ ≤ t` and the goal needs
`√u₁ + √u₂ ≤ t`, from which `√u₂ ≥ 0` gets you nothing. `adapt_bothfull` (both atoms bounded by
the whole budget) is likewise unsound as a route and duly measures 0/8. No hint can rescue either.
The prover has to produce a second `have` **and** a correct split. Same for H3 one level down:
the outer radicand contains an opaque `√v` with no bound in context, so the extra `have` is
forced.

And H4 needs **both** inventions: `adapt_oraclesplit` alone is 0/8, `adapt_oraclesplit_band`
is 8/8. Composition, not coincidence.

---

## 6. The two offline levers, and flatness

### 6.1 How wide is the numeric target? (run C + exhaustive offline)

The structural invention (an extra `have`) is worth little if any bound closes it. Sweeping every
integer guess in Lean:

| instance | budget `t` | candidates swept | guesses that close | generator's |
|---|---|---|---|---|
| H1 max b[-7,-1] a1 o0 s0 | 9 | 8 | **[4]** | 4 ✓ |
| H1 min b[-1,7] a3 o0 s1 | 16 | 15 | **[8]** | 8 ✓ |
| H1 max b[-14,-6] a1 o1 s1 | 15 | 14 | **[6]** | 6 ✓ |
| H1 min b[2,8] a3 o-1 s0 | 13 | 12 | **[7]** | 7 ✓ |
| H3 max b[-7,-1] a1 o0 s0 | 4 | 7 | **[5]** | 5 ✓ |
| H3 min b[-1,7] a3 o0 s1 | 8 | 10 | **[8, 9]** | 8 ✓ |
| H3 max b[-14,-6] a1 o1 s1 | 6 | 11 | **[9, 10]** | 9 ✓ |
| H3 min b[2,8] a3 o-1 s0 | 8 | 8 | **[6]** | 6 ✓ |

**Registered prediction P5 was: median ≤ 4 closing splits, always including the generator's.
Measured 1 (H1) and 1–2 (H3), always including it. Confirmed, tighter than predicted.**

For H1 this is provable, not just measured. The band maximum of `Uᵢ` is exactly `capᵢ² − slackᵢ`
with `slackᵢ ∈ {0,1}`, so the least integer bound that is *true* for atom `i` is exactly `capᵢ`;
and `cap₁ + cap₂ = t` by construction. Hence `s ≥ cap₁` and `t − s ≥ cap₂` force `s = cap₁`:
**a target of width 1**. Checked exhaustively offline — the feasible split set equals `{cap₁}` in
**4,000/4,000** random instances.

Two facts qualify how hard that target is to hit, and they point in opposite directions:

| lever | H1_twoatom | H4_twoatom_quartic | H3_nested |
|---|---|---|---|
| naive even split is the right guess | **35.9%** (719/2000) | **0.0%** (0/2000) | n/a |
| \|cap₁ − t/2\| median / max | 0.5 / **2.0** | 9.0 / 19.5 | n/a |
| lazy "bound it by the visible `t`" is legal | n/a | n/a | **64.5%** (1291/2000) |

(Legal ≠ closing: H3's lazy guess is a *true* statement 64.5% of the time but `adapt_innerfull`
closes only 3/8, because a loose inner bound also has to leave `nlinarith` enough room on the
outer step. Legality is the ceiling on the lazy route, not its rate.)

So H1's unique target sits **within ±2 of the obvious guess** — a five-candidate neighbourhood
covers 100% of leaves, and the obvious guess itself is right 36% of the time. That is corridor
shaped: not free, not out of reach, and *sampled 8 times*. H3's target has no such anchor (it can
exceed the visible budget entirely — the generator's inner cap was 5 against a visible `t` of 4,
and 9 against 6, in two of four probe cells), which is why H3 is the harder rung. H4's split is
never near the even guess, which is why nothing non-oracle closes it.

**This is also the difficulty knob case_tree does not currently have.** `|cap₁ − t/2|` is
directly tunable by the second atom's curvature and degree — measured range **0.5** (two matched
quadratics) to **9.0** (quadratic + quartic) — so an H1 ladder has a continuous lever between
"the even split usually works" and "the even split never works". F1's finding was that *no*
marginal inside the shipped support moves the number; this one does, by construction.

### 6.2 Flatness in k — where the quartic directions fail

`FAMILIES.md` requires per-node difficulty flat in k. case_tree's *only* k-dependence is a band's
absolute position: the domain is `[-T/2, T/2]` with `T ≈ 7k`, so a radicand's constant coefficient
grows with `m^deg`. Generated offline, n = 300 leaves per (direction, k), no Lean:

| direction | leaf prop chars, k=2 → k=32 | max\|coef\| median, k=2 → k=32 | growth |
|---|---|---|---|
| v2 | 68 → 73 (+5) | 31 → 4,170 | **134×** |
| H1_twoatom | 104 → 113 (+9) | 39 → 7,570 | **194×** |
| H3_nested | 103 → 113 (+10) | 39 → 7,633 | **196×** |
| H2_quartic | 98 → 111 (+13) | 324 → 14,707,723 | **45,394×** |
| H4_twoatom_quartic | 134 → 151 (+17) | 324 → 17,006,129 | **52,488×** |

Worst single leaf at k=32: v2 37,647; H1 38,996; H3 40,387; **H2 472,055,823; H4 439,230,016.**

Statement verbosity is flat everywhere (+5 to +17 characters across a 16× change in k), and the
cap support is **exactly** k-independent for every direction *by construction*, not by
measurement: `cap = _cap(a·far^deg + slack)` and `far = max(|lo−m|, |hi−m|)` depend only on
`(width, curvature, offset, slack)` — never on the band's absolute position. Measured maxima
confirm it (v2 9, H1 18, H2 44, H3 10, H4 53, identical at k = 2/4/8/16/32). So the outer
constant, the thing a prover reads its budget off, does not move with k in any direction. Good.

The coefficient axis is the problem. F1 measured max|coef| bucket against pass@8 on the real bank
and found it **flat** (0.885 / 0.938 / 0.949) — but over a range of 1–2,200. v2 at k=32 stays
inside a 17× extension of that range; **H2/H4 at k=32 are five orders of magnitude past it.**
Nothing measured says a nine-digit numeral inside `Real.sqrt` behaves like a four-digit one for a
7B prover: tokenisation alone changes, and `norm_num`'s cost on the non-negativity conjunct
changes with it.

This is precisely the shape of failure that `retune-notes.md` §8 documents for bridge_chain: a
difficulty gradient along an axis that grows with k, on an axis nobody measured, discovered only
after R1/R2 had passed and the family was written up as DONE. **Do not ship a quartic rung
without first measuring pass@8 against coefficient magnitude directly.** That measurement is
cheap (it is a stratified re-slice of any k-grid run) and it is a prerequisite, not a nicety.

### 6.3 Necessity stays structural (axis b, the `_repair_necessity` no-op)

`case_tree._repair_necessity` never fires under the shipped knobs because a piece's super-level
set reaches at most `2·|offset| + ε ≤ 2.24` past its own band, and `min(WIDTHS) = 6`, so every
band keeps its (integer) midpoint private. A repair that fired at k-dependent rates would itself
be a flatness leak — that constraint is why the bound exists.

Reach is a function of `(width, a, offset, slack)` and the derived second-atom knobs only, not of
absolute position, so the knob support can be swept **exhaustively** rather than sampled. Over
all 360 cells (2 widths × 3 curvatures × 3 offsets × 2 slacks × 2 variants × 5 band positions
spanning the k=2…32 domain), evaluating `holds_at` on `[lo−40, hi+40]`:

| direction | cells | max integer reach past own band | cells with reach ≥ 3 | width/2 |
|---|---|---|---|---|
| v2 | 360 | 2 | **0** | 3 |
| H1_twoatom | 360 | 2 | **0** | 3 |
| H2_quartic | 360 | 2 | **0** | 3 |
| H3_nested | 360 | 2 | **0** | 3 |
| H4_twoatom_quartic | 360 | 2 | **0** | 3 |

Every direction keeps reach < width/2, so `repaired_frac == 0.0` is preserved and the leaf-knob
distribution stays exactly k-independent. H1/H3/H4 are in fact *tighter* than v2 (mean spill
0.81/0.87/0.89 vs 1.33) — adding a second non-negative atom can only shrink the super-level set.
**Caveat:** this is exhaustive over the current knob support, not an analytic bound. Widening the
support (which the §6.1 lever proposes doing) requires re-running this sweep or re-deriving the
bound; the harness does it in under a second.

---

## 7. Ranking, with mechanism — and registered projections

### 7.1 The mechanism model

The measured taxonomy says DSV2 emits one template. A schema change costs the model *inventions* —
discrete things it must produce that are not in the template. The probes measure exactly two
kinds, plus how big the target is:

| direction | structural inventions | numeric target | anchored? | lazy default legal | measured routes |
|---|---|---|---|---|---|
| v2 | 0 | cap is `A − C`, read off the goal | — | — | base 8/8, sq_sqrt 5/8 |
| **H2** | 0 steps, **+1 hint** (band product) | none — cap unchanged | — | — | +bandprod 8/8 |
| **H1** | **+1 `have`** | **1 of 8–16** (`t` = 9–17), provably `cap₁` | **yes, within ±2 of `t/2`** | even split 35.9% | oracle 8/8, even 4/8 |
| **H3** | **+1 `have`** | 1–2 of 7–11 | **no** — may exceed visible `t` | inner ≤ `t` 64.5% legal, 3/8 closes | oracle 8/8, lazy 3/8 |
| **H4** | **+1 `have` and +1 hint** | 1 of 16–51 (`t` = 17–52) | **no** — even split legal 0.0% | none | oracle+band 8/8, all else 0/8 |

Ordering by expected pass@8: **v2 > H2 > H1 > H3 > H4**, and the ordering is carried by the
invention count first, target anchoring second.

### 7.2 Registered projections (before any pod measurement)

Calibrated against the only two anchors that exist — case_tree v2 (base closes, 0 inventions,
measured **0.923**) and bridge_chain (`retune-notes.md` §5: short idiomatic route closes 4/6 →
measured **0.429**; closes 0/6 → measured **0.13–0.20**).

| direction | projected mean pass@8 | interval | corridor verdict |
|---|---|---|---|
| H2_quartic | **0.60** | 0.45 – 0.80 | in band, near the ceiling; widest uncertainty |
| **H1_twoatom** | **0.45** | 0.30 – 0.60 | **in band, centred on the target** |
| H3_nested | **0.30** | 0.15 – 0.45 | in band but hugging the floor |
| H4_twoatom_quartic | **0.05** | 0.00 – 0.15 | **below the floor** |

**Pre-registration, and what moved.** P1–P5 above were written before run B/C. A P6 was
registered at the same time, from run A's evidence only: `H2 0.55–0.80 > H1 0.35–0.60 >
H3 0.25–0.45 > H4 0.00–0.10`. The table above is the post-evidence revision, and the changes are
small and directional: H2's lower bound dropped (0.55 → 0.45) once `adapt_vertexquartic` measured
0/8, showing the barrier is a hint-repertoire artifact of `nlinarith`'s search rather than
mathematics; H1's and H3's lower bounds dropped (0.35 → 0.30, 0.25 → 0.15) once run C proved the
numeric target is a *single* integer rather than a handful; H4's upper bound rose (0.10 → 0.15)
because the witness fix showed it is a sound, provable schema rather than a broken one. **The
ordering did not change.** Recording both so the revision is auditable rather than invisible.

These are **extrapolations off the measured support** — there is no measured case_tree leaf for
which the base idiom fails, so every one of these is outside the range the anchor was fitted on.
That is the same status `retune-notes.md` §5 gave `e3_lowdeg` ("20/30 leaves below the fitted es
support — extrapolation"), and that projection scored MAE 0.044 (`research/lever-model-refit.md`)
— which is encouragement to measure, not licence to skip measuring. **If the pod contradicts
these, the contradiction is the finding.**

### 7.3 Recommendation

1. **`H1_twoatom` is the rung to build.** It is the only direction that is simultaneously
   (i) projected nearest 0.45, (ii) flat in k on the same axis and to the same degree as v2
   (194× vs 134× coefficient growth; +9 chars over a 16× k range), (iii) exact and
   necessity-preserving with a *tighter* spill than v2, (iv) battery-surviving with the control
   live, (v) self-certifying in 4 lines, and — decisively — (vi) it ships with a continuous
   difficulty lever (`|cap₁ − t/2|`, measured range 0.5–9.0) that case_tree currently lacks
   entirely. Overshoot and undershoot are both correctable *within* the direction, which is the
   property F1 proved v2 does not have.
2. **`H3_nested` is the second rung**, to be materialised alongside H1 in the same pod run so the
   two are measured on the same day and the same sampling profile. If H1 lands high, H3 is the
   next step up; if H1 lands low, H3 is dropped rather than debugged.
3. **`H2_quartic`: measure the coefficient-magnitude axis first.** The direction is clean on every
   axis this survey tested and its projection is the highest, so it is the natural *lowest* rung —
   but its sole k-dependence grows 45,000× across the k-grid, five orders of magnitude past the
   range in which coefficient magnitude was measured to be difficulty-neutral. Shipping it before
   that measurement would be bridge_chain's R3 mistake with a different variable name.
4. **`H4_twoatom_quartic`: hold as the top rung, do not measure yet.** Witness fixed, predicate
   exact, battery-surviving — it is a legitimate schema. But every non-oracle route measures 0/8,
   the even split is legal in 0 of 2,000 instances, and it inherits H2's flatness leak in full
   (52,488× coefficient growth). Measure it only if H1 lands above 0.8 — i.e. only if the ladder
   turns out to need a rung above H1 — and only after the coefficient-magnitude study item 3 asks
   for, which gates H4 for the same reason it gates H2.
5. **`v2` stays the control**, not a candidate: it is the shipped schema and it measures 0.923.

Pod plan: materialise H1 and H3 at k ∈ {2,4,8} into a fresh candidate file, run the same
`build_bank` recipe `retune-notes.md` §0 specifies (same leaf model, same template, **no**
`--leaf-max-tokens`/`--leaf-temperature` overrides — `leaf_id` carries the sampling profile and a
different profile is a different experiment), include ~30 fresh v2 leaves as a same-day control,
and apply R0–R4 **including R3** with per-k means reported for every direction, shipped or not.
Add an R3′ for coefficient magnitude if any quartic rung is in the run.

---

## 8. What this survey does not establish

1. **No pass@8 was measured.** Battery and witness and exactness are definitive; the idiom ladder
   is a proxy whose calibration is now known to be non-discriminating within a schema (§5.1).
2. **The base-idiom probe cannot rank two directions that both fail it.** H1 vs H3 vs H4 are
   ordered by the *adaptation* results and the offline target widths, both of which are
   hand-constructed routes. Three hand routes are not eight DSV2 samples — `retune-notes.md` §7.1
   makes the same disclaimer and the measured bank later produced a 20-line chained proof no hand
   probe would have found.
3. **H2's barrier may be a tactic-budget artifact.** `adapt_bandprod` supplies a product
   `nlinarith` could in principle synthesise from `hx1, hx2` alone. If a future Mathlib or a
   larger `nlinarith` degree closes H2's base, the direction evaporates. Battery resistance has
   the same caveat and the same mitigation: the gate is re-runnable with its control attached.
4. **The projections in §7.2 are anchored on two families and four points.** They rank; they do
   not predict a value.
5. **Only the ALGEBRAIC-DEPTH axis was probed.** abs/floor caps, two-variable pieces,
   reciprocal/quotient pieces and product-of-atoms were not tested here; the brief assigns the
   functional axis to survey B.
6. **The exhaustive spill sweep is over the *current* knob support.** The §6.1 lever proposes
   widening it. Re-run §6.3 before shipping any widened support.

---

## 9. Contract friction and flags

1. **A `--skip-battery` run printed a battery verdict.** Found and fixed mid-task (§3). The
   general lesson is the one `retune-notes.md` §8 already paid for: a gate that reports a verdict
   it did not measure is worse than no gate. `lean_b.json` carries a `_correction` field and the
   harness now emits `SKIPPED (not measured)`.
2. **A narrow follow-up run clobbered the full audit artifact.** Run B's
   `--directions H2,H4 --n-random 60` overwrote `audit.json`, which had held the 5-direction /
   300-instance audit. Restored from the copy embedded in `lean.json`; the harness now writes
   `audit{tag}.json` so a tagged run cannot replace an untagged one. No data was lost, but it was
   luck that `lean.json` embeds the audit.
3. **`FAMILIES.md`'s corridor is a distributional target and `case_tree` has no operational
   R-rules of its own.** `retune-notes.md` §6 wrote R0–R4 for bridge_chain and they were adopted
   informally. A case_tree ladder needs its own written decision rule *before* the pod run —
   including R3, and including the coefficient-magnitude axis (§6.2) if any quartic rung is in it.
   Not written here: `FAMILIES.md` is not an owned file.
4. **The proposed H1 difficulty lever widens the knob support**, which touches
   `case_tree.CURVATURES` / the second-atom draw and therefore `_repair_necessity`'s validity
   argument (§6.3) and the distinct-leaf capacity that `FAMILIES.md`'s GRPO-correlation note asks
   datasheets to report. Both are re-checkable for free; neither is checked here, because
   `src/rlmath/families/case_tree.py` is not an owned file and no schema change was made to it.
5. **F1's distinct-leaf-capacity finding applies with more force to two-atom directions.** The
   shipped schema's true distinct-leaf space saturates in the low thousands at k=8. H1's second
   atom is drawn deterministically from the first, so it multiplies the *statement* space without
   multiplying the *knob* space — the effective distinct-leaf capacity does not grow as much as
   the statement length suggests. Worth a datasheet column if H1 ships.
6. **No GPU/LM measurement was made in this task.** Every number is local Lean or free offline
   generation. The `case_tree` pass@8 figures quoted in §1 are the existing bank's.
