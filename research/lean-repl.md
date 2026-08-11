# `leanprover-community/repl` — protocol, build/run, and setup commands

Researched as of 2026-08-11 against `leanprover-community/repl` master branch
(`lean-toolchain` pinned there: `leanprover/lean4:v4.34.0-rc1`), the
`leanprover-community/mathlib4` wiki, and the Lean reference docs. Source
excerpts below (`README.md`, `REPL/JSON.lean`, `REPL/Main.lean`) are
reproduced/quoted under the repo's Apache-2.0 license.

---

## 1. Wire protocol: framing

- Run with `lake exe repl` (or, from another project, `lake env <path-to-repl-binary>` — see §3).
- Transport is **JSON on stdin/stdout**. This is a REPL, not one-shot: keep
  the process alive and pipe multiple commands into the same stdin.
- **Framing rule (from `REPL/Main.lean`):** the REPL reads stdin **line by
  line and accumulates lines until it sees a blank line**:

  ```lean
  partial def getLines : IO String := do
    let line ← (← IO.getStdin).getLine
    if line.trimAscii.isEmpty then
      return line
    else
      return line.trimAsciiEnd.toString ++ (← getLines)
  ```

  Practical consequence: a command is normally written as **one line of
  compact JSON followed by one blank line**, but you are *not* required to
  put the JSON on a single physical line — you may split it across several
  physical lines as long as no blank line appears until you intend to
  terminate the command (the raw lines are concatenated, unparsed, before
  being handed to `Json.parse`).
- **EOF vs. blank line:** `IO.getLine` returns `""` (not `"\n"`) at EOF. A
  bare empty line still trims to `""`, so — importantly — **both a blank
  line and EOF terminate `getLines` the same way**, but the *main loop*
  additionally checks `if query = "" then return ()`, i.e. **EOF (empty
  concatenated query) exits the whole REPL process.** A blank-line-delimited
  but otherwise non-empty query proceeds to parsing. In other words: send
  `<json>\n\n` to submit one command and keep the process alive; closing
  stdin (or sending nothing before EOF) ends the session.
- **Comment lines:** a line starting with `#` or `--` causes the loop to
  skip and re-loop without emitting any output.
- **Output framing:** after each response the REPL does
  `IO.println <json>` followed by `printFlush "\n"` — i.e. **one line of
  JSON, then an explicitly flushed blank line**, mirroring the input
  framing. This makes it safe for a driver to read "until blank line" on
  both stdin and stdout. `printFlush` matters because Lean's stdout can
  otherwise be block-buffered, which would hang a naive driver waiting for
  a response that's sitting in a buffer.
- **Malformed input:** invalid JSON, or JSON that doesn't match any known
  command shape, produces `{"message": "Could not parse JSON:\n<err>"}` or
  `{"message": "Could not parse as a valid JSON command:\n<err>"}`
  respectively (the `Error` structure — see §2.6), thrown via
  `IO.userError` and printed like any other response. It does **not** crash
  the process.
- Dispatch on which "command kind" a JSON object is happens by **trying
  `fromJson?` against each candidate structure in a fixed priority order**
  (not by switching on a field name): `ProofStep` → `PickleEnvironment` →
  `UnpickleEnvironment` → `PickleProofState` → `UnpickleProofState` →
  `Command` → `File`. This matters if you ever send an object that could
  structurally satisfy two shapes — the earlier one in that list wins.

---

## 2. Message/request shapes (from `REPL/JSON.lean`, exact field names)

### 2.1 `Command` (command mode) — request

```lean
structure CommandOptions where
  allTactics : Option Bool := none
  rootGoals  : Option Bool := none
  infotree   : Option String   -- "full" | "tactics" | "original" | "substantive"

structure Command extends CommandOptions where
  env : Option Nat
  cmd : String
```

- `cmd`: a complete Lean command/declaration (string).
- `env`:
  - **absent** → a **fresh environment** is created; `import` statements are
    only legal in this case.
  - **present** (must equal an `env` value returned by a *previous*
    response) → the command elaborates on top of that existing
    `Environment`. This is also how you **backtrack**: just reuse an older
    `env` number instead of the most recent one — nothing is mutated in
    place, environments are immutable snapshots addressed by id.
- `allTactics`: if true, also populate `tactics` (per-tactic goal states) in
  the response for this command, not just for file mode.
