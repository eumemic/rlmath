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
| **1** | **OPEN on both families, for two DIFFERENT structural reasons** (rewritten 2026-08-13 after the overnight session — read `OVERNIGHT-2.md` for the narrative). **case_tree: sound and close.** The hardening ladder measured (239 leaves × 8, invoice $6.51); no rung reaches the corridor *unfiltered*, but that judged the wrong object — the bank's own discipline is measure-then-filter, and filtering gives `r3_floor` **0.448 against a 0.45 target**, band-fit 1.00, clearing the oracle gate at every k to 32 with 8 attempts/leaf. One test stands between this and a Phase-1 close: filtering at n=8 selects on noise, so the filtered pool must be **re-measured at n=32** (task #23). **bridge_chain: the leaf-difficulty gradient is solved but the family may be unusable.** Its **goal collapses** — a fixed *k-independent* proof closes the shipped `e3_lowdeg` goal at k=2/4/8/**32** (verified twice), so DIRECTION §5.4(d) "flat-prover solve rate decays in k" fails and the control arm never needs the decomposition. `research/retune-notes.md` §9, task #18. |
| **2** | Instrument validated; **cold-start question answered** — few-shot (rung 1.5) flips qwen3-30b from 0/5 to 5/5 stage-1-passing decompositions. Full study not yet run. |
| **3** | Design only. Not started. |

**Money — corrected 2026-08-12 23:12 CDT against `prime wallet`, which is the invoice; every
figure previously in this repo was a wall-clock estimate and undercounted.**

| | recorded (estimate) | actual (wallet) |
|---|---|---|
| pod #1 (SSH-denied, killed fast) | ≈$1.50 | **$0.12** |
| bake-off pod | ≈$13 | **$22.22** |
| overnight sweep pod | ≈$29.7 (vs a $30 cap) | **$36.19** |
| session-3 pod | ≈$5.8 | **$2.66** |
| inference (all sessions) | "pennies of $5" | **$0.36** |
| ct-ladder pod (2026-08-13) | ≈$3.50 | **$6.51** |
| **total** | **≈$52** | **$68.06** |

Consequences. (a) **The estimates run low, persistently and by a lot** — ~27% across the first four
pods, and **86% on the ct-ladder pod even after I explicitly padded for setup.** (b) The row that is
almost certainly the overnight sweep is **$36.19 against the $30 cap the user authorized**, an
overrun reported at the time as a clean $29.7 close. (c) Wallet timestamps are **UTC** (CDT+5),
which is what makes recent rows look like they are in the future.

**Why ct-ladder missed by 86%, because the cause generalises:** the pod was up **2h12m**, not the
~80 min projected. Install alone took 13 min, and the measurement ran ~1h45m rather than the ~35 min
that 430–480 rows/hr implies. **That throughput figure was measured at k ≤ 8 and does not transfer
to a k-grid containing 32** — those rows carry 4-decade coefficients and much longer statements, so
both generation and Lean verification are several times slower per row. Budget k=32 work at roughly
**3× the k ≤ 8 rate**.

**Balance $31.93 as of 2026-08-13 06:00.** Do not read it as authorization: the overnight
authorization was $12 and $6.52 of it is spent. Ask before the next pod. `CREDITS_ASK.md` was sent
2026-08-12; no reply seen.

---

## 1b. PHASE 3 IS RUNNING — how to check on it and harvest it (2026-08-14)

A GRPO run is live on pod **`ct-p3b`** (lambdalabs H100 PCIe). If this session is gone, that pod
may still be training or may have finished; **check before launching anything new**.

```bash
prime switch cmsp77l44000710s4dghtmtss        # pods live in the team wallet
prime pods list --plain                        # is ct-p3b alive? how long?
prime wallet | head -6                         # the invoice, never an estimate
# ssh alias may need re-adding: Host rlmath-p3b / HostName <ip> / Port 1234 / User root
ssh rlmath-p3b 'cat /root/train.done 2>/dev/null || echo RUNNING'
ssh rlmath-p3b 'grep "^  \[" /root/rlmath/logs/../train.log; grep -c TRAIN_DONE /root/train.log'
```

