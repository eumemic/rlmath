# Local-gate drivers for the case_tree hardening ladder (2026-08-13)

These produced every `gate_*.json` in the parent directory
(`research/case-tree-hardening.md` §11). They live under `data/` **only** because the
agent that ran the gate owned `data/families/ct_battery/**` and not `scripts/**`;
their natural home is `scripts/probes/`, next to `probe_ct_algebraic.py` and
`probe_ct_functional.py`. Moving them there is a no-op apart from the import
shim at the top of each file. This placement is flagged in §11.13.

Run order (each is `uv run python <file>` from the repo root; all read-only on
the generator, all write into the parent directory):

| file | phase | writes |
|---|---|---|
| `offline.py` | free structural computations: target width, tightness, distinct-leaf capacity, flatness structurals, R3′ power, necessity sweep + predicate audit at k ∈ {2,4,8,16,32} | `gate_offline.json` |
| `extended.py` | planted control (alone, first, aborts on survival) → battery on a knob-spanning subset + one goal per rung → witness kernel check on **all** staged leaves → idiom probe → k=32 structural validation | `gate_control.json`, `gate_battery_ext.json`, `gate_witness_all.json`, `gate_idiom.json`, `gate_validate_k32.json` |
| `k32.py` | where the elaboration wall is: V1–V4/V6 at k = 16/32/64, 3 seeds where it mattered | `gate_validate_scaling.json` |
| `heartbeat.py`, `hb2.py` | is the wall a heartbeat budget? recompose with `set_option maxHeartbeats` raised | `gate_heartbeat.json` |
| `rowmap.py` | per-staged-row verdicts (witness ok / battery probed / killers) | `gate_rows.jsonl` |

The sixth artifact set (`structural.json`, `<rung>.jsonl`, `battery.json`,
`validate.json`) comes from the shipped stager, not from these:

```bash
uv run python scripts/stage_ct_candidates.py \
  --rungs v2,r1_recip,r2_prod,r2_sum,r3_floor,r4_floorprod \
  --k-grid 2,4,8 --per-rung 30 --seed 5150 \
  --battery-n 6 --with-battery --validate --validate-n 3 --workers 4
```
