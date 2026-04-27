# Phase 1 PR-1 Probe Phase — Codex Second Opinion (2026-04-27)

## Context

After PR #18 (Phase 1 PR-1 readiness, merged at `commit 093ac64`
2026-04-27T12:54:31Z), the orchestrator consulted Codex (`gpt-5.5`
advisor mode, read-only) before kicking off the Task 1 probe phase. The
consultation surfaced one direct contradiction in the merged Plan (Probe
3 vs ADR 0011 §Q3) and four additional load-bearing claims that the
original probe set did not cover. The Plan was hotfixed in the same
readiness PR cascade to incorporate the findings before any in-game
probe runs.

This memo captures Codex's full second-opinion content verbatim for
traceability. Subsequent ADR 0013 / 0014 drafts must cite this memo when
claims it raises are referenced.

## Codex consultation prompt summary

The orchestrator asked Codex five questions: (1) probe-set
completeness, (2) instrumentation chicken-and-egg between 'no impl yet'
and 'probes need a server', (3) Probe 8 sub-option ranking, (4)
sequencing/batching to minimize CoQ launches, (5) risks the Plan §Risks
section did not name.

## Codex full response (verbatim from agent_message)

## 1. Completeness

Short answer: no. The probe set is close for ADR 0012’s “blocking CTA wait can work” claim, but it is not complete or internally consistent enough to lock ADR 0013.

The biggest issue is Probe 3. As written, it expects “exactly one `[decision]` and one `[cmd]` per turn” after socket close. That is a fail-open/fallback shape, not the sealed disconnect=pause posture. ADR 0011 says socket disconnect dispatches no `Decision` and native CoQ idle absorbs the pause at `PlayerTurn` (`decompiled/XRL.Core/ActionManager.cs:1797-1799`). To enter that path from CTA, the handler must leave energy `>= 1000` and `PreventAction == false` so the branch at `decompiled/XRL.Core/ActionManager.cs:838` calls `PlayerTurn`. Current Probe 3 would instead validate continued autonomous action.

Recommended fix: split Probe 3 into:

- **Probe 3a: timeout fallback**: keep the “one `[decision]` + one `[cmd]`” expectation for timeout only.
- **Probe 3b: disconnect mid-Decide enters pause**: Python closes while C# is waiting; pass means no terminal action, no stale decision, energy unchanged, `PreventAction` not set, and next engine state reaches `PlayerTurn`.

Missing load-bearing claims:

- **BTA/CTA bypass claim**: Probe 8 option (i) touches `BeginTakeActionEvent`, but no probe proves BTA blocking or BTA `PreventAction` does not bypass CTA semantics. BTA fires before the inner loop (`decompiled/XRL.Core/ActionManager.cs:786-800`); CTA is inside it (`decompiled/XRL.Core/ActionManager.cs:829-838`). Minimal probe: one disconnect pause via BTA instrumentation, logging BTA/CTA counts, energy before/after, and whether CTA/hostile interrupt/render fallback still occur.

- **Long blocking observation-silence claim**: Probe 6 covers 200ms latency, but not the fact that no new BTA-backed observation can flush while CTA is blocked. `RenderBase()` pumps `gameQueue` only when called on the core thread (`decompiled/XRL.Core/XRLCore.cs:2517-2522`), and after-render callbacks fire only during render generation (`decompiled/XRL.Core/XRLCore.cs:2347-2351`, `decompiled/XRL.Core/XRLCore.cs:2422-2426`). Minimal probe: one 1s and one 5s Decide sleep, recording UI responsiveness, after-render backlog, and exact time from response to next `[screen]/[state]`.

- **Stale response / epoch claim**: Probe 3 says no stale decision after reconnect, but PR-3 owns `action_nonce + state_version + session_epoch`. If ADR 0013 will claim stale rejection, add a Probe 7-lite: hold an old response, reconnect, send it late, and prove it is ignored. Otherwise, remove that claim from ADR 0013 for PR-1.

- **Save/load bridge lifecycle**: Phase 0-G explicitly leaves save/load resilience untested. New WebSocket state makes this load-bearing because `LLMOfQudSystem` is `[Serializable]`, and CoQ saves systems via `XRLGame.SaveSystems` (`decompiled/XRL/XRLGame.cs:1573-1582`) and calls `AfterLoad` after read (`decompiled/XRL/XRLGame.cs:1818-1821`). Minimal probe: connected run -> save -> load -> reconnect -> 5 turns; verify one active client, no duplicate after-render callback, no serialized socket/thread state.

