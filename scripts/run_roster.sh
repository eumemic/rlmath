#!/usr/bin/env bash
# Four-root few-shot roster — DIRECTION.md §5.5 cold-start ladder, RUNG 1.5.
#
# The pre-registered diagnostic, verbatim from the ladder entry (2026-08-12):
#
#   "Root-roster diagnostic before any escalation past this rung: qwen3-30b
#    few-shot re-run, haiku few-shot, one 100B-class open model, opus as
#    ceiling — a handful of episodes each. If NO root decomposes few-shot at
#    k=2, that is registered evidence rung 3 is unavoidable; if qwen few-shot
#    assembles, the cold-start problem was a prompt gap and priors barely move."
#
# It exists because of a measured fact, not a hunch (OVERNIGHT.md, 14:52):
# 12/12 zero-shot decomp episodes were `plan_invalid` at *stage 1* — lemma
# statements elaborated clean, assemblies failed. That localizes the failure to
# a missing affordance (what a working assembly block looks like), which is the
# one hypothesis a few-shot exemplar can kill cheaply.
#
# This driver only *arranges* cells; scripts/run_zeroshot.py owns every scoring
# decision, the resume rule and the budget guard. One cell = one JSONL under
# results/zeroshot/, so re-running this script resumes rather than duplicates.
#
# Usage:
#   bash scripts/run_roster.sh <leaf-base-url> [leaf-model] [leaf-template]
#   DRY_RUN=1 bash scripts/run_roster.sh            # resolve every cell, touch nothing
#   DIRECT_ONLY=1 bash scripts/run_roster.sh        # no GPU leaf available today
#
# The leaf endpoint is a positional parameter because it is session-specific:
# it is whatever pod is up right now (http://localhost:8000/v1 over a tunnel, or
# the pod's own address when running pod-side). There is no sane default and a
# stale one would silently score the wrong thing.
#
# Env knobs (all optional):
#   N=5                 episodes per cell
#   MAX_USD=0.75        per-cell spend cap (run_zeroshot.py stops between rows)
#   PROBLEMS=...        problem file (default bridge_chain k=2)
#   SET=bridge_chain    cell name base
#   BASE_URL / API_KEY_ENV / TEAM_ID     root endpoint + Prime team billing
#   FEW_SHOT_FLAG=--few-shot             rename escape hatch (see PREFLIGHT)
#   EXEMPLAR_ARGS="--exemplar-k 4"       extra --exemplar-* args, passed verbatim
#                                        (defaults already match: same family, k=2, seed 999)
#   ROOTS="qwen/... anthropic/..."       subset of the roster to run
#   REPAIR=1            re-run the cells' `status: "error"` rows (see below)
#   SKIP_LEAF_PROBE=1   skip the /v1/models check on the leaf endpoint
#   WORKERS=2           Lean REPL pool size (each worker holds Mathlib in RAM)
#
# Success marker: ROSTER_DONE
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LEAF_BASE_URL="${1:-}"
LEAF_MODEL="${2:-deepseek-ai/DeepSeek-Prover-V2-7B}"
LEAF_TEMPLATE="${3:-deepseek-prover-v2-non-cot}"

N="${N:-5}"
MAX_USD="${MAX_USD:-0.75}"
PROBLEMS="${PROBLEMS:-data/families/bridge_chain/k2.jsonl}"
SET="${SET:-bridge_chain}"
BASE_URL="${BASE_URL:-https://api.pinference.ai/api/v1}"
API_KEY_ENV="${API_KEY_ENV:-PRIME_KEY}"
TEAM_ID="${TEAM_ID:-cmsp77l44000710s4dghtmtss}"
FEW_SHOT_FLAG="${FEW_SHOT_FLAG:---few-shot}"
EXEMPLAR_ARGS="${EXEMPLAR_ARGS:-}"
WORKERS="${WORKERS:-2}"
OUT_DIR="${OUT_DIR:-results/zeroshot}"
LOG_DIR="${LOG_DIR:-logs/roster}"
DRY_RUN="${DRY_RUN:-0}"
DIRECT_ONLY="${DIRECT_ONLY:-0}"
SKIP_LEAF_PROBE="${SKIP_LEAF_PROBE:-0}"
# A leaf outage lands on exactly the episodes this diagnostic is about: a plan
# that PASSES stage 1 is the first thing to call the leaf, so a dead endpoint
# turns the positive result into an `error` row — and the resume rule skips
# error rows deliberately (they are recorded events, not holes). REPAIR=1 is the
# explicit re-roll of those rows and nothing else (run_zeroshot.py --repair,
# ../rl's repair_errors.py); measured rows are never re-rolled.
REPAIR="${REPAIR:-0}"
# shellcheck disable=SC2206  # deliberate word-splitting: a command, not a filename
PY=(${PY_CMD:-uv run python})

