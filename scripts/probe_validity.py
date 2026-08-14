#!/usr/bin/env python3
"""Which (budget, prefill) maximises VALIDITY — the only tier that still varies?

Everything so far optimised the wrong quantity. The prefill probe measured *parse* rate and
found `#lemma hb1 : ` at 384 tokens best (62.5% vs 37.5%). The Phase-3 baseline then measured
what actually matters:

    k=2  valid 1/40 (2.5%)   parsed 33/40 (82.5%)     384 tokens + prefill
    (§7.2 ladder: valid 3/20 = 15%                    2048 tokens, no prefill)

So prefill traded reasoning for format. The ~680 tokens of "preamble" I dismissed as
throat-clearing was doing work: forced to commit to a first lemma immediately, the model emits
well-formed **wrong** plans. Parse went up 2.4x and validity fell 6x.

That is decisive for training, because prefill also saturated the 0.3 format tier — so validity
is the ONLY varying reward tier, and it sets the fraction of GRPO groups carrying a gradient:

    validity  2.5%  ->  18% of groups
    validity  8%    ->  49%
    validity 15%    ->  73%

This probe measures validity (Lean stage-1, not just parsing) across the grid, so the training
config is chosen on the quantity the gradient depends on rather than on a proxy.

Usage:  python scripts/probe_validity.py [--n 16]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

# (budget, prefill) — the ladder's 2048/no-prefill point is the validity champion so far.
CONFIGS = [(384, "#lemma hb1 : "), (1024, "#lemma hb1 : "), (1024, ""), (2048, "")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", default="Qwen/Qwen3.5-9B")
    ap.add_argument("--problems", type=Path,
                    default=Path("data/phase3/eval/case_tree/k2.jsonl"))
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--batch", type=int, default=8)
    a = ap.parse_args(argv)

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from rlmath.core import leancode
    from rlmath.core.plan_format import PlanFormatError, parse_plan
    from rlmath.core.types import GoalSpec
    from rlmath.envs.decomp_env import build_prompt
    from rlmath.eval.arms import with_exemplar
    from rlmath.eval.exemplars import build_exemplar, load_exemplar_problem
    from rlmath.lean.repl_pool import ReplPool

    tok = AutoTokenizer.from_pretrained(a.model, trust_remote_code=True)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"
    model = AutoModelForCausalLM.from_pretrained(a.model, dtype=torch.bfloat16,
                                                 device_map="cuda", trust_remote_code=True)
    ex = build_exemplar(load_exemplar_problem("case_tree", k=2, seed=999), "decomp")
    rows = [json.loads(l) for l in a.problems.open()][: a.n]
    pool = ReplPool(n_workers=8)

    def run(budget: int, prefill: str) -> tuple[int, int, float]:
        parsed = valid = 0
        t0 = time.time()
        for i in range(0, len(rows), a.batch):
            chunk = rows[i : i + a.batch]
            texts = []
            for r in chunk:
                g = GoalSpec(id=r["goal"]["id"], prop=r["goal"]["prop"], name="goal")
                texts.append(tok.apply_chat_template(with_exemplar(build_prompt(g), ex),
                                                     tokenize=False,
                                                     add_generation_prompt=True) + prefill)
            enc = tok(texts, return_tensors="pt", padding=True).to(model.device)
            with torch.no_grad():
                o = model.generate(**enc, max_new_tokens=budget, do_sample=True,
                                   temperature=0.7, top_p=0.95, pad_token_id=tok.pad_token_id)
            plen = enc["input_ids"].shape[1]
            codes = []
            for j, r in enumerate(chunk):
                comp = prefill + tok.decode(o[j][plen:], skip_special_tokens=True)
                try:
                    plan = parse_plan(comp)
                except PlanFormatError:
                    continue
                parsed += 1
                g = GoalSpec(id=r["goal"]["id"], prop=r["goal"]["prop"], name="goal")
                codes.append(leancode.plan_check(g, plan))
            if codes:
                for res in pool.check_many(codes, timeout_s=90.0):
                    valid += bool(res.ok and res.sorries == 0)
        return parsed, valid, time.time() - t0

    print(f"n={len(rows)} k=2 problems, {a.model}\n", flush=True)
    print(f"{'budget':>7} {'prefill':>16} {'parsed':>9} {'VALID':>9} {'grad groups':>12} {'time':>7}",
          flush=True)
    try:
        for budget, pf in CONFIGS:
            p, v, dt = run(budget, pf)
            rate = v / len(rows)
            gg = 1 - (1 - rate) ** 8 - rate ** 8      # G=8 groups with reward variance
            print(f"{budget:>7} {pf!r:>16} {p}/{len(rows):<7} {v}/{len(rows):<7} "
                  f"{gg:>11.0%} {dt:>6.0f}s", flush=True)
    finally:
        pool.close()
    print("\nPick on VALID, not parsed: validity is the only tier that still varies, so it alone"
          "\nsets how many GRPO groups produce a gradient.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
