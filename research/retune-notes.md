# bridge_chain leaf-difficulty retune — staged candidates for the GPU session

Phase 1 stayed **open on one finding** (OVERNIGHT.md, 2026-08-12 flatness verdict):
bridge_chain's per-leaf difficulty is **flat in k** (pass@8 0.125 at k=4 vs 0.129 at k=8 —
within 0.004, the size axis is structurally sound) but the **level fails** — ~0.13 sits
below the **0.25** floor of the [0.25, 0.9] corridor. Leaves must get **easier** without
falling to the automation battery (FAMILIES.md V5), which is the corridor's floor.

This file stages that retune. It contains four candidate easier presets, the measured
evidence each was derived from, the **local** gate results (automation battery + witness
kernel checks, run here on the live toolchain), and the decision rule the GPU session
applies. **No pass@8 is measured here** — the frozen DSV2-7B leaf lives on the pod.

Owned files: `src/rlmath/families/bridge_chain.py` (knob parameterization only — no schema
change), `scripts/stage_retune_candidates.py`, `tests/test_family_bridge_chain.py`
(additions), this file. Measurement date: 2026-08-12, local `ReplPool(n_workers=2)`,
Mathlib @ lean v4.34.0-rc1, stock `PREAMBLE`.

---

## 0. What to run on the pod (TL;DR)

`data/families/retune_candidates.jsonl` — **150 rows, 5 presets × 30 deduped leaves**,
k ∈ {2,4,8} evenly, seed 4242, already `build_bank`-ingestable. All five survive the local
battery gate; none was dropped.

```bash
uv run python scripts/build_bank.py \
  --dataset json --data-files data/families/retune_candidates.jsonl \
  --out data/bank/retune_calibration.jsonl \
  --backend repl --workers 4 --concurrent 4 --k 8 \
  --leaf-base-url http://localhost:8000/v1 \
  --leaf-model deepseek-ai/DeepSeek-Prover-V2-7B \
  --leaf-template deepseek-prover-v2-non-cot
```

**Do not pass `--leaf-max-tokens`/`--leaf-temperature`**: the comparison baseline
(`data/bank/family_leaf_calibration.jsonl`) was measured at
`deepseek-ai/DeepSeek-Prover-V2-7B|deepseek-prover-v2-non-cot|Mdef|Tdef`, and `leaf_id`
carries the full sampling profile — a different profile is a different experiment, and
build_bank's provenance guard will refuse to mix them in one file anyway. Write to a
**fresh** `--out`; `bank_dsv2.jsonl` and `family_leaf_calibration.jsonl` are the measured
record and stay read-only.

Cost: 150 statements × 8 attempts. Measured overnight throughput was 430–480 rows/hr with
`--concurrent` (16.3 s/statement single-stream), so **≈20 minutes ≈ $1–2** of the ~$5
Phase-1-close session. `v2` is included as an in-session control (30 *fresh* leaves from
the shipped distribution) so the four candidates are compared against a v2 number measured
on the same pod, same day, same sampling profile — not against last night's 58 rows.

Then apply §6's decision rule and re-materialize the chosen preset with
`scripts/gen_families.py`.

---

## 1. What is being retuned, and what is not

`generate(k, seed, n, preset="v2")`. A preset is a `DifficultyPreset` — coefficient
ranges, offset range, δ choices, function mixture, start exponents. **Schema, step form,
witness template, the balanced `le_trans` fold and all three gates are unchanged**, which
is what keeps research/family-v2-hardening.md's measured V0–V6 tables applicable.

Two things are **not** knobs and cannot be switched off by any preset (asserted in
`DifficultyPreset.__post_init__` and by `test_no_preset_can_switch_off_the_battery_invariants`
/ `test_a_preset_that_drops_named_functions_is_rejected_at_construction`):

1. **the per-step congruence gate** — at least one of `(c, d, o)` strictly drops across
   every step; the measured fix for v1's 16 `intros; gcongr <;> linarith` kills;
2. **named-function content on every term** — `funcs` must be a non-empty subset of
   `{sqrt, log}` and `render_term` always emits `d * F(M)`.

