# bridge_chain growth laws — survey A: "keep the monomial, bound its growth"

C1 design agent, 2026-08-13. Brief: `research/retune-notes.md` §8.2. Probe:
`scripts/probes/probe_bc_growth_a.py` (owned here). Artifacts: `research/bc_growth_a/*.json` —
`lemmas/refute/witness/battery/adapt/collapse.json` from the Lean stages, `offline.json` from
`--offline`. Every number below names the function that produced it; re-run with

    uv run python scripts/probes/probe_bc_growth_a.py --offline
    uv run python scripts/probes/probe_bc_growth_a.py --lemmas --refute --witness --battery --adapt --collapse

(the second takes ~40 min on 3 REPL workers; `--offline` is a few minutes of CPU and no Lean).
Read-only on `src/rlmath/families/bridge_chain.py`; `preset "v2"`'s RNG stream is never entered.
All Lean numbers are from the local `ReplPool`, Mathlib @ lean v4.34.0-rc1, stock `PREAMBLE`
(`maxHeartbeats 400000` — see §10.7).

---

## 0. Verdict in one page

| # | claim | status |
|---|---|---|
| 1 | A **sawtooth in the exponent is impossible.** Each variable's exponent is non-decreasing along every true step, so degree can never be traded between variables nor given back. | **Kernel-checked** (2 of 3 refutation scripts closed, including the pure-trade case; the third is a tactic-script failure on the same statement class) |
| 2 | The schema has a **finite reservoir** `Φ = (C−c) + (C+D−c−d)`. Every step that leaves the monomial alone spends ≥1 unit of it; only a growth step refills it. This is the mechanism behind the R3 failure. | **Proved + exact DP**, DP verified against brute force on all 647 shipped live states |
| 3 | Therefore a law that **holds degree constant and coefficients ≤ 100 out to k=128 exists**: spend the reservoir instead of the exponent. Price: knob ranges **linear in k** (minimum budget 4 / 7 / 23 / **87** at k = 2/8/32/128 for the recommended gated form), not `3^k`. | **Built and measured** (`g3_k128`, `g4_deg4`, `g5_deg6`, `g6_tight`) |
| 4 | **The measured blocker `1 ≤ M` stops being k-dependent — and becomes the LEVEL DIAL.** `es_left` is *exactly* constant along the chain and across k (4.00 at every k for `g4_deg4`/`g6_tight`, 6.00 for `g5_deg6`), against the shipped 1.5 → 64.5. | **Measured offline**, 6 instances × 4 k per candidate |
| 5 | Leaves and goals **survive the full V0/V5 battery**; two planted controls die in the same pool. | **91 props over three passes, 91 survive; 2/2 planted controls killed in every pass** |
| 6 | Witnesses **kernel-check**. One new line (`1 ≤ √M`), no `nlinarith`, no `ring` — strictly cheaper than the shipped growth witness. | **203/203** over two passes, spanning the knob support at k = 2/8/32/128, plus two exhaustive k=32 instances |
| 7 | The flat leaf **had** a corridor-ceiling hole and it is now closed. At start degree 1, 2–3 of 6 one-hint routes close a flat leaf; the hole is exactly *slack* (`Δc+Δd+Δo ≥ 1` makes the leaf unconditionally true given `s²=M`). Adding a **tightness gate** `Δc+Δd+Δo = 0` takes it to **0 of 6**, at degree 4, at every k. | **Measured, mechanism identified, gate built** (§7.3) |
| 8 | **The goal is collapsible by a fixed k-independent 15-line proof — this is ALREADY true of the shipped rung, and no growth law in this term family can prevent it.** `e3_lowdeg`'s goal falls at k = 2/4/8/32. | **Kernel-checked + proved unavoidable** — outranks the flatness fix |

**Recommendation: `g6_tight` is the ladder rung** — the reservoir law, start degree 4, plus the
tightness gate. Measured at k = 2/8/32/128 on 6 instances per cell: **total degree exactly 5,
`es_left` exactly 4.00 (min = max = 4) at every k, total gain 3, max coefficient ≤ 100, 0 discards,
51/51 witnesses kernel-check, 19/19 leaves and goals survive the battery while both planted controls
die, and 0 of 6 adaptation routes close anything.** It is the flatness fix §8.2 asked for, it keeps
*both* budgets inside measured support, and it converts the strongest measured lever (`es_left`,
z = −4.48) from a confound into a calibration dial.

**But do not spend GPU on it until claim 8 is triaged**, because claim 8 says the k-axis is already
decorative at the GOAL level for the rung the retune selected. Claim 8 is not *caused* by bounding
growth; bounding growth merely stops a `3^32` gain from hiding it.

---

## 1. What the step actually requires (read from the code, not assumed)

A term is `c·M + d·√M + o`, `M = x^p y^q z^r`, side conditions `3 ≤ x,y,z`. This survey fixes
`funcs=("sqrt",)` — the `e3_lowdeg` lineage that R1/R2 selected — which matters because it makes
the two named-function atoms of a step **coincide** whenever the monomial does.

`bc._witness_proof` hands `linarith` four atoms and four facts, so a step is admissible iff a
linear program is feasible:

