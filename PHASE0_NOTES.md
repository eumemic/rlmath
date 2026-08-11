# Phase 0 notes — environment & leaf bank

Working log for Phase 0 (DIRECTION.md §5.5). Started 2026-08-11.

## Gate criteria

- [~] ≥ 2–3k verified leaf attempts/hour — **PROVISIONAL** (advisor review 2026-08-11: the 36,839/hr
  measurement is *verification-only* throughput — 2 REPL workers, trivial suite, 0/60 failures,
  p50 4.9 ms warm, `analysis/throughput.json`. A leaf *attempt* includes prover inference, which
  will dominate once a live leaf is wired. Gate stays open until re-measured end-to-end with the
  real leaf behind the adapter; verification is established as not-the-bottleneck.)
- [x] statement-extraction/elaboration failure rate < 5% — **PASS 2026-08-11 at n=2975:**
  elaboration failures 3/2975 = **0.10%** (Wilson 95% CI [0.03%, 0.30%]); extraction misses
  counted separately: 12/2987 = 0.4%. The big-operator rewrite saved **202 statements (6.8%)** —
  without it the rate would have been ~7%, above gate. Residual 3 failures are genuine
  current-Mathlib incompatibilities (binder-syntax oddities; `Complex.abs` renamed upstream).
  Elapsed at scale: p50 14 ms, mean 48 ms, max 8.9 s.
- [x] environment publishable to Prime Intellect Environments Hub — wrapper built AND pinned
  against installed verifiers 0.3.0 (58 env tests; v0 rollout loop validated end-to-end with a
  live policy + real Lean kernel). Hub package at `environments/rlmath_decomp/` builds a clean
  sdist+wheel. One push blocker: the package depends on `rlmath`, which is not on PyPI —
  needs a packaging decision (PyPI publish vs git+URL), then `prime env push`.
- [ ] leaf pass-rate bank pipeline runs end-to-end — elaborate-only path smoked live (29 rows);
  the leaf-proving path is unit-tested but needs a live leaf model (Pending: leaf model choice).

## Decisions

- **2026-08-11 — Backend order: own REPL pool first, Kimina client second.** Kimina Lean
  Server is the documented-throughput path but is Linux/docker-first; dev box is macOS arm64.
  Both implement the same `LeanBackend` protocol so the GPU-box migration is a constructor swap.
- **2026-08-11 — Plan check via hypothesis binders, not `axiom` declarations.**
  `theorem _plan (h1 : L1) ... : G := by <assembly>` keeps the axiom audit strict and clean (§5.2).
- **2026-08-11 — Backend is sorry-policy-free.** `VerifyResult.ok` = "no errors"; callers decide
  sorry-count policy (statement elaboration wants exactly 1, proof checks want 0).
- **2026-08-11 — Wire format `#lemma / #assembly / #end`** (core/plan_format.py): line-oriented,
  chatter-tolerant outside markers, strict inside, loud FORMAT_ERROR status. Direct consequence of
  ../rl's silent-format-failure lesson.
- **2026-08-11 — Status taxonomy fixed in core/types.py** (10 statuses). Feasibility evidence
  (context_window_exceeded) vs policy failure vs infrastructure error never share a bucket.
- **2026-08-11 — PREAMBLE = standard prover header.** `import Mathlib` + `set_option maxHeartbeats
  400000` + `open BigOperators Real Nat Topology Rat`. Measured cause: bare-env elaboration
  misclassified provable Lean-Workbook statements (bare `sin`/`π`/`k!`) as ill-formed — 2/12 then
  effectively ~7% of candidates; the opens are what DSV2/Goedel/miniF2F skeletons use, i.e. the env
  leaf provers were trained against. Empirically validated on Mathlib @ v4.34.0-rc1.
- **2026-08-11 — Lean-Workbook syntax drift handled by self-validating rewrite.** `∑ k in s` →
  `∑ k ∈ s` (old big-operator binders, pre-migration Mathlib), applied only as a retry and kept
  only if the kernel accepts the rewritten statement. Integrals (`∫ x in a..b`) untouched.
