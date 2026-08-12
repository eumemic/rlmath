#!/usr/bin/env bash
# Runs ON THE MAC. Drives the leaf bake-off (task #9, DIRECTION.md §5.3/§5.4):
# same candidate slice through both served provers, separate provenance-guarded
# out files, verification through the local ReplPool.
#
# Usage: bash scripts/bakeoff/run_bakeoff.sh <pod-ssh-host> [limit] [k]
# Assumes `ssh <pod-ssh-host>` works (prime pods status gives the SSH line);
# forwards :8000/:8001 for the duration of the run.
set -euo pipefail
HOST="${1:?usage: run_bakeoff.sh <pod-ssh-host> [limit] [k]}"
LIMIT="${2:-300}"
K="${3:-8}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "== port-forward :8000/:8001 via ${HOST}"
ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -N \
  -L 8000:localhost:8000 -L 8001:localhost:8001 "$HOST" &
TUNNEL=$!
trap 'kill $TUNNEL 2>/dev/null || true' EXIT
sleep 3
curl -s -m 5 http://localhost:8000/v1/models | grep -q '"id"' || { echo "dsv2 not reachable"; exit 1; }
curl -s -m 5 http://localhost:8001/v1/models | grep -q '"id"' || { echo "goedel not reachable"; exit 1; }

# Same slice both arms: identical --seed/--limit against the same dataset order.
# early_stop=False inside build_bank -> true pass@k. Separate --out per model:
# the provenance guard makes cross-contamination structurally impossible.
common=(--seed 42 --limit "$LIMIT" --k "$K" --backend repl --workers 2)

echo "== arm 1/2: DeepSeek-Prover-V2-7B (non-CoT)"
uv run python scripts/build_bank.py "${common[@]}" \
  --leaf-base-url http://localhost:8000/v1 \
  --leaf-model deepseek-ai/DeepSeek-Prover-V2-7B \
  --leaf-template deepseek-prover-v2-non-cot \
  --out data/bank/bakeoff_dsv2.jsonl

echo "== arm 2/2: Goedel-Prover-V2-8B (CoT, long generations)"
uv run python scripts/build_bank.py "${common[@]}" \
  --leaf-base-url http://localhost:8001/v1 \
  --leaf-model Goedel-LM/Goedel-Prover-V2-8B \
  --leaf-template goedel-prover-v2 --leaf-max-tokens 16384 \
  --out data/bank/bakeoff_goedel.jsonl

echo "== band-fit analysis"
uv run python scripts/bakeoff/analyze.py \
  data/bank/bakeoff_dsv2.jsonl data/bank/bakeoff_goedel.jsonl
echo "BAKEOFF_DONE"
