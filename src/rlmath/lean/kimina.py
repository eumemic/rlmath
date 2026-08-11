"""Kimina Lean Server client — the HTTP `LeanBackend` (DIRECTION.md §5.3).

Why a second backend at all: Phase 0's gate is ≥2–3k verified leaf attempts/hour
(§5.5), and the documented way to reach it is a warm-Mathlib Kimina server on a
large-CPU box. `core.backend.LeanBackend` keeps that box and the local macOS
REPL pool interchangeable, so the migration is a constructor swap and nothing
else — the same narrow-seam discipline that let ../rl run one runner across two
model backends.

Wire contract (server 2.0.0; every field verified against source in
research/kimina.md §3b):

    POST /api/check
      {"snippets": [{"id", "code"}], "timeout": int, "debug": bool,
       "reuse": bool, "infotree": null}
    -> {"results": [{"id", "time", "response" | "error", "diagnostics"?}]}

    GET /health -> {"status": "ok"}

`results[i]` lines up 1:1 with `snippets[i]` *and* echoes the id; exactly one of
`response`/`error` is set per result; ids must be unique within a request or the
server answers 422. Auth, when the server has `LEAN_SERVER_API_KEY` set, is
`Authorization: Bearer <key>`; `/health` is never authenticated.

Three deliberate departures from the official `kimina-client` SDK:

  1. **One shared `httpx.Client` across all worker threads.** The SDK's sync
     client opens a fresh client per request per thread, which walks into
     `ulimit -n` (256 by default on macOS) as a storm of connection errors
     (research/kimina.md §7). `httpx.Client` is thread-safe and pools
     connections; sharing one is strictly better and costs nothing.

  2. **Per-snippet failures never raise.** A 429 (REPL pool exhausted), a 500,
     or a dead socket becomes `VerifyResult(ok=False)` carrying the reason in an
     error-severity message plus a `kimina_error` block in `raw`. The harness
     must record infrastructure failure as a *row* — losing a whole eval cell to
     a traceback is exactly the contamination DIRECTION.md §6 forbids. Only
     constructor misuse and `health()` raise.

  3. **The HTTP read timeout is always held above the Lean-side timeout.**
     Giving up first is a 499 server-side, which cancels the request *and kills
     the REPL* working on our snippet — the most expensive possible way to time
     out, since the next request with that import header re-pays `import
     Mathlib`.

Retries: issue #58 (open, unresolved) reports ~8% transient error rate on an
*idle* 128-core box, so a bounded retry with exponential backoff is budgeted
here rather than assumed unnecessary. Retries cover transport errors and the
transient status codes only; 401/422 are deterministic misuse and fail fast.

Sorry policy lives in the caller, not here (PHASE0_NOTES 2026-08-11 decision):
`ok` means "no error-severity messages", and `sorries` is reported alongside so
statement elaboration can demand exactly one and proof checks exactly zero.
"""
from __future__ import annotations

import math
import os
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

import httpx

from ..core.types import LeanMessage, VerifyResult

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_HTTP_TIMEOUT_S = 600.0
# The server runs a whole batch concurrently (asyncio.gather) but only up to
# LEAN_SERVER_MAX_REPLS at once; the rest queue against LEAN_SERVER_MAX_WAIT and
# then 429. Chunking bounds the blast radius of one such 429 to `batch_size`
# snippets instead of the whole call, and keeps any single HTTP request short
# enough that a stuck REPL cannot hold the entire batch hostage.
DEFAULT_BATCH_SIZE = 8
DEFAULT_MAX_WORKERS = 4
# Headroom between our HTTP read deadline and the Lean-side snippet deadline.
HTTP_TIMEOUT_MARGIN_S = 30.0
HEALTH_TIMEOUT_S = 30.0
# 429 = REPL pool exhausted; 5xx = server-side blow-up (often a recycled REPL).
# 401/422/499 are deliberately absent: retrying misuse just burns the pool.
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

