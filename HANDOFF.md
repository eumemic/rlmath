# HANDOFF — read this first when resuming

Written 2026-08-12 ~19:30, before a context compaction. Everything durable is in git;
this file holds the state that otherwise lived only in the working session: the operational
runbook, unresolved flags from build agents, and the ordered next moves.

**Doc map:** `DIRECTION.md` = the science (question, registered priors §4, phase plan §5,
cold-start ladder in "Stack updates"). `FAMILIES.md` = Phase-1 contract (validator V0–V6,
leaf-disjointness, corridor). `PHASE0_NOTES.md` = gates + decision log. `OVERNIGHT.md` =
the 2026-08-12 run narrative + all three session-3 verdicts. `research/*.md` = per-topic
deep notes (papers, families, retune levers, verifiers API).

---

## 1. Where the project stands

| Phase | State |
|---|---|
| **0** | **CLOSED** — all gates. Repo public (MIT), Hub env `eumemic/rlmath-decomp` v0.1.2 PUBLIC. Bank: 4,102 rows / 401 band (299 train / 102 eval) / 0 errors. |
| **1** | **OPEN on case_tree only.** bridge_chain DONE at preset `e3_lowdeg` (measured 0.429 vs 0.404 projected; band-fit 0.83; 15/15 full-battery valid). case_tree measures 0.85/0.97/0.92 — **above** the 0.9 ceiling, i.e. too easy for DSV2. |
| **2** | Instrument validated; **cold-start question answered** — few-shot (rung 1.5) flips qwen3-30b from 0/5 to 5/5 stage-1-passing decompositions. Full study not yet run. |
| **3** | Design only. Not started. |

**Money: ≈$48.5 of the $50 Prime credit spent.** Credits ask (`CREDITS_ASK.md`) sent by the
user 2026-08-12; no reply yet. Every GPU item is gated on that reply or fresh funds.

---

## 2. Operational runbook (hard-won; each line cost time)

### Prime CLI
- **Two contexts, and they differ**: `prime switch <team-id>` for **pods** (the $ lives in the
  team wallet — team `Eumemic`, id `cmsp77l44000710s4dghtmtss`); `prime switch personal` for
  **env pushes** (the Hub username lives on the personal account). Wrong context = "Payment
  required" on pods or "missing a teamname" on pushes.
- Inference: `https://api.pinference.ai/api/v1`, key from `~/.prime/config.json`, **must** send
  `X-Prime-Team-ID: cmsp77l44000710s4dghtmtss` or it bills the empty personal balance.
- Availability IDs go stale in minutes — re-list before every `pods create`.
- `prime pods create --id <id> --name <n> --disk-size 200 --image cuda_12_6_pytorch_2_7 --yes --plain`
  (lambdalabs H100 PCIe ≈$3.2/hr; massedcompute rejects the CUDA images).
- Terminate: `printf 'y\n' | prime pods terminate <id>` (interactive prompt otherwise).

### SSH to pods
- Prime injects **account-registered** keys only — `~/.ssh/id_ed25519.pub` is registered in the
  dashboard; the CLI's `set-ssh-key-path` does *not* add keys to a pod.
- Add a `~/.ssh/config` alias per pod (`Host rlmath-<name>` / HostName / Port 1234 / User root).
- **`scp` needs `-O`** on this macOS build.

### Launching long work on a pod (the pattern that works)
```bash
scp -O script.sh pod:/root/script.sh
ssh pod 'setsid nohup bash /root/script.sh > /root/log 2>&1 < /dev/null & disown'
```
- Do **not** stream scripts via `ssh 'bash -s' < script` — stdin conflicts kill long jobs.
- Do **not** write `curl … | sh -s -- -y < /dev/null` — `sh -s` reads its *script* from stdin, so
  the redirect feeds it an empty program (this bit twice; misdiagnosed once as an image quirk).
- Watch with a loop covering **all** terminal states (done / failed / process-died), not just success.

### vLLM on these pods (pinned recipe — see `scripts/bakeoff/pod_setup.sh` comments)
`vllm==0.9.2` + `torch==2.7.0+cu126` + `transformers==4.53.0`, `--extra-index-url
https://download.pytorch.org/whl/cu126`. Newer vllm links `libcudart.so.13` against these pods'
12.8 driver (metadata says compatible; the wheel ABI is the truth). Launch models
**sequentially** — concurrent starts race on memory profiling and one engine gets a starved KV
budget. Verify `import torch, vllm, transformers` + a CUDA alloc *before* serving.

### Sweep architecture
`scripts/bakeoff/pod_sweep_setup.sh` puts **everything pod-side** (vLLM + Lean + repo + builder).
The earlier tunnel design lost 222 rows to an SSH death; the pod-side design ran 3,300 statements
with **zero** errors. Throughput at `--concurrent 6 --workers 12`: ~430–480 rows/hr, ~8.1k leaf
attempts/hr. Fresh-pod setup ≈20 min (models + Mathlib cache).

