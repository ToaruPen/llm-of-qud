using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Threading;
using ConsoleLib.Console;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Qud.API;
using QupKit;
using Qud.UI;
using XRL;
using XRL.Core;
using XRL.Rules;
using XRL.UI;
using XRL.World;
using XRL.World.Capabilities;
using XRL.World.Effects;

namespace LlmOfQud
{
    [HasModSensitiveStaticCache, HasCallAfterGameLoaded]
    public static class Bootstrap
    {
        [ModSensitiveCacheInit]
        public static void Init() { Runtime.Init(); }
        [CallAfterGameLoaded]
        public static void Loaded() { Runtime.Loaded(); }
    }

    [Serializable]
    public sealed class TurnSystem : IPlayerSystem
    {
        public override void RegisterPlayer(GameObject player, IEventRegistrar registrar)
        {
            registrar.Register(SingletonEvent<CommandTakeActionEvent>.ID);
            base.RegisterPlayer(player, registrar);
        }
        public override bool HandleEvent(CommandTakeActionEvent e) { return Runtime.OnCta(); }
    }

    internal static class Runtime
    {
        private static bool _uiStarted, _previousBackground, _backgroundCaptured;
        private static BackgroundSession _startup;
        private static bool _startupRead;
        private static volatile bool _quitRequested;
        private static volatile int _state; // 0 inactive, 1 armed, 2 controlled
        private static volatile bool _mapRequested;
        private static string _runId;
        private static string _gameId;
        private static long _lastWorldTurn;
        private static XRLGame _controlledGame;
        // Orders the UI-thread suspension against Loaded's recovery and game swap.
        private static readonly object Lifecycle = new object();
        private static volatile CheckpointLoad _checkpointLoad;
        private sealed class CheckpointLoad
        {
            public string Hash;
            public long TurnBefore;
            public bool Accepted;
            public readonly ManualResetEventSlim Answered = new ManualResetEventSlim(false);
        }
        private static volatile string _fatal;
        private static bool _development;
        private static Bridge _bridge;
        private static long _seq, _ctas, _mapFrame, _lastPoll, _travelCtas;
        // True only inside a compass Move that began on the world map (game thread only).
        private static bool _travelling;
        private static int _endTurns, _playerTurns, _uiTasks, _unknownTasks;
        private static long _strayKeys;
        private static string[] _map;
        private static readonly MessageDigest Digest = new MessageDigest();
        // Captured with the published observation on the game thread; never rebuilt when resolving an action.
        private static readonly Dictionary<string, GameObject> ItemHandles = new Dictionary<string, GameObject>();
        private static readonly FieldInfo QueueField = typeof(ThreadTaskQueue).GetField("taskQueue", BindingFlags.Instance | BindingFlags.NonPublic);
        private static readonly FieldInfo ActionField = typeof(ThreadTaskQueueEntry).GetField("actionToTake", BindingFlags.Instance | BindingFlags.NonPublic);
        private static JObject _pending;
        private static long _turnBefore;
        private static int _energyBefore, _energyAfter, _steps, _lastX, _lastY;
        private static bool _executed;
        private static string _reason;
        private static MacroGuard _macro;
        private static string _macroZone;
        private static HashSet<GameObject> _knownHostiles;
        private static HashSet<string> _macroEffects;
        private static ObservationAudit _audit; // null unless the local arm payload sets "audit":true
        private static readonly ModalDriver Modals = new ModalDriver(EmitModal, AddModalDigest, BeforeModalRule);

        internal static void Log(object value) { MetricsManager.LogInfo("[LLM] " + JsonConvert.SerializeObject(value)); }