| step form | atoms | facts | feasibility |
|---|---|---|---|
| **growth** `M' = v^δ·M`, δ ≥ 1 | `M, M', √M, √M'` | `1 ≤ M`, `3^δ·M ≤ M'`, `√M ≤ M`, `0 ≤ √M'` | `c₂·3^δ − (c₁+d₁) ≥ (o₁−o₂)⁺` — i.e. **exactly `bc._valid`** |
| **flat** `M' = M` (new) | `M`, `s = √M` — ONE `s`, because the rendered text is identical on both sides | `1 ≤ s ≤ M` | `A ≥ 0`, `A+B ≥ 0`, `A+B+K ≥ 0`, where `A=Δc, B=Δd, K=Δo` |

The flat LP is the vertex/ray decomposition of `{1 ≤ s ≤ M}`: vertex `(1,1)` gives `A+B+K ≥ 0`;
ray `(M→∞, s fixed)` gives `A ≥ 0`; ray `(M→∞, s=M)` gives `A+B ≥ 0`.

So there are exactly **two unit-cost flat moves**, and they are the whole growth law:

```
m1 = (Δc, Δd, Δo) = ( 0, +1, −1)    spend one OFFSET unit, bank a d unit
m2 = (Δc, Δd, Δo) = (+1, −1, +t)    spend one COEFFICIENT unit, refill the offset, return a d unit
```

(`t ≥ 0` is free in the raw LP; the tightness gate below pins it to `t = 0`.)

Both satisfy the **NOT-a-knob** congruence gate (`m1` drops `o`, `m2` drops `d`), so no invariant is
relaxed: `funcs` stays a non-empty subset of `FUNCS`, `LOWER = 3` is untouched, and the growth step
plus its witness stay **byte-identical to the shipped ones** — deliberately, so the growth leaf's
measured difficulty carries over unchanged.

### The one new witness line

```lean
have hfl : (1:ℝ) ≤ Real.sqrt (x ^ 2 * y ^ 1 * z ^ 1) := by
  have h := Real.sqrt_le_sqrt hM
  simpa using h
```

Probed, not guessed (`bc_growth_a/lemmas.json`): `Real.sqrt_le_sqrt hM` + `simpa` works,
`Real.one_le_sqrt.mpr hM` works, `(Real.one_le_sqrt (by positivity)).mpr` does **not** (it is an
`Iff`, not a function, in this Mathlib). Also probed and **available**: the log→√ cross bound
`Real.log M ≤ 2·√M − 2`, via `Real.log_sqrt` + `Real.log_le_sub_one_of_pos` in two search-free
lines — that is the reserve flavour of §7.3.

Structurally the flat witness is the shipped growth witness **minus** `hbase`, `hpow`, `hstep`,
`hring` and the `rw` (the whole multiplicative block, including its `gcongr` and `ring`), **plus**
the three-line `1 ≤ √M`. So it is strictly cheaper to elaborate, which matters at large `k` —
FAMILIES.md's heartbeat wall is a V4 (compose) wall, and at k=128 essentially every leaf is flat.

### The tightness gate (found by measurement, §7.3 — it is not optional)

The flat LP admits **slack**: `A+B+K ≥ 1` is legal. It is also fatal. With slack the leaf
`A·M + B·s + K ≥ 0` is true *unconditionally over ℝ* once `s² = M` is supplied — e.g. `A=1, B=−1,
K=3` is `s² − s + 3 ≥ 0`, discriminant `1 − 12 < 0` — so a single
`nlinarith [Real.sq_sqrt …]` hint closes it **at any degree**, and `1 ≤ M` (the blocker the whole
level dial rests on) is never needed. Requiring

```
A + B + K = 0          (the tightness gate; with the LP's A+B+K ≥ 0 it is an equality)
```

makes the leaf tight at `(M,s) = (1,1)`, so every certificate must pass through `1 ≤ s` or
`1 ≤ M` — which is exactly the degree-sensitive obligation. Measured effect: 2–3 of 6 adaptation
routes close a slack flat leaf, **0 of 6** close a tight one.

The gate costs the offset refill (`m2` becomes `(+1,−1,0)`), so `σ = o − o_min` becomes a one-way
budget and the tight run length is `≈ 2·(o_max − o_min)`. Reaching k=128 therefore needs
`o_max ≈ 70` rather than 40 — offsets up to 70 in a prop, and nothing else changes.

---

## 2. Claim 1 — the sawtooth is impossible, and the proof is one limit

> **Lemma (no-shrink).** If `∀ x y z ≥ 3, c₁M + d₁F₁(M) + o₁ ≤ c₂M' + d₂F₂(M') + o₂` holds with
> `M = x^p y^q z^r` and `M' = x^{p'} y^{q'} z^{r'}`, then `p' ≥ p`, `q' ≥ q`, `r' ≥ r`.
>
> *Proof.* Fix `y = z = 3`, let `x → ∞`. `√` and `log` are `o(M)`, so the sides are asymptotic to
> `c₁3^{q+r}x^p` and `c₂3^{q'+r'}x^{p'}`; if `p > p'` the ratio diverges. ∎

Consequences — and they are what kills the brief's first direction:

* **no trading** — you cannot lower `x`'s exponent while raising `y`'s, at constant total degree or
  otherwise. A sawtooth/bounded-window *in the exponent* does not exist for this term family.
