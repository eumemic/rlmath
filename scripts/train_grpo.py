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

# ASSISTANT-TURN PREFILL — measured, not guessed (scripts/probe_prefill.py, 2026-08-14):
#     prefill            parsed@384tok   time/8
#     (none)              0/8            163 s   "no plan markers found"
#     "#lemma "           0/8             15 s   "invalid lemma name: '1'"
#     "#lemma h1 : "      4/8             15 s
#     "#lemma hb1 : "     5/8 (62.5%)     13 s   <- this one
# Unprompted, the model spends ~680 tokens on preamble and needs 1024 to reach #end (37.5%
# parse, 180 s per 8). Started in-format it produces a complete, correctly-shaped plan in ~180
# tokens. A bare "#lemma " made it worse by inviting a NUMERIC name, which is not a Lean
# identifier — the prefix must show a valid name.
#
# This is content-free: it reveals no goal-specific reasoning, and it is identical at every k,
# so it cannot bias the k=2 -> k=4/8 transfer comparison. Same standing as the rung-1.5
# exemplar. It DOES change the decoding setup relative to §7.2's ladder, so that 35%-at-2048
# figure is no longer the reference — the run's own baseline eval is.
PREFILL = "#lemma hb1 : "


def build_dataset(path: Path, exemplar: str, tok, limit: int | None = None):
    """Prompts as PRE-TEMPLATED STRINGS ending in PREFILL.

    TRL treats a string `prompt` column as "standard" format and tokenizes it verbatim, so
    applying the chat template here is what lets the assistant turn be prefilled. Passing the
    conversational (list-of-messages) form instead would have TRL apply the template itself and
    there would be nowhere to put the prefix.
    """
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
        text = tok.apply_chat_template(with_exemplar(build_prompt(goal), exemplar),
                                       tokenize=False, add_generation_prompt=True) + PREFILL
        rows.append({"prompt": text, "goal_prop": goal.prop, "goal_id": goal.id})
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
    ap.add_argument("--eval-n", type=int, default=40)
    ap.add_argument("--eval-batch", type=int, default=8)
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
    from transformers import AutoTokenizer as _AT
    _tok = _AT.from_pretrained(a.model, trust_remote_code=True)
    if _tok.pad_token_id is None:
        _tok.pad_token = _tok.eos_token
    train_ds = build_dataset(a.train, exemplar, _tok)
    print(f"train: {len(train_ds)} k=2 problems", flush=True)

    pool = ReplPool(n_workers=a.lean_workers)
    stats = {"calls": 0, "parse_fail": 0, "invalid": 0, "valid": 0}

    def stage1_reward(completions, goal_prop, **kwargs):
        """Graded reward. Batched into ONE Lean pool call per group — a per-completion
        call would serialize the slowest part of the step."""
        # The prefill is part of the plan but NOT part of the completion TRL returns, so it
        # must be re-attached before parsing or every plan loses its first lemma name.
        texts = [PREFILL + (c if isinstance(c, str) else c[-1]["content"]) for c in completions]
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

        BATCHED. One sequence at a time measured ~2.2 min/completion, which made this eval a
        13-hour job against a ~2-hour training run — it is what made the first attempt look
        hung. Decode is memory-bandwidth-bound, so a batch of 8 costs barely more than a batch
        of 1 (measured: 13 s for 8 at 384 tokens). Left padding is mandatory for a decoder-only
        model; right padding puts pad tokens between the prompt and the first generated token.
        """
        from transformers import GenerationConfig
        tokenizer.padding_side = "left"
        res = {}
        for k in (2, 4, 8):
            f = a.eval_dir / f"k{k}.jsonl"
            if not f.exists():
                continue
            ds = build_dataset(f, exemplar, tokenizer, limit=a.eval_n)
            texts = list(ds["prompt"])          # already templated + prefilled
            valid = parsed = 0
            for i in range(0, len(texts), a.eval_batch):
                chunk = texts[i : i + a.eval_batch]
                enc = tokenizer(chunk, return_tensors="pt", padding=True).to(model.device)
                with torch.no_grad():
                    o = model.generate(**enc, generation_config=GenerationConfig(
                        max_new_tokens=a.eval_max_tokens, do_sample=True,
                        temperature=0.7, top_p=0.95,
                        pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id))
                plen = enc["input_ids"].shape[1]
                codes, rows_ = [], []
                for j in range(len(chunk)):
                    comp = PREFILL + tokenizer.decode(o[j][plen:], skip_special_tokens=True)
                    try:
                        plan = parse_plan(comp)
                    except PlanFormatError:
                        continue
                    parsed += 1
                    g = GoalSpec(id=ds[i + j]["goal_id"], prop=ds[i + j]["goal_prop"],
                                 name="goal")
                    codes.append(leancode.plan_check(g, plan)); rows_.append(j)
                if codes:                        # one Lean call per batch, not per completion
                    for r in pool.check_many(codes, timeout_s=90.0):
                        valid += bool(r.ok and r.sorries == 0)
            res[k] = {"valid": valid, "parsed": parsed, "n": len(texts),
                      "rate": valid / len(texts) if texts else 0.0}
            print(f"  [{tag}] k={k}: valid {valid}/{len(texts)} ({res[k]['rate']:.0%}), "
                  f"parsed {parsed}/{len(texts)}", flush=True)
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
        # NO stop_strings here, deliberately. transformers requires the tokenizer be passed
        # to `generate` alongside stop strings, and TRL's internal generate call does not
        # forward it — failure #8 was:
        #   ValueError: There are one or more stop strings ... we could not locate a tokenizer
        # The 384-token cap is where the saving actually came from (a k=2 plan is ~150 tokens),
        # and once the format reward teaches the model to close and emit EOS, generation stops
        # on its own. The eval path DOES use stop_strings, because there we call generate
        # ourselves and can pass tokenizer=.
    )
    peft_cfg = LoraConfig(r=32, lora_alpha=64, lora_dropout=0.05, bias="none",
                          task_type="CAUSAL_LM",
                          target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                          "gate_proj", "up_proj", "down_proj"])

    # Qwen3.5 is a VISION-language model, so TRL's default `AutoProcessor.from_pretrained`
    # builds Qwen3VL's image AND video processors — which is how setup failure #7 happened:
    #   [ERROR] `min_frames` is part of Qwen3VLVideoProcessorInitKwargs, but not documented
    # a transformers docstring-validation error raised while constructing a VIDEO processor for
    # a text-only task. The plain tokenizer loads cleanly (proved in the setup gate), so pass it
    # explicitly and the processor path is never entered.
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.model, trust_remote_code=True)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    trainer = GRPOTrainer(model=a.model, reward_funcs=stage1_reward, args=cfg,
                          train_dataset=train_ds, peft_config=peft_cfg,
                          processing_class=tok)

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
