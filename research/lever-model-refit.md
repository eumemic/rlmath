# bridge_chain lever-model refit — 150 fresh rows + pooled 220

Owned file: this note only. Touches no code, no other doc. Companion to
`research/retune-notes.md` (the staging log this refits) and answers repo task
#17 (F2): re-fit the difficulty-lever model on the GPU session's 150 fresh
`data/bank/retune_measure.jsonl` rows, confirm/refute the within-chain
gradient, and draft the DIRECTION.md §5.4(a) consequence.

**TL;DR**

1. **Every individual lever from `retune-notes.md` §2 replicates out of
   sample** when tested on its own experimental design (pooled v2-only,
   n=100: right-function 0.219/0.073 vs in-sample 0.206/0.074; δ 0.241/0.076
   vs 0.210/0.095; es-bucket 0.256/0.093/0.060 vs 0.233/0.114/0.054; offset
   0.183/0.120 vs 0.194/0.101 — see §2.3). None of them was an in-sample
   marginal artifact.
2. **The *ladder* (rung-to-rung) framing that the §5 projection used does
   not decompose as cleanly.** Only the low-degree/es_left lever (e3 vs e2)
   produced a large, significant rung jump (+0.163, z=2.82). The
   func-only and offset rungs are directionally right but not significant at
   n=30/rung (z=1.29, z=0.79). The δ rung (e2 vs e1) measured **≈0 net**
   (z=−0.31) *despite* δ having a robust, well-identified, highly significant
   direct effect once es_left is held fixed (z=−4.47, pooled v2+e1_sqrt,
   near-zero collinearity) — §2.4 traces this to a real confound the ladder
   design didn't control: restricting δ's support changes which `(c,d,o)`
   states the rejection sampler can occupy (`live_states` is
   preset-dependent), which quietly reshapes the other five knobs enough to
   roughly cancel δ's per-leaf benefit at the population level.
3. **The within-chain gradient is CONFIRMED, and it is not a k=16/32 risk —
   it is already breached at the measured k∈{2,4,8} grid for the chosen
   preset.** `e3_lowdeg`'s own per-k means are 0.575 / 0.463 / 0.250 at
   k=2/4/8 (k2-vs-k8 z=3.07, k4-vs-k8 z=2.94) — a spread 6.5× the retune's
   own R3 gate (±0.05). Pass-rate falls with left-exponent-sum in **every**
   preset tested (slope −0.025 to −0.052 pass-rate-points/unit, significant
   in 4/5). Linear extrapolation of e3's slope puts the mean below the 0.25
   corridor floor by k≈16; by k=32 the linear extrapolation goes negative,
   which is itself evidence the true decay is not linear that far out — but
   the data cannot say what shape it takes past position 8, because no leaf
   in this dataset has position > 8.
4. **DIRECTION §5.4(a) needs a second flatness axis, not just a k axis.**
   Draft text in §4 below.

---

## 0. Data and a contract-friction note (n=58 → n=70)

The task brief cites "the difficulty-lever model fitted IN-SAMPLE on n=58
leaves (`data/bank/family_leaf_calibration.jsonl`, the bridge_chain rows)".
As of this refit that file has **70** bridge_chain rows, not 58:

```
k=2  n=10  mean pass@8 = 0.225   (identical to the number retune-notes §3 cites for v2 at k=2)
k=4  n=20  mean pass@8 = 0.125   (identical to the number retune-notes §3 cites for v2 at k=4)
k=8  n=40  mean pass@8 = 0.106   (retune-notes §3 cites 0.129 for the original run)
```

`scripts/bakeoff/session3.sh` step 2/3 ("calibration completion (case_tree
remainder)") re-ran `build_bank.py` on `data/families/family_leaves_candidates.jsonl`
with `--out data/bank/family_leaf_calibration.jsonl` — an overwrite, not an
append, of a file whose comment says it exists to complete **case_tree's**
measurement. Its side effect was to also grow bridge_chain's k=8 slice from
28 to 40 leaves (68 case_tree rows also entered the file this way). The k=2
and k=4 subsets are byte-identical in row count and mean to the numbers
retune-notes §2/§3 report, so this is **a superset, not a resample or a
different distribution** — all 70 rows carry knobs inside the v2 preset's
declared ranges (`coef_range`/`fcoef_range`/`offset_range` all satisfied,
`funcs` spans both `sqrt`/`log`, `deltas` spans both 1/2, `es_left` floors at
3 = `sum(START_EXPONENTS)`), confirmed by parsing every row's `prop` text
with `scripts/stage_retune_candidates._knobs_of` (imported, not modified).

