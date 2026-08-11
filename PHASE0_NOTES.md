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

## Pending / carried forward

- Environments Hub publish needs an account decision (end of phase).
- α-normalization of statement cache keys (v1 is whitespace/comment-normalization only).
- `extract_goal`-based subgoal extraction: not needed for depth-1; build when the depth-2 probe lands.
