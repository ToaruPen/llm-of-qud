using System;
using System.Text;
using System.Threading;
using ConsoleLib.Console;
using XRL;
using XRL.Core;
using XRL.UI;
using XRL.World;
using XRL.World.Capabilities;   // NEW: AutoAct.ClearAutoMoveStop

namespace LLMOfQud
{
    [Serializable]
    public class LLMOfQudSystem : IPlayerSystem
    {
        public const string VERSION = "0.0.1";

        private static bool _loadMarkerLogged;
        private static bool _afterRenderRegistered;

        // Snapshot request handshake between HandleEvent (game thread) and
        // AfterRenderCallback (render thread). null = no pending request.
        // Game thread: Interlocked.Exchange a fully built PendingSnapshot.
        // Render thread: Interlocked.Exchange to null, captures the prior value.
        // Single class-instance keeps Turn and StateJson paired atomically;
        // a pair of int+string slots would not be atomic across the two writes.
        private static PendingSnapshot _pendingSnapshot;

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
            if (!Registrar.IsUnregister && !_afterRenderRegistered)
            {
                // XRLCore fires this after Zone.Render populates the source buffer
                // (including BackupChar for tile-mode cells) and BEFORE DrawBuffer
                // copies that source into CurrentBuffer through ConsoleChar.Copy,
                // which drops BackupChar. Source buffer is the only buffer from
                // which tile-mode ASCII glyphs are recoverable without mutating
                // game state.
                // decompiled/XRL.Core/XRLCore.cs:624-626 (RegisterAfterRenderCallback)
                // decompiled/XRL.Core/XRLCore.cs:2347-2351, 2380-2383, 2423-2426 (invocation sites)
                XRLCore.RegisterAfterRenderCallback(AfterRenderCallback);
                // Set the guard flag only after a successful Add so a hypothetical
                // throw inside RegisterAfterRenderCallback does not permanently
                // block future re-registration attempts.
                _afterRenderRegistered = true;
            }
            Registrar.Register(SingletonEvent<BeginTakeActionEvent>.ID);
            Registrar.Register(SingletonEvent<CommandTakeActionEvent>.ID);
            base.RegisterPlayer(Player, Registrar);
        }

