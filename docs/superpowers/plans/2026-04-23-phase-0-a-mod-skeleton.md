# Phase 0-A / 0-A2: MOD Skeleton + Load Verification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a Caves of Qud mod named `LLMOfQud` that Roslyn-compiles cleanly at game launch, registers an `IPlayerSystem`, emits exactly one `BeginTakeActionEvent` callback per player decision point, and survives a mid-session reload without duplicate callbacks. No LLM, no WebSocket, no observation logic — just the skeleton that every downstream phase depends on.

**Architecture:**
- Pure CoQ mod: a directory of `.cs` source files + `manifest.json` under the user's CoQ `Mods/` directory. CoQ's `RoslynCSharpCompiler` compiles it in-memory on game launch (`ModInfo.cs:757-823`); there is **no `.csproj` or prebuilt DLL in the mod directory**.
- A single `IPlayerSystem` subclass (`LLMOfQudSystem`) registers for `BeginTakeActionEvent` on the player body (object-level event per `BeginTakeActionEvent.cs:37-52`), logs activity, and guards against double-registration on mod reload (`XRLCore.RegisterOnBeginPlayerTurnCallback` has no internal duplicate guard per `XRLCore.cs:576`).
- Source-of-truth lives in the repo at `mod/LLMOfQud/`. The working directory that CoQ loads is linked (symlink) to the repo directory so editing in the repo immediately affects the installed mod.

