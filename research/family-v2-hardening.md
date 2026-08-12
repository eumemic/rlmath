# Family v2 — hardening the synthetic leaves against the FULL battery

Phase 1 of DIRECTION.md §5.5, iteration A of FAMILIES.md's **fallback direction 2**
("hardened synthetic steps: mix named-function content into ladder steps / band claims so
raw polynomial arithmetic doesn't suffice; re-measure"). Every number below was
**measured** on the local `ReplPool(n_workers=2)` (Mathlib @ lean v4.34.0-rc1, standard
`PREAMBLE`), never argued. 2026-08-12.

Modules: `src/rlmath/families/bridge_chain.py`, `src/rlmath/families/case_tree.py` ·
tests: `tests/test_family_bridge_chain.py`, `tests/test_family_case_tree.py` ·
superseded v1 logs: `research/family-bridge-chain.md`, `research/family-case-tree.md`.

---

## 0. Verdict

Both families clear the **full** battery with generator-known witnesses.

| family | **n=3 per k ∈ {2,4,8}** (the required grid) | wide n=8 per k ∈ {2,4,8} | scaling n=2, k=16 | k=32 |
|---|---|---|---|---|
| bridge_chain | **9/9 (100%)** | **24/24 (100%)** | **2/2** | **0/2 — elaborator limits, §4.3** |
| case_tree | **9/9 (100%)** | **24/24 (100%)** | **2/2** | **2/2** |

FAMILIES.md's fallback direction 2 **works for both skeletons** on the required grid, so
bank-drawn leaves (direction 1) remain a *widening* option rather than a necessity for
Phase 1's k-axis. Two things v2 does **not** settle, both stated at length below rather
than buried:

- **The corridor's ceiling is unmeasured** — whether the frozen DSV2-7B leaf closes these
  at pass@8 ∈ [0.25, 0.9]. The battery gives the floor; the ceiling needs a bank
  measurement. Highest-risk open item (§7.1). The indicative local probe (§4.5) is
  **encouraging for case_tree** (four short idiomatic routes into a leaf) and **a warning
  for bridge_chain** (zero — only the shipped 14-line witness closed it).
- **bridge_chain's checkable grid shrank from k=32 to k=16** as a direct cost of the
  hardening: longer leaf props blow PREAMBLE's `maxHeartbeats 400000` in V3/V4 while every
  individual leaf still checks. A regression against v1. Raising the heartbeat budget is
  **measured insufficient** (past ~800 000 the error becomes `maxRecDepth`, and unlimited
  heartbeats still fails); **slimming the leaf statements is measured sufficient** — V3 at
  k=32 then passes at the stock budget in 12 s, and that fix lives inside this family's
  own file. §4.3/§4.4/§7.6; it is the recommended next iteration, deliberately not
  half-landed here.

---

## 1. What v1 did and why it died

Both v1 schemas passed the *original* 7-tactic battery and then failed the strengthened
one (10 tactics × {bare, intros-first}, 20 proof attempts per prop). Re-materialization
under the strengthened battery, seed 42, n=5, k ∈ {2,4,8}: **bridge_chain 6/15 valid**
(16 leaf-kills), **case_tree 0/15** (70/70 leaf-kills). V0 held everywhere at every k —
the skeletons and the k-axis were never the problem, only leaf *content*.

### v1 bridge_chain (superseded) — "monomial ladder over ℝ"

    aᵢ = cᵢ * x^pᵢ * y^qᵢ * z^rᵢ + dᵢ            c ∈ [2,9], d ∈ [1,9], (p,q,r)₀ = (1,1,1)
    hᵢ : ∀ x y z : ℝ, 3 ≤ x → 3 ≤ y → 3 ≤ z → aᵢ₋₁ ≤ aᵢ

**Kill: all 16 to `intros; gcongr <;> linarith`.** `gcongr` anti-unifies the two sides of
`≤` and emits one side goal per differing position — here `c₁ ≤ c₂`, `M ≤ M'`, `d₁ ≤ d₂`
— and the `<;> linarith` discharger closes every one of them whenever the coefficients
rise together. v1 gated exactly this route *at the endpoints* (`endpoints_resist_naive_collapse`)
and never ran it against an individual step. Reproduced here in 0.6 s:

| prop | battery verdict |
|---|---|
| `∀ x y z : ℝ, 3 ≤ x → 3 ≤ y → 3 ≤ z → 4·xyz + 3 ≤ 6·x²yz + 7` | **DEAD — `intros; gcongr <;> linarith`** |

### v1 case_tree (superseded) — "expanded quadratic bands under max/min"

    qᵢ x = −a x² + b x + c        (concave; dual `min` variant is convex)
    hbᵢ : ∀ x : ℝ, lᵢ ≤ x → x ≤ rᵢ → 3 ≤ −a x² + b x + c
    witness: by intro x hl hr; nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]

**Kill: all 70 to `intros; nlinarith`, and it is structural, not incidental.**
`nlinarith`'s preprocessing multiplies *pairs* of hypotheses; after `intros` the
hypotheses are `lᵢ ≤ x` and `x ≤ rᵢ`, whose product `(x − lᵢ)(rᵢ − x) ≥ 0` **is** the hint
v1's witness passed in by hand. The witness template and the killing tactic were the same
argument. Reproduced on four leaves straight out of the v1 generator (0.1–0.2 s each):

| prop (generated, seed 1000) | battery verdict |
|---|---|
| `∀ x : ℝ, -7 ≤ x → x ≤ 1 → 3 ≤ -2x² - 12x + 17` | **DEAD — `intros; nlinarith`** |
| `∀ x : ℝ, 1 ≤ x → x ≤ 7 → 3 ≤ -3x² + 24x - 17` | **DEAD — `intros; nlinarith`** |
| `∀ x : ℝ, -15 ≤ x → x ≤ -7 → x² + 22x + 108 ≤ 3` | **DEAD — `intros; nlinarith`** |
| `∀ x : ℝ, 1 ≤ x → x ≤ 9 → x² - 12x + 14 ≤ 3` | **DEAD — `intros; nlinarith`** |
| v1 k=2 `max` **goal** (same pieces) | survives — V0 was never the problem |