- **2026-08-11 — verifiers wrapper targets v1 primarily, with a v0 shim.** prime-rl's orchestrator
  consumes only `verifiers.v1` (research/verifiers.md §6) and prime-rl is the Phase-3 trainer; the
  v0 shim (~40 lines over the same `score_plan`) buys `prime eval run`/`vf-eval` for Phase 2.
  ~~Flagged unknowns to pin on first real install: v1 metric-attachment call, Taskset
  construction.~~ **Resolved 2026-08-11 evening against installed verifiers 0.3.0:**
  `trace.record_metrics()` + `trace.info` (the guessed ladder would have stuffed a dict into the
  float-typed metrics dict — serialization corruption, not loss); `Taskset(config)` positional;
  `TaskData.system_prompt` EXISTS (research notes flatly wrong — inlining removed). Bonus catch
  nobody flagged: the v1 env server rebuilds tasks without calling `load()`, so budgets set as a
  `load()` side effect would have silently reverted to defaults under prime-rl — §5.6's hard caps
  now live in `DecompositionTaskConfig` (TOML: `[env.taskset.task]`).
- **2026-08-11 — Leaf oracle: bf16 on a rented GPU, never quantized-GGUF (advisor review).** The
  bank's measured pass rates ARE the delegability oracle; quantized pass rates are a different
  model's pass rates, and ../rl already ate one silent ollama pathology. Oracle runs use vLLM +
  bf16 checkpoint behind the same OpenAI-compatible adapter. Stand-ins (qwen3:30b ollama) are for
  pipeline plumbing only — enforced mechanically: bank rows carry `leaf_id`, and build_bank refuses
  to append to a file whose leaf_id differs (tested).
- **2026-08-11 — Leaf model selection = measured band-fit bake-off, not strongest-prover.** Serve
  DSV2-7B non-CoT and Goedel-Prover-V2-8B against the SAME few hundred candidates (same --seed /
  --limit slice, separate --out files), pick the one whose pass@8 distribution puts more mass in
  the [0.25, 0.9] band (DIRECTION.md §5.4) — the oracle wants *discriminative* leaves, not maximal
  ones. This resolves DIRECTION.md open decision #2's method; the pick itself happens on the GPU.

## Log

- 2026-08-11: repo scaffolded; core contracts frozen; Lean toolchain install launched (background);
  research+build workflow launched (14 agents: 4 research→builder pairs, 3 independent builders,
  2 paper deep-reads, 1 test-fix).
- 2026-08-11 ~16:15: Lean toolchain DONE (lean v4.34.0-rc1, Mathlib cache 7.4G, repl binary built).
  Raw REPL smoke measurements (M4 Pro, single worker):
  - cold `import Mathlib`: ~23s (disk-cold), ~2.5s (page-cached) → per-worker warm-env reuse is mandatory, as designed
  - warm trivial checks (`norm_num`/`simp` one-liners): **~0.5s each** → ~7.2k checks/hr/worker; the
    ≥2–3k/hr gate has wide headroom before pooling
  - protocol confirmed: sorries as structured `sorries` array; proved theorems → no error messages;
    `#print axioms` in the same cmd → info message `'_w4' depends on axioms: [propext]` (the
    same-check audit design in harness/episode works)

- 2026-08-11 ~16:40: build workflow: 11/12 steps completed cleanly; R3:verifiers died 5× at the
  report-serialization step (research file itself landed fine, 928 lines — key find: verifiers is
  mid-migration v0→v1 API, canonical repo now PrimeIntellect-ai/verifiers, v0.3.0 of 2026-08-07).
  Workflow stopped; B6 relaunched as a direct agent reading the on-disk file. Suite at 353 passed.
  Cross-module fixes applied by hand: episode/_leaf_result + build_bank normalizers now handle the
  adapter's real `(proof, list[AttemptRecord])` return; bank calls `early_stop=False` (pass-rate
  correctness); make_leaf uses `from_openai` + always-on AttemptCache.
