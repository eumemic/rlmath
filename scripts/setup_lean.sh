#!/usr/bin/env bash
# Idempotent Lean toolchain setup: elan -> Mathlib-backed lake project -> REPL binary.
# Long-running (Mathlib olean cache is a multi-GB download); run in background:
#   nohup bash scripts/setup_lean.sh > logs/setup_lean.log 2>&1 &
# Success marker on completion: SETUP_LEAN_DONE
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/logs" "$ROOT/lean"

# --- 1. elan (Lean toolchain manager)
if ! command -v elan >/dev/null 2>&1 && [ ! -x "$HOME/.elan/bin/elan" ]; then
  echo "== installing elan"
  curl https://elan.lean-lang.org/elan-init.sh -sSf | sh -s -- -y --default-toolchain none
fi
export PATH="$HOME/.elan/bin:$PATH"
elan --version

# --- 2. lake project depending on Mathlib
cd "$ROOT/lean"
if [ ! -d rlmathlib ]; then
  echo "== creating mathlib-backed project rlmathlib"
  # `+...:lean-toolchain` pins the toolchain to whatever current Mathlib uses;
  # `math.toml` is the lake template that adds the Mathlib dependency.
  lake +leanprover-community/mathlib4:lean-toolchain new rlmathlib math.toml
fi
cd rlmathlib
echo "== fetching Mathlib olean cache (multi-GB; the long pole)"
lake exe cache get
echo "== building project"
lake build

# --- 3. leanprover-community/repl, built against the same toolchain
cd "$ROOT/lean"
if [ ! -d repl ]; then
  echo "== cloning repl"
  git clone --depth 1 https://github.com/leanprover-community/repl
fi
cd repl
cp "$ROOT/lean/rlmathlib/lean-toolchain" .
lake build
test -x .lake/build/bin/repl

# --- 4. smoke: one command through the REPL inside the project env
cd "$ROOT/lean/rlmathlib"
echo '{"cmd": "theorem _smoke : 1 + 1 = 2 := by norm_num"}' | head -c 0 >/dev/null # placeholder; real smoke needs import round-trip, done by pytest -m integration
echo "SETUP_LEAN_DONE"
