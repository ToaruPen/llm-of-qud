# Phase 0-A Bootstrap Verification — 2026-04-23

> Plan authoring date: 2026-04-23. Verification executed: 2026-04-24 (Claude Code inline,
> backed by Codex advisor pass for QudJP coexistence in Q3 of
> `/tmp/codex-outputs/q3-qudjp-20260424-083211.jsonl`).

Chosen idiom: `[PlayerMutator]` class implementing `IPlayerMutator`, whose
`mutate(GameObject player)` calls `The.Game.RequireSystem<LLMOfQudSystem>()`.

## Sources

| Claim | Citation |
|-------|----------|
| `[PlayerMutator]` is `[AttributeUsage(AttributeTargets.Class)] public class PlayerMutator : Attribute` | `decompiled/XRL/PlayerMutator.cs:5-6` |
| `IPlayerMutator` is `public interface IPlayerMutator { void mutate(GameObject player); }` | `decompiled/XRL/IPlayerMutator.cs:5-7` |
| Real-world example pattern: `[PlayerMutator] public class WishMenu_PlayerMutator : IPlayerMutator { public void mutate(GameObject player) { player.RequirePart<WishMenu>(); } }` | `decompiled/WishMenu_PlayerMutator.cs:5-11` |
| Lifecycle: during embark, `ModManager.GetTypesWithAttribute(typeof(PlayerMutator))` iterates every registered class; each is `Activator.CreateInstance`-d and has `mutate(element)` called on the freshly-created player body | `decompiled/XRL.CharacterBuilds.Qud/QudGameBootModule.cs:300-303` |
| `The.Game.RequireSystem<T>() where T : IGameSystem, new()` returns the existing system instance if attached, otherwise `AddSystem(new T())` and returns it | `decompiled/XRL/XRLGame.cs:311-322` |

This is the canonical bootstrap hook: a class carrying `[PlayerMutator]` that calls
`The.Game.RequireSystem<LLMOfQudSystem>()` inside `mutate(GameObject player)`.

Phase 0-A mod `LLMOfQud` will implement this exactly once in
`mod/LLMOfQud/LLMOfQudBootstrap.cs` (Task 4b).

## Rejected idioms and why

- **`[HasGameBasedStaticCache]` / `[GameBasedStaticCache]` on a property** — invalid.
  `GameBasedStaticCacheAttribute` is `[AttributeUsage(AttributeTargets.Field)]`
  (`decompiled/XRL/GameBasedStaticCacheAttribute.cs:15`), so it cannot be placed on
  properties. Even on a field it is a field-reset utility for game start, not a
  bootstrap hook that drives system attachment.
- **Static ctor on `LLMOfQudSystem` alone** — not sufficient. A C# static ctor runs
  the first time the type is referenced at runtime. Without an external hook that
  references `LLMOfQudSystem` at game start (as `[PlayerMutator]` does via
  `RequireSystem<T>()`), the ctor is never triggered for our attachment path.
- **`XRLCore.RegisterOnBeginPlayerTurnCallback(Action<XRLCore>)`** — usable for a
  per-turn callback but has *no* internal duplicate-registration guard: its body
  is simply `OnBeginPlayerTurnCallbacks.Add(action)` (`decompiled/XRL.Core/XRLCore.cs:576`).
  If the mod is reloaded mid-session (Phase 0-A Task 7 scenario), a second registration
  would stack a duplicate callback. It is not a drop-in replacement for
  `IPlayerSystem` + `[PlayerMutator]`, which manages its own lifecycle through
  `ApplyRegistrar` (`decompiled/XRL/IPlayerSystem.cs:9-19`). This option is kept
  in mind as a fallback only if the `IPlayerSystem` path surfaces problems — no
  Phase 0-A code path depends on it.

## Cross-reference for downstream tasks

- Task 4b writes `LLMOfQudBootstrap` with the verified shape above.
- Task 4b writes `LLMOfQudSystem.RegisterPlayer(...)` carrying the load marker. The
  per-instance attachment of an `IPlayerSystem` handler on the player body is
  confirmed in `decompiled/XRL/IPlayerSystem.cs:9-19` (see also
  `decompiled/XRL/EventRegistrar.cs:24-36`).
- Task 5 registers `SingletonEvent<BeginTakeActionEvent>.ID` in the same
  `RegisterPlayer` call. `BeginTakeActionEvent` dispatch to all handlers is in
  `decompiled/XRL.World/BeginTakeActionEvent.cs:23-25,46-50`.
- Task 7's reload acceptance uses a *delta* measurement so the result is robust
  regardless of whether Roslyn swaps the `LLMOfQudSystem` assembly type on reload.
