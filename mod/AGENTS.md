# AGENTS.md — mod/
# Purpose: Rules for working in the C# MOD directory.
# Root rules still apply; this file adds MOD-specific constraints.

## Roslyn Compile Model (non-negotiable)

CoQ does NOT load prebuilt DLLs for mods. It Roslyn-compiles `.cs` files at game launch.

Verified flow (do not deviate):
- `ModManager.BuildMods()` (`decompiled/XRL/ModManager.cs:417-464`) calls
  `mod.TryBuildAssembly()` for every mod where `IsScripting == true`.
- `IsScripting` becomes true when any `.cs` file is found during `InitializeFiles()`
  (`decompiled/XRL/ModInfo.cs:478-481`).
- `TryBuildAssembly()` (`decompiled/XRL/ModInfo.cs:757-823`) feeds all `.cs` paths to
  `RoslynCSharpCompiler.CompileFromFiles()`. Output is an in-memory `Assembly`.
- `.dll` files (`ModFileType.Assembly`) are not loaded by any code path in the decompiled source.

**Do not place a prebuilt `.dll` in `mod/LLMOfQud/`. Do not create a `.csproj` inside the mod directory.**

A `.csproj` for IDE / type-check / CI is kept OUTSIDE `mod/LLMOfQud/`
(unknown files co-located with the mod may be scanned by `InitializeFiles()`).

## Layout

`mod/LLMOfQud/` — `manifest.json` + `*.cs` source files only. Recursive subdirs allowed.

## Manifest Fields

Only these fields exist in `decompiled/XRL/ModManifest.cs`:
`ID`, `LoadOrder`, `Title`, `Description`, `Tags`, `Version`, `Author`,
`PreviewImage`, `Directories`, `Dependencies`, `LoadBefore`, `LoadAfter`, `Dependency`.

There is **no** `entry assembly` field.
`ID` must match `[^\w ]` stripping rule (`decompiled/XRL/ModInfo.cs:288`).

## Event System Rules

- `BeginTakeActionEvent` is an OBJECT-level event dispatched via `Object.HandleEvent()`
  (`decompiled/XRL.World/BeginTakeActionEvent.cs:37-52`). `IGameSystem.HandleEvent`
  alone cannot receive it.
- Use `IPlayerSystem` (extends `IGameSystem`). Register the system via
  `The.Game.RequireSystem<LLMOfQudSystem>()`.
- In `RegisterPlayer()`, explicitly call
  `Registrar.Register(SingletonEvent<BeginTakeActionEvent>.ID)`.
  Subclassing alone is not sufficient. Verified: `decompiled/XRL/WanderSystem.cs:57-60`.

## HarmonyLib

Bundled by CoQ — do NOT redistribute. Auto-referenced (`ModManager.cs:402-405`).
`ApplyHarmonyPatches()` runs `Harmony.PatchAll(Assembly)` for types with `[HarmonyPatch]` (`ModInfo.cs:847-864`).

## Logging

| Destination | Method | File |
|-------------|--------|------|
| Compile-phase messages | `Logger.buildLog.Info(msg)` | `{save_dir}/build_log.txt` |
| Runtime info | `MetricsManager.LogInfo(msg)` | `Player.log` (Unity log) |

On macOS save dir: `~/Library/Application Support/Kitfox Games/Caves of Qud/`

## Verification Pattern

Compile output lives in `build_log.txt`, NOT `Player.log` (see Logging table above).

```bash
# Compile / load-probe output
grep -E "^\[[^]]+\] (=== LLM OF QUD ===|Compiling \d+ files?\.\.\.|Success :\)|COMPILER ERRORS)" \
  "$HOME/Library/Application Support/Kitfox Games/Caves of Qud/build_log.txt"

# Runtime info (MetricsManager.LogInfo → "INFO - " prefix)
grep "INFO - \[LLMOfQud\]" \
  "$HOME/Library/Application Support/Kitfox Games/Caves of Qud/Player.log"
```

## Phase Reference

| Phase | Key tasks | Spec lines |
|-------|-----------|------------|
| 0-A | `IPlayerSystem` skeleton, `BeginTakeActionEvent` subscription | 2730-2742 |
| 0-A2 | Packaging, manifest, load probe, exit criteria | 2743-2809 |
| 0-B+ | ScreenBuffer, observation tools | 2799-2816 |
| 2+ | Harmony patches, ModalInterceptor, StreamOverlay | 1722-1737 |

## Lint Policy

See `docs/lint-policy.md` for the full rule rationale (C# section) and suppression policy.
C# side-project builds use `Directory.Build.props` at repo root; `decompiled/Directory.Build.props` disables all analyzers for the read-only game source.

## Future sections

<!-- Phase 0-B: ScreenBuffer observation rules -->
<!-- Phase 2: Harmony patch conventions; cross-thread dispatch (gameQueue vs uiQueue, spec lines 1787-1804) -->