# Every message this module writes itself (as opposed to relaying from Lean) is
# prefixed, so an operator reading a failure row can tell backend trouble from a
# genuine proof failure at a glance. Machine-readable form: raw["kimina_error"].
MARKER = "kimina"


class KiminaError(RuntimeError):
    """Raised only by `health()` and the constructor — see module docstring."""


def _message(m: dict) -> LeanMessage:
    """One Lean REPL diagnostic -> LeanMessage.

    Positions are already header-offset-corrected by the server
    (`_apply_header_offset`), so they refer to *our* snippet's lines.
    """
    pos = m.get("pos") or {}
    line = pos.get("line") if isinstance(pos.get("line"), int) else None
    col = pos.get("column") if isinstance(pos.get("column"), int) else None
    # A missing `severity` cannot come from a healthy server (the field is
    # required by its pydantic model), so it means protocol drift — and drift
    # must fail closed. NB: repl_pool.to_result defaults to "info" instead;
    # there the field is genuinely optional in the REPL's own JSON.
    return LeanMessage(
        severity=str(m.get("severity", "error")),
        text=str(m.get("data", "")),
        line=line,
        col=col,
    )


def _failure(detail: str, *, kind: str, elapsed_s: float = 0.0, raw: dict | None = None) -> VerifyResult:
    """A backend-level failure as a result row rather than an exception."""
    err = {"kind": kind, "detail": detail}
    payload = dict(raw or {})
    payload["kimina_error"] = err
    return VerifyResult(
        ok=False,
        messages=[LeanMessage("error", f"{MARKER}: {detail}")],
        elapsed_s=elapsed_s,
        raw=payload,
    )


def _as_float(value: object, fallback: float) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else fallback


def to_verify_result(item: dict, *, fallback_elapsed_s: float = 0.0) -> VerifyResult:
    """Map one `/api/check` result element onto the shared `VerifyResult`.

    Module-level (not a method) because the mapping is the part worth testing
    exhaustively and reusing from analysis scripts that read logged raw rows.

    Four shapes, per research/kimina.md §3b:
      - `response` with no error-severity messages -> ok (info messages are fine)
      - `response` with an error-severity message  -> Lean-level failure
      - `response.sorries` non-empty               -> counted, never itself an error
      - top-level `error` string                   -> backend/REPL failure; the
        substring "timed out" is the only reliable timeout discriminator the
        server gives us (its own client branches on exactly this).
    """
    elapsed = _as_float(item.get("time"), fallback_elapsed_s)

    err = item.get("error")
    if err is not None:
        text = str(err)
        kind = "timeout" if "timed out" in text else "repl"
        return _failure(text, kind=kind, elapsed_s=elapsed, raw=dict(item))

    body = item.get("response")
    if not isinstance(body, dict):
        return _failure(
            "result has neither `response` nor `error`", kind="protocol",
            elapsed_s=elapsed, raw=dict(item),
        )

    raw_messages = body.get("messages")
    if raw_messages is None and isinstance(body.get("message"), str):
        # REPL-level error: the REPL answered with {"message": ...} instead of a
        # command response. Not a proof failure — an unusable answer.
        return _failure(
            f"REPL error: {body['message']}", kind="repl_error",
            elapsed_s=elapsed, raw=dict(item),
        )

    messages = [_message(m) for m in (raw_messages or []) if isinstance(m, dict)]
    env = body.get("env")
    return VerifyResult(
        ok=not any(m.severity == "error" for m in messages),
        messages=messages,
        sorries=len(body.get("sorries") or []),
        elapsed_s=elapsed,
        env_id=env if isinstance(env, int) else None,
        raw=dict(item),
    )


