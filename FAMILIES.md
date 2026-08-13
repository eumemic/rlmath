# Task families — Phase 1 contract

Phase 1 of DIRECTION.md §5.5: size-parameterized problem families with per-node difficulty flat
in k. This file is the contract generators are built against; `src/rlmath/families/types.py` and
`validate.py` are its code form. Started 2026-08-11.

## The object a generator emits

A `GeneratedProblem` (types.py) is a goal **plus its own witness**: the reference decomposition
(`oracle_plan`, in the same `DecompositionPlan` shape policies emit) and a kernel-checkable proof
for every leaf (`witnesses`). The generator knows the proofs by construction, so every problem is
**self-certifying**: `validate.py` can compose and kernel-check the whole artifact with *no LM
anywhere*. Oracle-replay solve rate is the Phase-1 gate metric (≥70% at every k, DIRECTION §5.5)
and doubles as the per-problem well-formedness check.

## Validity checks (validate.py, in order)

| # | Check | Why |
|---|---|---|
| V0 | goal resists the automation battery | else the flat arm wins by tactic dispatch and the k-axis measures nothing |
| V1 | goal elaborates (ok + exactly 1 sorry) | standard statement check |
| V2 | every witness prop elaborates; every witness proof kernel-checks | the problem must actually be true, with known proofs |
| V3 | oracle plan passes stage-1 plan check (assembly closes goal granting lemmas) | the reference decomposition must be *valid*, separably from leaves (§5.2) |
| V4 | full oracle compose → kernel + sanitizer + axiom audit = VERIFIED | the no-model ceiling; end-to-end well-formedness |
| V5 | every leaf resists the automation battery | DIRECTION §5.4(c): otherwise the experiment measures tactic dispatch, not decomposition |
| V6 | intermediate lemma props are not substrings of the goal (normalized; family may exempt named endpoints via `meta["visible_lemmas"]`) | intermediates must be *invented* by a policy, not copied |