**Resolution:** this refit uses all 70 as "the calibration set" (not a
58-row subset picked to match the brief's number, which would be an
unprincipled post-hoc filter). §2.3's "pooled 58+150" instruction is
therefore reported as **pooled v2-only, n=100** (70 calibration + 30 fresh
v2-preset rows from `retune_measure.jsonl`) — same experimental design on
both sides of the pool (full-range v2 knobs), which is what makes the pool a
legitimate out-of-sample test rather than a mixture of different sampling
regimes. Flagged, not silently reinterpreted.

**Provenance of the 150 fresh rows.** Joined `data/bank/retune_measure.jsonl`
(measured `pass_rate`/`n_verified`/`status`) onto `data/families/retune_candidates.jsonl`
(knobs: `preset`, `k`, `position`, `es_left`, `es_right`, `delta`, `c_left`,
`d_left`, `o_left`, `c_right`, `d_right`, `o_right`, `func_left`,
`func_right`) via `source_id.removeprefix("json#")` ↔ `id`. 150/150 rows
joined with matching `statement_key` and `prop`/`formal_statement` (exact
string equality checked, 0 mismatches); no regeneration through
`rlmath.families.bridge_chain` was needed — the staged candidates file
already carries every knob as a flat column, which is exactly what
`stage_retune_candidates.py`'s docstring says it's for. All 150 rows have
`elaborates=true`, `status != "error"`, `n_attempts=8`.

---

## 1. Preset-level refit (headline numbers)

| preset | n | measured mean | emp. SE | band-fit [0.25,0.9] | zero-rate | §5 projected | error | rel. error |
|---|---|---|---|---|---|---|---|---|
| v2 (control) | 30 | 0.1958 | 0.056 | 0.27 | 0.57 | 0.160 | +0.036 | +22% |
| e1_sqrt | 30 | 0.2833 | 0.038 | 0.57 | 0.10 | 0.243 | +0.040 | +17% |
| e2_flatstep | 30 | 0.2667 | 0.037 | 0.60 | 0.20 | 0.353 | **−0.086** | **−25%** |
| e3_lowdeg | 30 | **0.4292** | 0.044 | 0.83 | 0.07 | 0.404 | +0.025 | **+6%** |
| e4_slack | 30 | 0.3125 | 0.045 | 0.60 | 0.17 | 0.345 | −0.033 | −9% |

(The `band`/`zero` figures reproduce HANDOFF.md's cited 0.83 band-fit for
`e3_lowdeg` exactly — cross-check that this join and this pipeline reproduce
the number already reported from the live session.)

SE is the **empirical** (leaf-level) standard error — `std(pass_rate)/√n` —
which is larger and more honest than the naive binomial SE
`√(p̄(1−p̄)/(n·8))` (0.026–0.032 across presets) because it captures real
between-leaf heterogeneity, not just 8-sample binomial noise. All numbers
below use the empirical SE unless stated.

### 1.1 Scoring the §5 projection method

MAE = 0.044, RMSE = 0.049, Pearson r = 0.83 (n=5), Spearman ρ = 0.70.

- **Projected rank:** v2 < e1_sqrt < e4_slack < e2_flatstep < e3_lowdeg.
- **Measured rank:** v2 < e2_flatstep < e1_sqrt < e4_slack < e3_lowdeg.
- Only one adjacent-pair swap (e1_sqrt ↔ e2_flatstep), traced in §2.4 to the
  δ-restriction confound, not a projection-methodology failure per se.
- **R1 (nearest 0.45) picks the same preset either way**: `e3_lowdeg` is
  nearest to 0.45 under both the projected and the measured numbers. The
  decision the projection was built to support was made correctly.
- `e3_lowdeg` was explicitly flagged in §5 as extrapolation (26/30 of its
  leaves fall below the fitted es-support), and it is the **closest** of the
  five projections in relative terms (+6%). That is one data point, not a
  validated extrapolation capability — treat it as encouraging, not proven.

**What this means for the case_tree ladder's projections.** Use the cell-mean
projection to (a) size rung spacing well above the ~0.04–0.09 noise floor
this scoring measured, and (b) sanity-check which rung is likeliest to clear
the corridor floor before spending GPU time. **Do not** use it to read off
precise quantitative values, and **do not** trust a projected ranking between
two *adjacent* rungs — the one rank flip measured here (e1_sqrt vs
e2_flatstep, a true difference near 0 masked by a projected difference of
+0.11) is exactly the failure mode a case_tree ladder with similarly-spaced
rungs would be vulnerable to.

