#!/usr/bin/env bash
# Runs ON the bake-off pod (H100 80GB, cuda_12_6_pytorch_2_7 image).
# Serves both candidate leaf provers in bf16 on one GPU:
#   :8000  deepseek-ai/DeepSeek-Prover-V2-7B   (non-CoT bake-off arm)
#   :8001  Goedel-LM/Goedel-Prover-V2-8B       (CoT-style arm, long generations)
# Success marker: BAKEOFF_POD_READY
set -euo pipefail

export HF_HUB_ENABLE_HF_TRANSFER=1
pip install -q -U vllm hf_transfer "huggingface_hub[cli]" 2>&1 | tail -1

echo "== downloading models (~35 GB total)"
huggingface-cli download deepseek-ai/DeepSeek-Prover-V2-7B > /dev/null
huggingface-cli download Goedel-LM/Goedel-Prover-V2-8B > /dev/null

echo "== launching vLLM servers"
# 7B + 8B bf16 (~15+17 GB weights) fit one 80GB card with split KV budgets.
# DSV2 non-CoT: short generations, modest context. Goedel: long CoT, bigger len.
nohup vllm serve deepseek-ai/DeepSeek-Prover-V2-7B \
  --port 8000 --gpu-memory-utilization 0.40 --max-model-len 8192 \
  > /root/vllm_dsv2.log 2>&1 &
nohup vllm serve Goedel-LM/Goedel-Prover-V2-8B \
  --port 8001 --gpu-memory-utilization 0.50 --max-model-len 24576 \
  > /root/vllm_goedel.log 2>&1 &

echo "== waiting for readiness"
for port in 8000 8001; do
  for i in $(seq 1 120); do
    if curl -s -m 2 "http://localhost:${port}/v1/models" | grep -q '"id"'; then
      echo "port ${port} ready"; break
    fi
    if [ "$i" = 120 ]; then echo "port ${port} TIMEOUT"; tail -20 /root/vllm_*.log; exit 1; fi
    sleep 5
  done
done
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
echo "BAKEOFF_POD_READY"