**Rule extracted, and it is the general lesson for synthetic leaves:** *if the witness is
one automation call plus a hint the tactic's own preprocessing generates, the leaf is
dead.* The fix is not a better hint, it is a leaf whose witness needs a **rewriting step
the battery does not attempt**. Both v2 schemas are built on that sentence.

---

## 2. The empirical loop — kill-list per candidate

Probe = `theorem _proof_check : <prop> := by <p>` for every `p` in
`validate.battery_proofs()` (10 tactics × {bare, `intros;`} = 20 Lean calls per prop),
25 s cap, **any** success kills the candidate. Every candidate that survived was also
handed its intended witness and kernel-checked in the same pass, so "survives" never
means "unprovable".

### Round 1 — direction-finding (2026-08-12)

`M = x^1 y^1 z^1`, `M' = x^2 y^1 z^1`, binder `∀ x y z : ℝ, 3 ≤ x → 3 ≤ y → 3 ≤ z →`.

| # | candidate step | battery verdict | witness |
|---|---|---|---|
| BC-v1 | `4M + 3 ≤ 6M' + 7` (v1 shape, all coefficients rising) | **DEAD — `intros; gcongr <;> linarith`** | — |
| BC-A | `9M + 2√M ≤ 4M' + 7√M'` (same fn, **c drops** 9→4) | survives | OK |
| BC-B | `4M + 2 log M ≤ 9M' + 7√M'` (**fn mismatch**, all rising) | survives | OK |
| BC-C | `4M + 2√M ≤ 9M' + 7√M'` (same fn, nothing drops) | **DEAD — `intros; gcongr <;> linarith`** | — |
| BC-D | `9M + 1 ≤ 4M' + 9` (v1 shape, **c drops**, no named fn) | survives | — |
| BC-E | `9M + 2√M ≤ 4M' + 7 log M'` (fn mismatch + c drops) | survives | OK |
| BC-F | `4M + 2 log M ≤ 9M' + 7 log M'` (log|log, nothing drops) | survives | — |
| CT-A | `∀ x : ℝ, -3 ≤ x → x ≤ 3 → 3 ≤ 9 - √(2x² - 4x + 6)` | survives | OK |
| CT-B | `∀ x : ℝ, -3 ≤ x → x ≤ 3 → √(2x² - 4x + 6) - 3 ≤ 3` | survives | OK |

Three findings decided both schemas:

1. **`Real.sqrt` and `Real.log` are opaque to the whole battery.** `linarith`/`nlinarith`
   treat `Real.sqrt (…)` as an atom with no connecting hypothesis, `positivity` only
   proves `0 ≤ e`-shaped goals, and `simp`/`aesop`/`norm_num` do not find the
   monotonicity route. That is what makes named-function content the right hardening.
2. **`gcongr` *does* know both functions**, so wrapping both sides in the same function is
   not by itself protection — BC-C died exactly like BC-v1. `Real.sqrt_monotone` is
   `@[gcongr]` with **no side condition**, which is why `√|√` dies; `Real.log_le_log` is
   also `@[gcongr]` but carries `0 < x`, and gcongr's side-goal discharger (positivity /
   assumption) cannot establish `0 < x^p·y^q·z^r` for symbolic reals — which is the *only*
   reason BC-F survived. That is a discharger accident in a file we do not control, so v2
   does not rely on it: the congruence gate is applied to every step regardless of the
   function pair.
3. **The load-bearing property against `gcongr` is a strictly decreasing coefficient**
   (BC-A/BC-D survive, BC-C dies), because it makes one of gcongr's side goals *false*
   for every template. BC-D also shows, honestly, that a coefficient-drop gate alone
   would have repaired v1's bridge leaves with no named functions at all — the named
   functions buy leaf-distribution width and a second, independent barrier, not the
   minimum fix.

### Round 2 — knob coverage for the case_tree cap

Same probe over the whole shipped knob support, including a far-from-origin band (the
k≈32 regime) and the degenerate corners:

| candidate | verdict | witness |
|---|---|---|
| `3 ≤ 9 - √(2x² + 12x + 22)` on `[-7,1]` (a=2, t=6, e=4) | survives | OK |
| `3 ≤ 7 - √(x² - 10x + 25)` on `[1,7]` (a=1, t=4, **e=0**) | survives | OK |
| `√(3x² + 66x + 364) - 4 ≤ 3` on `[-15,-7]` (a=3, t=7, e=1) | survives | OK |
| `√(x² - 8x + 16) - 2 ≤ 3` on `[1,9]` (a=1, t=5, **e=0**) | survives | OK |
| `3 ≤ 9 - √(3x² - 624x + 32457)` on `[101,107]` (far band) | survives | OK |
| `√(x²) ≤ 3` on `[-3,3]` (a=1, m=0, **e=0**) | survives | OK — but rejected, see below |

The two `e=0` rows and the `m=0` row survive the battery and prove fine, and were still
**rejected on invention grounds, not battery grounds**: with `e = 0` the radicand is a
perfect square `a(x−m)²` (for `a = 1`, one `ring_nf` from `√((x−m)²) = |x−m|` via
`Real.sqrt_sq_eq_abs`), and with `m = 0` on top of that it degenerates to the bare
`a·x²` — which states the vertex, i.e. the band's centre, the thing the policy is
supposed to invent. The expanded rendering hides a perfect square from `simp`, so this
is a leak to a *prover that normalises*, which is exactly the prover we are building for.
The shipped `_cap()` therefore picks the smallest `t` with `t² > d` (strict), forcing
`e = t² − d ≥ 1`; `test_cap_forces_a_strictly_positive_radicand_pad` pins it.

---

## 3. Shipped v2 schemas

