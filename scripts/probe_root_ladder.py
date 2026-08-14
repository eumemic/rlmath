#!/usr/bin/env python3
"""Smallest root that can emit a VALID k-way plan — the number that prices Phase 3.

Phase 2 measured stage-1 plan validity for qwen3-30b (70% at k=2, 15% at k=4, 0% at k=8) and
haiku (70/50/40%). Stage-1 validity is the gate on everything: a plan that fails it never
reaches a leaf, and GRPO cannot learn from an all-zero reward column. So the question that
prices Phase 3 is **how small a root still clears stage 1 often enough to train on** — a 4B
root is a single-GPU LoRA job, a 30B MoE is a multi-node one, and the difference is one to two
orders of magnitude of GPU budget.

This probe answers it for **$0 of GPU**. It needs only root inference plus local Lean, because
stage-1 is exactly the check that does not involve the leaf prover:

    root completion -> plan_format.parse -> leancode.plan_check -> Lean

`plan_check` grants every lemma as a hypothesis binder and asks whether the assembly closes the
goal. That is the same code path `run_zeroshot.py` uses, so these numbers are comparable to
Phase 2's — no reimplementation, no second definition of "valid".

Usage:
  uv run python scripts/probe_root_ladder.py --models A,B,C --problems ... --n 20
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--models", required=True, help="comma-separated model ids")
    ap.add_argument("--problems", default="data/families/case_tree/k2.jsonl")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--base-url", default="https://api.pinference.ai/api/v1")
    ap.add_argument("--api-key-env", default="PRIME_KEY")
    ap.add_argument("--team", default="cmsp77l44000710s4dghtmtss")
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", type=Path, default=Path("results/root_ladder.jsonl"))
    a = ap.parse_args(argv)

    sys.path.insert(0, "src")
    from openai import OpenAI

    from rlmath.core import leancode
    from rlmath.core.plan_format import PlanFormatError, parse_plan
    from rlmath.core.types import GoalSpec
    from rlmath.envs.decomp_env import build_prompt
    from rlmath.eval.exemplars import build_exemplar, load_exemplar_problem
    from rlmath.eval.arms import with_exemplar
    from rlmath.lean.repl_pool import ReplPool

    key = os.environ.get(a.api_key_env, "")
    if not key:
        print(f"${a.api_key_env} is empty", file=sys.stderr)
        return 1

    problems = [json.loads(l) for l in open(a.problems)][: a.n]
    # Same exemplar the Phase-2 decomp cells used, so the prompt is the one that was measured.
    ex = load_exemplar_problem("case_tree", k=2, seed=999)
    exemplar = build_exemplar(ex, "decomp")

    client = OpenAI(base_url=a.base_url, api_key=key,
                    default_headers={"X-Prime-Team-ID": a.team})
    pool = ReplPool(n_workers=a.workers)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    out = a.out.open("a")

    print(f"{'model':38} {'valid':>7} {'parsed':>7} {'n_lemmas seen':>26}  {'$':>7}")
    try:
        for model in [m.strip() for m in a.models.split(",") if m.strip()]:
            counts: Counter = Counter()
            lemma_counts: list[int] = []
            spend = 0.0
            for p in problems:
                goal = GoalSpec(id=p["goal"]["id"], prop=p["goal"]["prop"], name="goal")
                # The FROZEN prompt pair the environment and Phase-2 both use
                # (`decomp_env.build_prompt` + rung-1.5 exemplar on the user turn).
                # An ad-hoc prompt here would measure the prompt, not the model —
                # a first pass of this probe did exactly that and read 0/6 parsed
                # on two models purely because it under-specified the wire format.
                msgs = with_exemplar(build_prompt(goal), exemplar)
                try:
                    r = client.chat.completions.create(
                        model=model, messages=msgs, max_tokens=a.max_tokens, temperature=0.7)
                    text = r.choices[0].message.content or ""
                    u = getattr(r, "usage", None)
                    if u:  # rough; the ladder is priced per-model elsewhere, this is a sanity meter
                        spend += (u.prompt_tokens * 0.2 + u.completion_tokens * 0.8) / 1e6
                except Exception as e:                     # a model the provider will not serve
                    counts["api_error"] += 1
                    out.write(json.dumps({"model": model, "id": p["id"],
                                          "status": "api_error", "detail": str(e)[:300]}) + "\n")
                    continue

                try:
                    # Catch ONLY the format error. A bare `except Exception` here swallowed an
                    # AttributeError (this file called a function that does not exist) and
                    # reported it as a MODEL format failure — 0/10 on a model measured at 70%
                    # in Phase 2. The control is what caught it; the narrow except is what
                    # stops it recurring.
                    plan = parse_plan(text)
                except PlanFormatError:
                    counts["format_error"] += 1
                    out.write(json.dumps({"model": model, "id": p["id"],
                                          "status": "format_error"}) + "\n")
                    continue
                lemma_counts.append(len(plan.lemmas))

                code = leancode.plan_check(goal, plan)
                res = pool.check_many([code], timeout_s=90.0)[0]
                ok = bool(res.ok and res.sorries == 0)
                counts["plan_valid" if ok else "plan_invalid"] += 1
                out.write(json.dumps({"model": model, "id": p["id"],
                                      "status": "plan_valid" if ok else "plan_invalid",
                                      "n_lemmas": len(plan.lemmas),
                                      "detail": ("; ".join(map(str, res.messages))[:200]) if not ok else ""}) + "\n")
                out.flush()

            n = sum(counts.values())
            valid = counts["plan_valid"]
            parsed = valid + counts["plan_invalid"]
            seen = sorted(set(lemma_counts)) if lemma_counts else []
            print(f"{model:38} {valid:>3}/{n:<3} {parsed:>3}/{n:<3} {str(seen):>26}  ${spend:>6.3f}"
                  + ("   (api errors: %d)" % counts["api_error"] if counts["api_error"] else ""))
    finally:
        pool.close()
        out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
