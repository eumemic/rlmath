# Family B — case trees (`case_tree`): design log

Built 2026-08-11 against FAMILIES.md (Phase 1, DIRECTION.md §5.4–5.5). Every
number below is **measured** against the local Lean 4 + Mathlib toolchain
(`lean v4.34.0-rc1`, `ReplPool(n_workers=2)`, the standard `PREAMBLE`), not
argued. Code: `src/rlmath/families/case_tree.py`; tests:
`tests/test_family_case_tree.py`.

---

## 1. What the family emits

A single quantified statement whose natural proof splits into k cases:

```
∀ x : ℝ, L ≤ x → x ≤ R → 3 ≤ max (max (q₁ x) (q₂ x)) (max (q₃ x) (q₄ x))
```

Each `qᵢ` is a **concave quadratic in expanded form** (`-a x² + b x + c`). Each
one dips below 3 somewhere in `[L, R]`, so no single piece proves the goal; the
super-level sets `{qᵢ ≥ 3}` cover `[L, R]`, so a k-way interval split does.
There is a dual variant (`min`, sampled per problem): convex pieces, upper
bound `min (…) ≤ 3`.

Leaf i (the invented content):

```
∀ x : ℝ, lᵢ ≤ x → x ≤ rᵢ → 3 ≤ -a x² + b x + c
```

Assembly (flat, depth 1 for every k):

```
intro x hx0 hxR
rcases le_or_gt x (-9) with c1 | c1
· exact le_max_of_le_left (le_max_of_le_left (hb1 x hx0 c1))
rcases le_or_gt x (-1) with c2 | c2
· exact le_max_of_le_left (le_max_of_le_right (hb2 x c1.le c2))
rcases le_or_gt x 7 with c3 | c3
· exact le_max_of_le_right (le_max_of_le_left (hb3 x c2.le c3))
exact le_max_of_le_right (le_max_of_le_right (hb4 x c3.le hxR))
```

`rcases le_or_gt x t with c | c` leaves two goals; the focused `·` closes the
in-band one and the block continues at the same indentation on the other, so
tactic-block depth is 1 for every k (nested `rcases` would indent 32 levels deep
at k=32).

Witness proof, identical for every leaf and every k:

```
by intro x hl hr; nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]
```

The product hint `(x − lᵢ)(rᵢ − x) ≥ 0` turns `x²` into a linear term, after
which the band bound is a linear consequence — so the *witness* is a one-liner
while the *statement* is not linear-arithmetic-closable. That asymmetry is the
whole trick: the generator knows the proof by construction (FAMILIES.md
self-certification) without the leaf being cheap for automation.

---

## 2. Battery kill-lists — the empirical loop

`validate.AUTOMATION_TACTICS` = `simp, aesop, norm_num, omega, decide, linarith,
positivity`, 25 s each, **any** success fails V0/V5.

Probes were scratch scripts (not committed); each datum is
`backend.check(leancode.proof_check(prop, f"by {tactic}"))` for every tactic in
`AUTOMATION_TACTICS`, i.e. exactly what `validate._resists_automation` does. The
props are reproduced in full below so any row can be re-run.

### Round 1 — candidate directions (2026-08-11)