- **AutoAct is not reopened by default PR-1**, because PR-1 still returns only `Move` / `AttackDirection` and does not set `AutoAct.Setting`. But if Probe 8 chooses `Keyboard.PushKey`, add a narrow wake-key probe proving the injected key does not become a terminal command or disturb AutoAct state. AutoAct interrupt is reachable after CTA when `PreventAction` stays false (`decompiled/XRL.Core/ActionManager.cs:833-837`).

## 2. Instrumentation chicken-and-egg

The right interpretation is **minimal-stub C#/Python first, probe second, production implementation third**.

Task 1’s phrase “before production C# / Python implementation begins” should be read literally. A WebSocket round trip cannot be probed without probe harness code. The harness should be intentionally disposable or clearly marked probe-only, but it must compile and run in-game.

Smallest setup sequence:

1. Add `mod/LLMOfQud/BrainClient.cs`.
   - Connects to `ws://localhost:4040`.
   - Sends one serialized `decision_input.v1`.
   - Receives one `decision.v1`.
   - Supports timeout, close-before-response detection, reconnect event, and a probe-mode wake callback.
   - Does not route tools, use DB, auth, or queue calls.

2. Add `mod/LLMOfQud/WebSocketPolicy.cs`.
   - Implements `IDecisionPolicy.Decide(DecisionInput input)`.
   - Blocks only on the BrainClient decision future.
   - Separates timeout from disconnect.
   - Throws `DisconnectedException` for pause probes.

3. Modify `mod/LLMOfQud/LLMOfQudSystem.cs` minimally.
   - Swap `_policy` to the probe `WebSocketPolicy`.
   - Add an explicit `DisconnectedException` branch before the existing broad catch/drain path.
   - Preserve the normal CTA execution body.
   - Add probe-only logging for energy, BTA/CTA counts, pause entry, reconnect wake.

4. Add `brain/app.py`.
   - WebSocket server on localhost:4040.
   - Configurable phase machine: sleep duration, timeout overrun, close-before-response, late stale response, reconnect marker.
   - No Codex auth, no SQLite, no tool envelope.

5. Add a probe memo artifact.
   - `docs/memo/phase-1-pr-1-probes-YYYY-MM-DD.md`.
   - Record raw logs and falsification decision per probe.

Before Probe 1 fires, run a compile-only sanity pass for `ClientWebSocket`. CoQ’s mod compiler references assemblies already loaded into the AppDomain (`decompiled/XRL/ModManager.cs:402-405`) and compiles mod `.cs` files through Roslyn (`decompiled/XRL/ModInfo.cs:757-771`). If `System.Net.WebSockets.ClientWebSocket` is not available in that reference set, the whole probe phase blocks before runtime.

## 3. Probe 8 sub-options prior

Recommended ranking:

1. **(iv) `Keyboard.PushKey` wake injection**
2. **(ii) drain energy via `PassTurn` on disconnect**
3. **(i) block-BTA polling loop**
4. **(iii) `PreventAction = true` with no energy drain**

Rationale:

1. **`Keyboard.PushKey` is the best first bet.**
   - It matches the native idle path. `PlayerTurn` checks keyboard input (`decompiled/XRL.Core/XRLCore.cs:726`) and idles through `Keyboard.IdleWait()` while energy remains high (`decompiled/XRL.Core/XRLCore.cs:2307-2315`).
   - `Keyboard.PushKey` enqueues under lock and signals `KeyEvent` (`decompiled/ConsoleLib.Console/Keyboard.cs:763-781`).
   - Failure mode: the wake key is interpreted as a real player command, causing an unintended wait/move/menu action and changing energy. The probe must use the least-action key possible and assert energy unchanged until the post-reconnect decision.

2. **`PassTurn` is mechanically likely to resume but violates pause semantics.**
   - If energy is drained below 1000, the player branch at `decompiled/XRL.Core/ActionManager.cs:838` is skipped and render fallback runs at `decompiled/XRL.Core/ActionManager.cs:1806-1808`.
   - Failure mode: it is not a true pause. Time advances, NPCs/environment can act, and repeated disconnects can become blind engine-speed waiting. Use only as fallback if native idle wake is impossible.

3. **Block-BTA polling is a risky fallback, not a first choice.**
   - BTA happens before the inner action loop (`decompiled/XRL.Core/ActionManager.cs:786-800`). Blocking there prevents the normal CTA path from even starting.
   - If BTA returns false / `PreventAction`, ActionManager zeroes energy (`decompiled/XRL.Core/ActionManager.cs:788-791`), which is no longer “energy unchanged pause.”
   - Failure mode: Unity/game thread appears frozen, render and queue pumping starve, and a 30s disconnect becomes unacceptable. Only test with a hard <5s watchdog.