**Harvest, then terminate, then read the invoice:**
```bash
scp -O rlmath-p3b:/root/rlmath/runs/grpo9b/eval.jsonl runs/grpo9b/
scp -O rlmath-p3b:/root/train.log logs/phase3_train.log
printf 'y\n' | prime pods terminate <id>       # retry; if HTTP 500, `poweroff -f` from inside
uv run python scripts/analyze_phase3.py         # applies §7.3's registered rule mechanically
```

**The run:** Qwen3.5-9B + LoRA r=32, 200 steps, G=8, 4 prompts/optimizer step, 384-token
completions, reward = graded stage-1 plan validity (0.0 unparseable / 0.3 parses / 1.0 valid in
Lean). Trained **only at k=2**; eval n=40 at k=2/4/8 at baseline, step 100, step 200.
**~2 h / ~$6** from measured timings.

**The two changes that made it viable** (DIRECTION §7.4/§7.5, both measured):
- `PREFILL = "#lemma hb1 : "` on the assistant turn. Unprompted the model burns ~680 tokens of
  preamble and needs 1024 to reach `#end`; a 384-token cap therefore made EVERY reward 0.0 —
  caught only because the baseline eval exists. Prefilled it parses 62.5% at 384 in 13 s.
  A bare `#lemma ` makes it WORSE (invites a numeric name, not a Lean identifier).
- Batched eval with left padding. Single-sequence generation made eval a 13-hour job against a
  2-hour training run.

**Known interaction:** prefill saturates the 0.3 format tier, so the reward is effectively binary
validity at ~15%; ~73% of groups still carry variance at G=8. The "parse → >85%" prediction is
therefore VOID as a plumbing check — watch the `reward stats` counters for `valid` going
non-zero instead.

**Read it with `scripts/analyze_phase3.py`, not by eye** — predictions are registered in
DIRECTION §7.3 and the analyzer applies them, including the correction that k=8 at n=40 is
**underpowered** (so k=8 is directional only and **k=4 carries the verdict**).

### The nine setup failures, so a future Phase-3 pod pays none of them
All fixed and consolidated in `scripts/bakeoff/pod_phase3_all.sh`; each is commented at its site.
1. image python is 3.10.12, `rlmath` needs ≥3.12 (StrEnum) → `uv venv --python 3.12`
2. `uv pip install -U trl transformers` replaced pinned cu126 torch with cu130 on a 12.8 driver
   → frameworks first, **torch last** from PyTorch's own `--index-url`, then a real bf16 matmul gate
