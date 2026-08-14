#!/usr/bin/env bash
# Phase-3 training pod: GRPO on the decomposition root.
#
# SIMPLER THAN THE MEASUREMENT PODS, and for a reason worth stating: the Phase-3 reward is
# **stage-1 plan validity**, which needs no leaf prover. So there is no vLLM, no DeepSeek-Prover
# download, no second model resident on the GPU — just the trainee, LoRA, and Lean. That frees
# the whole 80 GB for training and removes the piece that has broken most often.
#
# What it does need that the measurement pods did not: torch/trl/peft/transformers, and a
# Mathlib that the REWARD FUNCTION calls on every rollout. Lean is in the training loop here,
# not beside it.
#
# Success marker: PHASE3_POD_READY
set -euo pipefail

# NOTE (2026-08-14): this script pip-installs into the image's SYSTEM python, which is 3.10.12
# on cuda_12_6_pytorch_2_7 — and rlmath requires >=3.12 (StrEnum). Use
# `pod_phase3_fix.sh` after this one; it rebuilds the Python side under uv's 3.12 and reuses
# the Lean/Mathlib work below. Kept as-is because the Lean half is correct and slow.
echo "== training stack"
# transformers must be recent: Qwen3.5 ships arch `qwen3_5`, which the 4.53 pin used for the
# vLLM measurement pods does not know. Nothing here talks to vLLM, so that pin does not apply.
pip install -q "torch==2.7.0+cu126" --extra-index-url https://download.pytorch.org/whl/cu126 < /dev/null 2>&1 | tail -1
pip install -q -U "transformers>=4.57" "trl>=0.21" "peft>=0.14" accelerate datasets "huggingface_hub[cli]" < /dev/null 2>&1 | tail -1
python3 -c 'import torch, transformers, trl, peft; print("torch", torch.__version__, "tf", transformers.__version__, "trl", trl.__version__); torch.zeros(1, device="cuda")'

echo "== elan + mathlib + repl (the reward function runs Lean every rollout)"
# LESSON: never `curl … | sh -s … < /dev/null` — `sh -s` reads its SCRIPT from stdin, so the
# redirect hands it an empty program. Download, then run.
if [ ! -x "$HOME/.elan/bin/elan" ]; then
  curl -sSf https://elan.lean-lang.org/elan-init.sh -o /tmp/elan-init.sh
  sh /tmp/elan-init.sh -y --default-toolchain none < /dev/null
fi
export PATH="$HOME/.elan/bin:$PATH"

cd /root
[ -d rlmath ] || git clone -q https://github.com/eumemic/rlmath
cd rlmath && mkdir -p lean logs runs
cd lean
[ -d rlmathlib ] || lake +leanprover-community/mathlib4:lean-toolchain new rlmathlib math.toml
cd rlmathlib && lake exe cache get 2>&1 | tail -1 && lake build 2>&1 | tail -1
cd ..
[ -d repl ] || git clone -q --depth 1 https://github.com/leanprover-community/repl
cd repl && cp ../rlmathlib/lean-toolchain . && lake build 2>&1 | tail -1
test -x .lake/build/bin/repl

cd /root/rlmath
pip install -q uv < /dev/null 2>&1 | tail -1
pip install -q -e . < /dev/null 2>&1 | tail -1

echo "== readiness: a real Lean check, then the model actually loading"
cd /root/rlmath/lean/rlmathlib
printf '{"cmd": "import Mathlib\\ntheorem _s : 1 + 1 = 2 := by norm_num"}\n\n' \
  | lake env ../repl/.lake/build/bin/repl | grep -q '"env"' && echo "lean OK"
cd /root/rlmath
# Fail HERE if the architecture is unsupported — not 20 minutes into a training run.
python3 - <<'PY'
from transformers import AutoConfig, AutoTokenizer
m = "Qwen/Qwen3.5-9B"
print("config:", AutoConfig.from_pretrained(m, trust_remote_code=True).model_type)
AutoTokenizer.from_pretrained(m, trust_remote_code=True)
print("tokenizer OK")
PY
nvidia-smi --query-gpu=memory.total --format=csv,noheader
echo "PHASE3_POD_READY"
