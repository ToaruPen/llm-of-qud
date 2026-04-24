# AGENTS.md — decompiled/
# Purpose: Read-only policy for the decompiled CoQ source directory.

## READ-ONLY

This directory contains decompiled C# source from CoQ's `Assembly-CSharp.dll`.
**Do not create, edit, or delete any file here.**

If a tool accidentally stages or modifies a file under `decompiled/`, revert it immediately.

## Citation Format

```
decompiled/<path-from-repo-root>.cs:<line-number-or-range>
```

Example: `decompiled/XRL.World/BeginTakeActionEvent.cs:37-52`

Always include a line number or range. Path-only citations are insufficient.
Before citing, read the file. Do not rely on memory. Rule: root `AGENTS.md` §Imperatives item 1.

## Key Reference Files

| File | Contains |
|------|---------|
| `decompiled/XRL/ModInfo.cs` | `TryBuildAssembly`, `InitializeFiles`, `IsScripting` |
| `decompiled/XRL/ModManager.cs` | `BuildMods`, `RefreshModDirectory`, `MainAssemblyPredicate` |
| `decompiled/XRL/ModManifest.cs` | Manifest field names |
| `decompiled/XRL/IPlayerSystem.cs` | `RegisterPlayer` signature, body-swap |
| `decompiled/XRL/IPlayerMutator.cs` + `PlayerMutator.cs` | Bootstrap attribute + interface |
| `decompiled/WishMenu_PlayerMutator.cs` | Real `[PlayerMutator]` example |
| `decompiled/XRL.CharacterBuilds.Qud/QudGameBootModule.cs` | `[PlayerMutator]` lifecycle |
| `decompiled/XRL/XRLGame.cs` | `RequireSystem<T>` |
| `decompiled/XRL.World/BeginTakeActionEvent.cs` | Object-level dispatch |
| `decompiled/XRL/WanderSystem.cs` + `CodaSystem.cs` | `IPlayerSystem` examples |
| `decompiled/Logger.cs` + `decompiled/SimpleFileLogger.cs` | `Logger.buildLog` → `build_log.txt` |
| `decompiled/MetricsManager.cs` | `LogInfo` → `Player.log` (Unity) |
| `decompiled/GameManager.cs` | `gameQueue`, `uiQueue` thread task queues |
| `decompiled/XRL.Core/XRLCore.cs` | `RegisterOnBeginPlayerTurnCallback`, game loop |