Automation battery (V0/V5): `simp`, `aesop`, `norm_num`, `omega`, `decide`, `linarith`,
`positivity`, `nlinarith`, `gcongr`, `gcongr <;> linarith` — each run **bare and intros-first**
(20 proof attempts per prop), short per-tactic timeout; **any** success fails the check. The
battery is a constant in validate.py: extending it strengthens every family retroactively.
Both 2026-08-11 strengthenings came from the family agents' own measurements: no bare tactic
introduces ∀/→ (so quantified props passed the old battery for free — famB's affine-band kill),
and `gcongr <;> linarith` closed monomial goals all seven originals missed (famA).

V6 is likewise layered after both agents measured the original whole-prop substring check as
near-vacuous: **V6a** compares binder-stripped bodies (catches restatement across binder
spellings); **V6b** checks family-declared `meta["hidden_terms"]` against the goal (the strong
term-leakage property; bridge_chain emits it, structural-split families may have no term-shaped
secrets and rely on their own necessity tests instead).

Operational notes: `plan_format.MAX_LEMMAS_HARD` = 1024 (raised from 64 — it sat below the
beyond-window tier and would have made large decompositions policy-unemittable);
`Budgets.max_lemmas` defaults to 8, so k≥16 episode configs must raise it or every episode is
`budget_exhausted`.

**Empirical, not argued:** schema design happens against the real backend. A family is acceptable
when its measured validator pass rate is high (target ≥90% of generated problems pass V0–V6 before
discard/regenerate loops) at every k in {2,4,8,16,32}, with rejection reasons logged. Concrete
arithmetic dies to `norm_num`/`decide` — families need symbolic content (quantified statements,
function symbols, real Mathlib lemma steps).

## Scaling requirements

- `k` = number of leaves in the reference decomposition. Generators take `k` and `seed`; output is
  deterministic in `(k, seed)`.
- **Per-node difficulty flat in k** by construction: leaf statements at k=32 are drawn from the
  same distribution as at k=2 (same step schema, same term-size knobs). Measured calibration
  against the real leaf prover happens after the bake-off (bank pass rates); structural flatness
  (leaf prop length, step type mix) is checked at generation time and reported in the datasheet.
- The top of the k-grid must eventually exceed single-context feasibility (§5.4(e)); the schema
  should not break at k=128 even if Phase 1 only ships k≤32.
  **Measured 2026-08-13: this clause is already violated, by the SHIPPED family, and the cause is
  the harness rather than any schema.** At the shipped `PREAMBLE` (`maxHeartbeats 400000`), V4 —
  full oracle compose — exhausts heartbeats for `v2` and `r1_recip` at **k=128**, for `r2_prod`
  and `r2_sum` at **k=64**, and for `r4_floorprod` at **k=32** (3/3 seeds). V1/V2 pass at every k;
  V3 passes except at k=64. Raising to 1,600,000 clears everything observed up to k=64
  (`r4_floorprod` at k=64 needs 6,400,000). So the k-axis is bounded today by elaboration budget,
  not by any property the families were designed around, and DIRECTION §5.4(e)'s beyond-window
  tier cannot be reached without addressing it.

  **The bump is not free, and the reason is the trap worth remembering: `maxHeartbeats` is shared
  by the compose check and the automation battery.** V5 says "no battery tactic closes this leaf"
  — but `nlinarith`/`aesop` are searching under the same budget, so *raising the budget arms the
  adversary too*. Any change to this constant **retroactively invalidates every V0/V5 verdict in
  the repo** and requires re-running the full gate with the planted control attached. The corridor's
  floor is therefore a function of the heartbeat budget, not an absolute property of a statement,
  and the budget belongs in the datasheet alongside the tactic list.

## Status (2026-08-11 evening): v1 schemas fail the strengthened V5 — by design, iterate

Re-materialization under the strengthened battery (seed 42, n=5, k∈{2,4,8}):
**bridge_chain 6/15 valid** (16 leaf-kills, all `intros; gcongr <;> linarith` — the combo famA
gated at the endpoints but never ran against individual steps); **case_tree 0/15** (70/70
leaf-kills by `intros; nlinarith` — structural: its witness template IS one nlinarith call, so
every leaf is nlinarith-adjacent by construction). **V0 held everywhere** — goals resist the full
battery at every k, so the skeletons and the k-axis are sound; only leaf content is too soft.

What V5 now actually demands is a corridor: leaves too hard for any single battery call, yet
closable by the frozen 7B leaf in the [0.25, 0.9] band. The battery gives the corridor's floor;
the bake-off's measured bank gives its ceiling. **The band is a distributional target, not a
per-leaf hard constraint** (retune agent, 2026-08-12): at n=8 attempts a leaf whose true rate is
0.5 still lands outside the band ~4% of the time, so "every leaf in band" rejects correct presets
most of the time. Operational criterion: **band-fit fraction ≥ 0.60 with zero-rate ≤ 0.20** at
pass@8, mean targeted near 0.45; tighten only by raising attempts (~32 for per-leaf claims).

**The three clauses are conjunctive, and the mean is the weakest of them** (added 2026-08-12).
At n=8 the band `[0.25, 0.9]` excludes exactly `{0/8, 1/8, 8/8}`, so a leaf whose true rate is
`p` lands in band with probability `1 − (1−p)⁸ − 8p(1−p)⁷ − p⁸` — 0.34 at p=0.15, 0.63 at 0.25,
**0.94 at 0.45**, 0.97 at 0.62, 0.57 at 0.90, 0.34 at 0.95. It follows that **heterogeneity, not
the mean, is what fails the corridor**: a bimodal schema with 45% of leaves at 0.60 and 55% at
0.02 has mean 0.28 — respectable — yet band-fit 0.44 and zero-rate 0.47, failing both other
clauses. Report all three, always; a rung that passes R1 alone is rejected.

**Corollary — mixing to hit a mean is not a fix.** Blending two schemas (or two presets) so the
pooled mean lands near 0.45 makes the corridor *worse*, not better: a 50/50 mix of leaves at 0.9
and 0.2 has mean 0.55 and band-fit ≈ 0. The corridor is a statement about the leaf distribution's
shape, not its first moment. v2 directions, in preference order:
1. **Semi-synthetic leaves** (the original §5.4 design): draw leaf content from the calibrated
   bank — competition-style statements are battery-resistant by nature and arrive with measured
   pass rates. Needs the bake-off (leaf pass-rate bank).
2. **Hardened synthetic steps**: mix named-function content (√, log, abs, floor) into ladder
   steps / band claims so raw polynomial arithmetic doesn't suffice; re-measure.
The red datasheets in data/families/ are kept as the measured record of the v1 state.

## Leaf-disjointness contract (strategist review 2026-08-12 — binding before any v2 dataset)

With a finite leaf bank, **train/eval leaf disjointness is what makes the transfer plot
interpretable**: eval-k problems built from training-seen leaves cannot distinguish
"decomposition structure transferred" from "the root memorized these statements" — a
contamination channel the retrieval RLM never had (its content was inexhaustible).

- Membership is decided by `families/leaf_split.py` — a pure function of `statement_key`
  (last hex nibble; 25% eval). No manifest, stable under bank growth and re-sweeps.
- **Mutants INHERIT their parent's membership** (`pool_for`; strategist catch 2026-08-12):
  a mutant is a near-twin, so an own-key roll would seed eval with train-twins and recreate
  the contamination channel this contract closes. Fresh keys, inherited membership. (An
  earlier revision of this contract stated independent membership as a feature — it was the
  bug.) Consumers read `leaf_pool` on mutant rows, never bare `leaf_split`.
- **TRAIN problems (any k) draw leaves exclusively from the train pool; EVAL problems
  exclusively from the eval pool.** Datasets record the pool per problem; the gen CLI must
  refuse mixed draws.
- **How that is achieved for a *synthetic* k-leaf generator: leaf-level rejection, never
  problem-level** (ratified 2026-08-12 after the ladder design agent showed the literal
  reading is infeasible). Sampling a whole problem and discarding it unless all k leaves
  happen to agree has acceptance probability `0.75^k` for train and `0.25^k` for eval —
  0.56/0.32/0.10/0.010/0.0001 at k=2/4/8/16/32 train, and 1.5e-5 at k=8 for eval. It does
  not scale and must not be attempted. Instead **resample each piece until its own
  `statement_key` nibble lands in the target pool** (expected 1.33 draws train, 4.0 eval),
  which satisfies the contract's actual intent — no eval problem is built from a
  train-visible leaf — at constant cost per leaf. Two obligations come with it: the
  generator must stay deterministic in `(k, seed, idx, pool)`, and a χ² check must confirm
  that conditioning on the key nibble does not shift the knob marginals (the nibble is a
  hash of the rendered prop, so it should be independent of the knobs, but "should" is not
  "measured").
  **MEASURED 2026-08-13 — the precondition holds, and how you count matters.** 2,520 case_tree
  leaves over 3 rungs × k ∈ {2,4,8} × 60 seeds, χ² of pool membership against each knob:
  width p=0.885, curvature p=0.348, **offset p=0.033**, slack p=0.744 — all clear at a
  Bonferroni α of 0.0125. Eval share 0.259 against a 0.25 design.
  *The first run said otherwise and was wrong.* Counting per leaf **instance** put offset at
  χ²=11.885, p=0.0026 — apparently biased. The cause is that 17% of drawn leaves are duplicate
  statements (the schema's distinct-leaf space saturates in the low thousands), and a duplicate
  shares its nibble *and* its knobs, so it double-counts into exactly the cell that inflates χ².
  **Test on DISTINCT statement keys** — which is also the unit pool membership is defined on.
  Offset remains the closest to the line and is worth re-checking at larger n if this machinery
  ships.
- **Status: NOT YET IMPLEMENTED for family-generated leaves.** `scripts/gen_families.py`
  has no pool logic at all, so every currently-materialized family row is `unrecorded`
  rather than train/eval. This is not a contamination event — nothing has been trained —
  but it blocks the first dataset that feeds training, and it is the step where the
  contract stops being prose.
- GRPO-correlation note: problems assembled from few distinct leaves have correlated content —
  effective dataset size is closer to leaf count than problem count. Datasheets must report
  distinct-leaf counts and leaf-reuse distribution, not just problem counts.

**Corridor widening (v2 leaf sources, in order):** (1) the wide candidate sweep — 30–50k
Lean-Workbook/exercise statements at pass@8 ≈ $35–45 of GPU, projecting 2–3k band statements
(the current ~40 is a *sample*, not a bank); (2) mutation breeding — perturb constants/exponents/
bounds of known in-band statements and **re-measure every mutant's pass@8** (mutants inherit the
corridor's neighborhood, never membership; measurement is mandatory).

## Families

- **A — bridge chains** (`bridge_chain`): prove `R(a₀, a_k)` composed through k hidden
  intermediates; only endpoints appear in the statement. Transitivity supplies the assembly; the
  *intermediates* are the invented content.
- **B — case trees** (`case_tree`): goals whose natural proof splits into k cases (parity/modular/
  interval/structural), each case a distinct leaf lemma; the *split* is the invented content.

Each family module registers itself in `rlmath.families.REGISTRY` and ships a `BUILD_NOTES.md`-style
datasheet when `scripts/gen_families.py` materializes a dataset (counts, rejection stats, validator
table, leaf-shape distributions per k — the ../rl data-contract discipline).