* **no giving back** — total degree is non-decreasing, so a bounded degree band forces `M' = M` on
  all but finitely many steps. The flat step is therefore the only door, which is why the rest of
  this survey is about it.

Kernel-checked refutations (`bc_growth_a/refute.json`), each instantiating the negation at
`x = 100, y = z = 3` and finishing with `Real.sqrt_le_self_iff` + `norm_num`:

| case | step | refuted |
|---|---|---|
| `drop_degree` | `2x² + √ + 1 ≤ 9x + 9√ + 9` (total degree 2 → 1) | **yes** |
| `trade_big_offset` | `2x³yz + … ≤ 9xy³z + 9√ + 99` (degree 5 → 5, exponents traded, offset maximally favourable) | **yes** |
| `trade_x_for_y` | `2x²yz + … ≤ 9xy²z + 9√ + 9` (degree 4 → 4) | script did not close (`unsolved goals`, probably `norm_num` normalising `√90000` in one hypothesis but not another) |

The middle row **is** the sawtooth: a pure exponent trade with the offset stacked in the sawtooth's
favour, false in the kernel. Read the third row as a probe defect, not as evidence.

---

## 3. Claim 2 — the reservoir, and why the shipped law had to grow the degree

> **Theorem (flat-run bound).** On a flat step the congruence gate forces one of `(c,d,o)` strictly
> down and the LP forces `A ≥ 0`, `A+B ≥ 0`. Then `Δo < 0 ⇒ A+B ≥ 1` (so `c+d` strictly rises);
> `Δd < 0 ⇒ A ≥ 1` (so `c` strictly rises); `Δc < 0` is impossible. Hence every flat step strictly
> decreases `Φ = (C−c) + (C+D−c−d) ≥ 0`, and a flat run is at most `Φ` steps long. ∎

The exact longest run is a DP in reduced coordinates `(γ, μ, σ) = (C−c, d−d_min, o−o_min)` with
`λ+μ = D−d_min` invariant. **Verified against brute-force longest-path over the full move algebra
on all 647 live states of the shipped ranges** (`selftest`: `run_dp_matches_brute_force: true`,
`live_matches_shipped_fixpoint: true`, `flat_moves_exhaustive: true`,
`growth_moves_exhaustive: true`). `Φ` alone over-estimates by up to 20 at the `(d_min, o_min)`
boundary, where **no flat move exists at all** — hence the DP rather than the bound.

| knob ranges (c / d / o) | live states | longest flat run | mean over states | max k reached |
|---|---|---|---|---|
| shipped `e3_lowdeg` 2–9 / 1–9 / 1–9 | 647 | 22 | 10.7 | **19** |
| `g2_wide` 2–20 / 1–24 / 1–20 | 9,119 | 59 | 29.2 | **56** |
| `g3_k128`/`g4`/`g5` 2–100 / 1–100 / 1–40 | 395,999 | 295 | 147.0 | **292** |
| **`g6_tight`** 2–100 / 1–100 / 1–70, tight | 692,999 | 167 | 76.2 | **133** |

(The tight run is shorter at the same coefficient budget because `m2` can no longer refill the
offset, so `o − o_min` becomes a one-way budget and the run is `≈ 2·(o_max − o_min)`.)

**This is the mechanism behind R3.** With no flat step available, the generator must grow the
monomial every step, so `deg = deg₀ + Σδ` grows linearly in `k` *by construction* — retune §8's
"max es == k exactly for `e3_lowdeg`" is this theorem's contrapositive. The fix is not to change
what carries the growth; it is to **stop taking a growth step you do not need.**

---

## 4. Claim 3 — the trade-off law, in numbers

Two derived necessary conditions bound a bounded-degree chain's length, both from the closing step,
which is where the shipped endpoint gate bites:

1. `c_k ≥ ⌈(c+d)/3^δ⌉` at the closing growth step, and `c+d` never *decreases* on a flat step, so
   the endpoint gate's `c_k < c₀` forces **`d₀ < 2·c₀`**.
2. The offset can only be dumped by paying `c+d` (`Δo ≥ −(Δc+Δd)` on every flat step) and
   `#m2 ≤ (d₀−d_min) + #m1`, which caps how much of the run can be spent on `m1`.

`report_frontier` solves for the smallest **coefficient budget** `M` — the largest knob-range
endpoint, i.e. the largest numeral that can appear in a prop — that admits a k-step chain:

| k | min budget `M`, slack flat steps | min budget `M`, **tight** flat steps (the rung) | §8's multiplier `3^k` |
|---|---|---|---|
| 2 | **4** — start (4,1,4) | **4** — start (4,1,4) | 9 |
| 8 | **6** — start (5,1,6) | **7** — start (5,1,7) | 6,561 |
| 32 | **14** — start (5,1,7) | **23** — start (13,1,23) | 1.9 × 10¹⁵ |
| 128 | **46** — start (5,1,7) | **87** — start (45,1,87) | 1.2 × 10⁶¹ |

With the anti-collapse gate of §6 switched on the same search returns **nothing at any budget, for
k=2 and k=8, in both forms** (`offline.json → frontier_anticollapse_gate_on`) — the empty-acceptance
result, computed rather than argued.