- `rootGoals`, `infotree`: optional extras (info-tree capture mode is one of
  the four listed strings; anything else is ignored).

Two request examples straight from the README:
```json
{ "cmd" : "def f := 2" }
```
```json
{ "cmd" : "example : f = 2 := rfl", "env" : 1 }
```

### 2.2 `File` (file mode) — request

```lean
structure File extends CommandOptions where
  env  : Option Nat
  path : System.FilePath
```

Wraps command mode over a whole `.lean` file:
```
echo '{"path": "test/file.lean", "allTactics": true}' | lake exe repl
```
gives, for a 4-line file ending in a `by exact rfl` proof:
```json
{"tactics":
 [{"tactic": "exact rfl",
   "proofState": 0,
   "pos": {"line": 5, "column": 29},
   "goals": "⊢ f + g = 39",
   "endPos": {"line": 5, "column": 38}}],
 "env": 0}
```

### 2.3 `ProofStep` (tactic mode, experimental) — request

```lean
structure ProofStep where
  proofState : Nat
  tactic     : String
```
```json
{"tactic": "apply Int.natAbs", "proofState": 0}
```
Response is a `ProofStepResponse` (§2.5) carrying a **new** `proofState` id
to chain further tactics from. Enter tactic mode by first sending a `cmd`
containing a `sorry`; the initial `sorries[].proofState` is your entry
point. `sorry` may also appear *inside* a tactic-mode step, producing
further `proofState` ids in the resulting `sorries` list. There is
currently no way to "export" a finished tactic-mode proof back into an
`Environment`/replace the original `sorry` (explicitly listed as future
work) — command mode and tactic mode are one-way linked (`cmd` → `sorries[].proofState` → tactic mode), not round-trippable.

### 2.4 Common value types

```lean
structure Pos where
  line : Nat
  column : Nat

inductive Severity
  | trace | info | warning | error

structure Message where
  pos : Pos
  endPos : Option Pos
  severity : Severity   -- serialized as "trace" | "info" | "warning" | "error"
  data : String

structure Sorry where
  pos : Pos
  endPos : Pos
  goal : String
  proofState : Option Nat

structure Tactic where
  pos : Pos
  endPos : Pos
  goals : String
  tactic : String
  proofState : Option Nat
  usedConstants : Array Name
```

Note: Lean's own `.error`/`.warning`/`.information` severities map to JSON
`"error"`/`"warning"`/`"info"` — `"info"` not `"information"`.

### 2.5 Response shapes

```lean
structure CommandResponse where
  env : Nat
  messages : List Message := []
  sorries  : List Sorry   := []
  tactics  : List Tactic  := []
  infotree : Option Json := none
```
Custom `ToJson` instance **omits empty lists entirely** rather than emitting
`[]` — i.e. `messages`/`sorries`/`tactics` keys are simply absent from the
JSON when there's nothing to report, and `infotree` is absent when `none`.
Only `env` is always present. This matches the README example:

```json
{"sorries":
 [{"pos": {"line": 1, "column": 18},
   "endPos": {"line": 1, "column": 23},
   "goal": "⊢ Nat",
   "proofState": 0}],
 "messages":
 [{"severity": "error",
   "pos": {"line": 1, "column": 23},
   "endPos": {"line": 1, "column": 26},
   "data": "type mismatch\n  rfl\nhas type\n  f = f : Prop\nbut is expected to have type\n  f = 2 : Prop"}],
 "env": 6}
```

A clean command with no sorries/messages/tactics returns just `{"env": N}`.

```lean
structure ProofStepResponse where
  proofState : Nat
  goals : List String
  messages : List Message := []
  sorries : List Sorry := []
  traces : List String
  proofStatus : String
```
Example chain (from README), showing tactic mode entry via a `sorry`, then
two tactic steps to a closed goal:
```json
{"cmd" : "def f (x : Unit) : Nat := by sorry"}

{"sorries":
 [{"proofState": 0,
   "pos": {"line": 1, "column": 29},
   "goal": "x : Unit\n⊢ Nat",
   "endPos": {"line": 1, "column": 34}}],
 "messages":
 [{"severity": "warning",
   "pos": {"line": 1, "column": 4},
   "endPos": {"line": 1, "column": 5},
   "data": "declaration uses 'sorry'"}],
 "env": 0}

{"tactic": "apply Int.natAbs", "proofState": 0}

{"proofState": 1, "goals": ["x : Unit\n⊢ Int"]}

{"tactic": "exact -37", "proofState": 1}

{"proofState": 2, "goals": []}
```
(`goals: []` signals the goal is closed. The response objects here elide
`messages`/`sorries`/`traces`/`proofStatus` when empty, same omission rule
as `CommandResponse`; `proofStatus` in the fuller schema is a string status
tag — expect values describing e.g. an open/completed/sorry-containing
state.)

