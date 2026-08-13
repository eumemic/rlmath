#!/usr/bin/env python
"""Per-row gate verdicts for data/families/ct_candidates.jsonl.

Kept OUT of the candidates file itself so that file stays byte-reproducible from
the one documented staging command; this is the sidecar that says, per staged
statement, whether the automation battery was actually pointed at it and whether
its generator witness kernel-checked.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path("/Users/tom/code/playground/rlmath")
D = ROOT / "data" / "families"
B = D / "ct_battery"

cand = [json.loads(l) for l in open(D / "ct_candidates.jsonl")]
wit = json.load(open(B / "gate_witness_all.json"))
bat = json.load(open(B / "gate_battery_ext.json"))

# witness verdicts, keyed by the id the extended gate used
wok: dict[str, bool] = {}
for name, v in wit.items():
    if name == "_meta":
        continue
    for r in v["rows"]:
        wok[r["id"]] = r["ok"]

probed: dict[str, list[str]] = {}
for name, v in bat.items():
    if name == "_meta":
        continue
    for p in v["probes"]:
        if p["kind"] == "leaf":
            probed[p["prop"]] = p["killers"]
# the stager's own subset (coefficient extremes per k), from ct_battery/<rung>.jsonl
for name in ("v2", "r1_recip", "r2_prod", "r2_sum", "r3_floor", "r4_floorprod"):
    f = B / f"{name}.jsonl"
    if f.exists():
        for line in open(f):
            probed.setdefault(json.loads(line)["formal_statement"], [])

rows = []
for c in cand:
    key6 = c["statement_key"][:6]
    wid = f"{c['preset']}-k{c['k']}-p{c['position']}-{key6}"
    rows.append({
        "id": c["id"], "preset": c["preset"], "k": c["k"],
        "statement_key": c["statement_key"],
        "witness_kernel_ok": wok.get(wid),
        "battery_probed": c["formal_statement"] in probed,
        "battery_killers": probed.get(c["formal_statement"], []),
    })

with open(B / "gate_rows.jsonl", "w") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

n = len(rows)
print("rows", n,
      "witness_ok", sum(r["witness_kernel_ok"] is True for r in rows),
      "witness_missing", sum(r["witness_kernel_ok"] is None for r in rows),
      "battery_probed", sum(r["battery_probed"] for r in rows),
      "killed", sum(bool(r["battery_killers"]) for r in rows))
