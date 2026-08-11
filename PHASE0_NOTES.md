# Phase 0 notes — environment & leaf bank

Working log for Phase 0 (DIRECTION.md §5.5). Started 2026-08-11.

## Gate criteria

- [ ] ≥ 2–3k verified leaf attempts/hour on available hardware (`scripts/bench_throughput.py` → `analysis/throughput.json`)
- [ ] statement-extraction/elaboration failure rate < 5% on bank candidates
- [ ] environment publishable to Prime Intellect Environments Hub (`verifiers` format)
- [ ] leaf pass-rate bank pipeline runs end-to-end (full bank build may extend past Phase 0)

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
- **2026-08-11 — Leaf stand-in for local smoke:** qwen3:30b via ollama (already pulled, from ../rl).
  Real leaf (DeepSeek-Prover-V2-7B non-CoT / Goedel-Prover-V2-8B) per research findings; GGUF-on-ollama
  viability TBD, else leaf runs on a rented GPU behind the same OpenAI-compatible adapter.

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

## Pending / carried forward

- Environments Hub publish needs an account decision (end of phase).
- α-normalization of statement cache keys (v1 is whitespace/comment-normalization only).
- `extract_goal`-based subgoal extraction: not needed for depth-1; build when the depth-2 probe lands.
