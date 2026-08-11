"""REPL pool tests.

Unit tests drive the *real* state machine (framing, env retention, watchdog,
recycle, pool dispatch) against a scripted stand-in for the `lake env repl`
process, so they run offline in milliseconds. The stand-in speaks the exact wire
framing documented in research/lean-repl.md — JSON + blank line each way,
omitted empty lists — because that framing is precisely what would break
silently against a real REPL if the parser were tested against a friendlier
mock (the ../rl lesson: format compliance is a first-order failure surface).

Integration tests at the bottom need the toolchain from scripts/setup_lean.sh.
"""
from __future__ import annotations

import json
import queue
import threading
import time

import pytest

from rlmath.core.leancode import statement_check
from rlmath.lean.factory import get_backend
from rlmath.lean.repl_pool import (
    REPO_ROOT,
    ReplConfig,
    ReplPool,
    ReplWorker,
    to_result,
)

# --------------------------------------------------------------------------
# scripted repl process
# --------------------------------------------------------------------------


class FakeRepl:
    """A `ReplTransport` that behaves like one repl process.

    `handler(req, proc)` returns a dict (encoded as JSON), a raw string (emitted
    verbatim, for framing tests), or None to simulate a wedged elaboration that
    never answers.
    """

    def __init__(self, cfg, handler):
        self.cfg = cfg
        self.handler = handler
        self.requests: list[dict] = []
        self.raw_writes: list[str] = []
        self.imports = 0
        self.killed = False
        self._env = -1
        self._buf = ""
        self._lines: queue.Queue[str] = queue.Queue()
        self._dead = threading.Event()

    def next_env(self) -> int:
        self._env += 1
        return self._env

    # -- transport protocol
    def write(self, data: str) -> None:
        self.raw_writes.append(data)
        self._buf += data
        while "\n\n" in self._buf:                    # blank line terminates a request
            frame, self._buf = self._buf.split("\n\n", 1)
            if not frame.strip():
                continue
            req = json.loads(frame)
            self.requests.append(req)
            if "env" not in req:
                self.imports += 1
            resp = self.handler(req, self)
            if resp is None:
                continue                              # wedged: no reply ever comes
            self._emit(resp if isinstance(resp, str) else json.dumps(resp))

    def _emit(self, text: str) -> None:
        for line in text.split("\n"):
            self._lines.put(line + "\n")
        self._lines.put("\n")                          # explicit flushed blank line

    def readline(self) -> str:
        while True:
            try:
                return self._lines.get(timeout=0.005)
            except queue.Empty:
                if self._dead.is_set():
                    return ""                          # EOF
    def kill(self) -> None:
        self.killed = True
        self._dead.set()

    def poll(self) -> int | None:
        return -9 if self._dead.is_set() else None


def echo(req: dict, proc: FakeRepl) -> dict:
    """Minimal fake Lean: hands out env ids, echoes the command as an info message."""
    return {
        "env": proc.next_env(),
        "messages": [{"severity": "info", "pos": {"line": 1, "column": 0}, "data": req["cmd"]}],
    }


def answers(resp):
    """Handler that imports cleanly, then returns a canned response per command."""
    return lambda req, proc: {"env": 0} if "env" not in req else resp


def factory(handler=echo):
    """-> (transport_factory, list-of-spawned-processes)."""
    procs: list[FakeRepl] = []

    def make(cfg):
        p = FakeRepl(cfg, handler)
        procs.append(p)
        return p

    return make, procs


def worker(handler=echo, **cfg_kwargs):
    make, procs = factory(handler)
    kwargs = {"argv_override": ("fake",), **cfg_kwargs}
    return ReplWorker(ReplConfig(**kwargs), transport_factory=make), procs


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------


def test_config_resolves_paths_against_repo_root():
    cfg = ReplConfig(project_dir="lean/rlmathlib", repl_bin="lean/repl/.lake/build/bin/repl")
    assert cfg.project_dir == REPO_ROOT / "lean" / "rlmathlib"
    assert cfg.repl_bin == REPO_ROOT / "lean" / "repl" / ".lake" / "build" / "bin" / "repl"
    assert ReplConfig().project_dir.is_absolute()
    absolute = ReplConfig(project_dir="/tmp/elsewhere")
    assert str(absolute.project_dir) == "/tmp/elsewhere"


