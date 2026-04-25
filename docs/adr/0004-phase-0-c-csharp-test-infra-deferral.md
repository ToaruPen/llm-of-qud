# ADR 0004: Defer C# unit-test infrastructure for Phase 0-C AppendJsonString to Phase 2a

Status: Accepted (2026-04-25)

## Context

Phase 0-C will introduce a JSON state line emission alongside the existing
ASCII screen block, formatted as
`[LLMOfQud][state] {"turn":N,"hp":[...],"pos":{...},"entities":[...]}` and
written via `MetricsManager.LogInfo`. The JSON will be assembled by a new
helper file `mod/LLMOfQud/SnapshotState.cs` and emitted through the
existing Phase 0-B `AfterRenderCallback` request/emit path (per ADR 0002).

Inside `SnapshotState`, a `StringBuilder`-based helper
`AppendJsonString(StringBuilder, string)` will be needed to escape
arbitrary CoQ display strings into JSON-safe form (handling `\\`, `\"`,
`\b`, `\f`, `\n`, `\r`, `\t`, U+0000..U+001F, and U+2028/U+2029). CoQ
display names route through `Render.DisplayName` and `GetDisplayNameEvent`
(`decompiled/XRL.World/GameObject.cs:677-686, 6402-6421`); short forms,
including `ShortDisplayNameStripped`, are available at `:755-766`. Names
are content-driven: the input distribution to `AppendJsonString` is not
bounded by anything Phase 0-C acceptance can enumerate.

`AppendJsonString` is the one cleanly pure-functional seam in Phase 0-C
(Codex advisor 2026-04-25 review of Q5). Every other observation surface
(`The.Player`, `Zone.GetObjects()`, `Cell.X/Y`, `obj.IsVisible()`,
`obj.IsHostileTowards`, `Render`, `Options.UseTiles`) is bound to the CoQ
runtime and cannot be exercised outside it.

In principle a C# xUnit test could pin the escape table down with
synthetic inputs the manual acceptance run would never hit. In practice
the project has no C# test runner today:

- The mod is authored as bare `.cs` files compiled in-process by CoQ via
  `RoslynCSharpCompiler.CompileFromFiles` (`decompiled/XRL/ModInfo.cs:478,
  757-823`). `mod/AGENTS.md:5-21` forbids placing a `.csproj` inside
  `mod/LLMOfQud/` (a sibling `.csproj` outside the mod directory is
  allowed but not currently present).
- The C# CI workflow `.github/workflows/ci-cs.yml:23-32, 64-68` short-
  circuits to "no .csproj found, skipping" when nothing matches
  `mod/**/*.csproj`. Activating it requires introducing a side `.csproj`
  plus a test runner (xUnit/nunit) plus a CI gate invocation.
- Python `pytest` (`pyproject.toml:42, 130, 138-141`) is the only test
  runner currently wired and cannot execute C# directly.
  `tests/test_adr_decision_scripts.py` is the only non-Phase-0 test file,
  scoped to ADR scripts.
- `agents/references/testing-strategy.md:7-18, 49-52, 55-60, 87` declares
  game-as-harness as the primary MOD verification strategy, allows pure-
  external xUnit only for stateless helpers, and explicitly accepts
  manual-only verification when the decision is flagged.

Codex advisor (2026-04-25, second review of Q5) accepted the deferral on
record, with the trigger conditions enumerated below.

## Decision

Phase 0-C SHIPS `AppendJsonString` as production code in
`mod/LLMOfQud/SnapshotState.cs`, written defensively to handle the full
JSON escape table including U+0000..U+001F and U+2028/U+2029. Phase 0-C
DOES NOT introduce a C# unit-test runner (.csproj, xUnit/nunit, dotnet
test in CI) for that helper.

In place of unit tests, Phase 0-C acceptance includes a manual JSON
validity check: extract the latest `[LLMOfQud][state]` payload from
`Player.log` after the acceptance run and pipe it to
`python3 -c "import sys, json; json.loads(sys.stdin.read())"` to confirm
the line is parseable JSON. The acceptance command is required to parse
the **latest single** `[LLMOfQud][state]` line, not pipe a multi-grep
result through `json.loads` in bulk.

Re-open conditions (any one re-opens this decision and forces a unit-test
or equivalent infrastructure investment **before the phase that triggered
it can rely on AppendJsonString**):

1. `AppendJsonString` moves from log-only emission to a
   WebSocket/protocol boundary (Phase 1 `tool_call/tool_result` envelope
   per `docs/architecture-v5.md:2399-2419` is the most likely trigger).
2. The Python Brain begins auto-consuming Phase 0-C JSON state lines
   programmatically (i.e., the line crosses from "manual acceptance log"
   to "machine-parsed input").
3. The state JSON gains user-entered or dynamic free text that the manual
   acceptance run cannot reasonably enumerate (modal text, conversation
   transcripts, player-authored notes, zone-name templating output).
4. JSON invalidity is observed once by the prescribed latest-single-line
   acceptance check in a fresh manual run, after stripping the
   `Player.log` prefix and ruling out extraction or truncation error.
   Single attributable occurrence is sufficient — escape bugs do not
   stay isolated.
