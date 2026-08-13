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