        private static string SaveHash(string file)
        {
            using (var stream = File.OpenRead(The.Game.GetCacheDirectory(file + ".sav.gz")))
            using (var hash = SHA256.Create())
                return BitConverter.ToString(hash.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
        }

        private static void BeforeModalRule(string rule)
        {
            if (rule == "death_reload_checkpoint")
                _checkpointLoad = new CheckpointLoad { Hash = SaveHash("Checkpoint"), TurnBefore = The.Game.Turns };
        }

        public static void Loaded()
        {
            if (_state == 0 && _startup != null)
            {
                try
                {
                    Arm(_startup.Loaded());
                    The.ActionManager.SkipPlayerTurn = true;
                    // Arrival notices may precede the first CTA even in a fresh game.
                    // Normal notice rules must run; the bridge buffers events for seq 1.
                    Modals.SetContext(_runId, 1, true);
                    Log(new { kind = "background_loaded", run_id = _runId, game_id = _gameId, loaded_turn = The.Game.Turns });
                }
                catch (Exception ex)
                {
                    _fatal = "background_load:" + ex.GetType().Name;
                    if (The.Game != null) The.Game.Running = false;
                    Log(new { kind = "background_error", error = ex.ToString() });
                    GameManager.Instance.uiQueue.queueTask(() => GameManager.Instance.Quit());
                }
                return;
            }
            if (_state == 0) return;
            // A checkpoint may predate arming, so its serialized systems omit TurnSystem.
            // Restore the registrar before the engine can enter its player input loop.
            The.Game.RequireSystem<TurnSystem>();
            The.ActionManager.SkipPlayerTurn = true;
            Modals.SetContext(_runId, _seq, false);
            try
            {
                if (_fatal != null) throw new InvalidOperationException("Cannot recover a faulted run");
                if (The.Game.GameID != _gameId) throw new InvalidOperationException("Loaded a different game");
                string file;
                var checkpoint = _checkpointLoad;
                if (checkpoint != null)
                {
                    // A load continuation may reach this hook before the UI has
                    // published its acknowledgement. Preserve that ordering explicitly.
                    if (!checkpoint.Answered.Wait(2000) || !checkpoint.Accepted)
                        throw new InvalidOperationException("Checkpoint reload was not acknowledged");
                    file = "Checkpoint";
                    _lastWorldTurn = checkpoint.TurnBefore;
                }
                else if (_controlledGame != null && !_controlledGame.Running)
                    // Normal Continue after the prior game ended loads this slot's
                    // Primary (Qud.API/SaveGameInfo.cs:54-58). Live quickloads are refused.
                    file = "Primary";
                else throw new InvalidOperationException("Unverified load source");
                var meta = JObject.Parse(File.ReadAllText(The.Game.GetCacheDirectory(file + ".json")));
                if ((long?)meta["Turn"] != The.Game.Turns) throw new InvalidOperationException("Loaded save turn differs from metadata");
                string sha = SaveHash(file);
                if (checkpoint != null && checkpoint.Hash != sha) throw new InvalidOperationException("Checkpoint changed while loading");
                var recovery = new JObject { ["kind"] = "recovery", ["run_id"] = _runId, ["seq"] = _seq,
                    ["recovery_id"] = Guid.NewGuid().ToString(), ["reason"] = file == "Checkpoint" ? "checkpoint_reload" : "save_reload",
                    ["game_id"] = _gameId, ["save_file"] = file, ["save_sha256"] = sha,
                    ["turn_before"] = _lastWorldTurn, ["loaded_turn"] = The.Game.Turns,
                    ["lost_turns"] = Math.Max(0, _lastWorldTurn - The.Game.Turns) };
                _bridge.PublishRecovery(recovery);
                _pending = null; _macro = null; _knownHostiles = null;
                AutoAct.Interrupt();
                Keyboard.ClearInput();
                Digest.Clear();
                _lastWorldTurn = The.Game.Turns;
                // A UI-thread suspension check reads the old game and suspends atomically
                // with respect to this swap; it cannot land on the next CTA's request.
                lock (Lifecycle) { _controlledGame = The.Game; _checkpointLoad = null; }
                // Zone activation can show an arrival notice before the next CTA.
                // Give it the upcoming seq; the bridge buffers its events until that
                // request exists. System-rule popups must remain driveable meanwhile.
                Modals.SetContext(_runId, _seq + 1, true);
                Log(recovery);
            }
            catch (Exception ex)
            {
                _fatal = "load_recovery:" + ex.GetType().Name;
                _bridge.PublishFault(_fatal);
                Log(new { kind = "load_recovery_error", error = ex.ToString() });
            }
        }

        // The controlled game stopped running (exit to the main menu, or an end without a
        // reload). Void the open request so the harness cannot act on it; this is Loaded's
        // Primary-source condition, so only a verified reload (recovery) or a fault follows.
        // External answers stop; a live death menu keeps its automatic response.
        private static bool SuspendIfEnded()
        {
            lock (Lifecycle)
            {
                var game = _controlledGame; var bridge = _bridge;
                if (_state != 2 || bridge == null || _fatal != null || game == null || game.Running) return false;
                Modals.SuspendAnswers();
                if (bridge.Suspend()) Log(new { kind = "suspended", run_id = _runId, seq = _seq, reason = "game_not_running" });
                return true;
            }
        }

        public static void Init()
        {
            string startPath = DataManager.SavePath("llm-start.json");
            if (!SurfaceMatches("init"))
            {
                if (File.Exists(startPath)) GameManager.Instance.uiQueue.queueTask(() => GameManager.Instance.Quit());
                return;
            }
            if (!_startupRead)
            {
                _startupRead = true;
                try
                {
                    if (File.Exists(startPath))
                    {
                        string raw = File.ReadAllText(startPath);
                        // Consume even malformed intents so restart cannot retry them silently.
                        File.Delete(startPath);
                        var start = BackgroundStart.Parse(JObject.Parse(raw,
                            new JsonLoadSettings { DuplicatePropertyNameHandling = DuplicatePropertyNameHandling.Error }));
                        if (File.Exists(DataManager.SavePath("llm-control.json")))
                            throw new InvalidDataException("Pending operator control at background startup");
                        _startup = new BackgroundSession(start);
                        _runId = start.RunId;
                        _bridge = new Bridge(_runId, Modals.EnqueueAnswer);
                        Log(new { kind = "background_start", run_id = _runId, game_id = start.GameId });
                    }
                }
                catch (Exception ex)
                {
                    Log(new { kind = "background_error", error = ex.ToString() });
                    GameManager.Instance.uiQueue.queueTask(() => GameManager.Instance.Quit());
                    return;
                }
            }
            Register("OnEndPlayerTurnCallbacks", (Action<XRLCore>)OnEndTurn);
            Register("OnBeginPlayerTurnCallbacks", (Action<XRLCore>)OnBeginTurn);
            Register("OnNewMessageLogEntryCallbacks", (Action<string>)OnMessage);
            Register("AfterRenderCallbacks", (Action<XRLCore, ScreenBuffer>)AfterRender);
            if (!_uiStarted && GameManager.Instance != null)
            {
                _uiStarted = true;
                GameManager.Instance.uiQueue.queueTask(UiTick);
            }
            Log(new { kind = "init", assembly = typeof(XRLCore).Assembly.GetName().Version.ToString() });
        }

        // Game members reached by name through reflection; logs the sorted problems and refuses on any mismatch.
        private static bool SurfaceMatches(string phase)
        {
            string[] problems = SurfaceCheck.Validate();
            if (problems.Length == 0) return true;
            Log(new { kind = "surface_check_failed", phase, assembly = typeof(XRLCore).Assembly.GetName().Version.ToString(), problems });
            return false;
        }

        private static void Register<T>(string name, T callback)
        {
            var field = typeof(XRLCore).GetField(name, BindingFlags.Static | BindingFlags.NonPublic);
            var list = field == null ? null : field.GetValue(null) as IList<T>;
            if (list == null) throw new MissingFieldException("Callback list " + name);
            CallbackRegistration.Ensure(list, callback);
            int own = 0;
            foreach (T value in list) if (EqualityComparer<T>.Default.Equals(value, callback)) own++;
            Log(new { kind = "callback_registration", callback = name, own_count = own });
        }

        private static void AddModalDigest(string text)
        {
            Digest.Add(text);
            var audit = _audit;
            if (audit != null) audit.Modal(text);
        }

        private static void EmitModal(JObject message)
        {
            var bridge = _bridge;
            if (bridge == null) return;
            try
            {
                bridge.PublishModal(message);
                if ((string)message["kind"] == "modal_auto" && (string)message["rule"] == "death_reload_checkpoint")
                {
                    var checkpoint = _checkpointLoad;
                    if (checkpoint != null)
                    {
                        checkpoint.Accepted = (bool)message["accepted"];
                        checkpoint.Answered.Set();
                    }
                }
            }
            catch (Exception ex)
            {
                _fatal = "modal_transport:" + ex.GetType().Name;
                Log(new { kind = "modal_transport_error", error = ex.ToString() });
            }
        }

        private static void OnMessage(string message) { if (_state != 0 && message != "!clear") Digest.Add(message); }

        private static void OnBeginTurn(XRLCore core)
        {
            if (_state != 2) return;
            foreach (var frame in new StackTrace(false).GetFrames())
            {
                var method = frame.GetMethod();
                if (method.DeclaringType == typeof(XRLCore) && method.Name == "PlayerTurn")
                {
                    _playerTurns++;
                    Log(new { kind = "player_turn_entered", run_id = _runId, seq = _seq });
                    break;
                }
            }
        }

        private static void OnEndTurn(XRLCore core)
        {
            if (_state == 0) PollControl();
            else if (_state == 2) _endTurns++;
            if (_state != 0)
            {
                The.ActionManager.SkipPlayerTurn = true;
                Keyboard.KeyEvent.Set();
            }
        }

        // Local operator control; deliberately absent from the LLM tool surface.
        private static bool PollControl()
        {
            long now = Stopwatch.GetTimestamp();
            if ((now - _lastPoll) * 1000.0 / Stopwatch.Frequency < 200) return false;
            _lastPoll = now;
            string path = DataManager.SavePath("llm-control.json");
            if (!File.Exists(path)) return false;
            string raw = File.ReadAllText(path);
            File.Delete(path);
            var control = JObject.Parse(raw);
            string command = (string)control["command"];
            if (command == "save_and_quit")
            {
                try
                {
                    BackgroundStart.ValidateStop(control, _runId, _seq, _state == 2 && _fatal == null &&
                        _pending == null && The.Game.Running && (string)Modals.Status()["type"] == "none");
                }
                catch (ArgumentException ex)
                {
                    Log(new { kind = "stop_refused", run_id = _runId, seq = _seq, reason = ex.Message });
                    return false;
                }
                var game = The.Game;
                game.SaveTask?.GetAwaiter().GetResult();
                string previousHash = SaveHash("Primary");
                ZoneManager.instance.CheckCached(AllowFreeze: true, ForceFreeze: true);
                game.SaveGame("Primary")?.GetAwaiter().GetResult();
                var meta = JObject.Parse(File.ReadAllText(game.GetCacheDirectory("Primary.json")));
                string savedHash = SaveHash("Primary");
                if ((string)meta["ID"] != _gameId || (long?)meta["Turn"] != game.Turns || savedHash == previousHash)
                    throw new InvalidDataException("Shutdown save metadata mismatch");
                Log(new { kind = "background_saved", run_id = _runId, seq = _seq,
                    game_id = _gameId, turn = game.Turns, save_sha256 = savedHash });
                Modals.SuspendAnswers();
                _bridge.Suspend();
                if (!_bridge.DrainSuspended(6000))
                    throw new TimeoutException("Save completed but suspension delivery was not acknowledged");
                // Match the engine's save-and-exit path; otherwise RunGame builds a death score
                // and can delete the just-written save as a permadeath character.
                game.DeathReason = "<nodeath>";
                game.DeathCategory = "exit";
                game.forceNoDeath = true;
                _quitRequested = true;
                game.Running = false;
                return true;
            }
            if (command == "probe_modal" && _state == 2 && _development && _fatal == null)
            {
                DevelopmentProbe.Run((string)control["case"], _runId, _seq);
                return false;
            }
            if (command == "probe_lifecycle" && _state == 2 && _development && _fatal == null)
            {
                Type probe = null;
                foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
                {
                    Type candidate = assembly.GetType("LlmOfQud.ProbeR6.Probe", false);
                    if (candidate == null) continue;
                    if (probe != null) throw new InvalidOperationException("Multiple R6 probe assemblies");
                    probe = candidate;
                }
                if (probe == null) throw new InvalidOperationException("R6 development probe is not loaded");
                return (bool)probe.GetMethod("RunFixture", BindingFlags.Public | BindingFlags.Static).Invoke(null, new object[] { control });
            }
            if (command == "handoff" && _state != 0)
            {
                Log(new { kind = "handoff", intervention = "I4", run_id = _runId, seq = _seq });
                AutoAct.Interrupt();
                Modals.SetContext(_runId, _seq, false);
                _bridge.Dispose(); _bridge = null; _state = 0; _startup = null;
                if (_audit != null) { _audit.Dispose(); _audit = null; }
                The.ActionManager.SkipPlayerTurn = false;
                return true;
            }
            if (command != "arm" || _state != 0 || The.Player == null || The.Player.CurrentCell == null)
                throw new InvalidOperationException("arm requires an inactive bridge and live player");
            Arm(control);
            return false;
        }

        private static void Arm(JObject control)
        {
            if (_state != 0 || The.Player == null || The.Player.CurrentCell == null)
                throw new InvalidOperationException("arm requires an inactive bridge and live player");
            // Before any run state, audit file or socket: a mismatch leaves the bridge inactive.
            if (!SurfaceMatches("arm")) throw new InvalidOperationException("arm refused: reflection surface mismatch");
            _runId = (string)control["run_id"] ?? Guid.NewGuid().ToString();
            Guid parsed;
            if (!Guid.TryParse(_runId, out parsed)) throw new ArgumentException("run_id must be UUID");
            _seq = 0; _ctas = 0; _travelCtas = 0; _endTurns = _playerTurns = _uiTasks = _unknownTasks = 0;
            _strayKeys = 0;
            if (_audit != null) { _audit.Dispose(); _audit = null; }
            // Open the private audit before arming so an IO failure leaves the bridge inactive.
            bool audit = control["audit"] != null && (bool)control["audit"];
            _development = control["development"] != null && (bool)control["development"];
            if (audit) _audit = new ObservationAudit(_runId);
            _pending = null; _macro = null; _fatal = null;
            _gameId = The.Game.GameID; _lastWorldTurn = The.Game.Turns;
            _controlledGame = The.Game; _checkpointLoad = null;
            Digest.Clear();
            The.Game.RequireSystem<TurnSystem>();
            Keyboard.ClearInput();
            _state = 1;
            if (audit)
            {
                if (control["r9_fixture"] != null && (bool)control["r9_fixture"])
                {
                    try { _audit.Fixture = ObservationAudit.ApplyFixture(The.Player); }
                    catch (Exception ex) { _audit.Fixture = new JObject { ["error"] = ex.ToString() }; }
                }
                Log(new { kind = "r9_audit_armed", run_id = _runId, fixture = _audit.Fixture != null });
            }
            if (_bridge == null) _bridge = new Bridge(_runId, Modals.EnqueueAnswer);
            Log(new { kind = "armed", run_id = _runId, development = _development });
        }

        private static void UiTick()
        {
            try
            {
                if (_state != 0 || _startup != null)
                {
                    if (!_backgroundCaptured) { _previousBackground = UnityEngine.Application.runInBackground; _backgroundCaptured = true; }
                    UnityEngine.Application.runInBackground = true;
                    if (_startup != null && _fatal == null) _startup.Tick();
                    if (_quitRequested && GameManager.Instance.CurrentGameView == "MainMenu")
                    {
                        _quitRequested = false;
                        Log(new { kind = "background_quit", run_id = _runId, seq = _seq });
                        _bridge.Dispose();
                        GameManager.Instance.Quit();
                        return;
                    }
                    SuspendIfEnded();
                    Modals.Tick();
                }
                else if (_backgroundCaptured)
                {
                    UnityEngine.Application.runInBackground = _previousBackground;
                    GameManager._focused = UnityEngine.Application.isFocused;
                    _backgroundCaptured = false;
                    Modals.Tick();
                }
            }
            catch (Exception ex)
            {
                Log(new { kind = "ui_error", error = ex.ToString() });
                if (_startup != null && _state == 0)
                {
                    _fatal = "background_start:" + ex.GetType().Name;
                    _bridge.Dispose();
                    GameManager.Instance.Quit();
                }
            }
            finally { GameManager.Instance.uiQueue.queueTask(UiTick); }
        }

        private static void AfterRender(XRLCore core, ScreenBuffer buffer)
        {
            if (!_mapRequested || Thread.CurrentThread != XRLCore.CoreThread) return;
            if (buffer.Width != 80 || buffer.Height != 25) throw new InvalidOperationException("Expected 80x25 render");
            var rows = new string[25];
            for (int y = 0; y < 25; y++)
            {
                var chars = new char[80];
                for (int x = 0; x < 80; x++)
                {
                    var cell = buffer[x, y];
                    chars[x] = cell == null ? ' ' : ActionPolicy.Glyph(cell.Char, cell.BackupChar);
                }
                rows[y] = new string(chars);
            }
            _map = rows; _mapFrame++; _mapRequested = false;
            if (_audit != null) _audit.CountRender();
        }

        private static HashSet<GameObject> VisibleHostiles()
        {
            var result = new HashSet<GameObject>();
            foreach (var obj in ObservationBuilder.VisibleCreatures(The.Player)) if (obj.IsHostileTowards(The.Player)) result.Add(obj);
            return result;
        }

        private static JObject Observe()
        {
            return ObservationBuilder.Build(The.Player, Digest.Snapshot(), _map, _mapFrame, ItemHandles);
        }

        private static JArray RecordQueue()
        {
            if (QueueField == null || ActionField == null) throw new MissingFieldException("gameQueue fields unavailable");
            var queue = QueueField.GetValue(GameManager.Instance.gameQueue) as Queue<ThreadTaskQueueEntry>;
            if (queue == null) throw new InvalidOperationException("gameQueue is unavailable");
            var result = new JArray();
            lock (queue)
            {
                foreach (var entry in queue)
                {
                    var action = ActionField.GetValue(entry) as Delegate;
                    Type type = action == null ? null : action.Method.DeclaringType;
                    while (type != null && type.DeclaringType != null) type = type.DeclaringType;
                    string name = type == null ? "" : type.FullName;
                    string classification = name.StartsWith("Qud.UI.", StringComparison.Ordinal) ? "ui_task" :
                        name == "XRL.World.Conversations.Parts.EndGame" ? "engine_task" : "unknown";
                    if (classification == "ui_task") _uiTasks++;
                    if (classification == "unknown") _unknownTasks++;
                    result.Add(new JObject { ["task_id"] = entry.TaskID, ["type"] = name,
                        ["method"] = action == null ? "" : action.Method.Name, ["classification"] = classification });
                }
            }
            return result;
        }

        private static JObject Telemetry(JArray queue)
        {
            return new JObject { ["cta"] = _ctas, ["end_player_turns"] = _endTurns,
                ["player_turn_entries"] = _playerTurns, ["game_queue"] = queue,
                ["ui_tasks"] = _uiTasks, ["unknown_tasks"] = _unknownTasks, ["travel_ctas"] = _travelCtas,
                ["stray_keys"] = _strayKeys };
        }

        // Keyboard.PushKey uses this same lock. Count before clearing; never treat an
        // old run without this sensor as evidence of zero stray input. Mouse-originated
        // gameQueue tasks remain recorded separately by RecordQueue.
        private static void DrainStrayKeys()
        {
            int count;
            lock (Keyboard.KeyQueue)
            {
                count = Keyboard.KeyQueue.Count;
                Keyboard.KeyQueue.Clear();
            }
            if (count == 0) return;
            _strayKeys += count;
            Log(new { kind = "stray_input", run_id = _runId, seq = _seq, keys = count, total = _strayKeys });
        }

        private static void PreTurn()
        {
            // Fixed 2.0.211.56 XRLCore.PlayerTurn:692-733, before its input loop.
            XRLCore.CallBeginPlayerTurnCallbacks();
            Sidebar.SidebarTick++;
            The.Game.Player.Messages.BeginPlayerTurn();
            if (!The.Player.HasEffect<Confused>() && !The.Player.HasEffect<HulkHoney_Tonic>())
            { The.Core.ConfusionLevel = 0; The.Core.FuriousConfusion = 0; }
            var allegiance = The.Player.Brain == null ? null : The.Player.Brain.Allegiance;
            if (allegiance != null && allegiance.Count == 0) allegiance["Player"] = 100;
            Sidebar.UpdateState();
        }

        private static void Execute(JObject decision)
        {
            _pending = decision; _turnBefore = The.Game.Turns;
            _energyBefore = The.Player.Energy.Value;
            _steps = 0; _executed = false;
            string action = (string)decision["action"], dir = (string)decision["dir"];
            int? targetX = (int?)decision["target"]?["x"], targetY = (int?)decision["target"]?["y"];
            string until = (string)decision["until"];
            _reason = ActionPolicy.Validate(action, dir, (int)decision["budget"], targetX, targetY, until,
                (string)decision["item"], (string)decision["skill"], (string)decision["attribute"]);
            if (_reason != null) { _energyAfter = _energyBefore; return; }
            bool macro = action == "explore" || action == "goto" || action == "rest";
            if (macro)
            {
                if (The.Player.CurrentZone.IsWorldMap()) { _reason = "world_map"; _energyAfter = _energyBefore; return; }
                var cell = The.Player.CurrentCell;
                _knownHostiles = VisibleHostiles();
                if ((action != "rest" && The.Player.hitpoints * 4 <= The.Player.baseHitpoints) || _knownHostiles.Count > 0)
                { _reason = "unsafe_" + action; _energyAfter = _energyBefore; return; }
                if (action == "goto" && !cell.ParentZone.GetCell(targetX.Value, targetY.Value).IsExplored())
                { _reason = "unexplored_target"; _energyAfter = _energyBefore; return; }
                if (action == "goto" && cell.X == targetX && cell.Y == targetY)
                { _reason = "ARRIVED"; _energyAfter = _energyBefore; return; }
                string setting = action == "explore" ? "?" : action == "goto" ?
                    "M" + targetX.Value + "," + targetY.Value : until == "morning" ? "z" : "r";
                if (action == "rest" && AutoAct.ShouldHostilesInterrupt(setting, null, logSpot: false, popSpot: true))
                { _reason = "unsafe_rest"; _energyAfter = _energyBefore; return; }
                _lastX = cell.X; _lastY = cell.Y;
                _macroZone = cell.ParentZone.ZoneID;
                _macroEffects = ObservationBuilder.MacroEffects(The.Player);
                _macro = new MacroGuard(The.Game.Turns, (int)decision["budget"], cell.X, cell.Y,
                    action, targetX ?? -1, targetY ?? -1, The.Player.hitpoints);
                The.Player.CurrentZone.FlushNavigationCaches();
                AutoAct.ClearAutoMoveStop();
                AutoAct.Setting = setting;
                if (action == "rest")
                {
                    if (setting == "r")
                    {
                        The.ActionManager.RestingUntilHealed = true;
                        The.ActionManager.RestingUntilHealedCount = 0;
                    }
                    SoundManager.PlayUISound("sfx_wait", 0.1f, Combat: false, Interface: true);
                    The.Player.PassTurn();
                }
                _executed = true;
                _reason = "delegated";
            }
            else if (action == "move")
            {
                if (dir == "U" || dir == "D") _executed = VerticalMovement.Move(dir);
                else
                {
                    // A world-map step runs TerrainTravel.HandleLeavingCell synchronously; its
                    // loop re-enters CommandTakeActionEvent before Move returns (see OnCta).
                    Cell start = The.Player.CurrentCell;
                    bool worldMap = start.ParentZone.IsWorldMap();
                    _travelling = worldMap;
                    try { _executed = The.Player.Move(dir); }
                    finally { _travelling = false; }
                    // Lost and encounters move the player into a local zone, then return
                    // false to cancel the original overland destination. That is an action
                    // with a changed location, not a blocked move.
                    Cell end = The.Player.CurrentCell;
                    if (worldMap && end != null && end != start)
                    {
                        _executed = true;
                        if (!end.ParentZone.IsWorldMap())
                            _reason = The.Player.HasEffect<Lost>() ? "lost" : "left_world_map";
                    }
                }
            }
            else if (action == "attack") _executed = The.Player.AttackDirection(dir);
            else if (action == "learn_skill")
                _executed = CharacterGrowth.Learn(The.Player, (string)decision["skill"], out _reason);
            else if (action == "raise_attribute")
                _executed = CharacterGrowth.Raise(The.Player, (string)decision["attribute"], out _reason);
            else if (action == "talk")
            {
                // CmdTalk's conversation API, limited to a visible adjacent speaker in this zone.
                Cell here = The.Player.CurrentCell, cell = here.GetCellFromDirection(dir);
                var speaker = cell == null || cell.ParentZone != here.ParentZone ? null :
                    cell.GetFirstObjectWithPart("ConversationScript", obj => obj != The.Player && obj.IsVisible());
                if (speaker == null) _reason = "no_visible_speaker";
                else _executed = speaker.GetPart<XRL.World.Parts.ConversationScript>().AttemptConversation();
            }
            else if (ActionPolicy.IsItemAction(action))
            {
                GameObject item;
                if (!ItemHandles.TryGetValue((string)decision["item"], out item) || item.IsInvalid() ||
                    (action == "get" ? !ObservationBuilder.CanGet(The.Player, item) :
                     action == "equip" || action == "open" ? item.InInventory != The.Player :
                     item.InInventory != The.Player && item.Equipped != The.Player))
                    _reason = "item_unavailable";
                else if (action == "open" && (!item.HasPart<XRL.World.Parts.Container>() || item.IsCreature))
                    _reason = "item_action_unavailable";
                else
                {
                    string command = action == "get" ? "CommandTakeObject" :
                        action == "eat" ? "Eat" : action == "drink" ? "Drink" :
                        action == "equip" ? "CommandEquipObject" : action == "open" ? "Open" : "Apply";
                    InventoryAction selected = null;
                    int count = 0;
                    var candidates = EquipmentAPI.GetInventoryActions(item, The.Player);
                    if (candidates != null)
                        foreach (var candidate in candidates)
                            if (candidate.Command == command && (action != "equip" || candidate.Name == "DoEquip"))
                            { selected = candidate; count++; }
                    if (count != 1) _reason = count == 0 ? "item_action_unavailable" : "ambiguous_item_action";
                    else
                    {
                        selected.Process(item, The.Player);
                        // Process returns an event even when the engine refuses or the user cancels.
                        // Report dispatch; the resulting observation shows any actual effect.
                        _executed = true;
                        _reason = "dispatched";
                    }
                }
            }
            else
            {
                // CmdWait: XRLCore.cs:1517-1540; PassTurn alone omits these effects.
                int energy = 1000;
                if (The.Player.IsAflame())
                {
                    if (Firefighting.AttemptFirefighting(The.Player, The.Player, 1000, Automatic: true)) energy = 0;
                }
                else if (The.Player.IsFrozen()) The.Player.TemperatureChange(20);
                else The.Player.Physics.Search();
                The.Player.FireEvent("PassedTurn");
                if (energy > 0)
                {
                    SoundManager.PlayUISound("sfx_wait", 0.1f, Combat: false, Interface: true);
                    The.Player.PassTurn();
                }
                _executed = true;
            }
            _energyAfter = The.Player.Energy.Value;
            if (!macro)
            {
                _reason = ActionPolicy.FinalizeReason(_executed, _reason ?? (_executed ? "executed" : "blocked"),
                    _energyBefore, _energyAfter, The.Game.Turns - _turnBefore);
                _steps = _executed ? 1 : 0;
            }
            Log(new { kind = "action", run_id = _runId, seq = _seq, action, executed = _executed,
                reason = _reason, energy_before = _energyBefore, energy_after = _energyAfter });
        }

        public static bool OnCta()
        {
            if (_state == 0) return true;
            // Nested CTA from the finite travel loop of the accepted world-map step: not a
            // decision. Let vanilla travel continue (false aborts it); the outer CTA that
            // follows Execute reports the single result. A fault aborts travel promptly.
            if (_travelling) { _travelCtas++; The.ActionManager.SkipPlayerTurn = true; return _fatal == null; }
            try
            {
                if (_fatal != null) throw new InvalidOperationException(_fatal);
                _state = 2; _ctas++;
                _lastWorldTurn = The.Game.Turns;
                // Only a handoff may enter vanilla PlayerTurn. A lifecycle fixture
                // consumes this CTA even when it ends or replaces the game.
                if (PollControl()) return _state == 0;
                DrainStrayKeys();
                if (_macro != null)
                {
                    var cell = The.Player.CurrentCell;
                    if (cell.X != _lastX || cell.Y != _lastY) _steps++;
                    _lastX = cell.X; _lastY = cell.Y;
                    var hostiles = VisibleHostiles();
                    hostiles.ExceptWith(_knownHostiles);
                    var effects = ObservationBuilder.MacroEffects(The.Player);
                    effects.ExceptWith(_macroEffects);
                    string stop = _macro.Observe(The.Game.Turns, cell.X, cell.Y, The.Player.hitpoints,
                        The.Player.baseHitpoints, AutoAct.IsActive(), hostiles.Count > 0,
                        cell.ParentZone.ZoneID != _macroZone, effects.Count > 0);
                    if (stop == null) { The.ActionManager.SkipPlayerTurn = true; return true; }
                    var publicHostiles = new JArray();
                    foreach (var enemy in hostiles)
                        publicHostiles.Add(new JObject { ["name"] = enemy.GetDisplayName(AsIfKnown: false),
                            ["x"] = enemy.CurrentCell.X, ["y"] = enemy.CurrentCell.Y });
                    Log(new { kind = "macro_stop", run_id = _runId, seq = _seq, reason = stop,
                        utc = DateTime.UtcNow.ToString("o"), turn = The.Game.Turns, x = cell.X, y = cell.Y,
                        hp = The.Player.hitpoints, public_new_hostiles = publicHostiles, public_new_effects = effects });
                    AutoAct.Interrupt(); _macro = null; _reason = stop;
                    _energyAfter = The.Player.Energy.Value;
                }
                PreTurn();
                var queue = RecordQueue();
                long rendersBefore = _audit == null ? 0 : _audit.Renders;
                _mapRequested = true;
                The.Core.RenderBase();
                if (!The.Game.Running || !string.IsNullOrEmpty(The.Game.GetStringGameState("EndType")))
                    throw new InvalidOperationException("Game ended; no further decision requested");
                if (_mapRequested) throw new InvalidOperationException("No fresh AfterRender map");
                JObject observation = Observe(), telemetry = Telemetry(queue);
                string result = null;
                if (_pending != null)
                {
                    _reason = ActionPolicy.FinalizeReason(_executed, _reason, _energyBefore, _energyAfter,
                        The.Game.Turns - _turnBefore);
                    var outcome = new JObject { ["kind"] = "result", ["run_id"] = _runId, ["seq"] = _seq,
                        ["action"] = (string)_pending["action"], ["executed"] = _executed, ["reason"] = _reason,
                        ["observation"] = observation.DeepClone(), ["telemetry"] = telemetry.DeepClone(),
                        ["energy_before"] = _energyBefore, ["energy_after"] = _energyAfter,
                        ["turns_elapsed"] = The.Game.Turns - _turnBefore, ["steps"] = _steps };
                    result = outcome.ToString(Formatting.None);
                    Log(new { kind = "result", run_id = _runId, seq = _seq, executed = _executed,
                        reason = _reason, next_cta = _ctas, end_player_turns = _endTurns, player_turn_entries = _playerTurns });
                    _pending = null;
                }
                _seq++;
                var request = new JObject { ["kind"] = "request", ["run_id"] = _runId, ["seq"] = _seq,
                    ["observation"] = observation, ["telemetry"] = telemetry };
                string requestText = request.ToString(Formatting.None);
                // Private R9 capture at the same CTA, before publishing and without mutating the game.
                if (_audit != null)
                    _audit.Write(new JObject { ["run_id"] = _runId, ["seq"] = _seq, ["cta"] = _ctas,
                        ["result_seq"] = result == null ? null : (JToken)(_seq - 1) }, requestText, rendersBefore);
                Modals.SetContext(_runId, _seq, true);
                _bridge.Publish(_seq, requestText, result);
                Log(new { kind = "request", run_id = _runId, seq = _seq, turn = The.Game.Turns, cta = _ctas });
                while (true)
                {
                    // A fixture (or anything else) may end the game here: suspend before yielding.
                    if (PollControl()) { SuspendIfEnded(); return _state == 0; }
                    if (_fatal != null) throw new InvalidOperationException(_fatal);
                    if (SuspendIfEnded()) return false;
                    var decision = _bridge.WaitDecision();
                    if (decision == null) continue;
                    // Never execute a late decision into a game that stopped running.
                    if (SuspendIfEnded()) return false;
                    DrainStrayKeys(); // also discard keys that arrived while the LLM was deciding
                    Execute(decision);
                    if (_macro != null) { The.ActionManager.SkipPlayerTurn = true; return true; }
                    return false;
                }
            }
            catch (Exception ex)
            {
                _fatal = ex.ToString();
                Modals.SetContext(_runId, _seq, false);
                if (_bridge != null) _bridge.PublishFault("runtime:" + ex.GetType().Name);
                Log(new { kind = "fatal_paused", run_id = _runId, seq = _seq, error = _fatal });
                while (_state != 0)
                {
                    try { if (PollControl()) return true; }
                    catch (Exception controlError) { Log(new { kind = "control_error", error = controlError.GetType().Name }); }
                    Thread.Sleep(100);
                }
                return true;
            }
        }
    }
}