def test_default_argv_is_lake_env_repl():
    cfg = ReplConfig()
    assert cfg.argv == ["lake", "env", str(cfg.repl_bin)]
    assert ReplConfig(argv_override=("python", "-c", "pass")).argv == ["python", "-c", "pass"]


def test_config_rejects_degenerate_sizes():
    with pytest.raises(ValueError):
        ReplConfig(n_workers=0)
    with pytest.raises(ValueError):
        ReplConfig(recycle_after=0)


# --------------------------------------------------------------------------
# framing + env retention
# --------------------------------------------------------------------------


def test_request_framing_is_compact_json_plus_blank_line():
    w, procs = worker()
    w.check("example : True := trivial")
    frames = procs[0].raw_writes
    assert len(frames) == 2                       # preamble import, then the command
    for f in frames:
        assert f.endswith("\n\n")
        body = f[:-2]
        assert "\n" not in body                   # one physical line of JSON
        json.loads(body)


def test_reads_response_split_across_lines_and_tolerates_leading_blank():
    """`getLines`-style framing: read until the blank line, not one line."""
    pretty = "\n" + json.dumps({"env": 4, "messages": []}, indent=2)
    w, _ = worker(lambda req, p: pretty if "env" in req else {"env": 0})
    r = w.check("example : True := trivial")
    assert r.ok and r.env_id == 4


def test_toolchain_chatter_on_stdout_is_skipped():
    """A fresh checkout's `lake env` can print info lines before the child
    speaks; they must not be mistaken for the response frame."""
    noisy = "info: rlmathlib: no previous manifest\n" + json.dumps({"env": 2})
    w, _ = worker(lambda req, p: noisy)
    r = w.check("a")
    assert r.ok and r.env_id == 2


def test_unparseable_stdout_restarts_rather_than_desyncing():
    w, procs = worker(answers("{not json at all"))
    r = w.check("a", timeout_s=5)
    assert not r.ok and "repl timeout/restart" in r.errors[0].text
    assert procs[0].killed


def test_preamble_sent_once_and_env_reused():
    w, procs = worker()
    w.check("a")
    w.check("b")
    reqs = procs[0].requests
    assert reqs[0] == {"cmd": "import Mathlib"}    # stripped; no env -> fresh environment
    assert procs[0].imports == 1
    assert w.env_id == 0
    assert reqs[1] == {"cmd": "a", "env": 0}       # both commands reuse the import
    assert reqs[2] == {"cmd": "b", "env": 0}


def test_failed_preamble_is_a_failed_result_not_an_exception():
    bad = {"env": 0, "messages": [{"severity": "error", "pos": {"line": 1, "column": 0},
                                   "data": "unknown package 'Mathlib'"}]}
    w, _ = worker(lambda req, p: bad)
    r = w.check("a")
    assert not r.ok
    assert "preamble import failed" in r.errors[0].text
    assert "unknown package" in r.errors[0].text


# --------------------------------------------------------------------------
# response mapping
# --------------------------------------------------------------------------


def test_clean_response_maps_to_ok():
    w, _ = worker(lambda req, p: {"env": p.next_env()})     # empty lists are omitted by repl
    r = w.check("theorem t : 1 + 1 = 2 := by norm_num")
    assert r.ok and r.sorries == 0 and r.messages == []
    assert r.env_id == 1 and r.raw == {"env": 1}
    assert r.elapsed_s >= 0.0


def test_sorries_are_counted_and_do_not_make_it_not_ok():
    resp = {
        "env": 1,
        "sorries": [
            {"pos": {"line": 1, "column": 18}, "endPos": {"line": 1, "column": 23},
             "goal": "⊢ Nat", "proofState": 0},
            {"pos": {"line": 2, "column": 1}, "endPos": {"line": 2, "column": 6},
             "goal": "⊢ True", "proofState": 1},
        ],
        "messages": [{"severity": "warning", "pos": {"line": 1, "column": 4},
                      "data": "declaration uses 'sorry'"}],
    }
    w, _ = worker(answers(resp))
    r = w.check(statement_check("True"))
    assert r.sorries == 2
    assert r.ok                                   # sorry policy belongs to the caller
    assert r.errors == []