        public override bool HandleEvent(BeginTakeActionEvent E)
        {
            _beginTurnCount++;

            // Build the structured state JSON on the game thread. This MUST run
            // on the game thread (not the render callback) because it reads
            // The.Player / Zone.GetObjects() / GameObject statistics — see
            // docs/architecture-v5.md:1787-1790 for the canonical routing rule.
            // Reading these on the render thread risks tearing.
            // Capture display_mode on the game thread so [screen] mode= and
            // [state] display_mode= for this turn are guaranteed to agree even
            // if Options.UseTiles flips before AfterRenderCallback fires.
            // BuildStateJson reads Options.UseTiles exactly once for the
            // [state] payload and returns the captured value via out so we
            // can reuse it for the [screen] header.
            string stateJson;
            string displayMode;
            try
            {
                stateJson = SnapshotState.BuildStateJson(_beginTurnCount, out displayMode);
            }
            catch (Exception ex)
            {
                // Mirror the AfterRenderCallback exception posture: never let
                // observation kill the mod. Emit a sentinel JSON so the parser
                // sees a valid line; the broader [state] line will still flow
                // for the next turn.
                stateJson = "{\"turn\":" + _beginTurnCount.ToString() +
                    ",\"error\":\"" + ex.GetType().Name + "\"}";
                displayMode = Options.UseTiles ? "tile" : "ascii";
                MetricsManager.LogInfo(
                    "[LLMOfQud][state] ERROR turn=" + _beginTurnCount +
                    " " + ex.GetType().Name + ": " + ex.Message);
            }

            // Phase 0-D: build caps JSON on the game thread in a separate
            // try/catch. Failure here MUST NOT kill the [state] emission;
            // produce a valid-JSON sentinel so downstream parsers always
            // see a parseable [caps] line for this turn. Use the existing
            // SnapshotState.AppendJsonString helper so control characters
            // (newline / tab / U+0000-U+001F) in ex.Message are escaped
            // RFC-8259 correctly — a coarse Replace chain would emit
            // invalid JSON exactly when a parser is most likely to break.
            string capsJson;
            try
            {
                capsJson = SnapshotState.BuildCapsJson(_beginTurnCount, The.Player);
            }
            catch (Exception ex)
            {
                StringBuilder errSb = new StringBuilder(256);
                errSb.Append("{\"turn\":").Append(_beginTurnCount.ToString())
                    .Append(",\"schema\":\"runtime_caps.v1\"")
                    .Append(",\"error\":{\"type\":");
                SnapshotState.AppendJsonString(errSb, ex.GetType().Name);
                errSb.Append(",\"message\":");
                SnapshotState.AppendJsonString(errSb, ex.Message ?? "");
                errSb.Append("}}");
                capsJson = errSb.ToString();
                MetricsManager.LogInfo(
                    "[LLMOfQud][caps] ERROR turn=" + _beginTurnCount +
                    " " + ex.GetType().Name + ": " + ex.Message);
            }

            // Phase 0-E: build build JSON on the game thread in a separate
            // try/catch. Failure here MUST NOT kill [state] or [caps]
            // emission; produce a valid-JSON sentinel so downstream parsers
            // always see a parseable [build] line for this turn. Use the
            // existing SnapshotState.AppendJsonString helper so control
            // characters (newline / tab / U+0000-U+001F) in ex.Message are
            // escaped RFC-8259 correctly.
            string buildJson;
            try
            {
                buildJson = SnapshotState.BuildBuildJson(_beginTurnCount, The.Player);
            }
            catch (Exception ex)
            {
                StringBuilder errSb = new StringBuilder(256);
                errSb.Append("{\"turn\":").Append(_beginTurnCount.ToString())
                    .Append(",\"schema\":\"current_build.v1\"")
                    .Append(",\"error\":{\"type\":");
                SnapshotState.AppendJsonString(errSb, ex.GetType().Name);
                errSb.Append(",\"message\":");
                SnapshotState.AppendJsonString(errSb, ex.Message ?? "");
                errSb.Append("}}");
                buildJson = errSb.ToString();
                MetricsManager.LogInfo(
                    "[LLMOfQud][build] ERROR turn=" + _beginTurnCount +
                    " " + ex.GetType().Name + ": " + ex.Message);
            }

            PendingSnapshot pending = new PendingSnapshot
            {
                Turn = _beginTurnCount,
                StateJson = stateJson,
                DisplayMode = displayMode,
                CapsJson = capsJson,
                BuildJson = buildJson,
            };
            Interlocked.Exchange(ref _pendingSnapshot, pending);

            if (_beginTurnCount % 10 == 0)
            {
                MetricsManager.LogInfo(
                    "[LLMOfQud] begin_take_action count=" + _beginTurnCount);
            }
            return base.HandleEvent(E);
        }

