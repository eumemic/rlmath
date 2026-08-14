#!/usr/bin/env bash
# Phase-3 pod, ONE PASS. Every fix from the seven serial setup failures, in order, with the
# gates that catch each class — then the trainer preflight, then the real run.
#
# The seven, for whoever reads this next:
#   1. system python is 3.10.12; rlmath requires >=3.12 (StrEnum)  -> uv venv --python 3.12
#   2. `uv pip install -U trl transformers` replaced pinned cu126 torch with cu130 on a 12.8
#      driver -> install frameworks first, then torch from PyTorch's OWN --index-url, LAST
#   3. `pkill -f fix.sh` matched its own launching shell -> never pattern-match your own cmdline;
#      use a done-file sentinel
#   4. trl 1.10 GRPOConfig has no `max_prompt_length` -> removed
#   5. per_device_train_batch_size counts COMPLETIONS and must divide by num_generations
#   6. Qwen3.5 is a VL model; its processor needs torchvision
#   7. ...and AutoProcessor builds Qwen3VL VIDEO processors, which raises a transformers
#      docstring error -> pass processing_class=tokenizer explicitly
#
# Marker: P3_ALL_READY  (then the trainer runs and prints TRAIN_DONE)
set -euo pipefail
export PATH="$HOME/.elan/bin:$HOME/.local/bin:$PATH"

echo "== [1/5] repo + python 3.12 env"
cd /root
[ -d rlmath ] || git clone -q https://github.com/eumemic/rlmath
cd rlmath && git pull -q origin master && mkdir -p logs runs lean
command -v uv >/dev/null || pip install -q uv < /dev/null
[ -d .venv312 ] || uv venv --python 3.12 .venv312
# shellcheck disable=SC1091
source .venv312/bin/activate
python -V

echo "== [2/5] frameworks, THEN torch last from PyTorch's index (driver is 12.8 -> cu128)"
uv pip install -q -U "transformers>=4.57" "trl>=0.21" "peft>=0.14" accelerate datasets "huggingface_hub[cli]"
uv pip install -q --reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu128
uv pip install -q -e .
python - <<'EOF'
import torch, transformers, trl, peft, torchvision, rlmath
print("torch", torch.__version__, "| tv", torchvision.__version__, "| tf", transformers.__version__,
      "| trl", trl.__version__, "| peft", peft.__version__)
assert torch.cuda.is_available()
(torch.zeros(512, 512, device="cuda", dtype=torch.bfloat16) @
 torch.ones(512, 512, device="cuda", dtype=torch.bfloat16)); torch.cuda.synchronize()
print("cuda bf16 matmul OK")
EOF

echo "== [3/5] Lean + Mathlib (the REWARD calls this every rollout)"
if [ ! -x "$HOME/.elan/bin/elan" ]; then
  curl -sSf https://elan.lean-lang.org/elan-init.sh -o /tmp/elan-init.sh
  sh /tmp/elan-init.sh -y --default-toolchain none < /dev/null   # never `curl | sh -s`
fi
export PATH="$HOME/.elan/bin:$PATH"
cd /root/rlmath/lean
[ -d rlmathlib ] || lake +leanprover-community/mathlib4:lean-toolchain new rlmathlib math.toml
cd rlmathlib && lake exe cache get 2>&1 | tail -1 && lake build 2>&1 | tail -1
cd .. && [ -d repl ] || git clone -q --depth 1 https://github.com/leanprover-community/repl
cd repl && cp ../rlmathlib/lean-toolchain . && lake build 2>&1 | tail -1
test -x .lake/build/bin/repl && echo "repl built"

echo "== [4/5] reward path end-to-end under THIS interpreter"
cd /root/rlmath
python - <<'EOF'
import json
from rlmath.core import leancode
from rlmath.core.plan_format import parse_plan
from rlmath.core.types import GoalSpec
from rlmath.lean.repl_pool import ReplPool
p = json.loads(open('data/phase3/eval/case_tree/k2.jsonl').readline())
goal = GoalSpec(id=p['goal']['id'], prop=p['goal']['prop'], name='goal')
op = p['oracle_plan']
good = "\n".join([f"#lemma {l['name']} : {l['prop']}" for l in op['lemmas']] + ["#assembly", op['assembly'], "#end"])
pool = ReplPool(n_workers=4)
r = pool.check_many([leancode.plan_check(goal, parse_plan(good))], timeout_s=120.0)[0]
pool.close()
assert r.ok and r.sorries == 0, f"oracle plan failed stage 1: {r.messages}"
print("reward path OK (oracle -> 1.0)")
EOF

echo "== [5/5] TRAINER PREFLIGHT: construct GRPOTrainer, one real step, measure s/step"
python scripts/preflight_trainer.py --completions 4 --group-size 4 --tokens 128
echo "P3_ALL_READY"
