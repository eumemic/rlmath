"""Local `leanprover-community/repl` worker pool — the macOS-native LeanBackend.

Why a pool of long-lived processes rather than one `lake env repl` per check:
`import Mathlib` costs ~30 s of olean loading, a warm command costs seconds.
Phase 0's gate is ≥2–3k verified leaf attempts/hour (DIRECTION.md §5.5), which
is unreachable at one cold import per attempt. So each worker imports once, the
returned environment id is retained, and every subsequent `cmd` elaborates on
top of it. Kimina Lean Server does the same thing behind HTTP; this is the
process-local equivalent for a box without docker (PHASE0_NOTES, backend-order
decision).

Protocol (verified against repl master — see research/lean-repl.md):
  * one compact JSON object + a blank line per request on stdin;
  * one JSON line + an explicitly flushed blank line per response on stdout;
  * `{"cmd": ..., "env": N}` elaborates on environment N; omitting `env` makes
    a fresh one, and that is the only place `import` is legal;
  * empty `messages`/`sorries` lists are *omitted* from the JSON, so a clean
    command answers with exactly `{"env": N}`;
  * unparseable input answers `{"message": "Could not parse ..."}` — an Error
    object with no `env`, which we map to a hard failure (a response carrying
    no messages would otherwise read as ok=True).

Concurrency discipline (../rl operational lesson, DIRECTION.md §6): the REPL is
a stateful single-threaded process, so exactly one command may be in flight per
worker. The pool hands a worker out of an idle queue and takes it back; a
worker never sees two callers at once. This is the same hazard class as `../rl`'s
`LocalREPL` process-wide `os.chdir` race, handled structurally instead of by
convention.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from rlmath.core.leancode import PREAMBLE
from rlmath.core.types import LeanMessage, VerifyResult

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROJECT_DIR = REPO_ROOT / "lean" / "rlmathlib"
DEFAULT_REPL_BIN = REPO_ROOT / "lean" / "repl" / ".lake" / "build" / "bin" / "repl"

_ELAN_BIN = Path.home() / ".elan" / "bin"


class ReplBroken(RuntimeError):
    """Worker is unusable: timed out, died, or answered garbage. Always fatal to
    the *process* (we kill and respawn) because a late reply from a timed-out
    command would desynchronize the request/response stream forever."""


def _resolve(p: Path | str) -> Path:
    """Relative paths are repo-root-relative, so a config literal means the same
    thing regardless of the caller's cwd (scripts run from anywhere)."""
    q = Path(p).expanduser()
    return q if q.is_absolute() else (REPO_ROOT / q)


@dataclass
class ReplConfig:
    """Where the toolchain is and how hard to push it.

    Defaults match scripts/setup_lean.sh's layout, so `ReplPool()` with no
    arguments is the working configuration on this box.
    """

    project_dir: Path = DEFAULT_PROJECT_DIR
    repl_bin: Path = DEFAULT_REPL_BIN
    n_workers: int = 2            # each worker holds a full Mathlib environment (GBs of RSS)
    recycle_after: int = 200      # commands per process; REPL memory grows monotonically
    startup_timeout_s: float = 300.0   # cold `import Mathlib` is ~30 s warm-cache, minutes cold
    lake_bin: str = "lake"
    argv_override: tuple[str, ...] | None = None   # tests / non-lake invocations

    def __post_init__(self) -> None:
        self.project_dir = _resolve(self.project_dir)
        self.repl_bin = _resolve(self.repl_bin)
        if self.n_workers < 1:
            raise ValueError("n_workers must be >= 1")
        if self.recycle_after < 1:
            raise ValueError("recycle_after must be >= 1")

    @property
    def argv(self) -> list[str]:
        """`lake env <repl>` runs the (separately built) repl binary with the
        project's LEAN_PATH, which is what makes `import Mathlib` resolve
        (research/lean-repl.md §3; scripts/setup_lean.sh builds both halves)."""
        if self.argv_override is not None:
            return list(self.argv_override)
        return [self.lake_bin, "env", str(self.repl_bin)]

    def available(self) -> bool:
        """Is there something to talk to? Integration tests skip on this rather
        than failing, since setup_lean.sh takes hours on a cold checkout."""
        return self.project_dir.is_dir() and (self.argv_override is not None or self.repl_bin.exists())