### 3.1 bridge_chain v2 — named-function monomial ladder

    aᵢ  =  cᵢ * Mᵢ  +  dᵢ * Fᵢ(Mᵢ)  +  oᵢ         Mᵢ = x^pᵢ * y^qᵢ * z^rᵢ
    c ∈ [2,9]   d ∈ [1,9]   o ∈ [1,9]   F ∈ {Real.sqrt, Real.log} iid per term
    step: multiply M by v^δ, v ∈ {x,y,z}, δ ∈ {1,2}; resample (c, d, o, F)

    goal  ∀ x y z : ℝ, 3 ≤ x → 3 ≤ y → 3 ≤ z → a₀ ≤ a_k
    hᵢ    ∀ x y z : ℝ, 3 ≤ x → 3 ≤ y → 3 ≤ z → aᵢ₋₁ ≤ aᵢ
    asm   intro x y z hx hy hz
          exact (le_trans (le_trans (h1 …) (h2 …)) (le_trans (h3 …) (h4 …)))  -- no term text

**The `le_trans` fold is balanced, and that change was forced by a measurement.** v1's
right-nested fold puts step i at depth i. v2's leaf props carry two extra function
applications each, and at k=32 that combination tipped **V3 (`plan_check`) and V4
(`oracle_replay`) over PREAMBLE's `maxHeartbeats 400000`** —
`(deterministic) timeout at «synthesize pending MVars»` and `… at whnf` — while all 32
leaves still checked individually (v1's k=32 passed both with the same fold and smaller
terms; the extra term size is what tipped it). A balanced fold puts every step at depth
⌈log₂ k⌉, uses the same k−1 `le_trans` applications, still contains no term text, and
brings k=32 back inside budget (§4.3). This is the same Θ(k²)→Θ(k log k) elaboration
lesson case_tree learned in v1, arriving at bridge_chain one schema later. Pinned by
`test_the_le_trans_fold_is_balanced` (offline, k up to 128).

Three gates, all offline (no Lean in the loop):

| gate | condition | why |
|---|---|---|
| SAMPLING CONSTRAINT (`_valid`) | `c₂·3^δ − (c₁ + d₁) ≥ max(0, o₁ − o₂)` | exactly when the step is a `linarith` over the four atoms `M, M', F₁(M), F₂(M')` — the witness is search-free |
| CONGRUENCE GATE (`step_resists_congruence`) | at least one of `c, d, o` strictly drops | negation of gcongr's success condition (§2, BC-C vs BC-A) |
| ENDPOINT GATE (`endpoints_resist_naive_collapse`) | `c_k < c₀ ∧ d_k ≤ d₀ ∧ o_k ≤ o₀` | v1's measured gate, extended to the new coefficient; kills the "`M₀ ≤ M_k` + a bound on `M₀`" route family |

The congruence gate is applied **unconditionally**, i.e. stricter than the measurement
demands (only `√|√` steps needed it). Making it conditional on the drawn function pair
would make the `(c,d,o)` distribution depend on the function draw for no measured gain.

One corner of the knob grid, `(c,d,o) = (2,1,1)`, has no legal successor under the gate
(nothing can drop below the floor of all three ranges), so it is excluded from the sample
space; every other state has ≥ 7 legal successors, so the sampler cannot stall. Pinned by
`test_the_gate_corner_is_excluded_from_the_sample_space`.

Witness (search-free; one shape, two function-dependent lines):

```
intro x y z hx hy hz
have hbase : (3:ℝ) ^ δ ≤ v ^ δ := by gcongr <;> linarith      -- first: context is still small
have hpow  : (3^δ:ℝ) ≤ v ^ δ := by linarith [hbase]
have hp0/hp1/hp2 : (1:ℝ) ≤ x ^ p / y ^ q / z ^ r := one_le_pow₀ (by linarith)
have hA    : (1:ℝ) ≤ x^p * y^q := le_trans hp0 (le_mul_of_one_le_right (by linarith) hp1)
have hM    : (1:ℝ) ≤ M        := le_trans hA  (le_mul_of_one_le_right (by linarith) hp2)
have hstep : 3^δ * (M) ≤ v ^ δ * (M) := mul_le_mul_of_nonneg_right hpow (by linarith)
have hring : v ^ δ * (M) = M' := by ring
rw [hring] at hstep
-- upper bound on the LEFT function, non-negativity of the RIGHT one:
have hfu : Real.sqrt (M) ≤ M      := Real.sqrt_le_self_iff.mpr (Or.inr hM)
   -- or: Real.log (M) ≤ M - 1    := Real.log_le_sub_one_of_pos (by linarith)
have hfl : (0:ℝ) ≤ Real.sqrt (M') := Real.sqrt_nonneg _
   -- or: (0:ℝ) ≤ Real.log (M')   := Real.log_nonneg (by linarith [hM, hstep])
linarith [hM, hstep, hfu, hfl]
```

The final `linarith` certificate is
`c₂M' + d₂F₂(M') + o₂ − (c₁M + d₁F₁(M) + o₁) ≥ (c₂3^δ − c₁ − d₁)·M − (o₁ − o₂) ≥ 0`,
using `M ≥ 1` — which is precisely the sampling constraint. **No `nlinarith` anywhere**:
that was v1's lesson about PREAMBLE's `maxHeartbeats` at k=32, and it survives into v2.

### 3.2 case_tree v2 — `Real.sqrt`-capped quadratic bands

    qᵢ x = Aᵢ − Real.sqrt(aᵢ x² + bᵢ x + cᵢ)      max variant, Aᵢ = C + tᵢ
    qᵢ x = Real.sqrt(aᵢ x² + bᵢ x + cᵢ) − nᵢ      min variant, nᵢ = tᵢ − C

    goal  ∀ x : ℝ, L ≤ x → x ≤ R → C ≤ max (max (q₁ x) (q₂ x)) (max (q₃ x) (q₄ x))
    hbᵢ   ∀ x : ℝ, lᵢ ≤ x → x ≤ rᵢ → C ≤ qᵢ x