### 2.6 Error

```lean
structure Error where
  message : String
```
Emitted on unparseable input as `{"message": "Could not parse JSON:\n..."}`
etc. (§1).

### 2.7 Pickling (save/restore environments and proof states as `.olean`)

Requests:
```lean
structure PickleEnvironment where
  env : Nat
  pickleTo : System.FilePath

structure UnpickleEnvironment where
  unpickleEnvFrom : System.FilePath

structure PickleProofState where
  proofState : Nat
  pickleTo : System.FilePath

structure UnpickleProofState where
  unpickleProofStateFrom : System.FilePath
  env : Option Nat
```
```json
{"pickleTo": "path/to/file.olean", "env": 7}
{"pickleTo": "path/to/file.olean", "proofState": 17}
{"unpickleEnvFrom": "path/to/file.olean"}
{"unpickleProofStateFrom": "path/to/file.olean"}
```
Unpickle responses report a fresh `env`/`proofState` id usable in later
commands, same as any other response. Portable across machines given the
same imports are available; stores only diffs relative to imports (not a
full `Environment`), unpickling uses `mmap`, files are small (optionally
compress further with the external `leangz` tool). Known gap: scoped
environment extensions (e.g. scoped notations) created mid-session are not
correctly round-tripped.

---

## 3. Building against a project's toolchain and running via `lake env`

The REPL is its own Lake package (`lakefile.toml`, confirmed on master):

```toml
name = "REPL"
defaultTargets = ["repl"]
testDriver = "test"

[[lean_lib]]
name = "REPL"

[[lean_exe]]
name = "repl"
root = "REPL.Main"
supportInterpreter = true

[[lean_exe]]
name = "test"
root = "Test"
```

It has **no `require` of Mathlib itself** — it only needs Lean core plus the
`Lean` toolchain's own libraries to *build the REPL binary*. What has to
match your target project is the **Lean toolchain version** (the compiled
binary is toolchain/ABI-specific), not a Mathlib dependency of the REPL
package.

Canonical procedure (from the README's "Using the REPL from another
project" section):

1. In *your* project (e.g. a Mathlib-dependent project created per §4a),
   confirm `lake build` works.
2. Clone `leanprover-community/repl` separately, **make its
   `lean-toolchain` match your project's** (simplest: copy the file over —
   `cp your_project/lean-toolchain repl/lean-toolchain`), then `lake build`
   inside the `repl` checkout. This produces
   `repl/.lake/build/bin/repl`.
3. Run the REPL **from inside your project directory**, prefixed with
   `lake env`, pointing at the binary built in step 2:
   ```shell
   lake env ../path/to/repl/.lake/build/bin/repl < commands.in
   ```
   `lake env` sets up the environment (`LEAN_PATH` etc.) associated with
   *your* project — that's what lets the REPL binary resolve
   `import Mathlib...` and friends when you send `{"cmd": "import Mathlib"}`
   (or a curated subset import) as the first command in a fresh
   environment. Interactive use is identical, just without redirecting a
   file into stdin — keep the process attached and write JSON commands to
   its stdin as described in §1.

