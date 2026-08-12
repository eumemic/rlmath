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

## Status (2026-08-11 evening): v1 schemas fail the strengthened V5 — by design, iterate

Re-materialization under the strengthened battery (seed 42, n=5, k∈{2,4,8}):
**bridge_chain 6/15 valid** (16 leaf-kills, all `intros; gcongr <;> linarith` — the combo famA
gated at the endpoints but never ran against individual steps); **case_tree 0/15** (70/70
leaf-kills by `intros; nlinarith` — structural: its witness template IS one nlinarith call, so
every leaf is nlinarith-adjacent by construction). **V0 held everywhere** — goals resist the full
battery at every k, so the skeletons and the k-axis are sound; only leaf content is too soft.

What V5 now actually demands is a corridor: leaves too hard for any single battery call, yet
closable by the frozen 7B leaf at pass@8 ∈ [0.25, 0.9]. The battery gives the corridor's floor;
the bake-off's measured bank gives its ceiling. v2 directions, in preference order:
1. **Semi-synthetic leaves** (the original §5.4 design): draw leaf content from the calibrated
   bank — competition-style statements are battery-resistant by nature and arrive with measured
   pass rates. Needs the bake-off (leaf pass-rate bank).
2. **Hardened synthetic steps**: mix named-function content (√, log, abs, floor) into ladder
   steps / band claims so raw polynomial arithmetic doesn't suffice; re-measure.
The red datasheets in data/families/ are kept as the measured record of the v1 state.

## Families

- **A — bridge chains** (`bridge_chain`): prove `R(a₀, a_k)` composed through k hidden
  intermediates; only endpoints appear in the statement. Transitivity supplies the assembly; the
  *intermediates* are the invented content.
- **B — case trees** (`case_tree`): goals whose natural proof splits into k cases (parity/modular/
  interval/structural), each case a distinct leaf lemma; the *split* is the invented content.

Each family module registers itself in `rlmath.families.REGISTRY` and ships a `BUILD_NOTES.md`-style
datasheet when `scripts/gen_families.py` materializes a dataset (counts, rejection stats, validator
table, leaf-shape distributions per k — the ../rl data-contract discipline).