`LOWER = 3` is likewise fixed: it is what makes `M' ≥ 3^δ M` and `1 ≤ M` true at all.

**v2 is the default and is byte-identical to the pre-preset generator** — same ids, same
`theorem` names, same seed strings, same props, same witnesses. The golden test
(`test_determinism_is_stable_across_processes`, seed 42 / k=3) passes unchanged, and
`test_default_preset_is_v2_and_its_output_is_byte_identical` pins the equivalence across
three more (k, seed) pairs. Non-default presets tag their id/declaration name
(`bridge_chain-e3_lowdeg-k2-s4242-0`) so two presets can be materialized side by side.

---

## 2. The measured levers — where the presets came from

Not taste. `data/bank/family_leaf_calibration.jsonl` (58 bridge_chain leaves × 8 DSV2
attempts, overnight) was re-parsed back onto the knobs that produced each leaf. Overall:
mean 0.144, **18/58 in [0.25, 0.9]**, 28/58 measured 0/8.

| lever | cell | n | mean pass@8 | in band |
|---|---|---|---|---|
| right-hand function | `Real.sqrt` | 31 | **0.206** | 14/31 |
| | `Real.log` | 27 | 0.074 | 4/27 |
| step size | δ=1 | 25 | **0.210** | 11/25 |
| | δ=2 | 33 | 0.095 | 7/33 |
| left exponent sum | ≤ 4 | 22 | **0.233** | 11/22 |
| | 5–7 | 22 | 0.114 | — |
| | ≥ 8 | 14 | 0.054 | — |
| offset | `o₁ ≤ o₂` | 27 | **0.194** | 12/27 |
| | `o₁ > o₂` | 31 | 0.101 | 6/31 |
| function pair | √\|√ | 17 | **0.228** | 8/17 |
| | log\|√ | 14 | 0.179 | — |
| | √\|log | 14 | 0.116 | — |
| | log\|log | 13 | 0.029 | 1/13 |
| **combined** | δ=1 ∧ right √ | 15 | **0.283** | 9/15 |
| | es ≤ 4 ∧ δ=1 ∧ right √ | 6 | **0.438** | 5/6 |

Each lever has a mechanism, not just a correlation:

- **right-hand `√` vs `log`.** The step's witness needs the right function to be
  non-negative. `Real.sqrt_nonneg` is unconditional; `Real.log_nonneg` requires `1 ≤ M'`,
  i.e. it re-imposes the very sub-goal that research/family-v2-hardening.md §4.5 measured
  as the blocker. log|log is nearly dead (0.029) because both ends need it.
- **δ.** δ=2 makes the ring step `v²·M` and doubles the rate at which exponents grow along
  the chain, so late leaves carry much bigger monomials.
- **left exponent sum.** `1 ≤ M = x^p y^q z^r` is the measured blocker: `nlinarith`
  multiplies hypothesis *pairs*, and a three-factor product is out of reach (§4/§5 below
  reproduce this per preset).
- **offset.** `o₁ > o₂` forces the multiplicative gain to pay off the offset drop before
  it can cover anything else, so a crude bound on `F(M)` no longer suffices.

Confound worth stating: δ and exponent sum are correlated by construction (δ=2 grows
exponents faster), and c₁/d₁ marginals (c₁≥5 → 0.177 vs c₁≤4 → 0.066) are almost certainly
downstream of the congruence gate's downward walk rather than causal — so no preset moves
c₁ alone.

---

## 3. The candidate presets

A **ladder**, not four unrelated points: each adds one lever to the one above, so if the
measurement is flat between two rungs the responsible lever is identified.