4. **`PreventAction = true` with no drain is lowest priority.**
   - ADR 0007 already established the bad shape: `CommandTakeActionEvent.Check` returns false when `PreventAction` is set (`decompiled/XRL.World/CommandTakeActionEvent.cs:37-39`), and ActionManager immediately `continue`s (`decompiled/XRL.Core/ActionManager.cs:829-832`).
   - Failure mode: no energy drain, no render fallback, repeated CTA loop or cadence collapse. This is the option most likely to reproduce the exact class of Phase 0-F failure.

## 4. Sequencing and batching

Yes, Probes 1, 2, 3, and 6 can be batched into one CoQ session if the Python server is a phase controller instead of a static server.

Smallest theoretical number of CoQ launches: **one**, if Probe 8’s first wake option works and no option wedges the process.

Practical recommendation: plan for **one primary launch plus one reserved recovery launch**. Run the non-destructive probes first, then Probe 8 with only the highest-priority wake option. Do not burn the same session testing low-priority freeze-prone options unless the primary option fails.

Python orchestration sketch:

- Start `brain/app.py --probe-script phase1-pr1`.
- C# connects once and sends normal `decision_input.v1` requests.
- Server maintains a request counter and phase state.

Suggested order:

1. **Probe 1**
   - 25 turns at 0ms.
   - 25 turns at 50ms.
   - 25 turns at 100ms.
   - 25 turns at 250ms.
   - Response: fixed valid `Move` decision.

2. **Probe 6**
   - 60 turns at 200ms.
   - Keep this separate from Probe 1 because the assertion is observation backlog, not just round-trip success.

3. **Probe 2**
   - 50 turns sleeping beyond timeout.
   - C# should take timeout fallback path.
   - This should not be conflated with socket close.

4. **Probe 3 revised**
   - Close mid-Decide.
   - For ADR 0013: expect pause entry, not fallback action.
   - If keeping legacy fallback Probe 3a, label it explicitly as timeout/fail-open-only and do not use it to lock disconnect=pause.

5. **Probe 8**
   - Hold disconnected for 30+ seconds.
   - Reconnect.
   - Try `Keyboard.PushKey` wake.
   - Verify next BTA/CTA timing, energy unchanged until fresh decision, no stale `[decision]`/`[cmd]`.

The server should support phase changes through stdin/admin command or deterministic request counts. Restarting Python between phases is acceptable, but not required. The C# side should tolerate server restart without a CoQ restart, because that is itself part of the reconnect contract.

## 5. Risks the Plan does not name

1. **C# WebSocket assembly availability may fail before runtime.**
   - CoQ’s mod compiler references currently loaded AppDomain assemblies (`decompiled/XRL/ModManager.cs:402-405`) and compiles mod files via Roslyn (`decompiled/XRL/ModInfo.cs:757-771`).
   - If `System.Net.WebSockets` / `ClientWebSocket` is not already referenceable, `BrainClient.cs` may fail to compile even though the design is sound.
   - Add a compile probe before in-game Probe 1.

2. **Bridge runtime state can corrupt save/load unless explicitly nonserialized and rehydrated.**
   - `IGameSystem` is `[Serializable]` (`decompiled/XRL/IGameSystem.cs:11-12`).
   - CoQ writes each system on save (`decompiled/XRL/XRLGame.cs:1573-1582`) and calls `AfterLoad` after load (`decompiled/XRL/XRLGame.cs:1818-1821`).
   - `ClientWebSocket`, threads, tasks, cancellation tokens, and pending request maps should not live in serialized fields. Mark runtime fields `[NonSerialized]`, recreate in `AfterLoad`/registration, and probe save/load.

3. **Startup race between CoQ mod load and Python server readiness.**
   - PR-1 requires Python WebSocket on localhost:4040, with `websockets` 16.0 in the Brain stack.
   - If CoQ connects during `RegisterPlayer` before `brain/app.py` is listening, the first turn may enter disconnect pause before Probe 1 begins.
   - Add bounded retry/backoff and a clear `[connection_lifecycle]` log before the first CTA decision.

## Disposition

- Probe 3 split into 3a (timeout) + 3b (disconnect=pause) — Plan
  Change 2.
- Probes A (BTA/CTA bypass), D (save/load lifecycle), E (wake-key
  innocuousness) added — Plan Changes 3, 4, 6.
- Probe 8 narrowed to (iv) primary + (ii) fallback; (i) not tested;
  (iii) rejected per ADR 0007 — Plan Change 5.
- §Risks updated with 3 new entries — Plan Change 8.
- Compile-sanity pre-probe step added — Plan Change 1.
- Probes B (long observation silence) and C (stale response/epoch)
  deferred: B is covered well-enough by Probe 6 + Probe D for PR-1
  scope; C is owned by PR-3 (1-G idempotency) and need not block
  PR-1.1.