| candidate | prop | battery verdict |
|---|---|---|
| ℕ interval band, linear | `∀ n : ℕ, 4 ≤ n → n ≤ 9 → 3 * n ≤ 30` | **DEAD — omega, decide** |
| ℕ residue, divisibility | `∀ n : ℕ, n % 5 = 3 → 5 ∣ n + 2` | **DEAD — omega** |
| ℕ bounded ∀ | `∀ n : ℕ, n < 12 → n * n ≤ 121` | **DEAD — decide** |
| ℕ interval band, quadratic | `∀ n : ℕ, 4 ≤ n → n ≤ 9 → n * n ≤ 81` | **DEAD — decide** |
| ℝ interval band, linear | `∀ x : ℝ, 2 ≤ x → x ≤ 6 → 3 ≤ 4 * x - 5` | survives (but see round 2) |
| **ℝ interval band, concave quadratic** | `∀ x : ℝ, 2 ≤ x → x ≤ 6 → 3 ≤ -2*x^2 + 16*x - 20` | **survives** |
| **ℝ interval band, convex quadratic** | `∀ x : ℝ, 2 ≤ x → x ≤ 6 → 2*x^2 - 16*x + 26 ≤ 3` | **survives** |
| ℤ residue, quadratic | `∀ n : ℤ, n % 5 = 3 → (5:ℤ) ∣ n^2 + 1` | survives |
| ℝ band, monotone power | `∀ x : ℝ, 0 ≤ x → x ≤ 1 → x^5 ≤ x^2` | survives |
| ℝ band, sqrt | `∀ x : ℝ, 4 ≤ x → x ≤ 9 → 2 ≤ Real.sqrt x` | survives |
| goal, max-of-3-quadratics (k=3) | — | **survives** |
| goal, min-of-3-quadratics (k=3) | — | **survives** |

**Conclusion that decided the family.** Candidate direction 1 (modular splits)
and the ℕ form of direction 2 (interval splits over ℕ) are *not viable leaf
schemas*: `decide` discharges any bounded-ℕ band through Mathlib's bounded-∀
decidability instances for ℕ — including the nonlinear `n * n ≤ 81` — and
`omega` discharges linear-plus-`%` divisibility outright. The
prompt's warning that "each residue class needs a different Mathlib fact, NOT an
omega-closable arithmetic identity" is confirmed and is in fact stronger than
stated: over ℕ it is not enough to be non-omega, you must also escape `decide`,
which rules out *every* band with a finite integer domain. Direction 3
(piecewise `max`/`min`) over **ℝ** is the survivor, and that is what shipped.

### Round 2 — the self-imposed intro-first battery

The contract battery runs each tactic on the *closed* prop. None of the seven
introduces the leading `∀`/`→`, so a leaf can survive V5 simply by being
quantified. That is a property of the validator, not of the task, and this
family declines to exploit it. Re-running the same battery after
`intro x hl hr`:

| prop | intro-first verdict |
|---|---|
| `∀ x : ℝ, 2 ≤ x → x ≤ 6 → 3 ≤ 4 * x - 5` | **DEAD — linarith** |
| `∀ x : ℝ, 2 ≤ x → x ≤ 6 → 3 ≤ -2*x^2 + 16*x - 20` | survives |
| `∀ x : ℝ, 2 ≤ x → x ≤ 6 → 2*x^2 - 16*x + 26 ≤ 3` | survives |
| `∀ x : ℝ, 0 ≤ x → x ≤ 1 → x^5 ≤ x^2` | survives |
| `∀ x : ℝ, 4 ≤ x → x ≤ 9 → 2 ≤ Real.sqrt x` | survives |
| k=3 goal, `max` variant | survives |
| k=3 goal, `min` variant | survives |