**The trade-off law: the budget is LINEAR in k — ≈ 0.36·k with slack flat steps, ≈ 0.68·k with the
tightness gate — where the §8 proposal is exponential.** 87 sits inside the range over which coefficient magnitude has been *measured* difficulty-neutral
(1–2,200, F1); `3^128` is fifty-eight orders outside it. That is the whole argument for this family
of laws over §8's, and it is the answer to §8.2's "(a) keep the multiplier inside a defensible
range — which means a growth law that is not exponential in k".

### Measured instances (6 per cell: seeds 4501/4502/4503 × 2 idx)

`s0_shipped` is `e3_lowdeg`'s law (growth every step) rebuilt inside this probe, so the columns are
commensurable. `max knob` is the largest coefficient/offset — computed from the knobs, never from
the prop text (exponents would contaminate a regex).

| candidate | quantity | k=2 | k=8 | k=32 | k=128 |
|---|---|---|---|---|---|
| **g6_tight** (recommended) | max total degree | **5** | **5** | **5** | **5** |
| | leaf `es_left` mean (min–max) | **4.00** (4–4) | **4.00** (4–4) | **4.00** (4–4) | **4.00** (4–4) |
| | max knob (largest numeral in a prop) | 97 | 91 | 100 | 100 |
| | total gain `M_k/M₀` | **3** | **3** | **3** | **3** |
| | flat-leaf share | 0.50 | 0.875 | 0.969 | 0.992 |
| | growth steps | 1 | 1 | 1 | 1 |
| | discards to pass the gates (mean) | 0.0 | 0.0 | 0.0 | 0.0 |
| | one-step collapse slack (crude) | 2 | 2 | 2 | 2 |
| | mean leaf `c` / `d` | 55.7 / 24.1 | 52.2 / 22.2 | 85.9 / 48.9 | 69.1 / 1.5 |
| **g4_deg4** (no tightness gate) | max degree; `es_left` mean | 5; 4.00 | 5; 4.00 | 5; 4.00 | 6; 4.01 |
| **g5_deg6** | max degree; `es_left` mean | 7; 6.00 | 7; 6.00 | 7; 6.00 | 8; 6.01 |
| **g3_k128** (start degree 1) | max degree; `es_left` mean | 2; 1.00 | 3; 1.02 | 3; 1.01 | 3; 1.01 |
| **s0_shipped** = `e3_lowdeg` | max total degree | 3 | 9 | 33 | **129** |
| | leaf `es_left` mean (min–max) | 1.5 (1–2) | 4.5 (1–8) | 16.5 (1–32) | **64.5 (1–128)** |
| | max knob | 9 | 9 | 9 | 9 |
| | total gain | 9 | 6,561 | 1.9 × 10¹⁵ | **1.2 × 10⁶¹** |

`g1_reservoir` (shipped ranges + flat steps) covers **k ≤ 19** and `g2_wide` **k ≤ 56**, both at
degree 2–3, so the rung ladder is `g1 → g2 → g3/g4/g5` by knob budget, each buying more `k` at the
same degree.

### Claim 4 — what this does to the measured flatness driver, and the level dial

The R3′ covariate for this family is `es_left`, slope **−0.0353/unit (SE 0.0079, z = −4.48)**.
Projected per-k mean shift from k=2 to k=128, everything else held:

| law | Δ mean `es_left` | projected Δ pass@8 |
|---|---|---|
| shipped `e3_lowdeg` | **+63.0** | −2.22 (floors at 0 before k=32; §5 puts the corridor exit at k≈20) |
| `g3_k128` | +0.01 | −0.0004 |
| **`g4_deg4` / `g5_deg6`** | **+0.01** | **−0.0004** |

And the part that is more than a fix: **once growth is off the exponent, `start_exponents` is a
difficulty knob that is flat in k by construction.** `es_left` is *exactly* `sum(start_exponents)`
at every position of every chain at every k. The measured es→pass table (retune §8: es=1 → 0.475,
2 → 0.463, 3 → 0.414, 4 → 0.287, 5 → 0.188, 6–8 → 0.147) is then a **calibration curve for the
level**, not a description of a confound:

| rung | `es_left` (all k) | measured es→pass anchor |
|---|---|---|
| `g3_k128` | 1 | 0.475 — above the corridor's 0.45 target, likely too easy |
| **`g4_deg4` / `g6_tight`** | **4** | **0.287** |
| `g5_deg6` | 6 | 0.147 — likely below the floor |

This is the first time in this family that the corridor level and flatness can be set
*independently*. It is also, per §7.3, the lever that answers the flat leaf's ceiling risk.

### The residual: the gradient moves into the coefficient

Honest accounting — the mean leaf `c` still varies with k: `g4_deg4` 59.1 / 66.3 / 81.5 / 87.8 and
`g6_tight` 55.7 / 52.2 / 85.9 / 69.1 at k = 2/8/32/128 (range ≈ 20–100). A longer walk spends more
of the reservoir, and which part of the range it occupies depends on where the admissible start
sits. The k-axis
still carries *a* gradient; it is now in a variable that

* is bounded by 100 at every k — `log10 max|coef|` spread across the whole k-grid ≈ **0.07
  decades**, against case_tree `v2`'s 2.05 and the excluded `H2_quartic`'s 4.7 — and
* was measured neutral over 1–2,200 in the sibling family (F1): inside support, not nine orders
  past it.