# The roster, cheapest first: "model|price_in|price_out" ($/Mtok). Order is
# budget insurance — if the plumbing is broken, it breaks on the 0.2/0.8 root,
# not on the 5/25 one. The prices are the roster's, and they are also the budget
# guard's only input; a wrong number here silently disables the cap.
ROSTER=(
  "qwen/qwen3-30b-a3b-instruct-2507|0.2|0.8"   # the RL target (Phase-3 root)
  "Qwen/Qwen3.5-122B-A10B|0.3|0.9"             # 100B-class open model
  "anthropic/claude-haiku-4.5|1|5"
  "anthropic/claude-opus-5|5|25"               # ceiling
)
# The RL target's zero-shot decomp cell is the paired control for its few-shot
# cell: same root, same problems, same scorer, one prompt difference. Without it
# "few-shot assembles" has nothing to be a difference *from* (the existing n=3
# smoke rows live in this same file and are resumed, not re-rolled).
CONTROL_ROOT="qwen/qwen3-30b-a3b-instruct-2507"
CONTROL_PRICES="0.2|0.8"

mkdir -p "$OUT_DIR" "$LOG_DIR"

# ---------------------------------------------------------------------------
# PREFLIGHT — every check that can fail *before* any token is spent
# ---------------------------------------------------------------------------

[ -f "$PROBLEMS" ] || { echo "no problem file: $PROBLEMS" >&2; exit 1; }

if [ "$DRY_RUN" != "1" ] && [ -z "${!API_KEY_ENV:-}" ]; then
  echo "\$$API_KEY_ENV is empty: the root API key must be in that env var." >&2
  echo "  (2026-08-12 lesson: export it from a mode-600 file, not inline —" >&2
  echo "   an env-prefix expansion bug ate the key on the first smoke.)" >&2
  echo "  e.g.  export $API_KEY_ENV=\"\$(cat ~/.prime_key)\"" >&2
  exit 1
fi

# The few-shot flags belong to run_zeroshot.py (sibling task). Assuming they
# exist is fine; assuming *silently* is not — a missing flag would run four
# zero-shot cells that look like the diagnostic and answer a different question.
HELP="$("${PY[@]}" scripts/run_zeroshot.py --help 2>&1 || true)"
case "$HELP" in
  *"$FEW_SHOT_FLAG"*) ;;
  *)
    echo "run_zeroshot.py has no '$FEW_SHOT_FLAG' flag — this roster is the" >&2
    echo "FEW-SHOT diagnostic (DIRECTION §5.5 rung 1.5) and cannot run without it." >&2
    echo "If the flag landed under another name, re-run with FEW_SHOT_FLAG=--its-name." >&2
    exit 2
    ;;
esac
EXEMPLAR_FLAGS="$(printf '%s\n' "$HELP" | grep -o -- '--exemplar-[a-z0-9-]*' | sort -u | tr '\n' ' ')"