**Tech Stack:**
- Caves of Qud (Steam build, macOS) with mod directory scanning enabled
- C# compiled by CoQ's in-process Roslyn (`RoslynCSharpCompiler`, `ModManager.cs:395-414`)
- HarmonyLib (bundled by CoQ, auto-referenced; **do not redistribute**)
- Two distinct logging destinations (verified at `decompiled/Logger.cs:16,32` and `decompiled/MetricsManager.cs:407-409`):
  - `Logger.buildLog.Info(msg)` → `{CoQ save dir}/build_log.txt` (via `SimpleFileLogger` + `File.AppendAllText`, `decompiled/SimpleFileLogger.cs:24-28`). Used by CoQ itself for `Compiling N file(s)...` / `Success :)` / `[Required]` dependency lines.
  - `MetricsManager.LogInfo(msg)` → `UnityEngine.Debug.Log("INFO - " + msg)` → `Player.log` (Unity's standard player log). Used by CoQ for audio/platform/telemetry-adjacent info.
  - On macOS the save dir is `~/Library/Application Support/Kitfox Games/Caves of Qud/` — so `build_log.txt` and `Player.log` sit next to each other.
- Verification: manual game launch, reading BOTH log files plus the in-game Mods list. Load probe text is grepped in `build_log.txt`; turn-counter text is grepped in `Player.log`. Optional non-blocking check: external compile/reference probe against CoQ's bundled `Assembly-CSharp.dll` (proves reference compatibility only, not runtime behavior).

**Testing reality for this plan (v2, after Codex research 2026-04-23 — see `docs/memo/test-strategy-codex-research-2026-04-23.md`):**

Do not generalise "CoQ C# can't be unit-tested". The decompiled game ships 11 NUnit test files (e.g. `decompiled/XRL.Language/GrammarTest.cs`, `decompiled/XRL.Rules/DieRollTests.cs`) for pure/string/parser/math helpers, CoQ's Managed directory bundles `nunit.framework.dll`, and `Properties/AssemblyInfo.cs:6` declares `InternalsVisibleTo("UnitTests")`. External projects can reference `Assembly-CSharp.dll` + bundled DLLs for compile/reference probes; Wiki-documented mod examples (`Kizby/Clever-Girl`, `HeladoDeBrownie/Caves-of-Qud-Minimods`) do exactly that.

What is *not* viable (confirmed by Codex grep over `decompiled/`):
- **Headless / batch-mode smoke**: CoQ has no `-batchmode` "load mod, run scripted test, exit" path. Known CLI args are `NOMETRICS`, `-SAVEPATH`, `-SHAREDPATH`, `-SYNCEDPATH`, `STEAM:NO`, `GALAXY:NO` — none triggers a test runner. Unity's `-batchmode -nographics` is accepted by the player but CoQ's game loop still expects UI. No `XRL.Testing` namespace, no `RunTests` entry point in the game code.
- **"Hijacking the runtime" via the MOD itself to auto-embark and auto-drive** is theoretically possible (the MOD runs inside CoQ with full API access, so it could force-embark at boot, play scripted turns, and `Application.Quit()` — effectively game-as-harness). This is a promising direction for Phase 2+ automated regression but is deliberately out of scope for Phase 0-A: the surface area is too small to justify the harness, and we need a manual rehearsal of the startup/reload flow first to know what to script.

What *is* required for Phase 0-A / 0-A2:
- **Manual in-game verification** against `build_log.txt` (for compile / load-probe output via `Logger.buildLog.Info`) and `Player.log` (for runtime info via `MetricsManager.LogInfo`), both in `$COQ_SAVE_DIR` (on macOS: `~/Library/Application Support/Kitfox Games/Caves of Qud/`). Each task below ends with a specific, narrow acceptance criterion and a `grep` pattern against the correct file.
- **Optional non-blocking reference probe**: a throwaway test-compile project that references CoQ's bundled DLLs can prove that our namespaces resolve against `Assembly-CSharp.dll` before we depend on them. If the user wants it, it slots alongside Task 3 without changing any acceptance criterion. It proves compile-time compatibility only, never runtime behavior.

What Phase 0-A / 0-A2 is deliberately *not* pursuing yet:
- **External pure-logic unit tests**: no pure logic exists yet. Introduce NUnit / xUnit externally starting in Phase 0-B+ when the MOD ships self-owned helpers (snapshot shaping, protocol parsing, scoring, serialisation).
- **Game-as-harness automated smoke**: revisit when the MOD has enough scripted surface to benefit. Likely Phase 2a or 2b as part of the micro-eval fixture suite (2-M). Even then, it replaces manual rehearsal of complex flows — not the Phase 0 lifecycle sanity checks.

**Scope boundaries:**
- In scope: Phase 0-A (MOD skeleton + IPlayerSystem registration + duplicate guard) and Phase 0-A2 (packaging + load verification) from `docs/architecture-v5.md` (v5.9).
- Out of scope: observation tools (0-B onward), WebSocket bridge (Phase 1), LLM integration (Phase 2a), Harmony patches (deferred until Phase 2). The `AutoAct.TryToMove` Harmony patch is **not** part of this plan.

**Reference:** `docs/architecture-v5.md` v5.9, sections:
- §5 MOD Integration Strategy (IPlayerSystem, duplicate guard)
- Phase 0 Tasks (0-A, 0-A2)
- `docs/memo/v5.9-codex-review-2026-04-23.md` and earlier review memos for rationale

---

## Prerequisites (one-time user action)

Before starting Task 1, confirm the following on the user's machine:

1. Caves of Qud is installed and runnable.
2. The user knows the absolute path to their local CoQ `Mods/` directory. On macOS this is typically `~/Library/Application Support/Kitfox Games/Caves of Qud/Mods` but it depends on the install. If unsure, launch CoQ, open the Mods menu, and use the "Show Mods Folder" option — whatever path that opens is the correct value. Record this path as `$MODS_DIR`.
3. The user knows the absolute path to CoQ's **save directory** (parent of `Mods/`). This is where `build_log.txt` and `Player.log` are written. On macOS it is typically `~/Library/Application Support/Kitfox Games/Caves of Qud/`. Record as `$COQ_SAVE_DIR`.
4. Record the installed CoQ build version. Launch CoQ once; from the main-menu bottom-right (or Settings → About) copy the build string. Also stash it programmatically:
   ```bash
   head -n 5 "$COQ_SAVE_DIR/build_log.txt" 2>/dev/null
   # The first few lines include a build date / version header once CoQ initializes buildLog.
   ```
   The version is later pinned in the Phase 0-A exit memo (Task 8) so that Phase 0-B re-entry knows what was verified against.
5. Inspect whether `$MODS_DIR/LLMOfQud` already exists before Task 1 creates the symlink. Possible pre-existing states and resolutions:
   - **No entry**: proceed normally.
   - **Symlink to somewhere else**: stop, ask the user whether to replace. Do not auto-unlink.
   - **Regular directory**: stop, ask the user. It may be a stale manual mod directory — do not auto-delete.
   - **Dangling symlink**: OK to `rm` the link after confirming with the user, then recreate as part of Task 1.

Record both `$MODS_DIR` and `$COQ_SAVE_DIR` for use in later task commands. Every command below that uses `"$MODS_DIR"` or `"$COQ_SAVE_DIR"` assumes those shell variables are set for the session.

---

## Task 1: Create the repo mod directory and symlink it into CoQ's Mods folder

**Files:**
- Create: `mod/LLMOfQud/.gitkeep` (placeholder so the empty directory commits)
- Modify: `.gitignore` (add `*.log` and macOS `.DS_Store` if not already ignored)

**Why this task exists:** The mod source must live in the repo (version control, reviewable history) but CoQ only scans its own `Mods/` folder. A symlink lets us edit once and have CoQ see the changes.

- [ ] **Step 1: Confirm `$MODS_DIR` with the user and verify it exists**

```bash
ls -la "$MODS_DIR"
```

Expected: the directory exists and lists any other mods the user has installed. If it does not exist, stop and ask the user to locate it via "Show Mods Folder" in CoQ's Mods menu.

- [ ] **Step 2: Create the repo-side mod directory**

```bash
mkdir -p /Users/sankenbisha/Dev/llm-of-qud/mod/LLMOfQud
touch /Users/sankenbisha/Dev/llm-of-qud/mod/LLMOfQud/.gitkeep
```

- [ ] **Step 3: Create the symlink from CoQ's Mods folder to the repo directory**

```bash
ln -s /Users/sankenbisha/Dev/llm-of-qud/mod/LLMOfQud "$MODS_DIR/LLMOfQud"
ls -la "$MODS_DIR/LLMOfQud"
```

Expected: the `ls` output shows `LLMOfQud -> /Users/sankenbisha/Dev/llm-of-qud/mod/LLMOfQud` and the target directory is reachable.

- [ ] **Step 4: Update .gitignore if needed**

Ensure `.DS_Store` and `*.log` are ignored at the repo root. Check the current `.gitignore` (may not exist yet); if missing, create it:

```
.DS_Store
*.log
**/*.log
```

- [ ] **Step 5: Commit (only if the user explicitly asks)**

Per the repo-wide "Commit only when explicitly requested" rule (AGENTS.md), do NOT auto-commit. If and only if the user asks for a commit after the task is done, suggest:

```bash
git add mod/LLMOfQud/.gitkeep .gitignore
# Proposed message (single-sentence; user may override):
# "chore: add mod/LLMOfQud skeleton directory for Phase 0-A"
```

Otherwise leave changes uncommitted and move to Task 2.

---

## Task 2: Write minimal manifest.json so CoQ recognises the mod

**Files:**
- Create: `mod/LLMOfQud/manifest.json`

**Why this task exists:** `ModInfo.ReadConfigurations()` (`ModInfo.cs:275-301`) populates `ModManifest` from `manifest.json` at launch. Without this file, CoQ treats the directory as a mod folder but uses auto-generated defaults (directory name for ID, no title, etc.). Providing a manifest gives us a stable `ID` and human-readable title.

`ModManifest` fields are defined in `decompiled/XRL/ModManifest.cs` — only these are read:
`ID, LoadOrder, Title, Description, Tags (comma-delimited), Version, Author, PreviewImage, Directories, Dependencies, LoadBefore, LoadAfter, Dependency (legacy)`. **No `entry assembly` field exists.**

- [ ] **Step 1: Acceptance criterion before implementation**

Launch CoQ, open Mods menu. Expected: the mod does not appear (or appears with garbage title). This confirms the baseline.

- [ ] **Step 2: Create manifest.json**

```bash
cat > /Users/sankenbisha/Dev/llm-of-qud/mod/LLMOfQud/manifest.json << 'EOF'
{
  "ID": "LLMOfQud",
  "Title": "LLM of Qud",
  "Description": "Harness for LLM-driven autonomous play. Phase 0-A skeleton only — no runtime behavior yet beyond begin-turn logging.",
  "Version": "0.0.1",
  "Author": "pen3250",
  "Tags": "automation, mod"
}
EOF
```

- [ ] **Step 3: Launch CoQ and verify the mod appears in the list**

Launch CoQ → main menu → Mods. Expected: an entry titled "LLM of Qud" at version 0.0.1 with the given description.

If the mod does NOT appear:
- Check that `$MODS_DIR/LLMOfQud/manifest.json` is reachable via the symlink:
  `cat "$MODS_DIR/LLMOfQud/manifest.json"` must succeed.
- Check `$COQ_SAVE_DIR/build_log.txt` for JSON-parsing errors (CoQ's `ModInfo` routes manifest.json parse errors through `Logger.buildLog.Error`, same backend as the compile log).

- [ ] **Step 4: Commit (only if the user explicitly asks)**

Same policy as Task 1 Step 5. If requested:

```bash
git add mod/LLMOfQud/manifest.json
# Proposed message: "feat(mod): add manifest.json with verified ModManifest fields"
```

---

## Task 3: Write the minimal LLMOfQudSystem class that makes the mod `IsScripting`

**Files:**
- Create: `mod/LLMOfQud/LLMOfQudSystem.cs`

**Why this task exists:** `ModInfo.InitializeFiles()` (`ModInfo.cs:478-481`) sets `IsScripting = true` only if the mod directory contains at least one `.cs` file. `ModManager.BuildMods()` (`ModManager.cs:442`) only calls `TryBuildAssembly()` for `IsScripting` mods. So we need a single `.cs` file — even empty — to opt into the compilation path. This task writes that file with the bare skeleton (namespace, class declaration, nothing else) so we can confirm the Roslyn-compile path fires and succeeds.

- [ ] **Step 1: Acceptance criterion before implementation**

On current state (no `.cs` files), `build_log.txt` should NOT contain a `Compiling N file(s)...` line for `LLMOfQud`. Tail the log after launching CoQ:

```bash
grep -E "=== LLM OF QUD ===|Compiling.*files?\.\.\." "$COQ_SAVE_DIR/build_log.txt" | tail -20
```

Expected: no `=== LLM OF QUD ===` header and no subsequent `Compiling` line for this mod. (CoQ's `Logger.buildLog.Info` writes to `build_log.txt`; see `decompiled/Logger.cs:16,32` + `decompiled/SimpleFileLogger.cs:24-28`.)

- [ ] **Step 2: Write the skeleton class**

```csharp
using System;
using XRL;

namespace LLMOfQud
{
    [Serializable]
    public class LLMOfQudSystem : IPlayerSystem
    {
        // Phase 0-A: empty skeleton. Registration and event handling arrive in Tasks 4a-7.
    }
}
```

Save as `mod/LLMOfQud/LLMOfQudSystem.cs`.

- [ ] **Step 3: Launch CoQ and verify the Roslyn compile succeeds**

Launch CoQ. Inside `$COQ_SAVE_DIR/build_log.txt`, look for:

```
=== LLM OF QUD ===
Compiling 1 file...
Success :)
```

`ModManager.cs:432` emits the `=== <TITLE UPPER> ===` header; `ModInfo.cs:769` emits `Compiling {N} file(s)...` and `ModInfo.cs:774` emits `Success :)`. All go to `Logger.buildLog` which is `build_log.txt`, NOT `Player.log`.

```bash
grep -E "^(\[[^]]+\] )?(=== LLM OF QUD ===|Compiling \d+ files?\.\.\.|Success :\))" \
  "$COQ_SAVE_DIR/build_log.txt" | tail -10
```

(The optional `[timestamp]` prefix is prepended by `SimpleFileLogger.Info` via `AppendTimestamp`, see `decompiled/SimpleFileLogger.cs:19-28`.)

Expected lines (in order, modulo timestamps):
```
=== LLM OF QUD ===
Compiling 1 file...
Success :)
```

If the log shows `== COMPILER ERRORS ==` instead (also to `build_log.txt`), read the errors, fix the `.cs` file, and relaunch.

- [ ] **Step 4: Commit (only if the user explicitly asks)**

Same policy as Task 1 Step 5. If requested:

```bash
git add mod/LLMOfQud/LLMOfQudSystem.cs
# Proposed message: "feat(mod): add empty LLMOfQudSystem : IPlayerSystem skeleton"
```

---

## Task 4a: Verify the bootstrap idiom for attaching an IPlayerSystem from a MOD

**Files:** (none yet — this task is research-only)

**Why this task exists:** Before writing any bootstrap code, confirm which idiom CoQ actually uses to drive user-defined `IPlayerSystem` / `IGameSystem` attachment from a mod. `The.Game.RequireSystem<T>()` auto-creates the system on first call (verified at `decompiled/XRL/XRLGame.cs:311-322`), but **something must make that first call at the right point in the game lifecycle**. An incorrect hook (e.g. applying `[GameBasedStaticCache]` to a property when the attribute only targets fields — `decompiled/XRL/GameBasedStaticCacheAttribute.cs:15`) will silently fail to attach the system.

This step exists to eliminate guesswork before implementation, per the project rule "verify, don't guess".

- [ ] **Step 1: Catalogue candidate idioms by grepping decompiled source**

```bash
rg -n "\[PlayerMutator\]|IPlayerMutator|RequireSystem<|HasGameBasedStaticCache|GameBasedStaticCache\b" \
  /Users/sankenbisha/Dev/llm-of-qud/decompiled | head -40
```

Broad scope (`decompiled` root, not just `decompiled/XRL/`) is required because existing `[PlayerMutator]` examples live at the repo top level — the previously-used `decompiled/XRL/ + decompiled/XRL.Core/` scoping missed `decompiled/WishMenu_PlayerMutator.cs`.

- [ ] **Step 2: Confirm the `[PlayerMutator]` idiom from verified sources**

Read and cite each of these files (do not paraphrase — keep file:line references in the implementation memo):

- `decompiled/XRL/PlayerMutator.cs:1-8` — `[AttributeUsage(AttributeTargets.Class)] public class PlayerMutator : Attribute`.
- `decompiled/XRL/IPlayerMutator.cs:1-8` — interface `IPlayerMutator { void mutate(GameObject player); }`.
- `decompiled/WishMenu_PlayerMutator.cs:1-12` — concrete example: `[PlayerMutator] public class WishMenu_PlayerMutator : IPlayerMutator { public void mutate(GameObject player) { player.RequirePart<WishMenu>(); } }`.
- `decompiled/XRL.CharacterBuilds.Qud/QudGameBootModule.cs:300-304` — the lifecycle: during embark, `ModManager.GetTypesWithAttribute(typeof(PlayerMutator))` is iterated and `Activator.CreateInstance(item2) as IPlayerMutator)?.mutate(element)` is invoked with the new player GameObject.

This is the canonical bootstrap hook: a class carrying `[PlayerMutator]` that calls `The.Game.RequireSystem<LLMOfQudSystem>()` inside `mutate(GameObject player)`.

- [ ] **Step 3: Reject wrong idioms and record why**

- **`[HasGameBasedStaticCache]` on a property**: invalid — attribute targets `AttributeTargets.Field` only (`decompiled/XRL/GameBasedStaticCacheAttribute.cs:15`). Even if applied to a field, the attribute is a field-reset utility, not a bootstrap hook. Do not use.
- **Static ctor on `LLMOfQudSystem` alone**: not sufficient — the ctor only runs when `LLMOfQudSystem` is first referenced. Without a hook that references it at game start, the ctor never fires.
- **`XRLCore.RegisterOnBeginPlayerTurnCallback`**: usable for per-turn callbacks but has no duplicate-registration guard (`decompiled/XRL.Core/XRLCore.cs:576`). Safe only if we also manage a static registered flag. Secondary option — not the primary bootstrap.

- [ ] **Step 4: Write a short verification memo**

Create `docs/memo/phase-0-a-bootstrap-verification-2026-04-23.md`:

```markdown
# Phase 0-A Bootstrap Verification — 2026-04-23

Chosen idiom: `[PlayerMutator]` class + `IPlayerMutator.mutate(GameObject player)`
that calls `The.Game.RequireSystem<LLMOfQudSystem>()`.

Sources:
- `decompiled/XRL/PlayerMutator.cs:5` (attribute)
- `decompiled/XRL/IPlayerMutator.cs:5-7` (interface)
- `decompiled/WishMenu_PlayerMutator.cs:5-12` (real-world example)
- `decompiled/XRL.CharacterBuilds.Qud/QudGameBootModule.cs:300-304` (lifecycle)
- `decompiled/XRL/XRLGame.cs:311-322` (RequireSystem<T>() auto-creates)

Rejected idioms and why: see plan Task 4a Step 3.
```

No code written yet; proceed to Task 4b.

---

## Task 4b: Implement the `[PlayerMutator]` bootstrap and the `RegisterPlayer` load marker

**Files:**
- Create: `mod/LLMOfQud/LLMOfQudBootstrap.cs`
- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs`

**Why this task exists:** With the idiom confirmed in Task 4a, we can now wire `LLMOfQudSystem` into the game. Two things happen: (1) at embark, `mutate(player)` forces `The.Game.RequireSystem<LLMOfQudSystem>()`, which attaches the system; (2) on the first `RegisterPlayer(GameObject, IEventRegistrar)` invocation for this process, we log a **one-shot** load marker to `build_log.txt` through `Logger.buildLog.Info` per spec (`docs/architecture-v5.md:2782-2784`). Using `RegisterPlayer` rather than `Register` keeps us aligned with the spec's explicit wording ("static ctor or first `RegisterPlayer()` call") and places the probe after CoQ has a live player GameObject in hand.

- [ ] **Step 1: Create LLMOfQudBootstrap.cs**

```csharp
using XRL;
using XRL.World;

namespace LLMOfQud
{
    [PlayerMutator]
    public class LLMOfQudBootstrap : IPlayerMutator
    {
        public void mutate(GameObject player)
        {
            The.Game.RequireSystem<LLMOfQudSystem>();
        }
    }
}
```

Verified against `decompiled/WishMenu_PlayerMutator.cs:5-12` (shape) and `decompiled/XRL.CharacterBuilds.Qud/QudGameBootModule.cs:300-304` (lifecycle). `The.Game` is the static accessor for the current `XRLGame` instance (`decompiled/XRL/The.cs`). `RequireSystem<T>()` returns the existing instance or creates one (`decompiled/XRL/XRLGame.cs:311-322`).

- [ ] **Step 2: Extend LLMOfQudSystem.cs with RegisterPlayer override + load marker**

```csharp
using System;
using XRL;
using XRL.World;

namespace LLMOfQud
{
    [Serializable]
    public class LLMOfQudSystem : IPlayerSystem
    {
        public const string VERSION = "0.0.1";

        private static bool _loadMarkerLogged;

        public override void RegisterPlayer(GameObject Player, IEventRegistrar Registrar)
        {
            if (!Registrar.IsUnregister && !_loadMarkerLogged)
            {
                _loadMarkerLogged = true;
                Logger.buildLog.Info(
                    "[LLMOfQud] loaded v" + VERSION +
                    " at " + DateTime.UtcNow.ToString("o"));
            }
            base.RegisterPlayer(Player, Registrar);
        }
    }
}
```

Decisions, each with a cited source:

- Use `Logger.buildLog.Info` for the load probe — v5.9 spec mandates this (`docs/architecture-v5.md:2782-2784`) and it co-locates the probe with CoQ's own `Compiling N file(s)... / Success :)` lines in `build_log.txt` for a single grep-sweep. `Logger.buildLog` is declared at `decompiled/Logger.cs:16` and initialized at `decompiled/Logger.cs:32`.
- Emit the marker from `RegisterPlayer(GameObject Player, IEventRegistrar Registrar)` — the spec wording is "from its static ctor or from the first `RegisterPlayer()` call" (`docs/architecture-v5.md:2782-2784`). `RegisterPlayer` is defined on `IPlayerSystem` (`decompiled/XRL/IPlayerSystem.cs:35`) and fires when CoQ attaches the player body to the system — a predictable per-embark point. Emitting from `Register(XRLGame, IEventRegistrar)` would work mechanically but diverges from the frozen spec and would fire at a different lifecycle point (system attach to game) than intended.
- Guard with a `static bool _loadMarkerLogged` — static so it persists across `RegisterPlayer` re-invocations within a single process (e.g., body swap, where `IPlayerSystem` re-registers against the new body per `decompiled/XRL/IPlayerSystem.cs:42-53`). On a mod **reload** (toggle off → toggle on within one CoQ process) the static field *may* reset if Roslyn produces a fresh Assembly and the class type is fresh; Task 7 observes the actual behavior empirically and records whether it holds or resets.
- Additionally guard with `!Registrar.IsUnregister` so the marker never fires during the unregister pass (`RegisterPlayer` is invoked for both register and unregister paths per `decompiled/XRL/IPlayerSystem.cs:22-32`; the register path precedes unregister in the normal `AddSystem → ApplyRegistrar` sequence at `decompiled/XRL/XRLGame.cs:422-430`, but the guard makes the intent explicit and prevents any accidental emission during tear-down).
- Do not rely on static ctor — the ctor runs the first time the type is referenced (inside `RequireSystem<T>()`), which is before any `XRLGame` state is safe to touch. `RegisterPlayer` is triggered later in the attach sequence and has both the player body and a fresh `IEventRegistrar` in hand.
- Event registration (the `Registrar.Register(SingletonEvent<BeginTakeActionEvent>.ID)` call) is **not** added here — it arrives in Task 5. Keeping load-marker and event-registration as two separately-verifiable concerns lets Task 4c pass/fail on load probe alone, before Task 5's subscription is in place.

- [ ] **Step 3: Launch CoQ and start a new game (no verification yet)**

Fresh character, any build, Roleplay mode, embark. The next task (4c) verifies the marker emerged.

- [ ] **Step 4: Commit (only if the user explicitly asks)**

Same policy as Task 1 Step 5. If requested:

```bash
git add mod/LLMOfQud/LLMOfQudBootstrap.cs mod/LLMOfQud/LLMOfQudSystem.cs
# Proposed message: "feat(mod): wire PlayerMutator bootstrap and one-shot load marker"
```

---

## Task 4c: Verify the load marker appears exactly once in build_log.txt

**Files:** (none)

**Why this task exists:** We separate verification from implementation (Task 4b) so that a missing marker line can be diagnosed without re-scrolling the implementation. A `0` count means the bootstrap never attached; a `2+` count means either `Register` is invoked multiple times or the static guard was defeated (unlikely in Phase 0-A but worth catching).

- [ ] **Step 1: Grep build_log.txt for the marker**

```bash
grep -c "\[LLMOfQud\] loaded v" "$COQ_SAVE_DIR/build_log.txt"
```

Expected: `1`. Not `0`. Not `2+`.

- [ ] **Step 2: If count == 0, diagnose**

Likely causes:
- `[PlayerMutator]` class not found — check that `LLMOfQudBootstrap.cs` compiled (inspect `build_log.txt` for the `=== LLM OF QUD ===` block and `Success :)`; if compile errors, fix and relaunch).
- `mutate(player)` never called because a prior `[PlayerMutator]` threw during iteration. Check `build_log.txt` and `Player.log` for `Exception` lines mentioning `LLMOfQud`.
- `RequireSystem<T>()` call path threw. Same log sources.

- [ ] **Step 3: If count >= 2, diagnose**

Likely causes:
- The static guard field is being reset between `RegisterPlayer` invocations — meaning the class type itself was reloaded mid-session. This would indicate `mutate(player)` ran twice in one session, or a mid-session mod reload happened before Task 7 was reached. Confirm by ordering: only one `=== LLM OF QUD ===` block should precede the first marker.
- Multiple embarks in one session (quit to main menu, start a new game) — each embark runs `[PlayerMutator]`, each fresh game triggers a fresh `Register`. This is expected behavior, not a bug. Either restart CoQ to reset, or treat each embark as a separate "session" for the count.

- [ ] **Step 4: Pass criterion**

`grep -c` returns exactly `1` on the first embark of a fresh CoQ process. Record the timestamped line for use as the baseline in Task 7.

```bash
grep "\[LLMOfQud\] loaded v" "$COQ_SAVE_DIR/build_log.txt" | tail -1
```

---

## Task 5: Subscribe to BeginTakeActionEvent in RegisterPlayer

**Files:**
- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs`

**Why this task exists:** `BeginTakeActionEvent.Check()` (`decompiled/XRL.World/BeginTakeActionEvent.cs:50`) dispatches via `Object.HandleEvent(SingletonEvent<BeginTakeActionEvent>.Instance)`. To receive the event, the system must explicitly register for the event ID on the player body via `IPlayerSystem.RegisterPlayer()` (`IPlayerSystem.cs:38`). Simply subclassing `IPlayerSystem` is not sufficient — without the `Registrar.Register(...)` call, no event arrives.

- [ ] **Step 1: Add RegisterPlayer override with explicit event registration**

Update `LLMOfQudSystem.cs`:

```csharp
using System;
using XRL;
using XRL.World;

namespace LLMOfQud
{
    [Serializable]
    public class LLMOfQudSystem : IPlayerSystem
    {
        public const string VERSION = "0.0.1";

        private static bool _loadMarkerLogged;

        public override void RegisterPlayer(GameObject Player, IEventRegistrar Registrar)
        {
            if (!Registrar.IsUnregister && !_loadMarkerLogged)
            {
                _loadMarkerLogged = true;
                Logger.buildLog.Info(
                    "[LLMOfQud] loaded v" + VERSION +
                    " at " + DateTime.UtcNow.ToString("o"));
            }
            Registrar.Register(SingletonEvent<BeginTakeActionEvent>.ID);
            base.RegisterPlayer(Player, Registrar);
        }
    }
}
```

The diff against Task 4b's class is: one new line `Registrar.Register(SingletonEvent<BeginTakeActionEvent>.ID);` added immediately before `base.RegisterPlayer(...)`. Load marker and backend (`Logger.buildLog.Info`) remain unchanged from Task 4b.

*Verified against `decompiled/XRL/WanderSystem.cs:57-60` (example of `RegisterPlayer` body) and `decompiled/XRL.World/BeginTakeActionEvent.cs:4` (class extends `SingletonEvent<BeginTakeActionEvent>`, so `.ID` resolves).*

- [ ] **Step 2: Launch CoQ and verify the game still starts without errors**

Start a new game. Expected: no compiler errors, no runtime exception on embark. The load-marker log line from Task 4b still appears in `build_log.txt`.

```bash
# Compile / load probe live in build_log.txt
grep -E "(COMPILER ERRORS|\[LLMOfQud\])" "$COQ_SAVE_DIR/build_log.txt" | tail -10
# Runtime exceptions live in Player.log
grep -E "(Exception|ERROR -).*LLMOfQud" "$COQ_SAVE_DIR/Player.log" | tail -10
```

Expected: one `[LLMOfQud] loaded ...` line in `build_log.txt`, zero `COMPILER ERRORS`, zero exceptions mentioning `LLMOfQud` in `Player.log`.

(There is no observable behavior change yet — the event is subscribed but nothing handles it. That comes in Task 6.)

- [ ] **Step 3: Commit (only if the user explicitly asks)**

```bash
git add mod/LLMOfQud/LLMOfQudSystem.cs
# Proposed message: "feat(mod): RegisterPlayer subscribes to BeginTakeActionEvent"
```

---

## Task 6: HandleEvent(BeginTakeActionEvent) increments a counter and periodically logs

**Files:**
- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs`

**Why this task exists:** We need proof that the event subscription from Task 5 actually delivers events. A turn counter with a throttled log line gives us a quiet but measurable signal, and keeps the log from flooding. Throttling by 10 turns is arbitrary but small enough to confirm in a ~60-second play session.

- [ ] **Step 1: Add HandleEvent override**

Update `LLMOfQudSystem.cs`:

```csharp
using System;
using XRL;
using XRL.World;

namespace LLMOfQud
{
    [Serializable]
    public class LLMOfQudSystem : IPlayerSystem
    {
        public const string VERSION = "0.0.1";

        private static bool _loadMarkerLogged;

        private int _beginTurnCount;

        public override void RegisterPlayer(GameObject Player, IEventRegistrar Registrar)
        {
            if (!Registrar.IsUnregister && !_loadMarkerLogged)
            {
                _loadMarkerLogged = true;
                Logger.buildLog.Info(
                    "[LLMOfQud] loaded v" + VERSION +
                    " at " + DateTime.UtcNow.ToString("o"));
            }
            Registrar.Register(SingletonEvent<BeginTakeActionEvent>.ID);
            base.RegisterPlayer(Player, Registrar);
        }

        public override bool HandleEvent(BeginTakeActionEvent E)
        {
            _beginTurnCount++;
            if (_beginTurnCount % 10 == 0)
            {
                MetricsManager.LogInfo(
                    "[LLMOfQud] begin_take_action count=" + _beginTurnCount);
            }
            return base.HandleEvent(E);
        }
    }
}
```

**Log-backend choice for the turn counter:** `MetricsManager.LogInfo` is used here (not `Logger.buildLog.Info`) on purpose. Turn cadence is runtime data that belongs in `Player.log` next to other `INFO - ` lines; `Logger.buildLog.Info` is reserved by CoQ for compile/load-order output in `build_log.txt` (see `decompiled/Logger.cs:32`, `decompiled/MetricsManager.cs:407-409`). Keeping the two log channels separate makes the `build_log.txt` sweep concise for Phase 0-B re-entry.

- [ ] **Step 2: Launch CoQ, start a new game, play ~15 turns**

Any movement / wait / attack counts. The goal is to trigger `BeginTakeActionEvent` at least 10 times.

- [ ] **Step 3: Verify the counter log appears at count=10**

```bash
grep "\[LLMOfQud\] begin_take_action" "$COQ_SAVE_DIR/Player.log" | tail -5
```

Expected: at least one line `INFO - [LLMOfQud] begin_take_action count=10` (the `INFO - ` prefix is added by `MetricsManager.LogInfo` via `UnityEngine.Debug.Log`, see `decompiled/MetricsManager.cs:409`). If the count never logs, the event subscription from Task 5 is broken — return to Task 5 debug.

- [ ] **Step 4: Verify the count is monotonic (no double-counting)**

Play 10 more turns, check again:

```bash
grep "\[LLMOfQud\] begin_take_action" "$COQ_SAVE_DIR/Player.log" | tail -5
```

Expected: a new line with `count=20`. If `count=20` appears after fewer than 10 additional turns, duplicate dispatch is happening — stop and diagnose before proceeding to Task 7.

- [ ] **Step 5: Commit (only if the user explicitly asks)**

```bash
git add mod/LLMOfQud/LLMOfQudSystem.cs
# Proposed message: "feat(mod): HandleEvent(BeginTakeActionEvent) logs every 10th turn"
```

---

## Task 7: Reload acceptance — verify no duplicate begin-turn callback after mid-session reload

**Files:**
- Create: `docs/memo/phase-0-a-reload-acceptance-2026-04-23.md`

**Why this task exists:** `XRLCore.RegisterOnBeginPlayerTurnCallback()` (`decompiled/XRL.Core/XRLCore.cs:576`) simply `Add`s to a callback list with no duplicate guard. If the MOD re-registers on reload (which CoQ does during mod toggling), begin-turn callbacks can double up and every turn would fire multiple log lines. We use `IPlayerSystem` rather than the raw callback, so duplication risk is lower, but Phase 0-A must verify empirically (spec acceptance: `docs/architecture-v5.md:2740-2742`).

**Measurement shape: delta, not absolute value.** The previous plan asserted "count=20 → count=30" after a 10-turn reload gap. That assumption fails if Roslyn re-compilation on reload produces a fresh Assembly with a fresh `LLMOfQudSystem` type — in which case `_beginTurnCount` resets to 0, and after 10 more turns the log shows `count=10`, not `count=30`. That is a correct behavior of the engine (fresh type, fresh instance state), not a bug. The correct acceptance is: **after N further player actions, exactly N additional `begin_take_action` events are observed, regardless of whether the absolute counter continued or reset.**

- [ ] **Step 1: Establish a clean baseline**

Fresh CoQ launch → new game → play exactly 20 turns. Then capture the baseline into actual shell variables so Step 4 can compute the delta. Run these in a single persistent shell session (do not close the terminal between Step 1 and Step 4):

```bash
BASELINE_EVENT_LINES=$(grep -c "\[LLMOfQud\] begin_take_action" "$COQ_SAVE_DIR/Player.log")
BASELINE_COUNT_VALUE=$(grep "\[LLMOfQud\] begin_take_action" "$COQ_SAVE_DIR/Player.log" | tail -1 | awk -F'count=' '{print $2}')
BASELINE_LOG_LINES=$(wc -l < "$COQ_SAVE_DIR/Player.log")
echo "BASELINE: event_lines=$BASELINE_EVENT_LINES count_value=$BASELINE_COUNT_VALUE log_lines=$BASELINE_LOG_LINES"
```

With throttling of 10 and 20 turns played, expect `BASELINE_EVENT_LINES == 2` and `BASELINE_COUNT_VALUE == 20`. If the baseline does not match these numbers, stop here and diagnose — there is no point running the reload step on a bad baseline.

- [ ] **Step 2: Reload the mod mid-session**

Inside CoQ: Main menu (Esc) → Mods → find "LLM of Qud" → toggle off → toggle on → confirm prompt to reload mods. CoQ will re-compile the mod and reinitialize systems. Return to the game (load the auto-save if prompted).

- [ ] **Step 3: Play exactly N additional player turns**

Pick N = 20 (so we can observe either `count=30` if the counter survived, or `count=10` + `count=20` if it reset — both should add 2 log lines at throttle=10). Continue the same game after the reload. Do not reload the mod again during this step.

- [ ] **Step 4: Measure the post-reload delta**

```bash
POST_EVENT_LINES=$(grep -c "\[LLMOfQud\] begin_take_action" "$COQ_SAVE_DIR/Player.log")
echo "post=$POST_EVENT_LINES  baseline=$BASELINE_EVENT_LINES  delta=$((POST_EVENT_LINES - BASELINE_EVENT_LINES))"
grep "\[LLMOfQud\] begin_take_action" "$COQ_SAVE_DIR/Player.log" | tail -5
```

At throttle=10 and N=20, expected delta is **2** new log lines (firing at turns 10 and 20 post-reload, regardless of absolute count values). A delta of **4** would indicate duplicate registration (each action logged twice); a delta of **1** would indicate some actions were missed.

Pass criterion:
- `delta == 2` (no duplicates, no misses) → **PASS**.
- `delta == 4` → **FAIL, duplicate registration**. Diagnose: `ApplyRegistrar` invoked twice without `ApplyUnregistrar`. Check whether both the pre-reload `IPlayerSystem` instance and the post-reload instance are still receiving events. If the static field `_loadMarkerLogged` is preserved (`grep -c "\[LLMOfQud\] loaded v"` returns `1`) but events duplicate, the system lifecycle did not unregister the old instance — record this in the memo rather than working around it in this plan.
- `delta == 1` → missed events. Diagnose `RegisterPlayer` re-subscription; the post-reload system instance may not have re-registered for `SingletonEvent<BeginTakeActionEvent>.ID`.

- [ ] **Step 5: Also record what happened to absolute counter and load marker**

```bash
grep -c "\[LLMOfQud\] loaded v"        "$COQ_SAVE_DIR/build_log.txt"   # how many load markers total?
grep    "\[LLMOfQud\] begin_take_action" "$COQ_SAVE_DIR/Player.log" | awk -F'count=' '{print $2}'
```

Record for the memo:
- Did a second `[LLMOfQud] loaded v` marker appear after the reload? (If yes: the static `_loadMarkerLogged` did NOT survive the assembly swap — expected if type re-compiled. If no: Assembly was preserved or the guard held across instances.)
- Did the `count=` sequence after reload continue (e.g. `10,20,30,40`) or restart (`10,20,10,20`)? Either is acceptable under delta-based measurement, but phase-0-B needs to know.

- [ ] **Step 6: Write the reload acceptance memo**

```markdown
# Phase 0-A Reload Acceptance — 2026-04-23

Date: YYYY-MM-DD (fill in actual)
CoQ build: <from build_log.txt header / Settings → About>

## Method
Delta-measurement reload acceptance: N=20 post-reload player turns, throttle=10
(so expected delta in Player.log lines = 2).

## Observations
- BASELINE_EVENT_LINES = <value>  (expected 2)
- BASELINE_COUNT_VALUE = <value>  (expected 20)
- POST_EVENT_LINES     = <value>
- DELTA                = <value>  (PASS if == 2)
- load_marker_count (build_log.txt) = <1 or 2>
- count= sequence post-reload: <e.g. 10,20 restart; or 30,40 continuous>

## Result
PASS / FAIL with a one-line explanation.

## Implications for Phase 0-B
- Assembly-swap behavior on reload: <type reset / type preserved>
- Static field behavior: <survived / reset>
- Whether we can assume `_loadMarkerLogged` style guards hold across reload:
  <yes/no, with the observation that justifies it>
```

- [ ] **Step 7: Commit (only if the user explicitly asks)**

```bash
git add docs/memo/phase-0-a-reload-acceptance-2026-04-23.md
# Proposed message: "docs: record Phase 0-A reload acceptance test result"
```

---

## Task 8: Phase 0-A / 0-A2 exit criteria summary

**Files:**
- Create: `docs/memo/phase-0-a-exit-2026-04-23.md`

**Why this task exists:** The spec lists distinct exit criteria for Phase 0-A and Phase 0-A2 (`docs/architecture-v5.md` sections Phase 0 and §5). We need one concise document confirming we have met them before moving to Phase 0-B. This also gives future work a short artifact to cite when we start Phase 1.

- [ ] **Step 1: Re-run the full sequence end-to-end on a clean game launch**

Close CoQ entirely. Relaunch. Start a new game. Play ≥ 20 turns. Do NOT reload mods.

- [ ] **Step 2: Collect the acceptance evidence from both log files**

```bash
# Compile + load marker live in build_log.txt
grep -E "=== LLM OF QUD ===|^Compiling \d+ files?\.\.\.|^Success :\)|\[LLMOfQud\] loaded v" \
  "$COQ_SAVE_DIR/build_log.txt"

# Turn counter lives in Player.log
grep "\[LLMOfQud\] begin_take_action" "$COQ_SAVE_DIR/Player.log"
```

Expected output in `build_log.txt` (order and content, modulo timestamps prepended by `SimpleFileLogger`):
```
=== LLM OF QUD ===
Compiling <N> file(s)...
Success :)
[LLMOfQud] loaded v0.0.1 at <ISO-8601 timestamp>
```

Expected in `Player.log`:
```
INFO - [LLMOfQud] begin_take_action count=10
INFO - [LLMOfQud] begin_take_action count=20
```

- [ ] **Step 3: Write the exit memo with Phase 0-B feed-forward**

```markdown
# Phase 0-A / 0-A2 Exit — 2026-04-23

