# Recursive Language Models for Formal Theorem Proving

**Direction assessment and experimental design.**

- **Date:** 2026-08-11. Literature snapshot: same date (matters — see §2; the novelty position is time-sensitive).
- **Provenance:** written by Claude (Opus 5) in response to a direction brief from the experimenter,
  who deliberately withheld their own objections and design preferences in order to elicit an
  independent assessment. Everything below is therefore *one* independent reading, not a consensus
  view. The priors in §4 were fixed before seeing the experimenter's own.
- **Evidence base:** `../rl/` — a completed reproduction of the *inference-side* findings of
  Zhang & Khattab, "Language model harnesses are compositional generalizers"
  (alexzhang13.github.io/blog/2026/harness/). Numbers cited from it below are from
  `../rl/analysis/scores.csv` and `../rl/REPORT_NOTES.md`.
- **Verification depth on cited literature:** arXiv 2605.30914 was fetched directly at first
  writing. **Update 2026-08-11:** ProD-RL (2411.01829) and Goedel-Code-Prover (2603.19329) have now
  been read in full (research/prod-rl.md, research/goedel-code-prover.md) and their corrections
  integrated throughout — several original characterisations were wrong in both directions.
  Remaining papers are still characterised from abstracts/search summaries.

---

## 0. Summary verdict

Worth pursuing, but **not for the reason the brief centres**.

The brief's novelty claim — "nobody appears to have RL-trained the recursive decomposition policy
itself over a proof-assistant environment" — is no longer true as of March 2026. ProD-RL (2024)
did a version of it in **Isabelle/HOL**; Goedel-Code-Prover (v1 2026-03) did a version for Lean
**code verification** — GRPO on a dense decomposition score, with completion trained by supervised
replay rather than RL, and its own v3 revision (2026-08-10, COLM 2026) puts the RL contribution at
**+1.1–3.2 points over SFT-only** (one seed, authors declining significance, "a modest refinement").

What survives, and is sharper than the original framing: **nobody has tested whether the RLM
*generalization mechanism* holds in proving** — whether context isolation makes a trained
decomposition policy *transfer* along a size/difficulty axis. The nearest prior result cuts mildly
against the hypothesis: ProD-RL's gains over SFT-without-lemma-proposal decayed with distribution
shift — **+2.1** (AFP test) → **+0.1** (AFP 2023, a *temporal* split) → **−4.9/−1.3** (miniF2F).
But the deep-read (research/prod-rl.md, C5) shows that negative is **confounded**: the paper itself
attributes the miniF2F failure to miniF2F *not requiring hierarchical decomposition at all* —
evidence that a decomposition policy is useless on non-decomposable problems (nearly tautological),
much weaker evidence that decomposition policies fail to transfer. §5.4's constructed families are
decomposable *by construction*, which designs out precisely this confound.

That makes this a live, falsifiable, non-obvious question rather than a greenfield engineering
claim — and a better project for it.

*(2026-08-11, post deep-read: both near-neighbors verified against full texts —
research/prod-rl.md, research/goedel-code-prover.md — discharging open decision #5. Net effect:
the surviving gap is **wider** than this section originally assumed: neither system has context
isolation as a trained interface, and neither ran a size-axis or compute-matched transfer test.)*

---

## 1. The premise

**RLM architecture** (per the blog): a root LM operates a code REPL. Task context lives in REPL
*variables*, not the root's context window. Sub-LM calls are REPL functions; their inputs and
outputs route through variables and need never enter the root's context. Sub-calls may themselves be
RLMs. Key empirical claim: RL-training **only the root** on short tasks generalized to held-out
tasks 8–32× longer, far more efficiently than training on the tasks directly. Proposed mechanism:
task content never enters the root's context, so root trajectories are near-isomorphic across tasks
sharing a structure — the policy learns reusable *decomposition strategies* rather than task
content ("keeping every LM call locally in-distribution").

**The proposal:** port this to Lean 4. Root receives a theorem; its REPL contains a proof-assistant
environment. It can attempt the goal directly or decompose it — state intermediate lemmas, delegate
each to a sub-invocation, assemble returned sub-proofs into a proof of the parent. Then RL-train the
system, potentially including sub-invocations, possibly as one shared self-similar policy playing
every node conditioned on the goal rather than on depth.

### What `../rl/` establishes, and what it does not

Relevant because several arguments below lean on it.

| Blog claim | Status after reproduction |
|---|---|
| Over-window task infeasible direct, fine under harness | **Emphatic yes.** `mrcr-xl` (1.14–1.26M chars): direct 4/4 `context_window_exceeded`, RLM mean **0.998**. `graphwalks-long` (~270k real tokens): direct 14/14 infeasible, RLM 0.714 |
| Harness keeps long trajectories near short ones | **Yes.** Token-similarity 0.26–0.48 (RLM) vs 0.014–0.13 (direct) — a 4–20× gap; length-similarity 0.89–0.94 vs 0.11–0.17 |
| Harness generalizes with length, direct degrades | **Partial.** MRCR RLM flat 0.718 → 0.721 while direct decays 0.729 → 0.637 → infeasible. But **OOLONG reversed** on haiku: RLM degraded *faster* (0.554 → 0.214) than direct (0.571 → 0.357) |
| Emergent strategies + degenerate offload | Yes qualitatively. Degenerate single-subcall offload: **7–36%** of rollouts, zero-shot |
| Harness costs more compute | 2.3–4.7× wall-clock at short lengths (retrieval tasks) |

**Critical scope limit:** `../rl/` verified the *inference-side* mechanism claims only. The
**training** claim — the one this entire direction leans on — is an unreplicated blog result from a
single lab. See objection 5.

---

## 2. Literature position as of 2026-08-11

The brief's gap claim was: those that *train* with RL flatten decomposition into a single CoT
trajectory (no context isolation); those with genuinely recursive isolated structure use frozen
models. That dichotomy was accurate in early 2026 but has been broken on the training side.

