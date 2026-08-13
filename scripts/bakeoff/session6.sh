#!/usr/bin/env bash
# Session 6 (runs ON pod): PHASE 2 — the transfer-slope measurement.
#
# THE QUESTION (DIRECTION.md §7, registered before this ran): does the decomposition
# arm's advantage over the flat arm GROW WITH k? Both arms get the same problems, the
# same few-shot treatment and the same scoring path; only the harness differs.
#
#   family   case_tree preset v2 (leaves 0.847 -> oracle ceiling ~1.0, so a CORRECT plan
#            actually closes; at the hardened rungs' ~0.30 a perfect plan often fails and
#            "cannot decompose" would be confounded with "leaf could not finish")
#   k-grid   2, 4, 8      n   20 problems per k
#   arms     direct, decomp — both --few-shot, symmetric exemplars
#   roots    qwen3-30b-a3b-instruct-2507 (the Phase-3 RL target) and claude-haiku-4.5
#
# LEAF BUDGET IS NOT THE DEFAULT AND MUST NOT BE. DIRECTION §5.4(b′) / task #22: the
# shipped Budgets (4 attempts/leaf, 64 total) drive the oracle ceiling below the ≥70% gate
# from k=4 up. The n=32 replication put the filtered level at ~0.30, where 16 attempts/leaf
# clears every k to 32 with margin. Running this at the default would measure the budget,
# not the harness.
#
# Cells are independent: run_zeroshot.py owns scoring, resume and the spend cap, one JSONL
# per cell under results/zeroshot/. Re-running resumes rather than duplicates. A cell that
# fails is missing evidence, not a measured zero — the summary at the end says which.
#
# Marker: SESSION6_DONE
set -uo pipefail
cd /root/rlmath
export PATH="$HOME/.elan/bin:$PATH"
export PRIME_KEY="$(cat /root/.prime_key)"

BASE_URL="https://api.pinference.ai/api/v1"
TEAM="cmsp77l44000710s4dghtmtss"
LEAF=(--leaf-base-url http://localhost:8000/v1
      --leaf-model deepseek-ai/DeepSeek-Prover-V2-7B
      --leaf-template deepseek-prover-v2-non-cot)
# 16 attempts/leaf; total generous enough for k=32 later without re-editing this file.
BUDGET=(--leaf-attempts-per-lemma 16 --max-total-leaf-attempts 512 --max-lemmas 64)

N=20
mkdir -p logs/phase2 results/zeroshot
LOG=logs/session6.log
FAILED=()

cell() {   # cell <k> <arm> <root> <price_in> <price_out> <max_usd>
  local k="$1" arm="$2" root="$3" pin="$4" pout="$5" cap="$6"
  local tag="p2_k${k}_${arm}_$(printf '%s' "$root" | tr 'A-Z/' 'a-z-' | tr -c 'a-z0-9-' '-')"
  local args=(--problems "data/families/case_tree/k${k}.jsonl" --problem-set "case_tree"
              --k "$k" --arm "$arm" --few-shot
              --root-model "$root" --base-url "$BASE_URL" --api-key-env PRIME_KEY
              --extra-header "X-Prime-Team-ID=$TEAM"
              --n "$N" --max-usd "$cap" --price-in "$pin" --price-out "$pout"
              --out-dir results/zeroshot --workers 12)
  [ "$arm" = "decomp" ] && args+=("${LEAF[@]}" "${BUDGET[@]}")
  echo "== cell $tag" >> "$LOG"
  uv run python scripts/run_zeroshot.py "${args[@]}" >> "logs/phase2/${tag}.log" 2>&1
  local rc=$?
  [ "$rc" != "0" ] && { echo "   CELL FAILED rc=$rc" >> "$LOG"; FAILED+=("$tag"); }
}

# decomp before direct at each k: decomp is the measurement, direct is its paired baseline.
# k ascending so a budget stop-out loses the largest k rather than the whole grid.
for k in 2 4 8; do
  cell "$k" decomp "qwen/qwen3-30b-a3b-instruct-2507" 0.2 0.8 0.40
  cell "$k" direct "qwen/qwen3-30b-a3b-instruct-2507" 0.2 0.8 0.40
  cell "$k" decomp "anthropic/claude-haiku-4.5" 1 5 0.50
  cell "$k" direct "anthropic/claude-haiku-4.5" 1 5 0.50
done

echo "== cells failed: ${#FAILED[@]} ${FAILED[*]:-none}" >> "$LOG"
echo SESSION6_DONE >> "$LOG"
