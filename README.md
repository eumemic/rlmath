# rlmath

RLM-style decomposition harness for Lean 4 theorem proving. A root policy
decomposes a goal into lemma statements; a frozen leaf prover closes them; the
harness holds all proof text (the root never sees a proof) and the Lean kernel
verifies plan and leaves separately.

**Read [`DIRECTION.md`](DIRECTION.md) first** — direction assessment, the
transfer-slope research question, registered priors, and the phased design this
repo implements. Phase status and gate measurements live in
[`PHASE0_NOTES.md`](PHASE0_NOTES.md).

Sibling project [`../rl/`](../rl/) is the completed reproduction of the source
blog's inference-side findings; eval/analysis patterns here are lifted from it.

## Quickstart

```bash
uv sync                                  # python deps
nohup bash scripts/setup_lean.sh > logs/setup_lean.log 2>&1 &   # elan + Mathlib + REPL (long)
uv run pytest                            # offline unit suite
uv run pytest -m integration             # needs the Lean setup above completed
```

## Layout

| path | what |
|---|---|
| `src/rlmath/core/` | frozen contracts: types, `LeanBackend` protocol, Lean codegen, plan wire-format |
| `src/rlmath/lean/` | backends: local REPL worker pool, Kimina server client |
| `src/rlmath/sanitize.py` | source scan + axiom audit (`sorry`/`native_decide`/axiom smuggling) |
| `src/rlmath/leaf/` | frozen leaf-prover adapter, prompt templates, sqlite attempt cache |
| `src/rlmath/harness/` | episode runner: parse → sanitize → elaborate → plan-check → leaf → compose → audit |
| `src/rlmath/envs/` | `verifiers`-format environment (Environments Hub artifact) |
| `scripts/` | Lean setup, leaf-bank builder, throughput benchmark |
| `lean/` | lake project (Mathlib dep) + REPL checkout (gitignored builds) |
| `research/` | dated research notes backing DIRECTION.md claims |
