# Overnight run — 2026-08-12 (~07:00 start)

Authorized: $30 GPU cap (hard deadline 16:17, cron-enforced teardown), $5 inference cap,
full autonomy within caps. This file is the morning report; entries append as things land.

## Plan of record

- **Track A (GPU):** wide candidate sweep, pod-side everything (no tunnel — the 222-row lesson).
  Pod `rlmath-sweep` created ~07:00. Sequence: serve DSV2 (whole GPU) → Lean toolchain on pod →
  repo clone → repair the 222 error rows → concurrent sweep as far as $30 carries
  (builder concurrency is being added by the overnight workflow; sequential fallback if it
  isn't green in time). Scope honesty: strategist's 30–50k assumed better throughput than the
  measured 16.3 s/stmt; realistic tonight is 10–20k candidates → ~1–2k band statements.
- **Track B (local):** family-v2 hardening (named-function leaves vs the full battery, empirical
  loop) + mutation-breeding generator.
- **Track C (≤$5):** Phase-2 zero-shot runner build + smoke against Prime Inference roots
  (team-billing header verified working) with the sweep pod as leaf.
- **Track D:** compute-credits ask draft for morning send.

## Log

- 07:00 — overnight workflow launched (4 builders + testfix: concurrent bank, phase2 runner,
  family-v2 hardening, mutation breeder). Sweep pod creating. Crons armed: hard teardown 16:17,
  health checks ~2-hourly.
- 07:30 — workflow attempt 1 lost all 5 agents to simultaneous API 499s (shared transient,
  ~22 min in; agents were still in read phase — zero files written, clean relaunch, same run id).
  Sweep pod SSH up; pod-side setup (vLLM + Lean + repo) launched with full-coverage watcher.
- 08:00 — sweep pod setup completed after one fix (my own `curl | sh -s < /dev/null` bug — sh -s
  reads its script from stdin; also retroactively explains the earlier "uv installer doesn't
  survive this image" misdiagnosis). Sequential repair started pod-side (no tunnel anywhere).
- 09:15 — **workflow attempt 2: all 5 agents landed, suite green.** Concurrent bank builder
  (--concurrent N, fine-seam cache lock), Phase-2 zero-shot runner (arms share the env's exact
  scoring), family-v2 BOTH families clear the full battery (bridge: sqrt/log content +
  congruence gate vs gcongr; case_tree: sqrt-capped bands, rewrite-before-arithmetize
  witnesses), mutation breeder. All committed+pushed.
- 09:30 — **family-v2 materialization: 30/30 fully valid under the complete battery** —
  Phase-1 materialization gates met at 100% (validator ≥90% target, oracle ≥70% target).
  Pod being upgraded to the concurrent builder (repair remainder, then a 12k slice).
- 14:52 health check — pod ACTIVE, spend ≈$25/30, sweep 3,848 rows / 377 band / 0 errors.
  **Phase-2 smoke complete (after one auth fix — env-prefix expansion bug, key now via mode-600
  file): all 24 episodes measured, reward 0 everywhere with CLEAN status separation.** Decomp:
  12/12 plan_invalid — the qwen root speaks the wire format and emits well-formed lemmas (zero
  format/statement errors) but cannot assemble a valid decomposition. NOT restatement-delegation
  this time: real attempts failing stage-1. Direct: leaf_failed ×10 + **sanitizer_rejected ×2 —
  both literal smuggled `sorry`s, the §3.3 reward-hack channel observed in the wild and caught**.
  Cold-start implication (per strategist's framing): all-fail GRPO groups are measured reality at
  this scale; the escalation ladder is live. Spend: pennies of the $5 cap.
- 12:52 health check — pod ACTIVE, spend ≈$19/30, sweep at [2783]: ~3,200 rows / 308 band /
  0 errors, sustained ~430-480 rows/hr (≈2× sequential; earlier 4.7× figure was a bad
  between-two-points sample — corrected). **Phase-2 SMOKE LAUNCHED pod-side** (first
  scientific measurement of Phase 2): 8 cells = {bridge_chain, case_tree} × k{2,4} ×
  {direct, decomp}, n=3, qwen3-30b root via Prime Inference (team-billed), $0.50/cell cap,
  DSV2 leaf on localhost. Results land in results/zeroshot/ on the pod; harvested with the
  15:24 end-window.
- 10:52 health check — pod ACTIVE, spend ≈$12.5/30. Sweep at [1850]/12k: **2,307 rows,
  228 band, 0 errors** since the no-tunnel redesign; effective ~3.5 s/statement (4.7× sequential;
  ~8.1k attempts/hr end-to-end — closes the throughput gate's concurrency caveat with a measured
  number). Persistent monitor armed (completion/death/error-burst/30-min progress) after the user
  caught the coverage gap. End-window planned: 15:24 cron stops the sweep, runs the 138-leaf
  family calibration on the quiet pod (~15 min; closes DIRECTION §5.4a flatness for #11),
  harvests both files home, self-terminates before the 16:17 backstop. Candidates staged.