## Environment
- CoQ build: <version string from build_log.txt / About>
- OS / shell: <macOS version, zsh>
- Mods dir ($MODS_DIR): <absolute path>
- Save dir ($COQ_SAVE_DIR): <absolute path>

## Phase 0-A2 (MOD packaging / load verification)
- [x] CoQ Mods list shows "LLM of Qud" v0.0.1 after launch
- [x] `build_log.txt` matches `^Compiling \d+ files?\.\.\.$` then `Success :)`
- [x] Load probe line `[LLMOfQud] loaded v0.0.1 at ...` in `build_log.txt` appears
      exactly once on clean launch
- [x] No `COMPILER ERRORS` section for the mod

## Phase 0-A (MOD skeleton + IPlayerSystem registration + reload acceptance)
- [x] `LLMOfQudSystem : IPlayerSystem` registered via `The.Game.RequireSystem<T>()`
      — bootstrap idiom = `[PlayerMutator]` class calling `RequireSystem<LLMOfQudSystem>()`
      (source citations recorded in `docs/memo/phase-0-a-bootstrap-verification-2026-04-23.md`)
- [x] `RegisterPlayer()` explicitly registers `SingletonEvent<BeginTakeActionEvent>.ID`
- [x] `HandleEvent(BeginTakeActionEvent)` fires and count grows 1-per-turn
- [x] Reload acceptance (Task 7) passes — delta measurement matches N turns played

