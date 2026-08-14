#!/usr/bin/env python3
"""Phase 3 — GRPO on the decomposition root. Train at k=2, evaluate transfer at k=4/8.

THE EXPERIMENT (DIRECTION §5.5 Phase 3, priced by §7.2). Phase 2 localized the bottleneck to
**stage-1 plan validity**: the root proposes a decomposition, and the assembly either closes the
goal granting the lemmas or it does not. That check needs no leaf prover, so a rollout costs one
root generation plus ~1 s of Lean instead of up to 16 leaf attempts. It is also exactly what
collapses with k (untrained 30B: 70% → 15% → 0%), which makes it the right training target.

The claim under test is the RLM one: **train short, test long.** Train only at k=2 and measure
whether validity at k=4 and k=8 — never trained on — moves with it.

REWARD, and why it is graded rather than binary. §7.2 measured Qwen3.5-9B's failures as
13/20 `format_error`, 4/20 `plan_invalid`, 3/20 `plan_valid`. So **65% of this model's failures
are format, not content** — a pure 0/1 validity reward would spend most of training with no
gradient at all, on a model whose actual deficit is that it will not stop talking. Hence:

    0.0   unparseable
    0.3   parses as a plan (the wire format, which §7.2 showed is nearly free for small models
          and is the one thing 9B does worse than a 2B)
    1.0   plan passes stage 1 in Lean

The 0.3 tier cannot be farmed into the 1.0 tier: emitting a well-formed but wrong plan tops out
at 0.3 forever. It buys the model out of the format hole so the content signal is reachable.

NOT REWARDED, deliberately: lemma count, prop length, anything resembling the oracle
decomposition. The policy must invent its own split; rewarding proximity to the generator's
would train imitation of a decomposition the evaluation never uses.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, "src")


def build_dataset(path: Path, exemplar: str, limit: int | None = None):
    from datasets import Dataset

    from rlmath.core.types import GoalSpec
    from rlmath.envs.decomp_env import build_prompt
    from rlmath.eval.arms import with_exemplar

    rows = []
    for line in path.open():
        r = json.loads(line)
        if not r.get("validation", {}).get("ok"):
            continue
        goal = GoalSpec(id=r["goal"]["id"], prop=r["goal"]["prop"], name="goal")
        rows.append({"prompt": with_exemplar(build_prompt(goal), exemplar),
                     "goal_prop": goal.prop, "goal_id": goal.id})
        if limit and len(rows) >= limit:
            break
    return Dataset.from_list(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", default="Qwen/Qwen3.5-9B")
    ap.add_argument("--train", type=Path, default=Path("data/phase3/train/case_tree/k2.jsonl"))
    ap.add_argument("--eval-dir", type=Path, default=Path("data/phase3/eval/case_tree"))
    ap.add_argument("--out", type=Path, default=Path("runs/grpo9b"))
    ap.add_argument("--steps", type=int, default=200)
    # TRL SEMANTICS, spelled out because they are not what the names suggest:
    #   num_generations              = group size G (rollouts per prompt)
    #   per_device_train_batch_size  = COMPLETIONS per device step, and trl asserts it is
    #                                  divisible by G — it is NOT a prompt count
    #   prompts per optimizer step   = per_device_train_batch_size * grad_accum / G
    # Getting this wrong cost a smoke run: --batch-prompts 2 with --group-size 4 tripped
    # "generation_batch_size (2) must be divisible by num_generations (4)".
    ap.add_argument("--group-size", type=int, default=8, help="G: rollouts per prompt")
    ap.add_argument("--completions-per-step", type=int, default=8,
                    help="per-device completions; must be a multiple of --group-size")
    ap.add_argument("--grad-accum", type=int, default=4,
                    help="prompts per optimizer step = completions-per-step*grad-accum/G")
    ap.add_argument("--lr", type=float, default=1e-5)
    # 384 not 640: a k=2 plan is ~150 tokens (two #lemma lines, a short assembly, #end). The
    # preflight measured 88s/completion because generation ran the FULL budget every time --
    # the base model rambles and never emits #end, so nothing stopped it early. Halving the
    # cap halves the worst case, and `stop_strings` below ends the ones that do finish.
    ap.add_argument("--max-completion-tokens", type=int, default=384)
    ap.add_argument("--eval-max-tokens", type=int, default=640,
                    help="eval needs more room: a k=8 plan is 8 lemma lines, ~250+ tokens")
    ap.add_argument("--lean-workers", type=int, default=12)
    ap.add_argument("--eval-every", type=int, default=25)
    ap.add_argument("--eval-n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)

    import torch
    from peft import LoraConfig
    from trl import GRPOConfig, GRPOTrainer

    from rlmath.core import leancode
    from rlmath.core.plan_format import PlanFormatError, parse_plan
    from rlmath.core.types import GoalSpec
    from rlmath.eval.exemplars import build_exemplar, load_exemplar_problem
    from rlmath.lean.repl_pool import ReplPool

    if a.completions_per_step % a.group_size:
        raise SystemExit(f"--completions-per-step ({a.completions_per_step}) must be a multiple "
                         f"of --group-size ({a.group_size}); trl enforces this and the error it "
                         f"raises names generation_batch_size, which is neither flag.")
    print(f"config: G={a.group_size}, {a.completions_per_step} completions/device-step, "
          f"grad_accum={a.grad_accum} -> "
          f"{a.completions_per_step * a.grad_accum // a.group_size} prompts per optimizer step",
          flush=True)

    random.seed(a.seed)
    torch.manual_seed(a.seed)
    a.out.mkdir(parents=True, exist_ok=True)

    exemplar = build_exemplar(load_exemplar_problem("case_tree", k=2, seed=999), "decomp")
    train_ds = build_dataset(a.train, exemplar)
    print(f"train: {len(train_ds)} k=2 problems", flush=True)

    pool = ReplPool(n_workers=a.lean_workers)
    stats = {"calls": 0, "parse_fail": 0, "invalid": 0, "valid": 0}

    def stage1_reward(completions, goal_prop, **kwargs):
        """Graded reward. Batched into ONE Lean pool call per group — a per-completion
        call would serialize the slowest part of the step."""
        texts = [c if isinstance(c, str) else c[-1]["content"] for c in completions]
        out: list[float] = [0.0] * len(texts)
        codes, idx = [], []
        for i, (t, gp) in enumerate(zip(texts, goal_prop)):
            try:
                plan = parse_plan(t)
            except PlanFormatError:
                stats["parse_fail"] += 1
                continue
            out[i] = 0.3                       # parses; upgraded to 1.0 only if Lean agrees
            goal = GoalSpec(id="train", prop=gp, name="goal")
            codes.append(leancode.plan_check(goal, plan))
            idx.append(i)
        if codes:
            for i, res in zip(idx, pool.check_many(codes, timeout_s=90.0)):
                if res.ok and res.sorries == 0:
                    out[i] = 1.0
                    stats["valid"] += 1
                else:
                    stats["invalid"] += 1
        stats["calls"] += len(texts)
        return out

    def evaluate(model, tokenizer, tag: str):
        """Stage-1 validity on held-out k=2 and on the never-trained k=4 / k=8.
        This is the transfer measurement; everything else is bookkeeping."""
        from transformers import GenerationConfig
        res = {}
        for k in (2, 4, 8):
            f = a.eval_dir / f"k{k}.jsonl"
            if not f.exists():
                continue
            ds = build_dataset(f, exemplar, limit=a.eval_n)
            valid = parsed = 0
            for row in ds:
                text = tokenizer.apply_chat_template(row["prompt"], tokenize=False,
                                                     add_generation_prompt=True)
                ids = tokenizer(text, return_tensors="pt").to(model.device)
                with torch.no_grad():
                    o = model.generate(**ids, generation_config=GenerationConfig(
                        max_new_tokens=a.eval_max_tokens, do_sample=True, stop_strings=["#end"],
                        temperature=0.7, top_p=0.95, tokenizer=tokenizer,
                        pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id))
                comp = tokenizer.decode(o[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
                try:
                    plan = parse_plan(comp)
                except PlanFormatError:
                    continue
                parsed += 1
                goal = GoalSpec(id=row["goal_id"], prop=row["goal_prop"], name="goal")
                r = pool.check_many([leancode.plan_check(goal, plan)], timeout_s=90.0)[0]
                valid += bool(r.ok and r.sorries == 0)
            res[k] = {"valid": valid, "parsed": parsed, "n": len(ds),
                      "rate": valid / len(ds) if len(ds) else 0.0}
            print(f"  [{tag}] k={k}: valid {valid}/{len(ds)} ({res[k]['rate']:.0%}), "
                  f"parsed {parsed}/{len(ds)}", flush=True)
        (a.out / "eval.jsonl").open("a").write(json.dumps({"tag": tag, "res": res}) + "\n")
        return res

    cfg = GRPOConfig(
        output_dir=str(a.out), learning_rate=a.lr, max_steps=a.steps,
        per_device_train_batch_size=a.completions_per_step,
        gradient_accumulation_steps=a.grad_accum, num_generations=a.group_size,
        max_completion_length=a.max_completion_tokens,
        # NOTE: trl 1.10's GRPOConfig has NO `max_prompt_length` (checked on the pod:
        # the length-ish params are max_completion_length / vllm_max_model_length /
        # generation_batch_size). Prompts here are ~1k tokens — system 2.2k chars plus the
        # rung-1.5 exemplar — comfortably inside the model's window, so there is nothing to
        # cap. Passing the old kwarg was a TypeError caught by the setup's API gate.
        logging_steps=1, save_steps=a.eval_every, report_to=[], bf16=True,
        gradient_checkpointing=True, temperature=0.7, seed=a.seed,
        # Stop as soon as the plan is closed. The parser needs `#end` and tolerates anything
        # after it, so continuing past it buys nothing and costs the rest of the token budget.
        generation_kwargs={"stop_strings": ["#end"]},
    )
    peft_cfg = LoraConfig(r=32, lora_alpha=64, lora_dropout=0.05, bias="none",
                          task_type="CAUSAL_LM",
                          target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                          "gate_proj", "up_proj", "down_proj"])

    trainer = GRPOTrainer(model=a.model, reward_funcs=stage1_reward, args=cfg,
                          train_dataset=train_ds, peft_config=peft_cfg)

    print("== BASELINE (untrained) — the line every later number is read against", flush=True)
    evaluate(trainer.model, trainer.processing_class, "baseline")

    class EvalCB(__import__("transformers").TrainerCallback):
        def on_save(self, args_, state, control, **kw):
            evaluate(trainer.model, trainer.processing_class, f"step{state.global_step}")
            print(f"  reward stats so far: {stats}", flush=True)

    trainer.add_callback(EvalCB())
    trainer.train()

    print("== FINAL", flush=True)
    evaluate(trainer.model, trainer.processing_class, "final")
    trainer.save_model(str(a.out / "final"))
    pool.close()
    print("TRAIN_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