if [ "$DIRECT_ONLY" != "1" ] && [ "$DRY_RUN" != "1" ]; then
  [ -n "$LEAF_BASE_URL" ] || {
    echo "usage: bash scripts/run_roster.sh <leaf-base-url> [leaf-model] [leaf-template]" >&2
    echo "  the decomp cells dispatch lemmas to the frozen leaf; pass the endpoint that" >&2
    echo "  is up right now, or set DIRECT_ONLY=1 (direct cells only) / DRY_RUN=1." >&2
    exit 1
  }
  if [ "$SKIP_LEAF_PROBE" != "1" ]; then
    # Fail here, not 40 episodes in: a decomp episode only calls the leaf once
    # its plan passes stage 1, so a dead leaf can stay invisible for a whole
    # cell and then eat exactly the episodes this diagnostic is about.
    curl -s -m 10 "${LEAF_BASE_URL%/}/models" | grep -q '"id"' || {
      echo "leaf endpoint not answering: ${LEAF_BASE_URL%/}/models" >&2
      echo "  (SKIP_LEAF_PROBE=1 to run anyway)" >&2
      exit 1
    }
  fi
fi

# Cell count for the budget banner, computed through the same filters the run
# loop uses — a worst-case figure that ignored ROOTS/DIRECT_ONLY would be a
# scary number for a run that cannot spend it, which is how caps get ignored.
selected_roots=()
for entry in "${ROSTER[@]}"; do
  r="${entry%%|*}"
  if [ -n "${ROOTS:-}" ] && ! printf '%s\n' $ROOTS | grep -qxF "$r"; then continue; fi
  selected_roots+=("$r")
done
[ "${#selected_roots[@]}" -gt 0 ] || { echo "ROOTS filter selected no roster root" >&2; exit 1; }
n_cells=0
for r in "${selected_roots[@]}"; do
  n_cells=$((n_cells + 1))                                        # direct (fs)
  [ "$DIRECT_ONLY" = "1" ] || n_cells=$((n_cells + 1))            # decomp (fs)
  if [ "$r" = "$CONTROL_ROOT" ] && [ "$DIRECT_ONLY" != "1" ]; then
    n_cells=$((n_cells + 1))                                      # zero-shot control
  fi
done

