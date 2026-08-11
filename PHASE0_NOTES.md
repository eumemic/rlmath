# Phase 0 notes — environment & leaf bank

Working log for Phase 0 (DIRECTION.md §5.5). Started 2026-08-11.

## Gate criteria

- [~] ≥ 2–3k verified leaf attempts/hour — **PROVISIONAL** (advisor review 2026-08-11: the 36,839/hr
  measurement is *verification-only* throughput — 2 REPL workers, trivial suite, 0/60 failures,
  p50 4.9 ms warm, `analysis/throughput.json`. A leaf *attempt* includes prover inference, which
  will dominate once a live leaf is wired. Gate stays open until re-measured end-to-end with the
  real leaf behind the adapter; verification is established as not-the-bottleneck.)
- [~] statement-extraction/elaboration failure rate < 5% — **PROVISIONAL** (advisor review: 0/29
  is consistent with up to ~10% true rate. n≈3000 elaborate-only sweep running 2026-08-11 evening —
  also the first real stress of the syntax-rewrite retry. The two fixes that got 29/29: big-operator
  `in`→`∈` modernization (self-validating retry) and the standard prover header in PREAMBLE.)
- [x] environment publishable to Prime Intellect Environments Hub — wrapper built (v1-primary +
  v0 shim, both over one `score_plan`; `envs/envs_README.md` documents the publish steps). The
  actual push awaits the account decision (Pending).
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
  Flagged unknowns to pin on first real install: v1 metric-attachment call, Taskset construction.
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

## Pending / carried forward

- Environments Hub publish needs an account decision (end of phase).
- α-normalization of statement cache keys (v1 is whitespace/comment-normalization only).
- `extract_goal`-based subgoal extraction: not needed for depth-1; build when the depth-2 probe lands.