        // Phase 0-F: act on the player's command point.
        // Hook chosen per ADR 0006: CommandTakeActionEvent fires inside the inner
        // action loop in ActionManager (decompiled/XRL.Core/ActionManager.cs:829),
        // AFTER BeginTakeActionEvent has already enqueued the per-turn observation
        // snapshot. Acting here keeps EndActionEvent, hostile interrupt, AutoAct,
        // and the player render fallback (ActionManager.cs:1806-1808) intact.
        // BeginTakeActionEvent would skip all of those because draining energy
        // there fails the inner loop's gate at :800.
        // [cmd] is emitted on the game thread directly (NOT through PendingSnapshot)
        // — see ADR 0006 Consequence #3 and the design spec's Architecture section.
        public override bool HandleEvent(CommandTakeActionEvent E)
        {
            int turn = _beginTurnCount;
            GameObject player = The.Player;

            if (player == null)
            {
                MetricsManager.LogInfo(
                    "[LLMOfQud][cmd] {\"turn\":" + turn +
                    ",\"schema\":\"command_issuance.v1\",\"error\":{\"type\":\"NullPlayer\",\"message\":\"The.Player is null\"}}");
                E.PreventAction = true;
                return true;
            }

            int energyBefore = 0;
            try
            {
                energyBefore = player.Energy?.Value ?? 0;
                Cell cellBefore = player.CurrentCell;
                int posBeforeX = cellBefore?.X ?? -1;
                int posBeforeY = cellBefore?.Y ?? -1;
                string posBeforeZone = cellBefore?.ParentZone?.ZoneID;

                // Step B: adjacent hostile detection.
                // Direction priority: N -> NE -> E -> SE -> S -> SW -> W -> NW.
                // First non-null Cell.GetCombatTarget hit wins.
                // The filter o => o != player && o.IsHostileTowards(player) mirrors
                // what Combat.AttackCell uses internally (Combat.cs:877-889).
                string targetDir = null;
                GameObject targetObj = null;
                if (cellBefore != null)
                {
                    string[] priority = new[] { "N", "NE", "E", "SE", "S", "SW", "W", "NW" };
                    for (int i = 0; i < priority.Length; i++)
                    {
                        Cell adj = cellBefore.GetCellFromDirection(priority[i], BuiltOnly: false);
                        if (adj == null) continue;
                        // Verified signature at decompiled/XRL.World/Cell.cs:8511:
                        //   GetCombatTarget(GameObject Attacker = null,
                        //     bool IgnoreFlight = false, bool IgnoreAttackable = false,
                        //     bool IgnorePhase = false, int Phase = 0,
                        //     GameObject Projectile = null, GameObject Launcher = null,
                        //     GameObject CheckPhaseAgainst = null,
                        //     GameObject Skip = null, List<GameObject> SkipList = null,
                        //     bool AllowInanimate = true, bool InanimateSolidOnly = false,
                        //     Predicate<GameObject> Filter = null)
                        // GameObject.cs:10887-10894 IsHostileTowards.
                        GameObject t = adj.GetCombatTarget(
                            Attacker: player,
                            IgnoreFlight: false,
                            IgnoreAttackable: false,
                            IgnorePhase: false,
                            Phase: 5,
                            AllowInanimate: false,
                            Filter: o => o != player && o.IsHostileTowards(player));
                        if (t != null)
                        {
                            targetDir = priority[i];
                            targetObj = t;
                            break;
                        }
                    }
                }

                bool result;
                string action;
                string dir;
                string targetId = null;
                string targetName = null;
                bool hasTargetPosBefore = false;
                int targetPosBeforeX = -1;
                int targetPosBeforeY = -1;
                string targetPosBeforeZone = null;
                int? targetHpBefore = null;

                if (targetObj != null)
                {
                    targetId = targetObj.ID;
                    targetName = targetObj.ShortDisplayNameStripped;
                    Cell tCell = targetObj.CurrentCell;
                    if (tCell != null)
                    {
                        hasTargetPosBefore = true;
                        targetPosBeforeX = tCell.X;
                        targetPosBeforeY = tCell.Y;
                        targetPosBeforeZone = tCell.ParentZone?.ZoneID;
                    }
                    // hitpoints = Statistic.Value (live HP), per spec field semantics.
                    // GameObject.cs:1177-1198: hitpoints / baseHitpoints.
                    targetHpBefore = targetObj.hitpoints;
                    result = player.AttackDirection(targetDir);
                    action = "AttackDirection";
                    dir = targetDir;
                }
                else
                {
                    // Step A fallback: Move East.
                    AutoAct.ClearAutoMoveStop();   // mirror XRLCore.cs:1108
                    result = player.Move("E", DoConfirmations: false);
                    action = "Move";
                    dir = "E";
                }

                bool energySpent = (player.Energy != null && player.Energy.Value < energyBefore);

                string fallback = null;
                if (!result && !energySpent)
                {
                    player.PassTurn();
                    energySpent = true;
                    fallback = "pass_turn";
                }
                else if (!result)
                {
                    fallback = "pass_turn";
                }

                int? targetHpAfter = (targetObj != null) ? (int?)targetObj.hitpoints : null;
                int energyAfter = player.Energy?.Value ?? 0;
                Cell cellAfter = player.CurrentCell;

                SnapshotState.CmdRecord rec = new SnapshotState.CmdRecord
                {
                    Turn = turn,
                    Action = action,
                    Dir = dir,
                    Result = result,
                    Fallback = fallback,
                    EnergyBefore = energyBefore,
                    EnergyAfter = energyAfter,
                    PosBeforeX = posBeforeX,
                    PosBeforeY = posBeforeY,
                    PosBeforeZone = posBeforeZone,
                    PosAfterX = cellAfter?.X ?? -1,
                    PosAfterY = cellAfter?.Y ?? -1,
                    PosAfterZone = cellAfter?.ParentZone?.ZoneID,
                    TargetId = targetId,
                    TargetName = targetName,
                    HasTargetPosBefore = hasTargetPosBefore,
                    TargetPosBeforeX = targetPosBeforeX,
                    TargetPosBeforeY = targetPosBeforeY,
                    TargetPosBeforeZone = targetPosBeforeZone,
                    TargetHpBefore = targetHpBefore,
                    TargetHpAfter = targetHpAfter,
                };

                MetricsManager.LogInfo("[LLMOfQud][cmd] " + SnapshotState.BuildCmdJson(rec));
            }
            catch (Exception ex)
            {
                MetricsManager.LogInfo(
                    "[LLMOfQud][cmd] " + SnapshotState.BuildCmdSentinelJson(turn, ex));
                // Catch-path drain threshold = literal 1000, NOT energyBefore.
                // See Task 4 commentary: the exception may fire before energyBefore
                // is captured, in which case the local default of 0 would make a
                // ">= energyBefore" guard incorrectly skip drain. The autonomy
                // invariant is "engine does not wait on keyboard input"; that
                // depends only on Energy.Value < 1000 after our handler returns
                // (ActionManager.cs:800, :838, :1797-1799).
                if (player?.Energy != null && player.Energy.Value >= 1000)
                {
                    try { player.PassTurn(); } catch { /* swallow */ }
                    if (player.Energy.Value >= 1000)
                    {
                        player.Energy.BaseValue = 0;
                    }
                }
            }
            finally
            {
                // ADR 0007: PreventAction is Layer-4 abnormal-energy defense, not
                // the primary autonomy mechanism. The autonomy invariant (engine
                // does not wait on keyboard input) depends on Energy.Value < 1000
                // from Layers 1/2/3 (Move/AttackDirection success → PassTurn
                // fallback → BaseValue=0 last-ditch). The `:838` energy guard at
                // decompiled/XRL.Core/ActionManager.cs:838 already prevents the
                // keyboard-input branch (PlayerTurn at :1797-1799) when
                // Energy.Value < 1000; the iteration falls through to the
                // player render fallback at decompiled/XRL.Core/ActionManager.cs:1806-1808
                // and `[screen]/[state]/[caps]/[build]` flush per turn.
                //
                // Setting PreventAction = true would cause CommandTakeActionEvent.Check
                // (decompiled/XRL.World/CommandTakeActionEvent.cs:37-39) to return
                // false, the iteration to `continue` at decompiled/XRL.Core/ActionManager.cs:829-832,
                // and the render fallback to be skipped — destroying the
                // observation-channel cadence Phase 0-A through 0-E established.
                //
                // Reach this defense ONLY when post-recovery energy is still
                // >= 1000 (i.e., Layers 1/2/3 all failed to drain). One render
                // cadence is sacrificed to preserve autonomy.
                if (player?.Energy != null && player.Energy.Value >= 1000)
                {
                    E.PreventAction = true;
                }
            }

            return true;
        }