This is precisely the local repo's approach in `scripts/setup_lean.sh`:
build `rlmathlib` (the Mathlib-dependent project) first, copy
`rlmathlib/lean-toolchain` into a separate `repl/` checkout, `lake build`
there, then invoke the resulting binary with `lake env` **from within
`rlmathlib`**, e.g.:
```shell
cd lean/rlmathlib && lake env ../repl/.lake/build/bin/repl
```
(The script's current step 4 is only a placeholder marker — it doesn't yet
actually invoke `lake env ... repl`; the real invocation belongs in the
Python driver / integration test, per the script's own comment.)

---

## 4. Canonical setup commands — verification against Aug 2026 sources

### 4a. New Lean 4 project depending on Mathlib

**Command in question:**
```
lake +leanprover-community/mathlib4:lean-toolchain new NAME math.toml
```

**Verdict: this is correct, not a bug.** Confirmed directly from the
locally installed `lake help new` (elan toolchain
`leanprover--lean4---v4.34.0-rc1`, i.e. Lean `v4.34.0-rc1`, matching what
the running setup actually downloaded):

```
Create a Lean package in a new directory

USAGE:
  lake [+<lean-version>] new <name> [<template>][.<language>]

The initial configuration and starter files are based on the template:

  std                   library and executable; default
  exe                   executable only
  lib                   library only
  math-lax              library only with a Mathlib dependency
  math                  library with Mathlib standards for linting and workflows

Templates can be suffixed with `.lean` or `.toml` to produce a Lean or TOML
version of the configuration file, respectively. The default is TOML.
```

So `lake new NAME <template>[.<language>]` is a **single grammar**: the
argument is a template name optionally suffixed with `.lean` or `.toml` to
pick the config-file language. `math.toml` parses as **template=`math`,
language=`toml`** — a perfectly valid, explicit way of asking for exactly
what's already the default language. It is exactly equivalent (today) to
plain `math`, and to `math.lean` except for producing `lakefile.lean`
instead of `lakefile.toml`. It is **not** "a `.toml` file named
`math.toml`" and it is **not invalid syntax** — that reading would be a
false alarm.
- The `leanprover-community/mathlib4` wiki page "Using mathlib4 as a
  dependency" (last edited 2025-05-17) gives the bare form without the
  suffix:
  ```
  lake +leanprover-community/mathlib4:lean-toolchain new <your_project_name> math
  ```
  It also front-loads a version check: `elan --version` should be `2.0.0`
  or newer (`elan self update` if not) before running this.
- The `+leanprover-community/mathlib4:lean-toolchain` prefix tells elan/lake
  to resolve and use whatever Lean toolchain Mathlib's own
  `lean-toolchain` file currently names, so the new project starts out
  toolchain-matched to current Mathlib — this is the right idiom and is
  exactly what the running process picked up (it resolved to and installed
  `v4.34.0-rc1`).
- `math` (vs. `math-lax`) additionally wires up Mathlib's linting/workflow
  conventions; `math-lax` is Mathlib-dependent but skips those extras. Both
  produce a `lakefile.toml` that already contains a `require` of
  `leanprover-community/mathlib`.
- No action needed on the currently-running `lake new rlmathlib math.toml`
  process — let it finish. (It was mid-clone of `mathlib4` at the time of
  this check, per `logs/setup_lean.log` and a live `ps aux` snapshot showing
  the `lake new` and `git clone .../mathlib4` child processes.)

**Minor, non-blocking observations on the script** (`scripts/setup_lean.sh`):
- The comment "`math.toml` is the lake template that adds the Mathlib
  dependency" is *slightly* imprecise — `math` is the template; `.toml` is
  the (already-default) config-language suffix — but the command itself is
  correct as written, so this is a documentation nit, not a bug.
- Existing-project alternative (not needed here since `lake new ... math`
  already wires it up), for completeness: adding to `lakefile.toml`
  ```toml
  [[require]]
  name = "mathlib"
  scope = "leanprover-community"
  ```
  or, for a `lakefile.lean`, `require "leanprover-community" / "mathlib"`.

### 4b. Fetching the Mathlib olean cache

`lake exe cache get` is confirmed current and correct, run from inside the
Mathlib-dependent project directory (i.e. `rlmathlib/`, after the `require`
is in place) and **before** `lake build`:
- Mathlib README: "To obtain precompiled `olean` files, run
  `lake exe cache get`. (Skipping this step means the next step will be
  very slow.)"
- Wiki: same command, with expected output like "Decompressing 5000
  file(s)" or more.
- Related variants: `lake exe cache get!` force-redownloads even if
  locally present; `lake exe cache clean`/removing `.lake` + `lake clean`
  are the recommended recovery steps if the cache gets into a bad state;
  bare `lake exe cache` prints its own help.
- Precondition worth double-checking: the project's toolchain must match
  Mathlib's toolchain (true here, since `lake new ... math` derived the
  toolchain from Mathlib directly), otherwise cached `.olean`s won't be
  binary-compatible and `cache get` effectively can't help.