The radicand is the positive-definite `aᵢ(x − mᵢ)² + eᵢ` with `eᵢ ≥ 1`, written expanded.
`tᵢ = _cap(dᵢ)` is the least integer with `t² > d`, and `eᵢ = tᵢ² − dᵢ`.

**The geometry is untouched from v1.** Because `√u ≤ t ⟺ u ≤ t²` exactly (both sides
non-negative, and the radicand is positive definite so `Real.sqrt`'s junk value at
negative arguments is never reached), the piece satisfies the goal's inequality at `x`
iff `aᵢ(x − mᵢ)² ≤ dᵢ` — v1's condition, verbatim. So `holds_at`, `covers_band`,
`_redundant`, `_repair_necessity`, the balanced extremum tree, the flat `rcases` assembly
and all the necessity tests carry over unchanged and still use **no floating point in the
truth argument**. Only the claim's surface syntax moved.

Witness, one template for every leaf and every k:

```
intro x hl hr
have hb : Real.sqrt (u) ≤ t := Real.sqrt_le_iff.mpr
  ⟨by norm_num, by nlinarith [mul_nonneg (sub_nonneg.mpr hl) (sub_nonneg.mpr hr)]⟩
linarith
```

This is the exact line FAMILIES.md draws: `nlinarith`-with-hints inside a **witness** is
fine; the leaf is dead only if bare `intros; nlinarith` closes it. Here it does not,
because the band product cannot reach through the `Real.sqrt` atom — the prover must
first *find the rewriting step* (`Real.sqrt_le_iff` or equivalent) that the battery never
attempts. v1's one-call witness and v1's killer were the same tactic; v2's are not.

**`Real.log` was measured as a case_tree cap and rejected**, for a soundness reason
rather than a battery reason: `log u ≤ t` has no exact integer characterisation, so a
piece's true super-level set would be strictly larger than the integer certificate
believes. The necessity argument (`not _redundant(i)` exhibits a point only piece i
covers) would then be wrong in the *unsafe* direction — the generator could ship a k-leaf
plan that is secretly a (k−1)-leaf plan. `√` keeps the certificate exact.

---

## 4. Measured validator tables

`validate_problem(..., check_automation=True)`, real `ReplPool(n_workers=2)`,
`timeout_s=240`. Counts are **passing checks / total checks** (V2/V5/V6 fire once per
leaf, so their totals scale with k).

### 4.1 The specified grid — n=3 per k ∈ {2,4,8}

**bridge_chain**, seed 2026, balanced fold (15.0 s / 33.2 s / 65.2 s wall for k=2/4/8;
the right-nested fold measured 16.0 / 48.3 / 85.3 s on the same problems — the fold change
is a validation-cost win at every k, not only a k=32 rescue):

| check | k=2 | k=4 | k=8 |
|---|---|---|---|
| structure | 3/3 | 3/3 | 3/3 |
| V1_goal_elaborates | 3/3 | 3/3 | 3/3 |
| V0_goal_resists_automation | 3/3 | 3/3 | 3/3 |
| V2_stmt[leaf] | 6/6 | 12/12 | 24/24 |
| V2_proof[leaf] | 6/6 | 12/12 | 24/24 |
| V3_plan_check | 3/3 | 3/3 | 3/3 |
| V4_oracle_replay | 3/3 | 3/3 | 3/3 |
| V5_leaf_resists[leaf] | 6/6 | 12/12 | 24/24 |
| V6_hidden[leaf] | 6/6 | 12/12 | 24/24 |
| V6b_hidden_term | 3/3 | 9/9 | 21/21 |
| **problems fully passing V0–V6** | **3/3 (100%)** | **3/3 (100%)** | **3/3 (100%)** |

**case_tree**, seed 1000 (2.9 s / 56.1 s / 91.3 s):

| check | k=2 | k=4 | k=8 |
|---|---|---|---|
| structure | 3/3 | 3/3 | 3/3 |
| V1_goal_elaborates | 3/3 | 3/3 | 3/3 |
| V0_goal_resists_automation | 3/3 | 3/3 | 3/3 |
| V2_stmt[leaf] | 6/6 | 12/12 | 24/24 |
| V2_proof[leaf] | 6/6 | 12/12 | 24/24 |
| V3_plan_check | 3/3 | 3/3 | 3/3 |
| V4_oracle_replay | 3/3 | 3/3 | 3/3 |
| V5_leaf_resists[leaf] | 6/6 | 12/12 | 24/24 |
| V6_hidden[leaf] | 6/6 | 12/12 | 24/24 |
| **problems fully passing V0–V6** | **3/3 (100%)** | **3/3 (100%)** | **3/3 (100%)** |

(case_tree emits no `hidden_terms`: it is a structural-split family with no term-shaped
secret, so V6b does not fire — FAMILIES.md explicitly allows this and the family relies
on its own necessity tests instead.)

### 4.2 Wide sweep — n=8 per k, disjoint seeds

**bridge_chain**, seed 7001 — 24 problems, 112 leaves. Measured with the right-nested
fold (45.9 s / 95.8 s / 223.9 s for k=2/4/8); k=2 and k=4 were re-run with the shipped
balanced fold (42.8 s / 90.7 s, same 8/8) and the k=8 re-run was cut for machine time.
The fold changes only V3 and V4, both of which already passed 8/8 under the *more*
expensive nesting, so the verdict does not depend on the re-run:

| check | k=2 | k=4 | k=8 |
|---|---|---|---|
| structure · V1 · V0 · V3 · V4 | 8/8 each | 8/8 each | 8/8 each |
| V2_stmt / V2_proof / V5 / V6 (per leaf) | 16/16 each | 32/32 each | 64/64 each |
| V6b_hidden_term | 8/8 | 24/24 | 56/56 |
| **problems fully valid** | **8/8** | **8/8** | **8/8** |

