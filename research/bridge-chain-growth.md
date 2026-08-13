# bridge_chain growth-law ladder — staged rungs for the flatness fix

Phase 1 is open on bridge_chain for one measured reason (`research/retune-notes.md` §8): the
selected rung `e3_lowdeg` passes R1 (mean 0.429 against 0.404 projected) and R2 (band-fit 0.83,
zero-rate 0.07) and **fails R3**, the flatness gate, with per-k means **0.575 / 0.463 / 0.250** at
k = 2/4/8 — spread 0.325, 6.5× the ±0.05 tolerance, and all five presets fail the same way in the
same direction. The mechanism is structural, not statistical: leaf difficulty falls with left
exponent sum (**−0.0353/unit, SE 0.0079, z = −4.48**, n = 150) and exponent sum grows +δ per chain
position *by construction*, because `M' ≥ 3^δ M` with `M` a bare monomial can only be satisfied by
raising a degree.

This file is the bridge_chain analogue of `research/case-tree-hardening.md` — same sections, same
discipline. It stages the schema fix that §8 asked for and §8.2 then refused in its first proposed
form. Sources carried forward, cited and not re-run:

* `research/bc-growth-survey-a.md` (**C1**) — the growth-law survey: the reservoir theorem, the
  no-shrink lemma, the tightness gate, and all local gate results. C1 owns
  `scripts/probes/probe_bc_growth_a.py` and `research/bc_growth_a/*.json`.
* `research/retune-notes.md` §8 / §8.1 / §8.2 — the R3 verdict, R3's unattainable PASS state, and
  the refutation of the `3^i` multiplier fix.
* `research/case-tree-hardening.md` §12 — **the sibling ladder's MEASURED result, 2026-08-13.**
  It landed after C1's brief was written and it changes two things in this design: it makes
  coefficient magnitude a *measured*-neutral axis over four decades, and it resets the projection
  track record from MAE 0.044 to **MAE 0.253 with every error negative**.
* `research/lever-model-refit.md` (F2) — how a projection of this kind scores out of sample.
* `FAMILIES.md` (V0–V6, the corridor's three conjunctive clauses, leaf-disjointness, the
  `maxHeartbeats` coupling) and `DIRECTION.md` §5.4 (a), (b′), (d), (e) and §5.5.

**Nothing here measures pass@8.** Every number below is one of: a *battery floor* (measured locally
by C1, definitive), a *self-certification* (witness kernel check, definitive), a *kernel refutation*
(definitive), a *free structural computation* (exact, run off the generator or the probe), a
*ceiling proxy* (C1's adaptation ladder — indicative, and it is a route detector, not a difficulty
meter), or an *arithmetic projection* (§5, registered).

Owned file: this one. `src/rlmath/families/bridge_chain.py`, every test, and every other family's
files are **not** edited here; §9 is the order in which a later agent implements §3.

**Two new measurements were made while writing this file**, because neither is a re-run of C1 —
one is a correction to it and one is a cell it did not build. Both changed the document:

* **§2.5** — the goal collapses for **every** shipped preset at every k, for every function pair
  (60/60, kernel-checked). C1 reported this for one preset and read the others as resistant; that
  reading was a probe artifact. This outranks everything else in the file.
* **§4.1** — the tightness gate is **not sufficient** at a low start degree, and the boundary is
  exactly `es = 3`. This **changed the recommended rung** from C1's `g6_tight` (es=4, level anchor
  0.287) to `g7_mid` (es=3, anchor 0.414, one degree lower), and turned the start degree from a free
  dial into a gate with a measured floor (F13).

---

## 0. What to run (TL;DR)

**Four steps, in this order. The first two are local and cost $0, and step (0b) can stop the
project spending anything at all.**

### (0a) Implement `g7_mid` and its ladder — local, $0, and worth doing whatever (0b) decides

§3's rungs behind additive preset flags in `bridge_chain.py` (§9 step 1), then re-run the local
gate *through the shipped generator*: battery + witness + planted control + full `validate_problem`
(V0–V6) at k ∈ {2, 8, 32}. C1 gated hand-built probe instances; nothing has been gated through the
code that will materialise a dataset, and **V3/V4 have never been run for any bounded-growth
candidate.** This is the fix the measured R3 failure asks for, it is free, and it is what makes
every other bridge_chain number interpretable.

### (0b) TRIAGE §2.5 — the goal collapse — before any GPU decision

§2.5 reports a kernel-checked, **60/60** result: the goal of every shipped bridge_chain preset, at
k = 2/4/8/32, for every function pair including `log|log`, is closed by a fixed 15-line proof built
from the generator's own witness idiom applied to the *endpoints*. C1 proved the route unavoidable
for this term family and measured the acceptance set of an anti-collapse gate to be **empty**. This
is a DIRECTION §5.4(b)/(d) defect at the *goal* level — the object the transfer plot integrates
over — and it is independent of flatness. **It needs a decision from whoever owns DIRECTION, not a
patch from this file.** If the decision is "bridge_chain's k-axis must resist a fixed flat idiom",
the family needs a carrier outside this term algebra or `FAMILIES.md` direction 1 (bank-drawn
leaves), and the pod below should not be bought.

### (0c) Stage the candidates — local, $0

Cell sizes differ per rung, so this is one invocation per cell, all appending into one
`build_bank`-ingestable file. **`--out-name` and `--append` do not exist in
`stage_retune_candidates.py` today** — they, and the two selectors below, are the one-flag
extensions §10 (6) itemises; today's CLI writes a fixed `retune_candidates.jsonl` per run and
would overwrite.

```bash
# cell A — the flatness gate: 60 problems at k=2 => 60 flat + 60 growth
uv run python scripts/stage_retune_candidates.py --with-battery \
  --presets g7_mid     --k-grid 2 --per-preset 120 --seed 6180 \
  --out-dir data/families --out-name bcg_ladder_candidates.jsonl

# cell C — the coefficient-identifiability contrast: same law, numerals 1 decade smaller
uv run python scripts/stage_retune_candidates.py --with-battery --append \
  --presets g7_narrow  --k-grid 2 --per-preset 60  --seed 6180 \
  --out-dir data/families --out-name bcg_ladder_candidates.jsonl

# cell E — the LEVEL DIAL: one unit of start degree above the F13 gate (es=3 vs es=4)
uv run python scripts/stage_retune_candidates.py --with-battery --append \
  --presets g6_tight   --k-grid 2 --per-preset 60  --seed 6180 \
  --out-dir data/families --out-name bcg_ladder_candidates.jsonl

# cell D (drop first) — the step kind alone, shipped numerals, no gate: the upper bracket
uv run python scripts/stage_retune_candidates.py --with-battery --append \
  --presets g1_reservoir --k-grid 8 --per-preset 30 --seed 6180 --stratify-step-kind \
  --out-dir data/families --out-name bcg_ladder_candidates.jsonl
```

`e3_lowdeg` is deliberately **absent** from the fresh staging: its cell is the *paired* anchor
below, not a redrawn control. The two remaining cells cannot be expressed by any per-preset flag
combination and need the selectors §10 (6) names:

* **Cell B** — `g7_mid` at **k = 32**, 6 chains × positions {1, 8, 16, 24, 32} = 30 leaves
  (24 flat spanning the reservoir walk + 6 growth). The default selector takes leaves in
  (problem, position) order, which at k = 32 would return 30 flat leaves and **zero** growth
  leaves — the top-of-grid cell must be stratified by step kind or it measures nothing.
* **Cell 0** — the paired anchor: 15 statements **already measured** in
  `data/bank/retune_measure.jsonl` (`e3_lowdeg`), re-emitted verbatim to
  `data/families/bcg_anchor_replication.jsonl`. This is `case-tree-hardening.md` §12's R0c lesson:
  a *paired same-statement* drift test, not a redrawn control against a historical aggregate. It
  cost the sibling $0.11 and it is what made every candidate number interpretable.