This is why the pieces are **quadratic and not affine**. The affine version
passes the shipped contract and would have produced a clean validator table
while being a `linarith` one-liner for any leaf prover — precisely the
"experiment measures tactic dispatch" failure DIRECTION §5.4(c) is guarding
against. Under the stronger battery the shipped leaves still hold, so widening
`AUTOMATION_TACTICS` later (FAMILIES.md: "extending this list strengthens every
family retroactively") does not silently invalidate a bank generated today.

This check is committed, not just logged:
`test_leaves_resist_the_intro_first_battery_live` (integration-marked) re-runs
the intro-first battery against *generated* goals and leaves at k=2 and k=32 —
6 props × 7 tactics, all surviving.

Also settled in round 2, against the actual Mathlib in the container:

- `le_or_lt` **does not exist** (`Unknown identifier`); `le_or_gt` and
  `lt_or_ge` do. The assembly uses `rcases le_or_gt x t with c | c`, whose
  second branch `c : x > t` yields the next band's lower bound as `c.le`.
  (`lt_or_ge` type-mismatches — its first branch is strict on the wrong side.)
- `le_max_of_le_left/right` and `min_le_of_left_le/right_le` all exist and are
  the right glue for injecting a per-band fact into a nested extremum.
- Negative numerals need parentheses in *application* position: `le_or_gt x -9`
  parses as a subtraction and fails; `le_or_gt x (-9)` is the split point. Found
  by elaborating generated assemblies, not by reading the parser.

---

## 3. Three design bugs the loop caught

**(a) `decide` is stronger than expected over ℕ.** The original plan had an ℕ
interval split as the primary schema (cheap numerals, obvious bands). It died on
the first probe. Every subsequent choice — ℝ rather than ℕ, quadratic rather
than affine — is downstream of that measurement.

**(b) A k-case costume over a (k−1)-case problem.** First implementation sampled
each piece's vertex with an offset `δ ∈ {−1,0,1}` from its band midpoint and a
slack margin `s ∈ {0,1}`, and tiled bands of width `w ∈ {2,4}`. A piece's
super-level set reaches past its own band by

```
spill = |δ| + sqrt(far² + s/a) − w/2 = 2·|δ| + ε,   ε < 0.24,  far = w/2 + |δ|
```

— **independent of the band width**. With `w = 2` a single offset neighbour
therefore swallows an entire adjacent band, making that leaf redundant: the goal
is still true, the plan still checks, the validator still passes, and the "k-case
split" is quietly a (k−1)-case split. Nothing in V0–V6 detects this. First fix
was a repair pass that tightened the greedy neighbours; it worked, but
`leaf_stats()` showed the *repair rate itself* drifting with k —
0.25 / 0.28 / 0.34 / 0.45 / 0.56 at k = 2 / 4 / 8 / 16 / 32 — which is a
per-node-flatness leak (FAMILIES.md scaling requirement: leaves at k=32 must come
from the same distribution as at k=2). Real fix: `min(WIDTHS) = 6 > 2 × 2.24`,
which makes necessity **structural** (each band's midpoint, an integer since
widths are even, is provably covered by no other piece). Measured repair rate is
now `0.0` at every k, so the knob distribution is exactly k-independent. The
repair code stays as a tripwire for future knob changes; a test asserts it never
fires.

**(c) A Θ(k²) assembly, i.e. a token-count confound in the k-axis itself.** The
extremum was first built right-nested (`max q₁ (max q₂ (…))`), which puts leaf i
at depth i, so injecting its fact into the root costs i copies of
`le_max_of_le_right (`. Measured composed-artifact size, right-nested vs the
shipped **balanced** tree:

(all at seed 5; `leancode.compose` of the oracle plan with its witnesses)

| k | goal chars | artifact, right-nested | artifact, balanced | balanced assembly | ≈ tokens |
|---|---|---|---|---|---|
| 2 | 78 | 534 | 534 | 132 | 0.1 k |
| 8 | 282 | 2 724 | 2 488 | 932 | 0.6 k |
| 32 | 1 121 | 19 254 | **11 498** | 5 237 | 2.9 k |
| 128 | 4 641 | 207 146 | **52 286** | 26 664 | 13 k |
| 512 | 19 415 | 2 897 714 | **234 822** | 129 668 | 59 k |

The root policy has to *emit* the assembly, so a Θ(k²) glue term would make the
size axis partly measure token copying rather than decomposition — precisely the
confound the experiment exists to avoid. A balanced tree puts every leaf at depth
⌈log₂ k⌉ and the assembly at Θ(k log k). It also happens to make the family's
name literal. Side effect worth stating plainly: this *shrinks* the artifact, so
the "full proof text exceeds the window" tier of DIRECTION §5.4(e) now arrives at
k ≈ 512 (≈ 59 k tokens) rather than k ≈ 128. Reaching it earlier by keeping a
quadratic glue term would have been inflating the criterion with redundant
tokens, not with mathematical content.

The generator also raises rather than emits if any piece fails `covers_band`
(exact integer check `a·far² ≤ d` — no floating point anywhere in the truth
argument), and `tests/test_family_case_tree.py::test_every_case_is_necessary`
re-checks necessity for k ∈ {2,3,4,8,16} × 6 seeds × 2 indices offline.

---

## 4. Visibility (V6) — what is legitimately in the goal

The prompt allows partial visibility of the case structure via
`meta["visible_lemmas"]`. **This family uses none: `visible_lemmas == []`, and
every leaf passes V6 unexempted.**

What is unavoidably visible: the piecewise function itself — a statement about
`max (q₁ x) (… q_k x)` has to name the pieces. What is *not* visible, and is
what the policy must produce:

1. **The k band endpoints.** The pieces are in *expanded* form, so a piece's
   vertex is not readable off the goal without completing the square. The
   crossing points `qᵢ(x) = 3` sit at `m ± sqrt(d/a)`: measured over 600 sampled
   pieces, **50.5% are irrational** (the `slack = 1` half) and the rest are
   integral. Even for the integral ones the band is not the crossing interval —
   vertices are offset from band midpoints by `δ ∈ {−1,0,1}`, so "band =
   interval centred on the vertex" is wrong, and the policy must pick endpoints
   that both sit inside each piece's super-level set and tile the domain.
2. **The per-band claim** — a bound that holds on that band and nowhere stated.

No leaf prop is a substring of the normalized goal, because every leaf carries
band hypotheses (`lᵢ ≤ x → x ≤ rᵢ`) that appear nowhere in it. Only the outer
domain endpoints `L, R` are shared, and only with the first and last leaves,
which still differ on their other bound. Tested offline at every k
(`test_no_leaf_is_a_substring_of_the_goal_and_nothing_is_exempt`).

Where a policy *can* cheat cheaply: it may pick a different but valid split
(different band endpoints), and the plan check will accept it. That is correct
behaviour — the family scores *a* valid decomposition, not the generator's.

---

## 5. Per-node flatness in k

The leaf schema has one fixed knob support, independent of k:
`WIDTHS × CURVATURES × VERTEX_OFFSETS × SLACKS = {6,8} × {1,2,3} × {−1,0,1} × {0,1}`.
k changes only *how many* bands tile the domain. `leaf_stats()` (10 problems per
k, seed 101):

| k | leaves | leaf prop len mean | min | max | goal len mean | max abs coeff | repaired |
|---|---|---|---|---|---|---|---|
| 2 | 20 | 51.9 | 47 | 55 | 83 | 60 | 0.0 |
| 4 | 40 | 52.3 | 46 | 57 | 147 | 360 | 0.0 |
| 8 | 80 | 54.1 | 45 | 60 | 278 | 2 142 | 0.0 |
| 16 | 160 | 56.1 | 48 | 60 | 558 | 8 702 | 0.0 |
| 32 | 320 | 57.3 | 45 | 63 | 1 120 | 36 911 | 0.0 |

Leaf statement length grows **10.4% from k=2 to k=32** while the leaf count grows
16×. The residual growth has exactly one source, stated honestly: the band's
*absolute position*. The domain is `[−T/2, T/2]` with `T = Σ widths ≈ 7k`, so a
piece's constant coefficient scales like `a·m²` and gains digits. The domain is
centred on 0 rather than starting at 0 specifically to halve this. The proof
certificate is position-invariant (the same `nlinarith` hint, the same linear
combination), so difficulty should be flat even though the numerals are not
identical; that is a claim about the *leaf prover*, and it gets settled by the
measured bank pass rates after the bake-off, not here.

The `goal` grows linearly in k (83 → 1 120 chars) and the composed artifact
slightly faster (§3c). That is intrinsic to case trees — a k-case goal encodes k
pieces — and is the mechanism by which the top of the k-grid eventually exceeds a
single context (DIRECTION §5.4(e)); on the measured curve that tier lands around
k ≈ 512.

`test_scales_past_the_phase1_grid` builds k=128: 128 leaves, single-line goal,
127 `rcases`, flat assembly (no indentation growth — the focused-dot pattern
keeps depth at 1 for all k, unlike nested `rcases`).

---

## 6. Measured validator table

### 6.1 The specified grid — n = 3 per k ∈ {2,4,8}, `check_automation=True`

Seed 1000, `ReplPool(n_workers=2)`, `timeout_s=180`. Counts are `passed/total`
**per check instance** — V2/V5/V6 fire once per leaf, so their totals scale
with k.

| check | k=2 | k=4 | k=8 |
|---|---|---|---|
| structure | 3/3 | 3/3 | 3/3 |
| V1 goal elaborates | 3/3 | 3/3 | 3/3 |
| V0 goal resists automation | 3/3 | 3/3 | 3/3 |
| V2 leaf stmt elaborates | 6/6 | 12/12 | 24/24 |
| V2 leaf witness kernel-checks | 6/6 | 12/12 | 24/24 |
| V3 plan check | 3/3 | 3/3 | 3/3 |
| V4 oracle replay (kernel+sanitizer+axioms) | 3/3 | 3/3 | 3/3 |
| V5 leaf resists automation | 6/6 | 12/12 | 24/24 |
| V6 hidden intermediate | 6/6 | 12/12 | 24/24 |
| **problems fully valid** | **3/3 (100%)** | **3/3 (100%)** | **3/3 (100%)** |
| median wall-clock / problem | 0.6 s | 1.2 s | 3.9 s |

**Discard rate: 0/9 (0%).** No regeneration loop is needed or implemented — the
generator is correct by construction (exact integer coverage) rather than by
rejection sampling, so there is nothing to discard. Target was ≥90%
post-discard; measured is 100% pre-discard. Total run: 31.9 s.

### 6.2 Wider sweep — same validator, more samples and a bigger k

n = 12/12/12/6/3 for k = 2/4/8/16/32, seed 2000 (disjoint from §6.1). 45
problems, 384 leaves, 285.8 s total.

| check | k=2 | k=4 | k=8 | k=16 | k=32 |
|---|---|---|---|---|---|
| structure | 12/12 | 12/12 | 12/12 | 6/6 | 3/3 |
| V1 goal elaborates | 12/12 | 12/12 | 12/12 | 6/6 | 3/3 |
| V0 goal resists automation | 12/12 | 12/12 | 12/12 | 6/6 | 3/3 |
| V2 leaf stmt elaborates | 24/24 | 48/48 | 96/96 | 96/96 | 96/96 |
| V2 leaf witness kernel-checks | 24/24 | 48/48 | 96/96 | 96/96 | 96/96 |
| V3 plan check | 12/12 | 12/12 | 12/12 | 6/6 | 3/3 |
| V4 oracle replay | 12/12 | 12/12 | 12/12 | 6/6 | 3/3 |
| V5 leaf resists automation | 24/24 | 48/48 | 96/96 | 96/96 | 96/96 |
| V6 hidden intermediate | 24/24 | 48/48 | 96/96 | 96/96 | 96/96 |
| **problems fully valid** | **100%** | **100%** | **100%** | **100%** | **100%** |
| median wall-clock / problem | 0.5 s | 1.3 s | 3.7 s | 11.5 s | 44.5 s |

**54/54 problems across both runs, 0 discards.** Notably V2_proof is 96/96 at
k=32: the single `nlinarith` witness template holds at five-digit coefficients,
so the by-construction proof does not degrade as bands move away from the
origin. Wall-clock is dominated by the battery (7 tactics × (1 goal + k leaves)
per problem); a validation run without `check_automation` is ~10× faster.

### 6.3 Reading the table honestly

- V0 and V5 passing is *not* a timeout artifact. At k=8 a whole problem —
  82 Lean commands, 56 of them battery runs — completes in ~4 s wall-clock on
  2 workers, i.e. ~100 ms per battery tactic against a 25 s cap. The tactics
  genuinely fail; none is being cut off.
- 100% is what a by-construction generator *should* score, and it is weak
  evidence on its own — it mostly says the construction has no bugs. The
  load-bearing evidence for this family is §2 (the battery kill-lists that ruled
  out the ℕ directions and the affine pieces) and §5 (flatness), not the fact
  that the shipped schema passes.
- What the table does **not** measure: whether a real leaf prover can close
  these leaves at a useful rate, and whether that rate is flat in k. That is
  DIRECTION §5.4(a)/(b) and needs the leaf bake-off.

---

## 7. Known limitations / future work

- **One leaf schema.** Everything is a quadratic band. Measured-viable
  extensions that would widen the leaf distribution without touching the
  assembly: monotone-power bands (`x^5 ≤ x^2` on `[0,1]`) and `Real.sqrt` bands
  both survive the intro-first battery (§2). They were left out to keep the
  shipped distribution single-schema and therefore trivially flat; adding them
  means re-measuring the table, since the mixture must be identical at every k.
- **`abs` pieces** (`A − a·|x − m|`) fit the same assembly but state the vertex
  `m` in the goal, which gives away the band structure the expanded quadratics
  hide. Rejected on invention grounds, not on battery grounds.
- **Modular splits are unbuilt, not unexplored.** The one residue leaf that
  survives the battery is nonlinear (`∀ n : ℤ, n % 5 = 3 → 5 ∣ n^2 + 1`), which
  needs a per-residue witness template (`obtain ⟨q, hq⟩ : ∃ q, n = 5*q+3`, subst,
  `ring_nf`) rather than one uniform one-liner. That is the natural second split
  type for this family if `ZMod`-flavoured content is wanted.
- **The necessity certificate is integer-pointwise.** `not _redundant(i)`
  exhibits an *integer* point of band i that no other piece covers. It is
  sufficient for necessity and exact, but it is not a proof that the real
  interval is uncovered; a piece could in principle be necessary only on an
  interval containing no integer, and would be (conservatively) treated as
  redundant. Under the shipped knobs this never arises.
- **Difficulty calibration is not done here.** V5 says the leaves resist seven
  tactics; it does not say a leaf prover solves them at a useful rate.
  DIRECTION §5.4(a) wants measured per-node pass rates, which needs the leaf
  bake-off (task #9).

---

## 8. Contract friction found while building against it

Reported, not worked around — these live in files this family does not own.

1. **`rlmath.families.__init__` does not import family submodules**, so
   `REGISTRY` is empty until someone does `import rlmath.families.case_tree`.
   `register()` at module scope only fires on import. Whatever
   `scripts/gen_families.py` ends up being has to import the family modules
   explicitly (or the package has to import them).
2. **`core.plan_format.MAX_LEMMAS_HARD = 64` caps the policy-emittable k at 64.**
   This family generates and oracle-replays k=128 fine (oracle plans are
   constructed, not parsed), but a *policy* could never emit the matching
   128-lemma plan — `parse_plan` raises "more than 64 lemmas". FAMILIES.md asks
   that the schema not break at k=128; the schema doesn't, the wire format does.
   Pinned by `test_wire_format_lemma_cap_bounds_the_policy_emittable_k`.
3. **The V0/V5 battery cannot get past a leading binder.** None of the seven
   tactics introduces `∀`/`→`, so any quantified leaf passes V5 regardless of
   content — a linear real band passes V5 and dies to `intro; linarith`. This
   family compensates by self-imposing the intro-first battery (§2), but the
   cheap general fix would be for `_resists_automation` to also try
   `intros <;> <tactic>`. That is a validator change, and validate.py is not
   this family's file.