**case_tree**, seed 7002 (15.7 s / 28.9 s / 66.5 s) — 24 problems, 112 leaves:

| check | k=2 | k=4 | k=8 |
|---|---|---|---|
| structure · V1 · V0 · V3 · V4 | 8/8 each | 8/8 each | 8/8 each |
| V2_stmt / V2_proof / V5 / V6 (per leaf) | 16/16 each | 32/32 each | 64/64 each |
| **problems fully valid** | **8/8** | **8/8** | **8/8** |

Combined with §4.1: **66/66 problems, 0 failures, across 4 seeds** — ≈4 150 individual
Lean checks per family over §4.1+§4.2 (33 problems, 154 leaves; ~90% of the calls are
battery attempts, 20 per prop).

### 4.3 Beyond the required grid — n=2 per k ∈ {16,32}, and where the ceiling is

| family | k=16 | k=32 |
|---|---|---|
| bridge_chain (seed 7003) | **2/2 valid** (130.7 s) | **0/2 — V3 and V4 exceed `maxHeartbeats 400000`** |
| case_tree (seed 7004) | **2/2 valid** (37.6 s) | **2/2 valid** (134.9 s) |

case_tree's k=16/32 run is clean on every check instance, not just at the problem level:

| check | k=16 | k=32 |
|---|---|---|
| structure · V1 · V0 · V3 · V4 | 2/2 each | 2/2 each |
| V2_stmt / V2_proof / V5 / V6 (per leaf) | 32/32 each | 64/64 each |

**case_tree v2 scales to k=32 cleanly; bridge_chain v2 does not.** The asymmetry is leaf
text size: a case_tree leaf is 60–79 characters, a bridge_chain leaf 176–190, and V3
carries all k of them in one binder list. case_tree's k=32 wall clock (134.9 s for 2
problems, i.e. ~67 s each) is also ~1.5× v1's 44.5 s — the `√` cap is not free, just
affordable. Note that V2_proof is 64/64 at k=32, so the `Real.sqrt_le_iff` +
band-`nlinarith` witness template still holds at five-digit radicand coefficients.

**The bridge_chain k=32 failure is a *checking* ceiling, not a schema break, and it is a
real regression against v1 that must be stated plainly.** At k=32 every one of the 32
leaves elaborates and its witness kernel-checks; what fails is `V3_plan_check`
(`(deterministic) timeout at «synthesize pending MVars»`) and `V4_oracle_replay`
(`… at whnf`) — the two artifacts that carry all k lemma props at once. v1's k=32 passed
both; v2's leaf props are ~80% longer (177 vs 98 chars) and carry two extra function
applications each, and 32 of them in one binder list is what exhausts the budget.

The balanced fold (§3.1) was tried as the fix and is **not sufficient**: it cut validation
cost 25–30% at k ≤ 8 and is kept for that, but k=32 still fails, so the cost is dominated
by elaborating the k binders rather than by the fold's nesting depth.

Consequences, in order of how much they matter:

1. **The v2 bridge_chain grid is `k ≤ 16` under the current PREAMBLE.** The Phase-1
   required grid is {2,4,8} and is unaffected; DIRECTION §5.5's Phase-3 eval grid
   {8,32,64,128} is affected and needs one of the fixes below before k=32 bridge problems
   can be materialized with an oracle ceiling.
2. **It is a live-episode hazard, not just a validator one.** `plan_check` is stage 1 of
   the harness, so a *correct* policy plan at k=32 would be recorded as `PLAN_INVALID` —
   an infrastructure limit misclassified as a policy failure, which is exactly what
   DIRECTION §6's status separation exists to prevent.