3. `pkill -f fix.sh` matched its own launching shell → never pattern-match your own cmdline;
   use a done-file sentinel (a `pgrep -f` liveness check also reported ALIVE against a dead pod
   for 25 min because the pattern matched the monitor's own ssh command)
4. trl 1.10 `GRPOConfig` has no `max_prompt_length`
5. `per_device_train_batch_size` counts **completions**, not prompts, and must divide by
   `num_generations` — the error it raises names `generation_batch_size`, which is neither flag
6. Qwen3.5 is a **VL** model → needs `torchvision`
7. …and TRL's `AutoProcessor` builds Qwen3VL **video** processors, which raises a transformers
   docstring error → pass `processing_class=tokenizer` explicitly
8. `stop_strings` requires a tokenizer TRL will not forward → **deleted**, not worked around
9. a string-replacement "fix" silently did not match and I did not verify → assert the fixed
   state, never trust a replace

**Method lesson, which cost more than any single item:** the trainer was written against
remembered API shapes and validated in layers too thin to catch the next problem. The gate that
finally worked is `scripts/preflight_trainer.py` — it *constructs* the real trainer and takes one
real step. Write that gate first next time.

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
- **`prime wallet` is the only real spend number.** It prints balance plus itemised billing rows.
  Every cost figure this project reported before 2026-08-12 23:12 was elapsed-hours × assumed
  hourly rate, and that method ran ~27% low (§1 table) — it misses setup, image pull, teardown and
  rounding. Quote the wallet, never the estimate, and re-check it *after* terminating rather than
  at the moment you decide to. Its timestamps are **UTC**.
- A leftover `ssh` from a previous session can fail long after its pod is gone
  (`client_loop: send disconnect: Broken pipe`). That is a dead connection, not spend — confirm
  with `prime pods list` (0 pods) rather than assuming either way.

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

*Rewritten 2026-08-13 after the overnight session. The two families now need different things, and
the wide sweep is NO LONGER the recommended next spend — see the reason under (3).*

1. **#23 — the one measurement that matters: re-measure a FILTERED case_tree pool at n=32.**
   Filtering at pass@8 selects on noise (a leaf whose true rate is 0.95 can measure 0.875 and be
   kept), so `r3_floor`'s filtered 0.448 and band-fit 1.00 describe the *measurement*, not the
   leaves. If most of the band-fit survives n=32, **Phase 1 closes for case_tree** and the whole
   synthetic-leaf route is vindicated. If it collapses, synthetic leaves are out and direction 1
   needs a new family. Stage surplus (`r3_floor` 3.3×, `r2_prod` 1.9×), filter, re-measure; put
   `H2_quartic` in the same pod (R3′ re-legitimised it). Budget realistically — see the money note.
2. **#18 — decide bridge_chain's fate.** Not a calibration job any more: make the goal *require* the
   decomposition, or retire the family. Escapes named but untested in `research/retune-notes.md` §9.
   If none work, run the transfer experiment on case_tree alone — survivable (the design needs *a*
   size axis, not two) but it halves the generality of any transfer claim, and DIRECTION §5 should
   say so up front rather than have it surface at write-up.
3. ~~Wide sweep (#12)~~ **WITHDRAWN as the next spend.** It buys difficulty-calibrated *statements*,
   not usable *leaves*: the 401 in-band statements are self-contained competition inequalities with
   their own variables, while `bridge_chain` leaves must be relational steps over *shared* variables
   and `case_tree` leaves must be band claims over the goal's `x`. Neither can host them, and the
   obvious composing assembly (a conjunctive goal) fails V6 outright. **Leaf content and assembly
   are coupled** — the independence that makes a leaf calibrated is what makes it uncomposable.
   Revisit only once a family exists that can host independent statements.
4. **#22 — the attempt budget.** R5 turned this from theory into a gate: no corridor-target family
   satisfies DIRECTION §5.5(b) at k>2 under the shipped `Budgets`. A filtered `r3_floor` pool needs
   only 8 attempts/leaf, so this may be cheap — but it touches a frozen core contract and costs
   Phase-2/3 GPU linearly. User's call.
5. **#21 — `maxHeartbeats`.** Still blocks the k=128 tier and DIRECTION §5.4(e). Remember the trap:
   the same constant arms the automation battery, so any bump invalidates every V0/V5 verdict.
6. **#19 / #20** — leaf-pool rejection sampling (needed by #23's filtered pool) and the datasheet
   columns. Both local, free, small.
7. **Phase-2 full study** once a leaf endpoint exists: few-shot arms as default, roster roots,
   k-grid, `--max-usd` per cell.

**A contract gap worth fixing before any new family:** V0 is a *single-tactic* battery, and
bridge_chain's goals survive it 91/91 while falling to a fixed 15-line **idiom**. case_tree has an
instrument for this (its idiom probe — the thing that made its ladder readable); bridge_chain had
none, which is why the collapse went unseen for the whole retune. A registry of generator-derived
flat routes, run like the battery, belongs in `validate.py` beside V0.

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