| preset | knobs changed vs v2 | one-line rationale |
|---|---|---|
| `v2` | — (control) | shipped distribution; measured 0.225/0.125/0.129 at k=2/4/8, mean ~0.13, below the floor |
| `e1_sqrt` | `funcs=("sqrt",)` | √ only ⇒ the right-hand function's non-negativity is unconditional instead of re-requiring `1 ≤ M'` (0.206 vs 0.074) |
| `e2_flatstep` | + `deltas=(1,)` | one ring step per leaf and exponents grow half as fast, keeping late leaves near the measured-easy small-monomial end (0.210 vs 0.095) |
| `e3_lowdeg` | + `start_exponents=(1,0,0)` | starts at total degree 1, so `1 ≤ M` — the single measured blocker — stays a one/two-factor fact for most of the chain (es ≤ 4 → 0.233 vs 0.054 at es ≥ 8) |
| `e4_slack` | + `offset_range=(5,5)`, `coef=(2,6)`, `fcoef=(1,4)` | a fixed offset means no step ever pays an offset drop out of the multiplicative gain (0.194 vs 0.101), and the opaque √ atom carries less weight |

Notes on two of them:

- **`e3_lowdeg` renders exponent-0 factors** (`x ^ 1 * y ^ 0 * z ^ 0`). That is a knob
  value, not a rendering change — `_mono` is unchanged — and it is the only staged preset
  whose leaves are *outside* the region the calibration measured, which is why §5's local
  probe matters most for it. Its witness template needed no change (`one_le_pow₀` proves
  `1 ≤ v ^ 0`); all six probed witnesses kernel-check.
- **`e4_slack`'s fixed offset changes the sampler's dead-end set.** With nothing left to
  decrease in `o`, every `(c_min, d_min, o)` is a dead end, and a state whose only
  successors are dead ends is itself dead — so `live_states` is a greatest fixed point
  rather than v2's single excluded `_CORNER`. For v2 the fixpoint reduces exactly to
  `{(2,1,1)}`, which is why the shipped sampler's `!= _CORNER` test was correct and why
  v2's random stream is unchanged.

**Deliberately NOT staged: "drop the function term on alternating steps."** §2 of the v2
log measured BC-D (`9M + 1 ≤ 4M' + 9`, coefficient drop, no named function) as
battery-surviving, so it is a *legal* easier direction on battery grounds. It is excluded
because it violates this retune's CRITICAL constraint: it removes the second, independent
barrier and leaves the family standing on the congruence gate alone — and the v2 log is
explicit that log|log's survival is a `gcongr`-discharger accident "in a file we do not
control". Kept in the escalation list (§7) if all four presets still measure low.

### Offline structural report (`scripts/stage_retune_candidates.py`, no Lean)

| preset | leaves | k mix | leaf chars (min/med/max) | es_left (min/mean/max) | endpoint discards (mean/max) | invariant violations |
|---|---|---|---|---|---|---|
| v2 | 30 | 10/10/10 | 176/177/178 | 3 / 5.5 / 14 | 12.2 / 21 | 0 |
| e1_sqrt | 30 | 10/10/10 | 178/178/178 | 3 / 5.4 / 14 | 5.2 / 15 | 0 |
| e2_flatstep | 30 | 10/10/10 | 178/178/178 | 3 / 4.6 / 10 | 16.2 / 47 | 0 |
| e3_lowdeg | 30 | 10/10/10 | 178/178/178 | 1 / 2.6 / 8 | 14.5 / 46 | 0 |
| e4_slack | 30 | 10/10/10 | 178/178/178 | 3 / 4.6 / 10 | 3.6 / 12 | 0 |