        // Render a ScreenBuffer as an ASCII grid. Tile-mode cells hold the
        // ASCII glyph in BackupChar (written by Zone.Render when _Tile is set,
        // decompiled/XRL.World/Zone.cs:5411-5418); non-tile cells keep the
        // glyph in Char. Fall back Char -> BackupChar -> space, and count each
        // cell's source so AfterRenderCallback can emit ascii_sources metadata.
        // decompiled/ConsoleLib.Console/ScreenBuffer.cs:21 (Buffer[,]), :79-100 (Width/Height)
        // decompiled/ConsoleLib.Console/ConsoleChar.cs:65 (BackupChar), :116 (Char property)
        private static string SnapshotAscii(
            ScreenBuffer buf, out int charCount, out int backupCount, out int blankCount)
        {
            charCount = 0;
            backupCount = 0;
            blankCount = 0;
            if (buf == null)
            {
                return "<null-buffer>\n";
            }
            int w = buf.Width;
            int h = buf.Height;
            if (w <= 0 || h <= 0 || buf.Buffer == null)
            {
                return "<empty-buffer w=" + w + " h=" + h + ">\n";
            }
            StringBuilder sb = new StringBuilder(w * h + h);
            for (int y = 0; y < h; y++)
            {
                for (int x = 0; x < w; x++)
                {
                    ConsoleChar cell = buf.Buffer[x, y];
                    char c = cell.Char;
                    if (c == '\0')
                    {
                        char backup = cell.BackupChar;
                        if (backup == '\0')
                        {
                            blankCount++;
                            sb.Append(' ');
                        }
                        else
                        {
                            backupCount++;
                            sb.Append(backup);
                        }
                    }
                    else
                    {
                        charCount++;
                        sb.Append(c);
                    }
                }
                sb.Append('\n');
            }
            return sb.ToString();
        }

