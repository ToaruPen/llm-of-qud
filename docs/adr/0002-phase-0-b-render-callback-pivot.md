# ADR 0002: Phase 0-B observation pivot to AfterRenderCallback

Status: Accepted (2026-04-25)

## Context

Phase 0-B's goal is to emit a 80×25 ASCII snapshot of CoQ's current screen to
`Player.log` once per player decision point (`BeginTakeActionEvent`).

The original Phase 0-B plan (`docs/superpowers/plans/2026-04-25-phase-0-b-screen-buffer-observation.md`)
specified a synchronous read from `HandleEvent(BeginTakeActionEvent)` using
`TextConsole.GetScrapBuffer1(bLoadFromCurrent: true)`, explicitly rejecting
`XRLCore.RegisterAfterRenderCallback` because of the hot-reload duplicate
registration hazard deferred from Phase 0-A Task 7. The plan was approved and
implementation proceeded through Tasks 1-3.

In-game verification (95 turns, BEGIN/END/ERROR = 95/95/0) showed the snapshot
was structurally correct but the map body was almost entirely blank. The
player `@`, walls, floors, and tile-rendered NPCs did not appear in the log;
only stray CP437 fallback characters and UI text were visible.

Investigation traced the cause to `Zone.Render`
(`decompiled/XRL.World/Zone.cs:5411-5418`): in tile mode, the renderer writes
the ASCII glyph to `_Char`, then if a tile is assigned it copies the glyph to
`BackupChar` and zeros `_Char`. So tile-mode cells carry the ASCII fallback
only in `BackupChar`. A simple `_Char → BackupChar → ' '` fallback in the
snapshot helper restores the glyph — IF the buffer being read still has
`BackupChar` populated.

Two rounds of Codex code review surfaced a hard constraint:
`ConsoleChar.Copy` (`decompiled/ConsoleLib.Console/ConsoleChar.cs:385-400`)
does NOT propagate `BackupChar`. Therefore:

- `TextConsole.GetScrapBuffer1(true)` → `ScrapBuffer.Copy(CurrentBuffer)` →
  `ConsoleChar.Copy` per cell → BackupChar lost.
- `TextConsole.DrawBuffer(Buffer)` → `CurrentBuffer.Copy(Buffer)` (under
  `BufferCS` lock) → `ConsoleChar.Copy` per cell → BackupChar lost in
  `CurrentBuffer` itself.

Only the **source buffer** passed to `Zone.Render(Buffer, ...)` retains
`BackupChar`, and only between that call and the subsequent `DrawBuffer`
copy. The plan's `GetScrapBuffer1`-based observation point cannot reach that
buffer.

`docs/architecture-v5.md:408-411` (the frozen v5.9 spec) already lists
`XRLCore.RegisterAfterRenderCallback(Action<XRLCore, ScreenBuffer>)` as one
of two sanctioned ScreenBuffer-access mechanisms for the MOD. The plan was
stricter than the spec it implemented.

## Decision

Replace the Phase 0-B observation mechanism specified in
`docs/superpowers/plans/2026-04-25-phase-0-b-screen-buffer-observation.md`:

1. Subscribe `AfterRenderCallback(XRLCore, ScreenBuffer)` once per process via
   `XRLCore.RegisterAfterRenderCallback` from `IPlayerSystem.RegisterPlayer`,
   guarded by a static `_afterRenderRegistered` flag.
2. `HandleEvent(BeginTakeActionEvent)` increments the per-instance turn
   counter and stores the new turn number into a static request slot via
   `Interlocked.Exchange(ref _pendingSnapshotTurn, _beginTurnCount)`. It does
   NOT read or log the screen.
3. The render callback is a no-op when the slot is zero. When non-zero, it
   atomically captures-and-clears the slot via `Interlocked.Exchange`,
   walks the source buffer with `Char → BackupChar → ' '` fallback, and
   writes one `MetricsManager.LogInfo` call with the `[LLMOfQud][screen]
   BEGIN turn=N w=W h=H\n<body>END turn=N` framing.
4. `GetScrapBuffer1` and direct `CurrentBuffer` reads are removed from the
   observation path.

The plan is amended to record this design with the BackupChar drop rationale
and the rejected alternatives (Harmony postfix on `ConsoleChar.Copy`,
forcing CoQ ASCII display mode, abandoning tile-mode cells).

## Alternatives Considered

