# testing-strategy.md
# Purpose: Full testing policy for llm-of-qud.
# Referenced from: root AGENTS.md, brain/AGENTS.md.

## Tiers

### Tier 1: Game-as-harness (preferred for MOD behavior)

The MOD includes a scripted test mode (Phase 2+):
1. CoQ launches in test mode (config flag or env var).
2. MOD embarks with a fixed build/save.
3. MOD runs N turns of scripted actions.
4. MOD asserts invariants in-process and writes structured results to `Player.log`.
5. CoQ exits cleanly.

This is the only test tier that exercises `The.Game`, `XRLCore.Core`, `GameManager.Instance`,
and the event bus. It is not a nice-to-have; it is the primary regression path.

Use manual in-game verification only for:
- UI appearance judgements
- One-off acceptance checks that are too narrow to automate (e.g., Phase 0-A reload test)

### Tier 2: Pure Python unit tests (brain/)

Applicable to stateless helpers: JSON parsers, tool-schema validators, data transformations.
Do not attempt to import or mock the CoQ runtime from Python.

Command: `uv run pytest tests/`

### Tier 3: Reference compile probe (optional, non-blocking)

A throwaway test project that references CoQ's bundled `Assembly-CSharp.dll`
to verify our namespaces resolve. Proves compile-time compatibility only, never
runtime behavior. Useful in Phase 0-B+ for early type-check of new C# modules.

Reference DLL:
```
~/Library/Application Support/Steam/steamapps/common/Caves of Qud/
  CoQ.app/Contents/Resources/Data/Managed/Assembly-CSharp.dll
```

## What is Not Viable

- **Headless / batch-mode smoke for CoQ**: no `-batchmode` test-runner path exists.
  Known CLI args: `NOMETRICS`, `-SAVEPATH`, `-SHAREDPATH`, `-SYNCEDPATH`, `STEAM:NO`,
  `GALAXY:NO`. None triggers a test runner.
  Source: `docs/memo/test-strategy-codex-research-2026-04-23.md`

- **Pure external C# unit tests as primary strategy**: miss anything touching
  `The.Game`, `XRLCore.Core`, `GameManager.Instance`, events, or any game state.
  Acceptable only for isolated parsers and pure-math helpers.

## Phase Mapping

| Phase | Test approach |
|-------|--------------|
| 0-A | Manual in-game (log grep) |
| 0-B+ | Manual in-game + optional compile probe |
| 1 | Python pytest for Brain, manual for WebSocket protocol |
| 2a | Game-as-harness scripted test mode introduced |
| 2b | Micro-eval fixture suite (spec: arch-v5.md §Phase 2b, task 2-M) |
| 3+ | N-run evaluation infrastructure (arch-v5.md §Phase 3) |

## Acceptance Criteria Checklist Format

Each task ends with:
- One narrow acceptance criterion
- A specific `grep` pattern or command to verify it

Example:
```bash
# Load-probe via Logger.buildLog.Info → build_log.txt
grep -c "\[LLMOfQud\] loaded v" \
  "$HOME/Library/Application Support/Kitfox Games/Caves of Qud/build_log.txt"
# Expected: 1

# Runtime info via MetricsManager.LogInfo → Player.log (has "INFO - " prefix)
grep -c "INFO - \[LLMOfQud\] begin_take_action" \
  "$HOME/Library/Application Support/Kitfox Games/Caves of Qud/Player.log"
```

Grep target file matters. `Logger.buildLog.Info` writes to `{save_dir}/build_log.txt`
via `SimpleFileLogger` (`decompiled/Logger.cs:32`, `decompiled/SimpleFileLogger.cs:24-28`).
`MetricsManager.LogInfo` writes to `Player.log` via `UnityEngine.Debug.Log`
(`decompiled/MetricsManager.cs:407-409`). Do not interchange them.

Manual-only verification plans must explicitly flag the decision and justify it.

## Future sections

<!-- Phase 2a: add game-as-harness scripted mode invocation details -->
<!-- Phase 2b: add micro-eval fixture suite structure -->
<!-- CI: add GitHub Actions workflow reference when configured -->