The `g3_paced` ablation spends the reservoir at `Φ₀/k` per step, which flattens the coefficient
*marginal* (82 / 84 / 92 / 92) at the cost of degree 4 and gain 27, and makes leaf *tightness*
k-dependent instead (at k=2 each step jumps `c` by ~30, so the leaf is loose; at k=128 every step
is `Δc=1`, so it is tight). **Registered preference: ship the unpaced law** — keeping the per-leaf
`linarith` certificate literally identical at every k is worth more than flattening the magnitude
of `c`, because the certificate is what the prover must find. R3′ on `log10 max|coef|` is the
measurement that settles it.

---

## 5. Direction 4 — how far the SHIPPED law reaches ("bound k instead")

Using the measured slope and `e3_lowdeg`'s measured k=2 level (0.575), with mean
`es_left = k/2 + 0.5`:

| k | mean es | projected mean | ±1 SE band |
|---|---|---|---|
| 8 | 4.5 | 0.469 | 0.445 – 0.493 |
| 16 | 8.5 | 0.328 | 0.273 – 0.383 |
| **20** | 10.5 | **0.257** | 0.186 – 0.328 |
| 24 | 12.5 | 0.187 | 0.100 – 0.274 |
| 32 | 16.5 | 0.045 | −0.073 – 0.164 |

**The shipped size axis is constructible only up to k ≈ 20** (k ≈ 16 on the pessimistic slope).
That is a legitimate DIRECTION §5.5 finding on its own and it is *independent* of the candidates —
it is the shipped law's own arithmetic. It lands below the k=32 rung the experiment's grid wants,
and just above k=16.

---

## 6. Claim 8 — the goal collapses, it already did, and no law here can fix it

This is the survey's most important result and it was not in the brief.

`endpoints_resist_naive_collapse`'s docstring argues that a flat prover "must instead establish a
quantitative ratio `M_k ≥ r·M₀` with `r ≥ c₀/c_k > 1`, which is exactly the multiplicative content
the chain carries and **which `gcongr` cannot produce**". The first half is right; the second is
load-bearing and false — the *generator's own witness* produces such a ratio in four lines, and the
multi-variable generalisation is one `gcongr <;> linarith`:

```lean
have hbase : (3:ℝ) ^ 0 * 3 ^ 0 * 3 ^ 1 ≤ x ^ 0 * y ^ 0 * z ^ 1 := by gcongr <;> linarith
have hpow  : (3:ℝ) ≤ x ^ 0 * y ^ 0 * z ^ 1 := by linarith [hbase]
have hstep : (3:ℝ) * (x^1*y^0*z^0) ≤ (x^0*y^0*z^1) * (x^1*y^0*z^0) :=
  mul_le_mul_of_nonneg_right hpow (by positivity)
have hring : (x^0*y^0*z^1) * (x^1*y^0*z^0) = x^1*y^0*z^1 := by ring
rw [hring] at hstep
linarith [hM, hfu, hfl, hstep]
```

**Measured (`bc_growth_a/collapse.json`), on goals from the SHIPPED generator:**

| preset / candidate | k=2 | k=4 | k=8 | k=32 | k=128 |
|---|---|---|---|---|---|
| **`e3_lowdeg`** (the rung R1/R2 selected) | **closed** | **closed** | **closed** | **closed** | — |
| `v2` | no | closed | no | no | — |
| `g1_reservoir` / `g2_wide` / `g3_k128` | — | — | closed | closed | closed |
| `s0_shipped` | — | — | closed | closed | closed |

So the k=32 `e3_lowdeg` goal — 32 hidden intermediates, the artifact the transfer plot integrates
over — is closed by a proof whose length **does not depend on k**. V0 does not catch this because
V0 is the single-tactic battery, and the goals do survive that (§7.2). What it hits is DIRECTION
§5.4(b)/(d): the flat arm does not need the decomposition.

> **Theorem (collapse is unavoidable).** For a chain whose closing step is a growth step,
> `3^δ·c_k ≥ c_end + d_end + (o_end − o_k)⁺` and `c_end + d_end = c₀ + d₀ + Δ` where
> `Δ = Σ(Δc+Δd) ≥` total offset drop (because `Δo ≥ −(Δc+Δd)` on every flat step). Substituting
> into the crude one-step slack `c_k·3^δ − (c₀+d₀) − (o₀−o_k)⁺`, the `o` terms cancel and the slack
> is `≥ Δ − (o₀ − o_end) ≥ 0`. The route therefore always closes — for every knob range, every k,
> and every growth law in this term family. ∎

Numerically confirmed over ~2,000 random chains of all eight candidates at k = 2/8/32: minimum crude
slack **0**, never negative in any chain (`offline.json → collapse_bound`). For `s0_shipped` the slack is 49 / 39,354 /
1.5×10¹⁶ — the shipped law is not marginal, it is enormously collapsible, and the margin *grows*
with k.

Consequence for this survey: I designed an **anti-collapse gate**
(`c_k·3^Σδ + 3·d_k + o_k < c₀+d₀+o₀`) as a fourth gate, then proved and measured its acceptance set
to be **empty** — `report_frontier(anticollapse=True)` finds no admissible chain at any budget for
any k. It stays in the probe (`Cand.anticollapse`) precisely because its emptiness is the result.
Candidates are therefore gated on the shipped endpoint gate only, with the collapse slack
**reported**, never assumed away.