---

## 2. Which levers survive out of sample

### 2.1 Ladder decomposition (out-of-sample rung attribution, n=30/rung)

Each rung differs from its parent by exactly one declared knob change, so the
rung-to-rung *mean* difference is the marginal effect of that lever, measured
fresh (not fitted):

| rung comparison | Δ mean | emp. SE(Δ) | z | lever |
|---|---|---|---|---|
| e1_sqrt − v2 | +0.0875 | 0.068 | +1.29 | func: sqrt-only vs sqrt\|log mix |
| e2_flatstep − e1_sqrt | **−0.0167** | 0.053 | **−0.31** | δ: {1} vs {1,2} |
| e3_lowdeg − e2_flatstep | **+0.1625** | 0.058 | **+2.82** | start_exponents (1,0,0) vs (1,1,1) |
| e4_slack − e2_flatstep | +0.0458 | 0.058 | +0.79 | fixed offset=5, narrower coef/fcoef |

Only the low-degree/es_left lever clears conventional significance at
n=30/rung. This *matches* retune-notes §7.3's own framing ("es_left is the
single measured blocker") and is the strongest, cleanest result in this
refit.

### 2.2 Within-chain gradient regressions, per preset (§2.4 gives the pooled view)

`pass_rate ~ β₀ + β₁·es_left`, OLS, n=30 each (position gives numerically
**identical** slopes for e2_flatstep/e3_lowdeg/e4_slack, because those
presets fix δ=1 so `es_left = position + const` exactly — a useful internal
consistency check that the knob parser and the join are both correct):

| preset | slope (pts/es-unit) | SE | z | R² | es_left range |
|---|---|---|---|---|---|
| v2 | −0.025 | 0.018 | −1.35 | 0.06 | 3–14 |
| e1_sqrt | −0.033 | 0.011 | **−2.90** | 0.23 | 3–14 |
| e2_flatstep | −0.052 | 0.018 | **−2.92** | 0.23 | 3–10 |
| e3_lowdeg | −0.046 | 0.023 | **−2.01** | 0.13 | 1–8 |
| e4_slack | −0.044 | 0.024 | −1.82 | 0.11 | 3–10 |

Negative in all five, significant in 3/5 individually — see §3 for the
pooled, better-powered version of this same regression.

### 2.3 Pooled v2-only marginal refit (n=100: 70 calibration + 30 fresh), vs. the original in-sample table

| lever | cell | n (pooled) | mean pass@8 | in-sample (n=58) |
|---|---|---|---|---|
| right-hand function | `sqrt` | 52 | **0.219** | 0.206 |
| | `log` | 48 | 0.073 | 0.074 |
| step size | δ=1 | 44 | **0.241** | 0.210 |
| | δ=2 | 56 | 0.076 | 0.095 |
| left exponent sum | ≤4 | 40 | **0.256** | 0.233 |
| | 5–7 | 31 | 0.093 | 0.114 |
| | ≥8 | 29 | 0.060 | 0.054 |
| offset | o₁≤o₂ | 45 | **0.183** | 0.194 |
| | o₁>o₂ | 55 | 0.120 | 0.101 |
| function pair | √\|√ | 28 | **0.250** | 0.228 |
| | log\|√ | 24 | 0.182 | 0.179 |
| | √\|log | 25 | 0.090 | 0.116 |
| | log\|log | 23 | 0.054 | 0.029 |
| **combined** | δ=1 ∧ right √ | 25 | **0.340** | 0.283 |
| | es≤4 ∧ δ=1 ∧ right √ | 10 | **0.575** | 0.438 |

Every marginal replicates its sign and lands within ~0.02–0.06 of the
in-sample number — this is the strongest evidence in the whole refit that
**the individual §2 levers were not overfit**, only that composing them
additively into a ladder projection (§1.1, §2.4) is where the method loses
accuracy.

### 2.4 The δ confound, traced

§2.1's near-zero ladder jump for δ (e2−e1 = −0.017, z=−0.31) sits next to two
facts that say δ *does* matter per-leaf:

- **Pooled v2 marginal (n=100, §2.3):** δ=1 0.241 vs δ=2 0.076 — a large,
  clean difference, same direction and larger magnitude than the in-sample
  number.
