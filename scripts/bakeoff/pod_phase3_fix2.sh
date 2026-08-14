#!/usr/bin/env bash
# Phase-3 setup, pass 3: pin torch LAST so nothing can upgrade it out from under the driver.
#
# WHAT BROKE. pass 2 did:
#     uv pip install "torch==2.7.0+cu126" --extra-index-url .../cu126
#     uv pip install -U "transformers>=4.57" "trl>=0.21" ...
# and the second command's `-U` resolved a fresh torch as a dependency, landing
# **torch 2.13.0+cu130** on a pod whose driver is **12.8**:
#     RuntimeError: The NVIDIA driver on your system is too old (found version 12080)
# The pin was real but it was not last, and `--extra-index-url` leaves PyPI as a candidate
# source. This is the same class as the runbook's vLLM lesson — the wheel's linked CUDA is the
# truth, and here the resolver silently replaced a correct wheel with an incorrect one.
#
# FIX: install the framework packages first, then force torch from PyTorch's OWN index
# (`--index-url`, not `--extra-index-url`, so PyPI cannot win), then HARD-FAIL on a real CUDA
# allocation. Driver 12.8 -> cu128 wheels, which also lets transformers/trl stay recent enough
# for Qwen3.5's `qwen3_5` architecture.
#
# Success marker: PHASE3_READY3
set -euo pipefail
export PATH="$HOME/.elan/bin:$HOME/.local/bin:$PATH"
cd /root/rlmath
# shellcheck disable=SC1091
source .venv312/bin/activate

echo "== frameworks first (they may drag in whatever torch they like; we overwrite it next)"
uv pip install -q -U "transformers>=4.57" "trl>=0.21" "peft>=0.14" accelerate datasets "huggingface_hub[cli]"

echo "== torch LAST, from PyTorch's own index, matching the 12.8 driver"
uv pip install -q --reinstall torch --index-url https://download.pytorch.org/whl/cu128

echo "== hard gate: a real CUDA allocation, not just an import"
python - <<'PY'
import torch, transformers, trl, peft
print("torch", torch.__version__, "| tf", transformers.__version__,
      "| trl", trl.__version__, "| peft", peft.__version__)
assert torch.cuda.is_available(), "CUDA not available"
x = torch.zeros(1024, 1024, device="cuda", dtype=torch.bfloat16) @ \
    torch.ones(1024, 1024, device="cuda", dtype=torch.bfloat16)
torch.cuda.synchronize()
print("cuda bf16 matmul OK on", torch.cuda.get_device_name(0))
PY

echo "== rlmath + reward path under this interpreter"
uv pip install -q -e .
python - <<'PY'
import json
from rlmath.core import leancode
from rlmath.core.plan_format import parse_plan
from rlmath.core.types import GoalSpec
from rlmath.lean.repl_pool import ReplPool
p = json.loads(open('data/phase3/eval/case_tree/k2.jsonl').readline())
goal = GoalSpec(id=p['goal']['id'], prop=p['goal']['prop'], name='goal')
op = p['oracle_plan']
good = "\n".join([f"#lemma {l['name']} : {l['prop']}" for l in op['lemmas']] + ["#assembly", op['assembly'], "#end"])
pool = ReplPool(n_workers=2)
r = pool.check_many([leancode.plan_check(goal, parse_plan(good))], timeout_s=120.0)[0]
pool.close()
assert r.ok and r.sorries == 0, f"oracle plan failed stage 1 on the pod: {r.messages}"
print("reward path OK (oracle plan -> 1.0)")
PY

echo "== TRL API surface actually matches the trainer (fail here, not 20 min in)"
python - <<'PY'
import inspect
from trl import GRPOConfig, GRPOTrainer
cfg = set(inspect.signature(GRPOConfig.__init__).parameters)
need = {"learning_rate", "max_steps", "per_device_train_batch_size", "num_generations",
        "max_completion_length", "bf16", "temperature"}
missing = need - cfg
print("GRPOConfig missing:", missing or "none")
tr = set(inspect.signature(GRPOTrainer.__init__).parameters)
print("GRPOTrainer params:", sorted(tr - {"self"}))
assert not missing, f"trainer script uses GRPOConfig args this trl does not have: {missing}"
PY

echo "== model architecture"
python - <<'PY'
from transformers import AutoConfig, AutoTokenizer
m = "Qwen/Qwen3.5-9B"
print("model_type:", AutoConfig.from_pretrained(m, trust_remote_code=True).model_type)
AutoTokenizer.from_pretrained(m, trust_remote_code=True)
print("tokenizer OK")
PY
echo "PHASE3_READY3"
