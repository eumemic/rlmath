# Overnight session 2 — 2026-08-12 into 2026-08-13

**Authorized by the user at 23:20 CDT, before sleeping:**
- **GPU/inference cap: $12.** Hard. Wallet balance at authorization: **$38.45** (so the floor
  to stop at is **$26.45**). Earlier in the evening the user also said "you don't need to ask me
  to spend $3" — the $12 supersedes and bounds that.
- **Direction: finish both synthetic ladders.** Close case_tree on the staged ladder, then fix
  bridge_chain's flatness defect. Bank-drawn leaves (FAMILIES.md direction 1) and the wide sweep
  (#12) stay queued behind the credits reply — explicitly NOT tonight.
- No wake-ups. Ambiguous calls wait for morning.

**Spend discipline this session (the 2026-08-12 lesson):** every prior cost figure in this repo
was a wall-clock estimate and ran **~27% low** — the overnight pod billed $36.19 against a $30
cap I reported closing at $29.7. So: size caps with margin, and after every teardown read
`prime wallet` and record the *invoice* number here, never the estimate. Wallet timestamps are UTC.

## Plan

1. Gate finishes → V0–V6 per rung (**never yet run for any rung** — no rung has passed the shipped
   validator, only the battery on hand-built props).
2. Three-lens review (soundness / contract+flatness / science). Apply blocking fixes.
3. **Pod A — case_tree ladder confirm.** 5 cells (`v2` control, `r1_recip`, `r2_prod`, `r2_sum`,
   `r3_floor`) × 30 leaves × 8 attempts, plus the 60-per-k flatness confirm for the winner.
   ~270–300 statements, ~1 hr, est. $3.0–3.2 → budget $4, cap $6.
   Apply R0–R4 + R3′. Regenerate + revalidate. Phase 1 closes for case_tree.
4. **bridge_chain #18** — design + local gate are free. Stage the bounded-degree schema
   (`M_i = 3^i · x^p y^q z^r`, growth by integer multiplier so degree and hence the measured
   blocker `1 ≤ M` stay constant along the chain), battery gate with planted control, register
   projections, then **Pod B** confirm (~$2–4) if the $12 allows after Pod A's real invoice.
5. Local, $0, if time: **#19** leaf-pool rejection sampling (behind a flag — resampling inside the
   RNG stream breaks v2's byte-identity golden test — plus the χ² check that conditioning on the
   key nibble does not shift the knob marginals); **#20** datasheet columns.

## For the user's reviewers in the morning

Two written contracts were reinterpreted unilaterally. Both are reasoned and both are the class of
call the strategist has caught before:
1. **R3** → FAIL (gap ≥0.20 or ≥2 SE) / UNRESOLVED (0.05–0.20) / PASS (≤0.05), plus **R3′**, a
   regression of pass@8 on the continuous difficulty driver with rung fixed effects. Reason: at
   10 leaves/k the 2σ-detectable per-k gap is 0.22–0.27, so the literal ±0.05 had **no attainable
   PASS state** — it could only reject. `research/retune-notes.md` §8.1.
2. **Leaf-disjointness** ratified in its leaf-level form (resample each piece until its key nibble
   matches). Reason: the literal problem-level reading has acceptance `0.75^k` → 1e-4 at k=32.
   `FAMILIES.md`, leaf-disjointness section.

## Log