cat >&2 <<BANNER
== roster (DIRECTION §5.5 rung 1.5): ${#selected_roots[@]} root(s) x {direct,decomp} few-shot + zs control
   problems     : $PROBLEMS  (n=$N per cell)
   root endpoint: $BASE_URL   key env: \$$API_KEY_ENV   team: $TEAM_ID
   leaf         : ${LEAF_BASE_URL:-<none: direct-only>}  $LEAF_MODEL  ($LEAF_TEMPLATE)
   few-shot     : $FEW_SHOT_FLAG ${EXEMPLAR_ARGS:-<no --exemplar-* args>}
   exemplar flags seen in --help: ${EXEMPLAR_FLAGS:-<none>}
   per-cell cap : \$$MAX_USD  ->  WORST CASE \$$(awk "BEGIN{printf \"%.2f\", $MAX_USD * $n_cells}") over $n_cells cells
   NB: the caps are per cell. The session-level inference budget is not enforced
       here — watch the provider dashboard if the roster is repeated.
BANNER
[ "$DRY_RUN" = "1" ] && echo "   DRY RUN: resolving cells only" >&2

# ---------------------------------------------------------------------------
# One cell
# ---------------------------------------------------------------------------

FAILED=()

run_cell() {   # run_cell <arm> <root-model> <price-in> <price-out> <fs|zs>
  local arm="$1" root="$2" pin="$3" pout="$4" shot="$5"
  local args=()

  # Cell separation is the runner's: `--few-shot` puts an `fs-` marker on the
  # arm segment of the filename (`..._k2_fs-decomp_<root>.jsonl`), so a few-shot
  # cell can never resume into its zero-shot twin — which is exactly the pair
  # this roster needs to stay intact. Every row also carries `few_shot` and an
  # `exemplar` provenance block, so the analyzer reads the split off columns
  # rather than off a filename convention.
  if [ "$shot" = "fs" ]; then
    args+=("$FEW_SHOT_FLAG")
    # Exemplar defaults already match this roster (family = the cell's family,
    # k=2, dedicated seed 999); EXEMPLAR_ARGS is the override channel.
    # shellcheck disable=SC2206  # deliberate word-splitting of a flag string
    [ -n "$EXEMPLAR_ARGS" ] && args+=(${EXEMPLAR_ARGS})
  fi

  local label="${SET}_${shot}_${arm}_$(printf '%s' "$root" | tr 'A-Z/' 'a-z-' | tr -c 'a-z0-9-' '-')"
  # A dry run leaves no log either: a log file named after a cell is evidence
  # that the cell ran, and this one didn't.
  local log="$LOG_DIR/${label}.log"
  [ "$DRY_RUN" = "1" ] && log=/dev/null

  args+=(
    --problems "$PROBLEMS" --problem-set "$SET" --arm "$arm"
    --root-model "$root" --base-url "$BASE_URL" --api-key-env "$API_KEY_ENV"
    --extra-header "X-Prime-Team-ID=$TEAM_ID"
    --n "$N" --max-usd "$MAX_USD" --price-in "$pin" --price-out "$pout"
    --out-dir "$OUT_DIR" --workers "$WORKERS"
  )
  if [ "$arm" = "decomp" ]; then
    args+=(--leaf-model "$LEAF_MODEL" --leaf-template "$LEAF_TEMPLATE")
    [ -n "$LEAF_BASE_URL" ] && args+=(--leaf-base-url "$LEAF_BASE_URL")
  fi
  [ "$DRY_RUN" = "1" ] && args+=(--dry-run)
  [ "$REPAIR" = "1" ] && args+=(--repair)

  echo "" >&2
  echo "== cell: $shot $arm $root" >&2
  printf '   %s\n' "${PY[*]} scripts/run_zeroshot.py ${args[*]}" >&2

  # A cell is allowed to fail without taking the roster down: a root the
  # provider does not serve, or a model-side 400, must not cost us the other
  # seven cells. The failure is collected and re-reported at the end (and the
  # cell file simply has fewer rows, which the analyzer counts as missing
  # evidence rather than as a measured zero).
  set +e
  "${PY[@]}" scripts/run_zeroshot.py "${args[@]}" 2>&1 | tee -a "$log"
  local rc="${PIPESTATUS[0]}"
  set -e
  if [ "$rc" != "0" ]; then
    echo "   CELL FAILED (exit $rc) — see $log" >&2
    FAILED+=("$shot/$arm/$root (exit $rc)")
  fi
}

# ---------------------------------------------------------------------------
# The roster
# ---------------------------------------------------------------------------

for entry in "${ROSTER[@]}"; do
  root="${entry%%|*}"; rest="${entry#*|}"; pin="${rest%%|*}"; pout="${rest##*|}"
  if ! printf '%s\n' "${selected_roots[@]}" | grep -qxF "$root"; then
    echo "skip (ROOTS filter): $root" >&2
    continue
  fi

  # decomp before direct: decomp *is* the diagnostic (can this root assemble a
  # valid plan at all?); direct is the paired flat baseline on the same rows.
  [ "$DIRECT_ONLY" = "1" ] || run_cell decomp "$root" "$pin" "$pout" fs
  run_cell direct "$root" "$pin" "$pout" fs

  # The zero-shot control rides right behind its few-shot twin so the pair is
  # always measured in the same session, against the same endpoint state.
  if [ "$root" = "$CONTROL_ROOT" ] && [ "$DIRECT_ONLY" != "1" ]; then
    run_cell decomp "$CONTROL_ROOT" "${CONTROL_PRICES%%|*}" "${CONTROL_PRICES##*|}" zs
  fi
done

# ---------------------------------------------------------------------------
# Table + verdict
# ---------------------------------------------------------------------------

if [ "$DRY_RUN" != "1" ]; then
  echo "" >&2
  echo "== roster table + rung-1.5 verdict" >&2
  "${PY[@]}" scripts/roster_analyze.py --results-dir "$OUT_DIR" || true
fi

if [ "${#FAILED[@]}" -gt 0 ]; then
  echo "" >&2
  echo "ROSTER INCOMPLETE — ${#FAILED[@]} cell(s) failed:" >&2
  printf '   %s\n' "${FAILED[@]}" >&2
  echo "A missing cell is missing evidence, not a measured zero: re-run this" >&2
  echo "script (it resumes) before reading any 'no root decomposed' verdict." >&2
  exit 3
fi

echo "ROSTER_DONE"