        // Fires on the render thread after Zone.Render but before DrawBuffer.
        // No-op unless HandleEvent published a PendingSnapshot. Interlocked.Exchange
        // atomically captures-and-clears the slot so concurrent BeginTakeActionEvent
        // fires cannot double-log the same snapshot. Emits THREE LogInfo calls per
        // snapshot — one [screen] block (with display_mode + ascii_sources metadata),
        // one [state] structured line, one [caps] structured line — all sharing
        // turn=N as the parser-side correlation key. The parser must NOT assume
        // adjacency; LogInfo lines from other game subsystems can interleave.
        // decompiled/MetricsManager.cs:407-409 (LogInfo -> Player.log)
        // decompiled/XRL.UI/Options.cs:574-576 (Options.UseTiles)
        private static void AfterRenderCallback(XRLCore core, ScreenBuffer buf)
        {
            PendingSnapshot pending = Interlocked.Exchange<PendingSnapshot>(ref _pendingSnapshot, null);
            if (pending == null)
            {
                return;
            }
            int turn = pending.Turn;
            string stateJson = pending.StateJson;
            string capsJson = pending.CapsJson;
            string buildJson = pending.BuildJson;
            // Reuse the game-thread-captured DisplayMode so the [screen] mode=
            // header and the embedded [state] display_mode= for the same turn
            // are guaranteed to agree even if Options.UseTiles flipped between
            // HandleEvent and AfterRenderCallback.
            string displayMode = pending.DisplayMode;
            try
            {
                int w = buf != null ? buf.Width : 0;
                int h = buf != null ? buf.Height : 0;
                int charCount, backupCount, blankCount;
                string body = SnapshotAscii(buf, out charCount, out backupCount, out blankCount);

                // Frame 1: [screen] block, augmented with display_mode and counts
                // on the BEGIN line. END line is unchanged from 0-B for parser
                // continuity.
                MetricsManager.LogInfo(
                    "[LLMOfQud][screen] BEGIN turn=" + turn +
                    " w=" + w + " h=" + h +
                    " mode=" + displayMode +
                    " src=char:" + charCount + ",backup:" + backupCount + ",blank:" + blankCount +
                    "\n" + body +
                    "[LLMOfQud][screen] END turn=" + turn);

                // Frame 2: [state] structured line. Parser keys on turn=N to
                // correlate with the [screen] block; adjacency is NOT assumed
                // (see ADR 0004 acceptance step and docs/memo/phase-0-b-exit-
                // 2026-04-25.md).
                MetricsManager.LogInfo("[LLMOfQud][state] " + stateJson);
            }
            catch (Exception ex)
            {
                // Never let observation kill the mod. Each exception is logged
                // verbatim (type + message) so transient and recurring failures
                // both surface in Player.log without crashing the game. Phase 0-B
                // accepted ERROR=0 over 95 turns; if log spam ever shows up here,
                // dedupe at that point rather than pre-engineering a HashSet now.
                MetricsManager.LogInfo(
                    "[LLMOfQud][screen] ERROR turn=" + turn + " " + ex.GetType().Name + ": " + ex.Message);
            }

            // Phase 0-D: emit [caps] in its own try scope. A [caps] failure
            // here MUST NOT blank [screen]/[state] for this turn (those have
            // already emitted above). The capsJson value was prepared on the
            // game thread; if its build threw, capsJson is already an error
            // sentinel and this block just emits it verbatim.
            try
            {
                MetricsManager.LogInfo("[LLMOfQud][caps] " + capsJson);
            }
            catch (Exception ex)
            {
                MetricsManager.LogInfo(
                    "[LLMOfQud][caps] ERROR turn=" + turn + " " + ex.GetType().Name + ": " + ex.Message);
            }

            // Phase 0-E: emit [build] in its own try scope. A [build] failure
            // here MUST NOT blank [screen]/[state]/[caps] for this turn (those
            // have already emitted above). The buildJson value was prepared
            // on the game thread; if its build threw, buildJson is already an
            // error sentinel and this block just emits it verbatim.
            try
            {
                MetricsManager.LogInfo("[LLMOfQud][build] " + buildJson);
            }
            catch (Exception ex)
            {
                MetricsManager.LogInfo(
                    "[LLMOfQud][build] ERROR turn=" + turn + " " + ex.GetType().Name + ": " + ex.Message);
            }
        }
    }
}
