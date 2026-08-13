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
