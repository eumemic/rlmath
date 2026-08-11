# Kimina Lean Server — Research Notes (as of 2026-08-11)

Repo: [project-numina/kimina-lean-server](https://github.com/project-numina/kimina-lean-server) (MIT, 206★/37 forks at research time). Serves the [Lean REPL](https://github.com/leanprover-community/repl) behind FastAPI, parallelized across a pool of persistent `repl` subprocesses, with a Python client SDK (`kimina-client` on PyPI). Accompanying paper: [arXiv:2504.21230](https://arxiv.org/abs/2504.21230).

Versions found: server `__version__` = `2.0.0` (`server/__version__.py`); client package `kimina-client` = `0.2.1` on PyPI (releases `0.1.3`…`0.2.1`). Server and client are versioned independently and live in the same repo (`server/` vs `client/kimina_client/`).

All facts below are sourced directly from the repo tree at `main` (fetched 2026-08-11): `README.md`, `README-client.md`, `AGENTS.md`, `Dockerfile`, `setup.sh`, `compose.yaml`/`compose-dev.yaml`, `.env.template`, `server/*.py`, `server/routers/*.py`, `client/kimina_client/*.py`, `tests/match/**`, `.github/workflows/*.yaml`, and Docker Hub's tag API for `projectnumina/kimina-lean-server`.

---

## 1. macOS arm64 verdict

**Native source install works on macOS (incl. Apple Silicon) and is in fact how the maintainers develop/benchmark.** The README's own benchmark section states runs were done on a **MacBook Pro M2 (10 CPUs)** using `python -m server` directly (no Docker, no `.env`). The server is pure Python (FastAPI/asyncio) that shells out to `lake env <repl-binary>` as a subprocess — nothing OS-specific in the request path. `elan`/`lake`/Lean 4 and Mathlib's prebuilt `.olean` cache (`lake exe cache get`) all support macOS arm64 upstream, and `setup.sh` just calls the standard elan installer, so this is a genuinely supported dev path, not an emulation hack.

One real macOS-only code branch to know about, in `server/repl.py::Repl.start()`:
```python
def _preexec() -> None:
    import resource
    if platform.system() != "Darwin":  # Only for Linux
        resource.setrlimit(resource.RLIMIT_AS, (self.max_memory_bytes, self.max_memory_bytes))
    os.setsid()
```
`LEAN_SERVER_MAX_REPL_MEM` (the per-REPL memory cap) is **not enforced on macOS** — `RLIMIT_AS` is skipped on Darwin. The README's env-var table calls this out too ("Linux-only"). On macOS a runaway REPL can grow unbounded; you don't get the OOM guard rail Linux gets.

**Docker Hub images are amd64/linux-only.** Checked all 9 published tags (`latest`, `2.0.0`, `1.0.6-pu`, `1.0.5-pu`, `1.0.4-pu`, `1.0.3`, `1.0.2`, `1.0.1`, `1.0.0`) via the Docker Hub API — every one has a single-architecture manifest, `amd64/linux`. The GitHub Actions CD workflow (`cd-server.yaml`, "Deploy to Google Cloud") does a plain `docker build .` on `ubuntu-latest` with no `buildx`/multi-platform step, consistent with this. So:
- `docker compose up` / `docker run projectnumina/kimina-lean-server:2.0.0` on an Apple Silicon Mac will pull the amd64 image and run it under Rosetta/QEMU emulation (slow, and Lean/Mathlib compilation-heavy workloads are a bad fit for emulation).
- `docker build .` **locally** on an arm64 Mac would produce a native arm64 image (the `Dockerfile` itself is arch-agnostic — Debian slim + elan + `lake build`), but nobody publishes one, so you'd own that build.

**Bottom line for a Mac dev machine:** skip Docker, install from source (`bash setup.sh && pip install -r requirements.txt && pip install . && prisma generate && python -m server`). It's a first-class, maintainer-used path. Just be aware `LEAN_SERVER_MAX_REPL_MEM` is a no-op safety net on macOS.

---

## 2. Install options

### 2a. From source (works on macOS/Linux)
```sh
git clone https://github.com/project-numina/kimina-lean-server
cd kimina-lean-server
cp .env.template .env            # optional
bash setup.sh                    # installs elan+Lean, builds `repl` and `mathlib4` in ./repl and ./mathlib4
pip install -r requirements.txt  # or: uv sync
pip install .
prisma generate                  # generates the (optional) Prisma DB client — needed even if you don't use a DB
python -m server
```
`setup.sh` internals (env-overridable): installs elan pinned to `LEAN_SERVER_LEAN_VERSION` (default `v4.26.0`), then `git clone --depth 1` of `leanprover-community/repl` and `leanprover-community/mathlib4` at that same tag into `./repl` and `./mathlib4`, running `lake exe cache get && lake build` for mathlib4 (fetches Mathlib's prebuilt `.olean` cache rather than compiling from scratch — this is the expensive step, ~tens of GB).

> Note: the server hard-requires `mathlib4` and `repl` to already exist under the workspace before `python -m server` is run (README calls this out explicitly).

### 2b. Docker
```sh
docker compose up          # pulls projectnumina/kimina-lean-server:2.0.0 from Docker Hub
# or equivalently:
docker run -d --name server --restart unless-stopped --env-file .env \
  -p 80:${LEAN_SERVER_PORT} projectnumina/kimina-lean-server:2.0.0
```
Build your own image pinned to a specific Lean version:
```sh
docker build --build-arg LEAN_SERVER_LEAN_VERSION=v4.21.0 .
```
`Dockerfile` is `python:3.13-slim` based; it runs the same `setup.sh` inside the image, then `uv export --extra server --no-dev --no-emit-project > requirements.txt && pip install -r requirements.txt && pip install -e . && prisma generate`. **Caveat found in the Dockerfile**: its default `REPL_REPO_URL`/`REPL_BRANCH` build args point at a fork — `https://github.com/FrederickPu/repl.git` branch `lean415compat` — not the canonical `leanprover-community/repl` that `setup.sh` defaults to for source installs. If you build the image without overriding those build-args you get a different REPL fork than a plain source install gets. Worth pinning explicitly if reproducibility matters.

`compose-dev.yaml` additionally spins up a local Postgres (`postgres:17-alpine`) for the optional proof-logging DB (see §6).

### 2c. Python client (pip)
```sh
pip install kimina-client
```
```python
from kimina_client import KiminaClient
client = KiminaClient()   # api_url defaults to http://localhost:8000 (see caveat below), no API key
client.check("#check Nat")
```
Or from source: `pip install -e .` in the repo root (package name `kimina-client`, wheel packages `client/kimina_client`, `pyproject.toml` requires Python ≥3.9).

**Doc/code mismatch to flag:** `README-client.md` claims the client's "Default `api_url` is `https://projectnumina.ai`" — but the actual code (`client/kimina_client/base.py`) defaults to `os.getenv("LEAN_SERVER_API_URL", "http://localhost:8000")`. Trust the code: default is localhost:8000 unless `LEAN_SERVER_API_URL` is set.

**Also stale**: `README-client.md` and `examples/batch_verify.py` reference a `Lean4Client` class (`from kimina_client import Lean4Client` / `from client import Lean4Client`). That class doesn't exist in current code — `client/kimina_client/client_old.py` is entirely commented-out dead code, and `__init__.py` only exports `KiminaClient` / `AsyncKiminaClient`. Don't rely on `Lean4Client`; use `KiminaClient`/`AsyncKiminaClient` and the backward-compat REST endpoints (`/verify`, `/one_pass_verify_batch`) directly if you need the old `custom_id`/`proof` wire format.

---

## 3. HTTP API — exact endpoints, request/response JSON

FastAPI app (`server/main.py`): `title="Kimina Lean Server API"`, OpenAPI at `/api/openapi.json`, Swagger UI at `/docs`, ReDoc at `/redoc`.

| Method | Path | Router | Notes |
|---|---|---|---|
| `GET` | `/health`, `/health/`, `/` | `health.py` | liveness, no auth |
| `POST` | `/api/check` (alias `/api/check/`) | `check.py` — **primary/modern endpoint** | batch check, requires API key if set |
| `POST` | `/verify` | `backward.py` | legacy wire format (`custom_id`/`proof`) |
| `POST` | `/one_pass_verify_batch` | `backward.py` | identical handler/body to `/verify`, alternate path |

Note the prefix: `check_router` is mounted with `prefix="/api"` → real path is `/api/check`, **not** `/check` (the README's top-level curl example against `/verify` is the legacy router, which is *not* under `/api`). The Python SDK always calls `POST {api_url}/api/check`.

### 3a. `GET /health`
```json
{"status": "ok"}
```

### 3b. `POST /api/check` — the modern endpoint

**Request body** (`CheckRequest`):
```json
{
  "snippets": [
    {"id": "mathlib-import-def", "code": "import Mathlib\ndef f := 1"}
  ],
  "timeout": 20,
  "debug": false,
  "reuse": true,
  "infotree": "original"
}
```
Field semantics (`server/models.py` / `client/kimina_client/models.py`):
- `snippets: list[{id: str, code: str}]` — **required, non-empty, ids must be unique** (pydantic validator raises 422 otherwise). `id` is your own tracing key; `code` is the full Lean 4 source (imports + body together — the server auto-splits header imports from body, see §5).
- `timeout: int` — seconds to wait for the Lean REPL to answer *this* snippet (default `30` server-side; the SDK's `check()`/`api_check()` wrapper defaults to `60`). `ge=0`.
- `debug: bool` (default `false`) — when `true`, response includes a `diagnostics` block (REPL uuid, max CPU%, max RSS bytes observed during execution).
- `reuse: bool` (default `true`) — whether to reuse a warm REPL process that already has the same import header loaded (see §5/§7). Set `false` to force a cold REPL per request.
- `infotree: "full" | "tactics" | "original" | "substantive" | null` — passed straight through to the Lean REPL's `infotree` option; when set, the REPL response gains an `infotree` field (nested tree of `{"node": {...}, "children": [...]}`, each node has `stx.pp` (pretty-printed text), `stx.range.{start,finish}.{line,column}`, `goalsBefore`, `goalsAfter`). The client ships `client/kimina_client/infotree.py` with utilities to flatten an infotree into per-tactic `(goalsBefore, goalsAfter, tactic_text)` intervals — useful if you want tactic-level supervision signal instead of just pass/fail.

**Response** (`CheckResponse`, `response_model_exclude_none=True` so `null` fields are dropped):
```json
{
  "results": [
    {
      "id": "mathlib-import-def",
      "time": 1.842913,
      "response": {
        "env": 1
      }
    }
  ]
}
```
Each element of `results` is a `ReplResponse`:
- `id: str` — echoes the snippet id (order of `results` matches order of `snippets`; batch runs `asyncio.gather`, so results are *not* guaranteed to complete in wall-clock order, but the list positions do line up 1:1 with the request list).
- `time: float` — wall-clock seconds the REPL spent on the body command (header/import time is separate and not included here — see §5).
- **exactly one of** `error` or `response` is set (pydantic `model_validator` enforces this — a `ReplResponse` with both or neither is invalid):
  - `response: CommandResponse` on success — shape mirrors Lean REPL's own JSON (`repl`'s `REPL/JSON.lean`): `{"env": int, "messages"?: [...], "sorries"?: [...], "tactics"?: [...], "infotree"?: ...}`. `env` is the resulting Lean environment id (only meaningful if you keep reusing the same REPL). No `messages` key at all means the snippet compiled clean with zero diagnostics (see the `#check Nat` example below, which *does* get an info message).
  - `error: str` on failure/timeout — a plain string, e.g. `"Lean REPL command timed out in 20 seconds"` (server-generated) or a REPL-level parse/crash error.
- `diagnostics` (only present when request `debug=true`): `{"repl_uuid": "<uuid hex>", "cpu_max": <pct of one core>, "memory_max": <bytes>}`.

**Concrete example — `#check Nat`** (this is literally the sync/async client's smoke-test assertion, so it's guaranteed accurate):
```json
POST /api/check
{"snippets": [{"id": "t1", "code": "#check Nat"}], "timeout": 60, "debug": false, "reuse": true}
```
```json
{
  "results": [
    {
      "id": "t1",
      "time": 0.031,
      "response": {
        "messages": [
          {
            "severity": "info",
            "pos": {"line": 1, "column": 0},
            "endPos": {"line": 1, "column": 6},
            "data": "Nat : Type"
          }
        ],
        "env": 1
      }
    }
  ]
}
```

**Example — a proof with an actual Lean error** (from `examples/batch_verify.py`'s documented expected output, using a failing `nlinarith` call):
```json
{
  "custom_id": "1",
  "error": null,
  "response": {
    "messages": [
      {
        "severity": "error",
        "pos": {"line": 8, "column": 0},
        "endPos": {"line": 9, "column": 22},
        "data": "linarith failed to find a contradiction\ncase a\na b c : ℝ\nha : a ≥ 0 ∧ b ≥ 0 ∧ c ≥ 0 ∧ a + b + c = 1\na✝ : 1 / 4 > a ^ 3 + b ^ 3 + c ^ 3 + 15 * a * b * c / 4\n⊢ False\nfailed"
      }
    ],
    "env": 1,
    "time": 1.0048656463623047
  }
}
```
(That particular example is in the legacy `/verify` shape — `custom_id` instead of `id`, and `time` folded *into* `response` rather than sitting beside it. See §3c for why.)

**Example — timeout**, taken from a real match-test fixture (`tests/match/output/goedel-lean_workbook_10036.json`, legacy-shape):
```json
{"custom_id": "lean_workbook_10036", "error": "Lean process timed out", "response": null}
```
The current server's actual generated string (from `server/routers/check.py`) is `f"Lean REPL command timed out in {timeout} seconds"` for a body timeout, or `f"Lean REPL header command timed out in {timeout} seconds"` if the *import header* itself timed out — check for the substring `"timed out"` if you need to branch on timeout vs. other errors (that's exactly what the client's own `ReplResponse.analyze()` does: `if "timed out" in self.error: status = timeout_error`).

**How to classify a result** — port of the client's own logic (`SnippetStatus` in `client/kimina_client/models.py`), useful if you're writing your own httpx client and not using the SDK:
```python
def is_error(resp):        # resp = the "response" dict
    return any(m["severity"] == "error" for m in resp.get("messages") or [])
def has_sorry(resp):
    return bool(resp.get("sorries"))
# status: "valid" if no error and no sorry; "sorry" if sorry and no error; "lean_error" if error present
# top-level "error" string (not "response") -> "timeout_error" if "timed out" in it, else "server_error"
# a "response" dict containing top-level "message" (singular) instead of "messages" -> "repl_error"
```

**Error status codes** (not just 200 + JSON body — real HTTP errors too):
- `401` — API key required and missing/invalid (`WWW-Authenticate`-less `HTTPException(401, "Missing API key")` / `"Invalid API key"`).
- `422` — request body fails pydantic validation (e.g. empty `snippets`, duplicate ids) — standard FastAPI validation-error body.
- `429` — `"No available REPLs"` — REPL pool exhausted and `LEAN_SERVER_MAX_WAIT` elapsed waiting for a free slot (`NoAvailableReplError`).
- `499` — non-standard, custom: client disconnected mid-request (server polls `raw_request.is_disconnected()` every 100ms and cancels the task, killing the REPL that was in use).
- `500` — anything else (REPL failed to start, stdin broken pipe, JSON decode error from the REPL, etc.) — body is `str(exception)`, not a structured schema.

### 3c. `POST /verify` and `POST /one_pass_verify_batch` — legacy/backward-compat endpoint

Same handler (`one_pass_verify_batch` in `server/routers/backward.py`) mounted at both paths, **not** under `/api`. Kept for compatibility with an older "autoformalizer" client wire format that used `proof`/`code` + `custom_id` instead of `code`/`id`.

**Request** (`VerifyRequestBody`):
```json
{
  "codes": [
    {"custom_id": "1234", "proof": "#check Nat"}
  ],
  "timeout": 300,
  "infotree_type": "original",
  "disable_cache": false
}
```
- `codes[i]`: needs `custom_id` (`str | int`) plus **either** `proof` or `code` (both keys accepted, `proof` wins if both present — `Code.get_proof_content()`).
- `timeout` default is **300** here (vs. 30 on `/api/check`).
- `disable_cache: bool` inverts to `reuse = not disable_cache` internally.
- `infotree_type` is the same enum as `infotree` above, just renamed.

**Response** (`VerifyResponse`):
```json
{
  "results": [
    {
      "custom_id": "1234",
      "response": {"env": 1, "time": 0.0110960}
    }
  ]
}
```
Key structural difference from `/api/check`: `time` is merged **inside** `response` (an `ExtendedCommandResponse`/`ExtendedError` = the Lean REPL's own dict plus a bolted-on `"time"` key), and there's no separate `id`/`time` sibling fields — the identifier key is `custom_id`, not `id`. On error, `response` is `null`/absent and `error` holds the string (or `response` becomes `{"message": "...", "time": ...}` for REPL-level errors, since `ExtendedError` wraps `{"message": str}`).

The curl smoke test from `README.md`:
```sh
curl --request POST --url http://localhost/verify \
  --header 'Content-Type: application/json' \
  --data '{"codes": [{"custom_id": "1234", "proof": "#check Nat"}], "infotree_type": "original"}' | jq
```

### 3d. Batch support
Both endpoints are natively batched — one HTTP call, `snippets`/`codes` is a list, and the server runs every element of the batch **concurrently** via `asyncio.gather` (see `run_checks` in `check.py`), each grabbing its own REPL from the pool (up to `LEAN_SERVER_MAX_REPLS` concurrent REPL processes; extra items queue on `LEAN_SERVER_MAX_WAIT`). There's no server-side hard cap on batch size in one request — the practical limit is REPL-pool capacity plus your own HTTP timeout. The Python SDK additionally chunks a big list into sub-batches (`batch_size`, default 8) and fans those batches out across a thread pool / semaphore (`max_workers`, default 5) — that's a client-side convenience, not a server requirement; you can send an arbitrarily large `snippets` array to `/api/check` directly in one httpx POST if you prefer.

---

## 4. Pointing the server at a Mathlib workspace

Two settings in `server/settings.py` (env-prefixed `LEAN_SERVER_`, loaded via `pydantic-settings` from `.env`):
- `LEAN_SERVER_PROJECT_DIR` — path to the Lean 4 project directory (default `mathlib4`, resolved relative to the repo root: `BASE_DIR / "mathlib4"`). This becomes the `cwd` the REPL subprocess is launched in (`server/repl.py`: `asyncio.create_subprocess_exec("lake", "env", settings.repl_path, cwd=settings.project_dir, ...)`), so it must be a real Lake project with a built `.lake` (i.e., you ran `lake build`/`lake exe cache get` there, exactly what `setup.sh` does for `mathlib4`).
- `LEAN_SERVER_REPL_PATH` — path to the compiled `repl` binary (default `repl/.lake/build/bin/repl`, relative to repo root). The launch command is `lake env <repl_path>` run *inside* `PROJECT_DIR` — i.e. the REPL binary itself can live anywhere, but it's executed with Mathlib's Lake environment/toolchain active.

To point at a different/custom Mathlib checkout (e.g. a fork, a pinned commit, or a project that imports Mathlib as a dependency), set both to absolute paths in `.env`:
```
LEAN_SERVER_PROJECT_DIR=/abs/path/to/my_project   # a Lake project with Mathlib in its deps, already `lake build`-ed
LEAN_SERVER_REPL_PATH=/abs/path/to/repl/.lake/build/bin/repl
```
`.env.template` documents this directly: "Uncomment to specify absolute paths to repl binary and project directory (e.g. Mathlib)."

Beyond the workspace-level project dir, **per-request** import control also exists: any snippet's `code` can start with its own `import ...` lines (e.g. `import Mathlib\nimport Aesop\n...`), and `server/split.py::split_snippet` parses those out as a "header" that gets run first in the REPL (see §5) — so you don't need a monolithic global `import Mathlib` baked into the server; each request declares what it needs, and the REPL pool caches/reuses processes keyed by exact header string.

There is also `LEAN_SERVER_INIT_REPLS` — a `dict[header_string, count]` (default `{}`) letting you **pre-warm** N REPL processes per specific header at server startup (`Manager.initialize_repls`), e.g. `{"import Mathlib": 4}` to eagerly pay the `import Mathlib` elaboration cost for 4 REPLs before the first request arrives, rather than paying it lazily/per-request.

---

## 5. How the REPL pool + header/body split works (relevant to perf and correctness)

- `Manager` (`server/manager.py`) keeps `_free`/`_busy` sets of `Repl` objects up to `max_repls` (default `os.cpu_count() - 1`). `get_repl(header, reuse=True)` first tries to find a **free REPL whose already-loaded header matches** the request's header string exactly; if none, and the pool isn't full, it spins up a new one; if the pool is full, it evicts the oldest free REPL (LRU) to make room, or waits (up to `LEAN_SERVER_MAX_WAIT`) if none are free, raising `NoAvailableReplError` → HTTP 429 on timeout.
- Every request's `code` is split by `split_snippet` into `(header, body)`: leading `import ...`/blank lines become the header (with any `import Mathlib*` line hoisted to a canonical single `import Mathlib`, de-duplicated), everything else is the body. The header is run once per REPL (cached across requests with `reuse=True` and a matching header string) via `Manager.prep`; only the body is timed as the response's `time` and is what actually gets executed fresh each call. This is the whole point of the "REPL reuse" optimization in the README's benchmark charts — avoiding re-elaborating `import Mathlib` (which is expensive) on every single proof check.
- Line numbers in `messages`/`sorries` positions are shifted back by the header's line count before being returned (`_apply_header_offset` in `check.py`), so error positions in the response are relative to *your original snippet*, not the REPL's internal post-split body.
- Each Lean REPL command is sent as `{"cmd": ..., "env": 0, "gc": true}` (after the first use on a given REPL) and terminated by a blank line, matching the [`repl` project](https://github.com/leanprover-community/repl)'s own stdin/stdout JSON protocol. `"gc": true` is always set by the server specifically to discard elaboration environments after each command and bound memory growth.
- On a body timeout the whole REPL process is killed (`manager.destroy_repl`), not just the request — so a timeout always costs you a REPL restart (and the next request with that header pays the import cost again).

---

## 6. Auth / API-key handling

- Header-based bearer auth via `server/auth.py`. If `LEAN_SERVER_API_KEY` is **unset** (`None`, the default), `require_key` is a no-op — the server is fully open, no auth required, matching the "no API key" default in the client SDK's docstring.
- If it **is** set, every `/api/check`, `/verify`, `/one_pass_verify_batch` call must send an `Authorization` header (FastAPI `APIKeyHeader(name="Authorization")`); the server does `auth.removeprefix("Bearer ").strip()` then compares equality to `settings.api_key`. So both of these work:
  - `Authorization: Bearer my-api-key`
  - `Authorization: my-api-key` (no `Bearer` prefix — the removeprefix is a no-op if absent, so bare key also matches)
- Missing header when a key is configured → `401 "Missing API key"`. Wrong value → `401 "Invalid API key"`. `/health` has no auth dependency at all.
- There's a scaffolded-but-unused DB-backed key lookup (commented out in `auth.py`) — currently it's always a single static key from settings, not a key table.
- Client side (`client/kimina_client/base.py`): pass `api_key=` explicitly, or set env var `LEAN_SERVER_API_KEY` (or the older alias `LEANSERVER_API_KEY`); the client sets `headers["Authorization"] = f"Bearer {api_key}"` by default (only if you didn't already put `Authorization` in a custom `headers=` dict — `setdefault`).

---

## 7. Throughput / performance knobs

Environment variables (all `LEAN_SERVER_`-prefixed, `.env`/`pydantic-settings`):

| Variable | Default | Effect |
|---|---|---|
| `LEAN_SERVER_MAX_REPLS` | `cpu_count() - 1` | Max concurrent Lean REPL subprocesses (the real concurrency ceiling; extra requests queue). |
| `LEAN_SERVER_MAX_REPL_USES` | `-1` (unlimited) | Kill+recycle a REPL after N uses (header run doesn't count as a "use"). Mitigates any slow memory/state leak inside long-lived REPL processes. |
| `LEAN_SERVER_MAX_REPL_MEM` | `8G` (`.env.template` says `12G`; Dockerfile sets `8G`) | Per-REPL memory cap via `RLIMIT_AS` — **Linux only**, no-op on macOS (§1). Accepts `<int>[M|G]`. |
| `LEAN_SERVER_MAX_WAIT` | `60` (seconds) | How long a request will wait for a REPL to free up before returning `429`. |
| `LEAN_SERVER_INIT_REPLS` | `{}` | Pre-warm `{header: count}` REPLs at startup (§4). |
| `LEAN_SERVER_LEAN_VERSION` | `v4.26.0` | Lean toolchain pinned for `setup.sh`/Docker build. |

Request-level knobs (per `/api/check` call, §3b): `reuse` (skip re-importing headers on a matching warm REPL — the single biggest throughput lever per the README's own "with/without REPL reuse" benchmark charts) and `timeout` (per-snippet ceiling; too low starves valid-but-slow proofs, too high lets one stuck REPL block a pool slot for a long time before the 500/timeout path recycles it).

Server internals that affect throughput but aren't configurable: every command runs with Lean's `"gc": true` (forces environment GC after each check to bound RSS growth — always on, not a flag); `uvicorn.run(..., backlog=4096)` in `server/__main__.py` (OS-level TCP accept backlog, tuned for GCP's `somaxconn=4096`); per-REPL CPU%/RSS are sampled every 1s in background asyncio tasks purely for the optional `debug=true` diagnostics, not for enforcement.

**Client-side throughput gotchas (from the README, verified in code):**
- The **sync** `KiminaClient` opens a brand-new `httpx.Client` per request per worker thread (no shared connection pool across threads — see `_query` in `sync_client.py`). With `max_workers` above your OS's open-file/socket limit you'll hit `[Errno 24] Too many open files` → connection errors → `tenacity` retries → slow, noisy failures. Check with `ulimit -n` (often only 256 on macOS) and raise it (`ulimit -n 4096`) or just use `AsyncKiminaClient`, which shares one `httpx.AsyncClient` session (one real connection pool) across all concurrent requests — README explicitly recommends the async client for benchmarking for this reason.
- Known **open issue** (#58, filed Oct 2025, still open, no maintainer response as of this research): a user on a 128-core/1.5TB box saw frequent 429/500-style timeouts and ~8% error rate even at low client concurrency (`max_workers=4`, `batch_size=4`) with CPU/RAM both under 5% utilization — i.e., there's a reported failure mode where REPL-pool/timeout mechanics misbehave well below hardware limits. Worth budgeting retries/backoff in any client built against this server, and not assuming "idle box ⇒ no timeouts."
- The published Docker image ships all of Mathlib's build artifacts baked in — images are ~2.7–2.9 GB. Cold-start (`docker pull` + container start) is not instant; the REPL pool itself also does lazy header-import on first use per header (unless you set `LEAN_SERVER_INIT_REPLS`), so the very first request(s) against a given import header eat the "cold" `import Mathlib` elaboration cost (can be many seconds) — budget for that separately from steady-state per-proof latency.

---

## 8. Official Python client (`kimina-client`, PyPI 0.2.1)

Two classes, both subclass `BaseKimina` (`client/kimina_client/base.py`) — shared constructor signature:
```python
KiminaClient(api_url: str | None = None, api_key: str | None = None,
             headers: dict[str, str] | None = None,
             http_timeout: int = 600, n_retries: int = 3)
AsyncKiminaClient(same signature)
```
`api_url` falls back to `$LEAN_SERVER_API_URL` then `http://localhost:8000`; `api_key` falls back to `$LEAN_SERVER_API_KEY` then `$LEANSERVER_API_KEY`. Every request retries up to `n_retries` times with exponential backoff (`tenacity`, 1s→10s) on `httpx.HTTPError` or non-JSON responses, raising `RuntimeError("Request failed after N retries")` if exhausted.

Core methods (identical surface on both, `async`/sync):
```python
client.check(snips, timeout=60, debug=False, reuse=True, infotree=None,
             batch_size=8, max_workers=5, show_progress=True) -> CheckResponse
# snips: str | list[str] | Snippet | list[Snippet] — bare strings get a random uuid4-hex id.
# Internally chunks into batch_size-sized lists, fans out over max_workers, calls api_check() per chunk, merges.

client.api_check(snippets: list[Snippet], timeout=30, debug=False, reuse=True,
                  infotree=None, safe=False) -> CheckResponse
# The literal POST {api_url}/api/check wrapper — one HTTP call, no client-side chunking.
# safe=True swallows exceptions into per-snippet ReplResponse(error=str(e)) instead of raising.

client.health() -> dict           # GET /health
client.test() -> None             # sanity check against "#check Nat", asserts exact expected message
client.run_benchmark(dataset_name="Goedel-LM/Lean-workbook-proofs", split="train", n=100,
                      batch_size=8, max_workers=5, timeout=60, reuse=True, show_progress=True) -> None
# Loads a HF dataset (requires `pip install datasets`), infers id/code columns (hardcoded
# mappings for Goedel-LM/Lean-workbook-proofs -> problem_id/full_proof, and
# AI-MO/math-test-inference-results -> (uuid,proof_id)/proof; otherwise fuzzy-matches column
# names or prompts interactively), runs client.check(), prints a colored summary table
# (valid/sorry/lean_error/timeout/repl_error/server_error counts + CPU-time stats) via
# CheckResponse.analyze().
```
`AsyncKiminaClient` additionally needs `await client.close()` to close its `httpx.AsyncClient` session cleanly.

Result objects are real Pydantic models (`CheckResponse.results: list[ReplResponse]`), each with a `.analyze() -> SnippetAnalysis(status, time)` classifier (§3b's status logic) and a colorized `__repr__` for REPL/notebook use. `CheckResponse.merge([...])` concatenates multiple batch responses (used internally to stitch chunked results back into one object) — matches by list order, not by echoing back `id` matches for you, so if you need to correlate responses to your original inputs, key off `ReplResponse.id`, which is preserved verbatim from your request.

Extra dependencies pulled in by the client package itself (not the server): `httpx`, `tenacity`, `tqdm`, `pygments`+`colorama` (pretty console output), `tabulate`, `datasets` (only actually imported inside `run_benchmark`), `loguru`.

Also shipped but not part of the public `__all__` re-export from `kimina_client`: `client/kimina_client/infotree.py` (infotree → per-tactic interval extraction, §3b) and `client/kimina_client/proof_utils.py` (`has_error_response`, `parse_client_response`, `analyze_sample`/`analyze` — helpers written specifically against the *legacy* `BackwardResponse` shape from `/verify`, not `/api/check`'s `ReplResponse`). Import them explicitly (`from kimina_client.infotree import extract_data`) if needed — they aren't in the top-level namespace.

---

## 9. Cheat-sheet for writing your own httpx client (no SDK)

```python
import httpx

BASE = "http://localhost:8000"
API_KEY = None  # or "my-api-key" -> then send headers={"Authorization": f"Bearer {API_KEY}"}

def check(snippets: list[dict], timeout=60, debug=False, reuse=True, infotree=None) -> dict:
    """snippets: [{"id": "...", "code": "..."}], unique ids required."""
    payload = {"snippets": snippets, "timeout": timeout, "debug": debug,
               "reuse": reuse, "infotree": infotree}
    headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}
    with httpx.Client(timeout=httpx.Timeout(600, read=600)) as client:
        r = client.post(f"{BASE}/api/check", json=payload, headers=headers)
        r.raise_for_status()          # 401/422/429/499/500 all raise here
        return r.json()               # {"results": [{"id","time","response"|"error","diagnostics"?}]}
```
Key semantics to encode in a wrapper:
1. `results[i]` corresponds 1:1 to `snippets[i]` by list position; also carries `id` back for safety.
2. Exactly one of `response`/`error` is populated per result — check `error is not None` first.
3. `response.get("messages")` absent or empty ⇒ clean compile; any entry with `severity=="error"` ⇒ Lean-level failure (not an HTTP failure — you still got `200 OK`); non-empty `response.get("sorries")` with no error message ⇒ statement type-checks but proof is incomplete (`sorry`).
4. Treat HTTP `429` as "pool full, retry with backoff" and `499`/client-side timeout as "you gave up, no REPL state to trust." A `500` may leave a REPL destroyed server-side (that's intentional cleanup, not a symptom to work around).
5. Point the server at your own Mathlib checkout with `LEAN_SERVER_PROJECT_DIR`/`LEAN_SERVER_REPL_PATH` env vars (§4) rather than assuming the bundled `./mathlib4`.
6. On macOS, run from source (`python -m server`), not the published Docker image (amd64-only) — and don't rely on `LEAN_SERVER_MAX_REPL_MEM` to bound memory there.

---

## Sources
- [project-numina/kimina-lean-server](https://github.com/project-numina/kimina-lean-server) — `README.md`, `README-client.md`, `AGENTS.md`, `Dockerfile`, `setup.sh`, `compose.yaml`, `compose-dev.yaml`, `.env.template`, `server/main.py`, `server/settings.py`, `server/auth.py`, `server/manager.py`, `server/repl.py`, `server/split.py`, `server/errors.py`, `server/routers/check.py`, `server/routers/backward.py`, `server/routers/health.py`, `client/kimina_client/{base,models,sync_client,async_client,utils,infotree,proof_utils,__init__}.py`, `tests/match/**`, `tests/perfs/test_perfs.py`, `.github/workflows/{ci,cd-server,cd-client}.yaml`, `examples/batch_verify.py`, `pyproject.toml` — all fetched at `main` on 2026-08-11.
- [Kimina Lean Server: Technical Report (arXiv:2504.21230)](https://arxiv.org/abs/2504.21230)
- [PyPI: kimina-client](https://pypi.org/project/kimina-client/) — version/release history.
- [Docker Hub: projectnumina/kimina-lean-server](https://hub.docker.com/r/projectnumina/kimina-lean-server) — tag/architecture manifest data via the Docker Hub v2 API.
- [GitHub Issue #58 — Frequent Request Timeout Despite Idle CPU and Memory](https://github.com/project-numina/kimina-lean-server/issues/58) (open, unresolved at research time).
