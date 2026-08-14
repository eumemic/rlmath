#!/usr/bin/env python3
"""Which assistant-turn prefill makes Qwen3.5-9B emit a PARSEABLE plan at a small budget?

The token-budget probe found the model needs ~831 tokens to reach `#end` unprompted, but only
~180 when the assistant turn is prefilled with `#lemma ` — and yet parsed 0/8 either way. The
completion showed why:

    #lemma 1 : ∀ x : ℝ, -7 ≤ x → x ≤ 0 → min (...) ≤ 3
    #lemma 2 : ...
    #assembly
    intro x h1 h2
    rcases le_or_gt x 0 with (h3 | h3)
    ...
    #end
    -> PlanFormatError: invalid lemma name: '1'

That is a structurally complete decomposition — correct case split, real assembly, properly
closed — rejected for naming its lemmas `1` and `2`, which are not Lean identifiers. And the
bare `#lemma ` prefill CAUSED it: after that token the natural continuation is a number.

So the question is whether a prefill that also shows a valid *name* fixes it. A prefix is
content-free (it reveals no goal-specific reasoning), identical at every k, and therefore cannot
bias the transfer measurement — the same standing as the rung-1.5 exemplar. It does change the
decoding setup relative to §7.2's ladder, so the run's own baseline becomes the only valid
reference point.

Usage:  python scripts/probe_prefill.py [--budget 384] [--n 8]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

PREFILLS = ["", "#lemma ", "#lemma h1 : ", "#lemma hb1 : "]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", default="Qwen/Qwen3.5-9B")
    ap.add_argument("--problems", type=Path,
                    default=Path("data/phase3/eval/case_tree/k2.jsonl"))
    ap.add_argument("--budget", type=int, default=384)
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
    tok.padding_side = "left"          # decoder-only: right padding corrupts generation
    model = AutoModelForCausalLM.from_pretrained(a.model, dtype=torch.bfloat16,
                                                 device_map="cuda", trust_remote_code=True)
    ex = build_exemplar(load_exemplar_problem("case_tree", k=2, seed=999), "decomp")
    rows = [json.loads(l) for l in a.problems.open()][: a.n]

    def run(prefill: str) -> tuple[int, float, str]:
        texts = []
        for r in rows:
            g = GoalSpec(id=r["goal"]["id"], prop=r["goal"]["prop"], name="goal")
            texts.append(tok.apply_chat_template(with_exemplar(build_prompt(g), ex),
                                                 tokenize=False, add_generation_prompt=True)
                         + prefill)
        enc = tok(texts, return_tensors="pt", padding=True).to(model.device)
        t0 = time.time()
        with torch.no_grad():
            o = model.generate(**enc, max_new_tokens=a.budget, do_sample=True,
                               temperature=0.7, top_p=0.95, pad_token_id=tok.pad_token_id)
        ok, why = 0, ""
        plen = enc["input_ids"].shape[1]
        for i in range(len(texts)):
            comp = prefill + tok.decode(o[i][plen:], skip_special_tokens=True)
            try:
                parse_plan(comp)
                ok += 1
            except PlanFormatError as e:
                if not why:
                    why = str(e)[:70]
        return ok, time.time() - t0, why

    print(f"n={len(rows)}  budget={a.budget}  {a.model}\n", flush=True)
    print(f"{'prefill':>16} {'parsed':>8} {'time':>7}   first failure reason", flush=True)
    for pf in PREFILLS:
        ok, dt, why = run(pf)
        print(f"{pf!r:>16} {ok}/{len(rows):<6} {dt:>6.0f}s   {why}", flush=True)
    print("\nA prefix that reveals a valid NAME (not just the keyword) should fix the "
          "'invalid lemma name' rejection without supplying any goal-specific content.",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
