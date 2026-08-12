#!/usr/bin/env python
"""Leaf pass-rate bank builder (DIRECTION.md §5.4; Phase 0 artifact, §5.5).

Streams Lean 4 statements from a HuggingFace dataset, elaborates each one, and
measures the frozen leaf prover's pass@k on it. The resulting JSONL is two
things at once: the *delegability oracle* Phase 1 calibrates against, and the
pool from which statements with pass@k in [0.25, 0.9] are mined for the task
families. Measured pass rates are the point — a bank of statements without
them would not support either use.

Usage:
  uv run python scripts/build_bank.py --limit 200 --backend repl --k 8
  uv run python scripts/build_bank.py --limit 2000 --elaborate-only   # cheap: extraction+elaboration rate only
  uv run python scripts/build_bank.py --repair                        # re-run status=="error" rows, nothing else

Resumability is lifted from ../rl/eval/run_eval.py (`existing_ids`): keys already
present in the out file are skipped **including error rows**, so a crashed run
resumes without double-counting and infrastructure errors are retried only when
asked for explicitly (`--repair`, the analog of ../rl/eval/repair_errors.py,
which strips error rows and re-runs exactly those). Silent error retry would
make a bank row's measured pass rate depend on run history — the opposite of
the evidence discipline DIRECTION.md §6 demands.

Seams to concurrently-developed modules (`rlmath.lean`, `rlmath.leaf`) and to
`datasets` are all imported lazily inside `make_backend` / `make_leaf` /
`load_rows`, so this module imports — and its logic unit-tests — with no Lean
toolchain, no network, and no siblings present. Tests inject stubs either by
monkeypatching those three functions or via `--backend fake` plus the
`FAKE_BACKEND_FACTORY` / `FAKE_LEAF_FACTORY` hooks below.

Concurrency (`--concurrent N`, added for the wide candidate sweep — FAMILIES.md
"corridor widening" (1)). N=1 is the sequential path, unchanged. With N>1 up to
N statements are in flight in one thread pool; each in-flight statement runs the
same `process_one` — elaboration check first (cheap, per-statement, before any
generation), then leaf generation, then kernel verification through the SHARED
backend, and finally a single locked writer appends the row and prints the
progress line. Rows therefore land out of dataset order; resume is key-based so
that is safe, and every row carries `slice_index` (its position in this run's
dispatch order) so the sequential order stays reconstructible.

**Which seam gets the lock.** `AttemptCache` is sqlite and single-writer by
contract (leaf/cache.py), so all cache access is serialized behind one
process-wide lock via `_SerializedCache`. That is the finer of the two seams
`leaf/adapter.py` offers, and it is safe *because of how `prove` is written*:
`_attempts` reads the cache, releases it, calls the model, then writes the
attempts; `prove` then kernel-checks each attempt and writes the verdict — no
cache call is ever held across blocking work, and one statement is only ever
touched by one thread (`_dispatch` dedupes keys). So locking the cache calls
alone keeps *both* the HTTP generation (which dominates: PHASE0_NOTES measured
16.3 s/statement end-to-end, ~4 s/attempt inference, against a 36.8k checks/hr
verification ceiling) and the kernel checks parallel. The alternative — a coarse
mutex around `LeafProver.prove` — would additionally have serialized
verification, throwing away the ReplPool's fan-out, and would have forced
generation to be hoisted out of `prove` (via `LeafProver.generate`) to stay
parallel at all, i.e. two behavioural changes for no extra safety.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import sys
import threading
import time
import traceback
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from rlmath.core.leancode import statement_check
from rlmath.core.types import Budgets, Status, normalize_statement, statement_key

ROOT = Path(__file__).resolve().parent.parent

# Dataset facts from research/models-datasets.md §3 (schema verified there by
# downloading and parsing the file, not from the dataset card).
DEFAULT_DATASET = "internlm/Lean-Workbook"
DEFAULT_SPLIT = "train"
# The repo holds TWO files with different schemas: lean_workbook.json is the
# canonical 140,214-row dataset, while wkbk_1009.parquet is a 25,214-row
# tactic-state snapshot that HF's auto-conversion serves to the viewer. Pin the
# canonical one explicitly rather than let `datasets` infer and silently mine a
# third of the corpus at the tactic-state level (--data-files "" to unpin).
DEFAULT_DATA_FILES = "lean_workbook.json"
# First present, non-empty field wins. Both Lean-Workbook files use
# formal_statement (a Lean 4 declaration with `:= by sorry` as its body).
PROP_FIELDS = ("formal_statement", "statement", "theorem_statement", "problem", "lean4_statement")
# The canonical file has no id column (rows fall back to dataset#index); the
# parquet snapshot does. Note `split` in a row is "lean_workbook[_plus]", the
# dataset's own tier, not the HF split --split names.
ID_FIELDS = ("id", "problem_id", "name", "idx", "uuid")

DEFAULT_K = 8                                   # §5.4 mines the bank at pass@8
DEFAULT_TIMEOUT_S = Budgets().verify_timeout_s

# Bank-row status. Reuses the core taxonomy where it applies; ELABORATED is a
# bank-only value because --elaborate-only measures a statement, not an episode
# (no leaf attempt was made, so neither VERIFIED nor LEAF_FAILED is truthful).
STATUS_ELABORATED = "elaborated"

# Test seams (see module docstring). Left None in production; --backend fake errors out.
FAKE_BACKEND_FACTORY: Callable[[], object] | None = None
FAKE_LEAF_FACTORY: Callable[[], object] | None = None
# The two locks --concurrent needs, behind a named factory so a test can supply
# recording locks and *assert* the serialization claims rather than trust them.
LOCK_FACTORY: Callable[[str], object] = lambda name: threading.Lock()  # noqa: E731


# ---------------------------------------------------------------------------
# Statement extraction
# ---------------------------------------------------------------------------

_DECL = re.compile(
    r"^\s*(?:@\[[^\]]*\]\s*)?(?:private\s+|protected\s+|nonrec\s+)*"
    r"(?:theorem|lemma)\s+([A-Za-z_][^\s:({\[⦃]*)\s*"
)
_DECL_KW = re.compile(r"^\s*(?:@\[[^\]]*\]\s*)?(?:theorem|lemma|def|abbrev|example|instance)\b")
_OPEN, _CLOSE = "([{⦃⟨", ")]}⦄⟩"


def _split_signature(rest: str) -> tuple[str, str] | None:
    """Split `<binders> : <conclusion> := <proof>` at the top-level `:` and `:=`.

    Bracket-depth aware, because binder types are full of colons
    (`(hx : 0 < x)`) and so are ∀-telescopes in the conclusion.
    """
    depth, colon, end = 0, -1, len(rest)
    for i, c in enumerate(rest):
        if c in _OPEN:
            depth += 1
        elif c in _CLOSE:
            depth -= 1
            if depth < 0:
                return None
        elif depth == 0 and c == ":":
            if rest[i + 1 : i + 2] == "=":
                if colon < 0:
                    return None  # `:=` before any signature colon — not a theorem header
                end = i
                break
            if colon < 0:
                colon = i
    if colon < 0:
        return None
    return rest[:colon].strip(), rest[colon + 1 : end].strip()


def theorem_to_prop(src: str) -> str | None:
    """Turn a dataset theorem declaration into a closed proposition.

    Lean-Workbook ships `theorem name (x : ℝ) (hx : 0 < x) : x / x = 1 := by sorry`,
    but `leancode.statement_check` wraps a *proposition*: the binders have to be
    re-expressed as a ∀-telescope (`∀ (x : ℝ) (hx : 0 < x), x / x = 1`) or the
    generated snippet does not parse. Returns None when the row cannot be read
    as a declaration or a bare proposition — those are counted, not written, so
    the Phase 0 extraction-failure rate stays measurable.
    """
    s = normalize_statement(src or "")
    if not s:
        return None
    m = _DECL.match(s)
    if not m:
        # Some mirrors store a bare proposition; anything that looks like a
        # declaration but did not parse as one is dropped, not guessed at.
        return None if (":=" in s or _DECL_KW.match(s)) else s
    parts = _split_signature(s[m.end() :])
    if parts is None:
        return None
    binders, concl = parts
    if not concl:
        return None
    return f"∀ {binders}, {concl}" if binders else concl


def extract_prop(row: dict, prop_field: str | None = None) -> str | None:
    fields = (prop_field,) if prop_field else PROP_FIELDS
    for f in fields:
        v = row.get(f)
        if isinstance(v, str) and v.strip():
            return theorem_to_prop(v)
    return None


def source_id(row: dict, dataset: str, index: int) -> str:
    """Provenance for every bank row: which dataset row it came from."""
    for f in ID_FIELDS:
        v = row.get(f)
        if isinstance(v, (str, int)) and str(v).strip():
            return f"{dataset}#{v}"
    return f"{dataset}#{index}"


# ---------------------------------------------------------------------------
# JSONL I/O and resumability (../rl/eval/run_eval.py + repair_errors.py)
# ---------------------------------------------------------------------------

def read_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn last line from a killed run must not abort the resume
    return rows


def existing_keys(path: Path) -> set[str]:
    """statement_keys already recorded — error rows INCLUDED (../rl run_eval.existing_ids)."""
    keys = set()
    for r in read_rows(path):
        k = r.get("statement_key")
        if isinstance(k, str):
            keys.add(k)
    return keys


def split_error_rows(rows: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    """(keep, errors) — the repair partition. Only status=="error" is retried:
    statement_ill_formed / leaf_failed are *measurements*, not failures."""
    keep, errs = [], []
    for r in rows:
        (errs if r.get("status") == Status.ERROR else keep).append(r)
    return keep, errs


def rewrite_rows(path: Path, rows: Sequence[dict]) -> None:
    """Atomically replace the out file (repair drops error rows before re-running)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def append_row(path: Path, row: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Per-statement measurement
# ---------------------------------------------------------------------------

def _attempt_records(res: object) -> list | None:
    """The per-attempt list, if the leaf exposes one (directly, as `.attempts`,
    or as the second element of the adapter's actual `(proof, AttemptList)` return —
    without that case a real bank run would count n_ok as 0-or-1 instead of counting
    verified attempts, and the [0.25, 0.9] band filter would be garbage)."""
    if isinstance(res, tuple) and len(res) == 2 and isinstance(res[1], (list, tuple)):
        seq = res[1]
        return list(seq) if all(hasattr(a, "proof") for a in seq) else None
    if isinstance(res, (list, tuple)):
        return list(res) if all(hasattr(a, "proof") for a in res) else None
    seq = getattr(res, "attempts", None)
    if isinstance(seq, (list, tuple)) and all(hasattr(a, "proof") for a in seq):
        return list(seq)
    return None


def _single_result(res: object, k: int) -> tuple[str | None, int]:
    """(verified proof or None, attempts spent) — harness/episode._leaf_result verbatim,
    including its rule that an unknown attempt count is charged as the full k."""
    if res is None:
        return None, k
    if isinstance(res, str):
        return (res or None), (1 if res else k)
    if isinstance(res, tuple) and len(res) == 2:
        proof, n = res
        if isinstance(n, (list, tuple)):  # leaf adapter's actual contract: list[AttemptRecord]
            n = len(n)
        return (proof or None), (k if n is None else int(n))
    proof = getattr(res, "proof", None)
    if getattr(res, "verified", True) is False:
        proof = None
    n = getattr(res, "attempts_used", None)
    return (proof or None), (k if n is None else int(n))


def summarize_leaf(res: object, k: int) -> tuple[int, int, float | None, str | None]:
    """(n_attempts, n_verified, pass_rate, first_proof) from a leaf `prove` return.

    Accepts the same shapes as harness/episode._leaf_result — that is the
    contract the leaf adapter is written against — but keeps the verified
    *count*: the episode runner only needs first-success, whereas the bank's
    entire product is the measured rate (§5.4).

    Two honesty constraints. pass_rate is None with zero attempts, so an
    unmeasured statement never looks like a measured 0.0 to the [0.25, 0.9]
    band filter. And a leaf that stops at its first success reports
    n_attempts < k, making pass_rate a coarse estimate rather than pass@k —
    ask the leaf for all k attempts when the rate is what you are after.
    """
    records = _attempt_records(res)
    if records is not None:
        verified = [a for a in records if getattr(a, "verified", None)]
        n, n_ok = len(records), len(verified)
        first = getattr(verified[0], "proof", None) if verified else None
    else:
        proof, n = _single_result(res, k)
        n_ok, first = (1, proof) if proof else (0, None)
    return n, n_ok, (n_ok / n if n else None), first


# Lean-Workbook predates Mathlib's big-operator binder migration: it writes
# `∑ k in s, ...` where current Mathlib requires `∑ k ∈ s, ...` (measured on the
# first smoke: 2/12 statements failed elaboration with exactly this error).
# The rewrite is self-validating — it is only kept if the rewritten statement
# actually elaborates, so a false rewrite can never enter the bank.
# ∫ is deliberately absent from the operator class: integral syntax still uses `in`.
_BIGOP_IN = re.compile(r"([∑∏⨆⨅⋃⋂][^,∫]*?)\s+in\s+")


def modernize_bigops(prop: str) -> str:
    """`∑ k in s` → `∑ k ∈ s` (and ∏/⨆/⨅/⋃/⋂), leaving integrals alone."""
    return _BIGOP_IN.sub(r"\1 ∈ ", prop)


def process_one(
    prop: str,
    src_id: str,
    backend,
    leaf,
    *,
    k: int = DEFAULT_K,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """Elaborate, then (if leaf is not None) measure pass@k. Never raises.

    Elaboration policy is `statement_check`'s: ok AND exactly one sorry
    (leancode.statement_check docstring). A statement that elaborates with zero
    sorries would mean the "prop" is not the goal we think it is.
    """
    row = {
        "statement_key": statement_key(prop),
        "prop": prop,
        "source_id": src_id,
        "elaborates": False,
        "n_attempts": 0,
        "n_verified": 0,
        "pass_rate": None,
        "first_proof": None,
        "status": Status.STATEMENT_ILL_FORMED,
        "elapsed_s": 0.0,
        "detail": "",
    }
    t0 = time.perf_counter()
    try:
        res = backend.check(statement_check(prop), timeout_s=timeout_s)
        row["elaborates"] = bool(res.ok and res.sorries == 1)
        if not row["elaborates"]:
            # Retry once with modernized big-operator syntax; keep only if the
            # kernel accepts the rewrite (self-validating, see modernize_bigops).
            fixed = modernize_bigops(prop)
            if fixed != prop:
                res2 = backend.check(statement_check(fixed), timeout_s=timeout_s)
                if res2.ok and res2.sorries == 1:
                    prop = fixed
                    row.update(
                        prop=fixed,
                        statement_key=statement_key(fixed),
                        elaborates=True,
                        detail="modernized big-operator binder (in -> ∈)",
                    )
                res = res2  # either way: res2's error is the actionable one post-rewrite
        if not row["elaborates"]:
            row["detail"] = "; ".join(m.text for m in res.errors)[:500] or f"sorries={res.sorries}"
        elif leaf is None:
            row["status"] = STATUS_ELABORATED
        else:
            # harness/episode.LeafProver protocol: the leaf verifies its own
            # candidates through the backend (it owns the statement-keyed cache).
            # early_stop=False: the bank's product is the measured rate, so all
            # k attempts must be checked — first-success sampling would bias
            # pass_rate upward exactly on the easy statements (summarize_leaf docstring).
            n, n_ok, rate, first = summarize_leaf(
                leaf.prove(prop, k=k, backend=backend, early_stop=False), k
            )
            row.update(
                n_attempts=n, n_verified=n_ok, pass_rate=rate, first_proof=first,
                status=Status.VERIFIED if n_ok else Status.LEAF_FAILED,
            )
    except Exception as e:
        row["status"] = Status.ERROR
        row["detail"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}"
    row["elapsed_s"] = round(time.perf_counter() - t0, 3)
    return row


# ---------------------------------------------------------------------------
# Lazy construction seams
# ---------------------------------------------------------------------------

def make_backend(args):
    """Construct the Lean backend through rlmath.lean's factory — the one place
    a backend name becomes a `LeanBackend`. Lazy: it assumes a toolchain/server."""
    if args.backend == "fake":
        if FAKE_BACKEND_FACTORY is None:
            raise SystemExit("--backend fake requires FAKE_BACKEND_FACTORY (tests only)")
        return FAKE_BACKEND_FACTORY()
    from rlmath.lean import get_backend

    kw = {"n_workers": args.workers} if args.backend == "repl" else {"base_url": args.kimina_url}
    return get_backend(args.backend, **kw)


def make_leaf(args):
    """Construct the frozen leaf prover (DIRECTION.md §5.3). The backend is not
    a constructor arg — `LeafProver.prove` takes it per call (harness/episode)."""
    if args.backend == "fake":
        if FAKE_LEAF_FACTORY is None:
            raise SystemExit("--backend fake requires FAKE_LEAF_FACTORY (tests only)")
        return FAKE_LEAF_FACTORY()
    import os

    from rlmath.leaf import LeafProver
    from rlmath.leaf.cache import AttemptCache

    # Cache is what makes the bank resumable at the attempt level (repeated
    # statements do zero generation/kernel work on re-runs) — always on here.
    kw = {}
    if args.leaf_max_tokens is not None:
        kw["max_tokens"] = args.leaf_max_tokens
    if args.leaf_temperature is not None:
        kw["temperature"] = args.leaf_temperature
    return LeafProver.from_openai(
        base_url=args.leaf_base_url,
        api_key=os.environ.get("LEAF_API_KEY", "EMPTY"),
        model=args.leaf_model,
        template=args.leaf_template,
        cache=AttemptCache(),
        **kw,
    )


class _SerializedCache:
    """One lock around every `AttemptCache` call (see the module docstring).

    Delegation is total rather than a hand-listed method set: the cache is
    another agent's module, and a method added there must not silently escape
    the lock. Non-callable attributes (`.path`) pass through unwrapped — they
    touch no sqlite. The wrapped object's own methods never re-enter this proxy,
    so a plain (non-reentrant) lock cannot deadlock.
    """

    def __init__(self, cache: object, lock) -> None:
        self._cache = cache
        self._lock = lock

    def __getattr__(self, name: str):
        attr = getattr(self._cache, name)
        if not callable(attr):
            return attr

        def locked(*a, **kw):
            with self._lock:
                return attr(*a, **kw)

        return locked


def load_rows(args) -> Iterator[dict]:
    """Stream the dataset. Shuffle (if --seed) happens BEFORE the --limit slice,
    so a limited run is a deterministic random sample rather than the head of
    the file — the head of Lean-Workbook is not representative of its tail."""
    from datasets import load_dataset

    kw = {"data_files": args.data_files} if args.data_files else {}
    ds = load_dataset(args.dataset, split=args.split, streaming=True, **kw)
    if args.seed is not None:
        ds = ds.shuffle(seed=args.seed, buffer_size=args.shuffle_buffer)
    it: Iterator[dict] = iter(ds)
    if args.limit is not None:
        it = itertools.islice(it, args.limit)
    return it


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Build the leaf pass-rate bank (DIRECTION.md §5.4).")
    p.add_argument("--dataset", default=DEFAULT_DATASET)
    p.add_argument("--split", default=DEFAULT_SPLIT)
    p.add_argument(
        "--data-files",
        default=DEFAULT_DATA_FILES,
        help=f"file within the dataset repo (default {DEFAULT_DATA_FILES}, the canonical "
             "140k-row Lean-Workbook; empty string lets `datasets` infer)",
    )
    p.add_argument("--prop-field", default=None, help=f"override statement field (tried: {', '.join(PROP_FIELDS)})")
    p.add_argument("--limit", type=int, default=None, help="max dataset rows to consider")
    p.add_argument("--seed", type=int, default=None, help="shuffle seed, applied before --limit")
    p.add_argument("--shuffle-buffer", type=int, default=10_000)
    p.add_argument("--out", type=Path, default=ROOT / "data" / "bank" / "bank.jsonl")
    p.add_argument("--backend", choices=["repl", "kimina", "fake"], default="repl")
    p.add_argument("--kimina-url", default=None, help="default: $RLMATH_KIMINA_URL, then the client default")
    p.add_argument("--workers", type=int, default=4, help="REPL pool size")
    p.add_argument("--leaf-base-url", default="http://localhost:11434/v1")
    p.add_argument("--leaf-model", default=None)
    p.add_argument("--leaf-template", default=None, help="template name from rlmath.leaf.prompts.TEMPLATES")
    # CoT-style templates (goedel-prover-v2, deepseek CoT) generate 8-32k tokens;
    # the adapter default (2048) silently truncates them into parse failures.
    # Both knobs enter the cache sampling_key, so overriding them correctly
    # separates cache populations (leaf/adapter.py flag 5).
    p.add_argument("--leaf-max-tokens", type=int, default=None, help="override adapter DEFAULT_MAX_TOKENS")
    p.add_argument("--leaf-temperature", type=float, default=None, help="override adapter DEFAULT_TEMPERATURE")
    p.add_argument("--k", type=int, default=DEFAULT_K, help="leaf attempts per statement (pass@k)")
    p.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S)
    p.add_argument("--elaborate-only", action="store_true", help="skip the leaf prover")
    p.add_argument(
        "--concurrent",
        type=int,
        default=1,
        help="statements in flight (default 1 = sequential). >1 parallelizes leaf generation, "
             "the dominant cost; verification parallelism is still bounded by --workers",
    )
    p.add_argument(
        "--repair",
        action="store_true",
        help="re-run only rows whose status=='error' (drops them from --out first); ignores the dataset",
    )
    return p.parse_args(argv)


def _repair_targets(out: Path) -> list[tuple[str, str]]:
    """Error rows carry their own prop/source_id, so repair needs no dataset stream."""
    keep, errs = split_error_rows(read_rows(out))
    if errs:
        rewrite_rows(out, keep)
    return [(r["prop"], r.get("source_id", "")) for r in errs if r.get("prop")]


def _candidates(args) -> Iterator[tuple[str, str]]:
    """(prop, source_id) pairs from the dataset, minus unextractable rows."""
    n_skipped = 0
    for i, row in enumerate(load_rows(args)):
        prop = extract_prop(row, args.prop_field)
        if not prop:
            n_skipped += 1
            continue
        yield prop, source_id(row, args.dataset, i)
    if n_skipped:
        print(f"note: {n_skipped} rows had no extractable statement", file=sys.stderr)


def _dispatch(targets: Iterable[tuple[str, str]], done: set[str]) -> Iterator[tuple[int, str, str]]:
    """(slice_index, prop, source_id) for the statements this run will measure.

    The single place resume-skipping and in-run deduplication happen, shared by
    both modes so N=1 keeps exactly its old semantics. `slice_index` counts only
    dispatched statements, so it is the order the sequential path would have
    written them in — per run, not globally (a resumed run starts at 0 again;
    the row key, not the index, is the identity).
    """
    i = 0
    for prop, src_id in targets:
        key = statement_key(prop)
        if key in done:
            continue
        done.add(key)  # the dataset itself contains duplicate statements
        yield i, prop, src_id
        i += 1


class _Writer:
    """The single appender: one lock covers append_row + counters + progress line.

    Under --concurrent that lock is what keeps two rows from interleaving inside
    one JSONL line and the `[n]` counter from repeating. At N=1 it is an
    uncontended no-op and the sequential path is what it was, with one addition:
    `slice_index` is written in BOTH modes on purpose. A bank file must not have
    two row schemas depending on a flag — "which rows came from the concurrent
    path" is exactly the hidden variable DIRECTION.md §6's evidence discipline
    forbids, and rows predating this flag are already handled by `.get()`.
    """

    def __init__(self, out: Path, leaf_id: str | None, lock, *, show_slice: bool) -> None:
        self.out = out
        self.leaf_id = leaf_id
        self.lock = lock
        self.show_slice = show_slice
        self.counts: dict[str, int] = {}
        self.n_done = 0

    def emit(self, slice_index: int, row: dict) -> None:
        row["leaf_id"] = self.leaf_id
        row["slice_index"] = slice_index
        with self.lock:
            append_row(self.out, row)
            self.counts[row["status"]] = self.counts.get(row["status"], 0) + 1
            self.n_done += 1
            slice_note = f" slice={slice_index}" if self.show_slice else ""
            print(
                f"[{self.n_done}] {row['statement_key']} status={row['status']} "
                f"pass_rate={row['pass_rate']} elapsed={row['elapsed_s']}s{slice_note}",
                file=sys.stderr,
            )


def _run_concurrent(work: Iterator[tuple[int, str, str]], writer: _Writer, backend, leaf, args) -> None:
    """Bounded pipeline: never more than --concurrent statements in flight.

    Bounded because the dataset is streamed (140k rows) — submitting everything
    would materialize the whole slice and queue thousands of futures against a
    pool that can only run N. Refill-on-first-completion keeps all N busy.
    """

    def task(item: tuple[int, str, str]) -> None:
        idx, prop, src_id = item
        writer.emit(
            idx, process_one(prop, src_id, backend, leaf, k=args.k, timeout_s=args.timeout_s)
        )

    pending: set = set()
    exhausted = False
    with ThreadPoolExecutor(max_workers=args.concurrent, thread_name_prefix="bank") as pool:
        while True:
            while not exhausted and len(pending) < args.concurrent:
                item = next(work, None)
                if item is None:
                    exhausted = True
                    break
                pending.add(pool.submit(task, item))
            if not pending:
                return
            finished, pending = wait(pending, return_when=FIRST_COMPLETED)
            for f in finished:
                f.result()  # process_one never raises; this surfaces writer/IO failures


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.concurrent < 1:
        raise SystemExit("--concurrent must be >= 1")
    out: Path = args.out
    out.parent.mkdir(parents=True, exist_ok=True)

    done: set[str] = set()
    targets: Iterable[tuple[str, str]]
    if args.repair:
        targets = _repair_targets(out)
        print(f"repair: {len(targets)} error rows -> re-running", file=sys.stderr)
    else:
        done = existing_keys(out)
        targets = _candidates(args)
        print(f"bank: {out} ({len(done)} rows already present, skipped including errors)", file=sys.stderr)

    backend = make_backend(args)
    leaf = None if args.elaborate_only else make_leaf(args)

    # Leaf provenance guard: bank pass rates ARE the delegability oracle
    # (DIRECTION.md §5.4) — a file silently mixing leaf models would corrupt it
    # invisibly. Every leaf row records its model; appending with a different
    # model than the file already contains is a hard refusal, not a warning.
    # leaf_id carries the full sampling profile, not just model|template: the
    # 2026-08-12 bake-off showed max_tokens changes the measured population
    # (a 16k-CoT attempt and an 8k-capped attempt are different experiments).
    _mt = args.leaf_max_tokens if args.leaf_max_tokens is not None else "def"
    _tp = args.leaf_temperature if args.leaf_temperature is not None else "def"
    leaf_id = None if args.elaborate_only else (
        f"{args.leaf_model}|{args.leaf_template}|M{_mt}|T{_tp}"
    )
    if leaf_id is not None:
        prior = {r.get("leaf_id") for r in read_rows(out) if r.get("leaf_id")}
        if prior and prior != {leaf_id}:
            raise SystemExit(
                f"refusing to mix leaf models in one bank file: {out} already has "
                f"{sorted(prior)}, this run is {leaf_id!r}. Use a separate --out "
                f"(stand-in numbers must never leak into the oracle bank)."
            )

    # Cache access is serialized for the whole run (module docstring: "which seam
    # gets the lock"). Only under --concurrent: at N=1 there is nothing to
    # serialize and the wrapper would be dead weight on every attempt.
    if args.concurrent > 1 and getattr(leaf, "cache", None) is not None:
        leaf.cache = _SerializedCache(leaf.cache, LOCK_FACTORY("cache"))

    writer = _Writer(out, leaf_id, LOCK_FACTORY("writer"), show_slice=args.concurrent > 1)
    work = _dispatch(targets, done)
    try:
        if args.concurrent > 1:
            _run_concurrent(work, writer, backend, leaf, args)
        else:
            for idx, prop, src_id in work:
                writer.emit(
                    idx, process_one(prop, src_id, backend, leaf, k=args.k, timeout_s=args.timeout_s)
                )
    finally:
        backend.close()

    counts, n_done = writer.counts, writer.n_done
    n_ill = counts.get(Status.STATEMENT_ILL_FORMED, 0)
    rate = f"{n_ill / n_done:.1%}" if n_done else "n/a"
    print(
        f"done: {n_done} rows written; " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        + f"\nelaboration failure rate: {rate} (Phase 0 gate: <5%, PHASE0_NOTES.md)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