def test_error_severity_maps_to_not_ok_with_position():
    resp = {"env": 6, "messages": [{"severity": "error", "pos": {"line": 3, "column": 7},
                                    "endPos": {"line": 3, "column": 9}, "data": "type mismatch"}]}
    w, _ = worker(answers(resp))
    r = w.check("example : Nat := rfl")
    assert not r.ok
    assert [(m.severity, m.text, m.line, m.col) for m in r.messages] == [
        ("error", "type mismatch", 3, 7)
    ]
    assert r.raw == resp                          # the untouched response, for the result log


def test_repl_error_object_is_a_failure():
    """`{"message": ...}` carries no `messages` list; without special-casing it
    would score as a clean pass."""
    w, _ = worker(answers({"message": "Could not parse JSON:\nunexpected token"}))
    r = w.check("whatever")
    assert not r.ok
    assert "Could not parse JSON" in r.errors[0].text


def test_to_result_is_pure_and_reusable():
    assert to_result({"env": 2}, 1.5) == to_result({"env": 2}, 1.5)


# --------------------------------------------------------------------------
# watchdog, respawn, recycle
# --------------------------------------------------------------------------


def test_timeout_kills_worker_respawns_and_next_call_works():
    state = {"hang": True}

    def handler(req, proc):
        if "env" not in req:
            return {"env": 0}
        if state["hang"]:
            state["hang"] = False
            return None                            # wedged: never answers
        return {"env": 1}

    w, procs = worker(handler)
    r = w.check("slow", timeout_s=0.2)
    assert not r.ok
    assert r.errors[0].text.startswith("repl timeout/restart:")
    assert procs[0].killed and len(procs) == 1     # respawn is lazy, kill is not

    r2 = w.check("fast", timeout_s=5)
    assert r2.ok
    assert len(procs) == 2 and procs[1].imports == 1   # fresh process re-imported Mathlib
    assert procs[1].requests[1] == {"cmd": "fast", "env": 0}


def test_dead_process_is_detected_and_respawned():
    w, procs = worker()
    w.check("a")
    procs[0].kill()                                # process vanished between commands
    assert w.check("b").ok
    assert len(procs) == 2 and procs[1].imports == 1


def test_process_exiting_mid_command_is_a_failure_not_a_hang():
    def handler(req, proc):
        if "env" not in req:
            return {"env": 0}
        proc.kill()                                # dies without answering
        return None

    w, _ = worker(handler)
    r = w.check("crash", timeout_s=10)
    assert not r.ok and "repl timeout/restart" in r.errors[0].text


def test_recycle_after_restarts_the_process():
    w, procs = worker(recycle_after=2)
    for i in range(5):
        assert w.check(f"c{i}").ok
    # commands 0,1 on proc0; 2,3 on proc1; 4 on proc2 — each re-imports.
    assert len(procs) == 3
    assert [p.imports for p in procs] == [1, 1, 1]
    assert [len([r for r in p.requests if "env" in r]) for p in procs] == [2, 2, 1]
    assert w.commands_since_spawn == 1


def test_close_kills_the_process():
    w, procs = worker()
    w.check("a")
    w.close()
    assert procs[0].killed
    w.close()                                      # idempotent


# --------------------------------------------------------------------------
# real pipes, fake Lean — covers SubprocessTransport without a toolchain
# --------------------------------------------------------------------------

_STUB_REPL = r"""
import json, sys, time
env = -1
while True:
    lines = []
    while True:
        line = sys.stdin.readline()
        if line == "":          # EOF ends the process, as in REPL/Main.lean
            sys.exit(0)
        if line.strip() == "":
            break
        lines.append(line.rstrip("\n"))
    if not lines:
        continue
    req = json.loads("".join(lines))
    if req["cmd"] == "hang":
        time.sleep(120)         # wedged elaboration; the watchdog must kill us
    env += 1
    sys.stderr.write("stub: %s\n" % req["cmd"][:20]); sys.stderr.flush()
    print(json.dumps({"env": env, "messages":
                      [{"severity": "info", "pos": {"line": 1, "column": 0}, "data": req["cmd"]}]}),
          flush=True)
    print("", flush=True)
"""


