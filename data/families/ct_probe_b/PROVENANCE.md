# ct_probe_b — survey B (alternative-obligation) raw records

Rescued from `/tmp/ct_functional_probe/` on 2026-08-12 23:53 by the orchestrator, not written
here by the survey agent: S2 owned only two files (`scripts/probes/probe_ct_functional.py` and
`research/ct-hardening-survey-b.md`), so its per-instance JSON went to a scratch directory that
`/tmp` reaping would eventually have deleted. The design note flagged the asymmetry — survey A's
records are durable under `data/families/ct_probe_a/`, survey B's were not — which would have left
four of the ladder's five rungs (`r1_recip`, `r2_prod`, `r3_floor`, and the `r4_floorprod` join)
reproducible only from prose.

| file | what it is |
|---|---|
| `report.json` | the full run: 12 directions × 12 instances, exact-predicate audit, witness kernel checks, full battery, idiom probe + adaptations |
| `floorprod.json` | the `floor_product` combination rung, probed separately |
| `twovar.json` | the `two_var` direction — REJECTED (necessity collapses with k: 0% redundant at k=4 → 16.7% at k=16/32) |
| `lintcheck.json` | post-hoc re-check after the `positivity` probe bug was found and fixed |

**Read `report.json` as the record of the corrected run.** The first full pass produced a wrong
headline: several adaptations used `by positivity` for the `0 ≤ radicand` side goal, and
`positivity` cannot prove `0 ≤ x^2 + 6x + 17` (a positive-definite quadratic is not a sum of
syntactically non-negative terms). Seven probes were failing for a reason unrelated to the
direction under test — including the only route that cracks `floor_sqrt`, which read 0/12 before
the fix and 12/12 after. Side goals now use `nlinarith [sq_nonneg (x - m)]`. The lesson is in
`research/ct-hardening-survey-b.md`: an idiom-ceiling probe can fail *pessimistically*, so read
each failure's error text rather than counting failures.
