"""SQLite cache of leaf-prover attempts and their kernel verdicts.

Why (DIRECTION.md §5.6): "Leaf calls cached and deduped across the GRPO group.
Convenient side effect: degenerate restatement policies hit cache, so they cost
almost nothing to observe." The cache is therefore not just a speed knob — it is
what makes the degenerate-recursion measurement (§3.3 objection 2) affordable,
and what makes the Phase-0 leaf bank build resumable in the same way ../rl's
`run_eval.py` was (skip ids already present, including error rows; explicit
repair pass for the rest).

Rows are keyed by (statement_key, model, sampling_key, idx):
  * `statement_key`  — `core.types.statement_key`, i.e. sha256 of the
    whitespace/comment-normalized proposition. NOT α-normalized (v1 limitation,
    recorded in PHASE0_NOTES).
  * `sampling_key`   — template + decoding parameters (see
    `LeafProver.sampling_key`). Attempts made under different sampling settings
    are different populations and must never be pooled into one pass@k.
  * `idx`            — sample index within that population; makes a top-up from
    k=4 to k=8 add exactly four generations.
  * `verified`       — NULL until the kernel has ruled, then 0/1. NULL vs 0 is
    the same evidence separation the status taxonomy enforces elsewhere:
    "not checked" is not "checked and failed".

**Concurrency: single writer.** SQLite would serialize writers anyway, but the
discipline is deliberate — ../rl's REPORT_NOTES accommodation 2 records a
stateful component that raced under threads and cost a whole set of runs
(archived, never analyzed). Readers are safe alongside the writer (WAL is
enabled); a second *writing* process is out of contract. An instance is
mutex-guarded so a thread pool inside one process is safe.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ..core.types import AttemptRecord

DEFAULT_CACHE_PATH = Path("cache/leaf.sqlite")

SCHEMA = """
CREATE TABLE IF NOT EXISTS attempts (
    statement_key TEXT NOT NULL,
    model         TEXT NOT NULL,
    sampling_key  TEXT NOT NULL,
    idx           INTEGER NOT NULL,
    proof         TEXT NOT NULL,
    verified      INTEGER,
    PRIMARY KEY (statement_key, model, sampling_key, idx)
);
"""


class AttemptCache:
    """Attempt store. One writer process; see the module docstring."""

    def __init__(self, path: str | Path = DEFAULT_CACHE_PATH) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False + a mutex: the harness may fan leaf calls out
        # over a thread pool within the single writer process.
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=30.0)
        self._lock = threading.Lock()
        with self._lock:
            if self.path != ":memory:":
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.executescript(SCHEMA)
            self._db.commit()

    # -- reads ---------------------------------------------------------------

    def get_attempts(self, statement_key: str, model: str, sampling_key: str) -> list[AttemptRecord]:
        """All stored attempts for one (statement, model, sampling) population,
        ordered by index. An empty `proof` marks a completion that did not
        parse — see `LeafProver.generate`."""
        with self._lock:
            rows = self._db.execute(
                "SELECT idx, proof, verified FROM attempts"
                " WHERE statement_key=? AND model=? AND sampling_key=? ORDER BY idx",
                (statement_key, model, sampling_key),
            ).fetchall()
        return [
            AttemptRecord(
                statement_key=statement_key,
                model=model,
                index=idx,
                proof=proof,
                verified=None if verified is None else bool(verified),
            )
            for idx, proof, verified in rows
        ]

    def count(self, statement_key: str | None = None) -> int:
        """Row count, total or for one statement. Used by bank/throughput reporting."""
        with self._lock:
            if statement_key is None:
                (n,) = self._db.execute("SELECT count(*) FROM attempts").fetchone()
            else:
                (n,) = self._db.execute(
                    "SELECT count(*) FROM attempts WHERE statement_key=?", (statement_key,)
                ).fetchone()
        return int(n)

    # -- writes --------------------------------------------------------------

    def put_attempt(
        self,
        statement_key: str,
        model: str,
        sampling_key: str,
        idx: int,
        proof: str,
        verified: bool | None = None,
    ) -> None:
        """Insert or overwrite one attempt. Overwrite (rather than ignore) so a
        deliberate re-generation of a slot also resets its stale verdict."""
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO attempts"
                " (statement_key, model, sampling_key, idx, proof, verified) VALUES (?,?,?,?,?,?)",
                (statement_key, model, sampling_key, idx, proof,
                 None if verified is None else int(verified)),
            )
            self._db.commit()

    def mark_verified(
        self, statement_key: str, model: str, sampling_key: str, idx: int, verified: bool
    ) -> bool:
        """Record the kernel's verdict for one attempt. Returns False if no such
        attempt is stored — a caller marking a slot it never stored has a bug,
        and a silent no-op would hide it."""
        with self._lock:
            cur = self._db.execute(
                "UPDATE attempts SET verified=? WHERE statement_key=? AND model=?"
                " AND sampling_key=? AND idx=?",
                (int(verified), statement_key, model, sampling_key, idx),
            )
            self._db.commit()
            return cur.rowcount > 0

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> AttemptCache:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
