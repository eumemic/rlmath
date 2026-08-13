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
| **1** | **OPEN on BOTH families** (corrected 2026-08-12). bridge_chain at `e3_lowdeg` passes R1 (0.429 vs 0.404 projected) and R2 (band-fit 0.83) but **FAILS R3, the flatness gate** — per-k means 0.575/0.463/0.250, spread 0.325 = 6.5× the ±0.05 tolerance, and all five presets fail the same way. R3 was never evaluated at the session close; the earlier "DONE" was premature. Mechanism identified and structural: `research/retune-notes.md` §8. case_tree measures 0.923 — **above** the 0.9 ceiling, too easy, and the cause is idiom recall not calibration (`research/case-tree-forensics.md`). |
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

*Reordered 2026-08-12: Phase 1 is open on **both** families and bridge_chain's defect is the more
serious of the two, because it is the flatness property the whole k-axis rests on.*

1. **bridge_chain flatness fix (#18) — highest value, local, $0 until the confirm pass.**
   R3 fails for all five presets; the growth law is the cause (`research/retune-notes.md` §8).
   Stage a bounded-degree schema (candidate: growth by integer multiplier, `M_i = 3^i · x^p y^q z^r`)
   → local battery gate with planted control → register projections → GPU confirm → apply R0–R4
   **including R3 this time**. Note the process lesson: R1/R2 were applied at the close and R3 was
   silently skipped, which is how a failing family got written up as DONE.
2. **case_tree hardening ladder (#16)** — in flight as a workflow. The playbook does **not** transfer
   from bridge_chain: there is no lever inside the knob support (every marginal 0.87–0.99; 50/68
   leaves at a perfect 8/8), because 68/68 successful proofs run one memorized idiom
   (`Real.sqrt_le_iff` + `nlinarith [sq_nonneg …]`). So this is a *schema* ladder, and the
   coverage/necessity soundness asymmetry has to be re-derived per rung.
   See `research/case-tree-forensics.md`, `research/case-tree-hardening.md`.
3. ~~Re-fit the difficulty-lever model~~ **DONE** — `research/lever-model-refit.md`. Levers replicate
   out of sample; §5's projections scored MAE 0.044, r=0.83, and picked the right preset under R1.
4. ~~Confirm bridge's within-chain gradient~~ **DONE — confirmed**, see flag 1 and item 1 above.
5. **Phase-2 full study** once a leaf endpoint exists: few-shot arms as default (rung 1.5 is
   settled), roots per the roster, k-grid across both families, `--max-usd` per cell.
6. **Wide sweep (#12, ~$45)** the moment credits land — machinery proven, `--repair` first to
   re-run the 222 quarantined error rows.

---

## 4. Unresolved flags (from build agents; flag 1 is now BLOCKING)

**Science-relevant**
1. ~~Within-chain flatness risk (highest value).~~ **CONFIRMED 2026-08-12 — now a blocker, not a
   risk.** The gradient is real (es coef −0.0353/unit, SE 0.0079, **z = −4.48** controlling for
   preset) and exponent sum grows linearly with chain position by construction (e3_lowdeg's max es
   *equals k*), so chain-aggregate difficulty falls with k and **R3 fails for all five presets**.
   The per-position draw *is* flat in k (structural check, n=300 per k, no measurement), so the fix
   is bounded degree growth rather than a resampler change — leading candidate: carry growth in an
   integer multiplier (`M_i = 3^i · x^p y^q z^r`) so degree, and hence the measured blocker `1 ≤ M`,
   stays constant along the chain. Verdict + tables + mechanism: `research/retune-notes.md` §8;
   statistics: `research/lever-model-refit.md`. DIRECTION §5.4(a) still needs its second flatness
   axis (draft text in the refit note §4).
2. **Opus roster cell never ran** (budget deadline) — the ceiling datapoint is missing, so the
   rung-1.5 verdict is marked provisional for that root only. The **direct**-arm opus cell needs
   no leaf and costs ~$0.50 over Prime Inference; the decomp cell needs a leaf endpoint.
3. **Qwen3.5-122B-A10B went 0/5 on format** in the roster (both arms) — looks like a chat-template
   quirk, not a capability result. Don't cite it as evidence without diagnosing.
4. **Contamination check covers the exemplar's goal prop only.** When semi-synthetic (bank-drawn)
   leaves land, extend it to `leaf_pool` membership or rung 1.5 reopens the channel the
   leaf-disjointness contract closes.

**Engineering**
5. ~~`results/` is not in `.gitignore` and zero-shot rows store full root completions — decide
   track-vs-ignore before a large sweep.~~ **RESOLVED 2026-08-12: keep tracking, unsplit.**
   Measured on the 56 existing rows: 74% of row bytes is the `completion` field, 4,435 B/row raw —
   but model text is highly repetitive and **packs 8.6×** (514 B/row). A full Phase-2 study
   (6 roots × 2 arms × 2 families × 4 k × 30 problems × 2 few-shot variants ≈ 5,760 rows) is
   therefore **~25 MB of working tree but only ~3 MB packed**; a second pass doubles it to ~6 MB.
   That does not justify splitting completions into a sibling `.raw.jsonl`, which would add a
   two-file sync invariant to a script that already carries resume + `--repair` semantics — real
   complexity against a non-problem. `roster_analyze.py` reads `usage.completion_tokens`, never the
   text, so nothing downstream depends on the choice either way.
   **Re-check trigger:** completions are long-tailed by design (`run_zeroshot.py:422`) and a CoT root
   at k=32 can emit ~10× the tokens. Re-measure if `git count-objects -vH` attributes more than
   ~25 MB packed to `results/`, or before the beyond-window tier (§5.4e) runs.
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