class KiminaClient:
    """`LeanBackend` over Kimina's HTTP API. Thread-safe; reusable; closeable."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        timeout_s: float = DEFAULT_HTTP_TIMEOUT_S,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_workers: int = DEFAULT_MAX_WORKERS,
        reuse: bool = True,
        max_retries: int = 2,
        retry_backoff_s: float = 1.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """`timeout_s` is the HTTP deadline; the *Lean* deadline is the per-call
        `timeout_s` of `check`/`check_many` (the `LeanBackend` signature). The
        two are different clocks and the HTTP one is always the looser of them.

        `reuse=True` keeps warm REPLs keyed on the import header — the single
        biggest throughput lever the server exposes (research/kimina.md §7), and
        the reason a Phase-0 throughput gate is reachable at all.

        `transport` is the seam unit tests drive with `httpx.MockTransport`.
        """
        url = (
            base_url
            or os.environ.get("RLMATH_KIMINA_URL")
            or os.environ.get("LEAN_SERVER_API_URL")
            or DEFAULT_BASE_URL
        )
        url = url.strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            raise KiminaError(f"base_url must be an http(s) URL, got {url!r}")
        if timeout_s <= 0:
            raise KiminaError(f"timeout_s must be positive, got {timeout_s!r}")
        if batch_size < 1:
            raise KiminaError(f"batch_size must be >= 1, got {batch_size!r}")
        if max_workers < 1:
            raise KiminaError(f"max_workers must be >= 1, got {max_workers!r}")
        if max_retries < 0:
            raise KiminaError(f"max_retries must be >= 0, got {max_retries!r}")

        self.base_url = url
        self.http_timeout_s = float(timeout_s)
        self.batch_size = int(batch_size)
        self.max_workers = int(max_workers)
        self.reuse = bool(reuse)
        self.max_retries = int(max_retries)
        self.retry_backoff_s = float(retry_backoff_s)

        key = api_key or os.environ.get("LEAN_SERVER_API_KEY") or None
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        self._client = httpx.Client(
            timeout=httpx.Timeout(self.http_timeout_s),
            headers=headers,
            transport=transport,
        )

    # -- LeanBackend ------------------------------------------------------

    def check(self, code: str, *, timeout_s: float = 120.0) -> VerifyResult:
        return self._post_check([code], timeout_s=timeout_s, offset=0)[0]

    def check_many(self, codes: Sequence[str], *, timeout_s: float = 120.0) -> list[VerifyResult]:
        """Order-preserving batch check.

        The API is natively batched, so this is HTTP-level batching (one request
        per `batch_size` snippets), not a per-snippet fan-out. The thread pool
        exists only to overlap those requests; the server's own REPL pool is
        what actually bounds concurrency.
        """
        items = list(codes)
        if not items:
            return []
        chunks = [(off, items[off:off + self.batch_size])
                  for off in range(0, len(items), self.batch_size)]

        if len(chunks) == 1:
            off, chunk = chunks[0]
            per_chunk = [self._post_check(chunk, timeout_s=timeout_s, offset=off)]
        else:
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(chunks))) as pool:
                futures = [pool.submit(self._post_check, chunk, timeout_s=timeout_s, offset=off)
                           for off, chunk in chunks]
                per_chunk = [f.result() for f in futures]

        # Chunks are contiguous and in input order, and `_post_check` returns
        # exactly one row per code, so concatenation restores the input order.
        out = [r for rows in per_chunk for r in rows]
        assert len(out) == len(items), f"backend returned {len(out)} rows for {len(items)} codes"
        return out

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> KiminaClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- server probes ----------------------------------------------------

    def health(self) -> dict:
        """`GET /health` -> `{"status": "ok"}`. Raises on anything else.

        The one loud path in this module: a health probe is a *precondition*
        check, and a precondition that returns a soft failure object is a
        precondition nobody checks. Per-snippet failures stay soft.
        """
        url = f"{self.base_url}/health"
        resp = self._request("GET", url, timeout=httpx.Timeout(HEALTH_TIMEOUT_S))
        if resp.status_code != 200:
            raise KiminaError(f"health check failed: HTTP {resp.status_code} from {url}: {_snippet(resp)}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise KiminaError(f"health check returned non-JSON from {url}: {exc}") from exc
        if not isinstance(data, dict):
            raise KiminaError(f"health check returned {type(data).__name__}, expected object: {data!r}")
        return data

    # -- internals --------------------------------------------------------

    def _post_check(self, codes: list[str], *, timeout_s: float, offset: int) -> list[VerifyResult]:
        """One `POST /api/check`. Never raises: every failure mode lands in the
        returned rows, one per input code, in input order."""
        url = f"{self.base_url}/api/check"
        ids = [str(offset + i) for i in range(len(codes))]
        payload = {
            # `timeout` is an int of seconds server-side; round up so we never
            # silently ask Lean for less time than the caller budgeted.
            "snippets": [{"id": sid, "code": c} for sid, c in zip(ids, codes)],
            "timeout": max(1, math.ceil(timeout_s)),
            "debug": False,
            "reuse": self.reuse,
            "infotree": None,
        }
        http_timeout = httpx.Timeout(max(self.http_timeout_s, timeout_s + HTTP_TIMEOUT_MARGIN_S))

        started = time.monotonic()
        try:
            resp = self._request("POST", url, json=payload, timeout=http_timeout)
        except KiminaError as exc:
            wall = time.monotonic() - started
            return [_failure(str(exc), kind="transport", elapsed_s=wall) for _ in codes]
        wall = time.monotonic() - started

        if resp.status_code != 200:
            detail = f"HTTP {resp.status_code} from {url}: {_snippet(resp)}"
            return [
                _failure(detail, kind="http_status", elapsed_s=wall,
                         raw={"status_code": resp.status_code})
                for _ in codes
            ]
        try:
            data = resp.json()
        except ValueError as exc:
            return [_failure(f"non-JSON response from {url}: {exc}", kind="protocol", elapsed_s=wall)
                    for _ in codes]
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            return [_failure(f"malformed response from {url} (no `results` list)", kind="protocol",
                             elapsed_s=wall)
                    for _ in codes]

        # Key off the echoed id (the contract's own safety net) and fall back to
        # position, which the server also guarantees. Belt and braces: a silent
        # misalignment here would attribute one snippet's proof status to
        # another, which is unrecoverable after the fact.
        by_id = {str(r.get("id")): r for r in results if isinstance(r, dict)}
        out: list[VerifyResult] = []
        for i, sid in enumerate(ids):
            item = by_id.get(sid)
            if item is None and len(results) == len(codes) and isinstance(results[i], dict):
                item = results[i]
            if item is None:
                out.append(_failure(f"no result for snippet id {sid!r}", kind="protocol", elapsed_s=wall))
            else:
                out.append(to_verify_result(item, fallback_elapsed_s=wall))
        return out

    def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> httpx.Response:
        """Request with bounded exponential backoff on transient failure.

        Returns the response (including a non-200 one, once retries are spent);
        raises `KiminaError` only when no response was ever obtained.
        """
        detail = "request failed"
        for attempt in range(self.max_retries + 1):
            if attempt:
                time.sleep(self.retry_backoff_s * (2 ** (attempt - 1)))
            try:
                resp = self._client.request(method, url, json=json, timeout=timeout)
            except httpx.HTTPError as exc:
                detail = f"{type(exc).__name__}: {exc}"
                continue
            if resp.status_code in RETRY_STATUS and attempt < self.max_retries:
                detail = f"HTTP {resp.status_code} from {url}: {_snippet(resp)}"
                continue
            return resp
        raise KiminaError(f"{method} {url} failed after {self.max_retries + 1} attempts: {detail}")


def _snippet(resp: httpx.Response, limit: int = 200) -> str:
    """Short body excerpt for a failure message. 429/500 bodies are plain
    strings, 422 is a FastAPI validation object — both are worth seeing, neither
    is worth logging in full."""
    try:
        text = resp.text
    except Exception:  # pragma: no cover - body already consumed/streamed
        return "<unreadable body>"
    text = " ".join(text.split())
    return text[:limit] + ("…" if len(text) > limit else "")
