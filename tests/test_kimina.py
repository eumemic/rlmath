"""Kimina HTTP backend tests.

Everything offline runs against `httpx.MockTransport`, so the wire contract
(research/kimina.md §3b) is asserted byte-for-byte without a server: payload
shape, the four result shapes, batching, and every failure mode. The response
fixtures below are copied from that research file, which sourced them from the
server's own tests and code — not invented here.

Integration tests need a live server and are skipped unless RLMATH_KIMINA_URL
is set (DIRECTION.md hard rule: default suite is offline and fast).
"""
from __future__ import annotations

import json
import os

import httpx
import pytest

from rlmath.core.backend import LeanBackend
from rlmath.lean.kimina import KiminaClient, KiminaError, to_verify_result

# --- fixtures from research/kimina.md §3b ---------------------------------

CLEAN = {"id": "0", "time": 1.842913, "response": {"env": 1}}
INFO = {
    "id": "0", "time": 0.031,
    "response": {
        "messages": [{
            "severity": "info", "pos": {"line": 1, "column": 0},
            "endPos": {"line": 1, "column": 6}, "data": "Nat : Type",
        }],
        "env": 1,
    },
}
LEAN_ERROR = {
    "id": "0", "time": 1.0048,
    "response": {
        "messages": [{
            "severity": "error", "pos": {"line": 8, "column": 0},
            "endPos": {"line": 9, "column": 22},
            "data": "linarith failed to find a contradiction",
        }],
        "env": 1,
    },
}
SORRY = {
    "id": "0", "time": 0.5,
    "response": {
        "sorries": [{"pos": {"line": 1, "column": 25}, "goal": "⊢ 2 ∣ 4", "proofState": 0}],
        "messages": [{
            "severity": "warning", "pos": {"line": 1, "column": 8},
            "data": "declaration uses 'sorry'",
        }],
        "env": 1,
    },
}
TIMEOUT = {"id": "0", "error": "Lean REPL command timed out in 20 seconds"}