- The script's order (`cache get` → `lake build`) is the right order.

---

## 5. `#print axioms foo` — exact current output format

Confirmed against the current Lean reference docs (`lean-lang.org/doc/reference/latest/Axioms/`).

**Case A — depends on one or more axioms:**
```
'excluded_middle' depends on axioms: [propext, Classical.choice, Quot.sound]
```
General shape: `'<name>' depends on axioms: [<comma-separated names>]`.
Single-axiom example: `'simple_equality' depends on axioms: [propext]`.
This is what virtually every nontrivial Mathlib-based theorem prints,
listing exactly `propext`, `Classical.choice`, `Quot.sound` (Lean's three
standard/foundational axioms) when nothing unusual (like `sorry` or
`native_decide`) was used.

**Case B — depends on no axioms at all:**
```
'addThree' does not depend on any axioms
```
Exact shape: `'<name>' does not depend on any axioms`.

**Case C — incomplete proof (contains `sorry`):**
```
'lazy' depends on axioms: [sorryAx]
```
`sorryAx {α : Sort u} (synthetic := true) : α` can prove anything, so its
presence in `#print axioms` output is the standard sound/complete-proof
check: **a real, checked, axiom-clean theorem must print exactly the
allowed foundational axiom set and must never contain `sorryAx`** — i.e.
verification logic should treat any occurrence of `sorryAx` in the printed
list as "not actually proved," regardless of what else is in the bracket.

**Delivery through the REPL protocol:** sending
`{"cmd": "#print axioms foo", "env": N}` surfaces this exact string as a
single `Message` in the response's `messages` array with
`"severity": "info"` (Lean's `#print` output is an `.information`-severity
message, serialized to JSON as `"info"`, not `"information"`) — e.g.:
```json
{"messages":
 [{"severity": "info",
   "pos": {"line": 1, "column": 0},
   "endPos": {"line": 1, "column": 20},
   "data": "'foo' depends on axioms: [propext, Classical.choice, Quot.sound]"}],
 "env": N}
```
There is no separate structured field for axiom names — a driver that
wants to programmatically check "no `sorryAx`, only the standard three"
must parse this `data` string (e.g. regex out the bracketed list after
`depends on axioms: ` and check it against the allowed set, or check for
the literal `does not depend on any axioms` success case with an empty
allowed set).

**Known limitation (not specific to current-date changes, but relevant to
verification logic):** `Lean.collectAxioms` (which backs `#print axioms`)
does not transitively collect axioms referenced *by other axioms* — e.g. a
proof closed with `native_decide` can show `Lean.ofReduceBool` in the list
without also pulling in `Lean.trustCompiler`, which `ofReduceBool` itself
depends on. Worth keeping in mind if the training/verification pipeline
treats "axiom set ⊆ {propext, Classical.choice, Quot.sound}" as the
soundness gate — `native_decide` usage can slip through with a
misleadingly small-looking axiom list.

---

## 6. Summary for a driver implementation

- Keep one long-lived `repl` (or `lake env ... repl`) subprocess per
  worker; do not spawn per-command.
- Protocol unit = one line of compact JSON + `\n\n` on stdin; read stdout
  until a blank line to get the matching response line.
- First command in a session: `{"cmd": "import Mathlib"}` (or a narrower
  import) with **no `env` field** → note the returned `env` id.
- All subsequent commands in that "session": include `"env": <that id>`
  (or any later id you got back) to build on top of it; reuse an *older*
  id to backtrack/branch without re-importing.
- To get a checkable goal: send a `cmd` containing `sorry` at the point you
  want to prove; read `sorries[0].proofState`; drive tactics via
  `{"tactic": ..., "proofState": ...}`; success = final response has
  `"goals": []`.
- To verify soundness post-hoc, run `#print axioms <name>` as a `cmd` in
  the same/child `env` and pattern-match the `messages[].data` string per
  §5 — treat anything containing `sorryAx` as unproved, and be aware
  `native_decide`-closed proofs need extra scrutiny per the axiom-collection
  limitation above.
- Malformed JSON you send doesn't crash the process — it comes back as
  `{"message": "Could not parse..."}"`; handle it as a retryable protocol
  error rather than treating the whole subprocess as dead.
