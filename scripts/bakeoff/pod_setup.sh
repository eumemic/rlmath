#!/usr/bin/env bash
# Runs ON the bake-off pod (H100 80GB, cuda_12_6_pytorch_2_7 image).
# Serves both candidate leaf provers in bf16 on one GPU:
#   :8000  deepseek-ai/DeepSeek-Prover-V2-7B   (non-CoT bake-off arm)
#   :8001  Goedel-LM/Goedel-Prover-V2-8B       (CoT-style arm, long generations)
# Success marker: BAKEOFF_POD_READY
set -euo pipefail

export HF_HUB_ENABLE_HF_TRANSFER=1
# LESSON (cost three crash loops on 2026-08-12; keep this recipe until a reason not to):
#  - bare `pip install -U vllm` -> torch cu130 vs the pod's 12.8 driver -> init_device dies
#  - resolver-picked vllm 0.26.0 accepts torch 2.11+cu128 in METADATA but its compiled
#    extensions link libcudart.so.13 -> ImportError. Wheel ABI is ground truth, not metadata.
#  - the uv installer's curl|sh does not survive this image's /bin/sh
# What works: the battle-tested 2025 pairing, matching the image's original CUDA era.
#  - and pin transformers to the same era: vllm 0.9.2 registers an 'aimv2' config
#    that current transformers ships natively -> ValueError at import.
pip install -q "vllm==0.9.2" "torch==2.7.0+cu126" "transformers==4.53.0" "huggingface_hub[cli]" \
  --extra-index-url https://download.pytorch.org/whl/cu126 < /dev/null 2>&1 | tail -1
python3 -c 'import torch, vllm, transformers; torch.zeros(1, device="cuda")'  # fail HERE, not in the engine

echo "== downloading models (~35 GB total)"
# `huggingface-cli download` is a deprecated shim in current hf tooling (prints
# help, downloads nothing, exits 0 — cost one silent no-op on the first pod run).
# `< /dev/null` guards every long command against eating stdin if this script is
# ever streamed via `bash -s` again.
hf download deepseek-ai/DeepSeek-Prover-V2-7B < /dev/null > /dev/null
hf download Goedel-LM/Goedel-Prover-V2-8B < /dev/null > /dev/null
du -sh /root/.cache/huggingface

echo "== launching vLLM servers (SEQUENTIALLY — concurrent launch loses a memory race:"
echo "   both engines profile free memory mid-load and DSV2's KV budget came up 1.22GiB/3.75GiB)"
nohup vllm serve Goedel-LM/Goedel-Prover-V2-8B \
  --port 8001 --gpu-memory-utilization 0.50 --max-model-len 24576 \
  > /root/vllm_goedel.log 2>&1 &
for i in $(seq 1 90); do
  curl -s -m 2 http://localhost:8001/v1/models | grep -q '"id"' && break
  [ "$i" = 90 ] && { echo "goedel TIMEOUT"; tail -n 20 /root/vllm_goedel.log; exit 1; }
  sleep 5
done
echo "goedel up; launching dsv2"
nohup vllm serve deepseek-ai/DeepSeek-Prover-V2-7B \
  --port 8000 --gpu-memory-utilization 0.35 --max-model-len 8192 \
  > /root/vllm_dsv2.log 2>&1 &

echo "== waiting for readiness"
for port in 8000 8001; do
  for i in $(seq 1 120); do
    if curl -s -m 2 "http://localhost:${port}/v1/models" | grep -q '"id"'; then
      echo "port ${port} ready"; break
    fi
    if [ "$i" = 120 ]; then echo "port ${port} TIMEOUT"; tail -n 20 /root/vllm_dsv2.log /root/vllm_goedel.log; exit 1; fi
    sleep 5
  done
done
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
echo "BAKEOFF_POD_READY"