Seed **6180** is disjoint from 42 / 2026 (shipped datasets), 4242 (retune), 5150 (ct ladder),
4501–4503 (C1's probe) and 7001–7004 (v2 hardening), so no staged leaf has been measured before.

### (0d) Measure on the pod — one command per file, same recipe as `retune-notes.md` §0

```bash
uv run python scripts/build_bank.py \
  --dataset json --data-files data/families/bcg_ladder_candidates.jsonl \
  --out data/bank/bcg_ladder_calibration.jsonl \
  --backend repl --workers 4 --concurrent 4 --k 8 \
  --leaf-base-url http://localhost:8000/v1 \
  --leaf-model deepseek-ai/DeepSeek-Prover-V2-7B \
  --leaf-template deepseek-prover-v2-non-cot
```

**Do not pass `--leaf-max-tokens` / `--leaf-temperature`.** Every comparison in §5 is anchored on
`deepseek-ai/DeepSeek-Prover-V2-7B|deepseek-prover-v2-non-cot|Mdef|Tdef`; `leaf_id` carries the
full sampling profile, a different profile is a different experiment, and `build_bank`'s provenance
guard refuses to mix profiles in one file. Write to **fresh** `--out` paths;
`bank_dsv2.jsonl`, `family_leaf_calibration.jsonl` and `retune_measure.jsonl` are the measured
record and stay read-only.

Then apply §6's decision rule, and only then re-materialise with `gen_families.py` (§9).

### The cells, and what each one buys

| cell | rung | k | leaves | what it is the only source of |
|---|---|---|---|---|
| **0** | `e3_lowdeg` (anchor) | 2,4,8 | 15 (already measured) | R0c paired drift; without it nothing below is interpretable |
| **A** | **`g7_mid`** | **2** | **120** (60 flat + 60 growth) | `p_f`, `p_g`, and therefore **the whole flatness verdict** (§6/R3′). k=2 is the *most statistically efficient* k for this law: it is the only k where the two leaf types are 50/50 |
| **B** | `g7_mid` | **32** | 30 (24 flat + 6 growth) | top-of-grid: does the within-type rate measured at k=2 survive the reservoir walk (§7) |
| **C** | `g7_narrow` | 2 | 60 (30 + 30) | **coefficient identifiability** — same law, same degree, same gate, numerals 1 decade smaller. §8.2's option (b), measured rather than assumed |
| **E** | `g6_tight` | 2 | 60 (30 + 30) | **the level dial** — one unit of start degree above the F13 gate. The only lever this family has that moves the level without moving flatness |
| *D (drop first)* | `g1_reservoir` | 8 | 30 (stratified) | the step kind alone, no gate — the upper bracket and the ablation that shows F6 ∧ F13 is doing work |

**Row count: 285 statements (315 with cell D), 8 attempts each.**

Cell E is **not** droppable-first, and the reason is the sibling's lesson: its own drop order shed
`r1_recip`, "the only upper bracket *and* the cell §7.1's escalation branch reads first". Here cell E
is the level dial's second point, and §5 registers the level — not flatness — as the likely failure.
Cell D is the ablation and goes first if budget forces it.

### Cost

The sibling's estimate omitted pod setup and ran **86% low** on the invoice; the diagnosis was
pod-up time (2h12m against ~80 min projected), not throughput. So this table prices **pod-up**,
inflates it by the sibling's realised factor, and states the inflated number as the budget.

| step | statements × attempts | wall | $ at $3.2/hr (H100 PCIe) |
|---|---|---|---|
| fresh-pod setup (image, vLLM, model, Mathlib cache) | — | **~25 min** (sibling: install alone 13 min) | ~$1.33 |
| cells 0 + A (the decisive pair) | 135 × 8 | ~32 min @ 250 rows/hr | ~$1.71 |
| cells B + C + E | 150 × 8 | ~36 min | ~$1.92 |
| optional cell D (drop first) | +30 × 8 | +7 min | +$0.37 |
| **sub-total, cells 0/A/B/C/E** | **285 × 8** | **~93 min** | **~$4.96** |
| **× 1.65 (the sibling's realised pod-up inflation)** | | **~154 min** | **≈ $8.2** |
| the same with cell D | 315 × 8 | ~167 min | ≈ $8.9 |

**Budget $9, cap $11 — and this exceeds the standing authorization, so it must be asked for.**
The $12 overnight cap has $5.48 left above the $26.45 floor (`OVERNIGHT-2.md`, wallet $31.93 after
Pod A's $6.51 invoice).

**Minimum viable variant that fits the remaining $5.48: cells 0 + A only, 135 statements,
~57 min → ×1.65 → ~94 min → ≈ $5.0.** It answers the single question that matters — the flat leaf's
absolute level and `|p_f − p_g|` — and it leaves the within-type drift clause (§6/R3′b) formally
UNRESOLVED, which is the honest state to leave it in rather than a gap to hide.

One throughput note in this law's favour, and it is a real difference from the sibling: **the
reservoir law's leaf statements are the same size at k = 32 as at k = 2** (constant exponents,
≤ 3-digit knobs), so the "k=32 rows are several times slower" effect that blew up Pod A's estimate
does not apply here. 250 rows/hr is therefore deliberately pessimistic against the retune run's
measured 430–480.

---

## 1. What is being changed, and what is frozen

`generate(k, seed, n, preset="v2")`. The retune moved *knobs* over one unchanged schema. This
design adds **one new step kind** — a step that leaves the monomial alone — which is more than a
knob and less than a new family: the term shape `c·M + d·F(M) + o`, all three gates, the balanced
`le_trans` fold, the growth step and its witness are untouched, and the growth leaf's rendered text
and proof are **byte-identical** to the shipped ones. That is deliberate: it is what lets
`e3_lowdeg`'s measured growth-leaf difficulty carry into the new rung as an anchor rather than an
assumption.

### Frozen — a rung that breaks any of these is not a rung

| # | invariant | where it lives | why it is frozen |
|---|---|---|---|
| F1 | **preset `v2` is byte-identical** — same ids, declaration names, props, witnesses, RNG stream | golden tests; `_one`'s untagged id/name path | pinned by `test_default_preset_is_v2_and_its_output_is_byte_identical` and the cross-process determinism test. **Every new knob is drawn strictly AFTER the existing ones**, and `flat_steps` defaults `False`, so v2 never enters a new branch |
| F2 | **the per-step congruence gate** — at least one of `(c,d,o)` strictly drops across every step, **on both step kinds** | `step_resists_congruence`, `__post_init__` | the measured fix for v1's 16 `intros; gcongr <;> linarith` kills. C1's second planted control is a flat step differing from an admissible one *only* in that no coefficient drops, and it dies in ~1 s — so the gate does real work on the new leaf type too |
| F3 | **named-function content on every term** — `funcs` a non-empty subset of `{sqrt, log}`, `render_term` always emits `d·F(M)` | `__post_init__`, `render_term` | the second, independent barrier; a preset that relaxed it would be measuring tactic dispatch again |
| F4 | **`LOWER = 3`** | module constant | it is what makes `M' ≥ 3^δ M` **and** `1 ≤ M` true at all |
| F5 | **a flat step is a NEW STEP KIND, not `δ = 0`** — `deltas` keeps its `≥ 1` assertion | `__post_init__` | `δ=0` would make `_valid` and `_witness_proof` silently wrong (`hbase`/`hring` degenerate). `step_kinds` records `("flat", -1, 0)` so a datasheet can count leaf types |
| F6 | **the TIGHTNESS GATE is a gate, not a knob** — once `flat_steps` is on, `Δc + Δd + Δo = 0` on every flat step | `_valid_flat`, `__post_init__` | **new in this design, and it is measured, not argued.** With slack, `A·M + B·s + K ≥ 0` is unconditionally true over ℝ once `s² = M` is supplied (`A=1,B=−1,K=3` is `s²−s+3 ≥ 0`, discriminant `1−12 < 0`), so one `nlinarith [Real.sq_sqrt …]` hint closes the leaf **at any degree** and `1 ≤ M` — the whole level dial — is never needed. C1 measured 2–3 of 6 one-hint routes closing a slack flat leaf and **0 of 6** closing a tight one |
| F7 | **exactly one growth step per chain within the declared reach**, and it is the **last** step | `_sample_chain` schedule | this is what makes the per-k mean *exactly* affine in `1/k` (§6/R3′), which is the whole power argument. It must be asserted and recorded, not left to emerge |
| F8 | V0 (goal resists the battery), V5 (every leaf resists it), V6 with `visible_lemmas = []` and no exemption | `validate.py` | FAMILIES.md |
| F9 | **the planted control must die in the same pool, every pass** | the gate script | FAMILIES.md: "a gate that cannot kill is not a gate, and this project has shipped that defect twice" |
| F10 | determinism: a pure function of `(k, seed, idx, preset)` | `_rng`, golden tests | FAMILIES.md; C1's `build()` is exactly that |
| F11 | the witness stays **search-free** — no `nlinarith`, no new `ring`, no new `gcongr` on the flat kind | `_flat_witness_proof` | what keeps the composed k=32 artifact inside `PREAMBLE`'s `maxHeartbeats`. The flat witness is the growth witness **minus** the whole multiplicative block **plus** three lines, so V4's cost per leaf goes *down* |
| F12 | growth step + growth witness **byte-identical to shipped** | `_valid`, `_witness_proof` | the anchor in F-note above; a rung that changes them loses `e3_lowdeg`'s measured growth-leaf level |
| F13 | **`sum(start_exponents) ≥ 3` whenever `flat_steps` is on** — the start degree is a *gate below 3* and a dial only at and above it | `__post_init__` | **new in this design, measured in §4.1 and it changes the recommended rung.** The tightness gate alone is **not sufficient**: a *tight* flat leaf at es=1 falls to 2–3 of 6 one-hint routes and at es=2 to 0–3 of 6 (move-dependent); at es=3 and es=4 it is 0 of 6 at both numeral scales. Mechanism: the flat certificate needs `1 ≤ √M` or `1 ≤ M`, and with `s² = M` supplied `nlinarith` derives those from `3 ≤ x` by a *pair* product while a three-factor monomial is out of reach — the same blocker the whole family's difficulty rests on. F6 ∧ F13 is a conjunction; neither half suffices |

### Moving

`_sample_chain` (a schedule over two step kinds), `_valid_flat` + the tightness gate,
`_flat_witness_proof`, `admissible_starts(preset, k)`, and five additive `DifficultyPreset` fields
(`flat_steps`, `tight`, `final_growth`, `thrift`, `pace`). Knob **ranges** widen (`coef` to
`(2,100)`, `offset` to `(1,70)`) and `start_exponents` becomes a corridor-**level** dial that is flat
in k by construction — which is the part of this design that is more than a bug fix. Per F13 that
dial has a **measured floor at es = 3**: below it the flat leaf has a ceiling hole, so the usable
range is es ∈ {3, 4, 5, 6, …} and the two staged rungs sit on its first two rungs.

### What the fix costs, stated as a trade rather than a win

**Degree stops growing and the knob ranges start growing instead, linearly in k.** Minimum
coefficient budget (the largest numeral that can appear in a prop) is **4 / 7 / 23 / 87** at
k = 2/8/32/128 with the tightness gate, ≈ 0.68·k. That is the price, it is inside the range over
which coefficient magnitude is now *measured* difficulty-neutral (§2.4), and it is what §8.2 asked
for: "a growth law that is not exponential in k".

---

## 2. The measured problem — and there are two of them

### 2.1 R3 fails, for every preset, in the same direction

`data/bank/retune_measure.jsonl`, 150 rows, 30 leaves × 8 DSV2 attempts per preset:

| preset | mean | band-fit | zero | k=2 | k=4 | k=8 | spread | R3 (±0.05) |
|---|---|---|---|---|---|---|---|---|
| v2 | 0.196 | 0.27 | 0.57 | 0.237 | 0.113 | 0.237 | 0.125 | UNRESOLVED |
| e1_sqrt | 0.283 | 0.57 | 0.10 | 0.350 | 0.338 | 0.163 | 0.187 | UNRESOLVED |
| e2_flatstep | 0.267 | 0.60 | 0.20 | 0.325 | 0.325 | 0.150 | 0.175 | UNRESOLVED |
| **e3_lowdeg** | **0.429** | **0.83** | **0.07** | **0.575** | **0.463** | **0.250** | **0.325** | **FAIL (6.5×)** |
| e4_slack | 0.312 | 0.60 | 0.17 | 0.425 | 0.325 | 0.188 | 0.237 | UNRESOLVED |

(§8.1's correction is applied: at 10 leaves per k the 2σ-detectable per-k gap is 0.22–0.27, so only
`e3_lowdeg`'s 0.325 is a detectable failure. The other four read UNRESOLVED, not FAIL — the
original table's "FAIL" for those was stronger than the data.)

### 2.2 The mechanism, and it is structural

Two facts compose. **(i)** Leaf difficulty falls with left exponent sum: pooled es → pass@8 is
es=1 → 0.475, 2 → 0.463, 3 → 0.414, **4 → 0.287**, 5 → 0.188, 6–8 → ~0.147, 9+ → 0.106;
controlling for preset, **−0.0353/unit, SE 0.0079, z = −4.48**. **(ii)** Exponent sum grows +δ per
chain position by construction. For `e3_lowdeg` (δ=1, start degree 1) max es **equals k exactly**;
C1 measured mean leaf `es_left` 1.5 / 4.5 / 16.5 / **64.5** at k = 2/8/32/128, min–max 1–128 at the
top. A distribution that shifts right with k, crossed with a difficulty that falls in that
variable, *is* the per-k table.

es-standardising each k to the k=2 es distribution removes the whole k=4 gap and about half the
k=8 gap; the ~0.10 residual at k=8 is not separable from noise at n = 13–37 per cell.

### 2.3 What is NOT wrong — the per-position draw is flat in k

Structurally identical at every k (n=300 per k, free): `e3_lowdeg`'s position-1 `es` is 1.00 at
k = 2…32; v2's `(c,d,o)` at position 1 is 7.1–7.4 / 5.9–6.5 / 6.2–6.6 at every k. So FAMILIES.md's
per-position flatness claim holds and what fails is flatness of the **chain aggregate**, which is
the quantity the transfer plot integrates over. DIRECTION §5.4(a) still has no operational form for
the aggregate; §10 flags it.

### 2.4 §8.2's refutation of the multiplier fix — and one clause of it has since been measured

§8 proposed carrying growth in an integer multiplier, `M_i = 3^i · x^p y^q z^r`. §8.2 killed it:
`3^k` is 9 / 6,561 / **1.85×10¹⁵** at k = 2/8/32, i.e. **2.06×10¹⁴×** growth over k=2→32, where the
sibling ladder had already **excluded its highest-projected rung** (`H2_quartic`, projected 0.60)
for 45,394× on exactly these grounds.

**What has changed since C1's brief was written.** `case-tree-hardening.md` §12 measured R3′ on
239 rows: `pass@8 ~ log10 max|coef| + rung fixed effects`, support **0.60–4.59 decades**, slope
**+0.0053/decade, SE 0.0098, z = +0.55** (and −0.0007, z = −0.04 restricted to the three rungs with
variance). **Coefficient magnitude is measured difficulty-neutral over four decades.** Three
consequences for this file:

1. The reservoir law's price — numerals up to 87–100, i.e. **≈ 2.0 decades** — sits comfortably
   *inside* measured support, not one order past it. That is a much stronger claim than C1 could
   make and it is the single best piece of news in this design.
2. The residual coefficient gradient can now be **bounded with a measured slope** instead of
   argued. `g6_tight`'s mean leaf `c` moves 55.7 → 85.9 over k = 2→128 — i.e. **≤ 0.22 decades**, and
   `g7_mid` inherits it exactly (§3.4);
   at the 2σ upper edge of the sibling's slope (0.0249/decade) that is **≤ 0.0055 in pass@8**.
   Registered in §5 and cross-checked locally in §6/R3′b, because it is a cross-family borrow.
3. The objection to `3^k` must be restated as **"unmeasured at 10¹⁵"** rather than "known to break
   flatness" — 15 decades is still ~10 decades past the measured support, so the proposal stays
   rejected, on the honest grounds.

### 2.5 THE SECOND, PRIOR PROBLEM: the goal collapses, schema-wide — measured here, 2026-08-13

C1's claim 8 said the goal of `e3_lowdeg` falls to a fixed 15-line proof at k = 2/4/8/32, that v2
mostly resisted it (1 of 4), and that mixed `log`/`√` endpoints were a candidate escape. **The v2
rows were a probe artifact and the escape does not exist.** C1's `onestep_route` hard-codes
`Real.sqrt` for both endpoint function bounds, so it cannot close any goal whose endpoint drew
`log`; the failures show `hfu : √(x ^ 1 * …` in a goal containing `Real.log`.

Re-run with the route adapted to the function pair exactly as the generator's own `_fn_bounds`
adapts it (`Real.log_le_sub_one_of_pos` for a `log` on the left, `Real.log_nonneg` for one on the
right — both search-free, both already in the shipped witness), on goals from the **shipped
generator**, seed 4242, 3 problems per cell:

| preset | k=2 | k=4 | k=8 | k=32 | total |
|---|---|---|---|---|---|
| `v2` | 3/3 | 3/3 | 3/3 | 3/3 | **12/12** |
| `e1_sqrt` | 3/3 | 3/3 | 3/3 | 3/3 | **12/12** |
| `e2_flatstep` | 3/3 | 3/3 | 3/3 | 3/3 | **12/12** |
| `e3_lowdeg` | 3/3 | 3/3 | 3/3 | 3/3 | **12/12** |
| `e4_slack` | 3/3 | 3/3 | 3/3 | 3/3 | **12/12** |
| **by function pair** | `sqrt\|sqrt` 50/50 | `log\|sqrt` 4/4 | `sqrt\|log` 3/3 | `log\|log` 3/3 | **60/60** |

**60 of 60 goals closed**, kernel-checked at stock `PREAMBLE`. The proof is 15 lines at every k —
`intro`, the shipped `1 ≤ M` scaffold (`one_le_pow₀` ×3 + two `le_mul_of_one_le_right`), one
function upper bound, `hbase` (a single multi-variable `gcongr <;> linarith`), `hpow`, `hstep`,
`hring`, `rw`, `hMk`, one function lower bound, `linarith`. Its **line count does not depend on k**
and it reads only the two endpoint terms, which are the only thing the goal shows. A prover that
knows this idiom needs **zero** invented intermediates at any k.

C1's theorem says this cannot be gated away: with `3^δ·c_k ≥ c_end + d_end + (o_end − o_k)⁺`,
`c_end + d_end = c₀ + d₀ + Δ`, and `Δ ≥` the total offset drop (because `Δo ≥ −(Δc+Δd)` on every
flat step), the crude one-step slack is `≥ Δ − (o₀ − o_end) ≥ 0` for **every** knob range, every k
and every growth law in this term family. C1 then built an anti-collapse gate as a fourth gate and
measured its acceptance set **empty** at every budget and every k. Numerically: minimum crude slack
**0**, never negative, over ~2,000 random chains of eight candidate laws.

Four things follow, and the fourth is uncomfortable:

* **V0 cannot see this.** The battery is single tactics and the goals do survive it. FAMILIES.md's
  V0 row says "else the flat arm wins by tactic dispatch"; here the flat arm wins by a fixed
  **idiom**, one level up. bridge_chain has no known-route instrument; case_tree has one. §10.
* **The escape C1 left open is closed.** `log`-left/`√`-right does not help, because
  `log M ≤ M − 1` and `0 ≤ log M` (given `1 ≤ M`) are exactly as available and exactly as
  scale-free as the `√` bounds — they are the generator's own `_fn_bounds`. `log|log` closed 3/3.
* **`endpoints_resist_naive_collapse`'s docstring is false as stated** ("a quantitative ratio …
  which `gcongr` cannot produce"). `gcongr` produces `3^Δ ≤ v^Δ` in one line and
  `mul_le_mul_of_nonneg_right` + `ring` finish it. The gate still defeats the five routes it was
  measured against; its stated *reason* is wrong and the route it misses closes the shipped k=32
  goal. §10.
* **Bounding growth makes the collapse route CHEAPER to write, not harder.** Under the shipped law
  the route must carry the literal `3^Σδ` — a 16-digit numeral at k=32. Under the reservoir law the gain
  is **3** at every k, so the collapsing proof is byte-comparable at k=2 and k=128. What bounding
  growth *does* buy is margin: the crude collapse slack falls from **1.5×10¹⁶** (`e3_lowdeg` at
  k=32) to **2** (the reservoir law, at every k), so any relaxation weaker than the generator's own chain
  fails. That is a mitigation and it is measurable; it is not a fix.

**How to read this against the flatness fix.** The two problems are at different levels. The
reservoir law fixes the **leaf** axis, which is what R3/R3′, the corridor and requirement (a) are
about, and it fixes it well. The collapse is at the **goal** level, which is what requirements (b)
and (d) are about. Fixing the leaf axis is necessary and not sufficient, and no ordering of the two
lets the second be skipped. §6/R6 makes the collapse a reported, blocking line item rather than a
footnote.

---

## 3. The ladder

### 3.1 Shape: a chain, because here a chain is literally true — plus one designed side-branch

`case-tree-hardening.md` §3.1 used a star because its candidate mechanisms were different *kinds of
invention* and not orderable a priori. Here they are orderable and cumulative on one schema, which
is the condition retune §3 used a chain under: the levers are (1) the flat step exists, (2) the
tightness gate, (3) the start-degree dial, (4) the knob budget, and each adjacent pair of rungs
differs by exactly one of them, so a flat measurement between adjacent rungs localises a lever.

**Three of the four levers are not optional, and that is a measurement, not a preference** — which
is why the recommended rung is three levers from the control and why the brief's "one mechanism from
the control" cannot be honoured literally (deviation declared here, per the brief). The tightness
gate is a *gate* (F6) and the start degree is a *gate below 3* (F13, §4.1): a rung that moves only
lever (1) or only levers (1)+(2) has a measured corridor-ceiling hole and cannot ship. So levers
(1)–(3) travel together into the first shippable rung, and only lever (4) — the knob budget — and
the *remaining* degree freedom above the gate (es=3 vs es=4) are staged as separate cells.

```
e3_lowdeg ──(1) flat step exists──▶ g1_reservoir     [es=1, no gate; k ≤ 19; ABLATION: 3/3/2 of 6]
                                         │
                            (2) tightness gate       [es=1 tight: still 2–3 of 6 — §4.1]
                            (3) start degree → 3     [es=3 tight: 0 of 6 — the gate closes]
                                         ▼
                       g7_narrow ──(4) budget 9 → 100/70──▶  g7_mid   ◀── RECOMMENDED (es=3)
                    [k ≤ ~16]      (the identifiability contrast)  │
                                                                  │ (5) one unit of degree margin
                                                                  ▼
                                                              g6_tight  [es=4, C1's rung]
```

The `g7_narrow → g7_mid` edge moves **only** the knob budget, which is §8.2's option (b) — the
coefficient effect made identifiable rather than assumed. The `g7_mid → g6_tight` edge moves **only**
the start degree by one unit, above the F13 gate, which is the corridor's **level** dial and the one
lever this family has never been able to move without also moving flatness.

### 3.2 The step forms, once, for all rungs

A term is `c·M + d·√M + o`, `M = x^p y^q z^r`, side conditions `3 ≤ x,y,z`. Every rung fixes
`funcs=("sqrt",)` — the `e3_lowdeg` lineage R1/R2 selected — which matters because it makes the two
named-function atoms of a flat step **coincide**.

| step kind | monomial | atoms | facts handed to `linarith` | admissible iff |
|---|---|---|---|---|
| **growth** (unchanged, shipped) | `M' = v^δ·M`, δ ≥ 1 | `M, M', √M, √M'` | `1 ≤ M`, `3^δ M ≤ M'`, `√M ≤ M`, `0 ≤ √M'` | `c₂·3^δ − (c₁+d₁) ≥ (o₁−o₂)⁺` — **exactly `bc._valid`** |
| **flat** (new) | `M' = M` | `M`, `s = √M` — **one** `s`, the rendered text is identical on both sides | `1 ≤ s ≤ M` | `A ≥ 0`, `A+B ≥ 0`, `A+B+K = 0` where `A=Δc, B=Δd, K=Δo` |

The flat LP is the vertex/ray decomposition of `{1 ≤ s ≤ M}`: vertex `(1,1)` gives `A+B+K ≥ 0`;
ray `(M→∞, s fixed)` gives `A ≥ 0`; ray `(M→∞, s=M)` gives `A+B ≥ 0`. The **equality** in the third
is F6's tightness gate. Two unit-cost flat moves exist and they are the whole growth law:

```
m1 = (Δc, Δd, Δo) = ( 0, +1, −1)     spend one OFFSET unit, bank a d unit
m2 = (Δc, Δd, Δo) = (+1, −1,  0)     spend one COEFFICIENT unit, return a d unit
```

`m1` drops `o`, `m2` drops `d`, so F2 holds on both without any relaxation.

**Why the degree cannot be spent instead — and this is a kernel result, not a preference.**
*Lemma (no-shrink).* If `∀ x y z ≥ 3, c₁M + d₁F₁(M) + o₁ ≤ c₂M' + d₂F₂(M') + o₂` with `M`, `M'`
monomials, then every exponent of `M'` is ≥ the corresponding exponent of `M`. *Proof:* fix
`y = z = 3`, let `x → ∞`; `√` and `log` are `o(M)`, so the sides are asymptotic to `c₁3^{q+r}x^p`
and `c₂3^{q'+r'}x^{p'}`, and `p > p'` makes the ratio diverge. ∎ Kernel-checked refutations
(C1, `bc_growth_a/refute.json`): `drop_degree` (`2x²+√+1 ≤ 9x+9√+9`, degree 2→1) **refuted**;
`trade_big_offset` (`2x³yz+… ≤ 9xy³z+9√+99` — a **pure exponent trade at constant total degree 5**,
offset stacked in the sawtooth's favour) **refuted**. So there is no trading, no giving back, and a
bounded degree band forces `M' = M` on all but finitely many steps: **the flat step is the only
door.** (A third refutation script, `trade_x_for_y`, failed to close for a tactic-script reason —
`norm_num` normalising `√90000` in one hypothesis but not another. It is the same statement class as
the row that closed and it is reported as a probe defect, not as evidence.)

**Why a bounded-degree chain can only be so long — the reservoir.** *Theorem (flat-run bound).* On a
flat step F2 forces one of `(c,d,o)` strictly down and the LP forces `A ≥ 0`, `A+B ≥ 0`. Then
`Δo < 0 ⇒ A+B ≥ 1`; `Δd < 0 ⇒ A ≥ 1`; `Δc < 0` is impossible. So every flat step strictly decreases
`Φ = (C−c) + (C+D−c−d) ≥ 0`, and a flat run is at most `Φ` steps long. ∎ The exact longest run is a
DP in reduced coordinates, **verified against brute-force longest-path over the full move algebra on
all 647 live states of the shipped ranges**. This theorem *is* the R3 failure's contrapositive: with
no flat step available the generator must grow the monomial every step, so `deg = deg₀ + Σδ` grows
linearly in k by construction. The fix is not to change what carries the growth; it is to **stop
taking a growth step you do not need.**

### 3.3 The witness template, per step kind

**Growth — byte-identical to `bc._witness_proof` (F12).** No change, no re-derivation, and its
difficulty is anchored by `e3_lowdeg`'s measurement.

**Flat — the shipped scaffold, minus the multiplicative block, plus three lines:**

```lean
by
  intro x y z hx hy hz
  have hp0 : (1:ℝ) ≤ x ^ 2 := one_le_pow₀ (by linarith)
  have hp1 : (1:ℝ) ≤ y ^ 1 := one_le_pow₀ (by linarith)
  have hp2 : (1:ℝ) ≤ z ^ 1 := one_le_pow₀ (by linarith)
  have hA : (1:ℝ) ≤ x ^ 2 * y ^ 1 := le_trans hp0 (le_mul_of_one_le_right (by linarith) hp1)
  have hM : (1:ℝ) ≤ x ^ 2 * y ^ 1 * z ^ 1 := le_trans hA (le_mul_of_one_le_right (by linarith) hp2)
  have hfu : Real.sqrt (x ^ 2 * y ^ 1 * z ^ 1) ≤ x ^ 2 * y ^ 1 * z ^ 1 :=
    Real.sqrt_le_self_iff.mpr (Or.inr hM)
  have hfl : (1:ℝ) ≤ Real.sqrt (x ^ 2 * y ^ 1 * z ^ 1) := by
    have h := Real.sqrt_le_sqrt hM
    simpa using h
  linarith [hM, hfu, hfl]
```

No `ring`, no `gcongr`, no `nlinarith`; `hbase`/`hpow`/`hstep`/`hring`/`rw` are simply absent. The
three-line `1 ≤ √M` was probed, not guessed: `Real.sqrt_le_sqrt hM` + `simpa` works,
`Real.one_le_sqrt.mpr hM` works, `(Real.one_le_sqrt (by positivity)).mpr` does **not** (it is an
`Iff`, not a function, in this Mathlib). F11 holds and V4's per-leaf cost goes down, which matters
because at k=128 essentially every leaf is flat.

**The tightness gate is what makes this witness load-bearing.** With `A+B+K = 0` the leaf is tight
at `(M,s) = (1,1)`, so every certificate must pass through `1 ≤ s` or `1 ≤ M` — the
degree-sensitive obligation the level dial rests on. With slack, none of these lines is needed.

### 3.4 The rungs

Shared by every rung: `funcs=("sqrt",)`, `deltas=(1,)`, `flat_steps=True` (except the control),
`final_growth=True`, `thrift=1`, `pace=False`. Schedule: flat-first with forced growth on reservoir
exhaustion, thrifty successor choice, the last step a growth step chosen by `best_close` (argmin of
the endpoint-gate quantities), start state drawn from `admissible_starts(preset, k)`.

| rung | vs the rung above | coef | fcoef | offset | start_exp | tight | reach (k) | max total degree | leaf `es_left` | role |
|---|---|---|---|---|---|---|---|---|---|---|
| `e3_lowdeg` **(control)** | — (shipped; growth every step) | (2,9) | (1,9) | (1,9) | (1,0,0) | — | any (level dies ≈ 20) | **3 / 9 / 33 / 129** | 1.5 / 4.5 / 16.5 / **64.5** | the thing being replaced |
| `g1_reservoir` | **+ the flat step exists** | (2,9) | (1,9) | (1,9) | (1,0,0) | no | **≤ 19** | 2 / 2 / — / — | **1.00** (min=max) | **ablation** — isolates the step kind; fails F6 ∧ F13, cannot ship |
| `g7_narrow` | + F6 + F13 (start degree → 3) | (2,9) | (1,9) | (1,9) | **(1,1,1)** | **yes** | **≤ ~16** † | 4 / 4 / — / — | **3.00** (derived) | the coefficient-identifiability contrast |
| **`g7_mid`** | + knob budget 9 → 100/70 | **(2,100)** | **(1,100)** | **(1,70)** | **(1,1,1)** | **yes** | **≤ 133** | **4 / 4 / 4 / 4** | **3.00** (derived) | **RECOMMENDED** — nearest R1's target on the measured anchor (0.414) |
| `g6_tight` | + one unit of start degree | (2,100) | (1,100) | (1,70) | (2,1,1) | yes | **≤ 133** | **5 / 5 / 5 / 5** | **4.00** (min=max) | **margin rung** — C1's, fully gated; anchor 0.287 |
| ~~`g1t_tight`~~ (es=1 + gate) | — | (2,9) | (1,9) | (1,9) | (1,0,0) | yes | ≤ ~16 | 2 | 1.00 | **REFUTED as a rung** by §4.1: 2–3 of 6 routes close it. Kept as the ablation that identifies F13 |

Columns of four are k = 2/8/32/128. † `g7_narrow`'s reach is **derived, not measured**: the tight
run is ≈ 2·(o_max − o_min) = 16 at the shipped ranges and the tight minimum budget is 7 at k=8
(start `(5,1,7)`), so k ∈ {2,4,8} is safe and k=16 is not. `report_frontier` restricted to the
shipped ranges with `tight=True` settles it exactly, offline and free, and §9 step 1 requires it
before staging — `g7_narrow`'s feasibility, unlike `g1_reservoir`'s and `g6_tight`'s, was **not**
computed by C1.

`g7_mid` and `g6_tight` share every knob but `start_exponents`, and `start_exponents` does not touch
the `(c,d,o)` reservoir, so **`g7_mid` inherits `g6_tight`'s reach, discard rate, coefficient budget
and flat-share exactly** — the only differences are one unit of total degree and one unit of
`es_left`. That is what makes the pair a clean level dial.

### 3.5 Coefficient and degree budgets, at k = 2/8/32/128

| candidate | quantity | k=2 | k=8 | k=32 | k=128 |
|---|---|---|---|---|---|
| **`g6_tight`** | max total degree | **5** | **5** | **5** | **5** |
| | leaf `es_left` mean (min–max) | **4.00** (4–4) | **4.00** (4–4) | **4.00** (4–4) | **4.00** (4–4) |
| | max knob (largest numeral in a prop) | 97 | 91 | 100 | 100 |
| | `log10 max\|coef\|` | 1.99 | 1.96 | 2.00 | 2.00 |
| | total gain `M_k/M₀` | **3** | **3** | **3** | **3** |
| | growth steps | 1 | 1 | 1 | 1 |
| | flat-leaf share `(k−1)/k` | 0.500 | 0.875 | 0.969 | 0.992 |
| | discards to pass the gates (mean) | 0.0 | 0.0 | 0.0 | 0.0 |
| | crude collapse slack | 2 | 2 | 2 | 2 |
| | mean leaf `c` / `d` | 55.7 / 24.1 | 52.2 / 22.2 | 85.9 / 48.9 | 69.1 / 1.5 |
| **`g7_mid`** (recommended) | max degree; `es_left`; max knob | **4; 3.00; ≤100** | **4; 3.00; ≤100** | **4; 3.00; ≤100** | **4; 3.00; ≤100** |
| `g7_narrow` | max degree; `es_left`; max knob | 4; 3.00; **9** | 4; 3.00; **9** | — | — |
| `g1_reservoir` | max degree; `es_left`; max knob | 2; 1.00; **9** | 2; 1.00; **9** | — | — |
| ~~`g1t_tight`~~ (refuted) | max degree; `es_left`; max knob | 2; 1.00; 9 | 2; 1.00; 9 | — | — |
| `e3_lowdeg` (control) | max total degree | 3 | 9 | 33 | **129** |
| | leaf `es_left` mean (min–max) | 1.5 (1–2) | 4.5 (1–8) | 16.5 (1–32) | **64.5 (1–128)** |
| | max knob | 9 | 9 | 9 | 9 |
| | total gain | 9 | 6,561 | 1.9×10¹⁵ | **1.2×10⁶¹** |
| | crude collapse slack | 49 | 39,354 | 1.5×10¹⁶ | — |
| §8's `3^i` multiplier | max degree; total gain | 1; 9 | 1; 6,561 | 1; 1.9×10¹⁵ | 1; **1.2×10⁶¹** |

Rows for `g6_tight`, `g1_reservoir` and the control are **C1 measurements** (6 instances per cell,
seeds 4501/4502/4503 × 2 idx). Rows for `g7_mid` / `g7_narrow` / `g1t_tight` are **derived by
construction**
(degree = `sum(start_exponents) + Σδ` with `Σδ = 1`; `es_left` = `sum(start_exponents)` at every
position; max knob = the range endpoint) and must be confirmed by the offline table in §9 step 1.

**Both budgets are bounded, which is what §8.2 demanded.** Degree is *constant*; the coefficient
axis spans **0.04 decades across the entire k-grid** and tops out at 2.0 decades absolute — against
case_tree `v2`'s 2.05 decades of *k*-variation, the excluded `H2_quartic`'s 4.66, and §8's
multiplier at 15. The growth ratio k=2→32 is **1.03×**, against the multiplier's 2.06×10¹⁴×.

### 3.6 Directions considered and NOT staged, with the reason

| direction | source | why not |
|---|---|---|
| sawtooth / bounded window **in the exponent** (trade degree between variables) | the brief | **Kernel-refuted** (§3.2 no-shrink lemma + two closed refutations). No such step exists; this is a result, not a dead end — it converts "bound the degree" from a search over exponent schedules into the single question the flat LP answers |
| `M_i = 3^i · x^p y^q z^r` (integer multiplier) | retune §8 | **Rejected** per §8.2: 1.2×10⁶¹ at k=128, ~10 decades past the four now measured. §2.4 restates the objection as "unmeasured", which is the honest form and still disqualifying |
| `g3_k128` / `g4_deg4` / `g5_deg6` (reservoir law, **no** tightness gate) | C1 | Retained in C1's probe as the **ablation that identifies F6**, not as rungs. Flatness is as good as `g6_tight` (Δ`es_left` 0.01), all leaves and goals survive the full battery — and 2/2/2 (g3), 0/0/2 (g4), 2/2/2 (g5) of 6 one-hint routes close a flat leaf, always via `nlinarith [Real.sq_sqrt …]`. Raising the degree does **not** fix it (g5 at degree 6 is as leaky as g3 at degree 1), which is exactly the measurement that produced F6 |
| **start degree 1 or 2 WITH the tightness gate** (`g1t_tight`, `g2t_tight`) | §4.1 | **Refuted as rungs by measurement here.** They are the natural easier rungs — es=1 anchors at 0.475, closest of all anchors to R1's 0.45 — and they have a corridor-ceiling hole: 2–3 of 6 one-hint routes close a *tight* flat leaf at es=1, and 3 of 6 close the `m1` leaf at es=2, at **both** numeral scales. This is what F13 is, and it is the reason the level dial's floor is 0.414 rather than 0.475 |
| `start_exponents = (3,0,0)` (es=3, one factor) | this file, §6.1 step 2 | **Not measured, and it is the first thing to try if the level misses low.** §4.1's mechanism is that `nlinarith` chokes on *factor count* rather than exponent sum, so a one-factor es=3 monomial should be easier at the same total degree — and F13's measurement used `(1,1,1)`. If its ceiling proxy holds at 0/6 it is a free easing step; if it leaks, F13's real content is "≥ 3 distinct factors" and must be restated |
| `g2_wide` (intermediate budget, coef (2,20), no gate) | C1 | The measured middle of the linear trade-off law (budget 14 at k=32, reach k ≤ 56) and useful as such. Inherits g3's slack hole; needs F6 before it could be staged. Discards also rise to 7.5 at k=32 against `g6_tight`'s 0.0 |
| `g3_paced` (spend the reservoir at `Φ₀/k` per step) | C1 | Flattens the coefficient *marginal* (82/84/92/92) at the cost of degree 4, gain 27, and — fatally — making leaf **tightness** k-dependent: at k=2 each step jumps `c` by ~30 so the leaf is loose, at k=128 every step is `Δc=1` so it is tight. Keeping the per-leaf `linarith` certificate literally identical at every k is worth more than flattening `\|c\|`, because the certificate is what the prover must find. **Registered preference: ship the unpaced law**; §6/R3′b is the measurement that could overturn it |
| `log`-left / `√`-right flat flavour (cross bound `log M ≤ 2√M − 2`, probed available in two search-free lines) | C1 | Held as the **hardening reserve** (§6/R7b) if the flat leaf lands above 0.9. Not staged now: it changes the function mixture, which is a second lever, and the `log` marginal (0.074 vs 0.206) says it moves the level a long way |
| bank-drawn leaves (`FAMILIES.md` direction 1) | FAMILIES.md | Sidesteps the generator's growth law entirely and is where the sibling family's measured escalation already points. It is the right answer to §2.5 and it is out of scope for a $0 design: it needs the wide sweep (#12, ~$45 at estimates that run 50–90% low) |
| an anti-collapse fourth gate | C1 | **Built, then proved and measured EMPTY** — `report_frontier(anticollapse=True)` returns nothing at any budget for any k, and §2.5's theorem says why. Its emptiness is the result |

---

## 4. Local gate

§4.1 is measured here (it is a cell C1 did not build, and it moved the recommendation). §4.2
onwards is carried from C1, cited and not re-run.

### 4.1 The start-degree gate — measured here, 2026-08-13, and it is why `g7_mid` replaces `g6_tight`

C1 measured the tightness gate at **one** start degree (es=4) and concluded from `g5_deg6`'s
2/2/2-of-6 that "raising the degree alone does NOT fix it". That is true of *slack* leaves and it
left the interaction unmeasured: **is the gate sufficient at a low start degree?** The question
decides the rung, because R1's target is 0.45 and the measured es anchors are 0.475 (es=1) /
0.463 (2) / **0.414 (3)** / 0.287 (4) — C1's es=4 is 0.163 from target where es=3 is 0.036.

Twelve *tight* flat leaves built directly as strings — es ∈ {1,2,3} × both unit moves × both
numeral scales (shipped `(5,3,7)`-scale and wide `(55,24,40)`-scale) — through the same three
stages C1 ran, in one pool:

| es | monomial | move | routes closed of 6, shipped numerals | routes closed of 6, wide numerals | battery (20/prop) | witness |
|---|---|---|---|---|---|---|
| **1** | `x¹y⁰z⁰` | `m1` (needs `1 ≤ √M`) | **3** | **3** | survives | ✓ |
| 1 | | `m2` (needs `√M ≤ M`) | **2** | **2** | survives | ✓ |
| **2** | `x¹y¹z⁰` | `m1` | **3** | **3** | survives | ✓ |
| 2 | | `m2` | **0** | **0** | survives | ✓ |
| **3** | `x¹y¹z¹` | `m1` | **0** | **0** | survives | ✓ |
| **3** | | `m2` | **0** | **0** | survives | ✓ |
| 4 | `x²y¹z¹` | both | **0** (C1) | **0** (C1) | survives (C1) | ✓ (C1) |
| — | `x¹y⁰z⁰` | **planted_congruent** | — | — | **KILLED** | — |
| — | `x¹y⁰z⁰` | **planted_flat_nogate** | — | — | **KILLED** | — |

**12/12 witnesses kernel-check. 8/8 leaves survive the full battery. Both planted controls die in
the same pool** — including at the es=1 rendering with its exponent-0 factors, which is the cell
retune flagged as outside the measured region.

Four results, and three of them are new:

1. **F6 alone is not sufficient.** A tight flat leaf at es=1 falls to `nlinarith [Real.sq_sqrt …]`,
   `nlinarith [Real.one_le_sqrt.mpr …]` and the four-hint combination. **F6 ∧ F13 is the gate.**
2. **The boundary is exactly es=3**, and it is sharp: 3 → 0 for `m1` between es=2 and es=3.
3. **The mechanism is the family's own blocker, now shown to govern the flat leaf too.** `m1`'s leaf
   reduces to `1 ≤ √M` and `m2`'s to `√M ≤ M`; given `s² = M`, `nlinarith` gets both from `3 ≤ x`
   by a *pair* product when `M` has one or two factors and cannot when it has three. That is
   verbatim the `1 ≤ x^p y^q z^r` mechanism the retune measured (−0.0353/unit, z = −4.48) — which
   means the measured es → pass calibration curve should transfer to the flat leaf rather than
   needing its own. This is the strongest reason to expect `p_f ≈ p_g` (§5).
4. **The numeral scale makes no difference at all** — 3/2 at both scales for es=1, 3/0 for es=2,
   0/0 for es=3. That is *local, independent* evidence for P5 and for §2.4's measured neutrality,
   on the route axis rather than the pass-rate axis.

**Consequence: `start_exponents = (1,1,1)` — v2's own value, es=3, total degree 4 — is the
recommended rung, and es=4 becomes the margin rung.** es=3 is nearest R1's target on the measured
anchor, has one degree less, and is the *first* value that closes the ceiling hole; es=4 keeps one
unit of margin against a route repertoire richer than these six, which is exactly the risk a
boundary carries. Both are staged (§3.4).

Residual gap, stated: the es=3 **wide**-scale leaves got the witness and adaptation stages but not
the 20-proof battery (the es=1 wide-scale pair did, and C1 battery-tested five es=4 wide-scale flat
leaves). Step (0a) closes it.

### 4.2 Carried from C1 — cited and not re-run

All measured 2026-08-13 on the local `ReplPool`, Mathlib @ lean v4.34.0-rc1, stock `PREAMBLE`
(`maxHeartbeats 400000`). Battery = `families.validate.battery_proofs()`, 10 tactics ×
{bare, intros-first} = 20 attempts per prop, 25 s cap, **any** success kills.

| rung | witnesses kernel-checked | battery (V0/V5) | adaptation ladder (6 one-hint routes) | source |
|---|---|---|---|---|
| **`g6_tight`** | **51/51** — flat 27/27, growth 24/24; 12/12, 13/13, 13/13, **13/13** at k=2/8/32/128; **plus every leaf of one k=32 chain, 32/32** | 5 flat + 5 growth leaves + goals at k=8/32/128 + 6 k=128 flat leaves = **19/19 survive** | **0 of 6 on all 3 flat and all 3 growth leaves** | C1 §7.1–7.3 |
| `g1_reservoir` | 25/25 — flat 13/13, growth 12/12; 12/12 (k=2), 13/13 (k=8) | 5 flat + 5 growth + the k=8 goal survive | growth 0/6; **flat 3/3/2 of 6** (the slack hole) | C1 §7 |
| `g3_k128` (ablation) | 56/56 + 32/32 exhaustive | all survive | flat 2/2/2 of 6 | C1 §7 |
| `g4_deg4` / `g5_deg6` (ablations) | included, zero failures | all survive | 0/0/2 and 2/2/2 of 6 | C1 §7 |
| `s0_shipped` (= `e3_lowdeg`'s law, rebuilt in the probe) | 32/32 | — | 0 of 6 | C1 §7.1 |
| **cumulative** | **203/203 spanning + 64/64 exhaustive, zero failures anywhere** | **91 non-control props over three passes, 91 survive** | — | C1 |

**The planted controls were live, and they died — in the same pool, in every pass.**
`planted_congruent` (`2M+1√M+1 ≤ 9M+9√M+9`, all coefficients rise, same function) killed by
`intros; gcongr <;> linarith`. `planted_flat_nogate` (`4M+2√M+3 ≤ 5M+3√M+7` — a **flat** step
differing from an admissible one *only* in that no coefficient drops) killed the same way in ~1 s.
**2/2 controls killed in each of three passes.** The second one is the one that matters here: it is
the proof that F2 does real work on the *new* leaf type and that the gate **can** kill — the failure
mode FAMILIES.md says has shipped twice is not present.

**Offline machinery self-tested** (C1 `selftest`): the probe's fast move algebra and liveness match
`bc.live_states`' fixed point exactly (647/647 states), `flat_moves` and `growth_moves` are
exhaustive against a grid scan, and the reduced-coordinate run DP matches brute-force DAG
longest-path on every live state.

### What was NOT gated, and must be before the pod

* **V0–V6 have never been run for any bounded-growth candidate**, and V3/V4 in particular. C1
  built props in its own probe; the assembly is unchanged and V0/V2/V5 were measured on the props,
  but "should pass" is not measured, and this family already hit a k=32 V3 elaboration wall once.
  §9 step 1 makes it blocking. The flat witness is *cheaper* than the growth witness, so this law
  should **relax** the V4 wall — that prediction is registered in §5 (P8) precisely so it can fail.
* **`g7_mid` and `g7_narrow` were not built by C1 at all** — only §4.1's hand-built leaves at their
  start degree were. Their reach, discard rate and
  endpoint-gate feasibility at the shipped ranges are derived, not measured (§3.4 †). A rung that
  cannot pass its own gates at k=8 must be dropped in step (0a), not discovered on the pod.
* **The flat leaf's `maxHeartbeats` sensitivity.** Every verdict above is at 400000. FAMILIES.md is
  explicit that raising it **arms the adversary too** and retroactively invalidates every V0/V5
  verdict in the repo. If task #21 changes the budget, §4 and C1 §7.2/§7.3 must both be re-run with
  the planted controls attached.
* **Leaf-prop distinctness within a problem.** With a constant monomial, distinct exponent sums no
  longer make two leaves of one chain distinct for free. The flat-run monovariant does supply it
  (a `(c,d,o)` state cannot repeat inside a run), but it must be **checked**, not inherited (§10).

### One caveat when reading C1's raw files

The six k=128 battery props in C1's third pass are tagged `g3_k128/flat/k128/...` but were drawn
from `g6_tight`; the tag string was not updated with the candidate. Their offsets, up to 66,
identify them — only `g6_tight` has `o_max = 70`. Also, C1's `max_coef_of` counts exponents as
literals, so every coefficient-magnitude number above is from `max_knob`, computed from the knobs.

---

## 5. Registered predictions — written before the GPU run

### 5.1 How much to trust this, and in which direction to be wrong

There is no fitted model for the new step kind, so each projection is an interpolation between
measured anchors plus a mechanism argument, stated as such.

| anchor | what it measured | value | n |
|---|---|---|---|
| bridge_chain es → pass@8 (pooled, same family, same prover, same profile) | es=1 / 4 / 6 | **0.475 / 0.287 / 0.147** | 150 leaves × 8 |
| bridge_chain `e3_lowdeg` per-k | k=2 / 4 / 8 | 0.575 / 0.463 / 0.250 | 30 × 8 |
| bridge_chain, hand routes close **0/6** (four presets) | the "no probe closes" floor | **0.196 – 0.312** | 30 × 8 each |
| case_tree `r1_recip` — projected 0.62, idiom-distance 1, closes 12/12 locally | the "one lemma away, wrong family" floor | **0.000** (0 of 312) | 39 × 8 |
| case_tree R3′ | `log10 max\|coef\|` slope over 4 decades | **+0.0053/decade, SE 0.0098** | 239 |

**The track record has been reset since C1's brief.** bridge_chain's own §5 projections scored MAE
0.044 / r = 0.83 — but that was a *fitted three-factor cell model within one schema*. The sibling's
schema ladder, which is the right reference class for a new step kind, scored **MAE 0.253 with all
six errors negative** against a registered expectation of 0.15–0.20. So: **expect MAE ≈ 0.20–0.25,
and shade every projection DOWN.** Each interval below is deliberately asymmetric downward, and the
**ordering claims are the primary registered content** because they are far more robust than levels.

**The single most load-bearing regularity, and it cuts both ways.** "No local probe closes it" has
a measured floor of 0.196–0.312 in *this* family (four presets) — and a measured floor of **0.000**
in the sibling, when the required move lived in a family the prover does not use. C1's adaptation
ladder reads 0/6 for `g6_tight`, and §4.1 reads 0/6 for `g7_mid`'s start degree, on both leaf
types. That is consistent with 0.20 and it is
consistent with 0.00, and F6 is precisely a gate that *closed the route a prover would most
plausibly find* (`nlinarith [Real.sq_sqrt …]`). This is the `r1_recip` risk, in the same shape,
and it is why P2 carries an explicit 0.25 probability of collapse.

### 5.2 The quantity everything reduces to

Under F7 (exactly one growth step, last) the flat share is **exactly `(k−1)/k`**, so the chain
aggregate is

```
mean pass@8 at chain length k  =  p_f  +  (p_g − p_f) / k
```

with `p_f`, `p_g` the flat- and growth-leaf rates. (For k beyond one flat run, `G` growth steps
give `p_f + G(p_g − p_f)/k`; `G = 1` for all k ≤ 133 in `g7_mid` and `g6_tight`.) Two consequences that shape
every prediction and every gate below:

* the **spread over any k-range is `|p_g − p_f| · (1/2 − 1/k_max)`** — so R3's ±0.05 tolerance over
  k = 2…32 is exactly the condition **`|p_g − p_f| ≤ 0.107`**;
* the k-grid contributes **no new information about flatness** beyond what two leaf-type means at a
  single k already contain. That is the power argument in §6/R3′.

### 5.3 Per-rung projections

Band-fit is projected from an explicit leaf-level mixture, not guessed: at n=8 the band [0.25, 0.9]
excludes exactly {0/8, 1/8, 8/8}, so a leaf of true rate p is in band with probability
`1 − (1−p)⁸ − 8p(1−p)⁷ − p⁸` — 0.34 at p=0.15, 0.63 at 0.25, 0.94 at 0.45, 0.57 at 0.90.

| rung | `p_f` (flat leaf) | `p_g` (growth leaf) | projected k=2 mean | interval | projected band-fit | projected zero-rate | corridor verdict |
|---|---|---|---|---|---|---|---|
| `e3_lowdeg` (control) | — | 0.55 (es 1–2 at k=2) | **0.55** | 0.45–0.65 | 0.75 | ≤ 0.10 | in band at k=2, **fails R3** |
| `g1_reservoir` (ablation) | **0.60** | 0.45 | **0.53** | 0.35–0.85 | 0.70 | ≤ 0.05 | the slack hole makes the flat leaf the **easy** one; predicted to overshoot |
| `g7_narrow` | 0.32 | 0.36 | **0.34** | 0.15–0.52 | 0.78 | 0.15 | **in band, low side** |
| **`g7_mid`** | **0.32** | **0.36** | **0.34** | **0.15–0.52** | **0.78** | **0.15** | **in band, low side — the recommended rung** |
| `g6_tight` (margin) | 0.22 | 0.25 | **0.24** | 0.08–0.42 | 0.58 | 0.28 | at/below the floor; predicted to FAIL R2 on band-fit |

Reasoning, per rung:

* **`p_g` is the best-anchored number in the table.** The growth leaf is byte-identical in form to
  `e3_lowdeg`'s and carries `es_left` exactly `sum(start_exponents)`; the measured anchors are
  es=3 → **0.414** and es=4 → **0.287**. Both are shaded down (to 0.36 and 0.25) because the
  measured es-bucket pools monomials with 1–3 distinct factors while these rungs always have all
  three present — the *hard* end of the bucket, since the mechanism is that `1 ≤ x^p y^q z^r` is out
  of `nlinarith`'s pair-product reach in proportion to the number of factors.
* **`p_f` is projected only 0.04 below `p_g`, and §4.1 is why.** Before §4.1 the flat leaf was an
  unanchored leaf type and C1's registered prediction 6 put it well below the growth leaf. §4.1
  shows the two leaf types share **one** blocker: `m1`'s certificate is `1 ≤ √M`, `m2`'s is
  `√M ≤ M`, the growth leaf's is `1 ≤ M`, and all three flip from reachable to unreachable at the
  same place (2 → 3 distinct factors) for the same reason. So the measured es → pass curve should
  govern both types, `|p_g − p_f|` should be small, and R3′a should **pass**. This is the single
  biggest update §4.1 made to this design, and P2/P4's confidences move with it.
* **`g7_narrow` and `g7_mid` are projected identical** because §2.4's measured slope says the
  1-decade numeral difference moves pass@8 by ≤ 0.03 — and §4.1 measured *zero* difference between
  the two scales on the route axis. **That identity is the prediction**; the pair exists to test it
  (P5).
* **`g6_tight` is projected below `g7_mid` by 0.10**, which is the level dial's measured step
  (0.414 → 0.287 = 0.127 on the raw anchors). P6 is that this step reproduces.

### 5.4 Ladder-level registered claims

| id | claim | confidence |
|---|---|---|
| **P1** | `\|p_g − p_f\| ≤ 0.15` for `g7_mid`, i.e. the projected k=2→32 spread is ≤ 0.070 — **less than a quarter of the shipped rung's measured 0.325** | 0.75 |
| **P2** | `p_f < p_g` at the same start degree with the gate on | 0.55 — *deliberately near a coin flip.* C1 registered this at higher confidence on the grounds that the flat certificate carries one obligation more; §4.1 shows both types are gated by the same 2→3-factor threshold, so equality is now as plausible as the ordering |
| **P2′** | `p_f < 0.05` — the flat step is idiom-invisible, the `r1_recip` outcome | **0.12** (down from a pre-§4.1 0.25: `r1_recip` died because its lemma lived in a *different* family, whereas the flat leaf's blocker is this family's own measured blocker) |
| **P3** | The k=2 mean for `g7_mid` lands **below 0.25** (fails R2's level) | 0.35 |
| **P4** | Flatness on the mixture clause **PASSES** (`\|p_g−p_f\| ≤ 0.107`) for `g7_mid` | 0.65 |
| **P5** | `g7_narrow` and `g7_mid` differ by **< 0.08** in mean pass@8 — the coefficient axis is neutral over 2–100, extending §2.4's measured 4-decade neutrality downward into this family and matching §4.1's zero scale effect on the route axis | 0.80 |
| **P6** | The **level dial** works: `g7_mid` (es=3) − `g6_tight` (es=4) ≥ **+0.05**, same sign and order of magnitude as the measured anchors' 0.127 step and the −0.0353/unit slope | 0.65 |
| **P7** | `g1_reservoir`'s flat leaf measures **above** its growth leaf (the slack hole is a real difficulty hole, C1's 3/3/2-of-6 plus §4.1's 2–3/6 at es=1) — so that rung's per-k profile slopes the *wrong* way, upward in k | 0.65 |
| **P12** | The es=3 boundary is **not fragile to eight prover samples**: `g7_mid`'s flat leaves do not spike at 8/8 (share at exactly 8/8 ≤ 0.15). §4.1 found es=3 is the *first* value that closes the hole, and a boundary measured on 4 leaves × 6 hand routes is the weakest link in the recommendation — this is the number that tests it, and `g6_tight` is the margin rung if it fails | 0.55 |
| **P8** | The flat witness **relaxes** the V4 wall: full oracle compose for `g6_tight` at k=128 fits inside `maxHeartbeats 400000`. Stated as a prediction, not a comparison: FAMILIES.md's measured k=128 V4 exhaustion is for **case_tree**'s rungs, and bridge_chain's own V4 has never been run at k=128 — what *is* measured for this family is a k=32 **V3** wall that the balanced fold fixed (module docstring). So P8 is a claim about a cost that has never been measured in either direction | 0.55 |
| **P9** | Per-k means will read **UNRESOLVED** for every rung on the binned test at any n this project can afford (§6/R3), so an UNRESOLVED there must not be read as a failure; R3′ is the gate that can pass | 0.90 |
| **P10** | **Overshoot:** some rung's flat leaf measures > 0.9 and needs the hardening ladder | 0.15 |
| **P11** | R5: **no** rung satisfies DIRECTION §5.5(b) (≥70% oracle replay at every k) under the shipped `Budgets`, and none does at a flat `a=8` beyond k=8 | 0.85 |

**The registered shape of the outcome: flatness fixed, level in band but on the low side.** P4 at
0.65 and P3 at 0.35 say the most likely single result is `g7_mid` landing near 0.34 with a spread
under 0.07 — inside R2's band-fit clause, short of R1's 0.45, and flat. If the level misses low, the
dial exists and is measured (`start_exponents`: es=3 → 0.414, es=2 → 0.463, es=1 → 0.475) and is
flat in k by construction — but F13 forbids going below es=3, so the *available* range of the dial
is [es=3, es=4] and its lower stop is 0.414 on the anchor. **That is the design's tightest
constraint and it is worth stating plainly: F13 (a corridor-ceiling gate) and R1 (a corridor-level
target) squeeze the start degree from opposite sides onto essentially one value.** If es=3 measures
below 0.25, there is no legal easier start degree and the escalation is §6.1's step 3 (move the
level off the start-degree dial entirely) or step 4 (bank leaves).

If the pod contradicts any of this, **the contradiction is the finding** and should be written up as
such rather than patched.

### 5.5 The confounds, and which are controlled

| confound | status |
|---|---|
| statement length | **controlled, for free.** Leaf props are 176–180 chars at every k for every rung (constant exponents, ≤3-digit knobs), where the sibling's ladder varied 1.8× across rungs and had to declare it. Nothing here can be explained by text length |
| coefficient magnitude | **designed contrast** (`g7_narrow` vs `g7_mid`, 1.05 decades, everything else held) plus §2.4's measured 4-decade neutrality **and** §4.1's measured zero scale effect on the route axis. This is the one axis the law trades *into*, so it is measured three ways, not assumed |
| start degree vs the tightness gate | **separated locally, not on the pod.** §4.1 varies the start degree with the gate held on (es=1/2/3 tight) and C1 varies the gate with the degree held (g4 vs g6 at es=4), so the two are attributed by the local ceiling proxy. On the pod they travel together into every shippable rung, because F6 ∧ F13 is a conjunction — a pod-side attribution is not available and is not needed |
| leaf-type mixture | **it is the object of study**, not a nuisance: F7 makes the mixture weight exact and §5.2 makes the aggregate a closed form |
| position within the reservoir walk | **partly controlled.** Cell B samples positions {1, 8, 16, 24, 32} of a k=32 chain; the staged rows carry `position` already, so the analysis can condition on it |
| prover drift between pods | **controlled** by cell 0's paired anchor (the sibling's R0c, which found +0.025 ± 0.052 — no drift — over 15 paired statements, with individual leaf deltas of ±0.375 that would have fooled an eyeball) |

---

## 6. Decision rule for the GPU session

Applied to `data/bank/bcg_ladder_calibration.jsonl` in order. Adaptations from
`case-tree-hardening.md` §7 and `retune-notes.md` §6 are flagged **[adapted]** with a stated
reason; nothing is silently reinterpreted.

**R0 — validity.** Ignore rows with `status == "error"` (re-run with `--repair`). A row with
`elaborates == false` is a generator bug and blocks its rung outright.

**R0b — full validation, per rung, local and free. [new]** Before any rung is eligible,
`validate_problem` (V0–V6, battery on) must pass on ≥3 freshly generated problems at each of
k ∈ {2, 8} for that rung, plus one k=32 problem for V1/V3/V4 elaboration cost, plus the planted
controls dying in the same pool. Reason: this is a **step-kind** change, V3/V4 have never been run
for any bounded-growth candidate, and the flat witness is exactly what V4's compose path
exercises. This belongs in step (0a), not after the pod.

**R0c — anchor replication, blocking. [adapted]** Paired t-test over cell 0's 15 already-measured
statements against their `retune_measure.jsonl` values. If `|Δ| > 2 SE` (SE ≈ 0.05 at n=15), the
comparison is **void**: report it and select nothing. Reason: every projection in §5 is anchored on
that file's numbers; a paired same-statement test is the only form that separates prover/profile
drift from a leaf-mix difference — the sibling's redrawn-control version was measuring a 2.3×
median-coefficient difference, not drift.

**R1 — level (primary).** Pick the rung whose **mean measured pass@8 is nearest 0.45**. Report the
k=2 mean *and* the projected per-k profile `p_f + (p_g−p_f)/k`, because for this law they are
different numbers and only the second is what a k-grid dataset would deliver.

> **R1 tie rule, blocking. [adapted]** At 120 leaves per rung the SE of a rung's mean is
> **0.023–0.027** and the SE of a pairwise difference is **0.033–0.039**; at 60 leaves (cells C/D)
> those become 0.032–0.039 and 0.046–0.055. **R1 declares a TIE when two rungs' means differ by
> less than 1 SE of their difference — 0.04 for two 120-leaf cells, 0.06 when a 60-leaf cell is
> involved. Ties fall through to R4.** Reason: without a tolerance, R1 at this n decides between
> `g7_narrow` and `g7_mid` — a pair §5.3 projects *identical* and P5 registers no ordering for —
> by sampling noise, and the write-up would then read "X is the harder budget" about a coin flip.

**R2 — band fit, three CONJUNCTIVE clauses; report all three, always.** Require **band-fit ≥ 0.60**
(share of the rung's leaves with pass@8 ∈ [0.25, 0.9]) **and zero-rate ≤ 0.20** (share at 0/8),
with the mean near 0.45. FAMILIES.md's arithmetic is the justification and its corollary is the
warning: **heterogeneity, not the mean, is what fails the corridor** — a bimodal schema with 45% of
leaves at 0.60 and 55% at 0.02 has a respectable mean of 0.28, band-fit 0.44 and zero-rate 0.47,
and fails. **Mixing to hit a mean makes the corridor worse, not better.**

**R2b — leaf-type bimodality, reported and semi-gated. [new]** Report band-fit and zero-rate
**separately for flat and growth leaves**, and the share of leaves at exactly 0/8 or 8/8. Reason
specific to this law: the two leaf types are a *designed* mixture whose weights move from 50/50 to
99/1 across the k-grid, so a pooled band-fit measured at k=2 is not the band-fit a k=32 dataset
would have. **If `|p_g − p_f| > 0.20`, the pooled corridor numbers must be reported per leaf type
and the k=32 band-fit projected from the flat leaf alone** — otherwise the corridor verdict is
being read off a mixture the shipped grid does not contain.

**R3 — the binned per-k test: reported, NOT gated. [adapted]** Report per-k means and the max
pairwise gap for every rung. Do **not** use it as the gate: at 10 leaves per k the 2σ-detectable
gap is 0.22–0.27 and resolving ±0.05 needs ~288 leaves *per k per rung* (retune §8.1) — a gate with
no attainable PASS state. P9 registers UNRESOLVED as the expected reading.

**R3′ — flatness, PRIMARY, in two conjunctive clauses. [adapted — and this is the rule the design
turns on]**

The law makes the chain aggregate *exactly* `p_f + (p_g − p_f)/k` (§5.2), so flatness decomposes
into a mixture-weight term and a within-type drift term, and both are measurable at **one** k.

* **R3′a — the mixture clause (the gate).** Estimate `p_f` and `p_g` from cell A's 60 + 60 k=2
  leaves and require

  ```
  |p_g − p_f| ≤ 0.107      ⟺   projected k = 2…32 spread ≤ 0.05
  ```

  **PASS** if the 2σ interval for `|p_g − p_f|` lies below 0.107. **FAIL** if it lies above 0.213
  (projected spread ≥ 0.10). **UNRESOLVED** in between, which blocks Phase-1 close and triggers the
  60→120-per-type extension.

  **Power, exactly.** With leaf-rate SD 0.25–0.30, `SE(p_g − p_f) = SD·√(2/n)`:

  | leaves per type (all at k=2) | SE(difference) | 2σ-detectable \|p_g−p_f\| | resolvable k=2…32 spread |
  |---|---|---|---|
  | 15 | 0.091–0.110 | 0.18–0.22 | 0.086–0.103 |
  | 30 | 0.065–0.078 | 0.13–0.16 | 0.061–0.073 |
  | **60 (cell A)** | **0.046–0.055** | **0.091–0.110** | **0.043–0.051** |
  | 120 | 0.032–0.039 | 0.065–0.077 | 0.030–0.036 |

  Against the binned test, which needs **288 leaves per k** (≈ 864–1,152 leaves per rung) for the
  same 0.05 resolution: **cell A's 120 leaves buy the ±0.05 flatness verdict for the whole k-grid
  at roughly one eighth the cost.** The gain is structural — it comes from F7 making the k-profile a
  two-parameter family — not statistical, and it is the single strongest reason to prefer this law
  over any law whose k-profile has no closed form.

* **R3′b — the within-type drift clause.** `p_f` and `p_g` are themselves mildly k-dependent
  because `admissible_starts` depends on k and a longer walk occupies a different part of the knob
  range (mean leaf `c` 55.7 → 85.9, **≤ 0.22 decades**). Regress pass@8 on `log10(max knob)` over
  cells A + B + C with **step-kind fixed effects only — NOT rung fixed effects.** The sibling's R3′
  used rung fixed effects because its rungs differed in schema; here cells A and C differ *only* in
  the knob range, so a rung effect would absorb exactly the contrast being estimated and return a
  slope identified off nothing but the within-rung drift. (Cell E is the one cell that needs its own
  intercept, because its start degree differs; pool it with a `start_exponents` term, never with a
  free rung dummy that is collinear with the numeral scale.) Require

  ```
  2σ upper bound on |slope| × 0.22 decades  ≤  0.05
  ```

  The designed 1.05-decade contrast (cell C vs cell A, 30+30 leaves) gives slope SE ≈ 0.074/decade,
  2σ = 0.148, so the drift is bounded at **≤ 0.033** — inside the tolerance. The natural within-rung
  drift alone would only bound it to ≤ 0.07 at this n, which is *why* the identifiability cell
  exists. Cross-check, flagged as a cross-family borrow: the sibling's measured slope caps the
  drift at **≤ 0.0055**. Report both, and never let the borrow stand alone.

* **R3′c — `es_left` is a STRUCTURAL check, not a statistical one.** For every bounded-growth rung,
  `es_left` must satisfy **min = max = `sum(start_exponents)` at every position of every chain at
  every k**, verified offline on ≥300 chains per k at k ∈ {2,8,32,128}. There is no within-rung
  variance to regress against, by design: the −0.0353/unit lever is neutralised *by construction*,
  and the projected Δ pass@8 over k=2→128 is **0.0000** against **−2.22** for the shipped law. Any
  violation is a generator bug, not a flatness finding. Across rungs the same covariate becomes the
  **level dial** and P6 is its calibration test.

**R4 — tie-break**, in order: (1) smaller `|p_g − p_f|` (R3′a); (2) graded over bimodal (R2b);
(3) larger distinct-leaf capacity — the reservoir's live-state count is 647 at the shipped ranges
and 692,999 for the wide budget, and FAMILIES.md's GRPO-correlation note asks datasheets for
distinct-leaf counts; (4) lower discard rate (the wide budget 0.0 at every k vs `g2_wide`'s 7.5 at
k=32);
(5) smaller max numeral, since it is the axis the law trades into.

**R5 — oracle ceiling, blocking as a reporting requirement. [adapted]** The corridor is a
**per-leaf** statement; DIRECTION §5.5(b) is a **per-episode** one. A per-leaf mean of 0.45 does
**not** by itself satisfy (b) (§5.4(b′)). For this law the correct form is the **two-type** product,
because the mixture is known exactly:

```
oracle ceiling(k, a)  =  (1 − (1−p_g)^a) · (1 − (1−p_f)^a)^(k−1)
```

Report it for the shipped `Budgets` (`a = min(4, 64//k)`) **and** a raised flat `a`, alongside the
single-rate `(1 − (1−p)^a)^k` for comparability with the sibling. Registered scenarios:

| scenario | a | k=2 | k=4 | k=8 | k=16 | k=32 | k=128 |
|---|---|---|---|---|---|---|---|
| **S1** `p_f=0.15, p_g=0.25` (§5.3's central case) | shipped | 0.327 | 0.075 | 0.004 | 0.000 | 0.000 | 0.000 |
| | 8 | 0.655 | 0.347 | 0.097 | 0.008 | 0.000 | 0.000 |
| | 16 | 0.916 | 0.785 | 0.577 | 0.311 | 0.091 | 0.000 |
| **S2** `p_f=0.02` (flat leaf collapses, P2′) | 32 | 0.476 | 0.108 | 0.006 | 0.000 | 0.000 | 0.000 |
| **S4** `p_f=0.35, p_g=0.475` (start degree 1) | shipped | 0.759 | 0.512 | 0.233 | 0.048 | 0.000 | 0.000 |
| | 8 | 0.963 | 0.902 | 0.793 | 0.612 | 0.364 | 0.016 |
| | 16 | 0.999 | 0.997 | 0.993 | 0.985 | 0.969 | 0.879 |
| **S6** both at the corridor target 0.45 | 8 | 0.983 | 0.967 | 0.935 | 0.874 | 0.764 | 0.341 |
| | 16 | 1.000 | 1.000 | 0.999 | 0.999 | 0.998 | 0.991 |

Attempts needed for a ≥70% episode ceiling: **S1** {k2: 9, k8: 19, k32: 28, k128: 37}; **S4**
{4, 8, 11, 14}; **S6** {4, 6, 8, 10}; **S2** {60, 149, 222, 291} — i.e. if the flat leaf collapses,
no attempt budget this project could pay for rescues gate (b). A rung is **not** disqualified by a
low ceiling under the shipped budget — the budget is the free variable (task #22) — but the
write-up must state the ceiling explicitly, and P11 registers the expectation that nothing clears
(b) at k > 8 under `a = 8`.

**R6 — the goal-collapse line item, blocking on the write-up. [new, and it is §2.5]** No rung may
be reported as closing Phase 1 for bridge_chain without stating that the goal is closed by a fixed
k-independent 15-line idiom at every k tested, for every preset and every function pair (60/60),
and that C1 proved no growth law in this term family prevents it. Reason: R1–R5 are all *leaf* gates.
DIRECTION §5.4(b)/(d) are *goal* requirements, and this is exactly the failure mode §5.4(b′) was
written to prevent — two numbers that look healthy in isolation. Report the crude collapse slack per
rung (the reservoir law: 2 at every k; `e3_lowdeg`: 49 / 39,354 / 1.5×10¹⁶ at k=2/8/32) as the only
quantity that distinguishes them.

**Report every rung's numbers, including the ones that measure badly.** A rung that measures 0.05 is
as informative about the mechanism model as one that measures 0.45.

### 6.1 EASING ladder — if nothing lands because everything is too hard

Trigger: `g7_mid`'s k=2 mean < 0.25 (registered at 0.35 by P3).

1. **Read the two leaf types separately, first.** If `p_g ≈ 0.36` (its anchor) but `p_f < 0.05`,
   the finding is **P2′: the flat step is idiom-invisible** — the `r1_recip` outcome in a second
   family, which would make it a general result about synthetic step forms rather than an accident.
   Go to step 4 and report it as the headline.
2. **The start-degree dial is already at its legal floor.** F13 forbids es < 3, so the easing move
   the shipped rung would have used is closed by measurement. The one legal *fraction* of a step
   left is the monomial's *shape* at fixed es: `(1,1,1)` (three factors) versus `(3,0,0)` (one
   factor, es=3, total degree 4). §4.1's mechanism says factor count, not exponent sum, is what
   `nlinarith` chokes on — so `(3,0,0)` should be **easier at the same degree** and it is *not
   covered by F13's measurement*, which used `(1,1,1)`. **Measure the ceiling proxy on `(3,0,0)`
   first (6 routes × 4 leaves, local, free)**; if it holds at 0/6 it is a free easing step, and if
   it leaks then F13's real content is "≥ 3 distinct factors" and should be restated that way.
3. **Move the level off the start-degree dial.** Two measured levers touch only *one* leaf type, so
   they buy level at the cost of widening `|p_g − p_f|` — R1 and R3′a trade against each other here
   and the trade must be reported, not optimised away: the closing growth step's δ (δ=1 → 0.210 vs
   δ=2 → 0.095, growth leaf only) and the offset-drop lever (`o₁ ≤ o₂` → 0.194 vs `o₁ > o₂` → 0.101).
   Note that under F6 the flat moves already pin the offset direction, so the second lever is only
   available on the growth step.
4. **`FAMILIES.md` direction 1 — bank-drawn leaves.** Where the sibling family's measured escalation
   already points, and §2.5 says the goal-level defect needs a carrier outside this term algebra
   anyway. Needs the wide sweep (#12).

### 6.2 HARDENING ladder — if everything overshoots

Trigger: some rung's flat leaf measures > 0.9 (P10, 0.20 — and `g1_reservoir` is the cell most
likely to trigger it, by P7).

1. **Raise the start degree** — `(2,1,1)` (es=4, anchor 0.287, already staged as cell E), then
   `(2,2,1)` (es=5, 0.188) or `(2,2,2)` (es=6, 0.147). The dial has plenty of room upward, it stays
   flat in k, and total degree stays bounded (5 / 6 / 7). This is the *cheap* direction and it is the
   direction F13 leaves open.
2. **The `log`-left / `√`-right flat flavour** (§3.6). The cross bound `log M ≤ 2√M − 2` is
   available in two search-free lines via `Real.log_sqrt` + `Real.log_le_sub_one_of_pos` (probed),
   the measured `log` marginal is 0.074 vs 0.206, and it keeps the tightness gate intact. This is
   C1's registered reserve.
3. **δ=2 on the closing growth step** — hardens `p_g` only, and widens `|p_g − p_f|`.
4. **Do not reach for slack.** Dropping F6 would raise both rates, and C1 measured exactly what it
   buys: a leaf one `Real.sq_sqrt` hint closes at any degree, with `1 ≤ M` never needed. That is
   FAMILIES.md's V5 failure mode with extra steps.

---

## 7. Staging must cover the top of the k-grid

The sibling's original file was `k ∈ {2,4,8}` and therefore **could not reject a flatness failure at
k=16/32** — which is exactly how this family was written up as DONE while failing R3. Two things
follow, and the second is the interesting one.

**(a) k=32 is staged, as cell B.** 6 chains × positions {1, 8, 16, 24, 32} = 30 leaves, 24 flat
spanning the reservoir walk + 6 growth. It is the only cell that can detect a within-type drift the
`log10(max knob)` covariate does not capture — e.g. a position effect in the walk that is not a
magnitude effect. Its statistical resolution is coarse (a k=2-vs-k=32 within-type difference is
detectable at ~0.17 with 60 vs 15 leaves) and that is stated rather than hidden: cell B is a
**tripwire at the top of the grid**, not the flatness gate.

**(b) For this law, the flatness gate does not live at the top of the grid, and that is a property
of the law rather than a budget concession.** Because F7 makes the k-profile exactly
`p_f + (p_g−p_f)/k`, the k-grid's information about flatness is *entirely* contained in two
leaf-type rates, and k=2 is where they are estimated most efficiently (the only k with a 50/50
split; 60+60 from 60 problems, versus 60 growth leaves needing 60 problems and 1,860 wasted flat
leaves at k=32). Spending the budget at k=32 instead would **lose** power. The right discipline is
therefore: gate at k=2, tripwire at k=32, and state the closed form so a reader can check the
projection against any future k-grid dataset.

**(c) Structural coverage runs to k=128, offline and free**, and it must be reported in the
datasheet: max total degree, `es_left` min/mean/max, max knob, flat share, growth-step count,
discard rate and crude collapse slack at k ∈ {2, 8, 32, 128} — C1's table, re-run through the
shipped generator. That is where a k=128 regression would show up as a *construction* violation
(R3′c) long before any measurement.

**(d) The `maxHeartbeats` wall is the real top-of-grid limit, and it is not this law's fault.**
FAMILIES.md measured V4 (full oracle compose) exhausting the stock 400000 at k=128 for **case_tree**
rungs; bridge_chain's own V4 has never been run at k=128, and the family's one measured wall is a
k=32 **V3** failure that the balanced `le_trans` fold already fixed. P8 registers that the flat
witness relaxes whatever the wall turns out to be, since it is the growth witness minus the whole
multiplicative block. Either way: if task #21 raises the budget, every V0/V5 verdict in §4 must be
re-run with the planted controls attached — **the budget arms the adversary too.**

---

## 8. What this does NOT establish

1. **No pass@8 was measured, here or in C1.** Everything is a battery floor (definitive), a witness
   kernel check (definitive), a kernel refutation (definitive), an exact structural computation
   (definitive), a route-detector proxy (indicative), or an arithmetic projection (registered).
2. **`p_f` — the flat leaf's absolute level — is unmeasured, and flat leaves are 99% of leaves at
   k=128.** Every corridor claim in this file is conditional on a number nobody has. That is why
   cell A exists and why it is the minimum viable pod.
3. **The adaptation ladder is a route detector, not a difficulty meter.** C1's 0/6 for `g6_tight` and
   §4.1's 0/6 at es=3 say the six hand routes do not apply; the sibling measured that "no probe closes" spans 0.000 to
   0.219 and this family measured it spanning 0.196 to 0.312. Six hand routes are not eight DSV2
   samples — the one in-band v2 leaf's measured proof was a 20-line chained argument no hand probe
   would have found.
4. **The projections have no fitted model behind them for the new step kind**, and the right
   reference class scored **MAE 0.253 with every error negative**. Read §5 as ordering claims with
   a downward bias, not as estimates.
5. **`g7_mid` and `g7_narrow` are not built or gated as presets.** §4.1 gated hand-built leaves at
   their start degree and numeral scales, but their reach, discard rate and endpoint-gate
   feasibility are derived; `g7_narrow`'s k=8 feasibility in particular is unconfirmed. If either
   fails R0b it is dropped, and `g6_tight` — which C1 gated fully — becomes the primary rung at the
   cost of 0.13 on the level anchor.
6. **V3 and V4 are unmeasured for every bounded-growth rung**, and the k=128 compose wall is
   untested for the flat witness (P8 is a prediction).
7. **Battery resistance is a property of *this* Mathlib** (lean v4.34.0-rc1, stock PREAMBLE) and of
   `nlinarith`'s pair-product preprocessing in particular. F6 exists because a *single* hint changed
   a leaf from unreachable to closed; another hint repertoire could do it again. The mitigation is
   that the gate is re-runnable with its planted controls attached, so a Mathlib upgrade that
   softens a rung fails loudly.
8. **R3 as literally written (±0.05 on binned per-k means) is not attainable at any budget this
   project will spend.** §6/R3′ is what will be evaluated; the honest reading of a pass is "no
   leaf-type difference larger than 0.09–0.11 was detected, which bounds the projected k=2…32
   spread below 0.05", not "flat to ±0.05".
9. **Nothing here fixes §2.5.** The reservoir law repairs the leaf axis of a family whose *goal* is
   collapsible by a fixed idiom, and C1's theorem plus this file's 60/60 measurement say no growth
   law in this term algebra changes that. A dataset built on `g7_mid` has a defensible k-axis at the
   leaf level and a decorative one at the goal level.
10. **Leaf-disjointness is still not implemented for family-generated leaves** (task #19), so no
    dataset produced from any rung here is train/eval-separable yet, and the bounded-degree law
    makes one of its obligations *harder*: with a constant monomial, two leaves of one chain are no
    longer distinct for free.

---

## 9. ORDER OF OPERATIONS — a rung change invalidates every existing bridge_chain artifact

**Hard constraint, not a cleanup note.** A rung changes leaf *statements*. Statements are what
`statement_key` hashes, what `leaf_split` derives membership from, and what the measured bank is
keyed on.

1. **Implement §3 behind additive preset flags** (`flat_steps`, `tight`, `final_growth`, `thrift`,
   `pace`), drawn strictly after the existing knobs, with `v2`'s stream untouched (F1) and F5/F6/F7
   asserted in `__post_init__`. Then, offline and free, produce the **structural table**: for each
   rung, `report_frontier(tight=…)` restricted to its ranges (this is what settles `g7_narrow`'s
   reach), plus degree / `es_left` min-mean-max / max knob / flat share / growth-step
   count / discard rate / crude collapse slack at k ∈ {2, 8, 32, 128} on ≥300 chains per cell.
   **Drop any rung whose gates are infeasible at its staged k before spending anything.**
2. **Run the full local gate through the shipped generator** — battery + witness + both planted
   controls + `validate_problem` V0–V6 at k ∈ {2, 8, 32} (R0b). This is the first time V3/V4 will
   have run for a bounded-growth law.
3. **Fix the two blocking contract items in §10 (1) and (2)** — `check_preset_invariants` rejects
   every bounded-growth law today, and `gen_families.py` cannot select a preset. Without the first,
   step 2 fails for the wrong reason.
4. **Stage** (0c), including the two stratified cells and the paired anchor.
5. **Get authorization**, then measure (0d). $8 budget / $10 cap for all cells, or ~$5 for the
   minimum viable pair, against $5.48 remaining under the overnight authorization.
6. **Apply §6.** Then, and only then, re-materialise with `gen_families.py` at the chosen rung — at
   which point every existing bridge_chain dataset row, datasheet and leaf-split membership is
   stale and must be regenerated. `retune_measure.jsonl` and `family_leaf_calibration.jsonl` stay
   read-only as the measured record.

---

## 10. Contract friction (reported, not worked around — none of these files are owned here)

1. **BLOCKING: `check_preset_invariants` hard-codes `exponent sums are not strictly increasing` as
   a violation.** Every law that bounds degree makes that sequence non-decreasing, so the invariant
   checker **rejects the fix for the failure it was written alongside**. It must relax to
   non-decreasing, and the property it was really buying — no intermediate term collides with an
   endpoint — needs its own explicit check, **plus** a new check that no two leaf props in one
   problem are identical (with a constant monomial, distinct exponent sums no longer supply
   distinctness for free).
2. **BLOCKING: `gen_families.py` cannot select a preset** (retune §8 friction 4), so nothing
   designed here can be materialised into a dataset without that one-flag change.
3. **`endpoints_resist_naive_collapse`'s docstring is false as stated** — "a quantitative ratio
   `M_k ≥ r·M₀` … which `gcongr` cannot produce". `gcongr` produces `3^Δ ≤ v^Δ` in one line and
   `mul_le_mul_of_nonneg_right` + `ring` finish it; the generator's own per-step witness does
   exactly this. The gate still defeats the five routes it was measured against, but its stated
   reason is wrong and the route it misses closes the shipped k=32 goal (§2.5). Recommend correcting
   the docstring and re-scoping the gate to what it actually buys.
4. **V0 has no known-route instrument for bridge_chain.** FAMILIES.md's V0 row says "else the flat
   arm wins by tactic dispatch"; §2.5's route wins by a fixed **idiom**, one level up from a tactic.
   case_tree has an idiom probe for exactly this; bridge_chain has none. A small registry of
   generator-derived flat routes, run like the battery with a planted control, belongs in
   `validate.py` beside V0. C1's `--collapse` stage and this file's §2.5 probe are prototypes.
5. **DIRECTION §5.4(a) still has no operational form for the CHAIN AGGREGATE.** retune §8's "two
   flatness axes" draft sits in `lever-model-refit.md` §4 and never landed in DIRECTION. Everything
   here is reported against R3′ because it is the only form measurable at any n this project can
   afford. §6/R3′ additionally proposes the *closed-form* version for laws with a known leaf-type
   mixture, which is stronger than either draft and belongs in the same edit.
6. **`stage_retune_candidates.py` needs four flags, and NO new columns.** The row shape already
   carries `delta` (`0` ⟺ a flat leaf) and all six knobs, so `step_kind` and `max_knob` — the two
   covariates R3′ needs — are **derivable from the shipped columns**; nobody should add any. What is
   missing is plumbing, all of the same class the sibling's `stage_ct_ladder.py` added:
   (i) `--out-name` and (ii) `--append`, since today the output path is the fixed
   `retune_candidates.jsonl` and a second cell would overwrite the first;
   (iii) `--stratify-step-kind` (or an explicit `--positions` list), because the default takes
   leaves in (problem, position) order and at k=32 that returns 30 flat leaves and **zero** growth
   leaves — cell B would silently measure one leaf type and be reported as both;
   (iv) an emit-from-a-measured-file mode for cell 0's paired anchor. Also note `--per-preset`
   splits evenly across `--k-grid`, so a multi-k cell (E) gets `per_preset // |k_grid|` per k.
7. **`maxHeartbeats` coupling.** All §4 verdicts are at 400000. The flat witness is strictly cheaper
   than the growth witness, so this law *relaxes* the V4 wall FAMILIES.md documents — but any budget
   change retroactively invalidates every battery and adaptation verdict here and in C1, and both
   must be re-run with the planted controls attached (task #21).
8. **The attempt budget (task #22, DIRECTION §5.4(b′)) is now the binding constraint on gate (b),
   not the schema.** §6/R5's S6 row shows that even *both* leaf types at the corridor target need
   `a = 8` at k=8 and `a = 10` at k=128; the shipped `a = min(4, 64//k)` yields 0.000 at k=32 for
   every scenario in the table. No corridor-target family can satisfy §5.5(b) at k > 2 under the
   shipped `Budgets`. That is a core-contract decision and it does not belong to a family file.

---

## 11. Appendix — the two probes made here, verbatim

Neither is in the repo (this agent owns only this file), so both are transcribed. Whoever implements
§3 should fold them into `scripts/probes/` — §10 (4) argues the first belongs in `validate.py`
beside V0, and the second is the ceiling instrument every future start-degree change needs.

### 11.1 The §2.5 endpoint-collapse route

It
imports `bridge_chain` read-only, reconstructs each goal's two endpoint terms from the problem's own
`meta["step_kinds"]` and the preset's `start_exponents`, builds the endpoint route with the
function-adapted bounds, and kernel-checks it via `ReplPool(n_workers=3)` at `timeout_s=60`.

```python
# route(first, last) — the generator's own witness idiom, applied to the ENDPOINTS
lines = ["by", "  intro x y z hx hy hz"] + scaffold(e0)      # bc._witness_proof's `1 ≤ M` block
if f0 == "sqrt":                                              # LEFT bound, as bc._fn_bounds
    lines.append(f"  have hfu : Real.sqrt ({mono0}) ≤ {mono0} := Real.sqrt_le_self_iff.mpr (Or.inr hM)")
else:
    lines.append(f"  have hfu : Real.log ({mono0}) ≤ {mono0} - 1 := Real.log_le_sub_one_of_pos (by linarith)")
lines += [
    f"  have hbase : {ratio3} ≤ {ratiov} := by gcongr <;> linarith",
    f"  have hpow : ({gain}:ℝ) ≤ {ratiov} := by linarith [hbase]",
    f"  have hstep : ({gain}:ℝ) * ({mono0}) ≤ ({ratiov}) * ({mono0}) :="
    " mul_le_mul_of_nonneg_right hpow (by positivity)",
    f"  have hring : ({ratiov}) * ({mono0}) = {monok} := by ring",
    "  rw [hring] at hstep",
    f"  have hMk : (1:ℝ) ≤ {monok} := by linarith [hM, hstep]",
]
if fk == "sqrt":                                              # RIGHT bound, as bc._fn_bounds
    lines.append(f"  have hfl : (1:ℝ) ≤ Real.sqrt ({monok}) := by\n"
                 "    have h := Real.sqrt_le_sqrt hMk\n    simpa using h")
else:
    lines.append(f"  have hfl : (0:ℝ) ≤ Real.log ({monok}) := Real.log_nonneg (by linarith [hMk])")
lines.append("  linarith [hM, hfu, hfl, hstep]")
```

Grid: 5 presets × k ∈ {2,4,8,32} × 3 problems, seed 4242, `bc.generate` unmodified.
Result: **60/60 closed**, 0 failures, every function pair represented
(`sqrt|sqrt` 50, `log|sqrt` 4, `sqrt|log` 3, `log|log` 3).
The only k-dependence in the emitted text is the literal `gain = 3^Σδ` — 16 digits at k=32 for
`e3_lowdeg`, and **3 at every k** for any reservoir rung.

### 11.2 The §4.1 start-degree gate

Leaves are built as strings rather than sampled, so the cell is exactly the (es × move × scale) grid
and nothing else varies. `EXPS = {1:(1,0,0), 2:(1,1,0), 3:(1,1,1), 4:(2,1,1)}`;
`MOVES = {"m1": ((5,3,7) → (5,4,6)), "m2": ((5,3,7) → (6,2,7))}` at the shipped scale and
`{"m1": ((55,24,40) → (55,25,39)), "m2": ((55,24,40) → (56,23,40))}` at the wide scale — both moves
are tight (`Δc+Δd+Δo = 0`) and both drop a coefficient (F2).

```python
def prop_of(exps, lo, hi):                      # a tight flat leaf, rendered as bc does
    M = bc._mono(exps)
    side = lambda k: f"{k[0]} * {M} + {k[1]} * Real.sqrt ({M}) + {k[2]}"
    return f"{bc.BINDER}{side(lo)} ≤ {side(hi)}"

# stage (a) the flat witness of §3.3;  (b) V.battery_proofs() — 20 per prop, 25 s, ANY success kills,
# with planted_congruent ((2,1,1)->(9,9,9)) and planted_flat_nogate ((4,2,3)->(5,3,7)) in the SAME
# pool;  (c) C1's six ADAPT_ROUTES verbatim, formatted with M = N = the single monomial.
```

Result: **witnesses 12/12; battery 8/8 leaves survive and 2/2 planted controls die; adaptation
routes closed of 6 = es1 [3, 2, 3, 2], es2 [3, 0, 3, 0], es3 [0, 0, 0, 0]** (order: m1-shipped,
m2-shipped, m1-wide, m2-wide). The closers are always `nlinarith+sq_sqrt`,
`nlinarith+one_le_sqrt` and the four-hint `nlinarith+both` — every one of them a route that supplies
`s² = M` and then needs `1 ≤ √M` or `1 ≤ M` from `3 ≤ x`, which is a pair product at 1–2 factors and
a triple product at 3.
