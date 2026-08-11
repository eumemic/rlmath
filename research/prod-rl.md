# ProD-RL — deep read

**Paper:** Kefan Dong, Arvind Mahankali, Tengyu Ma (Stanford), *Formal Theorem Proving by Rewarding
LLMs to Decompose Proofs Hierarchically*, [arXiv:2411.01829](https://arxiv.org/abs/2411.01829),
submitted 2024-11-04. **Only v1 exists** (no v2/v3 as of 2026-08-11); no venue listed on the
abstract page; cs.LG.

**Source read:** full LaTeXML HTML (`arxiv.org/html/2411.01829v1`), all sections including
Appendices A and B. Everything below is from the paper text. Figures 3–6 are images; where a fact
lives only in a plot I say so rather than inventing numbers.

**Artifacts released:** test sets at <https://huggingface.co/kfdong/ProD/tree/main>. Fine-tuning /
RL code is the Llemma code base (<https://github.com/EleutherAI/math-lm>); no ProD-specific repo is
cited in the paper.

---

## 1. Proof system

**Isabelle/HOL. Not Lean.**

- Verifier: Isabelle (Nipkow et al. 2002), driven through **PISA** (Portal to ISAbelle, Jiang et al.
  2021). Chosen explicitly because "the proofs are declarative and human-readable without knowing
  the verifier's proof state" — i.e. the whole-proof-generation setting works in Isabelle/Isar in a
  way it does not in tactic-state-driven Lean.
- **Sledgehammer is load-bearing.** Following Thor (Jiang et al. 2022b), training proofs have steps
  replaced by a `sledgehammer` call when the step (a) contains `meson`/`metis`/`smt`, or (b) is in a
  fixed easy-tactic list: `by auto, by simp, by blast, by fastforce, by force, by eval, by
  presburger, by sos, by arith, by linarith, by (auto simp: field_simps)`. At verification time, a
  `sledgehammer` command is first attempted by substituting one of those predefined tactics; if all
  fail, real Isabelle premise selection runs with a **10 s timeout**; failure ⇒ step incorrect.
  Note they replace *without* consulting the verifier (unlike Thor, which calls sledgehammer at
  every step) purely because per-step sledgehammer is too slow for RL.
- Local-correctness checking trick: move each proposed lemma from the conditional proof into the
  context and give it `sorry` (registers the statement as a fact with no proof), then check the
  remaining proof under standard Isabelle syntax. **10 s timeout per proof step.**

*Relevance to this project:* Lean 4 has no exact Sledgehammer. A meaningful fraction of ProD-RL's
absolute pass rates is Sledgehammer closing leaves. Their per-node difficulty numbers do not port.

## 2. Model and scale

| Component | Value |
|---|---|
| Base / policy | **Llemma 7B** (Azerbayev et al. 2023; Llama-2 lineage, Llama 2 Community License) |
| Value function `V_φ` | a **second Llemma 7B**, initialised from the SFT checkpoint |
| Context window | **2048 tokens**; at test time the context is truncated to the **last 1k tokens** |
| Optimiser | AdamW, linear warmup → constant LR **1e-5**, macro batch **128** |
| Hardware | 8× A100-80G for SFT+RL; A100-80G + A5000 mix for generation |
| SFT cost | ~**8 GPU-days** (1 wall-clock day on 8×A100) for 7B on 300k examples × 2 epochs |
| RL cost | ~**30 GPU-hours** per RL experiment |
| Headline compute claim | "<36 GPU days to train a 7B model", vs Lample et al. 2022 HTPS ">1K A100 GPU days for a 600M model" |
| Test-time generation | depth-2 trees for 4k test theorems ≈ **1–2 h on 8× A5000** |

Sampling temperature **0.7** everywhere (train and test), tuned in Appendix B.1.

## 3. What is trained, and how

### 3.1 The representation: "conditional proofs" with inline `<invoke>`

A **conditional proof** is ordinary Isabelle proof text with proposed lemma *statements* spliced in
between `<invoke>` … `</invoke>` tokens:

```
t₁ <invoke> l₁ </invoke> t₂ <invoke> l₂ </invoke> … t_k <invoke> l_k </invoke> t_{k+1}
```

A **proof-tree node** = (premises, context, statement, conditional proof).
- *Premises*: all theorems from predecessor files — background facts the model may cite freely, and
  the pool Sledgehammer selects from. Defined implicitly by the AFP file dependency graph.
- *Context*: definitions/local assumptions needed to state the theorem, plus the statements of
  earlier lemmas in the file that were **not** peeled off into `T_tree`.

Two correctness notions:
- **Locally correct**: after adding `l₁…l_k` to the premises, `t₁…t_{k+1}` verifies. (Plan-level
  check — "does this decomposition suffice, granting the lemmas?")
- **Globally correct w.r.t. a node set N**: a valid proof tree rooted here can be assembled from the
  *locally correct* nodes in N, where a child must correspond to one proposed lemma and share the
  parent's premises and context. Final proof = list statements + conditional proofs child-first and
  delete the `<invoke>` markers.

**Important pass@k nuance:** global correctness is defined over the *pooled* set of locally-correct
nodes from **all** sampled trees for a theorem, deliberately — "if we generate more than one proof
tree per theorem, we may mix their locally correct nodes." So pass@k here allows cross-sample
subproof mixing; it is not k independent end-to-end trees.

### 3.2 Format tokens and exploration

Output = a special token `t₀ ∈ {<use_invoke>, <no_invoke>}` followed by the conditional proof. `t₀`
exists so RL can up-weight decomposition. During RL rollouts (Alg. 2):

- Compute normalised invoke probability `pᵢ = π(<use_invoke>) / (π(<use_invoke>) + π(<no_invoke>))`.
- For theorems in the **top 50% of the batch by `pᵢ`**, force `t₀ = <use_invoke>`; others sample
  (`pᵢ ≥ κ` or `uᵢ < pᵢ`, `κ` = median).
- For **every** theorem where an invoke-proof is generated, also generate a matching no-invoke
  proof. Either may end up the globally correct one.
- Ground-truth human conditional proofs for the batch are injected into the tree generation and into
  the training set each round.

### 3.3 RL algorithm — REINFORCE-style reward-weighted cross-entropy (not PPO, not GRPO)

Per round: sample batch `D`, generate trees, verify, assign reward, update. Section title is
literally "**Step 3: Update the model by REINFORCE**", and the update is a **weighted cross-entropy
loss** over (prompt, target, weight) triples. Prompt = context ⊕ statement; target = `t₀` ⊕
conditional proof.

Reward `r(c,s,ρ)` is **binary**, based on the node's **global** correctness.

The training weight is a variance-reduced surrogate for that reward:

```
w = γ^h · ∏_{i=1..k} V_φ(lᵢ)        (h = conditional proof length, k = # proposed lemmas)
w = 0                                if the node is not locally correct
γ = exp(−0.0005)
```

so the weight **factorises into a hard plan term × an estimated leaf term × a soft length penalty**:

- `1[locally correct]` — the plan check (was the assembly valid, granting the lemmas?);
- `∏ V_φ(lᵢ)` — the learned probability that the current policy can actually discharge each
  proposed lemma, replacing the *realised* (stochastic) child outcomes;
- `γ^h` — a **soft** length penalty favouring shorter proofs.

`V_φ` is implemented as a token trick: predict `<true>`/`<false>` conditioned on (context,
statement); value = `p_t / (p_t + p_f)`.

Two further ingredients: **augmented examples** (for any locally correct invoke-proof, add a copy
with the proposed lemmas moved into the context — always locally correct, no proposal) and a
**replay buffer** for stability.

The paper positions the method as (a) an instance of **hindsight experience replay** with correct
proof sub-trees as the hindsight trajectories, and (b) a generalisation of **expert iteration** —
expert iteration is the special case `w = 1[globally correct]`.

### 3.4 Partial credit for correct-but-unused novel lemmas — exact mechanics

This is the paper's signature idea and the details matter.

- Reward is assigned **per tree node**. A proposed lemma is itself a node. If the model proposes
  lemma `l`, the parent's conditional proof turns out **wrong**, but `l` is proved correctly in its
  own node, then that lemma node is globally correct → **r = 1**, positive weight, and it enters the
  training set as a (context ⊕ l → proof) example. Fig. 2's caption states it explicitly: "even if a
  theorem (Theorem 1) is not proved by the model because some lemmas (Lemma 1) are not proved, we
  still train on the correct lemma (Lemma 2) by setting its reward r = 1."
- **The credit lands on the child, not on the parent's proposal decision.** The parent's own example
  gets `w = 0` unless the parent is locally correct. So this is *hindsight data augmentation on the
  proved lemma*, not a reward for having proposed a nice-but-unused lemma. §4.4 Case 3 is the
  worked example (a `shortest_path_lower_bound` lemma proved correctly while the parent proof "contains
  a few mistakes" — "we still train on the correct lemma even though it might not be directly useful").
- Two **anti-degeneracy filters**, applied before reward:
  - **(a) trivial-proposal filter** — if a proposed lemma directly implies the theorem (e.g. it *is*
    the theorem restated), **discard the example entirely**. This is a restatement detector.
  - **(b) unnecessary-proposal stripping** — if the conditional proof still verifies after removing
    all references to a proposed lemma, that lemma is removed from the conditional proof. So the
    parent is not trained to emit dead `<invoke>`s, even though the lemma node itself may still be
    trained on.

**Quantified effect:** newly-proposed correct lemmas (not in the training dataset) make up
**37.7% of the training replay buffer** on AFP.

## 4. Context isolation — yes on proof text, and totally open-loop

The parent's context **never contains child proof text.** But this is not a harness property, it is
a consequence of the generation being feed-forward:

1. Parent is prompted with (context ⊕ statement) and emits its **entire** conditional proof in one
   completion, with lemma *statements* inline. No child has been attempted yet.
2. Children are proved in **separate model calls**, prompted with (the *same* context ⊕ the lemma
   statement). A child sees neither the parent's proof nor its sibling's.
3. Assembly is **textual splicing** in child-first order with `<invoke>` markers deleted. The verifier
   is the only thing that ever sees the concatenation.

Consequences worth being precise about:

- **Proof-text isolation: complete.** Root ⟷ leaf never exchange proof text, in either direction.
- **Status feedback: none.** The root is not conditioned on child success/failure, cannot retry,
  cannot restate, cannot react. There is no per-node "status" channel at all — strictly less
  information than "statements + statuses". The loop is open at every level.
- **Context is inherited, not isolated.** A valid tree requires each child to *share the parent's
  premises and context*. Only the statement differs. Plus the whole context is truncated to the last
  1k tokens at test time, so "context isolation" is partly just a 2048-token window.
- **Depth handling is a prompt hack**: to stop the tree growing, the harness prefixes
  `<no_invoke>` to the prompt at the depth limit.

So "Partial" isolation is the wrong label if it implies proof text leaks — it does not. The accurate
label is: *full proof-text isolation, open-loop (no child status ever returns to the parent), shared
file-level context.*

## 5. Tree depth in practice

| Where | Depth |
|---|---|
| **RL training** rollouts | trees truncated at **depth 3** (`d = 3` in Alg. 2) |
| **Test-time** generation | trees truncated at **depth 2** (Alg. 1, `d = 2`) |
| Where the gains actually come from | theorems whose **ground-truth** proof depth is **≤ 2** |

Alg. 1 semantics: loop `depth = 0 … d−1` sampling proofs that may invoke, then force `<no_invoke>`
at level `d`. So `d = 2` ⇒ at most three levels of nodes (root + 2), two levels of proposal.

Fig. 4 groups proved AFP-test theorems by ground-truth proof depth and colours by generated-tree
depth. Text conclusion: "the improvement of ProD-RL mostly comes from proving theorems with
low-to-medium difficulty where the depth of the ground-truth proof is at most 2. For more complex
theorems, both models' pass rates are low and the improvement of our method is not significant,
meaning that they are currently beyond the models' capability." **The per-bar numbers are not
recoverable from the HTML** (figure is an image).

Qualitative depth finding (§4.4 Remarks): proposed lemmas "typically do not involve complex ideas",
attributed to (a) small model + dataset and (b) AFP lemmas being genuinely basic-fact-shaped.

## 6. Train / eval distributions

**SFT dataset — 312k examples.** AFP (snapshot **2022-12-06**) + Isabelle built-in files (HOL etc.).
2 epochs (overfits after 2 in their preliminary runs). Loss on the special token + proof only for
AFP theorems; loss also on the statement for Isabelle built-ins, "to help the model internalize
basic facts". Augmented copies (proposed lemmas moved into context) included.

**RL dataset — 104k examples.** `T_tree`: theorems iteratively *peeled off* while parsing AFP files
(a theorem is peelable when nothing in the remaining file content refers to it — round 1 peels
roots, round 2 the next level, …). Theorems referenced from file content `c_j` (e.g. used to
instantiate local objects) are never peeled and stay in the context. Pipeline: **1 epoch SFT, then
20 RL rounds × 5k random examples per round.**

**Test sets.**

| Set | Size | Construction |
|---|---|---|
| **AFP test** | **4.3k** theorems | Dependency split: crawl <isa-afp.org/entries/>, find AFP entries no other entry depends on, randomly sample **10%** of them (35 entries, listed in A.3 — `Khovanskii_Theorem`, `FFT`, `Knot_Theory`, `LP_Duality`, `Jordan_Hoelder`, `Knights_Tour`, `Schutz_Spacetime`, …). Training examples never refer to any test file. Restricted to `T_tree`. |
| **AFP 2023** | **2k** theorems | AFP files submitted **after April 2023** (Llemma's knowledge cutoff), archive retrieved **2023-11-22**. Purpose is *data-leakage control*, not domain shift. The abstract calls it "out-of-distribution"; it is still AFP. Restricted to `T_tree`. |
| **miniF2F** valid/test | standard | The genuinely out-of-domain benchmark: competition-style problems, unlike AFP. Only appears in the Limitation section. |

**Evaluation protocol.** pass@k: sample k proof trees per theorem independently; a theorem counts as
proved if at least one conditional proof is globally correct **w.r.t. all generated tree nodes**
(cross-sample mixing, §3.1). Temperature 0.7, context truncated to last 1k tokens, trees truncated
at depth 2. Test theorems are never RL-trained on.

**Setup-difficulty calibration (Table 1, pass@4, SFT model trained on `D_train^{w/l}`):**

| `D_val^{w/l}` — w/ lemmas, random split | `D_test^{w/l}` — w/ lemmas, dependency split | `D_test^{w/o l}` — w/o lemmas, dependency split |
|---|---|---|
| **45.7** | **39.7** | **35.7** |

Both changes vs prior work (Jiang et al. 2021; First et al. 2023 / Baldur) make the task harder:
dependency splitting costs ~6 pts, withholding the file's own lemmas another ~4.

## 7. Main results, and the exact evidence behind the distribution-shift caveat

**Table 2 — pass@16 on AFP.** Four arms, all evaluated in the new no-human-lemmas setup:

| Test set | SFT w/o lemma proposal | RL w/o lemma proposal | ProD-SFT | **ProD-RL** |
|---|---|---|---|---|
| AFP test (4.3k) | 43.4 | 42.4 | 40.8 | **45.5** |
| AFP 2023 (2k) | 39.4 | 37.7 | 36.5 | **39.5** |

**Table 3 — pass@64 on miniF2F.** This is the caveat.

| Test set | SFT w/o lemma proposal | RL w/o lemma proposal | ProD-SFT | **ProD-RL** |
|---|---|---|---|---|
| miniF2F valid | **46.3** | 40.6 | 44.7 | **41.4** |
| miniF2F test | **40.6** | 38.9 | 39.3 | **39.3** |

### Reading these correctly

- **The abstract's numbers (40.8 → 45.5 and 36.5 → 39.5) are ProD-SFT → ProD-RL** — i.e. against the
  *lemma-proposal* SFT ablation, which is the **weakest of the four arms** on both AFP sets. Anyone
  citing "ProD-RL improves the pass rate from 40.8% to 45.5%" as "RL beats SFT" is quoting the
  favourable ablation.
- **Against the strongest SFT baseline** (SFT w/o lemma proposal): **+2.1 pts** on AFP test
  (43.4 → 45.5) and **+0.1 pts** on AFP 2023 (39.4 → 39.5 — a tie).
- **On miniF2F, ProD-RL loses to plain SFT**: −4.9 on valid (41.4 vs 46.3) and −1.3 on test
  (39.3 vs 40.6). ProD-RL also fails to beat ProD-SFT on miniF2F valid (41.4 vs 44.7) and only ties
  on miniF2F test (39.3 vs 39.3).
- **The negative-control result:** *RL without lemma proposal* is **worse than its own SFT model on
  every one of the four test sets** (42.4<43.4, 37.7<39.4, 40.6<46.3, 38.9<40.6). So the RL machinery
  buys nothing without decomposition; the lemma-proposal term is doing all of the work. The paper's
  claim "RL w/o lemma proposal yields no improvement" is, if anything, understated.
- ProD-SFT < SFT-w/o-proposal on both AFP sets. Paper's hypothesis: "proposing correct lemmas itself
  is challenging, which distracts the model from learning to generate direct proofs."

### The caveat as the paper states it, verbatim (Limitation, §6)

> "We observe that the improvement of ProD-RL over SFT w/o lemma proposal is significant only when
> the test distribution is close to the training distribution. On miniF2F (Zheng et al., 2021) where
> the theorems are very different from theorems in the training dataset, ProD-RL performs worse than
> SFT w/o lemma proposal, as shown in Table 3. We also observe that when tested on miniF2F theorems,
> **our model failed to propose meaningful lemmas. This may be because proving to miniF2F-level
> mathematics questions typically does not require hierarchical decomposition.**"

And in §4.3, on the milder shift:

> "on AFP 2023, the improvement is minor over SFT w/o lemma proposal, while ProD-RL still outperforms
> ProD-SFT. The results suggest that the baseline methods are more robust to heavier distribution
> shifts, while our method has a larger improvement when the test distribution is closer to the
> training distribution."

**The confound, stated plainly.** The paper's own diagnosis is that the miniF2F failure is a
**task-structure mismatch**, not a decomposition-policy transfer failure: miniF2F problems do not
*admit* useful hierarchical decomposition, so a policy whose entire edge is decomposition has no
edge to transfer, and the `<use_invoke>` machinery becomes pure overhead against direct proving.
That is a materially weaker negative than "trained decomposition policies do not transfer."
There is a monotone ladder of distribution shift with a matching monotone decay:

| Shift | Δ (ProD-RL − SFT w/o proposal) |
|---|---|
| AFP test (dependency-held-out, same corpus) | **+2.1** |
| AFP 2023 (same corpus, post-cutoff files) | **+0.1** |
| miniF2F valid / test (different domain, non-decomposable) | **−4.9 / −1.3** |

Also relevant: the shift axis tested is **domain**, never **size**. There is no train-small /
evaluate-large experiment anywhere in the paper, no compute-matched control (pass@16 vs pass@64
across tables, with ProD-RL paying extra generation for child nodes that the flat baseline does not),
and no measurement of trajectory similarity or any other mechanism mediator.

### Other quantitative odds and ends

- **37.7%** of lemmas proved during training are not in the dataset (= share of the replay buffer).
- Appendix B.2: pass rate over RL rounds is **non-monotone** (round 15 worse than round 10 —
  "might be due to training instability"); 20 rounds is best; *all* RL checkpoints beat ProD-SFT.
- Appendix B.1: temperature 0.7 chosen; lower temperature better at 1 sample, mildly higher better
  with many samples.
- §4.4 case taxonomy of proposed lemmas: (1) genuine case-split decomposition
  (`icard_insert_if` → `icard_insert_disjoint` + `icard_insert_eq`), (2) **rephrase of an existing
  lemma** — "not fundamentally useful… can be viewed as data augmentation", (3) novel but useless to
  the parent, still trained on. Authors note the examples are "biased toward easier theorems".

---

## 8. Corrections needed to `DIRECTION.md`

Nothing in §0 or §2 is *false*. Every correction below is a precision or attribution fix. Ordered by
how much it changes the argument.

### C1 — §2, ProD-RL row: say **Isabelle/HOL**, and flag Sledgehammer

The row never names the proof system. Sitting next to a row that says "Lean 4", it reads as Lean by
default. ProD-RL is **Isabelle/HOL via PISA**, and **Sledgehammer** closes its low-level steps — a
tool with no exact Lean 4 equivalent. This is not cosmetic: it means ProD-RL's absolute pass rates
and its per-node leaf difficulty are not comparable to anything in the Lean design of §5, and it
weakens any inference from ProD-RL's numbers to §5.4's leaf-bank calibration.

### C2 — §2, ProD-RL row: name the RL algorithm; it is **not** GRPO/PPO

The row says only "RL rewards proposing and proving lemmas". It is **REINFORCE-style reward-weighted
cross-entropy** — explicitly framed by the authors as generalised **expert iteration** + **hindsight
experience replay**, with a **replay buffer** and a **separate 7B learned value function** used
multiplicatively (not as a subtracted baseline). This matters because §0 and §2 implicitly contrast
ProD-RL with Goedel-Code-Prover's GRPO, and §5.6 plans GRPO; the contrast should be explicit rather
than latent, and "ProD-RL did a version of it" (§0) should not be read as "with a modern policy-
gradient recipe".

### C3 — §2, isolation column: "Partial" is the wrong label, in the *unfavourable* direction

ProD-RL has **complete proof-text isolation** — the parent never sees any child proof and the child
never sees the parent's. It is *less* informed than DIRECTION's design, not more: the parent gets **no
child status either**. The accurate cell is something like *"Full proof-text isolation, but fully
open-loop — no child status returns to the parent; children inherit the parent's file context."*

**This has a real cost to §5.1's positioning.** §5.1 claims to be "*more* faithful than the
scaffolding literature: the root never sees a proof — only goal statements and child statuses." The
first half of that is already true of ProD-RL. And since **v1 is explicitly single-shot** ("the root
emits the whole plan in one completion"), v1's root also sees no statuses — so v1's root
architecture is close to isomorphic to ProD-RL's. The honest deltas of v1 vs ProD-RL are: (a) a
**frozen, separately-measured leaf prover** vs the same model recursing on itself, (b) **GRPO** vs
reward-weighted CE, (c) a **restricted structured action space** vs inline `<invoke>` in free proof
text, (d) a **constructed size axis** vs naturalistic AFP, (e) Lean 4 vs Isabelle. §5.1 should say
that rather than claim isolation as the differentiator.

### C4 — §2, transfer column: the header conflates two different axes

Current cell: "**Reported negative:** gains significant only when test distribution ≈ train
distribution" under a column headed "Transfer/size-axis tested?". ProD-RL tested **domain shift
only** (AFP test → AFP 2023 → miniF2F). It has **no size axis**, **no train-small/eval-large
experiment**, **no compute-matched control**, and **no mechanism measurement**. Suggested cell:
*"Domain-shift only (AFP → AFP-2023 → miniF2F); no size axis, no compute-matched control; negative
on the far shift."* As written, the column implies ProD-RL already probed the axis §4 proposes, which
overstates the prior art and understates the gap.

### C5 — §0 and §2: attach the numbers, and state the confound

§0's sentence ("gains over SFT-without-lemma-proposal were significant only when the test
distribution was close to the training distribution… reported as a negative, by the closest prior
work") is an accurate paraphrase, but under-informative in a way that biases the project's own
prior. Add:

- The ladder: **+2.1** (AFP test) → **+0.1** (AFP 2023) → **−4.9 / −1.3** (miniF2F valid/test),
  pass@16 on AFP and pass@64 on miniF2F.
- **The paper's own attributed cause**: the model "failed to propose meaningful lemmas" on miniF2F,
  "because proving to miniF2F-level mathematics questions typically does not require hierarchical
  decomposition." The negative is therefore **confounded by the OOD benchmark being one where
  decomposition has no purchase at all** — it is evidence that a decomposition policy is useless on
  non-decomposable problems, which is close to tautological, and much weaker evidence that
  decomposition policies fail to transfer.

This cuts *for* the project: §5.4's constructed families (bridge chains, case trees) are
decomposable **by construction**, which removes precisely this confound. §0's "cuts mildly against
the hypothesis" is defensible, but the reason it is only *mild* should be stated, and §3.4's
"Phase 3 transfer fails → ProD-RL's caveat confirmed" should be re-worded: a Phase-3 failure would
be a **stronger and cleaner** negative than ProD-RL's, because the confound is designed out. Also
worth registering: the ladder is monotone in shift severity, which is at least *consistent* with a
genuine transfer decay independent of the confound. Both readings survive the data.

### C6 — anywhere ProD-RL numbers get quoted: use the right baseline

The abstract's "40.8% → 45.5%" and "36.5% → 39.5%" are **ProD-SFT → ProD-RL**, and ProD-SFT is the
weakest of the four arms. The defensible statement of ProD-RL's gain is **+2.1 pts on AFP test and
+0.1 pts (a tie) on AFP 2023 over SFT-w/o-lemma-proposal**. §2 currently quotes no numbers, so this
is prophylactic — but the temptation to quote the abstract pair is exactly the error to avoid, and
DIRECTION's own §0 already frames the comparison as against "SFT-without-lemma-proposal", which is
the *right* baseline and the *wrong* numbers.

### C7 — §5.2 needs a prior-art citation: `r = r_plan × r_leaves` is not new

§5.2 presents the two-stage `r = r_plan × r_leaves` factorisation as "the design gift of this domain"
and says "Retrieval-RLM had no analog". True of retrieval-RLM — but **ProD-RL already implements
essentially this factorisation**:

```
ProD-RL:   w = 1[locally correct] · ∏ᵢ V_φ(lᵢ) · γ^h
§5.2:      r = r_plan            ·   r_leaves
```

with two differences worth naming as the actual contribution: ProD-RL **estimates** the leaf term
with a learned 7B value function, where §5.2 can **measure** it against a frozen leaf prover with a
known pass-rate bank; and ProD-RL's plan check is `sorry`-based local correctness, structurally the
same trick as assuming the stated lemmas as hypotheses. Claiming novelty for the factorisation
itself would not survive review. The novelty is the *measured* leaf oracle.

### C8 — §5.6 / §3.3(2): credit ProD-RL's degeneracy controls, and note it used a soft penalty

- §3.3 objection 2 proposes "explicit restatement detectors". **ProD-RL has one**: filter (a)
  discards any example whose proposed lemma *directly implies the theorem*. There is also filter (b),
  which strips lemmas whose references can be deleted with the proof still verifying. Cite these as
  prior art rather than presenting the detectors as novel instrumentation.
- §5.6 argues for "**hard budgets** … rather than cost *penalties* — penalties suppress decomposition
  before it has a chance to pay off." ProD-RL is a counter-data-point: it used a **soft** length
  penalty `γ^h`, `γ = exp(−0.0005)`, alongside forced-`<use_invoke>` exploration on the top 50% of
  the batch — i.e. it paired a soft penalty with an explicit exploration bonus for decomposing. That
  pairing is arguably the more informative precedent and should be mentioned when the decision is
  made.

### C9 — §3.3(3) is confirmed, with a sharpening worth carrying

"ProD-RL hand-built partial credit for precisely this" is **correct**. Sharpen it: the credit lands
on the **child node's own training example** (a globally-correct lemma gets r = 1 regardless of the
parent's fate), *not* on the parent's proposal decision — the parent still gets `w = 0` when its own
conditional proof fails local checking, and filter (b) actively strips unused proposals from the
parent's target. So ProD-RL's answer to "child punished for parent's error" is *hindsight data
augmentation on the child*, plus `V_φ` absorbing child stochasticity out of the parent's weight. Both
halves are directly reusable.

### C10 — §3.1 row 3 ("at this scale depth ≤ 2 is what matters") is now evidence-backed

Currently asserted. ProD-RL supports it concretely: **trained at depth 3, evaluated at depth 2**, and
Fig. 4 shows gains concentrated on theorems whose *ground-truth* proof depth is ≤ 2, with deeper
theorems "beyond the models' capability" for both arms. Worth citing — it converts an assumption in
§3.1/§5.1 (depth-1 training, depth-2 as a held-out probe) into a decision grounded in the closest
prior work at a comparable model scale (7B).

### C11 — small factual additions for §2 / §5 sizing

- ProD-RL is a **7B** model (Llemma 7B) with a **2048-token** window; total training ≈ **8 GPU-days
  SFT + ~30 GPU-hours RL** on A100-80G. That is well inside §5.6's "$2–5k, 2–4 rented H100s for 2–3
  weeks" envelope and is a useful sanity anchor for it.
- ProD-RL's pass@k pools locally-correct nodes **across samples** when deciding global correctness.
  If §5.7 ever compares numbers to ProD-RL, this needs matching or noting — it is not k independent
  end-to-end attempts.
- The AFP 2023 set is a **temporal/leakage** split, not a domain shift, despite the abstract calling
  it "out-of-distribution". Any DIRECTION text that reads "test distribution ≈ training distribution"
  as the AFP-test-vs-AFP-2023 contrast would be misattributing the negative — the strong negative is
  **miniF2F**.

### Not corrections (verified accurate as written)

- §2: "proof is a tree, theorem proven only if all tree proofs check" — correct (modulo C11's
  cross-sample pooling nuance).
- §2: "partial credit for correct novel lemmas even when the parent fails" — correct; see C9 for the
  sharpening.
- §0: "ProD-RL (2024) did a version of it" — fair.
- §0's surviving novelty claim — that nobody has tested whether context isolation makes a *trained*
  decomposition policy transfer along a **size/difficulty** axis — **survives this read intact**, and
  is in fact strengthened: ProD-RL has the isolation and the trained policy, but tested only a domain
  axis, on a benchmark where decomposition is inapplicable, with no compute-matched control and no
  mechanism measurement.