## Feed-forward for Phase 0-B
Record these specifics so 0-B planning does not re-derive them:

| Item | Decision / Observation | Source |
|------|------------------------|--------|
| Bootstrap idiom | `[PlayerMutator]` → `RequireSystem<T>()` | `docs/memo/phase-0-a-bootstrap-verification-2026-04-23.md`; `decompiled/WishMenu_PlayerMutator.cs:5-12`; `decompiled/XRL.CharacterBuilds.Qud/QudGameBootModule.cs:300-304` |
| Log backend — build-time / load probe | `Logger.buildLog.Info` → `build_log.txt` | `decompiled/Logger.cs:16,32`; `decompiled/SimpleFileLogger.cs:24-28` |
| Log backend — runtime info | `MetricsManager.LogInfo` → `Player.log` (via `UnityEngine.Debug.Log`) | `decompiled/MetricsManager.cs:407-409` |
| Static field persistence on mod reload | <observed: survived / reset — copy value from reload-acceptance memo> | Task 7 Step 5 observation |
| Counter value on mod reload | <observed: continued / restarted from 0> | Task 7 Step 5 observation |
| Event system hooks in place | `RegisterPlayer(GameObject, IEventRegistrar)` (load marker + `SingletonEvent<BeginTakeActionEvent>.ID` registration); `HandleEvent(BeginTakeActionEvent)` (turn counter) | `decompiled/XRL/IPlayerSystem.cs:35`; `decompiled/XRL.World/BeginTakeActionEvent.cs:37-52` |