### Local hygiene
- `set -o pipefail` on any gating `pytest … | tail` — a pipe hides the failure and will let a red
  suite through a `&&` chain (this happened once, mislabeling a commit).
- **Scoped `git add`** while background agents share the tree; `git add -A` swept an agent's WIP
  into an unrelated commit once.
- Workflow agents: give each one an owned-files list and forbid editing others'; have them report
  contract friction as flags instead of fixing it.

---

## 3. Next moves, in order

1. **case_tree hardening ladder** (local, $0 until the confirm measurement). Mirror the bridge
   playbook exactly, since it worked: mine `data/bank/family_leaf_calibration.jsonl` for which
   knobs move difficulty → register 3–4 *harder* presets with projections **before** measuring →
   local battery gate (with planted control) → one GPU pass (~$2) → pick by the rule in
   `research/retune-notes.md` → regenerate + revalidate → **Phase 1 closes**.
   The tell for why it's too easy: every case_tree leaf uses the same
   `nlinarith [mul_nonneg …]` witness template.
2. **Re-fit the difficulty-lever model** on the 150 fresh `data/bank/retune_measure.jsonl` rows
   (currently fitted on 58, validated in-sample). Nearly free, improves every future preset
   projection. Retune agent called this the next session's first move.
3. **Confirm bridge's within-chain gradient at e3** (flag §4.3) during that same GPU pass.
4. **Phase-2 full study** once a leaf endpoint exists: few-shot arms as default (rung 1.5 is
   settled), roots per the roster, k-grid across both families, `--max-usd` per cell.
5. **Wide sweep (#12, ~$45)** the moment credits land — machinery proven, `--repair` first to
   re-run the 222 quarantined error rows.

---

## 4. Unresolved flags (from build agents; none blocking, all real)

**Science-relevant**
1. **Within-chain flatness risk (highest value).** Measured leaf pass rate falls with left
   exponent sum (0.233 → 0.114 → 0.054 for es ≤4 / 5–7 / ≥8), and exponent sum grows with chain
   *position* by construction. So per-node difficulty may not be flat *within* a chain even when
   flat *across* k. Confirm at e3; if real, it's a schema fix (bounded exponent growth), and
   DIRECTION §5.4(a) should state both flatness axes.
2. **Opus roster cell never ran** (budget deadline) — the ceiling datapoint is missing, so the
   rung-1.5 verdict is marked provisional for that root only. The **direct**-arm opus cell needs
   no leaf and costs ~$0.50 over Prime Inference; the decomp cell needs a leaf endpoint.
3. **Qwen3.5-122B-A10B went 0/5 on format** in the roster (both arms) — looks like a chat-template
   quirk, not a capability result. Don't cite it as evidence without diagnosing.
4. **Contamination check covers the exemplar's goal prop only.** When semi-synthetic (bank-drawn)
   leaves land, extend it to `leaf_pool` membership or rung 1.5 reopens the channel the
   leaf-disjointness contract closes.

**Engineering**
5. `results/` is **not** in `.gitignore` and zero-shot rows store full root completions — decide
   track-vs-ignore before a large sweep (tens of MB of model text).
6. `--max-usd` caps *successful* spend: a row that errors records no usage, so a repeatedly-failing
   cell can exceed the cap. Watch the provider dashboard on long runs.
7. Direct-arm kernel failures are recorded as `leaf_failed` (the harness's flat-arm baseline names
   it that). Truthful but confusing; a `PROVER_FAILED` status or a rename is a core change
   touching every consumer — deliberately not taken.
8. No pre-call context-window guard; over-window is classified from the provider's refusal. Before
   the beyond-window tier (§5.4e, the P1 headline), add a `--root-context-tokens` table so those
   rows are recorded without paying for refused calls.
9. `LeafProver.stats` counters are non-atomic under `--concurrent N>1` (undercount only; no bank
   number affected, but the format-failure instrument degrades after a concurrent run).
10. Direct-arm exemplar omits the `sorry` skeleton to stay sanitizer-clean, so the example frames
    the goal slightly differently from the real user turn. Reversible; documented.
11. `research/family-v2-hardening.md` §7.1 and `research/family-bridge-chain.md` need one-line
    pointers to the flatness verdict and `research/retune-notes.md`.

---

## 5. Review loop

The user runs this past two reviewer agents ("advisor", "strategist") who have caught real
problems repeatedly — provisional-gate discipline, the bf16-not-quantized oracle rule, the
mutant membership-inheritance bug, the "close phases on data, not snapshots" rule, and rung 1.5
itself. When they flag something, implement it *before* the next artifact materializes, and
write the reasoning into the binding contract file rather than only into a commit message.