30 distinct leaves per preset and **150 globally distinct statements** (`statement_key`
dedupe; the filter fired exactly once, on `e4_slack`, whose 19-state knob grid is the one
that can repeat a step — worth watching against FAMILIES.md's GRPO-correlation note if e4
wins, since its distinct-leaf capacity is materially lower than v2's 647). Leaf length
is flat at 176–178 chars everywhere, so **statement verbosity is held constant across the
ladder** — whatever the pod measures is the knob change, not a text-length effect. Discard
rates stay far inside the 400 cap (worst slot 47). Every preset still generates cleanly at
k=32 (`test_presets_scale_past_the_phase1_grid`).

---

## 4. Local gate — automation battery + witness kernel check

`scripts/stage_retune_candidates.py --with-battery`, `ReplPool(n_workers=2)`, 6 leaves per
preset (the min-`es_left` and max-`es_left` leaf at each k — battery risk lives at the
small-monomial end, witness risk at the far end) plus the k=8 **goal** for a V0 spot check.
Battery = `families.validate.battery_proofs()`, 10 tactics × {bare, intros-first}, 25 s cap,
**any** success kills. 720 Lean proof checks (5 presets × 7 probes × 20, plus the control)
\+ 30 witness checks in **68 s** wall.

| preset | leaves probed | battery verdict | goal (V0) | witnesses kernel-check |
|---|---|---|---|---|
| _control_ (uniformly-rising step) | 1 | **DEAD — `by intros; gcongr <;> linarith`** | — | — |
| v2 | 6 | survives 20/20 each | survives | 6/6 |
| e1_sqrt | 6 | survives 20/20 each | survives | 6/6 |
| e2_flatstep | 6 | survives 20/20 each | survives | 6/6 |
| e3_lowdeg | 6 | survives 20/20 each | survives | 6/6 |
| e4_slack | 6 | survives 20/20 each | survives | 6/6 |

**Kill table: nothing was killed; no preset is dropped.** The control is the reason that
sentence is worth anything — the script runs the known-dead v1-shape step through the same
pool and **aborts** if it survives, so "everything survives" cannot mean "the battery is
not executing" (`ControlFailed`). Full per-probe output:
`data/families/retune_battery/battery.json`; the probe inputs are
`data/families/retune_battery/<preset>.jsonl`.

Two specific worries this clears:

- `e1`/`e2`/`e4` are **√|√ on every step**, the pair that killed BC-C in the v2 log. They
  survive because the congruence gate is applied unconditionally — exactly the reason the
  v2 log gave for not making the gate conditional on the function pair. That decision is
  what makes a √-only preset legal at all.
- `e3_lowdeg`'s `y ^ 0 * z ^ 0` factors are not simplified into a soft goal by
  `simp`/`norm_num`/`aesop` (bare or intros-first), and its goals still resist V0.

---

## 5. Corridor plausibility (indicative proxy — NOT a pass rate)

The v2 log's §4.5 probe, re-run per preset: does a **short, idiomatic** proof — the shape a
prover model actually emits — exist at all? Two probes on the same 6 leaves per preset:

**(a) the blocking sub-step** `1 ≤ M` via `by intro x y z hx hy hz; nlinarith`
**(b) a 5-line idiomatic route** (`hM`, `hM2` by `nlinarith`, then one `nlinarith` with
`Real.sqrt_nonneg` / `Real.log_nonneg` / `Real.sqrt_le_self_iff` / `Real.log_le_sub_one_of_pos` hints)

| preset | (a) `1 ≤ M` closes | (b) short route closes |
|---|---|---|
| v2 | 0/6 | 0/6 |
| e1_sqrt | 0/6 | 0/6 |
| e2_flatstep | 0/6 | 0/6 |
| **e3_lowdeg** | **4/6** | **4/6** |
| e4_slack | 0/6 | 0/6 |

**(b) closes exactly when (a) closes — the sub-goal `1 ≤ M` is the whole gate**, and only
`e3_lowdeg` crosses it (at its small-monomial leaves; its two k=4/k=8 chain-tail leaves,
`x^4 y^3 z^1` and similar, still fail). This reproduces the v2 log's finding and localizes
it to one sub-step.

A third probe used the **chained** shape the measured bank proof actually used
(`have hxy : 9 ≤ x*y := by nlinarith; have hxyz : 27 ≤ x*y*z := by nlinarith; …`), on 3
leaves per preset:

| preset | k=2 head leaf | k=8 head leaf | k=8 tail leaf |
|---|---|---|---|
| v2 | CLOSES | fails | fails (`x^3 y^3 z^8`) |
| e1_sqrt | CLOSES | fails | fails (`x^1 y^4 z^9`) |
| e2_flatstep | CLOSES | **CLOSES** | fails (`x^3 y^4 z^3`) |
| e3_lowdeg | CLOSES | **CLOSES** | fails (`x^4 y^3 z^1`) |
| e4_slack | CLOSES | **CLOSES** | fails (`x^5 y^3 z^2`) |

So a short route exists at the *head* of every chain and at no chain *tail*. Read together
with §2's es-lever, this says the retune's real target is the **within-chain difficulty
gradient**, and that δ=1 (e2/e3/e4) already buys back the k=8 head leaves.

### Registered prediction (before the GPU run — §4 evidence discipline)

Projecting each staged leaf through a three-factor cell model (right function × δ ×
es-bucket) fitted on the same n=58:

| preset | projected mean pass@8 | leaves whose cell is in band |
|---|---|---|
| v2 | 0.160 | 7/30 |
| e1_sqrt | 0.243 | 15/30 |
| e2_flatstep | 0.353 | 20/30 |
| e3_lowdeg | **0.404** (20/30 leaves below the fitted es support — extrapolation) | 26/30 |
| e4_slack | 0.345 | 19/30 |

Registered: **e2/e3/e4 clear the 0.25 floor; e3_lowdeg lands nearest 0.45; e1_sqrt is
marginal.** The projection is a cell mean of ≤ 8 measured leaves per cell — a prior, not an
interval — and e3 is extrapolation by construction, which is precisely why it is measured
rather than assumed. If the pod contradicts this, the *contradiction* is the finding.

---

## 6. Decision rule for the GPU session

Applied to `data/bank/retune_calibration.jsonl` after the run. In order:

- **R0 — validity.** Ignore rows with `status == "error"` (re-run with `--repair`); a row
  with `elaborates == false` is a generator bug and blocks the preset outright.
- **R1 — level (primary, as specified).** Pick the preset whose **mean measured pass@8 is
  nearest 0.45**.
- **R2 — band fit (the operational form of "all leaves in [0.25, 0.9]").** Require
  **band-fit fraction ≥ 0.60** (share of the 30 leaves with measured pass@8 ∈ [0.25, 0.9])
  **and zero-rate ≤ 0.20** (share measured 0/8).
  *Why not the literal rule:* pass@8 from 8 samples is granular in 1/8 and noisy. A leaf
  whose true rate is 0.5 lands outside [0.25, 0.9] about 3.9% of the time, so even a
  perfectly-centred preset passes a literal "all 30 in band" only ≈30% of the time. The
  literal criterion would reject the right answer most of the time; ≥0.60 with ≤0.20 zeros
  is the same intent, measurable at n=8. **(Contract friction — flagged, not silently
  reinterpreted.)**
- **R3 — flatness must not regress.** Per-k means (k=2/4/8) within ±0.05 of each other.
  The retune exists to fix the level; buying level at the cost of the flatness that
  *already passes* is a bad trade, and §5 shows the mechanism by which it could happen.
- **R4 — tie-break.** Prefer the smaller within-chain gradient: regress measured pass@8 on
  `es_left` (both columns ship on every candidate row) and take the flatter slope. That
  slope is what decides whether flatness survives at k=16/32.

Report the numbers for **every** preset including dropped ones — a preset that measures
0.05 is as informative about the lever as one that measures 0.45.

**If no preset clears 0.25**, escalate in this order (all measured-backed, none new):
1. **§7.6 of research/family-v2-hardening.md — slim statements** (named function over a
   single *variable*, `Real.sqrt y`, not the whole monomial). Independently measured to fix
   the k=32 elaboration wall at the stock heartbeat budget (V3 in 12 s), and it removes one
   of the two scaffolds a prover must reinvent. Costs one witness line + a full re-measure
   (a shared atom changes what `gcongr` can anti-unify).
2. **FAMILIES.md direction 1 — bank-drawn leaves** from the 401 in-band statements now in
   `bank_dsv2.jsonl` (299 train / 102 eval), through `families/leaf_split.py`.
3. **BC-D (function term dropped on alternating steps)** — measured battery-safe, excluded
   here on the constraint that every preset keeps named-function content; it would need
   that constraint explicitly lifted by whoever owns FAMILIES.md.

**If a preset clears it**, re-materialize with `scripts/gen_families.py --family
bridge_chain --k-grid 2,4,8 --n 5 --validate` using the chosen preset, and only then close
Phase 1 on the number.

---

## 7. What this staging does *not* establish

1. **No pass@8 was measured.** Everything here is either the *battery floor* (measured
   locally, definitive) or a *proxy for the ceiling* (§5 hand-written routes, indicative).
   Three hand-written attempts are not eight DSV2 samples — the measured bank proof for the
   one in-band v2 leaf was a 20-line chained argument no hand probe would find.
2. **The presets share one schema and therefore one failure mode.** If DSV2 simply cannot
   do `1 ≤ x^p y^q z^r` at any p,q,r ≥ 1, then e1/e2/e4 will all measure low together and
   only e3 (and the §7.6 slim variant) can move. That is the ladder's design: a flat result
   across rungs is itself the diagnosis.
3. **The within-chain gradient is a flatness risk this retune does not remove.** Leaf
   difficulty falls with exponent sum, and exponent sum grows with chain position by
   construction (`M' > M` multiplicatively is what makes the step true), so late leaves are
   harder than early ones at every k. Flatness in k passes today because the position mixes
   at k=4 and k=8 happen to be similar; at k=16/32 the mean position keeps rising, so the
   *measured* flatness gate has not been tested where it is most likely to fail. δ=1 halves
   the growth rate (e2/e3/e4: es ≤ 3+k instead of ≤ 3+2k) and e3 lowers the intercept, but
   neither removes the trend. **Flagged for the owner of FAMILIES.md/DIRECTION §5.4a: the
   flatness gate should be re-measured at k=16 after the retune, not only at k ≤ 8.**
4. **Battery resistance is a property of *this* Mathlib.** Same caveat as the v2 log. The
   gate is re-runnable (`--with-battery`, and `test_every_preset_survives_the_battery_and_
   its_witnesses_check` as an integration test) with the positive control attached, so a
   Mathlib upgrade that softens a preset fails loudly.
5. **The projection in §5 is fitted and validated on the same 58 rows.** No held-out data
   exists. It ranks the ladder; it does not predict a value.

---

## 8. Contract friction (reported, not worked around — files not owned here)

1. **The literal decision rule "all leaves in [0.25, 0.9]" is not attainable at n=8
   samples** (§6/R2 has the arithmetic). Implemented as band-fit ≥ 0.60 with zero-rate
   ≤ 0.20; if the strategist wants the literal form, the leaf budget has to rise to ~32
   attempts per statement, which is 4× the GPU cost of this session.
2. **`data/families/bridge_chain/DATASHEET.md` and `k*.jsonl` predate the presets.** They
   are still valid v2 artifacts (v2 output is byte-identical), but they carry no `preset`
   field. Rows generated from here on do; consumers should read
   `meta.get("preset", "v2")`. Re-running `gen_families.py` is the fix and is not done here.
3. **`FAMILIES.md`'s corridor sentence gives no operational tolerance** ("closable by the
   frozen 7B leaf at pass@8 ∈ [0.25, 0.9]") — same issue as (1) one level up: it reads as a
   per-leaf hard constraint but is only measurable as a distribution. Worth one sentence in
   FAMILIES.md.
4. **`gen_families.py` cannot select a preset.** It calls `gen(k, seed, n)`, so materializing
   a non-default preset needs a `--preset` passthrough (one argparse flag + one kwarg) in a
   file this task does not own. Until then the staged candidates are the only preset
   artifacts.
5. **Both `research/family-bridge-chain.md` (v1) and `research/family-v2-hardening.md` are
   now upstream of a third state** (v2 = preset `"v2"`). The v2 log's §7.1 open item ("the
   corridor's ceiling is unmeasured … it needs it for bridge_chain first") has since been
   *measured and failed*; a one-line pointer from that file to this one and to the
   OVERNIGHT flatness verdict would keep the chain readable.
6. **The 58-row calibration is partial** (58 of 138 staged leaves; case_tree unmeasured).
   The lever table in §2 is therefore fitted on bridge_chain only, and cells hold 3–8
   leaves each. Re-fitting it on the retune run's 150 rows is nearly free and should be the
   first thing the next session does with the data.
