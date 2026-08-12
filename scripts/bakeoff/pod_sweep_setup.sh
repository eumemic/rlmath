#!/usr/bin/env bash
# Wide-sweep pod: EVERYTHING runs pod-side — vLLM leaf, Lean verification, the
# bank builder. No SSH tunnel in the loop (the 2026-08-12 bake-off lost 222 rows
# to a tunnel death; the fix is to not have a tunnel).
# Success marker: SWEEP_POD_READY
set -euo pipefail

# --- 1. serving stack (proven recipe from pod_setup.sh — keep in sync)
pip install -q "vllm==0.9.2" "torch==2.7.0+cu126" "transformers==4.53.0" "huggingface_hub[cli]" \
  --extra-index-url https://download.pytorch.org/whl/cu126 < /dev/null 2>&1 | tail -1
python3 -c 'import torch, vllm, transformers; torch.zeros(1, device="cuda")'

echo "== downloading DSV2 (~15 GB)"
hf download deepseek-ai/DeepSeek-Prover-V2-7B < /dev/null > /dev/null

echo "== launching vLLM (whole GPU: single model tonight)"
if ! curl -s -m 2 http://localhost:8000/v1/models | grep -q '"id"'; then
  if ! pgrep -f "vllm serve" >/dev/null; then
    nohup vllm serve deepseek-ai/DeepSeek-Prover-V2-7B \
      --port 8000 --gpu-memory-utilization 0.90 --max-model-len 8192 \
      > /root/vllm_dsv2.log 2>&1 &
  fi
fi

# --- 2. Lean toolchain (runs while vLLM warms)
echo "== installing elan + mathlib project + repl"
# LESSON: never `curl | sh -s ... < /dev/null` — `sh -s` reads its SCRIPT from
# stdin, so the null redirect hands it an empty script and curl dies EPIPE(23).
# (Same self-inflicted bug previously misdiagnosed as an image sh problem.)
if [ ! -x "$HOME/.elan/bin/elan" ]; then
  curl -sSf https://elan.lean-lang.org/elan-init.sh -o /tmp/elan-init.sh
  sh /tmp/elan-init.sh -y --default-toolchain none < /dev/null
fi
export PATH="$HOME/.elan/bin:$PATH"

# --- 3. repo (public) + python env
cd /root
if [ ! -d rlmath ]; then git clone -q https://github.com/eumemic/rlmath; fi
cd rlmath
mkdir -p lean logs data/bank cache
cd lean
if [ ! -d rlmathlib ]; then
  lake +leanprover-community/mathlib4:lean-toolchain new rlmathlib math.toml
fi
cd rlmathlib && lake exe cache get 2>&1 | tail -1 && lake build 2>&1 | tail -1
cd ..
if [ ! -d repl ]; then git clone -q --depth 1 https://github.com/leanprover-community/repl; fi
cd repl && cp ../rlmathlib/lean-toolchain . && lake build 2>&1 | tail -1
test -x .lake/build/bin/repl

cd /root/rlmath
pip install -q uv < /dev/null 2>&1 | tail -1
uv sync -q 2>&1 | tail -1 || pip install -q -e . 2>&1 | tail -1

# --- 4. readiness: vLLM + one real Lean check
for i in $(seq 1 120); do
  curl -s -m 2 http://localhost:8000/v1/models | grep -q '"id"' && break
  [ "$i" = 120 ] && { echo "vllm TIMEOUT"; tail -n 20 /root/vllm_dsv2.log; exit 1; }
  sleep 5
done
echo "== vllm up; smoke-checking Lean"
cd /root/rlmath/lean/rlmathlib
printf '{"cmd": "import Mathlib\\ntheorem _s : 1 + 1 = 2 := by norm_num"}\n\n' \
  | lake env ../repl/.lake/build/bin/repl | grep -q '"env"' && echo "lean OK"
nvidia-smi --query-gpu=memory.used --format=csv,noheader
echo "SWEEP_POD_READY"