**A fix is outside this survey's family.** The collapse survives because the crude relaxations
(`√M ≤ M`, `1 ≤ M`) are *scale-free*: applying them once at the endpoints is never weaker than
applying them k times. Escapes to hand to C2 / the orchestrator: mixed `log`-left/`√`-right
endpoints (the cross bound `log M ≤ 2√M − 2` **is** available in two search-free lines — probed);
a carrier that is not a bare monomial, so no `gcongr` ratio exists; or FAMILIES.md direction 1
(bank leaves), which replaces the term algebra entirely.

---

## 7. Local gate results

### 7.1 Witness kernel checks — 203/203

`bc_growth_a/witness.json`. Leaves chosen to span the knob support (extremes of Δc/Δd/Δo and of
`es_left`) at every reachable k, plus one **exhaustive** instance.

| candidate | total | flat | growth | k=2 | k=8 | k=32 | k=128 |
|---|---|---|---|---|---|---|---|
| g1_reservoir | 25/25 | 13/13 | 12/12 | 12/12 | 13/13 | n/a (k>19) | n/a |
| g2_wide | 39/39 | 20/20 | 19/19 | 12/12 | 13/13 | 14/14 | n/a (k>56) |
| g3_k128 | 56/56 | 29/29 | 27/27 | 12/12 | 15/15 | 15/15 | **14/14** |
| s0_shipped (control) | 32/32 | — | 32/32 | 8/8 | 8/8 | 8/8 | 8/8 |
| **g6_tight** | **51/51** | 27/27 | 24/24 | 12/12 | 13/13 | 13/13 | **13/13** |
| g3_k128 and g6_tight, **every leaf** of one k=32 instance each | 32/32, 32/32 | | | | | | |

Zero failures. The flat witness is search-free, so this was expected — but it was checked, not
argued.

### 7.2 Automation battery (V0/V5) — 91 survive, 2 planted controls die in every pass

`bc_growth_a/battery.json`. Full battery: 10 tactics × {bare, intros-first} = 20 proof attempts per
prop, 25 s each; ANY success kills.

| pool | props | survive |
|---|---|---|
| **planted control** `2M+1√M+1 ≤ 9M+9√M+9` (all coefficients rise, same function) | 1 | **0 — killed by `intros; gcongr <;> linarith`** |
| **planted control** a flat step with the congruence gate switched OFF (`4M+2√M+3 ≤ 5M+3√M+7`) | 1 | **0 — killed by `intros; gcongr <;> linarith`** |
| flat leaves, distinct props spanning the knob support (pass 1: g1/g2/g3; pass 2: g4/g5; pass 3: **g6_tight**) | 15 + 10 + 5 | all |
| growth leaves (same three passes) | 15 + 10 + 5 | all |
| flat leaves drawn specifically from **k=128** instances (degree 5–8 monomials) | 6 + 6 | all |
| goals (g1 k=8; g3 k=8/32/128; g4/g5 k=8/32/128; **g6_tight k=8/32/128**) | 4 + 6 + 3 | all |

The second control is the one that matters for the new step form: it is a *flat* step differing
from an admissible one **only** in that no coefficient drops, and it dies in ~1 s. So the
congruence gate is doing real work on the new leaf type, and the gate **can** kill — the failure
mode FAMILIES.md says has shipped twice is not present here.

(Probe defect to note when reading the raw file: the six k=128 leaves in the third pass are tagged
`g3_k128/flat/k128/...` but were drawn from `g6_tight` — the tag string was not updated with the
candidate. Their offsets, up to 66, identify them: only `g6_tight` has `o_max = 70`.)

### 7.3 Corridor-ceiling proxy (adaptation ladder) — the hole, its mechanism, and its gate

The battery is the corridor's *floor*. The sibling family's idiom probe (case-tree-hardening §5) is
the ceiling instrument; its transplant here is six one-hint routes run against 3 flat and 3 growth
leaves per candidate (`bc_growth_a/adapt.json`). Read it as a **route detector, not a difficulty
meter**.

| candidate | start degree | tightness gate | flat leaves: routes closed of 6 | growth leaves |
|---|---|---|---|---|
| g1_reservoir | 1 | no | **3, 3, 2** | 0, 0, 0 |
| g3_k128 | 1 | no | **2, 2, 2** | 0, 0, 0 |
| g4_deg4 | 4 | no | **0, 0, 2** | 0, 0, 0 |
| g5_deg6 | 6 | no | **2, 2, 2** | 0, 0, 0 |
| **g6_tight** | **4** | **yes** | **0, 0, 0** | **0, 0, 0** |

The closing route is always `nlinarith [Real.sq_sqrt …, Real.sqrt_nonneg …]` (twice, counting the
four-hint combination). **Registered prediction 5 said `g4_deg4` closes ≤1 of 6 and `g5_deg6`
closes 0 of 6; `g4` came in at 0/0/2 and `g5` at 2/2/2 — so the prediction was half wrong, and
being wrong is what located the real mechanism**: raising the degree does not help, because with
`s² = M` in hand the route never needs `1 ≤ M` at all when the step carries slack. The three `g5`
leaves that fell have `Δo = +2, +2, +3`; the two `g4` leaves that resisted have `Δc+Δd+Δo = 0`. That
is the tightness gate of §1, and with it the ladder reads 0/6 everywhere.