3. **Three fixes — and §4.4 measured which one actually works:**
   (a) raise `maxHeartbeats` in `core/leancode.PREAMBLE` or per-check — **measured
   insufficient**: past ~800 000 the error becomes `maxRecDepth`, and unlimited
   heartbeats still fails;
   (b) **slim the leaf text (§7.6's single-variable function argument) — measured
   sufficient: V3 at k=32 passes at the stock budget in 12 s.** Lives entirely inside
   this family's file. This is the recommended next iteration;
   (c) accept `k ≤ 16` for bridge_chain and let case_tree (clean to k=32, §4.3) carry the
   top of the grid — the status quo this iteration ships.

### 4.4 How far over budget — measured heartbeat requirement

Diagnostic: the *same* code `leancode.plan_check` / `compose` emit, prefixed with
`set_option maxHeartbeats N in`. The shipped `PREAMBLE` is untouched; this only measures
what the next iteration would have to buy. "SLIM" = the §7.6 variant, i.e. the named
function applied to a single **variable** (`Real.sqrt x`) instead of the whole monomial,
substituted into the statements only.

| k | artifact | stock 400 000 | 800 000 | 1 600 000 | 3 200 000 | 0 (unlimited) |
|---|---|---|---|---|---|---|
| 16 | V3 plan_check | **OK** (11 s) | — | — | — | — |
| 16 | V4 compose | **OK** (30 s) | — | — | — | — |
| 16 | V3, SLIM statements | **OK** (3 s) | — | — | — | — |
| 32 | V3 plan_check | FAIL (16 s) | FAIL (31 s) | FAIL (37 s) | FAIL (38 s) | **FAIL** (37 s) |
| 32 | V3, SLIM statements | **OK (12 s)** | — | — | — | — |

**Two findings here, and the second overturns the obvious fix.**

1. **Raising `maxHeartbeats` does not rescue k=32.** Past ~800 000 the error *changes*:
   the wall clock plateaus at ~37 s and Lean reports `maximum recursion depth has been
   reached (set_option maxRecDepth)`, not a heartbeat timeout — and it still says that at
   `maxHeartbeats 0` (unlimited). So bridge_chain at k=32 sits against **two** stacked
   elaborator limits, and §4.3's fix (a) buys only the first. Anyone tempted to bump the
   PREAMBLE constant should know it is not sufficient.
2. **Slimming the leaf statements clears k=32 at the *stock* budget, in 12 s** — no
   `core/` change at all. The SLIM variant keeps every structural property that makes the
   leaf hard (an opaque `Real.sqrt`/`Real.log` atom, the coefficient drop, the same
   witness skeleton); it only stops repeating the monomial inside the function argument.
   The same comparison at k=16 is 3 s vs 11 s, a ~3.7× elaboration saving.

This makes §7.6 the **recommended next iteration** rather than a speculative idea: it is
the only measured route to a k=32 bridge_chain, it lives entirely inside this family's
own file, and it costs one witness line. It is *not* taken in this iteration because
shipping it means re-measuring the whole table (battery kill-lists included — a shared
`Real.sqrt x` atom on both sides of a step changes what `gcongr` can anti-unify), and an
unmeasured schema is worth less than a measured one plus an evidence-backed handoff.

### 4.5 Corridor plausibility (indicative, NOT a pass-rate measurement)

V5 gives the corridor's floor. The ceiling needs the bank. What *can* be measured locally
and for free is a weaker but real proxy: **does a short, idiomatic proof — the kind a
prover model actually emits — exist at all?** If none does, the leaf is probably above the
band. Hand-written attempts, run against generated leaves:

**case_tree v2 leaf** (`∀ x : ℝ, -15 ≤ x → x ≤ -7 → √(x² + 22x + 130) − 2 ≤ 3`):

| attempt | verdict |
|---|---|
| `nlinarith [Real.sq_sqrt …, Real.sqrt_nonneg …, band product]` (the standard DSV2 idiom) | **CLOSES** (0.1 s) |
| `Real.sqrt_le_sqrt` then `Real.sqrt_sq` | **CLOSES** (0.1 s) |
| `Real.sqrt_le_left` | **CLOSES** (0.1 s) |
| the shipped witness (`Real.sqrt_le_iff`) | **CLOSES** (0.1 s) |

Four independent one-to-three-line routes, including the single most common prover idiom
for a `√` goal. Corridor-**positive**: the leaf resists all 20 battery attempts yet is one
retrieved lemma away for anything that knows Mathlib's `√` API.

**bridge_chain v2 leaf** (`8M + 8 log M + 7 ≤ 6M' + 1·log M' + 5`):

| attempt | verdict |
|---|---|
| 5-line: `hM : 1 ≤ M` by `nlinarith`, both log facts, then `nlinarith` | **fails** |
| same with an explicit `mul_pos (mul_pos hx0 hy0) hz0` positivity scaffold | **fails — and it fails at `1 ≤ M`** |
| the shipped 14-line witness | CLOSES (0.3 s) |

Corridor-**negative, or at least a warning**. The blocking sub-step is not the named
function at all: `nlinarith` cannot derive `1 ≤ x¹y¹z¹` from `3 ≤ x, 3 ≤ y, 3 ≤ z` (it
multiplies hypothesis *pairs*; this needs a triple product) — the same obstacle v1's log
recorded for flat routes on the *goal*, now sitting inside every *leaf*. The shipped
witness needs the `one_le_pow₀` + `le_mul_of_one_le_right` scaffold, and only the shipped
witness closed the leaf.

So the two families are in different places on the corridor even though both clear the
floor: **case_tree v2 looks comfortably reachable; bridge_chain v2 may be too hard.** The
honest reading is that the bank measurement matters much more for bridge_chain, and that
§7.6's slim variant is doubly attractive — with the named function over a single variable,
`F(v) ≤ v` follows from `3 ≤ v` directly, removing one of the two scaffolds a prover has
to reinvent. This is a proxy, not a pass rate: three hand-written attempts are not eight
samples from DSV2.

---

## 5. Discard / regeneration rates (offline, no Lean)

Both generators discard candidates *before* any Lean call, so discarding costs
microseconds and never shows up as a failed check.

**bridge_chain**, n=12 per k, two seeds:

| k | endpoint-gate discards (seed 7001) | (seed 11) | step resamples (7001) | worst single slot |
|---|---|---|---|---|
| 2 | 98/110 = 89.1% | 81/93 = 87.1% | 16/40 = 40.0% | 23 retries |
| 4 | 142/154 = 92.2% | 122/134 = 91.0% | 30/78 = 38.5% | 42 retries |
| 8 | 97/109 = 89.0% | 59/71 = 83.1% | 83/179 = 46.4% | 28 retries |
| 16 | 56/68 = 82.4% | 62/74 = 83.8% | 100/292 = 34.2% | 15 retries |
| 32 | 57/69 = 82.6% | 126/138 = 91.3% | 240/624 = 38.5% | 28 retries |
| hidden-intermediate pre-check | **0 violations in 120 problems**, every k — structurally impossible, kept as a tripwire |

The endpoint-gate discard rate rose from v1's ~78–83% to ~82–92%. Two effects pull in
opposite directions and the first wins: the gate gained a **third** conjunct
(`d_k ≤ d₀`, for the new named-function coefficient), which roughly halves acceptance,
while the per-step congruence gate biases the `(c,d,o)` walk *downward* and so makes the
endpoint condition easier to satisfy. Worst observed
slot is 42 retries against a cap of 400; at an 8% acceptance rate the probability of
exhausting the cap is ~3·10⁻¹⁵ per slot. The per-step resample rate rose from v1's 5% to
~34–46% because the congruence gate rejects the majority of the `(c,d,o)` grid — still
72 candidate draws at worst, all arithmetic.

**Of the problems actually emitted, 100% pass V0–V6.** The discarding buys collapse
resistance, not validator pass rate.

**case_tree: 0 discards, by construction, at every k.** The generator is correct by
exact-integer construction rather than by rejection sampling; `_repair_necessity` (the
one thing that could fire) measures `repaired_frac = 0.0` at every k, unchanged from v1.

---

## 6. Per-node flatness (structural half of DIRECTION §5.4a)

**bridge_chain** — `leaf_shape_stats`, n=12 per k, seed 7001:

| k | leaves | leaf prop chars (min / median / max) | δ mix (1:2) | fn mix (√:log) | fn-pair mix |
|---|---|---|---|---|---|
| 2 | 24 | 176 / 177 / 178 | 6:18 | 14:22 | 3:7:6:8 |
| 4 | 48 | 176 / 177 / 178 | 24:24 | 34:26 | 13:14:14:7 |
| 8 | 96 | 176 / 177 / 178 | 51:45 | 45:63 | 12:28:28:28 |
| 16 | 192 | 176 / 177 / 186 | 81:111 | 105:99 | 42:54:57:39 |
| 32 | 384 | 176 / 182 / 190 | 181:203 | 196:200 | 94:95:97:98 |

Leaf statements sit at 176–178 characters for the whole Phase-1 grid; the +5 median at
k=32 is exactly the extra digits of two-digit exponents (the same mechanism, and the same
magnitude, as v1). The knob support — `COEF_RANGE`, `FCOEF_RANGE`, `OFFSET_RANGE`,
`DELTAS`, `FUNCS` — is module-level and identical at every k; k changes only how many
steps compose. The **named-function mixture is ~50/50 at every k**, which is the new
flatness obligation v2 takes on and `test_both_named_functions_appear_at_every_k` pins.

**case_tree** — `leaf_stats`, n=12 per k, seed 7002:

| k | leaves | leaf len mean | min | max | goal len mean | max abs radicand coeff | **max outer const** | repaired |
|---|---|---|---|---|---|---|---|---|
| 2 | 24 | 68.2 | 63 | 70 | 116 | 57 | 12 | 0.0 |
| 4 | 48 | 68.9 | 63 | 73 | 213 | 378 | 12 | 0.0 |
| 8 | 96 | 69.9 | 60 | 76 | 405 | 1 881 | 12 | 0.0 |
| 16 | 192 | 71.4 | 55 | 76 | 803 | 9 076 | 12 | 0.0 |
| 32 | 384 | 72.7 | 59 | 79 | 1 612 | 38 994 | 12 | 0.0 |

Leaf statement length grows **6.6% from k=2 to k=32** (v1: 10.4%) while the leaf count
grows 16×. The residual has the same single source as v1 — the band's *absolute
position*, since the domain is `[−T/2, T/2]` with `T ≈ 7k`, so the radicand's constant
coefficient scales like `a·m²`. The **outer constant is flat at 12 for every k**: it is
`C + t` with `t = _cap(d)` and `d` bounded by the knob support, so the `√` cap adds no new
k-dependence. The proof certificate is position-invariant (same `Real.sqrt_le_iff` step,
same linear combination).

### Distinct-leaf counts and leaf reuse

FAMILIES.md's GRPO-correlation note asks for distinct-leaf counts, not just problem
counts, because "problems assembled from few distinct leaves have correlated content".
Measured over 48 problems per k (4 seeds × n=12):

| k | bridge_chain leaves / distinct / max reuse | case_tree leaves / distinct / max reuse |
|---|---|---|
| 2 | 96 / 96 (100%) / 1 | 96 / 82 (85.4%) / 3 |
| 4 | 192 / 192 (100%) / 1 | 192 / 175 (91.1%) / 3 |
| 8 | 384 / 384 (100%) / 1 | 384 / 358 (93.2%) / 3 |
| 16 | 768 / 768 (100%) / 1 | 768 / 733 (95.4%) / 3 |
| 32 | 1 536 / 1 536 (100%) / 1 | 1 536 / 1 459 (95.0%) / 3 |

bridge_chain never repeats a leaf (the exponent triple alone is a near-unique key).
case_tree repeats 5–15% of leaves at a maximum reuse of 3 — expected, since a leaf is
determined by (band position, 4 knobs, variant) and bands at small |position| recur
across problems. A mild correlation, not a collapse; both families are far above the
bank-drawn regime the strategist's note is aimed at.

**Leaf-disjointness contract: not applicable to these two generators.** Both are fully
synthetic and draw **no** bank leaves, so nothing here goes through
`rlmath.families.leaf_split` — the contract binds whatever draws from
`data/bank/bank_dsv2.jsonl`, which is the direction-1 (bank-drawn) family and the
mutation breeder, not v2 synthetic content. If a future mixture family combines synthetic
and bank leaves in one problem, the bank half must route through `leaf_split` and the
problem must record its pool.

### Scaling headroom (composed oracle artifact, offline)

| k | bridge: max leaf / goal / assembly / artifact chars | case_tree: max leaf / goal / assembly / artifact chars |
|---|---|---|
| 2 | 177 / 177 / 77 / 2 727 | 69 / 112 / 132 / 857 |
| 8 | 177 / 176 / 263 / 10 255 | 74 / 408 / 932 / 3 777 |
| 32 | 190 / 183 / 1 030 / 40 874 | 78 / 1 615 / 5 237 / 16 687 |
| 128 | 190 / 183 / 4 131 / 164 730 | 81 / 6 608 / 26 664 / 73 252 |
| 512 | — | 85 / 27 293 / 129 668 / 319 631 |

Leaves stay ~180 / ~70 characters at every k while the full proof grows past 160 kB
(bridge, k=128) and 320 kB (case_tree, k=512) — the §5.4(e) beyond-window tier, reached
by mathematical content rather than by glue (case_tree's assembly is Θ(k log k), the
balanced-tree decision inherited from v1).

---

## 7. What v2 does *not* establish — read this before trusting the tables

1. **The corridor's ceiling is unmeasured, and the local proxy already splits the two
   families (§4.5).** V5 says these leaves resist 20 automation attempts; it does **not**
   say the frozen DSV2-7B leaf closes them at pass@8 ∈ [0.25, 0.9], and v2 leaves are by
   construction *harder* than v1's. The indicative probe found **four** short idiomatic
   routes into a case_tree leaf and **zero** into a bridge_chain leaf (only the shipped
   14-line witness). **This is the single highest-risk open item**, it needs a bank
   measurement rather than an argument, and it needs it for bridge_chain first. If the
   measured pass@8 lands below the band: for bridge_chain try §7.6's slim variant (which
   removes one of the two scaffolds a prover must reinvent) before falling back to
   FAMILIES.md direction 1 (bank-drawn leaves). A per-problem mixture of v1-easy and
   v2-hard leaves is *not* a fix — it reintroduces the V5 failure for its easy arm.