| Work | Trains decomposition? | Context isolation? | Transfer/size-axis tested? |
|---|---|---|---|
| [ProD-RL](https://arxiv.org/abs/2411.01829) (Dong, Mahankali, Ma, 2024; **Isabelle/HOL via PISA** — Sledgehammer closes low-level steps, no clean Lean 4 analog; Llemma-7B, 2k ctx) | **Yes** — REINFORCE-style reward-weighted CE (expert iteration + hindsight replay; separate learned 7B value function used *multiplicatively*; **not** GRPO/PPO); a correct novel lemma earns r=1 on the *child's* training example even when the parent fails | **Full proof-text isolation, fully open-loop** — parent never sees child proofs *or statuses*; children inherit the parent's file context | Domain/temporal shift only, **no size axis**: +2.1 AFP test → +0.1 AFP-2023 (temporal) → −4.9/−1.3 miniF2F; the paper attributes the miniF2F negative to miniF2F not requiring decomposition (confound — see §0) |
| [Goedel-Code-Prover](https://arxiv.org/abs/2603.19329) (v1 2026-03; **v3 2026-08-10**, COLM 2026; Lean 4 **code verification**; Qwen3-8B) | **Yes, modestly** — GRPO's reward is the dense decomposition score *S only*; completion is supervised replay (λ=0.08), never RL-trained; v3 matched-budget ablation: SFT-only 66.1 → SFT+RL 68.8 pass@32 (+1.1–3.2 pts, one seed, authors decline significance) | **No** — sequential two-stage pipeline; the decomposer's prompt carries the whole Lean file incl. accumulated sorry-lemmas and it writes the parent proof itself; depth emergent (flat best-first worklist, no depth stat) | No; inference-time scaling only. v3 H.3: decomposition score r>0 on 9/14 CSLib theorems but **0/10 Mathlib** ("not a general-purpose measure of mathematical decomposition quality"); H.8: no OOD claim |
| [DeepSeek-Prover-V2](https://arxiv.org/abs/2504.21801) | Uses recursive decomposition to synthesize **cold-start data**, then flattens subgoal proofs into a single CoT for RL | No (deliberately flattened) | No |
| [MerLean-Prover](https://arxiv.org/pdf/2605.26959) (2026-05) | No — "no finetuning, no custom RL objective"; recursive outer loop over proof plans | Yes | No |
| [RL + recursive inference for formal verification](https://arxiv.org/html/2605.30914) (2026-05, MSc thesis) | Dafny only (GRPO/RLVR); **Lean scaffold uses a fixed base model** | Unspecified in abstract | No transfer experiments |
| [Hilbert](https://arxiv.org/pdf/2509.22819), DeltaProver, POETRY, [DreamProver](https://arxiv.org/pdf/2604.26311) | Inference-time scaffolds / lemma libraries | Varies | No |

**What is actually unclaimed:** the *conjunction* of (a) **closed-loop** RLM-style context
isolation — the root never sees proof text but *does* see child statuses (ProD-RL has full
proof-text isolation but is open-loop: no statuses either; Goedel-Code-Prover has none) — with
(b) an explicit, constructed **size axis**, (c) a train-small / evaluate-large **transfer
measurement** against a compute-matched flat control, and (d) the isomorphism mechanism measured
as a *mediator* rather than assumed. Post deep-read, (b)–(d) are individually unclaimed by every
system in this table; (a)'s delta over ProD-RL is the status feedback loop plus the frozen
measured leaf (§5.1 honesty note).

Note the implication for the brief's five arguments: arguments 1, 3, 4, 5 all support the
*uncontested* half of the idea (recursive decomposition helps proving — known since DSP/POETRY/DSV2
and now trained by Goedel-Code-Prover). Only argument 2 supports the *novel* half (isolation →
isomorphism → RL that transfers). Argument 2 is the weakest of the five (§3.2).

---

## 3. Assessment

### 3.1 The brief's five arguments, scored

| # | Argument | Verdict |
|---|---|---|
| 1 | Verifiable reward at every recursion level; unhackable and dense in the tree | True and genuinely special — **but** unhackable only *per node*; see objection 2 |
| 2 | Proof strategy = small set of content-independent shapes → trajectory isomorphism | **The crux, and oversold** — §3.2 |
| 3 | Unlimited recursion natural; policy self-similar; depth as generalization axis | True in principle; at this scale depth ≤ 2 is what matters. Depth is better used as a held-out *probe* than a training axis — now evidence-backed: ProD-RL trained at depth 3 with gains concentrated at ground-truth proof depth ≤ 2 (C10) |
| 4 | Training sub-invocations is meaningful here (unlike frozen retrieval sub-calls) | True but **premature** — defer (objection 3) |
| 5 | The composition is an unpicked gap | **Partly false** as of 2026-03; the surviving gap is the mechanism/transfer test, not the system (§2) |

### 3.2 The central disanalogy

In the retrieval RLM, **sub-call easiness is guaranteed by construction**. Chunking is
content-oblivious: any 2M-token document splits into 4k-token chunks, each trivially
in-distribution for the sub-model, *without the root understanding anything*. The root can be nearly
blind to content and still win. `../rl/` shows this starkly — on GraphWalks the root wrote a
pure-Python BFS and made **zero** sub-calls (`mean_subcalls = 0.000`, both splits) while scoring
0.929 / 0.714.

In theorem proving, **producing in-distribution subgoals is the mathematical work.** A hard theorem
does not split into easy lemmas by any content-oblivious operation; knowing *which* intermediate
lemma bridges A to C is the insight. "Induction, then cases" is a content-free shape, but *what to
induct on* and *how to strengthen the hypothesis* is content — and it sits in the root's context,
because the root must write the lemma statements.

So the faithful transplant of the hypothesis is **not** "isolation keeps every call
in-distribution" (in proving that is not architectural; it is contingent on decomposition quality).
It is:

> **(i)** RL can teach a policy to emit child goals that a fixed leaf prover reliably closes
> (learnable *delegation calibration*), and
> **(ii)** because the root's context excludes proof *content* — only statements and child statuses
> enter — what it learns is invariant along decomposition-tree size, so training on small trees
> transfers to large trees where flat-RL transfer does not.

Part (i) is shared with ProD-RL and Goedel-Code-Prover. **Part (ii) is the RLM-specific payload and
is untested by anyone.** The whole project should be organised around (ii).

### 3.3 Objections, ranked

1. **The disanalogy above** — §3.2. Fixable by reframing, not by engineering.

2. **Degenerate recursion = structured resampling.** The trivially available "decomposition" is
   restating the goal as its own single lemma: recursion as a retry button. `../rl/` measured
   degenerate single-subcall offload at 7–36% *zero-shot*; RL will find it immediately if it pays.
   Subtler and more important: because the policy chooses its own subgoals, any per-node reward is
   densified on a **policy-chosen distribution**. The brief's "essentially unhackable" is right
   per-node and wrong system-wide — a policy can farm trivial subgoals. Mitigations: terminal-only
   reward, hard node/call budgets, explicit restatement detectors. Prior art on the detectors (C8):
   ProD-RL ships two such controls — discarding proposals that directly imply the theorem (a
   restatement filter) and stripping lemmas whose references can be deleted with the proof still
   verifying; cite, don't reinvent. But **"did it learn decomposition, or did it learn to spend
   more compute?" must be a first-class measured distinction**, or the headline result is
   uninterpretable.

3. **Reward density ≠ clean credit assignment.** A child that fails on a *false or
   unprovable-within-budget* lemma generates gradient noise for the child policy — the parent's
   error, the child's punishment. ProD-RL hand-built partial credit for precisely this — hindsight
   augmentation on the *child's* example (a proved lemma scores 1 regardless of the parent's fate)
   plus a learned value function absorbing child stochasticity out of the parent's weight; both
   halves are directly reusable here (C9). Partially
   defused here by the two-stage check (§5.2), which is a real advantage retrieval-RLM never had.
   This is also the main reason to **defer joint/shared-policy training**: with a frozen leaf,
   delegation is calibration against a *fixed, measurable* oracle; with a learning leaf it chases a
   moving target, and hierarchical-RL non-stationarity is a poor first RL project.

4. **Current benchmarks do not need context isolation.** miniF2F/PutnamBench proofs fit comfortably
   in one window. The regime where isolation *must* win — proof artifact ≫ context window — barely
   exists in public benchmarks and has to be constructed. Corollary: **the compute-matched baseline
   is brutal.** Flat best-of-N with a strong open prover is very strong at benchmark scale, and
   harness overhead was 2.3–4.7× wall-clock in `../rl/` *for retrieval* — it will be larger here. A
   win at equal attempt-count but a loss at equal compute is a weak result. Note that DeepSeek
   deliberately flattened recursion into single-context CoT for training; assume they had reasons.

5. **Compound replication risk.** `../rl/` verified the blog's *inference-side* claims. The training
   claim is unreplicated. This direction would test "does their training result replicate" and
   "does it transfer to a new domain" *simultaneously*, as a first RL project. Mitigated in §5.5 by
   (a) a zero-shot phase in front — if the inference-time signatures are absent in proving, training
   will not rescue them — and (b) a **known-recipe flat-RL control trained first**, to validate the
   trainer before the novel arm touches it.

6. **The root must emit well-formed Lean.** Writing elaborable lemma statements is a
   prover-adjacent skill that general instruct models are mediocre at. This is the analog of the
   XML-vs-fences parser bug that silently zeroed Claude's RLM scores in `../rl/` (11/14 on
   oolong-long) — except **better**: statement elaboration fails *loudly* and instantly, with no
   proving required, so it is a bounded retry loop and a trainable signal rather than a silent
   collapse. Still: measure ill-formed-statement rate from day one.

### 3.4 What each failure would teach

Each phase gate in §5.5 is designed so that failing it kills one specific assumption:

- **Phase 1 fails** (cannot hold per-node difficulty flat while scaling k) → the size axis is not
  constructible in mathematics the way it is in retrieval. That is itself a publishable finding
  about the disanalogy in §3.2.
- **Phase 2 fails** (isolation buys nothing zero-shot at matched compute) → the isolation premise is
  dead at this scale and DSV2's flattening choice is vindicated. Write it up, stop, having spent
  ~6 weeks and <$1k.
- **Phase 3 transfer fails** → a **stronger and cleaner negative than ProD-RL's**: its transfer
  negative was confounded by a non-decomposable OOD benchmark (C5); here the families are
  decomposable by construction and the control is compute-matched, so a failure indicts the
  mechanism itself. A real scientific answer either way.
- **Degenerate autocurricula dominate** → a finding about verifiable-reward RL in general, of
  interest well beyond proving.

The only uninformative failure is "the trainer never worked," which the control-first sequencing
exists to catch cheaply.

---

## 4. The sharpest testable question

Not "can an RLM prove theorems" (MerLean-class scaffolds already do, frozen), and not "can RL
improve decomposition" (Goedel-Code-Prover: yes, in code verification). It is the **transfer
slope**:

> Fix a frozen leaf prover. Build problem families with a controllable decomposition-size parameter
> **k** and per-node difficulty **flat in k**. RL-train (a) a context-isolated decomposition root
> and (b) a flat prover, on **k ≤ k₀ only**. At **k ≫ k₀** — including k beyond flat feasibility —
> does (a)'s improvement transfer while (b)'s does not, with transfer **mediated by trajectory
> isomorphism** (content-masked trajectory similarity across k) rather than by structured
> resampling (compute-matched, restatement-audited)?

This is the blog's money experiment (train 64k → eval 2M) transplanted, with the one ingredient
mathematics does not natively supply — a structure-preserving scaling knob — supplied by
construction. It contains the mechanism claim as a *measurement* (isomorphism as mediator), which is
what makes it science rather than a systems demo, and what keeps it publishable even if a bigger
prover ships next month.

### Registered priors (fixed 2026-08-11, before any runs)

| Claim | Prior |
|---|---|
| Environment is feasible to build solo at this budget | ~99% |
| Zero-shot beyond-window feasibility asymmetry reproduces in proving | ~90% |
| Zero-shot isomorphism signature present, but weaker than in retrieval | ~75% |
| Harness-RL improves in-distribution (k ≤ k₀) | ~70% (Goedel-Code-Prover is evidence for) |
| **Headline: harness transfer beats flat transfer at matched compute** | **~35–45%** |
| Visible miniF2F/PutnamBench gains at this budget | ~15% |

The headline sitting near a coin flip is the argument *for* running it. If it were 85% it would be
engineering; if it were 10% it would be a bad bet.

**Prior updates (2026-08-11, post deep-read — original table left untouched per pre-registration
discipline):** two opposing evidence shifts. Goedel-Code-Prover's v3 ablation weakens the
"harness-RL improves in-distribution" evidence (its RL delta is +1.1–3.2 pts, one seed):
70% → **65%**. ProD-RL's transfer negative turns out confounded (C5), slightly raising the
headline's floor. Headline stays **35–45%**, the two updates roughly offsetting.

---

## 5. Experimental design

Scale assumption: solo practitioner, strong systems background, first serious RL project,
single-to-few GPUs, open-source stacks. Every phase ships an independently valuable artifact.

### 5.1 Architecture: a decomposition MDP, not a free REPL (v1)

The RLM essence is **context isolation via external state**; the REPL was Zhang & Khattab's
vehicle for it, not the point. For proving, be *more* faithful than the scaffolding literature: the
harness holds all proof text in variables, and the root **never sees a proof** — only goal
statements and child statuses.

- **Environment state:** goal store (id → statement), proof store (id → proof text,
  **root-invisible**), frozen leaf-prover adapter, composer, kernel checker, sanitizer (axiom audit,
  no `sorry`, environment diff).
- **Root action space (structured):** `decompose(goal, [lemma statements] + assembly tactic block)`
  | `close(goal)` → leaf prover | `abandon`.
- **v1 is single-shot:** the root emits the whole plan in one completion (~300–800 tokens). This
  matters twice: it makes training a *vanilla* GRPO-on-completions problem — commodity recipe, no
  multi-turn machinery, which is the right choice for a first RL project — and it makes root tokens
  ~10× cheaper. Multi-turn adaptivity (react to failed children, restate, retry) is v1.5; the
  zero-shot phase can measure what adaptivity is worth before paying for it.
- **Depth:** v1 trains depth-1 (root states lemmas, leaves close them). **Depth-2 is a zero-shot
  eval probe**: apply the trained policy recursively to its own failed children. Recursion becomes a
  held-out generalization *measurement* instead of an upfront engineering burden.

**Design note — why the action space is restricted.** A free REPL would leak the experiment. In
`../rl/`, given a free REPL on GraphWalks, the root wrote a Python BFS and made zero sub-calls; the
strategy detectors caught it. The analog here is a root that string-generates whole Lean proofs
programmatically — at which point the experiment measures program synthesis, not decomposition
policy. Constrain the action space to decomposition itself. A free-REPL "ecological" arm can be
added later as a separate comparison.

**Honesty note vs ProD-RL (C3).** Full proof-text isolation is *not* novel — ProD-RL already has
it, in a stricter open-loop form (no child statuses either), and its single-shot lemma-proposal
step is near-isomorphic to this v1 root. The honest deltas, in the order they matter: (a) a frozen,
separately-measured leaf prover — a *measurable* delegation oracle — vs the same weights recursing;
(b) a constructed size axis with compute-matched controls vs naturalistic AFP; (c) a structured
action space vs inline invoke-tags in free proof text; (d) mechanism measurement (masked-trajectory
isomorphism) vs none; (e) Lean 4/Mathlib vs Isabelle+Sledgehammer.

### 5.2 Two-stage verification — the design gift of this domain

Check the **assembly** first, with the stated lemmas assumed as hypotheses (fast: does the plan even
suffice?), then discharge the leaves. Reward factorizes:

```
r = r_plan × r_leaves
```

This separates *bad plan* from *unlucky leaf* — per-decomposition binary feedback independent of
leaf stochasticity. Retrieval-RLM had no analog, and it directly addresses objection 3. Not novel
in proving, though (C7): ProD-RL's training weight `w = 𝟙[locally correct] · ∏ᵢ V_φ(lᵢ) · γ^h` is
essentially this factorization, with sorry-based local-correctness checking playing the role of the
hypothesis-binder plan check. The claimable delta is the leaf term: ProD-RL *estimates* it with a
learned 7B value function; a frozen leaf with a measured pass-rate bank lets us *measure* it.
Caveat: `r_plan` alone is hackable by restatement, hence the detectors and budgets in §5.6.

### 5.3 Model roles and stack

| Role | Choice |
|---|---|
| Leaf prover (frozen) | DeepSeek-Prover-V2-7B in non-CoT mode (cheap, strong) or Goedel-Prover-V2-8B, behind a cache keyed by α-normalized statement |
| Root (trained) | Qwen3-4B or 8B instruct + LoRA |
| Zero-shot reference roots | one 30B-class open model; optionally claude-haiku via the Anthropic backend already built in `../rl/eval/run_eval.py`. **2026-08-11:** both available through Prime Inference on one OpenAI-compatible endpoint (`qwen/qwen3-30b-a3b-instruct-2507` $0.20/$0.80 per 1M — the exact `../rl` base model — and `anthropic/claude-haiku-4.5`), so Phase 2 needs no local GPU and none of `../rl`'s 10–15 min/sample prefills. Prover models are **not** served: the leaf still needs a rented GPU (~$3.2/hr H100). |
| Verification | Kimina Lean Server (warm Mathlib, batched) on a large-CPU box |
| Training | environment in `verifiers` format → directly publishable to Prime Intellect's Environments Hub, trainable with prime-rl |

### 5.4 Task design — where the scientific validity lives

**Leaf bank.** Mine ~5–20k statements the frozen leaf closes at pass@8 ∈ [0.25, 0.9] from
Lean-Workbook + Mathlib-derived exercises; store measured pass rates. Useful as an artifact in its
own right, and it provides a ground-truth *delegability oracle* against which policy calibration can
be measured.

**Family A — bridge chains.** Prove `R(a, z)` (inequality / divisibility / inclusion) composed by
the generator from k hidden intermediate steps, sampled as walks in a relation graph over bank
facts. Only the endpoints appear in the statement, so the policy must *invent* the intermediates.

**Family B — case trees.** Goals over sum / union / piecewise structure that split into k
bank-adjacent leaves.

**Validity requirements, checked at generation time:**

| # | Requirement | Why |
|---|---|---|
| a | Per-node leaf pass-rate **flat in k** | *The* validity metric for the entire size axis. Without it, k confounds size with difficulty and the transfer plot means nothing |
| b | Oracle-replay (generator's own decomposition) solves ≥70% at every k | Ceiling estimate; separates "policy failed" from "task impossible" — **but see (b′): it is coupled to (c) through the attempt budget** |
| c | Leaves resist automation (`aesop`/`omega`/`simp` run at gen time; auto-closable leaves discarded) | Otherwise the experiment measures tactic dispatch |
| d | Flat-prover solve rate decays in k | The axis must actually stress the control |
| e | A top tier where full proof text exceeds the window | The regime where isolation *must* win — the claim-2 analog |

**(b′) — requirements (b) and (c) are in tension, and the attempt budget is what reconciles them
(found 2026-08-13 by the ladder review; not previously stated anywhere).** (c) pushes leaf
difficulty *down* toward the corridor's [0.25, 0.9] with a target mean of 0.45, so the flat arm
cannot win by tactic dispatch. But oracle replay must close **every one of k leaves**, so the
ceiling is `(1 − (1−p)^a)^k` for per-leaf rate `p` and `a` attempts per leaf — and it collapses in
k. Under the **shipped** `Budgets` (`leaf_attempts_per_lemma=4`, `max_total_leaf_attempts=64`,
so `a = min(4, 64//k)`):

| per-leaf p | k=2 | k=4 | k=8 | k=16 | k=32 |
|---|---|---|---|---|---|
| 0.923 (case_tree as shipped) | 1.000 | 1.000 | 1.000 | 0.999 | 0.827 |
| **0.45 (the corridor target)** | 0.825 | **0.681** | **0.464** | **0.215** | **0.000** |
| 0.25 (corridor floor) | 0.467 | 0.218 | 0.048 | 0.002 | 0.000 |

So **hitting the corridor target breaks gate (b) from k=4 upward** — and it does so silently,
because both numbers look healthy in isolation. The current family passes (b) only by being too
easy, i.e. by failing (c). This is not an argument against the corridor; it is a statement that
`Budgets` was set for a family that never had one.

`a` is the free variable. At a flat 8 attempts per leaf, p=0.45 yields 0.983 / 0.967 / 0.935 /
0.874 / 0.764 — (b) holds at every k. Attempts needed for ≥70%: `{k=2: 4, 4: 5, 8: 6, 16: 7,
32: 8}` at p=0.45, so `max_total_leaf_attempts` must scale roughly as `8k` (256 at k=32), not sit
at a flat 64 — the flat cap is what starves k=32 down to 2 attempts per leaf. Raising it costs
Phase-2/3 GPU linearly, which is the real trade and belongs to whoever owns the compute budget.

**Consequence for reading any corridor measurement:** a per-leaf mean of 0.45 does **not** by
itself satisfy (b). Report `(1 − (1−p)^a)^k` alongside the corridor numbers, for the shipped
budget *and* a raised one, or (b) will be assumed rather than checked — which is how (a) got
assumed for bridge_chain.

**Tier B (external validity):** miniF2F-test and a PutnamBench subset. Report honestly; expect
movement only on the hard tail where flat pass@N ≈ 0. Do not stake the thesis here.

### 5.5 Phases

| Phase | Weeks | Content | Artifact | Gate (and lesson if failed) |
|---|---|---|---|---|
| **0** | 1.5–2 | Environment: goal extraction (`extract_goal`), harness, leaf adapter + cache, sanitizer, Kimina integration | **Environment published to Environments Hub** + leaf pass-rate bank | ≥2–3k verified leaf attempts/hr (fail ⇒ infra infeasible solo; low risk, all components exist) |
| **1** | 2 | Family generators + calibration against §5.4 requirements | Datasets + datasheets + oracle ceilings | Leaf difficulty flat in k; oracle ≥70% (fail ⇒ **size axis unconstructible in math** — a finding) |
| **2** | 2–3 | Zero-shot study: {flat 1-shot, flat best-of-N compute-matched, flat-CoT-decomposition, isolated-RLM} × roots × k-grid, plus tier B | Standalone report, publishable regardless of outcome | Isolated must beat flat-CoT somewhere real **at matched compute** (especially beyond-window), and the isomorphism signature must exist (fail ⇒ **isolation premise dead at this scale**; write up, stop) |
| **3** | 4–6 | RL: **first** flat-GRPO control on the leaf prover (known recipe — validates the trainer), **then** harness-GRPO on the root, k ≤ 8. Eval k ∈ {8, 32, 64, 128} + tier B + cross-family + depth-2 probe throughout | Checkpoints + the transfer-slope figure (the money plot) | Control must train (fail ⇒ fix trainer, not science). Harness must improve at k ≤ 8 (fail ⇒ harness-trainability finding). Transfer then resolves empirically either way |
| **4** | open | Only on Phase-3 signal: shared self-similar policy, joint leaf training, multi-turn adaptivity, hindsight relabeling for false-lemma noise | — | — |

**Stack updates (2026-08-12, from Prime's July/Aug releases — verifiers 0.3.0 multi-agent layer +
prime-rl 0.8.0 algorithms layer; we already sit on the enabling substrate):**
- **Phase 3, services gap:** before building tunnel plumbing, spike modeling the frozen leaf as a
  verifiers `Agent` with its own `Runtime` (the `UserSimEnv` frozen+trainable pattern) — if the
  framework manages leaf execution, hosted rollouts may need no side-channel services at all.
  **Spike survival requirements (strategist 2026-08-12, pass/fail criteria of the spike itself):**
  (a) the normalized leaf cache must still intercept every leaf call — it is load-bearing for cost
  *and* for making degenerate restatement nearly free to observe; (b) the `leaf_id` provenance
  guard must travel onto bank/episode rows unchanged. If either dies in translation, keep the
  process-global wart — it is cheaper than the fix.
- **Phase 3, cold start — a scientific decision wearing an infrastructure costume (strategist
  2026-08-12); it does not get made at the tooling layer.** The danger is real (all-fail GRPO
  groups → zero advantages → nothing trains; cf. Goedel-Code-Prover's 281k-pair SFT), but warm-up
  touches the headline measurement twice: **symmetry** (whatever warm-up the root gets, the flat
  arm gets the matched equivalent, and distillation compute enters the compute-matching) and
  **attribution** (distilling decomposition *content* from a frontier teacher means transfer at
  large k could be teacher priors surviving, not RL-under-isolation). Escalation ladder, in order:
  (1) primary defense is **curriculum, not estimator or warm-up** — start at small k with leaves
  from the high-pass-rate end of the band, where group degeneracy mostly doesn't arise;
  (1.5) **few-shot exemplars in the root prompt** (strategist, 2026-08-12, after first light):
  one complete worked decomposition (statements + assembly) as inference-time context — none of
  OPD's symmetry/attribution costs since it is trivially matched across arms and roots. Motivated
  by the data: 12/12 zero-shot failures were `plan_invalid` at *stage-1* — lemma statements
  elaborated clean, assemblies failed — which localizes to a missing affordance (what a working
  assembly block looks like), not necessarily a capability wall. Root-roster diagnostic before
  any escalation past this rung: qwen3-30b few-shot re-run, haiku few-shot, one 100B-class open
  model, opus as ceiling — a handful of episodes each. If NO root decomposes few-shot at k=2,
  that is registered evidence rung 3 is unavoidable; if qwen few-shot assembles, the cold-start
  problem was a prompt gap and priors barely move;
  (2) format-compliance-only warm-up (wire format + well-formed statements, no strategy content);
  (3) strategy distillation only if GRPO still flatlines on in-band tasks at small k. MaxRL stays
  a fallback estimator, not a substitute for (1). **Scope is decided by Phase-2 data** — the 100%
  restatement figure is n=3 from one model; the zero-shot study measures decomposition rates
  across roots and k, which is the datum that sets warm-up scope. **Any warm-up adopted
  re-registers the affected §4 priors in this document, dated, before the run.**
- **Phase 4:** Hierarchical GRPO (role-aware credit in multi-agent episodes) removes the
  infrastructure argument for deferring joint root+leaf training; the attribution argument for
  root-only-first stands unchanged. Far-future note: their proposer-solver learnability reward
  `4·rate·(1−rate)` is the [0.25, 0.9] band as a *trained objective* — a trained family proposer
  is the Phase-4+ version of Phase 1, with §3.3(2)'s degenerate-autocurriculum caution attached.

### 5.6 Training recipe and budget

- Single-shot decomposition completions; **G = 8–16** samples per problem.
- **Terminal reward** = sanitized, kernel-verified root closure. `r_plan` used for diagnosis and
  ablation, not as the primary objective in v1.
- **Hard budgets** (max lemmas, max leaf attempts) rather than cost *penalties* — penalties suppress
  decomposition before it has a chance to pay off. Goedel-Code-Prover's shaped decomposition-score
  is the alternative; note it is hackable in principle, which is presumably why they needed QuickCheck
  filtering. Counter-data-point worth carrying (C8): ProD-RL paired a *soft* length penalty
  (`γ^h`, γ = exp(−0.0005)) with an explicit exploration subsidy for decomposing (forced
  invoke-tokens on the top half of the batch) — penalty-plus-subsidy is the more informative
  precedent if hard budgets alone stall decomposition.
- Leaf calls **cached and deduped across the GRPO group**. Convenient side effect: degenerate
  restatement policies hit cache, so they cost almost nothing to observe.
- **Envelope:** ~300 steps × 64 problems × G8 ≈ low-single-digit 10⁹ generated tokens before
  caching, ~1–2×10⁹ after → **2–4 rented H100s for 2–3 weeks including false starts, ≈$2–5k**.
  Phases 0–2 under $1k (mostly CPU plus one inference GPU). Fallback: 4B root on 1×H100, slower
  iteration. Publishing the environment may unlock Prime Intellect compute credits — worth asking
  early. Sanity anchor (C11): ProD-RL trained its 7B in ≈8 GPU-days SFT + ~30 GPU-hours RL on
  A100s — comfortably inside this envelope.

### 5.7 Metrics and registered predictions

Maintain a `REPORT_NOTES.md`-style claim table, **written before Phase 2 runs** (per §4 priors):

| ID | Prediction |
|---|---|
| P1 | Beyond-window feasibility asymmetry: flat arm infeasible where harness succeeds (~90%) |
| P2 | Zero-shot content-masked trajectory isomorphism: harness ≫ flat (~75%) |
| P3 | **Transfer slope: harness-RL > flat-RL at matched compute (~35–45%) — the bet** |
| P4 | Degenerate-restatement rate rises under RL; hard budgets control it (expect it appears) |
| P5 | Tier-B hard-tail movement (~15%) |
| P6 | Cross-family transfer: train bridge chains → eval case trees (stretch; the true content-independence probe) |

**Key instrument:** extend `../rl/analysis/traj_metrics.py` with **content masking** — replace
statement tokens with placeholders and compare the remaining scaffolds. Raw token similarity will
understate isomorphism here, because roots legitimately see statements (unlike in retrieval, where
they need not).

**Status separation (non-negotiable).** Distinguish, in the result rows themselves:
`plan_invalid` / `leaf_failed` / `budget_exhausted` / `context_window_exceeded` /
`statement_ill_formed`. See §6.

---

## 6. Reuse from `../rl/`

Direct lifts:

- **`eval/run_eval.py` cell structure** — one JSONL per (family, k, arm, system), resumability that
  skips ids *including error rows*, plus `repair_errors.py` for explicit retries.
- **Analysis chain** — `summarize.py` → `score_figs.py` → `traj_metrics.py` (+ content masking) →
  `strategy_stats.py`, extended with new detectors: restatement similarity, delegation rate,
  plan-valid-but-leaf-failed attribution, ill-formed-statement rate.
- **`report/build_report.py`** and the claim-table-first REPORT_NOTES discipline.
- **Anthropic backend** for a frontier zero-shot reference arm.

Operational lessons that transfer:

- Single-writer concurrency discipline around the stateful environment (the `rlms` `LocalREPL` did
  process-wide `os.chdir`; threaded instances raced. A Lean server session pool has the same shape
  of hazard).
- **Format compliance is a first-order failure surface**, not a detail — it silently zeroed whole
  cells in `../rl/`. Here it fails loudly, which is a gift; instrument it anyway.
- Never trust token estimates. `../rl/` used chars/3.5 and was wrong by ~2× on hash-dense text.
  Measure statement and proof sizes directly.

**The most important thing to copy is the evidence discipline.** `../rl/` recorded over-window runs
as `context_window_exceeded` rather than score-0, which kept "the task was impossible for this arm"
(feasibility evidence) from contaminating "this arm scored worse" (degradation evidence). The exact
analog here: a flat arm failing at k=128 because the proof cannot fit is **feasibility** evidence
and must not enter mean-score comparisons. Likewise `leaf_failed` vs `plan_invalid` vs
`budget_exhausted` need that same status separation from day one, or Phase 3's transfer plot will be
uninterpretable after the fact.

---

## 7. Decisions still open

1. **Repository:** own git repo for `rlmath/`, or shared history with `../rl/`? (Leaning own repo —
   different deliverable, and the environment is separately publishable.)
2. ~~Leaf prover choice~~ **RESOLVED 2026-08-12: DeepSeek-Prover-V2-7B non-CoT** (bake-off,
   same-slice pass@8, bf16 vLLM). DSV2: band-mass 5–8%, ~4 s/attempt. Goedel-Prover-V2-8B's
   quality is causally tied to its 16k+ CoT budget (capping to 8k: matched statement 4/8 → 0/8
   verified while proofs still parse) and ~29 s/attempt at the working budget — operationally
   incompatible with the harness inner loop. Selection was band-fit **at the operating profile**,
   per the recorded method; revisit only if leaf budgets change. Full evidence:
   PHASE0_NOTES 2026-08-12 entry, analysis/bakeoff_final.txt, data/bank/bakeoff_*.jsonl.
3. **Family A vs B first.** Bridge chains are the cleaner size axis; case trees may calibrate more
   easily. Phase 1 should probably attempt A and keep B as fallback.
4. **Whether `r_plan` enters the v1 objective** or stays diagnostic-only. Recommend diagnostic-only
   in v1, ablate in Phase 3.
5. ~~Read ProD-RL and Goedel-Code-Prover in full before finalizing §2's positioning~~ **Done
   2026-08-11** — research/prod-rl.md (corrections C1–C11) and research/goedel-code-prover.md
   (§10, C1–C6); all corrections integrated throughout this document.

---

## 8. Sources

- [ProD-RL — Formal Theorem Proving by Rewarding LLMs to Decompose Proofs Hierarchically (arXiv 2411.01829)](https://arxiv.org/abs/2411.01829)
- [Goedel-Code-Prover — Hierarchical Proof Search for Open State-of-the-Art Code Verification (arXiv 2603.19329)](https://arxiv.org/abs/2603.19329) · [weights](https://huggingface.co/Goedel-LM/Goedel-Code-Prover-8B)
- [DeepSeek-Prover-V2 (arXiv 2504.21801)](https://arxiv.org/abs/2504.21801)
- [Hilbert (arXiv 2509.22819)](https://arxiv.org/pdf/2509.22819)
- [MerLean-Prover — A Recursive Looping Harness for Lean 4 (arXiv 2605.26959)](https://arxiv.org/pdf/2605.26959)
- [Automating Formal Verification with RL and Recursive Inference (arXiv 2605.30914)](https://arxiv.org/html/2605.30914)
- [DreamProver (arXiv 2604.26311)](https://arxiv.org/pdf/2604.26311)
- [Prime Intellect — Recursive Language Models: the paradigm of 2026](https://www.primeintellect.ai/blog/rlm)
- Zhang & Khattab — Language model harnesses are compositional generalizers (alexzhang13.github.io/blog/2026/harness/)
- `../rl/REPORT_NOTES.md`, `../rl/analysis/scores.csv` — reproduction of the above blog's inference-side findings

---

## §7. Phase 2 — registered before the run (2026-08-13)

The project's live risk is that three days of work have produced a great deal of evidence about
*task construction* and none about *decomposition transfer*. This run exists to change that ratio,
and it is designed so that a null result is informative rather than merely disappointing.

### What is being measured

The inference-side analogue of the transfer slope: **does the decomposition arm's advantage over
the flat arm grow with k?** Both arms get the same problems, the same few-shot treatment (rung 1.5
is settled) and the same scoring path; only the harness differs.

| | |
|---|---|
| family | `case_tree` preset `v2` — the shipped rung, deliberately |
| k-grid | 2, 4, 8 |
| n | 20 problems per k |
| arms | `direct` (flat), `decomp` — both `--few-shot`, symmetric exemplars |
| roots | `qwen3-30b-a3b-instruct-2507` (the ../rl base model) and `claude-haiku-4.5` |
| leaf | DeepSeek-Prover-V2-7B non-CoT, **16 attempts/leaf** (§5.4(b′), task #22) |

**Why `v2` and not a hardened rung.** `v2`'s leaves measure 0.847, so the oracle ceiling is ≈1.0
and a decomposition that is *correct* will actually close. The hardened rungs sit at ~0.30, where
even a perfect plan fails often — which would confound "the root cannot decompose" with "the leaf
prover could not finish." For a first signal, the leaf must not be the bottleneck. `v2`'s goals
still resist the full automation battery (V0 held at every k), so the flat arm gets no free win.
The cost of this choice is stated up front: `v2` fails the corridor at the *leaf* level, so this
run measures the **mechanism**, not the final calibrated experiment.

### Registered predictions

1. **Direct-arm solve rate decays in k** — DIRECTION §5.4(d), never yet measured for case_tree.
   Predicted: qwen3-30b roughly 0.35 / 0.10 / 0.02 at k=2/4/8; haiku 0.60 / 0.25 / 0.05. If the
   flat arm does *not* decay, the k-axis is decorative for this family too and that is the finding
   — it is what killed bridge_chain.
2. **Decomp beats direct at k=8, and the gap widens with k.** This is the premise of the whole
   project. Predicted gap (decomp − direct): ≈0.0 at k=2, +0.10 at k=4, **+0.20 at k=8**.
3. **Decomp's own solve rate also decays**, just more slowly — predicted 0.35 / 0.25 / 0.20.
   A *flat* decomp curve would be a stronger result than predicted and should be treated with
   suspicion until the plans are read.
4. **The dominant decomp failure at k=8 is `plan_invalid`, not `leaf_failed`** — the two-stage
   check exists precisely to separate these. If it is `leaf_failed` instead, the leaf budget is
   still wrong and #22 needs revisiting before anything else is concluded.

### The decision this run informs

- **Gap widens as predicted** → the mechanism is real at inference time, RL training (Phases 3–4)
  is worth its cost, and the corridor work resumes with a purpose.
- **Gap flat or negative at every k** → the premise is in trouble. Before abandoning it, check the
  status split: a gap hidden behind `plan_invalid` at 90% is a *format/prompting* problem, not
  evidence against decomposition. If plans are valid and decomp still does not win, that is a real
  negative and it should be written up as one.
- **Direct arm does not decay in k** → the family cannot support the axis, same defect as
  bridge_chain, and no amount of leaf calibration fixes it.

Registered before any Phase-2 datum exists. Whatever comes back, the numbers go in the repo
against these lines.

### §7.1 MEASURED — Phase 2 (2026-08-13, pod `ct-phase2`, invoice $12.83)

215 episodes, case_tree v2, 11 of 12 cells (haiku k=8 direct not run — the pod was terminated
after haiku k=4 direct measured 0/20, so that cell was near-certainly 0.000 and not worth $4).

**Solve rate by (root, arm, k):**

| root | arm | k=2 | k=4 | k=8 |
|---|---|---|---|---|
| qwen3-30b | direct | 0.150 | **0.000** | **0.000** |
| qwen3-30b | **decomp** | **0.500** | 0.000 | 0.000 |
| haiku-4.5 | direct | 0.350 | 0.000 | — |
| haiku-4.5 | decomp | 0.300 | 0.000 | 0.000 |

**1. The k-axis is real for case_tree.** The direct arm decays to zero by k=4 for both roots.
DIRECTION §5.4(d) — "flat-prover solve rate decays in k" — **holds**, which is exactly what
bridge_chain failed. The family supports the experiment.

**2. Decomposition beats the flat arm at k=2 for the RL target, by a lot**: 0.500 vs 0.150,
**+0.35**. It does *not* help the stronger root (haiku 0.300 vs 0.350, −0.05). Decomposition
helps the model that cannot do it alone — which is the interesting direction, since qwen3-30b is
the Phase-3 training target.

**3. Above k=2 everything is zero, through TWO distinct bottlenecks — and neither is "the harness
does not work".**

*(a) Stage-1 plan validity collapses with k, and it is root-dependent:*

| root | k=2 | k=4 | k=8 |
|---|---|---|---|
| qwen3-30b | 14/20 (70%) | 3/20 (15%) | **0/20 (0%)** |
| haiku-4.5 | 14/20 (70%) | 10/20 (50%) | 6/15 (40%) |

*(b) Even valid plans do not close.* Of the 19 stage-1-valid plans at k≥4 across both roots,
**0 verified**. The reason is visible in `n_lemmas`: asked for a k=4 problem the root emits
**[2, 4]** lemmas; asked for k=8 it emits **[4, 5, 8, 13]**. **The root under-decomposes**, so
each invented lemma spans several bands and is far harder than a calibrated oracle leaf.

**4. The finding that reframes Phase 1: the corridor work has been calibrating the wrong
distribution.** Every oracle-ceiling number in this repo — R5, §5.4(b′), the [0.25, 0.9] band, the
whole measure-and-filter effort — is computed over *the generator's* leaves at pass rate 0.847.
But a policy invents *its own* lemmas, drawn from a different and much harder distribution.
Measured: policy-invented leaves close **10/14 at k=2** and **0/19 at k≥4**. Oracle-replay tells
you what happens if the policy reproduces the generator's decomposition exactly; it says nothing
about the difficulty of what a policy actually proposes, and that is the binding constraint.

**5. Registered predictions: 1 of 5 hit.**

| predicted | measured | |
|---|---|---|
| qwen direct 0.35/0.10/0.02 | 0.150/0.000/0.000 | MISS — faster |
| haiku direct 0.60/0.25/0.05 | 0.350/0.000/— | MISS — faster |
| decomp 0.35/0.25/0.20, decaying *slower* | 0.500/0.000/0.000 | MISS — collapsed |
| gap 0.0/+0.10/+0.20, widening | +0.35/0.000/0.000 | MISS — largest at k=2 |
| dominant k=8 decomp failure is `plan_invalid` | 19/20 (qwen) | **HIT** |

Four misses, all in the same direction — everything is harder than predicted, the same systematic
optimism the ladder projections showed (all six errors negative there too). The one hit is the
diagnostic, which is the one that decides whether the rest is interpretable.

### What this means for the project

**Phase 3 is viable, and the design already anticipated this.** RL needs reward signal, and at
k=8 qwen scores literally zero on every episode — GRPO cannot learn from that. But there *is*
strong signal at k=2 (decomp 0.500, with 70% valid plans), and the whole point of the RLM result
being tested is **train short, test long**. So: train at k=2, evaluate transfer at k=4/8. That is
the registered design, and Phase 2 has just confirmed the training regime has signal and the
evaluation regime has headroom.

**And the thing training must fix is precisely what reward shapes.** The measured failure is
under-decomposition — the root proposes too few, too-large lemmas. A reward that pays only for a
fully closed proof pushes directly against that. This is a much more specific and more tractable
target than "learn to decompose".

**What must change:** leaf calibration should be re-pointed from oracle leaves to
*policy-invented* lemma difficulty. The corridor as defined is a property of the generator, not of
the task the policy actually faces. #23's measure-and-filter machinery is still useful, but the
distribution it should be filtering is the one measured *from policy proposals*, which nothing in
the repo currently measures.

### §7.2 What prices Phase 3 — the root size ladder (2026-08-13, $0.09 of inference, no GPU)

Phase 2 localized the bottleneck to **stage-1 plan validity**. That check needs only root
inference plus local Lean — no leaf prover — so the question "how small a root still clears it"
is answerable for pennies, and it is the question that sets Phase 3's budget: a 9B LoRA is one
H100, a 30B MoE is a multi-node job, and that is 1–2 orders of magnitude.

n=20, case_tree k=2, the frozen `decomp_env.build_prompt` + rung-1.5 exemplar — the identical
prompt Phase 2 measured, so these numbers are comparable rather than merely similar.

| root | stage-1 valid | parsed | emitted the right lemma count (k=2) |
|---|---|---|---|
| Qwen3.5-0.8B | **0/20** | 18/20 | 13/18 |
| Qwen3.5-2B | **0/20** | 18/20 | 15/18 |
| Qwen3.5-4B | 1/20 (5%) | 15/20 | 12/15 |
| **Qwen3.5-9B** | **3/20 (15%)** | 7/20 | **7/7** |
| qwen3-30b-a3b | **14/20 (70%)** | 20/20 | **20/20** |

**The wire format is not the barrier.** 0.8B and 2B *parse* 18/20 — they emit well-formed plans
that are simply wrong. Format compliance is nearly free; producing a decomposition whose assembly
actually closes the goal is what scales with size. That matters because it means the rung-1.5
exemplar has done its job and further prompt work is not the lever.

**The jump is between 9B and 30B, and it is not gradual**: 0%, 0%, 5%, 15%, 70%. Note also that
9B is the only model that always gets the *lemma count* right when it parses (7/7) while parsing
least often (7/20) — it fails verbosely rather than confidently, which is a different and more
recoverable failure than the small models' fluent-but-wrong plans.

**Trainability.** GRPO needs within-group variance; with group size 8:

| root | stage-1 valid | P(≥1 success in a group of 8) | |
|---|---|---|---|
| 0.8B / 2B | 0% | 0.00 | no signal — untrainable |
| 4B | 5% | 0.34 | too sparse |
| **9B** | **15%** | **0.73** | **usable** |
| 30B-A3B | 70% | 1.00 | usable, and expensive |

**So Phase 3 has an affordable form: train Qwen3.5-9B, single H100, LoRA.** 9B in bf16 is ~18 GB,
so LoRA plus rollouts fits one card with room to spare. And the cheapest scientifically honest
version rewards **stage-1 plan validity alone** — no leaf prover on the GPU, ~1 s of Lean per
episode instead of up to 16 leaf attempts, and it targets exactly the measured bottleneck.
Train at k=2 where signal exists; evaluate validity transfer at k=4 and k=8, where the untrained
9B and 30B both fall off (30B: 70% → 15% → 0%). That is the train-short-test-long design the
whole direction rests on, at a scale the project can actually pay for.

### §7.3 Phase 3 — registered before training (2026-08-14)

**Setup.** Qwen3.5-9B + LoRA (r=32), GRPO via TRL, single H100. Reward is graded stage-1 plan
validity: 0.0 unparseable / 0.3 parses / 1.0 passes `plan_check` in Lean. **Train only at k=2.**
Evaluate at held-out k=2 and at k=4 and k=8, which are never trained on. Train and eval problems
come from disjoint seed families (1000 vs 2000), so no goal appears in both.

**Why graded and not binary:** §7.2 measured this model's failures as 13/20 `format_error`,
4/20 `plan_invalid`, 3/20 `plan_valid`. Two-thirds of its failures are format, so a 0/1 validity
reward would sit at no-gradient for most of training against a deficit that is not the one under
study. The 0.3 tier is unfarmable — a well-formed wrong plan stays at 0.3 forever.

**Registered predictions.** My record this week is 1 hit in 5 on Phase 2 and 1 in 6 on the ladder,
missing low every time, so these are deliberately shaded pessimistic relative to what the
mechanism story would suggest:

| quantity | baseline (measured, §7.2) | prediction after ~200 steps |
|---|---|---|
| k=2 parse rate | 35% (7/20) | **>85%** — the format tier should saturate early; if it does not, the reward plumbing is broken, not the model |
| k=2 stage-1 valid | 15% | **35–55%** |
| **k=4 stage-1 valid** (never trained) | ~5% (inferred; 30B falls 70→15%) | **15–30%** |
| **k=8 stage-1 valid** (never trained) | ~0% | **5–15%** |

**The actual result is the transfer ratio, not the levels.** Define lift = (trained − baseline) at
each k. The RLM claim predicts lift at k=4 and k=8 that is a substantial fraction of the lift at
k=2 — training on short tasks buying competence on long ones. The null is lift concentrated
entirely at k=2 with k=4/8 flat, i.e. the policy learns *these problems* rather than *how to
decompose*.

**What would make me call it a null:** k=4 lift below one third of k=2 lift, or k=8 lift within
noise of zero at n=30 (which at these rates means roughly ≤2 successes). I expect to be able to
distinguish "clear transfer" from "no transfer" at this n, and **not** to be able to resolve the
*shape* of the decay — that would need several hundred eval problems per k and is not what this
run buys.

**Known limits, stated now rather than at write-up:** one seed, one family, one model size, no
compute-matched flat control (the flat arm cannot be trained on this reward — it emits no plan),
and stage-1 validity is a *necessary* condition for a closed proof rather than the proof itself.
This measures whether decomposition *competence* transfers, not whether end-to-end proving does.