So the corridor-ceiling risk that the start-degree dial was supposed to address was in fact a
*slack* problem, and the degree dial remains available for the level — now on a leaf whose
certificate genuinely goes through `1 ≤ M`. The reserve if `g6_tight` still lands above 0.9 on GPU
is the `log`-left/`√`-right flat flavour, whose cross bound already checks (§1).

## 8. What a new preset would need (design only — implementation is not owned here)

All additive, all drawn after the existing knobs so `v2`'s stream is untouched:

1. `DifficultyPreset`: `flat_steps: bool = False`, `final_growth: bool = False`, `thrift: int = 1`,
   `pace: bool = False`, **`tight: bool = False`**. `deltas` keeps its `≥ 1` assertion — a flat step
   is a **new step kind**, not `δ=0` — and `step_kinds` should record `("flat", -1, 0)` so the
   datasheet can count leaf types.
2. `_valid_flat(prev, new) := A ≥ 0 ∧ A+B ≥ 0 ∧ A+B+K ≥ 0`, plus **`A+B+K = 0` when `tight`**
   (§1 — this is a gate, not a knob: without it one `Real.sq_sqrt` hint closes the leaf at any
   degree). The congruence gate applies unchanged to both step kinds.
3. `_flat_witness_proof` — the shipped `1 ≤ M` scaffold, `Real.sqrt_le_self_iff`, the new `1 ≤ √M`
   line, `linarith`. No `ring`, no `gcongr`, no `nlinarith`; the multiplicative block is simply
   absent, so V4's cost per leaf goes *down*.
4. `_sample_chain`: flat-first with forced growth on reservoir exhaustion; **thrifty** successor
   choice (uniform over all flat successors realises ~40% of the DP-optimal run and forces extra
   growth steps); the closing step is `best_close`, the argmin of the endpoint-gate quantities; the
   start state is drawn from `admissible_starts(preset, k)` (a cached pure function).
5. `check_preset_invariants`: `exponent_sums` must become **non-decreasing** rather than strictly
   increasing (§10.1), plus a new check that no two leaf props in one problem are identical — with
   a constant monomial, distinct exponent sums no longer supply that for free. (The flat-run
   monovariant does supply it, since a state cannot repeat inside a run, but it should be checked
   rather than inherited.)
6. Datasheet: leaf-type mix per k, `max_knob` per k, `es_left` per k. `flat_share` rising
   0.50 → 0.99 with k is a real property of the law and consumers must see it.
7. Recommended rung values (`g6_tight`): `coef_range=(2,100)`, `fcoef_range=(1,100)`,
   `offset_range=(1,70)`, `deltas=(1,)`, `funcs=("sqrt",)`, `start_exponents=(2,1,1)`,
   `flat_steps=True`, `final_growth=True`, `tight=True`, `thrift=1`, `pace=False`. Reach: k ≤ 133
   (tight run ≈ 2·(o_max − o_min)); to go further, widen `offset_range`, not the exponent.

Determinism is preserved: everything is a pure function of `(k, seed, idx, preset)` — the probe's
`build()` is exactly that.

---

## 9. Ranking

| candidate | flatness (R3′ proxy) | corridor level | adaptation ladder | max numeral | max degree | reach | verdict |
|---|---|---|---|---|---|---|---|
| **`g6_tight`** | **Δ`es_left` = 0.00 over k=2→128** | anchored at es=4 → **0.287** measured | **0 of 6** | 100 | 5 | k ≤ 133 | **ladder rung** |
| `g4_deg4` | Δ 0.01 | same anchor | 0/0/2 of 6 | 100 | 6 | k ≤ ~292 | rung only with the tightness gate (= `g6_tight`) |
| `g5_deg6` | Δ 0.01 | es=6 → 0.147, probably below the floor | 2/2/2 of 6 | 100 | 8 | k ≤ ~292 | needs the gate; harder reserve |
| `g3_k128` | Δ 0.01 | es=1 → 0.475, above target | 2/2/2 of 6 | 100 | 3 | k ≤ ~292 | needs-more-work (level + slack) |
| `g2_wide` | Δ 0.03 (k≤32) | as `g3` | not run | 24 | 3 | k ≤ 56 | cheapest numerals for a k≤32 grid |
| `g1_reservoir` | Δ 0.00 (k≤8) | as `g3` | 3/3/2 of 6 | **9 (shipped ranges)** | 2 | **k ≤ 19** | best *control-adjacent* rung: same knob ranges as `e3_lowdeg`, so a difference isolates the step kind |
| `g3_paced` | Δ 0.2 | worse: tightness becomes k-dependent | not run | 100 | 4 | k ≤ ~292 | ablation only |
| sawtooth in the exponent | — | — | — | — | — | — | **refuted (kernel)** |
| §8's `3^i` multiplier | Δ 0 | unmeasurable: 10¹⁵ is nine orders past support | — | 1.9×10¹⁵ | 1 | any | **reject** (as §8.2 said) |
| `s0_shipped` = `e3_lowdeg` | **Δ 63** | measured 0.575 → 0.250 over k=2→8 | 0 of 6 | 9 | 129 | k ≤ 20 | the thing being replaced |