2. **Battery resistance is a property of *this* Mathlib.** `gcongr`'s lemma set and
   `nlinarith`'s preprocessing are the two moving parts. Both A/B controls are committed
   as integration tests (`test_the_sqrt_cap_is_what_survives_intros_nlinarith`,
   `test_the_congruence_gate_is_what_survives_gcongr_linarith`) and assert *both*
   halves — the v1 control still dying and the v2 leaf still surviving — so a Mathlib
   upgrade that softens either family fails loudly instead of silently.
3. **bridge_chain collapsibility is unchanged from v1.** `≤` over ℝ is transitive *and*
   total, so a prover establishing a quantitative ratio `M_k ≥ r·M₀` closes the goal in a
   k-independent number of lines. The k-axis here stresses plan length and intermediate
   invention; DIRECTION §5.4(d) (flat-prover decay) is a Phase-2 measurement.
4. **One leaf schema per family.** Both distributions are single-schema mixtures (bridge:
   2 functions × 3 variables × 2 δ; case_tree: 2 variants × 12 knob tuples). That keeps
   flatness trivially true and diversity low; the GRPO-correlation caution in FAMILIES.md
   applies to synthetic leaves as much as to bank-drawn ones.
5. **`e ≥ 1` and the excluded `(2,1,1)` corner are shipped as invariants, not as
   coincidences** — both are asserted at build time and pinned by offline tests, because
   both were found by inspecting probe output rather than by reasoning.
