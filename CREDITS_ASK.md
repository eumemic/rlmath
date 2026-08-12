# Draft: compute-credits request to Prime Intellect

*(Draft for the user to edit and send — via the dashboard contact/credits channel or
community Discord. Written 2026-08-12; numbers current as of that morning.)*

---

Subject: Compute credits for an open RL-for-theorem-proving environment built on verifiers v1

Hi — I'm building **rlmath**, an open research project testing whether RLM-style context
isolation makes RL-trained decomposition policies *transfer* along a controlled proof-size
axis in Lean 4 — the mechanism question left open by ProD-RL and Goedel-Code-Prover. Design
doc with registered priors, all code MIT:

- Environment (live on your Hub): `eumemic/rlmath-decomp` — kernel-verified rewards, v1
  Taskset/Trace-native, the budget knobs in `[env.taskset.task]` TOML for prime-rl
- Repo: github.com/eumemic/rlmath (design doc `DIRECTION.md`; registered priors §4)

Status after two days (≈$41 of my own $50 on your platform): environment published and
externally verified; a 4,000-statement leaf pass-rate bank measured on H100 pods (DSV2-7B
bf16 via vLLM); two size-parameterized task families validated 30/30 against a 20-proof
automation battery with kernel-checked oracle replay; first zero-shot cells run through
Prime Inference (team-billed). The project exercises your new stack end-to-end — v1
environments today, Hierarchical GRPO for the multi-agent phase later — and everything is
public as it lands.

**Ask: $1,500–2,000 in platform credits**, covering: the full 30–50k-statement bank sweep
(~$45), the Phase-2 zero-shot study across root models via Prime Inference (~$50–150), and
the Phase-3 GRPO training runs (2–4 H100s for 2–3 weeks, the bulk). In return: a maintained
public Hub environment with genuinely unhackable (kernel-decided) rewards, a documented
case study of prime-rl on formal theorem proving, and publication of all findings —
positive or negative — with the registered-priors discipline already in the repo.

Happy to share the full design doc, the overnight run logs, or scope this differently.

---

*(Send checklist: paste repo + Hub links; attach or link DIRECTION.md; mention the
$41-of-$50 ledger honestly — it shows the money goes to metal, not overhead.)*