class ReplTransport(Protocol):
    """The subprocess seam. Unit tests substitute a scripted object so the whole
    framing/timeout/recycle state machine is exercised without a Lean toolchain."""

    def write(self, data: str) -> None: ...
    def readline(self) -> str: ...     # "" == EOF
    def kill(self) -> None: ...
    def poll(self) -> int | None: ...  # None while alive


class SubprocessTransport:
    """`lake env repl` as a line-oriented pipe pair."""

    def __init__(self, cfg: ReplConfig) -> None:
        self._stderr_tail: deque[str] = deque(maxlen=40)
        try:
            self.proc = subprocess.Popen(
                cfg.argv,
                cwd=str(cfg.project_dir),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                # Lean speaks UTF-8 (goals are full of ⊢, ℕ, ∀) regardless of the
                # parent's locale; decoding by locale would corrupt goal text on a
                # box with LANG unset. Requests are ASCII-escaped by json.dumps.
                encoding="utf-8",
                errors="replace",
                env=_child_env(),
            )
        except OSError as e:  # missing lake / missing binary — the common setup failure
            raise ReplBroken(f"cannot spawn {cfg.argv!r} in {cfg.project_dir}: {e}") from e
        # stderr must be drained or a chatty toolchain fills the pipe and wedges
        # the child; keeping a tail turns "it just died" into a usable message.
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    def _drain_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self._stderr_tail.append(line.rstrip("\n"))

    def write(self, data: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def readline(self) -> str:
        assert self.proc.stdout is not None
        return self.proc.stdout.readline()

    def kill(self) -> None:
        try:
            self.proc.kill()
            self.proc.wait(timeout=10)
        except Exception:
            pass
        for pipe in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            try:
                if pipe is not None:
                    pipe.close()
            except Exception:
                pass

    def poll(self) -> int | None:
        return self.proc.poll()

    def diagnostics(self) -> str:
        return " | ".join(self._stderr_tail)


def _child_env() -> dict[str, str]:
    """elan installs `lake` outside the default PATH of a GUI-launched process;
    prepend it so the pool works from editors and daemons, not just a shell."""
    env = dict(os.environ)
    if _ELAN_BIN.is_dir():
        env["PATH"] = f"{_ELAN_BIN}{os.pathsep}{env.get('PATH', '')}"
    return env


def _diagnostics(t: ReplTransport | None) -> str:
    fn = getattr(t, "diagnostics", None)
    return fn() if callable(fn) else ""


def to_result(resp: dict, elapsed_s: float) -> VerifyResult:
    """CommandResponse -> VerifyResult.

    `ok` is "no error-severity message", never "no sorries": sorry policy is the
    caller's (core/types.py VerifyResult docstring — statement elaboration wants
    exactly one, proof checks want zero). A `sorry` only ever produces a
    *warning* ("declaration uses 'sorry'"), so both stay independent.
    """
    messages: list[LeanMessage] = []
    for m in resp.get("messages") or []:
        pos = m.get("pos") or {}
        messages.append(
            LeanMessage(
                severity=str(m.get("severity", "info")),
                text=str(m.get("data", "")),
                line=pos.get("line"),
                col=pos.get("column"),
            )
        )
    if "env" not in resp and "message" in resp:
        # Error object (§2.6): unparseable request. No messages list, so without
        # this it would score as a clean success.
        messages.append(LeanMessage("error", f"repl error: {resp['message']}"))
    return VerifyResult(
        ok=not any(m.severity == "error" for m in messages),
        messages=messages,
        sorries=len(resp.get("sorries") or []),
        elapsed_s=elapsed_s,
        env_id=resp.get("env"),
        raw=resp,
    )


def _failure(text: str, elapsed_s: float) -> VerifyResult:
    return VerifyResult(ok=False, messages=[LeanMessage("error", text)], elapsed_s=elapsed_s)


class ReplWorker:
    """One repl process plus its warm Mathlib environment.

    Not thread-safe by accident — it holds a lock, but the pool is what
    guarantees a single in-flight command; the lock only keeps a stray direct
    caller from corrupting the stream.
    """

    def __init__(
        self,
        cfg: ReplConfig | None = None,
        *,
        transport_factory: Callable[[ReplConfig], ReplTransport] | None = None,
        name: str = "repl",
    ) -> None:
        self.cfg = cfg or ReplConfig()
        self.name = name
        self._new_transport = transport_factory or SubprocessTransport
        self._t: ReplTransport | None = None
        self._lock = threading.Lock()
        self._lines: queue.Queue[str] | None = None
        self._env_id: int | None = None
        self._commands = 0
        self.spawns = 0

    # --- lifecycle -----------------------------------------------------------

    @property
    def env_id(self) -> int | None:
        """Environment id returned by the preamble import; every check reuses it."""
        return self._env_id

    @property
    def commands_since_spawn(self) -> int:
        return self._commands

    def _teardown(self) -> None:
        if self._t is not None:
            self._t.kill()
        # A stale reader thread keeps draining the *old* queue and exits at EOF;
        # binding a fresh queue per spawn is what makes that harmless.
        self._t = None
        self._lines = None
        self._env_id = None
        self._commands = 0

    def _spawn(self) -> None:
        self._teardown()
        t = self._new_transport(self.cfg)
        self._t = t
        lines: queue.Queue[str] = queue.Queue()
        self._lines = lines
        self.spawns += 1
        threading.Thread(
            target=self._read_loop, args=(t, lines), name=f"{self.name}-reader", daemon=True
        ).start()
        resp = self._roundtrip({"cmd": PREAMBLE.strip()}, self.cfg.startup_timeout_s)
        env = resp.get("env")
        errs = [m for m in (resp.get("messages") or []) if m.get("severity") == "error"]
        if env is None or errs:
            detail = errs[0].get("data", "") if errs else resp.get("message", str(resp)[:200])
            self._teardown()
            raise ReplBroken(f"preamble import failed: {detail}")
        self._env_id = int(env)

    @staticmethod
    def _read_loop(t: ReplTransport, lines: queue.Queue[str]) -> None:
        try:
            while True:
                line = t.readline()
                lines.put(line)
                if line == "":  # EOF: process gone
                    return
        except Exception:
            lines.put("")

    def _ensure_ready(self) -> None:
        dead = self._t is None or self._t.poll() is not None
        # Recycling is lazy — checked before a command rather than eagerly after
        # the threshold one — so a pool about to be closed never pays for an
        # import it will not use.
        if dead or self._commands >= self.cfg.recycle_after:
            self._spawn()

    # --- one request/response round trip -------------------------------------

    def _roundtrip(self, payload: dict, timeout_s: float) -> dict:
        assert self._t is not None and self._lines is not None
        try:
            self._t.write(json.dumps(payload) + "\n\n")
        except Exception as e:
            raise ReplBroken(f"write failed: {e}") from e
        raw = self._read_frame(time.monotonic() + timeout_s)
        try:
            resp = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ReplBroken(f"unparseable response {raw[:200]!r}: {e}") from e
        if not isinstance(resp, dict):
            raise ReplBroken(f"non-object response {raw[:200]!r}")
        return resp

    def _read_frame(self, deadline: float) -> str:
        """Read until the blank line that terminates a response.

        The watchdog is the deadline on each queue pop: the reader thread does
        the blocking I/O, so a wedged Lean elaboration cannot pin the caller.
        """
        parts: list[str] = []
        assert self._lines is not None
        lines = self._lines
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ReplBroken(f"no response within timeout ({''.join(parts)[:120]!r} so far)")
            try:
                line = lines.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            if line == "":
                raise ReplBroken(f"process exited mid-command ({_diagnostics(self._t)})")
            if line.strip() == "":
                if parts:
                    return "".join(parts)
                continue  # leading blank line (e.g. flush artifact): not a frame
            if not parts and not line.lstrip().startswith("{"):
                # `lake env` occasionally prints toolchain chatter on stdout
                # before the child's first response. Every repl reply is a JSON
                # *object*, so anything else outside a frame is noise; swallowing
                # it here keeps a fresh checkout's first command from failing.
                continue
            parts.append(line.rstrip("\n"))

    # --- public API ----------------------------------------------------------

    def check(self, code: str, *, timeout_s: float = 120.0) -> VerifyResult:
        """Elaborate `code` on the warm environment. Never raises: a broken
        worker is a failed *result*, because a Phase-0 bank run of thousands of
        statements must not die on one wedged elaboration (../rl resumability
        discipline — errors are rows, not crashes)."""
        t0 = time.monotonic()
        with self._lock:
            try:
                self._ensure_ready()
            except Exception as e:  # includes a transport factory that cannot spawn at all
                self._teardown()
                return _failure(f"repl timeout/restart: startup failed: {e}", time.monotonic() - t0)
            payload: dict = {"cmd": code}
            if self._env_id is not None:
                payload["env"] = self._env_id
            try:
                resp = self._roundtrip(payload, timeout_s)
            except Exception as e:
                # Kill, don't reuse: the answer to this command may still be
                # coming and would be read as the answer to the next one.
                self._teardown()
                return _failure(f"repl timeout/restart: {e}", time.monotonic() - t0)
            self._commands += 1
            return to_result(resp, time.monotonic() - t0)

    def close(self) -> None:
        with self._lock:
            self._teardown()


class ReplPool:
    """`LeanBackend` over N warm workers (core/backend.py).

    Workers are spawned lazily on first use — constructing a pool must stay free
    so `--elaborate-only` style runs and `--help` never wait on Mathlib.
    """

    def __init__(
        self,
        config: ReplConfig | None = None,
        *,
        transport_factory: Callable[[ReplConfig], ReplTransport] | None = None,
        **config_kwargs,
    ) -> None:
        if config is not None and config_kwargs:
            raise TypeError("pass either a ReplConfig or its fields as kwargs, not both")
        self.cfg = config or ReplConfig(**config_kwargs)
        self.workers = [
            ReplWorker(self.cfg, transport_factory=transport_factory, name=f"repl{i}")
            for i in range(self.cfg.n_workers)
        ]
        self._idle: queue.Queue[ReplWorker] = queue.Queue()
        for w in self.workers:
            self._idle.put(w)
        self._pool: ThreadPoolExecutor | None = None
        self._closed = False

    def _executor(self) -> ThreadPoolExecutor:
        if self._pool is None:
            self._pool = ThreadPoolExecutor(
                max_workers=self.cfg.n_workers, thread_name_prefix="replpool"
            )
        return self._pool

    def check(self, code: str, *, timeout_s: float = 120.0) -> VerifyResult:
        if self._closed:
            raise RuntimeError("ReplPool is closed")
        worker = self._idle.get()
        try:
            return worker.check(code, timeout_s=timeout_s)
        finally:
            self._idle.put(worker)

    def check_many(self, codes: Sequence[str], *, timeout_s: float = 120.0) -> list[VerifyResult]:
        """Order-preserving fan-out. Exactly n_workers threads run against
        exactly n_workers workers, so no task can starve waiting for one."""
        codes = list(codes)
        if not codes:
            return []
        if len(codes) == 1 or self.cfg.n_workers == 1:
            return [self.check(c, timeout_s=timeout_s) for c in codes]
        futs = [self._executor().submit(self.check, c, timeout_s=timeout_s) for c in codes]
        return [f.result() for f in futs]

    def warm(self) -> list[VerifyResult]:
        """Import Mathlib in every worker, in parallel.

        Not `check_many` of N trivial commands: nothing stops one fast worker
        from taking two of those. This takes every worker out of the idle queue
        so each one provably pays its own import — which is what a throughput
        measurement (Phase 0 gate, DIRECTION.md §5.5) needs before it starts
        timing anything.
        """
        if self._closed:
            raise RuntimeError("ReplPool is closed")
        held = [self._idle.get() for _ in self.workers]
        try:
            futs = [
                self._executor().submit(
                    w.check, "example : True := trivial", timeout_s=self.cfg.startup_timeout_s
                )
                for w in held
            ]
            return [f.result() for f in futs]
        finally:
            for w in held:
                self._idle.put(w)

    def close(self) -> None:
        self._closed = True
        if self._pool is not None:
            self._pool.shutdown(wait=True)
            self._pool = None
        for w in self.workers:
            w.close()

    def __enter__(self) -> "ReplPool":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