- 23:20 — authorization recorded; `caffeinate -im -t 39600` armed (11 h). Gate running.
- 01:20 — Gate clean. Planted control died twice; 7,920 battery attempts over 316 props, 1 kill
  (the control). 1,315/1,315 witnesses. **V0–V6 ran for the first time for any rung: 54/54.**
  New repo-level finding: `maxHeartbeats` bounds the k-axis (task #21) — and raising it arms the
  battery too, so the corridor floor is a function of the budget.
- 02:05 — **All three reviews in: SHIP-WITH-FIXES / SHIP-WITH-FIXES / SHIP.** 5 blocking, all
  resolved before any spend. 10/10 agents, 0 errors, ~2.9 h wall, ~2.0 M subagent tokens, $0.

  **Soundness: SHIP, zero blocking**, and verified the right way — it parsed the *rendered Lean
  strings* rather than trusting the module's own audits, then re-derived every predicate
  independently from the Lean semantics. 68,076 points at 80 digits + 290,700 exact-integer
  points to k=128: **0 mismatches in either direction**. Goal truth checked on dense real grids at
  irrational-offset steps (1/37, 1/53) so no grid point can land on a tie by construction.

  Blocking fixes applied:
  1. **DIRECTION §5.4(b′) — the corridor and the oracle gate contradict each other.** Per-leaf
     0.45 drives the per-episode oracle ceiling `(1−(1−p)^a)^k` below the ≥70% gate **from k=4 up**
     under the shipped `Budgets`. The shipped family passes (b) only by failing (c). Task #22;
     the attempt budget is the free variable. Added as **R5** so the ceiling is reported, not assumed.
  2. **R1 tie rule (0.08).** Without it, Monte Carlo over the note's own mixtures makes the shipped
     schema a coin flip (r2_prod 58.6% / r2_sum 39.2%) on a pair §6.2 explicitly declines to order.
  3. **Drop order 6/5/4 → 6/4/3.** The old order shed `r1_recip`, the only upper bracket *and* the
     cell §7.1's escalation branch reads first.
  4. **k=32 staged** (`--k-grid 2,4,8,32 --per-rung 40`, 186 leaves/rung). The old k∈{2,4,8} file
     could not reject a flatness failure at the top of the grid — coefficient magnitude grows ~k²
     and only 4.8% of k=32 leaves fell in the k=2 range. That is precisely how bridge_chain was
     written up as DONE while failing R3. Staged max|coef| now reaches ~39,000 vs ~2,200 before,
     so R3′ finally has support where it matters.
  5. **Anchor replication cell** (`data/families/ct_anchor_replication.jsonl`, 15 already-measured
     statements, anchor mean 0.767, spread 0.25–1.0). R0c was comparing a *redrawn* control against
     a historical aggregate whose leaf mix differs (staged v2 has 2.3× the anchor's median
     coefficient at k=8, true expectation ~0.913 not 0.923). Now a paired same-statement drift test.

  **Two corrections to earlier claims in this repo, both from the soundness review:**
  - `case_tree.py`'s r4 docstring justified the integer form with "`u·w` reaches ~10¹⁸ at k=32,
    past double precision." **False by six orders of magnitude** — measured max is 25,090 within a
    band, 4.0×10¹² across the whole domain at k=128, still ~2,200× *inside* float64's exact-integer
    range. The integer form is still mandatory, for the reason the review actually measured:
    `min |piece value − C_LEVEL|` is **exactly 0** on all six rungs, so knife-edge points exist and
    only exact arithmetic decides them the way the Lean statement does. Docstring corrected.
  - **The per-rung predicate dispatch has no observable effect on the shipped knob support.** Over
    2,268 knob cells × 41 integer points, all five non-v2 rungs' `holds_at` agree with v2's. The
    implementer's report — and the orchestrator's summary of it — over-credited it: the test that
    exhibits v2's predicate giving a wrong necessity answer uses a piece *outside* the shipped
    support. It is a guard against a future knob widening, not a fix for a live bug. Worth keeping;
    not worth the credit it was given.

  Also fixed: `gen_families.py` wrote `k{k}.jsonl` with no preset component while `append_row`
  appends, so materializing a second rung at the same k would have silently interleaved two
  distributions into one file that every consumer reads as one. Default-preset paths unchanged.
- 04:10 — **Pod A done and TERMINATED. Invoice $6.51** (wallet $38.45 → $31.93). 254 statements,
  0 errors. Spent $6.52 of the $12 cap; $5.48 left above the $26.45 floor.

  **My estimate was $3.50; the invoice is $6.51 — 86% low, after I had already added margin for
  setup specifically because the estimates run low.** Cause identified: the pod was up **2h12m**,
  not the ~80 min projected. The install alone took 13 min, and the measurement ran ~1h45m rather
  than the ~35 min the 430–480 rows/hr figure implies. The k=32 rows are the reason — they carry
  4-decade coefficients and much longer statements, so both generation and Lean verification are
  several times slower per row than the k≤8 baseline that throughput number came from. **Lesson for
  the runbook: throughput measured at k≤8 does not transfer to a k-grid that includes 32.**

  **RESULT: no rung reaches the corridor, and the reason is a finding.** Full write-up in
  `research/case-tree-hardening.md` §12. Headlines:
  - R0c: no drift (paired, t=+0.48). The $0.11 replication cell did its job.
  - Means: v2 0.847 | r2_prod 0.219 | r3_floor 0.169 | r2_sum 0.091 | r4_floorprod 0.025 |
    **r1_recip 0.000**. No rung passes R2.
  - **The corridor sits in a gap.** Nothing between 0.22 and 0.85. Difficulty w.r.t. this prover is
    a step function of idiom match, not a continuum. `r1_recip` — projected 0.62, the highest of any
    candidate — measured 0 of 312 attempts, diagnosed as a real capability result
    (elaborates=True, n_attempts=8, status leaf_failed on all 39).
  - **R3′ PASSES: coefficient magnitude is difficulty-neutral over four decades** (+0.0053/decade,
    z=+0.55, support 0.60–4.59). Staging k=32 is what bought this. It re-opens the quartic rungs
    (§3.8's exclusion was over-cautious) and restates the objection to bridge_chain's 3^k multiplier
    as "unmeasured at 10¹⁵" rather than "known to break flatness".
  - **R5 independently disqualifies the ladder**: no candidate meets DIRECTION §5.5(b) at any k>2
    even at 8 attempts/leaf. Added last night as a *reporting* requirement; it turned out to be a
    gate, and without it `r2_prod` would have shipped.
  - Projections: MAE 0.253 (registered 0.15–0.20), **all six errors negative** — systematic
    optimism, not noise. Rank order refuted.

  Registered escalation fires: **FAMILIES.md direction 1 (bank-drawn leaves)**. Phase 1 does not
  close for case_tree on this ladder.

- 04:15 — bridge_chain growth-law workflow (task #18) running locally, $0. Two candidate tracks →
  design → two adversarial lenses. Its brief was written before R3′ landed, so **R3′'s flat result
  is new information for it** — noted here for the morning; the design should be re-read against it
  rather than taken as final.

## MORNING DECISIONS FOR THE USER (do not need waking, but these are yours)

1. **Direction.** The synthetic-schema route is measured out for case_tree: the prover's competence
   is idiom-shaped and the corridor is in the gap. The escalation is bank-drawn leaves, which needs
   the wide sweep (#12, ~$45 — and note my estimates run ~50–90% low, so budget accordingly). That
   exceeds the remaining balance ($31.93) and was explicitly out of scope for tonight.
2. **The one cheap synthetic option R3′ re-opened**: reinstate `H2_quartic` (§3.8), which carried
   the highest projection of anything and was excluded on a flatness fear the data has now
   contradicted. One pod, ~$4–7 at realistic rates.
3. **#22 attempt budget** — R5 makes this urgent rather than theoretical. No corridor-target family
   can satisfy DIRECTION §5.5(b) at k>2 under the shipped `Budgets`. Raising it costs Phase-2/3 GPU
   linearly and touches a frozen core contract.
4. **#21 maxHeartbeats** — still open, still blocks the k=128 tier and DIRECTION §5.4(e).
5. Two contract reinterpretations from last night still want reviewer eyes: R3→R3′ and the
   leaf-disjointness leaf-level reading.
