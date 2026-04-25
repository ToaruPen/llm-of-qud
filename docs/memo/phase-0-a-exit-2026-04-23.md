# Phase 0-A / 0-A2 Exit — 2026-04-23 (Task 7 closed by ADR 0003)

> Plan authoring date: 2026-04-23. Execution and verification completed: 2026-04-24.
> Task 7 closure recorded: 2026-04-25.
>
> **Status:** Phase 0-A2 fully met. Phase 0-A met except Task 7 (mid-session mod
> reload acceptance), which was originally deferred and is now formally CLOSED
> by [ADR 0003](../adr/0003-phase-0-a-task-7-closure-by-design.md) as a
> design-decision closure (the streaming runtime fixes mods at launch; the
> toggle path is non-applicable to production operation). See "Task 7
> resolution" below for the closure rationale and the re-open triggers.

## Environment (empirically verified, not plan-assumed)

| Item | Value | Note |
|------|-------|------|
| CoQ build | `BUILD_2_0_210` | From `Defined symbol: BUILD_2_0_210` in `build_log.txt` |
| OS | macOS 26.3.1 (BuildVersion 25D771280a) | `sw_vers` |
| Shell | `/bin/zsh` | |
| `$MODS_DIR` | `$HOME/Library/Application Support/Freehold Games/CavesOfQud/Mods` | **NOT** `Kitfox Games/Caves of Qud` as plan assumed |
| `$COQ_SAVE_DIR` | `$HOME/Library/Application Support/Freehold Games/CavesOfQud` | |
| `$PLAYER_LOG` | `$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log` | **Different location** from `$COQ_SAVE_DIR`, per Unity macOS standard (`~/Library/Logs/{companyName}/{productName}/Player.log`) |
| Coexisting mod | `QudJP` (Japanese localization, user's own project, currently `Skipping, state: Disabled` in build_log) | Codex verified low interference risk |

**Path discrepancy rationale.** CoQ delegates to Unity `Application.persistentDataPath`
(`decompiled/XRL.Core/XRLCore.cs:430,436,3514`, `decompiled/GameManager.cs:848`); the
publisher/product name segment comes from Unity PlayerSettings baked into the built
player, not from decompiled C#. No `Kitfox` string exists in decompiled source.
Codex advisor confirmed `Freehold Games/CavesOfQud` is the correct/current path
(investigation output: `/tmp/codex-outputs/q1-publisher-20260424-083211.jsonl`).

## Phase 0-A2 (MOD packaging / load verification)

- [x] CoQ Mods list shows "LLM of Qud" v0.0.1 after launch (confirmed by user 2026-04-24)
- [x] `build_log.txt` matches `^Compiling \d+ files?\.\.\.$` then `Success :)`:
      ```
      [2026-04-24T21:08:05] === LLM OF QUD ===
      [2026-04-24T21:08:05] Compiling 2 files...
      [2026-04-24T21:08:05] Success :)
      [2026-04-24T21:08:05] Defined symbol: MOD_LLMOFQUD
      ```
- [x] Load probe line appears exactly once on fresh launch + embark:
      ```
      [2026-04-24T21:09:16] [LLMOfQud] loaded v0.0.1 at 2026-04-24T12:09:16.6327240Z
      ```
- [x] No `COMPILER ERRORS` section for the mod (0 matches)

## Phase 0-A (MOD skeleton + IPlayerSystem registration) — reload acceptance deferred

- [x] `LLMOfQudSystem : IPlayerSystem` registered via `The.Game.RequireSystem<T>()`.
      Bootstrap idiom = `[PlayerMutator]` class calling `RequireSystem<LLMOfQudSystem>()`.
      Sources cited in `docs/memo/phase-0-a-bootstrap-verification-2026-04-23.md`.
- [x] `RegisterPlayer()` explicitly registers `SingletonEvent<BeginTakeActionEvent>.ID`
      (`mod/LLMOfQud/LLMOfQudSystem.cs:25`).
- [x] `HandleEvent(BeginTakeActionEvent)` fires and the counter grows one-per-turn.
      Evidence in `Player.log`:
      ```
      INFO - [LLMOfQud] begin_take_action count=10
      INFO - [LLMOfQud] begin_take_action count=20
      INFO - [LLMOfQud] begin_take_action count=30
      ```
      The 10-turn spacing is exact in terms of player actions. If duplicate
      dispatch were happening, the logged values `10, 20, 30` would still appear
      (the `% 10` throttle threshold is the same) but each would fire after only
      5 player actions instead of 10 — i.e. the whole sequence would arrive in
      half the real play time. Session C's cadence against a ~30-action play
      session is consistent only with single dispatch per action.
- [x] **Reload acceptance (Task 7) — CLOSED by ADR 0003 (2026-04-25).**
      `IPlayerSystem`-based architecture eliminates the
      `XRLCore.RegisterOnBeginPlayerTurnCallback` duplicate-guard hazard that
      motivated the plan's Task 7. The mid-session Mods-menu toggle path is
      formally **not measured**, but the streaming harness's runtime contract
      fixes mods at launch (architecture-v5.9 Phase 2+), so the toggle path is
      non-applicable to production operation. Closed as design-decision, not
      empirical PASS. **Re-open triggers** are enumerated in ADR 0003 ("Decision"
      section) — primarily any phase introducing dev-loop iteration, runtime
      A/B switching of mod logic, or reliance on specific in-process
      assembly-swap state-survival semantics. See "Task 7 resolution" below for
      the original deferral context that ADR 0003 supersedes.

## Execution deviations from plan (recorded here for traceability)

The plan is frozen and Codex-round-3 approved; these are execution-level decisions,
not spec amendments:

1. **Tasks 5 + 6 merged into one CoQ embark cycle (Option B).** The separation in
   the plan was test-discipline, not a correctness requirement. Diagnostic fidelity
   is preserved: `Player.log` catches exceptions regardless, and Task 6's
   10-ticks-per-log pattern retroactively proves Task 5's subscription works.
   Codex advisor B vs A judgement recorded at
   `/tmp/codex-outputs/task5-6-decision-20260424-210521.jsonl`.
2. **Task 7 (mid-session mod toggle reload) deferred.** Not an execution
   shortcut; recorded here as an **acceptance criterion not met** rather than a
   normal deviation. See "Task 7 resolution" below.
3. **Task 8 Step 1 (fresh relaunch + 20 turns final re-verification) skipped.** Two
   prior fresh relaunches had already produced equivalent `build_log.txt` and
   `Player.log` evidence; a third relaunch would only retimestamp the same pattern.
4. **No per-task commits.** Plan's "Commit only if the user explicitly asks" policy
   is in effect; all Phase 0-A files are currently uncommitted, awaiting explicit
   staging.

## Task 7 resolution: acceptance criterion CLOSED by ADR 0003 (2026-04-25), architectural hazard removed

> **Update 2026-04-25:** What follows is the original deferral analysis written
> on 2026-04-24. The acceptance gap it describes is now formally **CLOSED** by
> [ADR 0003](../adr/0003-phase-0-a-task-7-closure-by-design.md) as a
> design-decision closure (no in-game delta measurement performed). The
> closure rests on the streaming runtime's fixed-launch contract; the four
> behavioral questions enumerated in this section remain formally unanswered
> and ADR 0003 lists the re-open triggers that would require them to be
> answered.

The plan's Task 7 targets the `XRLCore.RegisterOnBeginPlayerTurnCallback` API,
which has no duplicate-registration guard. Its implementation body (`decompiled/XRL.Core/XRLCore.cs:576-579`)
is simply `OnBeginPlayerTurnCallbacks.Add(action);`. Mid-session reload through
that API would stack duplicate callbacks.

**The primary hazard is removed by implementation choice.** `LLMOfQudSystem` is
an `IPlayerSystem` whose lifecycle is managed by `ApplyRegistrar` /
`ApplyUnregistrar` (`decompiled/XRL/IPlayerSystem.cs:9-33`) — a symmetric
per-instance path. The `EventRegistrar` handler scope is also per-instance
(`decompiled/XRL/EventRegistrar.cs:24-36`). We never call
`RegisterOnBeginPlayerTurnCallback`, so its duplicate-guard gap does not apply
to us.

**Empirical supporting evidence (fresh-relaunch only — weaker than mid-session toggle).**
- Two independent fresh CoQ launches (Session B: 2026-04-24T21:02, Session C:
  2026-04-24T21:08) each produce exactly one load marker — no marker
  duplication across process relaunches.
- Session C's ~30 consecutive turns produce `count=10, 20, 30` at exact
  10-player-action spacing. Duplicate subscription would still show the same
  threshold values but arrive after half as many real player actions; the
  observed cadence against the play session rules that out.

**Acceptance criterion status: NOT MET.** The plan's Task 7 specifically required
a *delta measurement against the mid-session Mods-menu toggle path*, and that
measurement has not been performed. Treat this as an **acceptance gap**, not a
completed criterion.

**What the in-process toggle would have checked and we have not verified.**
These are the concrete gaps not closed by fresh-relaunch evidence:

1. Whether `ApplyUnregistrar` actually executes on the old instance when CoQ
   toggles the mod off (as opposed to being retained in memory alongside the
   new assembly).
2. Whether the old `LLMOfQudSystem` instance still holds a live `EventRegistrar`
   subscription on the player `GameObject` after toggle-off, which would cause
   double-dispatch after toggle-on if a fresh instance also registers.
3. Whether `_loadMarkerLogged` (static `bool`) survives an in-process Roslyn
   assembly swap, or resets because the `Type` is newly JIT-compiled.
4. Whether `_beginTurnCount` continues or restarts across the same in-process
   assembly swap.

**Why deferral is acceptable for Phase 0-A in this project.** Live-stream
operation (Phase 2+) runs CoQ with the mod set fixed from launch; no
mid-session toggling occurs in the harness's intended runtime. Mid-session
reload resilience is a developer-experience property. **Phase 0-B and later
phases MUST NOT assume in-process hot-reload works.** If a phase introduces a
hot-swap use case (runtime A/B of MOD logic, dev-loop iteration within one CoQ
process, etc.), this Task 7 gap must be closed before that phase can rely on
the behavior.

## Feed-forward for Phase 0-B

| Item | Decision / Observation | Source |
|------|------------------------|--------|
| Bootstrap idiom | `[PlayerMutator]` → `The.Game.RequireSystem<T>()` | `docs/memo/phase-0-a-bootstrap-verification-2026-04-23.md`; `decompiled/WishMenu_PlayerMutator.cs:5-11`; `decompiled/XRL.CharacterBuilds.Qud/QudGameBootModule.cs:300-303` |
| Log backend — build-time / load probe | `Logger.buildLog.Info(msg)` → `$COQ_SAVE_DIR/build_log.txt` | `decompiled/Logger.cs:16,32`; `decompiled/SimpleFileLogger.cs:24-28` |
| Log backend — runtime info | `MetricsManager.LogInfo(msg)` → `UnityEngine.Debug.Log` → `$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log` (Unity macOS default, NOT `$COQ_SAVE_DIR`) | `decompiled/MetricsManager.cs:407-409`; Codex advisor confirmation in `/tmp/codex-outputs/q2-playerlog-20260424-083211.jsonl` |
| Third log backend (not ours) | `$COQ_SAVE_DIR/game_log.txt` + `game_log.N.txt` are `Logger.gameLog` via NLog FileTarget (unrelated to `MetricsManager.LogInfo`) | `decompiled/Logger.cs:14,28-35` |
| Static field persistence on mod reload | **NOT OBSERVED via in-process toggle.** Across fresh-process relaunch (the stronger form of reload), the assembly is reloaded and static state resets to its initial value. Mid-session toggle behavior (whether `_loadMarkerLogged` survives or resets) is **unknown — Task 7 gap.** | (deferred, see Task 7 resolution) |
| Counter value on mod reload | Within a single fresh process, `_beginTurnCount` is monotonic and increments exactly once per player action. Mid-session toggle behavior (continue vs restart) is **unknown — Task 7 gap.** | Session C (fresh-process) evidence only |
| Mid-session hot-reload assumption for downstream phases | **FORBIDDEN until Task 7 is run.** Phase 0-B and any later phase must not rely on in-process mod toggle preserving state, dropping old handlers, or being free of duplicate dispatch. Any phase that needs these guarantees must re-open Task 7 as a prerequisite. | Task 7 resolution section, this memo |
| Event system hooks in place | `RegisterPlayer(GameObject, IEventRegistrar)` (load marker + `SingletonEvent<BeginTakeActionEvent>.ID` registration); `HandleEvent(BeginTakeActionEvent)` (turn counter) | `mod/LLMOfQud/LLMOfQudSystem.cs`; `decompiled/XRL/IPlayerSystem.cs:35`; `decompiled/XRL.World/BeginTakeActionEvent.cs:37-52` |
| QudJP coexistence verdict | Low interference risk. `[PlayerMutator]` runs per-mod-assembly; `IPlayerSystem` handlers are per-instance; `[LLMOfQud]` log prefix is sufficient to disambiguate output. Required discipline: `HandleEvent` returns `true`, do not touch `E.PreventAction`, keep counter in instance field. | `/tmp/codex-outputs/q3-qudjp-20260424-083211.jsonl` |

## Phase 0-B preparation pointers

Do NOT start 0-B here — these are entry-point citations for the next plan:

- Screen buffer observation entry points:
  - `decompiled/ConsoleLib.Console/TextConsole.cs` — search for `CurrentBuffer` to confirm the API shape
  - `decompiled/ConsoleLib.Console/ScreenBuffer.cs` — cell representation
  - `RegisterAfterRenderCallback` — grep in `decompiled/` to find the wiring
- Python Brain directory layout for 0-B: `docs/architecture-v5.md:1838-1864`

## Recommended next steps

1. **Update `architecture-v5.md` path assumptions via ADR** (not a spec change —
   just a correction of environment assumptions). Alternatively, leave the spec
   as-is and require all future memos to cite this exit memo for the correct paths.
   User judgement.
2. **Stage governance + Phase 0-A files for commit** (per project rule, not yet
   committed). Suggested groups:
   - `mod/LLMOfQud/*` — Phase 0-A mod skeleton
   - `docs/memo/phase-0-a-*.md` — verification and exit memos
   - `.gitignore` — minor updates from Task 1
3. **Write Phase 0-B plan** using `superpowers:writing-plans` — screen-buffer
   observation + bridge to Python Brain.

## Files modified / created in Phase 0-A

Created:
- `mod/LLMOfQud/.gitkeep`
- `mod/LLMOfQud/manifest.json`
- `mod/LLMOfQud/LLMOfQudBootstrap.cs`
- `mod/LLMOfQud/LLMOfQudSystem.cs`
- `docs/memo/phase-0-a-bootstrap-verification-2026-04-23.md`
- `docs/memo/phase-0-a-exit-2026-04-23.md` (this file)

Modified:
- `.gitignore` (added `.DS_Store`, `*.log`, `**/*.log`)

External:
- Symlink `$MODS_DIR/LLMOfQud` → repo `mod/LLMOfQud`