@pytest.fixture(autouse=True)
def _no_kimina_env(monkeypatch):
    """The constructor falls back to env vars, so a developer's own
    RLMATH_KIMINA_URL / LEAN_SERVER_API_KEY must not leak into the offline
    tests. Integration tests read the module-level KIMINA_URL captured at
    import time and pass it explicitly, so they are unaffected."""
    for var in ("RLMATH_KIMINA_URL", "LEAN_SERVER_API_URL", "LEAN_SERVER_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def client(handler, **kw) -> KiminaClient:
    """Client wired to a MockTransport. Retries default off so a test that does
    not opt in cannot silently pass by retrying (and cannot sleep)."""
    kw.setdefault("max_retries", 0)
    kw.setdefault("retry_backoff_s", 0.0)
    return KiminaClient("http://kimina.test", transport=httpx.MockTransport(handler), **kw)


def responder(results, *, status: int = 200, record: list | None = None):
    """Handler returning `results` verbatim, echoing request ids when `results`
    is callable."""
    def handle(request: httpx.Request) -> httpx.Response:
        if record is not None:
            record.append(request)
        body = json.loads(request.content) if request.content else {}
        payload = results(body) if callable(results) else results
        return httpx.Response(status, json={"results": payload})
    return handle


def echo(body: dict) -> list[dict]:
    """One clean result per snippet, ids echoed — the happy-path server."""
    return [{"id": s["id"], "time": 0.1, "response": {"env": 1}} for s in body["snippets"]]


# --- payload shape ---------------------------------------------------------

def test_payload_shape_and_path():
    seen: list[httpx.Request] = []
    with client(responder(echo, record=seen)) as c:
        c.check("import Mathlib\ntheorem t : True := trivial", timeout_s=45.0)
    (req,) = seen
    assert req.method == "POST"
    assert str(req.url) == "http://kimina.test/api/check"
    body = json.loads(req.content)
    assert body["snippets"] == [{"id": "0", "code": "import Mathlib\ntheorem t : True := trivial"}]
    assert body["timeout"] == 45 and isinstance(body["timeout"], int)
    assert body["debug"] is False
    assert body["reuse"] is True
    assert body["infotree"] is None
    assert "authorization" not in req.headers  # no key configured -> no header


def test_fractional_timeout_rounds_up():
    seen: list[httpx.Request] = []
    with client(responder(echo, record=seen)) as c:
        c.check("x", timeout_s=0.2)
    assert json.loads(seen[0].content)["timeout"] == 1  # never ask for less than budgeted


def test_ids_unique_within_a_request():
    # duplicate ids are a 422 server-side, so this is a hard requirement
    seen: list[httpx.Request] = []
    with client(responder(echo, record=seen), batch_size=64) as c:
        c.check_many(["a", "a", "a"])
    ids = [s["id"] for s in json.loads(seen[0].content)["snippets"]]
    assert len(set(ids)) == len(ids) == 3


def test_api_key_sets_bearer_header():
    seen: list[httpx.Request] = []
    c = KiminaClient("http://kimina.test", "sekrit",
                     transport=httpx.MockTransport(responder(echo, record=seen)), max_retries=0)
    with c:
        c.check("x")
    assert seen[0].headers["authorization"] == "Bearer sekrit"


def test_reuse_can_be_disabled():
    seen: list[httpx.Request] = []
    with client(responder(echo, record=seen), reuse=False) as c:
        c.check("x")
    assert json.loads(seen[0].content)["reuse"] is False


def test_http_deadline_exceeds_lean_deadline():
    """A client-side timeout before the server's own is a 499 that kills the
    REPL mid-proof — the module keeps HTTP_TIMEOUT_MARGIN_S of headroom."""
    seen: list[httpx.Request] = []
    with client(responder(echo, record=seen), timeout_s=10.0) as c:
        c.check("x", timeout_s=600.0)
    assert seen[0].extensions["timeout"]["read"] >= 630.0


# --- response mapping ------------------------------------------------------

def test_clean_compile_is_ok():
    r = to_verify_result(CLEAN)
    assert r.ok and r.messages == [] and r.sorries == 0
    assert r.env_id == 1
    assert r.elapsed_s == pytest.approx(1.842913)
    assert r.raw == CLEAN


def test_info_message_is_still_ok():
    r = to_verify_result(INFO)
    assert r.ok and r.sorries == 0
    assert [m.severity for m in r.messages] == ["info"]
    assert r.messages[0].text == "Nat : Type"
    assert (r.messages[0].line, r.messages[0].col) == (1, 0)


def test_error_message_maps_to_not_ok():
    r = to_verify_result(LEAN_ERROR)
    assert not r.ok
    assert len(r.errors) == 1
    assert "linarith failed" in r.errors[0].text
    assert r.errors[0].line == 8


def test_sorry_counted_and_ok_unaffected():
    # sorry policy belongs to the caller (core/types.py): ok stays True, the
    # count is reported so statement_check can demand exactly one.
    r = to_verify_result(SORRY)
    assert r.ok and r.sorries == 1
    assert [m.severity for m in r.messages] == ["warning"]


def test_timeout_error_string():
    r = to_verify_result(TIMEOUT)
    assert not r.ok
    assert "timed out" in r.errors[0].text
    assert r.raw["kimina_error"]["kind"] == "timeout"


def test_non_timeout_error_string():
    r = to_verify_result({"id": "0", "error": "stdin broken pipe"})
    assert not r.ok
    assert r.raw["kimina_error"]["kind"] == "repl"


def test_repl_message_object_is_a_failure():
    # {"message": ...} (singular) is a REPL-level error, not a clean compile.
    r = to_verify_result({"id": "0", "time": 0.1, "response": {"message": "unknown command"}})
    assert not r.ok
    assert r.raw["kimina_error"]["kind"] == "repl_error"
    assert "unknown command" in r.errors[0].text


def test_result_with_neither_response_nor_error():
    r = to_verify_result({"id": "0", "time": 0.1})
    assert not r.ok
    assert r.raw["kimina_error"]["kind"] == "protocol"


def test_missing_time_falls_back_to_wall_clock():
    r = to_verify_result({"id": "0", "response": {"env": 1}}, fallback_elapsed_s=2.5)
    assert r.elapsed_s == 2.5


def test_malformed_severity_fails_closed():
    r = to_verify_result({"id": "0", "response": {"messages": [{"data": "?"}], "env": 1}})
    assert not r.ok  # protocol drift must never read as a verified proof


def test_check_end_to_end_maps_error():
    with client(responder([LEAN_ERROR])) as c:
        r = c.check("theorem t : False := by nlinarith")
    assert not r.ok and "linarith failed" in r.errors[0].text


# --- batching --------------------------------------------------------------

def test_check_many_uses_one_request_when_it_fits():
    seen: list[httpx.Request] = []
    with client(responder(echo, record=seen), batch_size=8) as c:
        out = c.check_many(["a", "b", "c"])
    assert len(seen) == 1
    assert len(out) == 3 and all(r.ok for r in out)


def test_check_many_order_preserved_when_server_reorders():
    def handler(request: httpx.Request) -> httpx.Response:
        snips = json.loads(request.content)["snippets"]
        # results returned back-to-front, tagged so we can check the mapping
        out = [{"id": s["id"], "time": 0.1,
                "response": {"messages": [{"severity": "info", "data": s["code"]}], "env": 1}}
               for s in reversed(snips)]
        return httpx.Response(200, json={"results": out})

    with client(handler, batch_size=8) as c:
        out = c.check_many(["a", "b", "c", "d"])
    assert [r.messages[0].text for r in out] == ["a", "b", "c", "d"]


def test_check_many_chunks_and_preserves_order():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        snips = json.loads(request.content)["snippets"]
        return httpx.Response(200, json={"results": [
            {"id": s["id"], "time": 0.1,
             "response": {"messages": [{"severity": "info", "data": s["code"]}], "env": 1}}
            for s in snips
        ]})

    codes = [f"c{i}" for i in range(5)]
    with client(handler, batch_size=2, max_workers=3) as c:
        out = c.check_many(codes)
    assert len(seen) == 3                      # 2 + 2 + 1
    assert [r.messages[0].text for r in out] == codes
    # ids are the global index, so a logged raw row points back at its input
    assert [r.raw["id"] for r in out] == [str(i) for i in range(5)]


def test_check_many_empty_makes_no_request():
    seen: list[httpx.Request] = []
    with client(responder(echo, record=seen)) as c:
        assert c.check_many([]) == []
    assert seen == []


def test_one_bad_chunk_does_not_sink_the_others():
    def handler(request: httpx.Request) -> httpx.Response:
        snips = json.loads(request.content)["snippets"]
        if snips[0]["id"] == "2":
            return httpx.Response(429, text="No available REPLs")
        return httpx.Response(200, json={"results": [
            {"id": s["id"], "time": 0.1, "response": {"env": 1}} for s in snips
        ]})

    with client(handler, batch_size=2) as c:
        out = c.check_many(["a", "b", "c", "d"])
    assert [r.ok for r in out] == [True, True, False, False]
    assert out[2].raw["kimina_error"]["kind"] == "http_status"


def test_missing_result_for_an_id():
    def handler(request: httpx.Request) -> httpx.Response:
        snips = json.loads(request.content)["snippets"]
        keep = [s for s in snips if s["id"] != "1"]  # server drops one, count mismatches
        return httpx.Response(200, json={"results": [
            {"id": s["id"], "time": 0.1, "response": {"env": 1}} for s in keep
        ]})

    with client(handler, batch_size=8) as c:
        out = c.check_many(["a", "b", "c"])
    assert [r.ok for r in out] == [True, False, True]
    assert out[1].raw["kimina_error"]["kind"] == "protocol"


# --- failure handling ------------------------------------------------------

@pytest.mark.parametrize(
    ("status", "body"),
    [(401, "Missing API key"), (422, '{"detail": "duplicate ids"}'),
     (429, "No available REPLs"), (500, "RuntimeError: repl died")],
)
def test_non_200_is_a_result_row_not_an_exception(status, body):
    """Infrastructure failure must be recordable as a row — a traceback here
    would lose the whole eval cell (DIRECTION.md §6 evidence discipline)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body)

    with client(handler) as c:
        r = c.check("x")
    assert not r.ok
    assert f"HTTP {status}" in r.errors[0].text
    assert body[:20] in r.errors[0].text
    assert r.raw["kimina_error"]["kind"] == "http_status"
    assert r.raw["status_code"] == status


def test_transport_error_is_a_result_row():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with client(handler) as c:
        r = c.check("x")
    assert not r.ok
    assert "ConnectError" in r.errors[0].text
    assert r.raw["kimina_error"]["kind"] == "transport"


def test_non_json_body_is_a_result_row():
    with client(lambda request: httpx.Response(200, text="<html>gateway</html>")) as c:
        r = c.check("x")
    assert not r.ok and r.raw["kimina_error"]["kind"] == "protocol"


def test_missing_results_key_is_a_result_row():
    with client(lambda request: httpx.Response(200, json={"oops": []})) as c:
        r = c.check("x")
    assert not r.ok and r.raw["kimina_error"]["kind"] == "protocol"


def test_retries_transient_status_then_succeeds():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, text="No available REPLs")
        return httpx.Response(200, json={"results": [CLEAN]})

    with client(handler, max_retries=2, retry_backoff_s=0.0) as c:
        r = c.check("x")
    assert r.ok and len(calls) == 3


def test_retries_are_bounded():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, text="unavailable")

    with client(handler, max_retries=2, retry_backoff_s=0.0) as c:
        r = c.check("x")
    assert not r.ok and len(calls) == 3


def test_deterministic_errors_are_not_retried():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(422, text="duplicate ids")

    with client(handler, max_retries=3, retry_backoff_s=0.0) as c:
        c.check("x")
    assert len(calls) == 1  # retrying misuse just burns the REPL pool


# --- health ----------------------------------------------------------------

def test_health_ok():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "ok"})

    with client(handler) as c:
        assert c.health() == {"status": "ok"}
    assert str(seen[0].url) == "http://kimina.test/health"
    assert seen[0].method == "GET"


@pytest.mark.parametrize("status", [404, 500, 503])
def test_health_raises_on_non_200(status):
    # the one loud path: a precondition check that fails softly is not checked
    with client(lambda request: httpx.Response(status, text="nope")) as c:
        with pytest.raises(KiminaError, match="health check failed"):
            c.health()


def test_health_raises_on_unreachable_server():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with client(handler) as c:
        with pytest.raises(KiminaError, match="failed after"):
            c.health()


def test_health_raises_on_garbage_body():
    with client(lambda request: httpx.Response(200, text="not json")) as c:
        with pytest.raises(KiminaError, match="non-JSON"):
            c.health()


# --- construction ----------------------------------------------------------

def test_implements_the_backend_protocol():
    with client(responder(echo)) as c:
        assert isinstance(c, LeanBackend)


@pytest.mark.parametrize("kw", [
    {"base_url": "kimina.test"},          # no scheme
    {"base_url": "ftp://kimina.test"},
    {"timeout_s": 0},
    {"batch_size": 0},
    {"max_workers": 0},
    {"max_retries": -1},
])
def test_constructor_rejects_misuse(kw):
    kw.setdefault("base_url", "http://kimina.test")
    with pytest.raises(KiminaError):
        KiminaClient(**kw)


def test_trailing_slash_is_normalized():
    seen: list[httpx.Request] = []
    c = KiminaClient("http://kimina.test/", transport=httpx.MockTransport(responder(echo, record=seen)),
                     max_retries=0)
    with c:
        c.check("x")
    assert str(seen[0].url) == "http://kimina.test/api/check"


def test_env_fallbacks(monkeypatch):
    monkeypatch.setenv("RLMATH_KIMINA_URL", "http://from-env:9000")
    monkeypatch.setenv("LEAN_SERVER_API_KEY", "envkey")
    seen: list[httpx.Request] = []
    c = KiminaClient(transport=httpx.MockTransport(responder(echo, record=seen)), max_retries=0)
    with c:
        assert c.base_url == "http://from-env:9000"
        c.check("x")
    assert seen[0].headers["authorization"] == "Bearer envkey"


# --- integration (live server) ---------------------------------------------

KIMINA_URL = os.environ.get("RLMATH_KIMINA_URL")
live = pytest.mark.skipif(not KIMINA_URL, reason="set RLMATH_KIMINA_URL to run against a live server")


@pytest.fixture
def live_client():
    c = KiminaClient(KIMINA_URL, timeout_s=900.0)
    yield c
    c.close()


@pytest.mark.integration
@live
def test_live_health(live_client):
    assert live_client.health().get("status") == "ok"


@pytest.mark.integration
@live
def test_live_check_nat(live_client):
    # the server's own smoke test; needs no Mathlib import
    r = live_client.check("#check Nat", timeout_s=60.0)
    assert r.ok, r.messages
    assert any("Nat : Type" in m.text for m in r.messages)
    assert r.elapsed_s > 0


@pytest.mark.integration
@live
def test_live_sorry_and_error_mapping(live_client):
    from rlmath.core.leancode import PREAMBLE, proof_check, statement_check

    stmt = PREAMBLE + statement_check("∀ n : ℕ, n + 0 = n")
    good = PREAMBLE + proof_check("∀ n : ℕ, n + 0 = n", "by simp")
    bad = PREAMBLE + proof_check("∀ n : ℕ, n + 1 = n", "by simp")
    stmt_r, good_r, bad_r = live_client.check_many([stmt, good, bad], timeout_s=180.0)

    assert stmt_r.ok and stmt_r.sorries == 1     # elaborates, proves nothing
    assert good_r.ok and good_r.sorries == 0
    assert not bad_r.ok and bad_r.errors


@pytest.mark.integration
@live
def test_live_batch_order_and_chunking(live_client):
    codes = [f"#check ({i} : Nat)" for i in range(10)]
    out = live_client.check_many(codes, timeout_s=60.0)
    assert len(out) == 10 and all(r.ok for r in out)
    for i, r in enumerate(out):
        assert any(f"{i}" in m.text for m in r.messages), r.messages