- **Well-identified multivariate check**, `v2 + e1_sqrt` pooled (n=60, the
  only fresh subset where δ varies with near-zero collinearity to
  `es_left`: r=−0.01 in this subset):

  ```
  pass_rate ~ es_left + delta + I(preset=e1_sqrt)
    es_left            coef=−0.029  SE=0.009  z=−3.17
    delta              coef=−0.251  SE=0.056  z=−4.47   <- highly significant, es_left held fixed
    preset=e1_sqrt     coef=+0.069  SE=0.056  z=+1.23
  ```

  A one-unit δ increase costs ~0.25 pass-rate points independent of es_left —
  comparable to moving from es_left=1 to es_left=8. This is *not* a
  restatement of the es_left effect; it is a separate, robust, per-leaf
  causal-looking signal.

**Why the ladder rung doesn't show it.** `e1_sqrt`'s live `(c,d,o)` state set
is computed under `deltas=(1,2)`; `e2_flatstep`'s is computed under
`deltas=(1,)` — `live_states()` (`bridge_chain.py`) is a
greatest-fixed-point over *whichever* δ support the preset declares, so
restricting δ changes which `(c,d,o)` transitions the rejection sampler can
ever reach, not just which δ value gets drawn. Measured on the fresh rows,
the two presets' realized knob means do differ (e.g. `c_right` 5.60 vs 6.37,
`d_right` 4.17 vs 3.53, `o_right` 4.83 vs 5.27) even though neither preset's
*declared* ranges changed — only the reachable subset did. This is plausible
enough to explain a ~0.09-point offset that roughly cancels δ's ~0.25-point
per-leaf benefit (half of e1_sqrt's leaves draw δ=2, so the *expected*
direct benefit of dropping to e2 is ≈0.5×0.25=0.125, well above what the 12
noisy points of ±0.09 knob drift alone would predict cancelling — so this
mechanism is offered as the most plausible explanation available in this
data, not a fully closed case). **State plainly: this refit did not run a
controlled experiment that holds `live_states` fixed while flipping δ
support, so "confound via live-state redistribution" is the best-supported
hypothesis here, not a proven mechanism.**

### 2.5 c₁/d₁: was the "downstream of the congruence gate" suspicion right?

retune-notes §2 flagged `c₁`/`d₁` marginals (c₁≥5 → 0.177 vs c₁≤4 → 0.066) as
"almost certainly downstream of the congruence gate's downward walk rather
than causal." Tested directly (pooled v2, n=100): control for `es_left` and
see whether `c_left`/`d_left`'s independent coefficient survives.

| | univariate coef (z) | controlling es_left: coef (z) | corr(·, es_left) |
|---|---|---|---|
| `c_left` | +0.017 (1.66) | +0.014 (**1.42**, n.s.) | −0.10 |
| `d_left` | +0.027 (**3.26**) | +0.020 (**2.41**, still sig.) | −0.33 |

