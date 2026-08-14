#!/usr/bin/env python3
"""The gate that was missing: CONSTRUCT GRPOTrainer against the real model and take one step.

Seven setup failures were found one per pod-launch. The earlier gate checked `GRPOConfig`'s
argument *names*, which is not the same as exercising the trainer's construction path — and
that path is precisely where failure #7 lived: TRL calls `AutoProcessor.from_pretrained`, which
for the VL Qwen3.5 builds Qwen3VL image and video processors, and transformers raised a
docstring-validation error about `min_frames` while doing it. A names-only check sails past that.

So this builds the real trainer, with the real model, and runs one real optimizer step at a
tiny size. If the plumbing is broken, it breaks here in a couple of minutes rather than after a
model download plus a baseline eval.

It also prints a measured seconds-per-step at a known shape, which is the input to the
cost projection — my extrapolated projections have run 27–86% low all week, and one of them
(793 s/step) was wrong in the other direction because it assumed sequential generation where
TRL batches the group.

Usage:  python scripts/preflight_trainer.py [--model ...] [--completions 4] [--tokens 128]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", default="Qwen/Qwen3.5-9B")
    ap.add_argument("--train", type=Path,
                    default=Path("data/phase3/train/case_tree/k2.jsonl"))
    ap.add_argument("--completions", type=int, default=4)
    ap.add_argument("--group-size", type=int, default=4)
    ap.add_argument("--tokens", type=int, default=128)
    ap.add_argument("--steps", type=int, default=1)
    a = ap.parse_args(argv)

    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoTokenizer
    from trl import GRPOConfig, GRPOTrainer

    from rlmath.core.types import GoalSpec
    from rlmath.envs.decomp_env import build_prompt
    from rlmath.eval.arms import with_exemplar
    from rlmath.eval.exemplars import build_exemplar, load_exemplar_problem

    ex = build_exemplar(load_exemplar_problem("case_tree", k=2, seed=999), "decomp")
    rows = []
    for line in list(a.train.open())[: a.completions * 2]:
        r = json.loads(line)
        g = GoalSpec(id=r["goal"]["id"], prop=r["goal"]["prop"], name="goal")
        rows.append({"prompt": with_exemplar(build_prompt(g), ex), "goal_prop": g.prop})
    ds = Dataset.from_list(rows)
    print(f"dataset: {len(ds)} prompts", flush=True)

    tok = AutoTokenizer.from_pretrained(a.model, trust_remote_code=True)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    print("tokenizer OK (NOT AutoProcessor — that is the VL trap)", flush=True)

    seen = {"n": 0}

    def rf(completions, goal_prop, **kw):
        # Plumbing only; the real graded reward is exercised by pod_phase3_preflight.sh.
        # What matters here is that TRL calls it with the shape the real one expects.
        seen["n"] += len(completions)
        texts = [c if isinstance(c, str) else c[-1]["content"] for c in completions]
        assert len(texts) == len(goal_prop), "reward kwargs misaligned with completions"
        return [0.0] * len(texts)

    cfg = GRPOConfig(
        output_dir="/tmp/pf_step", learning_rate=1e-5, max_steps=a.steps,
        per_device_train_batch_size=a.completions, num_generations=a.group_size,
        gradient_accumulation_steps=1, max_completion_length=a.tokens,
        logging_steps=1, report_to=[], bf16=True, gradient_checkpointing=True,
        temperature=0.7, generation_kwargs={"stop_strings": ["#end"]},
    )
    t0 = time.time()
    trainer = GRPOTrainer(
        model=a.model, reward_funcs=rf, args=cfg, train_dataset=ds,
        peft_config=LoraConfig(r=8, lora_alpha=16, task_type="CAUSAL_LM",
                               target_modules=["q_proj", "v_proj"]),
        processing_class=tok)
    print(f"GRPOTrainer constructed in {time.time()-t0:.0f}s", flush=True)

    t0 = time.time()
    trainer.train()
    dt = time.time() - t0
    print(f"STEP OK: {a.steps} step(s), {a.completions} completions x {a.tokens} tok "
          f"in {dt:.0f}s ({dt/max(1,a.steps):.0f}s/step); reward fn saw {seen['n']} completions",
          flush=True)

    # Project the real run from MEASURED time, scaling by completions and token budget.
    real_completions, real_tokens, real_steps = 8, 384, 200
    scale = (real_completions / a.completions) * (real_tokens / a.tokens)
    est = dt / max(1, a.steps) * scale
    print(f"PROJECTION: ~{est:.0f}s/step at {real_completions}x{real_tokens} -> "
          f"{real_steps} steps ~= {real_steps*est/3600:.1f}h ~= ${real_steps*est/3600*3.2:.0f}",
          flush=True)
    print("  (upper bound: decode is memory-bound, so 8 completions cost well under 2x of 4)",
          flush=True)
    print("PREFLIGHT_TRAINER_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
