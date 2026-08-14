#!/usr/bin/env python3
"""How many tokens does Qwen3.5-9B need to reach `#end`? Diagnose before re-spending.

The §7.2 ladder measured 7/20 = 35% parse for this model at `max_tokens=2048` (via Prime
Inference). The Phase-3 baseline eval measured **0/40** at 448. At a true 35% rate, 0/40 has
probability 0.65^40 ≈ 1e-7, so the difference is systematic, not luck — and the obvious
suspect is the token budget I cut to save money.

This matters far beyond the eval number: training used a **384**-token cap. If the model cannot
close a plan inside 384 tokens, every rollout scores 0.0, GRPO sees no variance, and the run
learns nothing while costing $25. Measure it before spending again.

Also probes the cheap fix: **prefill**. Seeding the assistant turn with `#lemma ` forces the
model to start in the wire format instead of writing a preamble, which is exactly the failure
mode (§7.2: 9B fails verbosely — 13/20 format_error while a 2B parses 18/20).

Usage:  python scripts/probe_token_budget.py [--budgets 384,640,1024,2048] [--n 8]
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
    ap.add_argument("--problems", type=Path,
                    default=Path("data/phase3/eval/case_tree/k2.jsonl"))
    ap.add_argument("--budgets", default="384,640,1024,2048")
    ap.add_argument("--n", type=int, default=8)
    a = ap.parse_args(argv)

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from rlmath.core.plan_format import PlanFormatError, parse_plan
    from rlmath.core.types import GoalSpec
    from rlmath.envs.decomp_env import build_prompt
    from rlmath.eval.arms import with_exemplar
    from rlmath.eval.exemplars import build_exemplar, load_exemplar_problem

    tok = AutoTokenizer.from_pretrained(a.model, trust_remote_code=True)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(a.model, torch_dtype=torch.bfloat16,
                                                 device_map="cuda", trust_remote_code=True)
    ex = build_exemplar(load_exemplar_problem("case_tree", k=2, seed=999), "decomp")
    rows = [json.loads(l) for l in a.problems.open()][: a.n]

    def run(budget: int, prefill: str = "") -> tuple[int, float, int]:
        """(parsed, mean completion tokens, mean tokens-to-#end where present)"""
        parsed, toks, to_end = 0, [], []
        for r in rows:
            g = GoalSpec(id=r["goal"]["id"], prop=r["goal"]["prop"], name="goal")
            text = tok.apply_chat_template(with_exemplar(build_prompt(g), ex),
                                           tokenize=False, add_generation_prompt=True)
            text += prefill
            ids = tok(text, return_tensors="pt").to(model.device)
            with torch.no_grad():
                o = model.generate(**ids, max_new_tokens=budget, do_sample=True,
                                   temperature=0.7, top_p=0.95,
                                   pad_token_id=tok.pad_token_id or tok.eos_token_id)
            new = o[0][ids["input_ids"].shape[1]:]
            comp = prefill + tok.decode(new, skip_special_tokens=True)
            toks.append(len(new))
            if "#end" in comp:
                to_end.append(len(tok(comp[: comp.index("#end") + 4]).input_ids))
            try:
                parse_plan(comp); parsed += 1
            except PlanFormatError:
                pass
        return parsed, sum(toks) / len(toks), (sum(to_end) // len(to_end)) if to_end else -1

    print(f"n={len(rows)} k=2 problems, {a.model}\n")
    print(f"{'budget':>8} {'prefill':>9} {'parsed':>8} {'mean gen tok':>13} {'tok to #end':>12}")
    for b in [int(x) for x in a.budgets.split(",")]:
        t0 = time.time()
        p, mt, te = run(b)
        print(f"{b:>8} {'no':>9} {p}/{len(rows):<6} {mt:>13.0f} {te if te>0 else '(never)':>12}"
              f"   [{time.time()-t0:.0f}s]")
    # The cheap fix: force the format from the first token.
    for b in (384, 640):
        t0 = time.time()
        p, mt, te = run(b, prefill="#lemma ")
        print(f"{b:>8} {'#lemma ':>9} {p}/{len(rows):<6} {mt:>13.0f} {te if te>0 else '(never)':>12}"
              f"   [{time.time()-t0:.0f}s]")
    print("\nRead: if parsing needs >=1024 tokens WITHOUT prefill but works at 384 WITH it,"
          "\nprefill is the fix — it costs nothing and removes the preamble that eats the budget.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