6. **bridge_chain leaves are verbose (177 chars vs case_tree's 69)** because the monomial
   is written three times per side (`c * M`, `Real.sqrt (M)`, and again on the right).
   That verbosity is what walls k=32 off (§4.3/§4.4) and is plausibly a pass-rate tax on
   a 7B prover as well. **Recommended next iteration** (measured, not speculative — the
   slim statements pass V3 at k=32 at the stock budget in 12 s): apply the named function
   to a single **variable** (`d * Real.sqrt y`) instead of the whole monomial. Sketch:
   - sample the function's variable per term (drawing it *independently* of the step's
     variable keeps consecutive terms disagreeing, so the atoms rarely cancel);
   - sampling constraint becomes `c₂·3^δ − c₁ − d₁ ≥ max(0, o₁ − o₂)` unchanged, since
     `F(v) ≤ v ≤ M` still bounds the left function term by `M`;
   - one extra witness line: `have hv : v ≤ M := le_mul_of_one_le_right …` (from
     `1 ≤` the other two factors, which the existing `hp*` scaffold already proves);
   - **must be re-measured end to end**, because a shared `Real.sqrt x` atom on both
     sides of a step changes what `gcongr` can anti-unify — the round-1 kill-list (§2)
     has to be re-run, not assumed.

---

## 8. Contract friction (reported, not worked around — these files are not owned here)

1. **`research/family-bridge-chain.md` and `research/family-case-tree.md` still describe
   the v1 schemas as shipped.** They are the measured record of v1 and should keep their
   numbers, but each needs a one-line "SUPERSEDED by research/family-v2-hardening.md
   (2026-08-12)" banner at the top. Not applied here: those files are outside this
   iteration's ownership.
2. **`data/families/*/DATASHEET.md` are the red v1 datasheets** and will disagree with
   the v2 generators until `scripts/gen_families.py` is re-run. The generators keep every
   `meta` key that script consumes (`discards`, `resamples`, `knobs[*].repaired`), so a
   re-run needs no code change.
3. **`scripts/gen_families.py`'s docstring says `rlmath.families.__init__` deliberately
   does not import the family modules.** It does (since 2026-08-11); the comment is stale.
4. **Large-k plan checks hit *two* elaborator limits, and this is a status-taxonomy
   hazard, not only a validation one.** `plan_check` is harness stage 1, so a *correct*
   policy plan at k=32 is recorded `PLAN_INVALID` — an infrastructure limit wearing a
   policy-failure label, which is what DIRECTION §6 exists to prevent. Two notes for
   whoever owns `core/`: (i) `PREAMBLE`'s `maxHeartbeats 400000` is only the first wall —
   past ~800 000 the same check fails on `maxRecDepth` instead (measured, §4.4), so a
   heartbeat bump alone does not fix it; (ii) if the taxonomy is to stay honest, an
   elaborator-limit error in `plan_check` probably deserves its own status (or at least
   the `ERROR` bucket) rather than `PLAN_INVALID`. bridge_chain v2's own contribution to
   the problem is fixable inside this family (§7.6) and that is the route recorded here.
5. **The V0/V5 battery is a list of single tactics plus exactly one hand-added combo**
   (`gcongr <;> linarith`), each run bare and intros-first. Both v1 kills came from the
   combo-or-intros dimension, which is evidence that the *next* ratchet is more two-step
   routes rather than more single tactics — candidates worth probing:
   `intros; nlinarith [sq_nonneg _]`, `intros; simp; nlinarith`, `intros; positivity`,
   `intros; nlinarith [Real.sq_sqrt _, Real.sqrt_nonneg _]` (the last one aimed squarely
   at case_tree v2 — see §4.5). That is a `validate.py` change; both families here were
   probed against the current battery only, so the ratchet applies to them too.
6. **FAMILIES.md's "Status (2026-08-11 evening): v1 schemas fail the strengthened V5"
   section is now superseded by this iteration** — direction 2 cleared the full battery for
   both families on the required grid. FAMILIES.md is not this iteration's file; the
   numbers it needs are §0 and §4.
