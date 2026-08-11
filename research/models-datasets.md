# Models & Datasets Research — Formal Theorem Proving (Lean 4)

Research date: 2026-08-11. All identifiers verified live against Hugging Face
model/dataset cards, the arXiv paper HTML (ar5iv), and GitHub repo metadata on
this date.

---

## 1. DeepSeek-Prover-V2-7B

**HF repo id:** `deepseek-ai/DeepSeek-Prover-V2-7B`
(sibling: `deepseek-ai/DeepSeek-Prover-V2-671B`; paper: [arXiv:2504.21801](https://arxiv.org/abs/2504.21801))

- **Base architecture:** built on `DeepSeek-Prover-V1.5-Base` (llama-type arch), BF16 safetensors, 7B params.
- **Context length:** "extended context length of up to 32K tokens" (extended from the 4,096 of DeepSeek-Prover-V1.5-Base-7B).
- **License:** Custom **DEEPSEEK LICENSE AGREEMENT, Version 1.0 (23 Oct 2023)** ("Model License" — `LICENSE-MODEL` in the `deepseek-ai/DeepSeek-V3` repo, which `DeepSeek-Prover-V2-7B/LICENSE-MODEL` points to). It is a permissive, source-available license modeled on RAIL-style licenses: perpetual/worldwide/royalty-free copyright + patent grant, redistribution allowed with attribution + notice of the license passing to downstream users, use-based restrictions in an "Attachment A" (acceptable-use policy), no rights claimed over model *output*. It is **not** MIT and **not** Apache-2.0 — accompanying *code* in the DeepSeek-V3/Prover-V2 GitHub repos is MIT-licensed separately, but the **model weights** are under this DeepSeek Model License.

### Prompt templates

Both modes share an identical skeleton (a `Complete the following Lean 4 code:` instruction wrapping a ```` ```lean4 ```` block with `import Mathlib`, `import Aesop`, `set_option maxHeartbeats 0`, the `open ...` line, a docstring, and the theorem ending in `sorry`). They differ only in whether two extra "give a proof plan first" sentences are appended. This is confirmed directly from **Appendix A of the paper** (arXiv:2504.21801v2, section "Examples of Non-CoT and CoT Prompting for Proof Generation") and matches the Quick Start code published on the HF model card.

#### Non-CoT template (verbatim, from paper Appendix A.1 "Input")

This is the fast, high-throughput mode — no proof-plan/reasoning is requested; the model is expected to emit only completed Lean 4 code.

```
Complete the following Lean 4 code:

```lean4
import Mathlib
import Aesop

set_option maxHeartbeats 0

open BigOperators Real Nat Topology Rat

/-- Prove that $\cos{\frac{\pi}{7}}-\cos{\frac{2\pi}{7}}+\cos{\frac{3\pi}{7}}=\frac{1}{2}$.-/
theorem imo_1963_p5 : Real.cos (Real.pi / 7) - Real.cos (2 * Real.pi / 7) + Real.cos (3 * Real.pi / 7) = 1 / 2 := by
  sorry
```
```

As a reusable Python format string (this exact `prompt = """...""".strip()` non-CoT wrapper is **not** separately published by DeepSeek as a code snippet — only the CoT version below is published verbatim on the HF card / Quick Start script. The string below is the paper's Appendix A.1 text reproduced in the same `.strip()`-template style DeepSeek uses for the CoT variant, i.e. the CoT prompt with its two trailing proof-plan sentences removed):

```python
prompt = """
Complete the following Lean 4 code:

```lean4
{}
```
""".strip()
```

#### CoT template (verbatim — this IS the one published as executable code on the official HF model card's "Quick Start" section, identical text also reused verbatim on Goedel-Prover-V2's model card)

```python
prompt = """
Complete the following Lean 4 code:

```lean4
{}
```

Before producing the Lean 4 code to formally prove the given theorem, provide a detailed proof plan outlining the main proof steps and strategies.
The plan should highlight key ideas, intermediate lemmas, and proof structures that will guide the construction of the final formal proof.
""".strip()
```

`{}` is filled with a `formal_statement` string of exactly this shape (from the official Quick Start script):

```python
formal_statement = """
import Mathlib
import Aesop

set_option maxHeartbeats 0

open BigOperators Real Nat Topology Rat

/-- What is the positive difference between $120\%$ of 30 and $130\%$ of 20? Show that it is 10.-/
theorem mathd_algebra_10 : abs ((120 : ℝ) / 100 * 30 - 130 / 100 * 20) = 10 := by
  sorry
""".strip()
```

Full official invocation (HF Quick Start, `deepseek-ai/DeepSeek-Prover-V2-7B` README §5):

```python
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch
torch.manual_seed(30)

model_id = "DeepSeek-Prover-V2-7B"
tokenizer = AutoTokenizer.from_pretrained(model_id)
chat = [{"role": "user", "content": prompt.format(formal_statement)}]
model = AutoModelForCausalLM.from_pretrained(model_id, device_map="auto", torch_dtype=torch.bfloat16, trust_remote_code=True)
inputs = tokenizer.apply_chat_template(chat, tokenize=True, add_generation_prompt=True, return_tensors="pt").to(model.device)
outputs = model.generate(inputs, max_new_tokens=8192)
```

Note the model card itself only shows the CoT-style prompt (the one that asks for a plan); to run **non-CoT**, drop the two "Before producing..."/"The plan should..." sentences and send just the `Complete the following Lean 4 code: ```lean4 {} ``` ` block as the user message, per Appendix A.1 of the paper. The paper (§3.1, "CoT vs. non-CoT") also notes that even in non-CoT mode the 671B model sometimes emits inline `-- ` comments that look like reasoning, but this is *not* prompted for.

### GGUF conversions for Ollama

Yes — usable, actively-maintained GGUF conversions exist:

| Repo | Maintainer | Notes |
|---|---|---|
| `unsloth/DeepSeek-Prover-V2-7B-GGUF` | Unsloth | "Unsloth Dynamic 2.0" quants; 25 quant files from 1-bit (`UD-IQ1_S`, 1.86 GB) up to `BF16` (13.8 GB). Directly `ollama run`-able. |
| `Mungert/DeepSeek-Prover-V2-7B-GGUF` | Mungert | Also exists (returned HTTP 401 on anonymous fetch at research time — gated/rate-limited, not confirmed broken) |
| `mlx-community/DeepSeek-Prover-V2-7B-4bit` / `-bf16` | mlx-community | **MLX format, not GGUF** — for `mlx-lm`/LM Studio on Apple Silicon, not for Ollama. Listed here only to avoid confusion; do not use for Ollama. |

**Ollama one-liner (works via Ollama's native `hf.co/...:TAG` GGUF pull support):**
```
ollama run hf.co/unsloth/DeepSeek-Prover-V2-7B-GGUF:UD-Q4_K_XL
```

**Full unsloth quant ladder (25 files):**
1-bit: `UD-IQ1_S` 1.86GB, `UD-IQ1_M` 1.96GB
2-bit: `UD-IQ2_XXS` 2.15GB, `Q2_K` 2.72GB, `UD-IQ2_M` 2.6GB, `Q2_K_L` 2.82GB, `UD-Q2_K_XL` 2.9GB
3-bit: `UD-IQ3_XXS` 2.8GB, `Q3_K_S` 3.14GB, `Q3_K_M` 3.46GB, `UD-Q3_K_XL` 3.67GB
4-bit: `IQ4_XS` 3.81GB, `Q4_K_S` 4.03GB, `IQ4_NL` 4.0GB, `Q4_0` 4.01GB, `Q4_1` 4.41GB, `Q4_K_M` 4.22GB, `UD-Q4_K_XL` 4.34GB
5-bit: `Q5_K_S` 4.81GB, `Q5_K_M` 4.93GB, `UD-Q5_K_XL` 4.97GB
6-bit: `Q6_K` 5.67GB, `UD-Q6_K_XL` 6.46GB
8-bit: `Q8_0` 7.35GB, `UD-Q8_K_XL` 8.92GB
16-bit: `BF16` 13.8GB

**Recommendation for a 48GB Mac:** headroom is generous relative to a 7B model, so quantization quality, not RAM, is the binding constraint (proof search benefits from precision). Recommended:
- **Best default:** `unsloth/DeepSeek-Prover-V2-7B-GGUF:UD-Q6_K_XL` (6.46 GB) — near-lossless, huge headroom left on 48GB for a large Ollama context window (this model natively supports 32K context) plus Mathlib/Lean REPL processes running alongside.
- **If you want closest-to-bf16 fidelity for eval/benchmark runs:** `Q8_0` (7.35GB) or `UD-Q8_K_XL` (8.92GB) — still trivially fits in 48GB with room for a full 32K-token context and KV cache.
- **Fastest / most parallel workers:** `UD-Q4_K_XL` (4.34GB) — Unsloth's own default in all their usage snippets; lets you run several concurrent Ollama instances/contexts for parallel proof search within 48GB.
- Avoid 1–2 bit quants for actual theorem-proving use — Lean tactic syntax is precision-sensitive and a 7B model has little redundancy to spare.

---

## 2. Goedel-Prover-V2-8B (Goedel-LM)

**HF repo id:** `Goedel-LM/Goedel-Prover-V2-8B`
(sibling: `Goedel-LM/Goedel-Prover-V2-32B`; companion formalizer: `Goedel-LM/Goedel-Formalizer-V2-8B`; paper: [arXiv:2508.03613](https://arxiv.org/abs/2508.03613); GitHub: `Goedel-LM/Goedel-Prover-V2`)

- **Base model:** `Qwen/Qwen3-8B` (→ `Qwen/Qwen3-8B-Base`), architecture `qwen3`, BF16 safetensors, 8B params.
- **License:** `apache-2.0` (confirmed in HF card YAML frontmatter: `license: apache-2.0`).
- **Benchmark headline:** 83.0% MiniF2F-test @ Pass@32 (standard mode), matching DeepSeek-Prover-V2-671B at ~1/100th the parameter count. Also ships a **self-correction mode** (2 rounds of Lean-compiler-feedback-guided revision; total output grows modestly from 32K → ~40K tokens).
- **Lean/Mathlib env used for training/eval infra:** Lean 4 v4.9 + matching Mathlib4 (per GitHub README §5, following DeepSeek-Prover-V1.5's environment).

### Prompt format (verbatim, from the official HF README "Quick Start" — identical structure/wording to DeepSeek-Prover-V2, i.e. Goedel reuses DeepSeek's CoT-style prompt convention)

```python
formal_statement = """
import Mathlib
import Aesop

set_option maxHeartbeats 0

open BigOperators Real Nat Topology Rat


theorem square_equation_solution {x y : ℝ} (h : x^2 + y^2 = 2*x - 4*y - 5) : x + y = -1 := by
  sorry
""".strip()

prompt = """
Complete the following Lean 4 code:

```lean4
{}```

Before producing the Lean 4 code to formally prove the given theorem, provide a detailed proof plan outlining the main proof steps and strategies.
The plan should highlight key ideas, intermediate lemmas, and proof structures that will guide the construction of the final formal proof.
""".strip()

chat = [{"role": "user", "content": prompt.format(formal_statement)}]
inputs = tokenizer.apply_chat_template(chat, tokenize=True, add_generation_prompt=True, return_tensors="pt").to(model.device)
outputs = model.generate(inputs, max_new_tokens=32768)
```

(Note: the README's `model_id` in this exact snippet is `Goedel-LM/Goedel-Prover-V2-32B`; swap to `Goedel-LM/Goedel-Prover-V2-8B` for the 8B model — the prompt template itself is identical across both sizes.) Card does not document a separate non-CoT prompt for Goedel-Prover-V2 (unlike DeepSeek-Prover-V2, Goedel-Prover-V2's paper/card presents only this single CoT-style template plus the self-correction pipeline).

### GGUF for Ollama
- `mradermacher/Goedel-Prover-V2-8B-GGUF` — static quants, `Q2_K` (3.28GB) through `f16` (16.4GB); card recommends `Q4_K_S`/`Q4_K_M` ("fast, recommended") and calls `Q6_K` "very good quality", `Q8_0` "best quality".
- `NikolayKozloff/Goedel-Prover-V2-8B-Q8_0-GGUF` — single `Q8_0` llama.cpp conversion.
- No Unsloth GGUF found for this specific model as of this research date.
- **Recommendation for 48GB Mac:** `Q8_0` (8.8GB) or the `f16` (16.5GB) full-precision GGUF both fit comfortably; prefer `Q8_0` for near-lossless quality with more headroom for the 32-40K context window plus concurrent Lean REPL/Mathlib processes.

---

## 3. Lean-Workbook dataset

**HF dataset id:** `internlm/Lean-Workbook`
(paper: [arXiv:2406.03847](https://arxiv.org/abs/2406.03847), NeurIPS 2024 D&B track; DOI `10.57967/hf/2399`; code: `github.com/InternLM/InternLM-Math`)

- **License:** apache-2.0. **Language:** English.
- **Files in repo:** `lean_workbook.json` (94.5MB, the full/canonical dataset) and `wkbk_1009.parquet` (4.6MB — a smaller tactic-state-level snapshot; this is what HF's auto-Parquet-conversion "Data Studio" viewer shows by default, with a *different* schema: `id, status, tactic, state_before, state_after, natural_language_statement, answer, formal_statement` over 25,214 rows — **do not confuse this with the full dataset**).

### Canonical schema (verified directly by downloading and parsing `lean_workbook.json`)

Each row is a JSON object with exactly these 6 fields:

```json
{
  "natural_language_statement": "string — the informal math problem",
  "answer": "string — the final answer (may be empty string)",
  "tags": ["string", "..."],
  "formal_statement": "string — Lean 4 theorem statement, body = sorry",
  "split": "\"lean_workbook\" | \"lean_workbook_plus\"",
  "proof": ["string", "..."]  // list of candidate tactic-proof strings found via search; often empty []
}
```

Example row:
```json
{
  "natural_language_statement": "Let $a,b,c$ be positive real numbers .Prove that $ \\frac{b+c}{\\sqrt{a^2 + 8bc}} + \\frac{c+a}{\\sqrt{b^2 + 8ca}} + \\frac{a+b}{\\sqrt{c^2 + 8ab}} \\geq 2. $",
  "answer": "2",
  "tags": ["inequality"],
  "formal_statement": "theorem lean_workbook_0 (a b c : ℝ) (ha : 0 < a) (hb : 0 < b) (hc : 0 < c) : (b + c) / Real.sqrt (a ^ 2 + 8 * b * c) + (c + a) / Real.sqrt (b ^ 2 + 8 * c * a) + (a + b) / Real.sqrt (c ^ 2 + 8 * a * b) ≥ 2  :=  by sorry",
  "split": "lean_workbook",
  "proof": []
}
```

### Row counts (measured directly, `lean_workbook.json`, 2026-08-11)

- **Total: 140,214 rows.**
- `split == "lean_workbook"`: **57,321** rows (dataset card text says "57231" — a minor card/data discrepancy; the live file's actual count is 57,321).
- `split == "lean_workbook_plus"`: **82,893** rows (matches the card exactly).
- Rows with a non-empty `proof` list (i.e., a tactic proof was actually found by search): **12,823** of 140,214 (~9.1%). The rest have `formal_statement` ending in `sorry` with `proof: []`.

### Lean 4 confirmation

**Confirmed Lean 4.** `formal_statement` values use Lean 4 / Mathlib4 syntax throughout (`Real.sqrt`, `ℝ`, `theorem ... := by sorry`, Mathlib4 tactics like `nlinarith`, `norm_num`, `field_simp`, `Nat.mod_mod`, etc. — Lean 3 used `theorem ... :=` without `by` for tactic mode and different Mathlib3 namespacing). The dataset card additionally states explicitly: "contest-level math problems formalized in Lean 4," and that the test/compile environment is "Lean v4.8.0-rc1 with Mathlib4 of the same version" (git tag `v4.8.0-rc1`). Statements as shipped do **not** include the `import Mathlib` / `open ...` header lines (those must be prepended before compiling, as noted in community discussions on the dataset's HF Discussions tab — some rows also implicitly rely on `open`/`variable` declarations not included per-row).

---

## 4. miniF2F in Lean 4 — canonical maintained version

**Canonical / currently-maintained repo:** **`google-deepmind/miniF2F`** (GitHub) — https://github.com/google-deepmind/miniF2F

- Actively maintained: verified commit history shows commits as recent as **2026-04-23** ("Update to Lean 4.27.0") and **2026-04-22** ("Move to a new version of FormalConjectures"), i.e. still receiving updates as of this research date (2026-08-11).
- **Current Lean toolchain pinned:** `leanprover/lean4:v4.27.0` (from the repo's `lean-toolchain` file).
- **License:** Apache-2.0.
- **Provenance:** a fork of `openai/miniF2F`, translated from Lean 3 to Lean 4 via `mathport`, "with corrections to formalizations and informal descriptions" and "many fewer misformalizations, with all known false statements removed" vs. earlier Lean-4 ports. Explicitly the version **AlphaProof was evaluated on** ("This is the version of the benchmark on which AlphaProof is evaluated" — per repo README), though the repo itself carries the disclaimer "this is not an official Google product."
- Standard split sizes (original miniF2F, preserved across ports): 244 `valid` + 244 `test` = 488 problems total, sourced from AIME/AMC/IMO plus MATH-dataset algebra/number-theory problems.

### Other Lean 4 ports (for context — none are as actively maintained)
- `yangky11/miniF2F-lean4` — historically the most widely used community port; **explicitly self-flagged as unmaintained**: "This repo is NOT maintained regularly. Use your own discretion." Reservoir shows toolchains up to `v4.18.0-rc1`.
- `rahul3613/miniF2F-lean4` — another Lean 4 port, originates from the (now-archived) `facebookresearch/miniF2F` lineage.
- `hoskinson-center/minif2f-lean4` (HF Datasets) — a static dataset-viewer port, not a buildable/updatable Lean project.
- DeepSeek-Prover-V2's own paper (§ Appendix D, "Revision to MiniF2F") layers its own additional corrections on top of a miniF2F revision by Wang et al. (2025) — yet another variant, used only inside that paper's eval harness, not a general-purpose repo.

**Bottom line: use `google-deepmind/miniF2F` (Lean 4.27.0 toolchain, Apache-2.0) as the canonical, currently-maintained Lean 4 miniF2F.** Avoid `yangky11/miniF2F-lean4` for new work given its explicit "not maintained" disclaimer, though it remains widely cited in older papers' eval harnesses.

---

## Sources
- https://huggingface.co/deepseek-ai/DeepSeek-Prover-V2-7B (README, raw)
- https://arxiv.org/html/2504.21801v2 (Appendix A — exact non-CoT/CoT prompt examples)
- https://github.com/deepseek-ai/DeepSeek-V3/blob/main/LICENSE-MODEL
- https://huggingface.co/Goedel-LM/Goedel-Prover-V2-8B (README, raw) and https://github.com/Goedel-LM/Goedel-Prover-V2
- https://huggingface.co/unsloth/DeepSeek-Prover-V2-7B-GGUF
- https://huggingface.co/mradermacher/Goedel-Prover-V2-8B-GGUF , https://huggingface.co/NikolayKozloff/Goedel-Prover-V2-8B-Q8_0-GGUF
- https://huggingface.co/mlx-community/DeepSeek-Prover-V2-7B-4bit (MLX, not GGUF — noted for contrast)
- https://huggingface.co/datasets/internlm/Lean-Workbook (README + direct download/parse of `lean_workbook.json`, 140,214 rows verified locally)
- https://github.com/google-deepmind/miniF2F (README, `lean-toolchain`, commit history via GitHub API)
- https://github.com/yangky11/miniF2F-lean4