## Phase 0-B preparation pointers (do not start 0-B here — just cite where 0-B will pick up)

- Screen buffer observation entry points to inspect at 0-B planning time:
  - `decompiled/ConsoleLib.Console/TextConsole.cs` — search for `CurrentBuffer` to confirm the API shape
  - `decompiled/ConsoleLib.Console/ScreenBuffer.cs` — cell representation
  - Register-after-render callback: grep `RegisterAfterRenderCallback` in `decompiled/` to find the wiring
- Python Brain directory layout for 0-B: `docs/architecture-v5.md:1838-1864`

## Next
Phase 0-B (ScreenBuffer observation). Implementation plan TBD — will build on the
bootstrap + event registration produced here, plus the feed-forward table above.
```

- [ ] **Step 4: Commit (only if the user explicitly asks)**

```bash
git add docs/memo/phase-0-a-exit-2026-04-23.md \
        docs/memo/phase-0-a-bootstrap-verification-2026-04-23.md \
        docs/memo/phase-0-a-reload-acceptance-2026-04-23.md
# Proposed message: "docs: record Phase 0-A / 0-A2 exit + supporting memos"
```

---

## Self-Review

**Spec coverage:**
- Phase 0-A (MOD skeleton, IPlayerSystem registration, BeginTakeActionEvent, duplicate guard) → Tasks 3, 4a, 4b, 4c, 5, 6, 7
- Phase 0-A2 (packaging, Roslyn compile, HarmonyLib auto-reference, load probe, exit criteria) → Tasks 1, 2, 3, 8
- v5.9 reload acceptance (`architecture-v5.md:2740-2742`) → Task 7 (delta-based measurement, not absolute-count)
- v5.9 load-probe spec (`architecture-v5.md:2782-2784`, `Logger.buildLog.Info`) → Task 4b Step 2 + Task 4c grep path
- No Harmony patch (out of scope for this plan; Phase 2 territory)
- No WebSocket (Phase 1), no observation tools (Phase 0-B), no LLM (Phase 2a) — all intentionally deferred

**Placeholders scan:**
- No "TBD", "add appropriate error handling", or "similar to Task N" phrases.
- Task 4a explicitly is research-only (by design, not by omission). Its deliverable is a verification memo that downstream tasks cite.
- Commit steps are conditional ("only if the user explicitly asks") per the repo-wide AGENTS.md rule; this is a policy gate, not a placeholder.

**Type consistency:**
- `LLMOfQudSystem.VERSION` constant defined in Task 4b, referenced consistently.
- `_loadMarkerLogged` (static bool) and `_beginTurnCount` (instance int) — static vs instance split is intentional: load marker is per-assembly (survives body swap within a session but is observed to reset when the Assembly is swapped during mod reload — Task 7 records which); counter is per-system-instance.
- Log-backend consistency:
  - Load probe: `Logger.buildLog.Info` → `build_log.txt` (per spec, Task 4b + Task 4c).
  - Runtime turn counter: `MetricsManager.LogInfo` → `Player.log` (Task 6 Step 2 rationale).
  - Every grep command targets the correct file for the text it is looking for.
- Log line prefix `[LLMOfQud]` used consistently across both backends so mod-origin filtering is one grep.

**Known risks / explicit non-assumptions:**
- Whether the `_loadMarkerLogged` static persists across mod reload is **not assumed**. Task 7 Step 5 observes and records the actual behavior; downstream tasks consume that observation rather than a predicted value.
- Whether `_beginTurnCount` continues or resets on reload is **not assumed**. Task 7 uses delta measurement, which is robust to either.
- `[PlayerMutator]` lifecycle assumes embark creates one player GameObject per game. Multiple embarks in one CoQ process (quit to menu + start new game) will run `mutate(player)` again and produce an additional load-marker line — Task 4c Step 3 documents this as expected behavior.

---

## Execution Handoff

Plan complete. Recommended execution mode: **Inline Execution** (within the current Claude Code session).

Rationale:
- Task 4a is research-only but its output (bootstrap idiom memo) is needed by Task 4b; a subagent boundary here adds serialization cost without isolation benefit.
- Task 4c through Task 7 form a tight loop with the user: "Claude Code edits file → user launches CoQ / plays turns / reloads → Claude Code greps logs → iterate." Fresh-subagent-per-task would re-upload context that is stable in a single inline session.
- Phase 0-A acceptance verification requires the real CoQ process, which subagents cannot drive.

Task ownership split (keep this visible during execution):

| Actor | Owns |
|-------|------|
| Claude Code | Repo file edits; `grep` / `wc -l` verification commands; log interpretation; memo drafting |
| User | Setting `$MODS_DIR` / `$COQ_SAVE_DIR`; launching CoQ; embarking; playing N turns; toggling the mod off/on for reload; providing log excerpts back when asked |
| Claude Code | Pass/fail decision per step using the provided acceptance criteria |

Before Task 1 runs, the user must confirm:
1. `$MODS_DIR` (e.g. `~/Library/Application Support/Kitfox Games/Caves of Qud/Mods`)
2. `$COQ_SAVE_DIR` (typically the parent of `$MODS_DIR`)
3. The pre-existing state of `$MODS_DIR/LLMOfQud`, if any (per Prerequisites step 5)
4. CoQ build version string

These belong to Prerequisites, not to Task 1 proper.
