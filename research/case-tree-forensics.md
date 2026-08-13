# case_tree measurement forensics (F1)

Owner: this task only. Touches no other file. Source data:
`data/bank/family_leaf_calibration.jsonl` (68 `case_tree` rows, 8 DeepSeek-Prover-V2-7B
attempts each) joined against a fresh re-generation with
`rlmath.families.case_tree` (seed 42). Measurement date of the underlying bank: pre-existing
(overnight run referenced in HANDOFF.md); this file only re-analyzes it — no new Lean/GPU
calls were made.

**Headline: saturation is real but does not hide a usable lever. The 68-leaf population has
genuine heterogeneity (Beta-Binomial SD ≈ 0.14 in true rate, rejecting a single global rate at
p ≈ 5×10⁻¹²), but of every knob the schema exposes, only `variant` (max/min) separates
in-band from saturated leaves at significance (Fisher p = 0.0009), and even isolating pure-max,
high-curvature, high-slack leaves — stacking every weakly-suggestive direction at once — only
reaches mean pass@8 ≈ 0.79–0.83, nowhere near the 0.45 target. The proof taxonomy shows one
strategy family (three surface encodings of "characterize the √ bound, then `nlinarith` with
squared-difference hints") covering all 68 leaves, with the non-default encodings appearing
*only* on the easiest tier. This is the generator's own witness read back, exactly as
hypothesized. A schema change (H1–H4) is forced, not merely preferred.**

---

## 1. Method: regenerate-and-join, not regex

Regex-parsing the 68 `prop` strings back onto knobs (the orchestrator's approach) works but
throws away provenance. Instead: `rlmath.families.case_tree.layout(k, seed, idx)` was called
for `k ∈ {2,4,8}`, `seed=42`, `idx ∈ [0, 200)`, and every leaf's exact `prop` string (via the
module's own `_leaf_prop`) was used as a join key against the 68 calibration rows.

**All 68 matched at seed 42** (0 misses) — strong evidence this is in fact the seed used to
build the candidate pool (`data/families/family_leaves_candidates.jsonl`) the calibration ran
against. That pool's `id` field (`case_tree-k2-70` … `case_tree-k8-137`) is **not** a generator
index — it is a flat counter over a combined bridge_chain+case_tree candidate list (bridge_chain
occupies ids 0–69, case_tree continues 70–137) — so the source-id suffix cannot be read as
`idx`. The join therefore has to go through the prop string, as the task brief anticipated.

**A subtlety the join surfaced and had to be resolved:** re-searching for each of the 68 props
across `k ∈ {2,4,8}` finds **multiple valid generator preimages for 53/68 leaves** (a leaf
statement produced at, e.g., `k=4, idx=155` is byte-identical to one produced at a different
`k`/`idx`). This is *expected* given the schema (§6 below quantifies why) and it is **not** a
threat to the geometric features: for every leaf with >1 preimage found, all preimages agreed
on knobs and variant with **zero disagreements** (verified directly — piece geometry is exactly
recoverable from the rendered text: `lo`/`hi` are literal substrings, and `(a, m, pad)` are
algebraically invertible from the expanded radicand's three coefficients, so identical text
⟺ identical piece). What is *not* recoverable is which `k` the leaf "belongs to" in a
regeneration sense — **17/68 leaves matched a different `k` than their `source_id` tag claims**.
The calibration file's own `k`-tag (parsed from `source_id`) is used as the ground-truth
`k` throughout this report (it reflects how the measurement was actually organized: 10/19/39
leaves at k=2/4/8, matching the orchestrator's numbers exactly); all knob/geometry features come
from the regenerated match, which is provably k-invariant.

**Sanity check against the orchestrator's numbers** — recomputing every marginal from the joined
data reproduces them exactly: curvature 0.933/0.910/0.925, width 0.905/0.939, offset
0.890/0.940/0.944, slack 0.943/0.899, variant 0.872/0.988, k 0.850/0.974/0.917. The join is
correct.

---

## 2. Is flat-marginal-at-0.92 a saturation artifact? Quantified.

Observed `n_verified` histogram (68 leaves, 8 attempts each): `{2:1, 3:1, 4:1, 5:3, 6:6, 7:6,
8:50}`. Mean pass@8 = 0.923.

### 2.1 A single global true rate is rejected

Fit a homogeneous-Binomial(8, p) model by MLE: p̂ = 0.9228. Goodness-of-fit on pooled bins
(≤5 / 6 / 7 / 8, pooled because the tail bins are sparse):

| bin | observed | expected under p̂=0.923 |
|---|---|---|
| ≤5 | 6 | 1.30 |
| 6 | 6 | 7.01 |
| 7 | 6 | 23.93 |
| 8 | 50 | 35.76 |

χ² = 36.17, df = 2, **p ≈ 1.4×10⁻⁸**. A single true rate for all 68 leaves is decisively
rejected — the low bins (2,3,4,5/8) are ~5× overrepresented relative to what one shared rate
would produce, and the 7/8 bin is underrepresented. There is real heterogeneity in the
population, not just binomial noise around one number.

### 2.2 Beta-Binomial fit: heterogeneity is real, and its size

Fitting a Beta-Binomial (Binomial(8,p), p ~ Beta(α,β)) by grid MLE: **α=2.48, β=0.20**, giving
implied population mean true-rate = **0.925** and implied **SD of true rate across leaves ≈
0.138**. Fit quality (expected vs observed counts): 8/8→49.5 (obs 50), 7/8→8.5 (obs 6), 6/8→4.2
(obs 6), ≤5/8→3.9 (obs 6) — visibly closer than the homogeneous fit. Likelihood-ratio test
against the homogeneous model: **LR = 47.6, df=1, p ≈ 5×10⁻¹²**. The heterogeneity is not
subtle; it is the dominant feature of the data.

### 2.3 How large an effect could n=8 have hidden?

Per-leaf Bayesian posterior on true rate (flat Beta(1,1) prior, so this is a lower-information
bound on precision, not using the population fit above):

| observed | posterior median | 90% credible interval |
|---|---|---|
| 8/8 | 0.926 | **[0.717, 0.994]** |
| 7/8 | 0.820 | [0.571, 0.959] |
| 6/8 | 0.714 | [0.450, 0.902] |
| 5/8 | 0.607 | [0.345, 0.831] |
| 4/8 | 0.500 | [0.251, 0.749] |

**Answer to "how large a knob effect could the data have hidden":** among the 50 leaves that
scored 8/8, individual true rates anywhere from ~0.72 to ~0.99 are all consistent with what was
observed — a **~0.27-wide band of true difficulty is invisible at n=8** once a leaf is already
easy. A knob that moved true pass rate by less than ~0.25–0.3 *within the already-easy region*
would not show up in this bank at all.

**But** §2.2 shows the population is *not* just noise around 0.92 — there is a real ≈0.14-SD
spread, which is exactly what would make ~18/68 leaves land in [0.25,0.9] "for real" rather than
by chance (a homogeneous p=0.92 population would put essentially 0 leaves that low — expected
count in the ≤5/8 pooled bin was 1.3, observed was 6, itself evidence some of the low scorers are
not chance draws). So: **saturation masks the exact position of easy leaves within the top ~0.27
of the scale, but it does not manufacture the 18-leaf corridor population out of nothing — some
of that population is a real, harder tail.** The question in §3 is whether that real tail tracks
any usable generator knob.

---

## 3. What separates the 18 in-band leaves from the 50 saturated ones?

In-band = pass@8 ∈ [0.25, 0.9] (i.e. `n_verified` ∈ {2..7}, 18 leaves). Saturated = pass@8 = 1.0
(`n_verified`=8, 50 leaves). No leaf scored 0/8 or 1/8, so this partition is exhaustive and the
two groups above already cover it, matching the corridor definition in FAMILIES.md exactly.

Mann-Whitney U (two-sided normal approximation, tie-corrected) on every recoverable numeric
feature:

| feature | in-band mean | saturated mean | in-band median | saturated median | p |
|---|---|---|---|---|---|
| k (source_id) | 6.22 | 5.92 | 8 | 8 | 0.65 |
| width | 6.89 | 7.08 | 6 | 8 | 0.49 |
| curvature (a) | 1.83 | 1.80 | 2 | 2 | 0.86 |
| offset | -0.17 | -0.08 | 0 | 0 | 0.66 |
| slack | 0.50 | 0.44 | 0.5 | 0 | 0.66 |
| cap (t) | 6.28 | 6.20 | 6 | 6 | 0.75 |
| pad (e) | 8.39 | 7.92 | 9 | 8 | 0.66 |
| d (margin) | 32.78 | 32.56 | 32 | 32 | 0.75 |
| far (max radius) | 4.17 | 4.14 | 4 | 4 | 0.87 |
| \|vertex\| (\|m\|) | 10.17 | 10.96 | 5 | 10 | 0.62 |
| max\|coeff\| (own radicand) | 301.6 | 334.7 | 56 | 207 | 0.61 |
| prop length (chars) | 69.0 | 68.6 | 69 | 69 | 0.83 |
| **outer_const** | **8.61** | **5.84** | 9 | 5.5 | **0.0013** |

Every knob the generator exposes as an independent difficulty axis (width, curvature, offset,
slack, and the derived cap/pad/d/far/position/coefficient-magnitude quantities) is **not
significant at any reasonable threshold** — this replicates the orchestrator's "flat marginals"
finding leaf-by-leaf with an actual test, not eyeballing, and extends it: even `max|coeff|`,
which spans two orders of magnitude in this sample (leaves with own-radicand coefficients from
single digits to 700+, because coefficient magnitude is the one quantity the docstring says
*should* grow with band position/k), shows **no relationship to difficulty** — its median is
even a bit *lower* for the harder (in-band) group. `k` itself is flat too (χ² = 3.79, df=2,
p=0.15, on the 3×2 contingency table k∈{2,4,8} × in-band/saturated) — a positive finding for the
family's structural soundness (the corridor split doesn't drift with k even at leaf grain), but
it means k is not a source of extra difficulty variance to exploit either.

**`outer_const` is significant, but it is not an independent knob** — `outer_const = C_LEVEL +
cap` (max variant) or `cap - C_LEVEL` (min variant), a deterministic function of `cap` (itself
flat, p=0.75) and `variant`. It is downstream of variant, not a separate lever.

### 3.1 `variant` is the one real signal

2×2 table (variant × in-band), Fisher's exact test:

| | in-band | saturated | total | in-band rate |
|---|---|---|---|---|
| max | 16 | 22 | 38 | **42.1%** |
| min | 2 | 28 | 30 | **6.7%** |

**Fisher exact two-sided p = 0.00094**, odds ratio ≈ 10.2. This is the single strongest
within-schema signal found anywhere in this analysis. Mean pass@8 by variant: max 0.872, min
0.988 (reproduces the orchestrator's number). No confound was found: curvature, width, offset,
slack, cap, and k are all statistically indistinguishable between the two variant groups (the
one nominal difference, min-variant leaves running *bigger* own-coefficients on average — 403 vs
265 — cuts the *wrong* way for a magnitude-driven story, since min is the *easier* group).

**Mechanistic read:** both variants reduce to the identical fact `√u ≤ cap` (max: `C ≤ A - √u ⟺
√u ≤ A-C`; min: `√u - n ≤ C ⟺ √u ≤ C+n`), so this is not a difference in mathematical content —
it is a difference in *surface form*. `min`'s goal literally reads `Real.sqrt(u) - n ≤ C`, a
direct "sqrt-expression compared to a constant" shape; `max`'s reads `C ≤ A - Real.sqrt(u)`, an
extra layer of subtraction between the model and the pattern it needs to recall. Consistent with
the idiom-recall thesis in the task brief: **the model is more reliable at pattern-matching one
surface arrangement of the identical fact than the other.**

### 3.2 How far could stacking every hard-looking direction go?

Isolating cells that combine every direction with *any* (non-significant) hint of being harder:

| cell | n | mean pass@8 |
|---|---|---|
| max & curvature=3 & slack=1 | 3 | 0.79 |
| max & slack=1 | 18 | 0.83 |
| max & offset=-1 | 13 | 0.82 |
| max & cap≤6 | 28 | 0.90 |
| **overall max-only** (measured) | 38 | 0.872 |

The hardest identifiable combination (n=3, so noisy) still lands at 0.79. **No combination of the
existing knob support reaches anywhere near 0.45** — the gap from the best stacked cell (~0.79)
to the target (0.45) is larger than the gap from the unfiltered mean (0.92) to that same stacked
cell.

---

## 4. Proof taxonomy: how many strategies are there, really?

All 68 `first_proof` fields parse cleanly (every leaf that was ever solved has a recorded
`first_proof`). Signature = (uses `sqrt_le_iff`, uses `sq_sqrt`, uses `sqrt_nonneg`):

| signature | count | in-band | in-band rate |
|---|---|---|---|
| `sqrt_le_iff` + `sqrt_nonneg` (no `sq_sqrt`) | **53** | 16 | 30.2% |
| `sqrt_le_iff` only (no `sqrt_nonneg`, no `sq_sqrt`) | 9 | 2 | 22.2% |
| `sq_sqrt` + `sqrt_nonneg` (no `sqrt_le_iff`) | 5 | **0** | **0%** |
| `sqrt_nonneg` only (neither) | 1 | 0 | 0% |

100% use `nlinarith`; 100% use `sq_nonneg` hints; mean 9.8 proof lines; mean 2.87 `nlinarith`
calls per proof — flat between in-band and saturated groups (9.06 vs 10.08 lines, 3.00 vs 2.82
nlinarith calls — no signal, consistent with §3's finding that verbosity doesn't track
difficulty).

**There is exactly one functional strategy, in three superficial encodings.** All 68 proofs
characterize the same fact — the radicand is squeezed against `cap` — either via
`Real.sqrt_le_iff.mpr ⟨_, _⟩` (the generator's own witness shape, 62/68) or via the algebraically
equivalent `Real.sq_sqrt` squaring identity plus a shotgun of `sq_nonneg` hints for `nlinarith`
to search over (5/68, one example threw **24** `sq_nonneg` hints at a single call). **The
non-default encodings appear only on already-saturated leaves — 0/5 and 2/9 in-band vs 30.2% for
the main cluster** — i.e. they are not a second, more powerful strategy that reaches harder
leaves; they are a *looser* fallback that only succeeds where the problem is easy enough not to
need precision. This is exactly the pattern predicted by "the model has memorized the
generator's own template": on the leaves the template covers cold, it reproduces it almost
verbatim (`sqrt_le_iff.mpr` + one/two `nlinarith` calls, occasionally dropping the redundant
`sqrt_nonneg` step the generator's real witness never uses either); everywhere else, it either
finds a looser paraphrase that happens to still be easy, or it fails.

A representative harder-tier (in-band) proof and a representative easy-tier non-default proof,
side by side, make the "same template, different confidence" pattern visible:

```
-- in-band (pass_rate 0.75), main cluster, near-verbatim generator template
by
  intro x hx1 hx2
  have h₁ : 0 ≤ Real.sqrt (2 * x ^ 2 + 8 * x + 21) := by apply Real.sqrt_nonneg
  have h₂ : Real.sqrt (2 * x ^ 2 + 8 * x + 21) ≤ 8 := by
    apply Real.sqrt_le_iff.mpr
    constructor
    · nlinarith
    · nlinarith [sq_nonneg (x + 2), sq_nonneg (x - 1)]
  nlinarith [sq_nonneg (x + 2), sq_nonneg (x - 1), sq_nonneg (x + 7)]

-- saturated (pass_rate 1.0), sq_sqrt fallback, huge coefficients (150x + 1876), 24 hints
by
  intro x hx1 hx2
  have h₁ : 0 ≤ Real.sqrt (3 * x ^ 2 + 150 * x + 1876) := by apply Real.sqrt_nonneg
  have h₂ : Real.sqrt (3 * x ^ 2 + 150 * x + 1876) ^ 2 = 3 * x ^ 2 + 150 * x + 1876 := by
    rw [Real.sq_sqrt] <;> nlinarith [sq_nonneg (x + 25), sq_nonneg (x + 5)]
  nlinarith [sq_nonneg (x + 25), sq_nonneg (x + 5), sq_nonneg (x + 21), sq_nonneg (x + 29), …]
```

The second proof's coefficients are ~10–100× the first's and it still lands 8/8 — direct,
concrete confirmation of §3's `max|coeff|` null result.

---

## 5. Is there any within-schema knob move that could plausibly reach 0.45?

**The strongest case for "yes":** `variant` is a real, significant, sizeable effect (Fisher
p=0.0009, OR≈10 on the corridor-membership question) — the only one found. One could argue the
calibration only probed a narrow slice of the parameter space (`WIDTHS={6,8}`,
`CURVATURES={1,2,3}`, `VERTEX_OFFSETS={-1,0,1}`, `SLACKS={0,1}` — small integer ranges by
design), and that widening any of these (curvature to 10+, offsets to ±5, wider domains pushing
`|m|` much larger at high k) might expose a real gradient the current narrow support simply
doesn't reach — the classic "haven't looked outside the box" objection.

**Why it does not survive contact with the data in hand:**

1. **Magnitude already varies 100×+ within the sampled range and shows nothing.** `|m|` and
   `max|coeff|` are not narrowly clustered in this sample — they range from single digits to the
   700s (driven by cumulative band position, which *does* grow with domain size / `k` by
   construction, per the module docstring). If magnitude were a lever, it should show up as a
   gradient across this range already; instead the correlation runs slightly the wrong way
   (§3, §4's worked example). Extending the range further extrapolates a trend that isn't there.
2. **Stacking every weakly-suggestive direction only reaches ~0.79** (§3.2), and that's the
   *ceiling* of what's achievable by recombining existing knob values, not a floor with more
   room below it — `variant` alone is the whole story, and its full range (0.872 pure-max vs
   0.988 pure-min) is already exhausted by the measured data.
3. **The proof taxonomy (§4) shows the memorized template operates at the level of *shape*, not
   *magnitude*.** All three encodings key off "there is exactly one `Real.sqrt` applied to a
   quadratic, compared to a constant" — a structural pattern invariant under every knob this
   schema has (width/curvature/offset/slack/cap all change *coefficients inside* that shape, not
   the shape). This is the same reasoning the docstring already used to explain why v1→v2 needed
   a shape change (bare quadratic → `√`-wrapped quadratic), not a distribution retune within v1.
   Retuning knobs inside v2 changes numbers inside the same shape a second time; nothing in this
   analysis suggests that will land differently than it did for v1's coefficients.
4. **Bridge_chain's own retune (research/retune-notes.md) is the contrastive case, and it
   worked with a knob ladder because it changed the *reachability* of a structurally different
   sub-goal** (`1 ≤ x^p y^q z^r`, es-bucket controlled which of a genuinely different obstacle a
   proof had to clear). case_tree has no analogous internal obstacle: the whole leaf is one
   `√(quadratic) ≤ t` fact with nothing else in it. There is no second gate to retune the
   reachability of.

**Answer: a schema change is forced.** The forensics point at the same conclusion the module
docstring already reached for v1→v2, one level up: the corridor needs a shape the memorized
`sqrt_le_iff`/`sq_sqrt`-plus-`nlinarith` template does not directly close — H1 (two-atom sum,
forcing an invented budget split `t1+t2=t` that is not template-covered) is the most
directly supported candidate by this analysis specifically because it breaks the *single-atom*
assumption every one of the 68 measured proofs relies on, rather than perturbing a number inside
that assumption.

---

## 6. Why the knob support can't carry a gradient: the schema's content space is small

A secondary, mechanistic finding that explains §3's flat marginals rather than just observing
them. Sampling `layout(k, 42, idx)` for `idx ∈ [0, 1000)` and collecting distinct
`(variant, lo, hi, a, m, d)` tuples:

| k | leaf draws | distinct pieces | % unique |
|---|---|---|---|
| 2 | 2,000 | 288 | 14.4% |
| 4 | 4,000 | 1,041 | 26.0% |
| 8 | 8,000 | 2,888 | 36.1% |

And the growth decelerates — at k=8, distinct-piece count vs. draws: 500 probs → 2,194 distinct;
1,000 → 2,888 (+694); 2,000 → 3,398 (+510); 4,000 → 3,723 (+325); 8,000 → 3,974 (+251). Each
doubling of sampling effort adds fewer new distinct leaves — a coupon-collector saturation curve,
meaning **the true leaf-content space at k=8 tops out on the order of a few thousand distinct
statements**, not an open-ended distribution. This is *why* 53/68 measured leaves have multiple
generator preimages (§1): the knob support (`CURVATURES × VERTEX_OFFSETS × SLACKS` = 3×3×2 = 18
combinations per band position, and band positions themselves cluster near the domain center
because `WIDTHS` only takes 2 values) is genuinely narrow. A retune that only reshuffles
probabilities over this same small, already-exhausted set cannot manufacture a difficulty
gradient that isn't there in the set itself — which §3 already shows it isn't.

This also bears on FAMILIES.md's leaf-disjointness / GRPO-correlation note (effective dataset
size ≈ distinct-leaf count, not problem count): this schema's distinct-leaf capacity is much
smaller than a naive "widths × curvatures × offsets × slacks × k" count would suggest, because
most of that support collapses onto a handful of actually-distinct near-center bands. Any
successor schema should re-measure this saturation curve before assuming its own knob support is
wide.

---

## 7. Flags (contract friction / caveats)

1. **The candidate pool's `id` field is not a generator index.** `case_tree-k2-70` etc. is a flat
   counter over a combined bridge_chain+case_tree list, not `(k, seed, idx)`. Anyone re-deriving
   knobs from `family_leaf_calibration.jsonl` in the future should regenerate-and-join by prop
   string (as this file did), not parse the id suffix as an idx.
2. **`source_id`'s `k`-tag and the regenerated match's `k` disagree on 17/68 leaves.** This is
   expected given §6 (leaf content is not k-unique) and does not affect any geometric/knob
   feature (proven invariant across preimages), but it means "which k a given leaf statement
   belongs to" is not a well-defined question at the statement level for this schema — only at
   the problem level. Reported as an observation, not a defect: it is a *direct consequence* of
   the flat-in-k design (leaf content is drawn from one k-independent distribution, so k-crossing
   collisions are exactly what "flat in k" predicts when the support is this narrow).
3. **No new Lean/GPU measurement was made here.** Every number in §2–§6 is a re-analysis of the
   existing 68-row bank plus free local re-generation (no LM, no REPL calls beyond what was
   already banked). §5's "schema change forced" conclusion is an extrapolation from that data,
   not a new pod-measured fact — consistent with the retune-notes playbook's staging discipline
   (register the direction now; the pod session measures it).
