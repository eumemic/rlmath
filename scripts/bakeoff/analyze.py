"""Band-fit analysis for the leaf bake-off (DIRECTION.md open decision #2, method
fixed 2026-08-11): the winner is the prover whose pass@k distribution puts more
mass in the [0.25, 0.9] band on the SAME candidate slice — a *discriminative*
oracle, not a maximal one. Also reports the end-to-end throughput gate number
(verified leaf attempts/hr including inference), closing the PROVISIONAL gate
in PHASE0_NOTES.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BAND = (0.25, 0.90)


def load(path: str) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # torn last line
    return rows


def report(path: str) -> dict:
    rows = load(path)
    leaf_ids = {r.get("leaf_id") for r in rows if r.get("leaf_id")}
    measured = [r for r in rows if r.get("pass_rate") is not None]
    rates = [r["pass_rate"] for r in measured]
    in_band = [r for r in rates if BAND[0] <= r <= BAND[1]]
    zeros = sum(1 for r in rates if r == 0.0)
    ones = sum(1 for r in rates if r == 1.0)
    attempts = sum(r.get("n_attempts", 0) for r in measured)
    verified = sum(r.get("n_verified", 0) for r in measured)
    elapsed = sum(r.get("elapsed_s", 0.0) for r in measured)
    out = {
        "file": path,
        "leaf_id": sorted(leaf_ids),
        "n_measured": len(measured),
        "n_errors": sum(1 for r in rows if r.get("status") == "error"),
        "mean_pass": sum(rates) / len(rates) if rates else None,
        "band_mass": len(in_band) / len(rates) if rates else None,
        "frac_zero": zeros / len(rates) if rates else None,
        "frac_one": ones / len(rates) if rates else None,
        "attempts": attempts,
        "verified": verified,
        "attempts_per_hr_end_to_end": attempts / (elapsed / 3600) if elapsed else None,
        "mean_s_per_statement": elapsed / len(measured) if measured else None,
    }
    print(f"\n== {path}")
    for k, v in out.items():
        if k != "file":
            print(f"   {k:28} {v if not isinstance(v, float) else round(v, 4)}")
    return out


def main() -> int:
    reports = [report(p) for p in sys.argv[1:]]
    scored = [r for r in reports if r["band_mass"] is not None]
    if len(scored) >= 2:
        best = max(scored, key=lambda r: r["band_mass"])
        print(f"\nBAND-FIT WINNER (mass in [{BAND[0]}, {BAND[1]}]): {best['leaf_id']}"
              f"  band_mass={round(best['band_mass'], 4)}")
        print("Reminder: the winner is the more *discriminative* leaf, not the stronger one "
              "(PHASE0_NOTES decision 2026-08-11). Sanity-check frac_zero/frac_one before "
              "committing — a high-band_mass arm with huge frac_zero may just be weak.")
    out_path = Path("analysis/bakeoff.json")
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(reports, indent=2), encoding="utf-8")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
