# Goedel-Code-Prover — full read

**Paper:** *Goedel-Code-Prover: Hierarchical Proof Search for Open State-of-the-Art Code Verification*
**arXiv:** [2603.19329](https://arxiv.org/abs/2603.19329) · v1 2026-03-18 · **v3 2026-08-10** · "Published as a COLM paper" (COLM 2026)
**Authors:** Zenan Li¹, Ziran Yang²(=), Deyuan He³, Haoyu Zhao³, Andrew Zhao³, Shange Tang², Kaiyu Yang⁴, Aarti Gupta³, Zhendong Su¹, Chi Jin²
¹ETH Zürich · ²Princeton Language and Intelligence · ³Princeton CS · ⁴Apodex (was "MiroMind" in v1)
**Weights:** [`Goedel-LM/Goedel-Code-Prover-8B`](https://huggingface.co/Goedel-LM/Goedel-Code-Prover-8B) — confirmed live, `base_model: Qwen/Qwen3-8B`, Apache-2.0. **No code/harness release found** (paper links no repo).

**Read basis:** full HTML of both v1 and v3, diffed line-by-line. Everything below is from v3 unless marked. **Read v3, not v1** — v3 materially weakens several v1 claims (§9).

> **One-line summary.** A two-stage Lean-4 *code-verification* system: a Qwen3-8B policy first decomposes a Hoare-triple goal into `sorry`-bodied lemmas (scored by a syntactic "operator footprint" reduction, gated by an LLM-written assembly proof term and by random-testing), then proves the leaves with compiler-feedback refinement. SFT does almost all the work; GRPO on the decomposition score adds **+1.1 to +3.2 points**, one seed, no significance.

---

## 1. Domain — read this before importing anything

This is **code verification, not mathematics.** The task is Hoare-style: given a Lean program `C` and predicates `P`, `Q`, prove

```
G : ∀ x, P(x) → Q(x, C(x))
```

The paper's own §1/Appendix D argument for why it needed new machinery is that mathematics methods *do not transfer here* — "ungrounded decomposition" (no NL corpus about proving program specs), "concept proliferation" (every program defines fresh concepts, no Mathlib to lean on), "tactic distribution shift" (`grind`/induction/`omega` over discrete domains, not `linarith`/`polyrith`).

That argument runs in reverse too, and the paper measures it: **their decomposition score returns exactly zero on Mathlib** (§7.2). Any port of their reward into `rlmath` is a port *against* the direction of their own stated transfer gap.

---

## 2. Base model and scale

| | |
|---|---|
| Backbone | **Qwen3-8B** (Yang et al., 2025) |
| Result | Göedel-Code-Prover-8B — a **single unified policy** doing both decomposition and completion |
| SFT stack | LLaMA-Factory, 3 epochs, LR 1e-5 cosine, warmup 0.1, ctx 10,240 tok, sequence packing, batch 128 |
| RL stack | GRPO (Shao et al. 2024) in **verl**, **100 steps**, **16 GPUs** (v1 said "4×4 GPUs") |
| Frontier models used | GPT-5.2 (formalization + trajectories), Gemini-3-Flash (trajectories, completion fallback), GPT-OSS-120B (off-the-shelf probe), text-embedding-3-large (decontamination) |

There is **no larger sibling** — 8B is the only trained model.

---

## 3. SFT data construction and sizes

**Problem pool.** 5K unique problems from **LeetCode** (Xia et al. 2025) and **OpenCodeInstruct** (Ahmad et al. 2025). Each auto-formalized into Lean by **GPT-5.2**, then *iteratively refined until it passes both syntactic validation and quickcheck* ("ensuring empirical consistency"). 4,277 implementations survive to the decontamination audit — so ~15% of the 5K is dropped somewhere in curation/dedup.

**Trajectory generation.** Frontier models (**GPT-5.2 and Gemini-3-Flash**) generate "scaffolded trajectories" for both stages. This yields:

- **281K decomposition input–output pairs**
- **151K completion pairs**

Merged and used to fine-tune Qwen3-8B → initial policy π₀.

**Trajectory filtering** (Appendix G):
- *Decomposition* trajectories kept only if (a) constructively justified — proposed lemmas provably entail the parent — **and** (b) positive structural reduction, i.e. **S > 0**. (v1 phrased (b) as "the decomposition score strictly decreases"; v3 restates as `S>0`. Same thing under v3's orientation fix, §9.)
- *Completion* trajectories kept only if the final proof is **accepted by the Lean kernel**.

**Decontamination** (v3 §4.1 + Appendix H.2 — all new in v3):
- Exact title/description match against Verina/Clever/AlgoVeri removed.
- Longest-shared-substring on boilerplate-stripped Lean, vs all 4,277 training implementations: **13/427 at ≥50 chars, 3/427 at ≥100, 0/427 at ≥200**.
- Embedding audit (text-embedding-3-large, cos ≥ 0.95): **2/427 flagged**, both Verina — `verina_advanced_42/maxProfit` (0.997), `verina_advanced_18/isArmstrong` (0.964). Manual inspection: materially different specs/impls, no proof transfer.
- Residual similarity attributed to independently formalizing the same LeetCode source.

**Soundness gate on all accepted proofs:** only `propext`, `Classical.choice`, `Quot.sound` admitted. Proofs invoking **`Lean.ofReduceBool` or `Lean.trustCompiler` are rejected** as kernel-bypassing. (v1's Appendix D had recommended `native_decide` as a needed tactic — which *produces* `ofReduceBool`; v3 quietly replaced that recommendation with "`grind`, domain-specific decision procedures, and explicit recursive reasoning". A v1→v3 soundness fix.)

---

## 4. The decomposition score — exact definition

Two axes: **(i) constructive justification** and **(ii) decomposition effectiveness**. Computed by two custom Lean tactics, `operatorcount` and `quickcheck`, invocable at any proof state.

### (i) Constructive justification → binary validity gate `v`

A candidate decomposition must supply a **proof reconstruction**: a proof term `π_parent`, *produced by the LLM as part of its decomposition output*, such that **Lean can verify `(L₁ ∧ … ∧ L_k) ⇒ G`**. The paper requires that `π_parent` **explicitly invokes each proposed lemma**, "ensuring the decomposition is not merely a syntactic list but a constructively justified reduction of the original goal."

Constructive justification alone is insufficient — the paper names the exact hack:

> "a false lemma (e.g., `l = [] ∧ l.length > 0`) can technically prove the parent theorem but shifts the burden to an impossible sub-task."

So **quickcheck** is layered in as a *semantic gate*: random concrete inputs are sampled and each `Lᵢ` evaluated; a counterexample on **any** `Lᵢ` discards the **entire** decomposition before any proof search.

```
v(L₁,…,L_k ; G)  =  𝟙_proof(L₁,…,L_k ; G) · ∏_{i=1}^{k} 𝟙_qc(L_i)
```

where `𝟙_proof = 1` iff proof reconstruction succeeds, `𝟙_qc(L_i) = 1` iff no counterexample found for `L_i`.

### (ii) Decomposition effectiveness → continuous reduction ratio `r`

**Structural difficulty `d(G)` = operator footprint**: the total number of *logical* operator occurrences (connectives, quantifiers) plus *domain-specific program* operator occurrences (arithmetic, bitwise, data-structure constructors) in the goal's Lean **AST**, **excluding variable references and type annotations**. Rationale: "each operator corresponds to a specific class of proof obligations."

Aggregated over sub-lemmas by **LogSumExp** — chosen because plain `maxᵢ d(Lᵢ)` "is insensitive to partial progress: reducing one of two equally hard subgoals leaves the max unchanged" (v1 wording, dropped for brevity in v3):

```
d̄(L₁,…,L_k)  =  T · log Σ_{i=1}^{k} exp( d(L_i) / T )
```

`T` controls smoothness. **The value of `T` is never given anywhere in the paper.**

```
r(L₁,…,L_k ; G)  =  max( 1 − d̄(L₁,…,L_k) / d(G) , 0 )
```

### Final score

```
S  =  r(L₁,…,L_k ; G) · v(L₁,…,L_k ; G)
```

Range `[0,1]`, higher is better. Used **identically** as training reward and inference-time ranking criterion — "policy learning and tree-search control are optimized against exactly the same objective." This alignment is the paper's headline framing.

**Worked example (Figure 1/2).** `FindSingleNumber_spec` mixes spec operators (`∀ → ∧ ∨ ∈ =`) with program operators (`filterlist`, `List.count`, `List.map`, `List.length`) → `d(G) = 18`. Split into `L₁` (filterlist on the unique element returns a singleton, `d = 7`) and `L₂` (every other element appears exactly twice, `d = 8`). Figure 2 annotates `S = validity · d-reduction = 1.0 × 0.54` at that node, and `S = v · r = 1.0 × 0.33` at another.

### Properties worth noting for our purposes

- Because LogSumExp is monotone in `k`, **adding more lemmas raises `d̄` and lowers `r`** — an *implicit* penalty on lemma count. There is no explicit lemma-count penalty.
- **Nothing in `S` measures leaf provability.** `v` measures *truth* (random testing) and *sufficiency* (assembly checks); `r` measures *syntactic size*. A true-but-tactically-hard leaf scores identically to a true-but-trivial one of the same footprint.
- Conversely, **a true restatement of the goal at reduced syntactic size passes both gates.** The only pushback on degenerate decomposition is `r`, and `r` is a syntax count. This is exactly the "structured resampling / policy-chosen reward densification" objection in DIRECTION.md §3.3(2), now with a named mechanism and a named metric.

---

## 5. GRPO setup — what is dense, what is sparse, what is replayed

The paper states the problem plainly (§3.2.1):

> "reward mismatch: decomposition receives a dense, continuous score in [0,1], while completion yields only a sparse binary signal (proof accepted or rejected). Naively merging these objectives causes decomposition gradients to dominate and completion proficiency to stagnate."

Resolution: **decouple the objectives, share the parameters.**

| Stage | Signal | How it enters training |
|---|---|---|
| **Decomposition** | dense continuous **`S ∈ [0,1]`** | **GRPO** policy gradient — `J_GRPO` |
| **Completion** | sparse binary verified proof | **NOT a policy-gradient reward.** Kernel-accepted proofs are collected and **replayed as a supervised loss** — `J_SFT` |

```
J  =  J_GRPO  +  λ · J_SFT          λ = 0.08
```

**This is the single most-mis-summarized fact about the paper.** There is *no RLVR on proof completion*. The sparse verified-proof reward never appears in any policy gradient; it acts only as an **acceptance filter deciding which trajectories enter the supervised replay buffer**. Lean verification *does* enter GRPO — but only inside `S`, via `𝟙_proof` (Lean checks the reduction `(L₁∧…∧L_k) ⇒ G`) and `𝟙_qc`. Never via "did the whole theorem get proved."

**Policy-first replay collection** (Algorithm 1, line 5): π attempts each lemma itself first; a frontier model is invoked **only when π fails within `m` attempts** — "ensuring that π is exposed to its own successful completions for replay." `m` is never given.

**Online curriculum** (Algorithm 1, line 8): successfully decomposed lemmas are folded back into the problem set, `P_t ← P_{t−1} ∪ L_t` — "an ever-expanding curriculum of progressively simpler subgoals." Note this makes the training distribution **drift toward easier, smaller goals** over the run.

**GRPO hyperparameters** (Appendix G):

| | |
|---|---|
| Framework / steps / hardware | verl · **100 steps** · 16 GPUs |
| LR | 5e-6, cosine decay |
| Clip ratio | **[0.2, 0.28]** (asymmetric, DAPO-style) |
| Sampling temperature | 0.9 |
| Batch | 64 prompts × **n = 8** generations; mini-batch 256 for the update |
| Group filtering | rollout groups with mean reward **0 or 1 are dropped** (zero-advantage filtering) |
| Replay | aux SFT loss on completion trajectories, **λ = 0.08**; online proof-state buffer refreshed at sampling ratio **¼ per step** |

**Algorithm 1 (Hybrid RL with Online Lemma Collection), verbatim structure:**
1. sample `G ~ P_{t−1}`
2. roll out π → lemmas `L_t = {L₁…L_k}`
3. reward `S = r·v`; form `J_GRPO`
4. attempt completion of `L_t` — π first, frontier fallback after `m` failures → proofs `T_t`
5. form `J_SFT` on `(L_t, T_t)`
6. update π with `J = J_GRPO + λ·J_SFT`
7. `P_t ← P_{t−1} ∪ L_t`

---

## 6. Role of QuickCheck filtering

Implementation: a custom Lean tactic **extending the [Plausible](https://github.com/leanprover-community/plausible) library** — for a universally quantified lemma, sample random concrete inputs (**up to 1000 trials**), evaluate by **native execution**, report a counterexample if found.

It plays **four** distinct roles:

1. **Data curation.** Auto-formalizations from GPT-5.2 are iteratively refined "until they pass both syntactic validation and quickcheck filtering, ensuring empirical consistency." Filters bad formalizations before they ever become training data.
2. **Reward-hack gate inside `S`.** The `∏ 𝟙_qc(Lᵢ)` factor is what stops the `l = [] ∧ l.length > 0` exploit — a false lemma that makes proof reconstruction trivially succeed while shifting the burden to an impossible subtask. **The paper names this hack explicitly**, which retroactively confirms DIRECTION.md §5.6's guess ("hackable in principle, which is presumably why they needed QuickCheck filtering").
3. **Inference-time pruning.** Every candidate decomposition is checked; failure ⇒ discard and retry, "before expensive proof search is attempted."
4. **Disproving benchmark tasks.** Quickcheck is also run *directly on the top-level goal*; when a counterexample is found it is handed to the LLM "which then uses it as evidence to disprove the problem." **23 / 10 / 14 problems disproved on Verina / Clever / AlgoVeri = 47 of 427 (11%) of the benchmark is false.** (See §8 caveat — it is unclear whether these sit in the success-rate denominator.)

**Measured filter strength (Table 1, v3):**

| Dataset | Proof Failed (% of *iterations* rejected by proof reconstruction) | QC Failed (% of *runs* with ≥1 lemma failing quickcheck) |
|---|---|---|
| Verina | 59.4 | 46.4 |
| Clever | 44.9 | 31.8 |
| AlgoVeri | 52.8 | 32.6 |

v3 adds a correction v1 lacked: **different denominators (runs vs iterations), so these must not be added.** v1 wrongly described them as sequential filters ("quickcheck eliminates semantically invalid runs early, and proof reconstruction catches logically unsound iterations *within the remaining runs*"); v3 calls them "complementary failure modes."

**Limits of the gate:** quickcheck tests *truth*, not *difficulty*, and only over randomly sampled concrete inputs with native execution — so it says nothing about non-executable/classical statements, and nothing at all about whether a true lemma is provable within budget.

---

## 7. Context isolation, recursion depth, and generalization

### 7.1 Does the decomposer see completed sub-proofs? — **No, but not by design, and this is not RLM-style context isolation**

The two stages are **strictly sequential** (§3.2.2):

> "the decomposition stage runs first, iteratively breaking down the original goal until a budget is exhausted, **after which** the completion stage takes over and attempts to prove each remaining leaf lemma."

So the decomposer never sees a leaf proof — **because at decomposition time no leaf proof exists yet.** There is **no re-planning loop**: nothing feeds completion outcomes back into decomposition within a run. Isolation is an artifact of stage ordering, not an architectural commitment. **The paper never uses the phrase "context isolation" and never argues for it.**

Three further facts cut against reading this row as isolation:

- **The decomposer writes proof text.** `π_parent`, the assembly proof term discharging `(L₁∧…∧L_k) ⇒ G`, is *emitted by the decomposition policy as part of its output*. The root is not proof-blind; it is only *leaf*-proof-blind.
- **The decomposer's context is the whole Lean file.** Per Appendix G: "the prompt presents the current Lean file with the target theorem highlighted." That file carries program `C`, spec `P`/`Q`, and the accumulated previously-generated lemmas (with `sorry` bodies). Context therefore **grows with the open-goal set**, capped only by the 32-open-lemma limit.
- **The policy is unified.** The same weights do decomposition and completion, so there is no parameter-level separation either.

**Verdict for the DIRECTION.md table:** the honest cell is *"No — sequential two-stage, so the decomposer never sees leaf proofs, but only because none exist yet; no re-planning loop; the decomposer itself writes the parent assembly proof and its prompt carries the full Lean file including all open `sorry`-bodied lemmas."*

### 7.2 Recursion depth — **unbounded and unreported; it is a worklist, not a call tree**

There is **no depth limit and no depth parameter**. Algorithm 2, Stage 1:

```
O ← {G}
for i = 1..128:                       # decomposition iterations
    g ← argmax_{g ∈ O} operator_footprint(g)     # best-first selection
    roll out π to decompose g → {L₁…L_k}
    verify proof reconstruction + quickcheck each Lᵢ; on failure discard and retry
    if |O| would exceed 32 open goals: stop
    O ← (O \ {g}) ∪ {L₁…L_k};  recompute footprints
```

This is a **flat open-goal worklist with a greedy max-operator-footprint selection rule**, not recursive descent. Depth is *emergent*: a lemma can be re-selected and split again, so depth grows implicitly. Budget: **≤ 128 decomposition iterations, ≤ 32 open lemmas, 30 min wall-clock per problem**; then **≤ 128 completion iterations per lemma**. pass@k launches k independent runs.

**No depth statistic is reported anywhere.** The only structural numbers are lemma counts (Table 7): mean **17.02 / 12.13 / 8.48** lemmas on Verina / Clever / AlgoVeri (14.38 overall), std ~11–12. Figure 2's illustration reaches depth 2; Appendix E's running example uses 6 auxiliary lemmas / >130 lines.

(v1's Algorithm 2 differed in two ways: it selected "the highest-scoring goal" rather than the largest-footprint goal, ran unbounded `i = 1,2,…`, and had no 32-goal stop line. v3 made the selection rule and both caps explicit.)

### 7.3 Generalization / transfer — **no train-easy/eval-hard, no size axis; and one hard negative for math**

**Absent:** any train-small/eval-large experiment, any difficulty-axis transfer measurement, any compute-matched comparison. All reported scaling is **inference-time** (search iterations, pass@k), never train/test difficulty transfer. Training problems (LeetCode + OpenCodeInstruct, GPT-5.2-formalized) and eval problems (Verina/Clever/AlgoVeri) differ in *source*, but this is never framed or measured as a transfer experiment, and both sit in the same difficulty regime.

**v3 adds three results that bear directly on transfer — two of them negative:**

**(a) Appendix H.3 — the score does not transfer to mathematics.** The reduction ratio `r` was evaluated on 22 CSLib + 10 Mathlib theorems with human-written decompositions:

| Theorem class | Cases | `r > 0` |
|---|---|---|
| Hoare-style program correctness (CSLib) | 14 | **9** |
| Type-safety theorems (CSLib) | 3 | **0** |
| Structural / categorical (CSLib) | 5 | **0** |
| **Pure mathematics (Mathlib)** | **10** | **0** |

Examples with positive reduction: `otp_ciphertextDist_eq_uniform` (0.872), `mergeSort_sorted` (0.502), `toNAFinAcc_language_eq` (0.492), Shamir privacy (0.154), SKI `pred_correct` (0.112). Zero across the board on Lagrange, Beatty, Hensel, Siegel, Kronecker, Shortlex, Lucas–Lehmer. Authors' conclusion, verbatim:

> "operator-footprint reduction is **not a general-purpose measure of mathematical decomposition quality**."

**This is a directly relevant negative result for `rlmath`**, which is a mathematics project. Their dense reward is measured to be inert on exactly our target distribution.

**(b) Appendix H.8 — score/provability correlation is in-distribution only.** v3 explicitly retreats from v1 here: "This in-distribution result shows that the association is not unique to Verina, but **it does not by itself establish out-of-distribution generalization**." (v1 had claimed the opposite: "confirming that the score captures a robust, transferable signal of proof tractability" and "rather than overfitting to benchmark-specific patterns.")

**(c) Appendix H.1 — the *framework* generalizes across models even untrained.** Off-the-shelf GPT-OSS-120B, no fine-tuning: Verina **20.1% whole-proof → 44.9% hierarchical**. "The structural benefit is not restricted to the frontier models used for data collection; it does not, however, substitute for a fully frontier-free training run." Mildly *supportive* of DIRECTION.md's Phase-2 zero-shot prior.

---

## 8. Benchmarks and numbers

**Benchmarks (427 tasks total).** Verina (Ye et al. 2025) 189 tasks, intro programming exercises · Clever (Thakur et al. 2025) 161 problems, specs designed to avoid test leakage · AlgoVeri (Zhao et al. 2026) 77 classical algorithms with identical functional contracts across Dafny/Verus/Lean, Lean subset used.

> **Construction caveat.** Only Verina ships complete programs. **Clever and AlgoVeri release specifications without reference implementations, so the authors "prompt GPT-5.2 to generate the code and manually verify the results."** Their Clever/AlgoVeri instances are therefore author-constructed, not the released artifacts — cross-paper comparison on those two is not apples-to-apples.

**Headline (v3, §4.2):**

| System | Verina | Clever | AlgoVeri | Overall (427) |
|---|---|---|---|---|
| **Göedel-Code-Prover-8B** | **68.8** | **54.0** | **62.3** | **62.0** |
| BFS-Prover-V2-32B (best neural prover) | — | — | — | 23.8 |
| GPT-5.3-Codex (best frontier) | <20 | 23.6 | <20 | — |

→ "a **2.6×** improvement over the strongest baseline" and "**+38.2 percentage points**" over the best neural prover. Per-system per-benchmark bars live only in Figure 3 (an image); the text gives only the numbers above.

**Baselines.** Frontier single-pass: Claude-Opus-4.6, Gemini-3-Flash, GPT-5.2-Pro, GPT-5.3-Codex, DeepSeek-V3.2-Speciale. Neural provers: Kimina-Prover-72B, DeepSeek-Prover-V2-671B, Goedel-Prover-V2-32B, BFS-Prover-V2-32B (best-first tactic search; the rest whole-proof). All at **pass@128**, default decoding.

> **NOT compute-matched — stated four times in v3** (§4.1, §4.2, Appendix H.4, Conclusion). Their system gets **30 min/problem, ≤128 decomposition iterations, ≤32 open lemmas, ≤128 completion iterations per lemma, × k parallel runs**; baselines get pass@128 single-pass. v3: "our comparisons concern verified success under the stated budgets, **not equal-cost efficiency** or an effect attributable to parameter count." v1's "surpassing neural provers up to **84× larger**" was **deleted** in v3.

**Inference scaling.** Success rises monotonically with completion iterations and pass@k; persistent pass@1 → pass@32 gap, unsaturated. Residual operator-footprint ratio `d̄/d(G)` falls steadily with iterations and with larger k. Baselines (BFS-Prover-V2-32B, Goedel-Prover-V2-32B) extended to **pass@1024** and plateau well before it.

**Ablation — component swap (Table 2, Verina):**

| Decomposition | Completion | Verina |
|---|---|---|
| — (whole-proof) | Gemini-3-Flash | **19.6** (v1 said 26.4) |
| GPT-5.2-Pro | Gemini-3-Flash | 54.4 |
| **Ours** | Gemini-3-Flash | 58.2 |
| GPT-5.2-Pro | **Ours** | 59.2 |
| **Ours** | **Ours** | **68.8** (v1 said 68.7) |

v3 adds the disclaimer: "these module swaps compare models trained with **both** SFT and RL, so they **do not isolate the RL contribution**."

**Ablation — SFT vs SFT+RL (Table 3, Verina, matched budget) — NEW IN v3, and the most important table in the paper for us:**

| Model | Pass@1 | Pass@10 | Pass@20 | Pass@32 |
|---|---|---|---|---|
| SFT only | 26.9 | 44.9 | 53.9 | 66.1 |
| SFT + RL | 29.1 | 46.0 | 57.1 | 68.8 |
| **Δ** | **+2.2** | **+1.1** | **+3.2** | **+2.7** |

v3's own reading:

> "RL adds a **smaller but consistent 1.1–3.2 percentage points**; the **bulk of performance comes from hierarchical search and supervised training**, and the **single training run does not establish statistical significance**."

Corroborating: Appendix H.9 — training shifts mean *unnormalized* score 282→185 (Verina), 437→329 (Clever), 271→196 (AlgoVeri), i.e. decompositions do get structurally simpler; but that is the SFT+RL pipeline jointly, not RL alone.

**Cross-paradigm (Appendix C, AlgoVeri's 77 aligned-contract tasks).** Published Gemini-3-Flash evaluation: Dafny 40.3%, Verus 24.7%, **Lean 7.8%**; their Lean framework reaches **62.3%**. v3 hedges: "controls the functional contracts but not the end-to-end inference compute, so the 22.0-point difference from Dafny should be interpreted as an **outcome comparison**, not a compute-matched systems comparison." (v1 had instead asserted "proving performance turns out to be comparable across all three systems" — a flatly different claim.)

**Stated limitations (v3 Conclusion, all new).** Not compute-matched; inference cost high despite unsaturated scaling; **RL limited to one run — no across-seed variance or significance**; no comparable token / API-cost / GPU-hour accounting; no per-task cross-system AlgoVeri outcomes; pre-formalized programs assumed; **operator counting is syntactic**; single-procedure scope only (no interprocedural reasoning).

---

## 9. v1 → v3: what changed (read v3)

DIRECTION.md is dated 2026-08-11; **v3 landed 2026-08-10**. Any characterization formed from v1 is now partly stale. Substantive changes:

| # | v1 | v3 |
|---|---|---|
| 1 | RL framed as a co-equal pillar; no SFT-vs-RL ablation | **Table 3 added**: RL = **+1.1 to +3.2 pts**; intro now calls hybrid RL "a **modest refinement**"; "the single training run does not establish statistical significance" |
| 2 | Decomposition score plotted as **higher = better**; "higher scores correlate with higher prove rates" | **Orientation corrected**: the plotted quantity is the *unnormalized* score = **residual difficulty, lower = better**; "**lower** raw scores correlate with higher prove rates." AUROC unchanged at **0.903** |
| 3 | Score "captures a generalizable signal... rather than overfitting to benchmark-specific patterns" | "**does not by itself establish out-of-distribution generalization**" (H.8) |
| 4 | — | **H.3 added**: score is **0/10 on Mathlib**, 0/8 on type-safety+structural; "not a general-purpose measure of mathematical decomposition quality" |
| 5 | "surpassing neural provers up to **84× larger**" | **Deleted**; replaced by "+38.2 points under the reported inference settings"; four separate not-compute-matched disclaimers + Appendix H.4 budget disclosure |
| 6 | AlgoVeri: "proving performance turns out to be **comparable** across all three systems" | Concrete numbers: Dafny 40.3 / Verus 24.7 / **Lean 7.8** for Gemini-3-Flash; ours 62.3 |
| 7 | No decontamination beyond title/description match | **H.2 added**: substring + embedding audits, 0/427 at ≥200 chars, 2/427 flagged by embedding |
| 8 | QC-failed and proof-failed described as **sequential** filters | Corrected: **different denominators, not additive**, "complementary failure modes" |
| 9 | Ablation: no-decomposition baseline **26.4%**; ours 68.7% | **19.6%**; ours **68.8%** |
| 10 | Algorithm 2: unbounded loop, select "highest-scoring goal" | **≤128 iterations**, select **largest operator footprint**, explicit **32-open-goal stop** |
| 11 | Appendix D recommends **`native_decide`** | Replaced with `grind` / decision procedures / explicit recursion (consistent with rejecting `Lean.ofReduceBool`) |
| 12 | Affiliation ⁴ **MiroMind**; Figure 9 caption misnamed baselines as "BFS-Prover-V2 and Göedel-Code-Prover-8B" | **Apodex**; caption fixed to BFS-Prover-V2-32B and Göedel-Prover-V2-32B |
| 13 | — | Related work adds **Quarry** (Zhang et al. 2026) — ranks Rocq decompositions by *predicted hammer solvability*; the nearest neighbour to a "delegability oracle" |

---

## 10. Corrections needed to `DIRECTION.md`

### §2 table — replace the Goedel-Code-Prover row

Current:

> | [Goedel-Code-Prover](https://arxiv.org/abs/2603.19329) (2026-03, Lean 4 code verification) | **Yes** — SFT on 281K decomposition + 151K completion pairs, then GRPO with online Lean verification; decomposition *score* as dense reward, QuickCheck filtering; Qwen3-8B base | Recursive decomposition with independent leaf proving | No; reports inference-time scaling, not train-small/eval-large transfer |

Problems, cell by cell:

**C1 — "Trains decomposition? **Yes**" is right but unqualified.** v3's matched-budget ablation puts RL at **+1.1 to +3.2 points** over SFT-only (one seed, explicitly not significant), and the paper itself now calls RL "a modest refinement." Cell should read *"Yes — but RL is a small delta: SFT-only 66.1 → SFT+RL 68.8 at pass@32 on Verina (+1.1–3.2 pts across budgets, single run, authors decline significance)."*

**C2 — "GRPO with online Lean verification" is wrong as stated.** GRPO's reward is **only** the decomposition score `S`. Completion is **not** RL-trained — it is stabilized by a supervised-replay loss, `J = J_GRPO + λ·J_SFT` with λ=0.08. The sparse verified-proof signal never enters a policy gradient; it only filters which trajectories enter the replay buffer. Lean verification enters GRPO *inside* `S`, as the `𝟙_proof` reduction check and `𝟙_qc` gate — not as a whole-theorem verified reward.

**C3 — "Context isolation? Recursive decomposition with independent leaf proving" is misleading.** Should be **No**. It is a strictly sequential two-stage pipeline (all decomposition, then all completion), so the decomposer never sees a leaf proof only because none exists yet; there is no re-planning loop. The decomposer *does* write proof text (`π_parent`), its prompt carries the entire Lean file including all accumulated `sorry`-bodied lemmas, and decomposition/completion share one set of weights. The paper never uses the term and never argues for it. **This matters for §2's closing "what is actually unclaimed" paragraph: item (a) is now *more* clearly unclaimed than the table implies, not less.**

**C4 — recursion depth is missing and worth a clause.** No depth limit, no depth parameter, no depth statistic reported. It is a flat best-first open-goal worklist (`argmax` operator footprint), ≤128 iterations, ≤32 open lemmas, 30 min/problem. Depth is emergent. Only lemma counts are reported (mean 8.5–17.0).

**C5 — the transfer cell is right but should carry v3's two negatives.** Append: *"v3 Appendix H.3 measures the decomposition score on human decompositions outside code verification: `r > 0` for 9/14 Hoare-style CSLib theorems but **0/10 Mathlib** and 0/8 type-safety/structural — authors' words, 'not a general-purpose measure of mathematical decomposition quality.' H.8: score/provability correlation shown in-distribution only, 'does not by itself establish out-of-distribution generalization.'"*

**C6 — date/version.** Row header says "(2026-03…)". Should be "(v1 2026-03; **v3 2026-08-10**, COLM 2026)" — the revision landed one day before DIRECTION.md and is where the weakened claims live.

### §0 Summary verdict

> "Goedel-Code-Prover (2026-03) did it convincingly in Lean with GRPO over online verifier rewards."

Three corrections in one sentence: (a) **"convincingly"** overstates — v3's own ablation is +1.1–3.2 pts, one seed, no significance, and the authors downgrade RL to "a modest refinement"; (b) **"over online verifier rewards"** is wrong — the GRPO reward is the decomposition score, not verifier rewards (C2); (c) **"in Lean"** should be **"in Lean *code verification*"** — the paper's whole premise is that math methods don't transfer to it, and H.3 shows the reverse direction fails too. Suggested: *"Goedel-Code-Prover (v1 2026-03) did a version of it for Lean **code verification** — GRPO on a dense decomposition score, with completion trained by supervised replay rather than RL; its v3 ablation puts the RL contribution at +1.1–3.2 points over SFT, one seed, not significant."*

The **direction** of §0's verdict survives intact — the brief's novelty claim is still broken on the training side, and the surviving question is still the transfer/mechanism one. If anything the surviving gap is *wider* than §0 assumed.

### §3.1, argument 5

"**Partly false** as of 2026-03" — keep, but the qualifier should note that the trained-decomposition prior art is (i) in code verification, not math, and (ii) only weakly attributable to RL.

### §4 registered priors

> | Harness-RL improves in-distribution (k ≤ k₀) | ~70% (Goedel-Code-Prover is evidence for) |

The cited evidence is much weaker than the parenthetical implies: **+1.1–3.2 points on one benchmark, one seed, no significance, and confounded with a 100-step run on a curriculum that drifts toward easier problems.** Either annotate the evidence strength or revisit the 70%. Flagging, not prescribing — priors are the experimenter's.

### §5.2 — prior art, currently unattributed

DIRECTION.md presents "check the **assembly** first, with the stated lemmas assumed as hypotheses… `r = r_plan × r_leaves`" as "the design gift of this domain" that "retrieval-RLM had no analog." **Goedel-Code-Prover already does exactly the plan-side half**: their `𝟙_proof` *is* `r_plan` — Lean verifies `(L₁∧…∧L_k) ⇒ G` from an LLM-emitted assembly term that must explicitly invoke each lemma. Their `S = v · r` is the same multiplicative factorization. §5.2 should cite it as prior art; what remains genuinely ours is using the factorization for **status separation and credit assignment** (§6) rather than as a ranking score.

### §5.6 — upgrade a guess to a citation, and add the residual hole

> "Goedel-Code-Prover's shaped decomposition-score is the alternative; note it is hackable in principle, which is presumably why they needed QuickCheck filtering."

**Confirmed — drop "presumably."** The paper names the exploit verbatim (`l = [] ∧ l.length > 0` — a false lemma that discharges the parent while shifting the burden to an impossible subtask) and introduces quickcheck precisely as the gate. Add the measured rates: quickcheck discards **31.8–46.4% of runs**; proof reconstruction rejects **44.9–59.4% of iterations**.

Then add what quickcheck does **not** close, because it is DIRECTION.md's own objection 2 with a mechanism attached: **quickcheck tests truth, not difficulty.** A true-but-trivial restatement passes both `𝟙_proof` and `𝟙_qc`; the only thing resisting degenerate decomposition is `r`, a syntactic AST operator count. That is a much thinner defence than "unhackable," and it strengthens the §3.3(2) argument for terminal-only reward + hard budgets + explicit restatement detectors in our v1.

### §5.4 — a live hazard for the size axis

If Family A/B generation ever reaches for an operator-footprint-style syntactic complexity metric to define or validate the size axis, **H.3 is the counterexample**: `r` is zero on 10/10 Mathlib theorems with human-written decompositions. Their metric is calibrated to Hoare triples whose postconditions unfold into many program operators. Validity requirement (a) ("per-node leaf pass-rate flat in k") should be measured by **measured leaf pass-rate**, never by a syntactic proxy borrowed from this paper.

### §7 Decisions still open, item 5

> "Read ProD-RL and Goedel-Code-Prover in full before finalizing §2's positioning."

Goedel-Code-Prover half is now discharged — see this note. ProD-RL remains.

### §8 Sources

Annotate the entry: `arXiv 2603.19329` — **v3 (2026-08-10) is the version to cite**, COLM 2026; weights [`Goedel-LM/Goedel-Code-Prover-8B`](https://huggingface.co/Goedel-LM/Goedel-Code-Prover-8B) (Qwen3-8B base, Apache-2.0) — **no code release found**. Optionally add **Quarry** (Zhang et al. 2026, Rocq decompositions ranked by *predicted hammer solvability*), surfaced in v3's related work — the closest published thing to our proposed delegability oracle, and worth reading before §5.4 is finalized.

---

## 11. What is directly reusable in `rlmath`

- **`operatorcount` / `quickcheck` as Lean meta-programs** — the pattern (custom tactics computing reward components at any proof state) is the right shape for our environment. But per H.3, `operatorcount` itself is inert on math goals; treat it as a template, not a metric.
- **Quickcheck-before-proof-search** as a cheap semantic gate on generated lemma statements, via Plausible (≤1000 trials, native execution). Cheap, and in our Family-A/B generators it doubles as a generator-validity check. Caveat: only works for executable, decidable statements.
- **Rollout-group filtering** (drop groups whose mean reward is 0 or 1) — standard, but they report it as load-bearing.
- **`J = J_GRPO + λ·J_SFT` with λ=0.08** as a concrete recipe for mixing a dense planning reward with a sparse verified signal *without* letting the sparse side become an RL objective. Directly relevant to DIRECTION.md's open decision 4 (whether `r_plan` enters the v1 objective) — their answer was "dense score for planning, supervised replay for proving," and it worked well enough to reach SOTA while the RL delta stayed small.
- **The 30-min/problem, ≤128-iteration, ≤32-open-lemma budget triple** — a real-world calibration point for Phase-0 throughput planning.
- **Their honesty template**: v3's compute-matching disclaimers, single-seed caveat, and H.3 negative-scope result are exactly the evidence discipline DIRECTION.md §6 wants to copy.
