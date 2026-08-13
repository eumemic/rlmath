#!/usr/bin/env bash
# Session 4 (runs ON pod): case_tree hardening-ladder confirm pass.
#
# Measures pass@8 for the six staged rungs (research/case-tree-hardening.md §3)
# plus a replication cell of 15 already-measured statements. Everything is
# pod-side; there is no tunnel (the 2026-08-12 bake-off lost 222 rows to one).
#
# Two output files, deliberately separate:
#   ct_ladder_calibration.jsonl — the ladder, 239 rows, the thing R0–R5 read
#   ct_anchor_measure.jsonl     — R0c's PAIRED drift test against statements whose
#                                 pass@8 was measured on 2026-08-12. Comparing a
#                                 freshly-drawn control against a historical
#                                 aggregate cannot separate drift from a different
#                                 leaf mix; the same statements can.
#
# Sampling profile must match the anchor exactly or the comparison is void:
# leaf_id = deepseek-ai/DeepSeek-Prover-V2-7B|deepseek-prover-v2-non-cot|Mdef|Tdef,
# so do NOT pass --leaf-max-tokens or --leaf-temperature. build_bank's provenance
# guard refuses to mix profiles in one file anyway.
#
# Marker: SESSION4_DONE
set -uo pipefail
cd /root/rlmath
export PATH="$HOME/.elan/bin:$PATH"

LEAF=(--leaf-base-url http://localhost:8000/v1
      --leaf-model deepseek-ai/DeepSeek-Prover-V2-7B
      --leaf-template deepseek-prover-v2-non-cot)
BK=(--k 8 --backend repl --workers 12 --concurrent 6)

mkdir -p logs data/bank
LOG=logs/session4.log

echo "== [1/2] anchor replication (15 already-measured statements) — R0c" >> "$LOG"
# Runs FIRST and is cheap (~2 min): if the prover or harness has drifted, that is
# knowable before spending the ladder's 35 minutes.
uv run python scripts/build_bank.py --dataset json \
  --data-files data/families/ct_anchor_replication.jsonl \
  "${BK[@]}" "${LEAF[@]}" --out data/bank/ct_anchor_measure.jsonl >> "$LOG" 2>&1
echo "   anchor rows: $(wc -l < data/bank/ct_anchor_measure.jsonl)" >> "$LOG"

echo "== [2/2] ladder confirm (239 leaves: 6 rungs x k in {2,4,8,32})" >> "$LOG"
uv run python scripts/build_bank.py --dataset json \
  --data-files data/families/ct_candidates.jsonl \
  "${BK[@]}" "${LEAF[@]}" --out data/bank/ct_ladder_calibration.jsonl >> "$LOG" 2>&1
echo "   ladder rows: $(wc -l < data/bank/ct_ladder_calibration.jsonl)" >> "$LOG"

echo SESSION4_DONE >> "$LOG"