def stub_worker(tmp_path, **cfg_kwargs):
    import sys

    cfg = ReplConfig(
        project_dir=tmp_path,
        argv_override=(sys.executable, "-u", "-c", _STUB_REPL),
        **cfg_kwargs,
    )
    return ReplWorker(cfg)


def test_subprocess_transport_round_trip(tmp_path):
    """Real pipes, real framing, real flushing — the parts a scripted transport
    cannot vouch for (Lean's stdout is block-buffered without the repl's own
    explicit flush, which is exactly what would hang a naive driver)."""
    w = stub_worker(tmp_path)
    try:
        r = w.check("theorem t : True := trivial", timeout_s=30)
        assert r.ok and r.env_id == 1
        assert r.messages[0].text == "theorem t : True := trivial"
        assert w.env_id == 0                       # env 0 = the preamble import
        # Goal text is full of ⊢ / ℕ / ∀; a locale-decoded pipe would mangle it.
        unicode_code = statement_check("∀ n : ℕ, n + 0 = n")
        assert w.check(unicode_code, timeout_s=30).messages[0].text == unicode_code
    finally:
        w.close()


def test_subprocess_transport_timeout_kills_and_respawns(tmp_path):
    w = stub_worker(tmp_path)
    try:
        bad = w.check("hang", timeout_s=0.5)
        assert not bad.ok and "repl timeout/restart" in bad.errors[0].text
        good = w.check("theorem t : True := trivial", timeout_s=30)
        assert good.ok and w.spawns == 2
    finally:
        w.close()


def test_subprocess_transport_reports_a_missing_binary(tmp_path):
    w = ReplWorker(ReplConfig(project_dir=tmp_path, argv_override=("definitely-not-a-binary",)))
    r = w.check("a")
    assert not r.ok and "startup failed" in r.errors[0].text


# --------------------------------------------------------------------------
# pool
# --------------------------------------------------------------------------


def pool(handler=echo, **cfg_kwargs):
    make, procs = factory(handler)
    kwargs = {"argv_override": ("fake",), **cfg_kwargs}
    return ReplPool(ReplConfig(**kwargs), transport_factory=make), procs


def test_pool_spawns_nothing_until_used():
    p, procs = pool(n_workers=3)
    assert procs == []
    p.check("a")
    assert len(procs) == 1                         # workers warm up lazily, one per use
    p.close()


def test_check_many_preserves_order():
    p, procs = pool(n_workers=3)
    codes = [f"lemma l{i} : True := trivial" for i in range(12)]
    out = p.check_many(codes)
    assert [r.messages[0].text for r in out] == codes
    assert all(r.ok for r in out)
    assert len(procs) == 3
    p.close()


def test_check_many_runs_workers_in_parallel():
    """A barrier the size of the pool: if dispatch were serial this deadlocks
    and the resulting BrokenBarrierError surfaces as a failed result."""
    barrier = threading.Barrier(3, timeout=10)

    def handler(req, proc):
        if "env" in req:
            barrier.wait()
        return echo(req, proc)

    p, _ = pool(handler, n_workers=3)
    out = p.check_many(["a", "b", "c"], timeout_s=20)
    assert [r.ok for r in out] == [True, True, True]
    p.close()


def test_exactly_one_command_in_flight_per_worker():
    lock = threading.Lock()
    live: dict[int, int] = {}
    peak: dict[int, int] = {}

    def handler(req, proc):
        k = id(proc)
        with lock:
            live[k] = live.get(k, 0) + 1
            peak[k] = max(peak.get(k, 0), live[k])
        time.sleep(0.005)
        with lock:
            live[k] -= 1
        return echo(req, proc)

    p, procs = pool(handler, n_workers=3)
    p.check_many([f"c{i}" for i in range(15)])
    assert len(procs) == 3
    assert set(peak.values()) == {1}               # the REPL is single-threaded; never overlap
    p.close()


