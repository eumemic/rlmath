#!/usr/bin/env bash
# Phase-3 preflight: exercise the ENTIRE path once, cheaply, before the trainer runs.
#
# WHY THIS EXISTS. Five separate setup incompatibilities were found one per launch, each
# costing a pod-cycle: py3.10 vs the package's 3.12, a resolver replacing pinned cu126 torch
# with cu130, a pkill pattern that killed its own launching shell, `max_prompt_length` removed
# from trl 1.10's GRPOConfig, and `per_device_train_batch_size` counting completions rather
# than prompts. Then a sixth — Qwen3.5 is a **VL** model (`image-text-to-text`), so its
# processor imports Qwen2VLImageProcessor, which needs **torchvision**, which nothing pulled in.
#
# Finding those serially at ~$3.20/hr is the wrong way to buy information. This script walks the
# whole pipeline in one pass — install, load, generate, parse, reward, time it — so the next
# failure (if any) is found in the same cycle as this one.
#
# Success marker: PREFLIGHT_OK
set -euo pipefail
export PATH="$HOME/.elan/bin:$HOME/.local/bin:$PATH"
cd /root/rlmath
# shellcheck disable=SC1091
source .venv312/bin/activate

echo "== torchvision (Qwen3.5 is a VL model; its processor needs it), matched to torch's cu128"
uv pip install -q torchvision --index-url https://download.pytorch.org/whl/cu128
python -c 'import torch, torchvision; print("torch", torch.__version__, "| torchvision", torchvision.__version__)'

echo "== full path: load -> generate -> parse -> reward, with timings"
python - <<'PY'
import json, time
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from rlmath.core import leancode
from rlmath.core.plan_format import PlanFormatError, parse_plan
from rlmath.core.types import GoalSpec
from rlmath.envs.decomp_env import build_prompt
from rlmath.eval.arms import with_exemplar
from rlmath.eval.exemplars import build_exemplar, load_exemplar_problem
from rlmath.lean.repl_pool import ReplPool

M = "Qwen/Qwen3.5-9B"
t0 = time.time()
tok = AutoTokenizer.from_pretrained(M, trust_remote_code=True)
model = AutoModelForCausalLM.from_pretrained(M, torch_dtype=torch.bfloat16,
                                             device_map="cuda", trust_remote_code=True)
print(f"model loaded in {time.time()-t0:.0f}s; {torch.cuda.memory_allocated()/1e9:.1f} GB allocated")

ex = build_exemplar(load_exemplar_problem("case_tree", k=2, seed=999), "decomp")
rows = [json.loads(l) for l in open("data/phase3/eval/case_tree/k2.jsonl")][:4]
pool = ReplPool(n_workers=4)

gen_t, lean_t, rewards = 0.0, 0.0, []
for r in rows:
    goal = GoalSpec(id=r["goal"]["id"], prop=r["goal"]["prop"], name="goal")
    msgs = with_exemplar(build_prompt(goal), ex)
    text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    ids = tok(text, return_tensors="pt").to(model.device)
    t = time.time()
    with torch.no_grad():
        out = model.generate(**ids, max_new_tokens=640, do_sample=True, temperature=0.7,
                             top_p=0.95, pad_token_id=tok.pad_token_id or tok.eos_token_id)
    gen_t += time.time() - t
    comp = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
    try:
        plan = parse_plan(comp)
    except PlanFormatError:
        rewards.append(0.0); continue
    t = time.time()
    res = pool.check_many([leancode.plan_check(goal, plan)], timeout_s=90.0)[0]
    lean_t += time.time() - t
    rewards.append(1.0 if (res.ok and res.sorries == 0) else 0.3)

pool.close()
n = len(rows)
print(f"generate: {gen_t/n:.1f}s/completion | lean: {lean_t/max(1,sum(1 for x in rewards if x>0)):.1f}s/check")
print(f"rewards: {rewards}")
# The projection that decides whether the real run is affordable.
per_step = 8 * (gen_t / n) + (gen_t / n)  # 8 completions/step, Lean batched alongside
print(f"PROJECTION: ~{per_step:.0f}s/step at 8 completions -> "
      f"200 steps ~= {200*per_step/3600:.1f}h ~= ${200*per_step/3600*3.2:.0f}")
PY
echo "PREFLIGHT_OK"