**Mixed verdict, not a clean confirmation.** `c₁`'s effect shrinks toward
non-significance once `es_left` is controlled (consistent with the
"downstream" suspicion, though it was only marginally significant to begin
with). `d₁`'s effect does **not** wash out — it stays significant
(z=2.41) even net of `es_left`, despite a real negative correlation with it
(r=−0.33). The retune-notes suspicion holds for `c₁`; it does not hold for
`d₁`, which looks like an independent lever nobody has staged a preset
around yet (higher `d₁`, the function-term coefficient, correlates with
*easier* leaves — plausible mechanism: a larger `d·F(M)` term gives
`nlinarith`/`linarith` more slack in the final inequality, independent of
the monomial's own size).

---

## 3. Within-chain gradient — confirmed, and already live at k≤8

HANDOFF flag 1 asked whether per-node difficulty is flat *within* a chain
even though it is flat *across* k. **Confirmed, with the strongest possible
version of the finding**: it is not merely a k=16/32 risk that survives
today's k∈{2,4,8} flatness gate — the gate is **already breached today** for
the preset that was picked.

### 3.1 e3_lowdeg per-k detail (the chosen preset)

| k | n | mean pass@8 | SE | zero-rate | band-fit | position range |
|---|---|---|---|---|---|---|
| 2 | 10 | **0.575** | 0.088 | 0.10 | 0.90 | 1–2 |
| 4 | 10 | **0.463** | 0.042 | 0.00 | 1.00 | 1–4 |
| 8 | 10 | **0.250** | 0.059 | 0.10 | 0.60 | 1–8 |

- k2 − k8 = 0.325, SE = 0.106, **z = 3.07**
- k4 − k8 = 0.213, SE = 0.072, **z = 2.94**
- retune-notes §6/R3's gate: "per-k means within ±0.05 of each other." The
  measured spread is **0.325 — 6.5× the gate's tolerance**, and the
  k2-vs-k8 gap is a 3-sigma result, not sampling noise at n=10/cell.
- At k=8 alone, band-fit (0.60) sits exactly on R2's pass/fail line and
  zero-rate (0.10) is inside the 0.20 cap — so the *aggregate* R1/R2
  decision (computed over all 30 leaves pooled across k) still clears the
  corridor. **R3 specifically, which is a per-k gate, does not clear it.**
  HANDOFF.md's Phase-1 status line ("bridge_chain DONE at preset e3_lowdeg
  … band-fit 0.83; 15/15 full-battery valid") does not mention R3, and this
  refit did not find an R3 verdict recorded anywhere for the chosen preset.
  **This is the headline finding of this note.**

For context, the *old* v2 flatness claim this whole retune was built on top
of ("k4 0.125 vs k8 0.129, within 0.004") does not reproduce on the fresh
30-row v2 control at n=10/cell (k2=0.238, k4=0.113, k8=0.238 — U-shaped, not
monotone) — a reminder that n=10/cell per-k means are noisy in general.
e3_lowdeg's result is not an artifact of that noise: it is monotone,
3-sigma, and mechanically exactly what the es_left slope in §2.2 predicts.

### 3.2 Pooled es_left/position slope (better-powered version of §2.2)

All 150 fresh rows, `pass_rate ~ es_left + preset dummies` (v2 baseline):

```
es_left            coef=−0.0353  SE=0.0079  z=−4.48   <- survives preset fixed effects
preset:e1_sqrt     coef=+0.085   SE=0.059   z=+1.43
preset:e2_flatstep coef=+0.038   SE=0.060   z=+0.63
preset:e3_lowdeg   coef=+0.130   SE=0.064   z=+2.04
preset:e4_slack    coef=+0.086   SE=0.060   z=+1.44
```

`es_left` remains highly significant *after* controlling for which preset
produced the leaf — this is not a preset-composition artifact, it is a
within-preset, within-chain effect that generalizes across all five knob
distributions tested.

### 3.3 Extrapolation to k=16/32 — what the data supports and what it does not

Position ranges 1–8 in every measured leaf (retune_candidates.jsonl's
`per_k` staging only reaches k=8). Linearly projecting e3_lowdeg's
position-slope fit (slope −0.046/pos, intercept 0.547) at the *mean*
position for larger k (≈(k+1)/2, the design's approximate position mix):

| k | mean position (approx.) | linear-projected mean pass@8 |
|---|---|---|
| 2 | 1.5 | 0.48 (measured 0.575 — model underfits the head) |
| 4 | 2.5 | 0.43 (measured 0.463 — close) |
| 8 | 4.5 | 0.34 (measured 0.250 — model **underestimates** the tail's decline) |
| 16 | 8.5 | **0.16** — below the 0.25 floor |
| 32 | 16.5 | **−0.21** — nonsensical |

**What this supports:** the sign and rough scale of the risk. The linear fit
already *underestimates* how much k=8's tail actually declines (0.34
projected vs 0.250 measured), so if anything the true k=16 mean is likely
**worse** than 0.16, not better — the flatness-in-k gate that "passes" today
only because k=4 and k=8's position mixes happen to be similar (as
retune-notes §7.3 predicted) is very unlikely to survive to k=16.

**What this does not support:** any literal number at k=16, and nothing at
all at k=32. No leaf in this dataset has position > 8, so k=32's projection
is extrapolating 4× past the edge of the measured range, and the fact that
the linear model produces an impossible negative pass rate there is itself
evidence the true relationship is not linear that far out (it must flatten
or floor near 0, not cross it) — but the *shape* of that flattening (does it
floor at some small positive rate the way v2's zero-rate suggests, or does
some fraction of leaves become permanently unprovable past a threshold
es_left?) is not something this dataset can distinguish. **Directly measuring
k=16 is the next value-for-money step, not further extrapolation of this
fit.**

---

## 4. Consequence for DIRECTION.md §5.4(a)

Current text (the row this refit bears on):

> | a | Per-node leaf pass-rate **flat in k** | *The* validity metric for the
> entire size axis. Without it, k confounds size with difficulty and the
> transfer plot means nothing |

**§3 shows a single "flat in k" axis is not sufficient**: `e3_lowdeg`'s k-level
mean (0.429) sits inside the corridor and its aggregate band-fit (0.83)
clears R2, yet its leaves are not exchangeable across position within a
chain — the *tail* of every chain is reliably harder than the *head*, in
every preset tested, with a slope that survives controlling for which preset
produced the leaf. A size axis built by handing the root longer chains at
larger k is silently also handing it position-mixes that skew harder, which
is exactly the "k confounds size with difficulty" failure the existing row
already names — just along an axis the current row's wording doesn't cover.

**Draft replacement** (for DIRECTION.md's owner to review, not applied here):

> | a | Per-node leaf pass-rate **flat in k** (across-chain axis) **and flat
> in chain position / left-exponent-sum within a chain** (within-chain
> axis) | *The* validity metric for the entire size axis, now in two parts.
> Without the across-k axis, k confounds size with difficulty and the
> transfer plot means nothing. Without the within-chain axis, a flat
> *k-level mean* can still hide a strong position-dependent gradient — late
> nodes in a long chain are reliably harder than early ones — which lets the
> size axis confound "more nodes" with "some much-harder nodes" even when
> per-k means look flat. Measured on bridge_chain
> (`research/lever-model-refit.md`, 2026-08-12, 150 fresh leaves, 5 presets):
> pass-rate falls with left-exponent-sum in every preset tested (slope
> −0.025 to −0.052 pass-rate-points/unit; significant net of preset,
> z=−4.48, n=150), and the chosen preset `e3_lowdeg` breaches the retune's
> own per-k flatness gate (±0.05) at the already-measured k∈{2,4,8} grid:
> per-k means 0.575/0.463/0.250, k2-vs-k8 z=3.07 |

If the owner wants the two axes split into separate table rows instead of one
row with two clauses (arguably cleaner, since they can fail independently and
the calibration report should say which one failed), the within-chain half
alone reads:

> | a2 | Per-node leaf pass-rate **flat in chain position** (equivalently,
> flat in left-exponent-sum for schemas where the two are linked by
> construction) | A family can pass the across-k gate (a) by having
> position-mixes that happen to be similar at the k values tested, while
> still handing a longer-k root systematically harder late nodes. Not
> implied by (a); check separately, and re-check at any k beyond what was
> directly measured (this axis has only been measured at position ≤ 8) |

---

## 5. What this refit does not establish

1. **The δ-confound mechanism (§2.4) is a hypothesis, not a closed
   measurement.** No experiment here holds `live_states` fixed while varying
   δ's declared support; the knob-mean drift cited is suggestive, not
   sufficient on its own to fully explain a 0.125-point gap.
2. **c₁'s "downstream of the congruence gate" status is now weakened, not
   settled** (§2.5) — its univariate marginal was only marginally
   significant to start with (z=1.66, n=100), so "shrinks to z=1.42 net of
   es_left" is a small, noisy movement, not a clean refutation or
   confirmation.
3. **No k=16/32 data exists.** §3.3's numbers are a linear extrapolation
   flagged as such; treat the k=16 "0.16" figure as "probably worse than
   this," not as a number to plan a corridor decision around.
4. **The pooled v2-only n=100 (§2.3) is still not a controlled experiment
   in the randomized sense** — the calibration 70 and the fresh 30 v2 rows
   were drawn under different seeds on different dates, and while both draw
   from the identical `DifficultyPreset("v2", …)` distribution (verified by
   knob-range membership), nothing here checks for any other date/seed
   drift (e.g. `random.Random` stream artifacts) beyond that.
5. **This refit used only the levers already staged as presets** (func, δ,
   es_left/start_exponents, offset, plus the two new checks c₁/d₁). It did
   not search for additional levers in the 150-row data beyond what
   `retune_candidates.jsonl`'s columns expose (e.g., no interaction terms
   beyond the two reported, no exploration of `c_right`/`d_right`/`o_right`
   as independent predictors of *this* step's pass rate).

---

## 6. Files touched / reused (read-only)

- `data/bank/retune_measure.jsonl` (150 fresh, read)
- `data/families/retune_candidates.jsonl` (150 knob rows, read)
- `data/bank/family_leaf_calibration.jsonl` (138 rows, 70 bridge_chain used, read)
- `scripts/stage_retune_candidates.py` — imported `_knobs_of` to parse
  calibration-file props back onto knobs (not modified)
- `src/rlmath/families/bridge_chain.py` — read for the `live_states`/preset
  mechanism cited in §2.4 (not modified)

No git-tracked file was edited besides this one.
