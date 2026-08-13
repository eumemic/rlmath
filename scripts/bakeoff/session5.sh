#!/usr/bin/env bash
# Session 5 (runs ON pod): does an n=8 corridor filter survive n=32?
#
# THE QUESTION. research/case-tree-hardening.md §12.1 showed the corridor is reachable by
# measure-and-filter (r3_floor's filtered pool = 0.448 against a 0.45 target, band-fit 1.00
# by construction). But filtering at n=8 SELECTS ON NOISE: a leaf whose true rate is 0.95 can
# measure 7/8 = 0.875 and be kept; one at 0.5 can measure 8/8 and be dropped. So band-fit 1.00
# is a property of the measurement, not of the leaves. Everything downstream rests on this.
#
# THE DESIGN — two-sided on purpose. Re-measuring only the winners would confirm nothing: it
# cannot distinguish "the filter works" from "these leaves regress toward the middle like any
# noisy sample". So the input carries three strata (data/families/ct_n32_replication.jsonl):
#   in_band   33 leaves measured 0.25-0.9 at n=8  -> how many STAY in band at n=32?
#   zero       8 leaves measured 0/8              -> do any turn out to be in-band all along?
#   saturated  8 leaves measured 8/8              -> ditto from the other side
# Together they estimate the true-rate distribution rather than just re-checking a selection.
#
# 49 leaves x 32 attempts = 1,568 attempts, one pass, ~1h20m expected.
# Sampling profile is pinned to the anchor's so the n=8 and n=32 numbers are comparable:
# deepseek-ai/DeepSeek-Prover-V2-7B|deepseek-prover-v2-non-cot|Mdef|Tdef. Do NOT pass
# --leaf-max-tokens or --leaf-temperature.
#
# Marker: SESSION5_DONE
set -uo pipefail
cd /root/rlmath
export PATH="$HOME/.elan/bin:$PATH"

LEAF=(--leaf-base-url http://localhost:8000/v1
      --leaf-model deepseek-ai/DeepSeek-Prover-V2-7B
      --leaf-template deepseek-prover-v2-non-cot)

mkdir -p logs data/bank
LOG=logs/session5.log

echo "== n=32 replication of the n=8 filter (49 leaves, 3 strata)" >> "$LOG"
uv run python scripts/build_bank.py --dataset json \
  --data-files data/families/ct_n32_replication.jsonl \
  --k 32 --backend repl --workers 12 --concurrent 6 "${LEAF[@]}" \
  --out data/bank/ct_n32_measure.jsonl >> "$LOG" 2>&1
echo "   rows: $(wc -l < data/bank/ct_n32_measure.jsonl)" >> "$LOG"

echo SESSION5_DONE >> "$LOG"