Staging order — one lever per rung, in the retune §3 sense:

1. **`g1_reservoir`** — shipped knob ranges, start degree 1, no tightness gate. A difference against
   `e3_lowdeg` isolates *the step kind* with nothing else moved. Covers k ≤ 19, which is where §5
   says the shipped axis dies anyway.
2. **`g6_tight`** — adds the degree dial and the tightness gate. Covers the whole k-grid.
3. `g2_wide` / `g3_k128` — isolate the knob budget, if the budget turns out to matter.

## 10. Contract friction (reported, not worked around — none of these files are owned here)

1. **`check_preset_invariants` hard-codes `exponent sums are not strictly increasing` as a
   violation.** Every bounded-growth law makes that sequence non-decreasing, so the invariant
   checker rejects the fix for the failure it was written alongside. It must relax to
   non-decreasing, and the property it was really buying (no intermediate collides with an
   endpoint) needs its own explicit check.
2. **`endpoints_resist_naive_collapse`'s docstring claim is false as stated** ("which `gcongr`
   cannot produce"). `gcongr` produces `3^Δ ≤ v^Δ` in one line; `mul_le_mul_of_nonneg_right` and
   `ring` finish the ratio. The gate still defeats the five routes it was measured against, but its
   stated *reason* is wrong, and §6 shows the route it misses closes the shipped k=32 goal.
3. **V0 as written cannot see §6.** The battery is single tactics; the collapse route is 15 lines.
   FAMILIES.md's V0 row says "else the flat arm wins by tactic dispatch" — here the flat arm wins by
   a *fixed idiom*, the same threat one level up. A known-route check (a small registry of
   generator-derived flat routes, run like the battery) belongs in `validate.py` beside V0.
   case_tree has this instrument (its idiom probe); bridge_chain has none.
4. **DIRECTION §5.4(a) still has no operational form for the chain aggregate.** retune §8's "two
   flatness axes" draft sits in `lever-model-refit.md` §4 and has not landed in DIRECTION. This
   survey reports against R3′ (`es_left` regression) because that is the only form measurable at
   any plausible n.
5. **`gen_families.py` cannot select a preset** (retune §8 friction 4), so nothing here can be
   materialised into a dataset without that one-flag change.
6. **The corridor level for the flat leaf is unmeasured and it is 98% of leaves at k=128.** No local
   instrument settles it; §7.3 is a proxy. Whatever GPU stages this law must measure the flat leaf's
   pass@8 **first**, ~30 leaves at one k, before paying for a k-grid: the level is the risk, not the
   flatness.
7. **The `maxHeartbeats` coupling (FAMILIES.md) applies to everything here.** All §7 verdicts are at
   `maxHeartbeats 400000`. Since the flat witness is cheaper than the growth witness, this law
   *relaxes* the V4 wall — but any budget change retroactively invalidates §7.2/§7.3 and both must
   be re-run with the planted controls attached.

---

## 11. Registered predictions (written before any GPU measurement)

1. **Without** the tightness gate, the flat leaf's pass@8 lands **above** the growth leaf's and
   plausibly above the corridor's 0.9 ceiling — §7.3's ladder already shows it locally (2–3 of 6
   one-hint routes close it). This is the reason `g3_k128`/`g4_deg4` are not the recommendation.
   **With** the gate the ordering is prediction 6. If `g6_tight` still lands above 0.9, the reserve
   is the `log`-left/`√`-right flat flavour, whose cross bound already checks (§1).
2. `g1_reservoir` vs `e3_lowdeg` at k=8 differ by **more than 0.10** in mean pass@8, `g1` easier.
   If they are indistinguishable, the step kind is inert and the reservoir buys flatness for free —
   the best possible outcome, and it should be reported as such.
3. Coefficient magnitude over 2–100 moves pass@8 by **less than 0.05** (F1's neutrality extends
   over this range). This is R3′ on `log10 max|coef|`; it is cheap, and it is the one axis this
   survey trades *into*.
4. Per-k means for any of these rungs will sit inside the 2σ detection floor of each other at any n
   this project can afford (0.22–0.27 at 10 leaves/k, retune §8.1), so **R3 will read UNRESOLVED,
   not PASS**, and R3′ on `es_left` is the only gate that can actually pass. Stated in advance so an
   UNRESOLVED is not read as a failure.
5. ~~`g4_deg4` closes ≤ 1 of 6 adaptation routes and `g5_deg6` 0 of 6.~~ **Registered and then
   measured in the same session: half wrong** (`g4` 0/0/2, `g5` 2/2/2). The failure is what found
   the slack mechanism and the tightness gate — recorded here rather than quietly edited, per §4
   evidence discipline.
6. With the tightness gate on, the flat leaf's pass@8 lands **below** the growth leaf's at the same
   start degree, because it must establish `1 ≤ M` *and* `1 ≤ √M` where the growth leaf establishes
   `1 ≤ M` and a ratio. If instead they measure equal, the flat/growth leaf-type mixture is
   unimodal and the corridor's band-fit clause is safe at every k — which is the outcome to hope
   for, since `flat_share` runs 0.50 → 0.99 across the grid.
