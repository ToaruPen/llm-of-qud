using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using System.Threading;
using ConsoleLib.Console;
using UnityEngine;
using XRL;
using XRL.Core;
using XRL.UI;
using XRL.World;
using XRL.World.Capabilities;   // AutoAct.ClearAutoMoveStop

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

        // Phase 1 PR-1: IDecisionPolicy boundary now crosses the WebSocket bridge.
        // Runtime bridge state is rehydrated from RegisterPlayer / AfterLoad because
        // IGameSystem is serialized and load calls AfterLoad
        // (decompiled/XRL/IGameSystem.cs:11-12; decompiled/XRL/XRLGame.cs:1818-1821).
        [NonSerialized] private IDecisionPolicy _policy;

        // Phase 0-G: memory for DecisionInput.Adjacent.BlockedDirs and .Recent.
        // Updated after each action dispatch, read by BuildDecisionInput on the
        // next CTA invocation. These are legitimate per-game instance state;
        // the [Serializable] attribute covers them as part of save/load.
        //
        // Per-cell blocked-dir memory: keyed by cell coordinate (x:y:zone).
        // BuildDecisionInput passes only the CURRENT cell's blocked-dir set as
        // DecisionInput.Adjacent.BlockedDirs, so the policy sees "directions
        // that failed FROM this cell" rather than "directions that failed
        // anywhere". Earlier Phase 0-G drafts used a flat HashSet plus a
        // clear-on-success rule; that lost wall knowledge whenever the player
        // stepped one cell, causing 2-cell pockets between walls to oscillate
        // forever (observed in Run 2: 49% pass_turn fallback rate over 1777
        // turns). Per-cell memory eliminates that re-learning loop without
        // changing the decision_input.v1 wire schema (BlockedDirs : List<string>
        // is unchanged; only the source of its contents shifts from global to
        // per-cell). HeuristicPolicy is unmodified.
        private readonly Dictionary<string, HashSet<string>> _blockedDirsByCell =
            new Dictionary<string, HashSet<string>>();
        private int _lastActionTurn = -1;
        private string _lastAction;
        private string _lastDir;
        private bool _lastResult;

        private void EnsureRuntimePolicy()
        {
            WebSocketPolicy webSocketPolicy = _policy as WebSocketPolicy;
            if (webSocketPolicy == null)
            {
                webSocketPolicy = new WebSocketPolicy(BrainClient.DefaultEndpoint, OnBrainReconnected);
                _policy = webSocketPolicy;
                return;
            }
            webSocketPolicy.EnsureClient(OnBrainReconnected);
        }

        private static void OnBrainReconnected()
        {
            // Probe 8 default: wake native PlayerTurn keyboard idle by injecting
            // the most inert key. Keyboard.PushKey enqueues and signals KeyEvent at
            // decompiled/ConsoleLib.Console/Keyboard.cs:763-781; PlayerTurn idles
            // on Keyboard.IdleWait at decompiled/XRL.Core/XRLCore.cs:2307-2315.
            //
            // Probe 8 fallback (not active): drain one turn via PassTurn if PushKey
            // is empirically falsified. Do not use PreventAction-without-drain.
            Keyboard.PushKey(KeyCode.None);
            MetricsManager.LogInfo("[LLMOfQud][wake] PushKey injected key=None");
        }

        // Cell key for _blockedDirsByCell. Stable string form so the dictionary
        // does not depend on Cell object identity (Cell instances are
        // re-created when zones unload / reload). Format mirrors the [cmd]
        // pos_before / pos_after JSON shape so debugging across channels is
        // trivial: "x:y:zone".
        private static string CellKey(int x, int y, string zone)
        {
            return x.ToString(CultureInfo.InvariantCulture) + ":" +
                   y.ToString(CultureInfo.InvariantCulture) + ":" +
                   (zone ?? "<null-zone>");
        }

        public override void RegisterPlayer(GameObject Player, IEventRegistrar Registrar)
        {
            if (!Registrar.IsUnregister && !_loadMarkerLogged)
            {
                _loadMarkerLogged = true;
                Logger.buildLog.Info(
                    "[LLMOfQud] loaded v" + VERSION +
                    " at " + DateTime.UtcNow.ToString("o"));
            }
            if (!Registrar.IsUnregister)
            {
                EnsureRuntimePolicy();
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

        public override void AfterLoad(XRLGame game)
        {
            base.AfterLoad(game);
            EnsureRuntimePolicy();
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

        // Phase 0-G: build the DecisionInput DTO that the policy receives.
        // hostileObj (out) carries the adjacent-hostile reference so the
        // caller can capture target_* fields without an instance field
        // (addendum A2: no stale-state leakage between CTA dispatches).
        // cell may be null (player not positioned); defensive fallbacks
        // match Phase 0-F's posBeforeX/Y = -1, zone = null pattern.
        private DecisionInput BuildDecisionInput(
            GameObject player, int turn, out GameObject hostileObj)
        {
            Cell cell = player.CurrentCell;
            string hostileDir;
            ScanAdjacentHostile(cell, player, out hostileDir, out hostileObj);

            int posX = cell != null ? cell.X : -1;
            int posY = cell != null ? cell.Y : -1;
            string posZone = cell?.ParentZone?.ZoneID;

            return new DecisionInput
            {
                Turn = turn,
                Player = new PlayerSnapshot
                {
                    // decompiled/XRL.World/GameObject.cs:1177-1198: hitpoints / baseHitpoints.
                    Hp = player.hitpoints,
                    MaxHp = player.baseHitpoints,
                    Pos = new Pos { X = posX, Y = posY, Zone = posZone },
                },
                Adjacent = new AdjacencySnapshot
                {
                    HostileDir = hostileDir,
                    HostileId = (hostileObj != null) ? hostileObj.ID : null,
                    // Per-cell lookup: pass only THIS cell's blocked-dir
                    // history. Empty list when the cell has never had a
                    // failed Move from it. See _blockedDirsByCell docstring.
                    BlockedDirs = LookupBlockedDirsForCell(posX, posY, posZone),
                },
                Recent = new RecentHistory
                {
                    LastActionTurn = _lastActionTurn,
                    LastAction = _lastAction,
                    LastDir = _lastDir,
                    LastResult = _lastResult,
                },
            };
        }

        // Phase 0-G: update blocked-direction memory after each action.
        // A Move that needed a PassTurn fallback means the direction was
        // blocked AT pos_before; record it on that cell's entry only.
        // Successful Moves do NOT clear memory — wall geometry is persistent
        // in Joppa, and earlier Phase 0-G drafts that cleared on success
        // re-learned the same walls every time the player re-entered a cell
        // (oscillation observed in Run 2).
        private void UpdateBlockedDirsMemory(
            string action, string dir, bool result, string fallback,
            int posBeforeX, int posBeforeY, string posBeforeZone)
        {
            if (action != "Move" || dir == null) return;
            if (result || fallback != "pass_turn") return;

            string key = CellKey(posBeforeX, posBeforeY, posBeforeZone);
            HashSet<string> set;
            if (!_blockedDirsByCell.TryGetValue(key, out set))
            {
                set = new HashSet<string>();
                _blockedDirsByCell[key] = set;
            }
            set.Add(dir);
            // Per-cell cap at 8 (one per cardinal / ordinal direction). At
            // 8 the cell is fully blocked; any further failed dir is a
            // duplicate of an existing entry.
        }

        // Phase 0-G: read the current cell's blocked-dir history into a fresh
        // list for DecisionInput.Adjacent.BlockedDirs. Returns an empty list
        // (NOT null) when no entry exists, matching the schema invariant that
        // BlockedDirs is always a list (possibly empty).
        private List<string> LookupBlockedDirsForCell(int x, int y, string zone)
        {
            string key = CellKey(x, y, zone);
            HashSet<string> set;
            if (_blockedDirsByCell.TryGetValue(key, out set) && set.Count > 0)
            {
                return new List<string>(set);
            }
            return new List<string>();
        }

        // Phase 0-G: persist the most-recent action for DecisionInput.Recent.
        private void UpdateRecentHistory(string action, string dir, bool result, int turn)
        {
            _lastActionTurn = turn;
            _lastAction = action;
            _lastDir = dir;
            _lastResult = result;
        }

        // Phase 0-G: scan adjacent cells for the nearest hostile in direction-
        // priority order. Direction priority: N -> NE -> E -> SE -> S -> SW -> W -> NW.
        // First non-null Cell.GetCombatTarget hit wins. The filter mirrors what
        // Combat.AttackCell uses internally (decompiled/XRL.World.Parts/Combat.cs:877-889).
        // Extracted from the Phase 0-F inline block for reuse by BuildDecisionInput.
        private static void ScanAdjacentHostile(
            Cell cellBefore, GameObject player,
            out string targetDir, out GameObject targetObj)
        {
            targetDir = null;
            targetObj = null;
            if (cellBefore == null) return;
            string[] priority = new[] { "N", "NE", "E", "SE", "S", "SW", "W", "NW" };
            for (int i = 0; i < priority.Length; i++)
            {
                // Verified signature at decompiled/XRL.World/Cell.cs:7322:
                //   public Cell GetCellFromDirection(string Direction, bool BuiltOnly = true)
                // BuiltOnly:false matches XRLCore's CmdMoveE wrapper which uses the same
                // un-built-aware lookup (Cell-level neighbor, not Zone-level).
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
                // decompiled/XRL.World/GameObject.cs:10887-10894 IsHostileTowards.
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
                    return;
                }
            }
        }

        // Phase 0-G: act on the player's command point with the explicit
        // BuildDecisionInput → Decide → Execute boundary (ADR 0009).
        // Hook chosen per ADR 0006: CommandTakeActionEvent fires inside the inner
        // action loop in ActionManager (decompiled/XRL.Core/ActionManager.cs:829),
        // AFTER BeginTakeActionEvent has already enqueued the per-turn observation
        // snapshot. Acting here keeps EndActionEvent, hostile interrupt, AutoAct,
        // and the player render fallback (decompiled/XRL.Core/ActionManager.cs:1806-1808) intact.
        // BeginTakeActionEvent would skip all of those because draining energy
        // there fails the inner loop's gate at decompiled/XRL.Core/ActionManager.cs:800.
        // [decision] and [cmd] are emitted on the game thread directly (NOT through
        // PendingSnapshot) — see ADR 0006 Consequence #3.
        public override bool HandleEvent(CommandTakeActionEvent E)
        {
            int turn = _beginTurnCount;
            GameObject player = The.Player;

            // Addendum A3: null-player sentinel path. Emit [decision] sentinel
            // BEFORE [cmd] sentinel (spec: [decision] precedes [cmd] on every
            // code path for parser parity). Then set PreventAction and return.
            // BuildDecisionInput is NOT called when player is null.
            if (player == null)
            {
                MetricsManager.LogInfo(
                    "[LLMOfQud][decision] {\"turn\":" + turn +
                    ",\"schema\":\"decision.v1\",\"error\":{\"type\":\"NullPlayer\"" +
                    ",\"message\":\"The.Player is null\"}}");
                MetricsManager.LogInfo(
                    "[LLMOfQud][cmd] {\"turn\":" + turn +
                    ",\"schema\":\"command_issuance.v1\",\"error\":{\"type\":\"NullPlayer\",\"message\":\"The.Player is null\"}}");
                E.PreventAction = true;
                return true;
            }

            // decisionEmitted tracks whether a [decision] line has been logged so
            // the outer catch can decide whether to emit a [decision] sentinel itself
            // (needed when BuildDecisionInput or Execute throws before Decide runs).
            bool decisionEmitted = false;
            bool disconnectPause = false;
            int energyBefore = 0;
            try
            {
                energyBefore = player.Energy?.Value ?? 0;
                Cell cellBefore = player.CurrentCell;
                int posBeforeX = cellBefore?.X ?? -1;
                int posBeforeY = cellBefore?.Y ?? -1;
                string posBeforeZone = cellBefore?.ParentZone?.ZoneID;

                // ---- BuildDecisionInput ----
                // hostileObj is captured here (addendum A2: out param, not instance
                // field) so target_* capture below uses the same reference that
                // informed the decision, without stale-state leakage.
                GameObject hostileObj;
                DecisionInput input = BuildDecisionInput(player, turn, out hostileObj);

                // ---- Decide ----
                Decision decision;
                try
                {
                    EnsureRuntimePolicy();
                    decision = _policy.Decide(input);
                }
                catch (DisconnectedException)
                {
                    throw;
                }
                catch (Exception policyEx)
                {
                    MetricsManager.LogInfo(
                        "[LLMOfQud][decision] " +
                        SnapshotState.BuildDecisionSentinelJson(turn, policyEx));
                    decisionEmitted = true;
                    throw;  // propagates to outer catch for [cmd] sentinel + drain
                }

                // [decision] MUST be emitted BEFORE [cmd] on the same handler invocation.
                MetricsManager.LogInfo(
                    "[LLMOfQud][decision] " +
                    SnapshotState.BuildDecisionJson(turn, decision, input));
                decisionEmitted = true;

                // ---- Execute ----
                // target_* capture: snap hostileObj state BEFORE the action dispatch
                // so target_hp_before reflects pre-attack HP (Phase 0-F invariant).
                // target_* is populated ONLY when decision.Action == "AttackDirection",
                // preserving Phase 0-F's structural invariant that target_id != null
                // implies an attack outcome row (mirrors SnapshotState.CmdRecord
                // docstring "null when no hostile attacked"). For escape/explore Move
                // decisions, target_* stays null even when hostileObj is non-null —
                // the [decision] line's input_summary.adjacent_hostile_dir captures
                // the scan-time presence so downstream parsers don't lose that signal.
                string targetId = null;
                string targetName = null;
                bool hasTargetPosBefore = false;
                int targetPosBeforeX = -1;
                int targetPosBeforeY = -1;
                string targetPosBeforeZone = null;
                int? targetHpBefore = null;

                if (decision.Action == "AttackDirection" && hostileObj != null)
                {
                    targetId = hostileObj.ID;
                    targetName = hostileObj.ShortDisplayNameStripped;
                    Cell tCell = hostileObj.CurrentCell;
                    if (tCell != null)
                    {
                        hasTargetPosBefore = true;
                        targetPosBeforeX = tCell.X;
                        targetPosBeforeY = tCell.Y;
                        targetPosBeforeZone = tCell.ParentZone?.ZoneID;
                    }
                    // hitpoints = Statistic.Value (live HP), per spec field semantics.
                    // decompiled/XRL.World/GameObject.cs:1177-1198: hitpoints / baseHitpoints.
                    targetHpBefore = hostileObj.hitpoints;
                }

                bool result = false;
                string fallback = null;

                // decision.v1 locks Action ∈ {"Move", "AttackDirection"}.
                // PassTurn is engine bookkeeping (3-layer drain Layer-2 fallback),
                // never a Decision.Action. Adding PassTurn requires decision.v2 +
                // command_issuance.v2 bump per spec.
                if (decision.Action == "AttackDirection")
                {
                    // decompiled/XRL.World/GameObject.cs:17882
                    result = player.AttackDirection(decision.Dir);
                }
                else if (decision.Action == "Move")
                {
                    // Addendum A4: ClearAutoMoveStop BEFORE every Move dispatch,
                    // regardless of intent (escape or explore).
                    // Mirrors decompiled/XRL.Core/XRLCore.cs:1108.
                    AutoAct.ClearAutoMoveStop();
                    // decompiled/XRL.World/GameObject.cs:15719
                    result = player.Move(decision.Dir, DoConfirmations: false);
                }

                // 3-layer drain — applies UNIFORMLY to BOTH terminal actions
                // (Phase 0-F invariant). Either action can return false without
                // spending energy (Move bumps wall; AttackDirection misses moved
                // target). The fallback check is outside the action-dispatch
                // branch, not inside Move's branch only.
                bool energySpent = (player.Energy != null && player.Energy.Value < energyBefore);
                if (!result && !energySpent)
                {
                    player.PassTurn();
                    energySpent = true;
                    fallback = "pass_turn";
                }
                else if (!result)
                {
                    // Action drained energy on its own fail path; record for log
                    // honesty (Phase 0-F spec invariant).
                    fallback = "pass_turn";
                }

                // Update memory AFTER drain, BEFORE emitting [cmd]. Per-cell
                // blocked-dir memory uses pos_before (the cell where the failed
                // Move was attempted FROM) as the dictionary key.
                UpdateBlockedDirsMemory(
                    decision.Action, decision.Dir, result, fallback,
                    posBeforeX, posBeforeY, posBeforeZone);
                UpdateRecentHistory(decision.Action, decision.Dir, result, turn);

                // target_hp_after gated on the same AttackDirection-only condition as
                // target_hp_before so the [cmd] row remains internally consistent
                // (an attack-only row has both before/after; a non-attack row has
                // both null). hostileObj may have moved or died; the after-snapshot
                // is taken from the same reference we recorded for before.
                int? targetHpAfter = (decision.Action == "AttackDirection" && hostileObj != null)
                    ? (int?)hostileObj.hitpoints
                    : null;
                int energyAfter = player.Energy?.Value ?? 0;
                Cell cellAfter = player.CurrentCell;

                SnapshotState.CmdRecord rec = new SnapshotState.CmdRecord
                {
                    Turn = turn,
                    Action = decision.Action,
                    Dir = decision.Dir,
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
            catch (DisconnectedException ex)
            {
                // ADR 0011 Q3: disconnect means pause, not runtime HeuristicPolicy
                // fallback. Emit a non-decision.v1 sentinel-style line only; no
                // [cmd], no terminal action, no energy mutation, and no
                // PreventAction. Keeping Energy.Value >= 1000 lets ActionManager
                // enter PlayerTurn at decompiled/XRL.Core/ActionManager.cs:838,
                // :1797-1799; reconnect wake uses Keyboard.PushKey.
                disconnectPause = true;
                decisionEmitted = true;
                MetricsManager.LogInfo(
                    "[LLMOfQud][decision] DISCONNECTED turn=" + turn +
                    " posture=pause message=" + SanitizeForLog(ex.Message));
            }
            catch (Exception ex)
            {
                // If [decision] was not yet emitted (BuildDecisionInput or pre-Decide
                // code threw), emit a [decision] sentinel first so [decision] always
                // precedes [cmd] on every code path.
                if (!decisionEmitted)
                {
                    MetricsManager.LogInfo(
                        "[LLMOfQud][decision] " +
                        SnapshotState.BuildDecisionSentinelJson(turn, ex));
                }
                MetricsManager.LogInfo(
                    "[LLMOfQud][cmd] " + SnapshotState.BuildCmdSentinelJson(turn, ex));

                // Catch-path drain threshold = literal 1000, NOT energyBefore.
                // ADR 0007: the exception may fire before energyBefore is captured,
                // in which case the local default of 0 would make a ">= energyBefore"
                // guard incorrectly skip drain. The autonomy invariant depends on
                // Energy.Value < 1000 after this handler returns.
                // decompiled/XRL.Core/ActionManager.cs:800, :838, :1797-1799.
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
                // keyboard-input branch (PlayerTurn at decompiled/XRL.Core/ActionManager.cs:1797-1799) when
                // Energy.Value < 1000; the iteration falls through to the
                // player render fallback at decompiled/XRL.Core/ActionManager.cs:1806-1808
                // and `[screen]/[state]/[caps]/[build]` flush per turn.
                //
                // Setting PreventAction = true would cause CommandTakeActionEvent.Check
                // (decompiled/XRL.World/CommandTakeActionEvent.cs:37-39) to return
                // false, the iteration to `continue` at decompiled/XRL.Core/ActionManager.cs:829-832,
                // and the render fallback to be skipped — destroying the
                // observation-channel cadence Phase 0-A through 0-G established.
                //
                // Reach this defense ONLY when post-recovery energy is still
                // >= 1000 (i.e., Layers 1/2/3 all failed to drain). One render
                // cadence is sacrificed to preserve autonomy.
                if (!disconnectPause && player?.Energy != null && player.Energy.Value >= 1000)
                {
                    E.PreventAction = true;
                }
            }

            return true;
        }

        private static string SanitizeForLog(string value)
        {
            if (value == null)
            {
                return "";
            }
            return value.Replace('\n', ' ').Replace('\r', ' ');
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