5. A C# test harness lands in Phase 2a/2b (the original Phase 0-I
   harness/crash-dashboard work moved to Phase 2b per
   `docs/architecture-v5.md:2806-2809`; Phase 2b scope is
   `docs/architecture-v5.md:2934-2957`). At that point the runner cost
   is already amortized; `AppendJsonString` SHOULD be cherry-picked into
   it as the first unit test.
6. `AppendJsonString` gains a second production call site outside Phase
   0-C state-line emission, or its escape table is materially changed
   after initial acceptance.

## Alternatives Considered

- **Introduce a sibling `LLMOfQud.Tests/` `.csproj` (outside the mod
  directory) with xUnit and wire `dotnet test` into `ci-cs.yml`** —
  rejected. The runner cost is not amortized: the test would be the only
  test, and the workflow would gain its first non-skip code path. Scope
  creep mid-Phase 0.
- **Implement `AppendJsonString` in Python and unit-test it there, then
  transliterate to C#** — rejected. Two implementations of the same
  escape rules drift on every change. Maintenance cost outweighs the
  test value for a function that is ~30 lines.
- **Standalone `csc`-compiled probe in `scripts/`** — rejected. No
  toolchain in the repo runs `csc` from CI or pre-commit. Adding one is
  a larger investment than the .csproj path.
- **Run a script-style C# probe via `csi`, `dotnet-script`, or Roslyn
  scripting from pre-commit/CI** — rejected. None of those runners is
  currently wired in this repo, and making them deterministic in CI
  still adds SDK/package bootstrap plus a new gate.
- **Roslyn analyzer / static rule for JSON escaping** — rejected. An
  analyzer could require call sites to use `AppendJsonString`, but it
  cannot prove the helper's escape table is semantically correct for
  arbitrary runtime strings.
- **Skip `AppendJsonString` entirely and use string interpolation with
  manual escaping at call sites** — rejected. Caller-side escaping
  duplicates the work, and the failure mode (one missed escape produces
  invalid JSON) is exactly what the helper exists to prevent. The
  defensive helper is the safer base case.

## Consequences

### Positive

- Phase 0-C ships with no test-infrastructure prerequisites. The plan can
  proceed entirely within the existing manual-acceptance + Roslyn-compile
  + Player.log-grep loop that 0-A and 0-B established.
- The deferral has explicit, mechanical re-open triggers. Future phases
  can self-check whether they fire any condition without re-deriving the
  rationale.
- The seam (`AppendJsonString` as a pure helper) is preserved. When
  Phase 2a/2b lands the C# harness, the unit test cherry-picks in cleanly.

### Negative / Carry-forward

- Rare-character coverage (U+0000..U+001F, isolated surrogates, U+2028,
  U+2029, escape edge cases) rests on defensive code review, not
  enumerated test cases. A bug here can ship undetected until either the
  manual JSON-validity step happens to encounter it or one of the re-open
  triggers fires.
- The acceptance command must be authored carefully. Multi-line greps
  bulk-piped to `json.loads` will erroneously appear to fail or pass.
  Phase 0-C plan body MUST specify: take the **latest** `[LLMOfQud][state]`
  line only, then `json.loads` it.
- This is a second precedent (after ADR 0003) for closing/deferring a
  testing-or-acceptance criterion via design decision rather than
  empirical PASS. Future agents may anchor on the precedent. Keeping
  re-open triggers explicit is the mitigation.

## Related Artifacts

- `docs/architecture-v5.md:2800` — Phase 0-C scope (HP, position, zone,
  entities)
- `docs/architecture-v5.md:2399-2419` — Phase 1 wire envelope (re-open
  trigger 1)
- `docs/architecture-v5.md:2806-2809` — original Phase 0-I → 2-M move
  (re-open trigger 5 source)
- `docs/architecture-v5.md:2934-2957` — Phase 2b scope (re-open trigger
  5 destination)
- `agents/references/testing-strategy.md` — game-as-harness preferred,
  manual-only allowed when justified (this ADR is the justification)
- `mod/AGENTS.md:5-21` — `.csproj`-in-mod-directory prohibition; sibling
  `.csproj` outside the mod directory is allowed
- `.github/workflows/ci-cs.yml:23-32, 64-68` — current C# CI skip-when-no-
  .csproj logic
- `pyproject.toml:42, 130, 138-141` — Python test runner scope
- `decompiled/XRL/ModInfo.cs:478, 757-823` — Roslyn compile flow
- `decompiled/XRL.World/GameObject.cs:677-686, 755-766, 6402-6421` —
  display name surfaces feeding `AppendJsonString`
- `docs/adr/0002-phase-0-b-render-callback-pivot.md:55-66, 106-108` —
  Phase 0-B render-callback request/emit path extended by Phase 0-C
- (To be created in same change) `mod/LLMOfQud/SnapshotState.cs` —
  implementation of `AppendJsonString` and Phase 0-C state extraction

## Supersedes

None.
