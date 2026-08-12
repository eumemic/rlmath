#!/usr/bin/env bash
# Session 3 (runs ON pod): retune measurement -> calibration completion -> roster.
# Marker: SESSION3_DONE
set -uo pipefail
cd /root/rlmath
export PATH="$HOME/.elan/bin:$PATH"
export PRIME_KEY=$(cat /root/.prime_key)
LEAF=(--leaf-base-url http://localhost:8000/v1 --leaf-model deepseek-ai/DeepSeek-Prover-V2-7B --leaf-template deepseek-prover-v2-non-cot)
BK=(--k 8 --backend repl --workers 12 --concurrent 6)

echo "== [1/3] retune preset measurement (150 leaves)" >> logs/session3.log
uv run python scripts/build_bank.py --dataset json --data-files data/families/retune_candidates.jsonl \
  "${BK[@]}" "${LEAF[@]}" --out data/bank/retune_measure.jsonl >> logs/session3.log 2>&1

echo "== [2/3] calibration completion (case_tree remainder)" >> logs/session3.log
uv run python scripts/build_bank.py --dataset json --data-files data/families/family_leaves_candidates.jsonl \
  "${BK[@]}" "${LEAF[@]}" --out data/bank/family_leaf_calibration.jsonl >> logs/session3.log 2>&1

echo "== [3/3] four-root roster" >> logs/session3.log
bash scripts/run_roster.sh http://localhost:8000/v1 deepseek-ai/DeepSeek-Prover-V2-7B deepseek-prover-v2-non-cot >> logs/session3.log 2>&1

echo SESSION3_DONE >> logs/session3.log