- **Stay with `GetScrapBuffer1` and a Harmony postfix on `ConsoleChar.Copy`
  to propagate `BackupChar`** — rejected. `ConsoleChar.Copy` is a hot
  per-cell function used by every `ScreenBuffer.Copy`; modifying it changes
  engine-wide semantics for a peripheral observation feature. `mod/CLAUDE.md`
  designates Harmony for Phase 2+ (ModalInterceptor-class patches), and a
  `BackupChar` propagation patch would set a precedent that erodes the
  staged adoption.
- **Force CoQ into ASCII display mode via `Options.SetStringOption`** —
  rejected. The streaming pipeline is intended to keep tile graphics for
  human viewers; mutating user-facing settings violates that goal and the
  "harness first, LLM second" design philosophy.
- **Accept tile-mode blank snapshots** — rejected. Phase 0-B acceptance
  requires `@`, walls, floors readable; without those the LLM has no map.
- **Re-call `Zone.Render` ourselves into a private buffer** — rejected.
  `Zone.Render` mutates `RenderedObjects`, `WantsToPaint`, `SoundMapDirty`
  and triggers `item.Paint(Buf)` for `WantsToPaint` objects
  (`decompiled/XRL.World/Zone.cs:5388-5439`). Calling it twice per turn
  could double-fire visual side effects.

## Consequences

### Positive

- The implementation aligns with the frozen architecture-v5 spec
  (`:408-411`) which already sanctioned `RegisterAfterRenderCallback`. The
  Phase 0-B plan was stricter than the spec; this ADR brings them back in
  line.
- The observation captures `BackupChar` losslessly. In-game verification
  (95 turns, ERROR=0) confirms `@`, walls, floors, NPCs, water, foliage are
  all readable.
- The pattern (capture-on-render-thread, atomic-handshake-from-game-thread)
  is the natural primitive for Phase 0-C+ when the Brain pulls observations
  over WebSocket: the capture point stays here; ordering and delivery
  layer above it.

### Negative / Carry-forward

- The hot-reload duplicate-callback hazard that motivated the original
  plan's "no callback" rule is now real but gated by `_afterRenderRegistered`
  (a static bool). Within one process, registration happens at most once.
  Mid-session mod recompilation (Phase 0-A Task 7, deferred) could in
  principle reset static state and re-register, doubling the callback. This
  remains a known risk.
- Phase 0-B exit memo MUST state that the verified runtime model is
  fresh-launch only; mid-session reload behavior is unverified.
- Phase 0-A Task 7 is effectively re-opened. Closing it now requires a
  separate plan that addresses both the IPlayerSystem reload gap and the
  AfterRenderCallback duplicate-registration gap.
- Snapshot logging now happens on the render thread, not the game thread.
  `MetricsManager.LogInfo` → `UnityEngine.Debug.Log` is thread-safe
  (`decompiled/MetricsManager.cs:407-409`), but Phase 0-C+ designs that
  assume strict turn→snapshot serialization on a single thread must take
  the per-turn `Interlocked.Exchange` handshake into account.

## Related Artifacts

- `mod/LLMOfQud/LLMOfQudSystem.cs` — implementation of Design B
- `docs/superpowers/plans/2026-04-25-phase-0-b-screen-buffer-observation.md`
  — Phase 0-B plan (amended in same change as this ADR)
- `docs/memo/phase-0-b-tile-mode-finding-2026-04-25.md` — empirical record
  of the tile-mode discovery and two Codex review pivots
- `docs/architecture-v5.md:408-411` — frozen ScreenBuffer access guidance
- `docs/memo/phase-0-a-exit-2026-04-23.md` — Phase 0-A exit, Task 7 deferral
- `decompiled/XRL.Core/XRLCore.cs:624-626` — `RegisterAfterRenderCallback`
- `decompiled/XRL.Core/XRLCore.cs:2347-2351, 2380-2383, 2423-2426` —
  callback invocation sites (post-`Zone.Render`, pre-`DrawBuffer`)
- `decompiled/XRL.World/Zone.cs:5411-5418` — `BackupChar` write
- `decompiled/ConsoleLib.Console/ConsoleChar.cs:385-400` — `Copy` drops
  `BackupChar`
- `decompiled/ConsoleLib.Console/TextConsole.cs:142-163` — `DrawBuffer`
  path

## Supersedes

None. This ADR amends the Phase 0-B plan, but the frozen architecture-v5
spec at `:408-411` is unchanged.
