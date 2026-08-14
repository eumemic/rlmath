#!/usr/bin/env bash
# Phase-3 setup, corrected: build the training env under Python 3.12 via uv.
#
# WHY: `pod_phase3_setup.sh` pip-installed into the image's SYSTEM python, which is 3.10.12.
# `rlmath` declares `requires-python = ">=3.12"` and means it — `core/types.py` uses `StrEnum`,
# which is 3.11+. So `pip install -e .` failed with
#   ERROR: Package 'rlmath' requires a different Python: 3.10.12 not in '>=3.12'
# The measurement pods never hit this because they drive everything through `uv`, which
# provisions its own interpreter. The training script imports rlmath (for the reward function),
# so it must run under the same 3.12 env as the package.
#
# This script is idempotent and re-runnable: Lean/Mathlib from the first pass are reused, only
# the Python side is rebuilt.
#
# Success marker: PHASE3_FIXED_READY
set -euo pipefail
export PATH="$HOME/.elan/bin:$HOME/.local/bin:$PATH"
cd /root/rlmath

command -v uv >/dev/null || pip install -q uv < /dev/null
uv venv --python 3.12 .venv312
# shellcheck disable=SC1091
source .venv312/bin/activate
python -V

echo "== training stack under 3.12"
uv pip install -q "torch==2.7.0+cu126" --extra-index-url https://download.pytorch.org/whl/cu126
uv pip install -q -U "transformers>=4.57" "trl>=0.21" "peft>=0.14" accelerate datasets "huggingface_hub[cli]"
uv pip install -q -e .
python -c 'import torch, transformers, trl, peft, rlmath; print("torch", torch.__version__, "tf", transformers.__version__, "trl", trl.__version__, "peft", peft.__version__); torch.zeros(1, device="cuda"); print("rlmath imports OK")'

echo "== reward path end-to-end under this interpreter (Lean must answer from HERE)"
python - <<'PY'
import json, sys
from rlmath.core import leancode
from rlmath.core.plan_format import PlanFormatError, parse_plan
from rlmath.core.types import GoalSpec
from rlmath.lean.repl_pool import ReplPool
p = json.loads(open('data/phase3/eval/case_tree/k2.jsonl').readline())
goal = GoalSpec(id=p['goal']['id'], prop=p['goal']['prop'], name='goal')
op = p['oracle_plan']
good = "\n".join([f"#lemma {l['name']} : {l['prop']}" for l in op['lemmas']] + ["#assembly", op['assembly'], "#end"])
pool = ReplPool(n_workers=2)
r = pool.check_many([leancode.plan_check(goal, parse_plan(good))], timeout_s=120.0)[0]
pool.close()
assert r.ok and r.sorries == 0, f"oracle plan did not pass stage 1 on the pod: {r.messages}"
print("reward path OK (oracle plan -> 1.0)")
PY

echo "== model architecture"
python - <<'PY'
from transformers import AutoConfig, AutoTokenizer
m = "Qwen/Qwen3.5-9B"
print("model_type:", AutoConfig.from_pretrained(m, trust_remote_code=True).model_type)
AutoTokenizer.from_pretrained(m, trust_remote_code=True)
print("tokenizer OK")
PY
echo "PHASE3_FIXED_READY"