- 2026-08-11 ~16:50: paper deep-reads integrated into DIRECTION.md (ProD-RL C1–C11,
  Goedel-Code-Prover C1–C6). Headline changes: ProD-RL is Isabelle/HOL with FULL open-loop
  proof-text isolation (my "Partial" was wrong in the unfavorable direction); its transfer negative
  is confounded by miniF2F being non-decomposable; Goedel-Code-Prover v3 (2026-08-10!) self-reports
  RL delta at +1.1–3.2 pts, one seed. Net: surviving gap wider; §4 prior "in-distribution
  trainability" 70→65%; headline unchanged 35–45%.

- 2026-08-11 ~17:15: integration suite 4/4 against real Lean (multiline preamble validated);
  throughput gate PASS (36.8k/hr); bank smoke 29/29 elaborated after preamble + bigop fixes;
  B6 verifiers wrapper landed (v1-primary + v0 shim; 41 tests). Full suite 395 passed, 6 skipped
  (verifiers-absent guards), 8 deselected (integration, run separately). Three of four Phase-0
  gates met; the fourth (live leaf pass@k) awaits the leaf-model decision.

- 2026-08-11 ~18:00: Prime Intellect account live (team Eumemic); Prime CLI 0.6.21 installed
  (`uv tool install prime`, pulls verifiers 0.3.0). Surveyed what the account provides:
  - **Prime Inference serves NO prover models** (no DeepSeek-Prover-V2, no Goedel-Prover, no
    Kimina). The leaf oracle therefore still needs a rented GPU — task #9 stands unchanged.
  - **Prime Inference is the right home for the ROOT policy**, though: it serves
    `qwen/qwen3-30b-a3b-instruct-2507` — the exact ../rl base model — at $0.20/$0.80 per 1M
    in/out, plus claude-haiku-4.5 ($1/$5) and claude-opus-5. Phase 2's zero-shot study needs **no
    local GPU and no 10–15 min/sample prefills** (../rl's hardest operational constraint, gone).
    `prime eval run` speaks to it natively.
  - **H100 80GB on-demand ~$3.2/hr (PCIe) / ~$4.8/hr (SXM5)**, 1/2/8-GPU configs available.
    Leaf bake-off ≈ a few hours ≈ $10–15; full bank build well inside DIRECTION.md §5.6's envelope.
  - `prime tunnel` (expose local services) is a candidate answer to the envs/ flag about Lean and
    the leaf being process-local rather than services — revisit at Phase 3 integration.

- 2026-08-11 ~18:30: verifiers API pinning complete (all 3 guesses + 1 unflagged bug fixed; suite
  402 passed). **First live eval smoke ran the full loop** — policy (qwen3-30b via ollama) →
  verifiers rollout → wire-format parse → run_episode → real Lean kernel. Scientific note: all 3
  zero-shot completions parsed the format correctly and then **restated the goal as a single lemma
  and delegated it** (`plan_restatement_max=1.0`) rather than direct-closing — the §5.7 P4
  degenerate-recursion pathology, visible on the literal first three rollouts, caught by the
  instrument built for it. Two run-config landmines now in envs_README: `state_columns=["rlmath"]`
  required or the diagnostics blob is dropped from saved rows; v1 harness must be `null` — the
  default resolves to `bash`, handing the policy a shell and reopening the free-REPL leak §5.1
  closed. Remaining unverified: full v1 agent rollout (needs Lean/leaf as services — Phase 3).

- 2026-08-11 ~19:15: **repo public at https://github.com/eumemic/rlmath** (MIT). Pinned git-dep
  verified from a clean venv against the public URL. Stand-in plumbing smoke (#10) passed:
  generation→extract→kernel→cache→provenance all exercised; qwen-as-leaf 0/2 per statement as
  expected (instruct model, not a prover — the bake-off exists for this); 46–106 s/statement
  confirms inference dominates end-to-end throughput (advisor's point). Hub push: wheel builds
  (needed `hatch.metadata.allow-direct-references` for the git-pin), team context lacked a
  teamname → switched CLI to personal; remaining step is the one-time public username prompt
  (user-only decision), then `prime env push` completes.

## Pending / carried forward

- Environments Hub publish needs an account decision (end of phase).
- α-normalization of statement cache keys (v1 is whitespace/comment-normalization only).
- `extract_goal`-based subgoal extraction: not needed for depth-1; build when the depth-2 probe lands.