def test_warm_imports_in_every_worker_exactly_once():
    p, procs = pool(n_workers=3)
    out = p.warm()
    assert len(out) == 3 and all(r.ok for r in out)
    assert len(procs) == 3 and [x.imports for x in procs] == [1, 1, 1]
    p.close()


def test_check_many_edge_cases():
    p, _ = pool(n_workers=2)
    assert p.check_many([]) == []
    assert [r.messages[0].text for r in p.check_many(["only"])] == ["only"]
    p.close()


def test_pool_close_is_final():
    p, procs = pool(n_workers=2)
    p.check_many(["a", "b"])
    p.close()
    assert all(x.killed for x in procs)
    with pytest.raises(RuntimeError):
        p.check("c")


def test_pool_context_manager():
    make, procs = factory()
    with ReplPool(ReplConfig(argv_override=("fake",), n_workers=1), transport_factory=make) as p:
        assert p.check("a").ok
    assert procs[0].killed


def test_pool_rejects_config_and_kwargs_together():
    with pytest.raises(TypeError):
        ReplPool(ReplConfig(), n_workers=2)


# --------------------------------------------------------------------------
# factory
# --------------------------------------------------------------------------


def test_factory_builds_a_repl_pool_without_touching_kimina():
    import sys

    sys.modules.pop("rlmath.lean.kimina", None)
    b = get_backend("repl", n_workers=1, argv_override=("fake",))
    assert isinstance(b, ReplPool) and b.cfg.n_workers == 1
    assert "rlmath.lean.kimina" not in sys.modules   # lazy: kimina's absence is not repl's problem
    b.close()


def test_factory_rejects_fake_and_unknown_names():
    with pytest.raises(ValueError, match="tests"):
        get_backend("fake")
    with pytest.raises(ValueError, match="unknown backend"):
        get_backend("nope")


# --------------------------------------------------------------------------
# integration — needs scripts/setup_lean.sh to have completed
# --------------------------------------------------------------------------

_cfg = ReplConfig()
needs_lean = pytest.mark.skipif(
    not _cfg.available(), reason=f"no lean project/repl binary at {_cfg.project_dir} / {_cfg.repl_bin}"
)


@pytest.fixture(scope="module")
def live_pool():
    """One warm pool for the whole module: `import Mathlib` is the expensive
    part and sharing it is the entire reason the pool exists."""
    p = ReplPool(n_workers=1)
    yield p
    p.close()


@pytest.mark.integration
@needs_lean
@pytest.mark.timeout(900)
def test_live_verifies_a_real_theorem(live_pool):
    r = live_pool.check("theorem _it_trivial : 1 + 1 = 2 := by norm_num", timeout_s=600)
    assert r.ok, r.messages
    assert r.sorries == 0
    assert r.env_id is not None


@pytest.mark.integration
@needs_lean
@pytest.mark.timeout(900)
def test_live_statement_check_rejects_nonsense(live_pool):
    r = live_pool.check(statement_check("Nat.no_such_lemma_xyz 3 = 7", name="_it_bad"), timeout_s=600)
    assert not r.ok
    assert r.errors


@pytest.mark.integration
@needs_lean
@pytest.mark.timeout(900)
def test_live_statement_check_of_good_prop_has_exactly_one_sorry(live_pool):
    r = live_pool.check(statement_check("∀ n : ℕ, n + 0 = n", name="_it_good"), timeout_s=600)
    assert r.ok, r.messages
    assert r.sorries == 1


@pytest.mark.integration
@needs_lean
@pytest.mark.timeout(900)
def test_live_env_is_reused_across_commands(live_pool):
    """The whole point of the pool: the second command must not re-import."""
    first = live_pool.check("theorem _it_a : True := trivial", timeout_s=600)
    t0 = time.monotonic()
    second = live_pool.check("theorem _it_b : True := trivial", timeout_s=600)
    assert first.ok and second.ok
    assert time.monotonic() - t0 < 20            # warm command, not a Mathlib import
