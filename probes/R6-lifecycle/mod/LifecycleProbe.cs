using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using ConsoleLib.Console;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Qud.UI;
using XRL;
using XRL.Core;
using XRL.World.Capabilities;

namespace LlmOfQud.ProbeR6
{
    [HasModSensitiveStaticCache, HasCallAfterGameLoaded]
    public static class Probe
    {
        private static readonly object Sync = new object();
        private static readonly string[] Keys = { "begin", "end", "end_single", "passed_ten", "after_render", "message" };
        private static readonly string[] Fields = { "OnBeginPlayerTurnCallbacks", "OnEndPlayerTurnCallbacks", "OnEndPlayerTurnSingleCallbacks",
            "OnPassedTenPlayerTurnCallbacks", "AfterRenderCallbacks", "OnNewMessageLogEntryCallbacks" };
        private static readonly Dictionary<string, string> SaveHashes = new Dictionary<string, string>();
        private static readonly HashSet<string> Fixtures = new HashSet<string>();
        private static readonly HashSet<object> SeenDeathMenus = new HashSet<object>();
        private static string _session, _nonce, _path, _previous = new string('0', 64), _fixtureId, _deathAnswer;
        private static int _n, _epoch, _boundary, _ctaIndex;
        private static bool _uiStarted, _first, _dieSeen;
        private static long _lastHeartbeat;
        private static object[] _lists;
        [ModSensitiveStaticCache] private static bool _sentinel;

        [ModSensitiveCacheInit]
        public static void Init()
        {
            string opt = DataManager.SavePath("r6-dev-optin.json");
            if (!File.Exists(opt)) return;
            JObject config = JObject.Parse(File.ReadAllText(opt));
            string why = R6Policy.ValidateOptIn((int?)config["v"] ?? 0, (bool?)config["development"] ?? false,
                (bool?)config["disposable"] ?? false, (string)config["savepath"], (string)config["nonce"], DataManager.SavePath(""));
            if (why != null) throw new InvalidOperationException(why);
            bool initial = _session == null;
            _nonce = (string)config["nonce"];
            if (initial)
            {
                _session = Guid.NewGuid().ToString();
                string dir = DataManager.SavePath("r6-evidence");
                Directory.CreateDirectory(dir);
                _path = Path.Combine(dir, DateTime.UtcNow.ToString("yyyyMMddTHHmmssfff") + "-" + Process.GetCurrentProcess().Id + "-" + _session + ".jsonl");
            }
            object[] lists = Fields.Select(f => typeof(XRLCore).GetField(f, BindingFlags.Static | BindingFlags.NonPublic).GetValue(null)).ToArray();
            bool replaced = _lists != null && lists.Where((v, i) => !ReferenceEquals(v, _lists[i])).Count() == lists.Length;
            _lists = lists;
            var registration = new JObject();
            Register(0, (Action<XRLCore>)Begin, registration);
            Register(1, (Action<XRLCore>)End, registration);
            Register(4, (Action<XRLCore, ScreenBuffer>)Render, registration);
            Register(5, (Action<string>)Message, registration);
            var frames = Frames();
            _epoch++; _boundary++; _first = true; _ctaIndex = 0;
            var record = Snapshot("init");
            record["reason"] = initial ? "process_start" : "reinit";
            record["pid"] = Process.GetCurrentProcess().Id;
            record["argv"] = new JArray(Environment.GetCommandLineArgs());
            record["savepath"] = DataManager.SavePath(""); record["optin_nonce"] = _nonce;
            record["game_version"] = typeof(XRLCore).Assembly.GetName().Version.ToString();
            record["sentinel_reset"] = !_sentinel; record["lists_replaced"] = initial ? null : (JToken)replaced;
            record["frames"] = new JArray(frames.Select(f => f[0] + "::" + f[1]));
            record["hotload_frame"] = frames.Any(f => R6Policy.IsHotloadFrame(f[0], f[1]));
            record["wish_frame"] = frames.Any(f => R6Policy.IsWishFrame(f[0], f[1]));
            record["registration"] = registration;
            Write(record); _sentinel = true;
            if (!_uiStarted && GameManager.Instance != null)
            {
                _uiStarted = true;
                GameManager.Instance.uiQueue.queueTask(UiTick);
            }
        }

        private static void Register(int index, Delegate callback, JObject result)
        {
            IList list = (IList)_lists[index];
            bool existed = list.Contains(callback);
            while (list.Contains(callback)) list.Remove(callback);
            list.Add(callback); result[Keys[index]] = existed ? "deduplicated" : "added";
        }

        private static List<string[]> Frames()
        {
            var result = new List<string[]>();
            foreach (var frame in new StackTrace(false).GetFrames())
            {
                var method = frame.GetMethod();
                Type type = method.DeclaringType;
                while (type != null && type.DeclaringType != null) type = type.DeclaringType;
                result.Add(new[] { type == null ? "" : type.FullName, method.Name });
            }
            return result;
        }

        private static void Begin(XRLCore core)
        {
            var frames = Frames();
            string source = R6Policy.CtaSource(frames.Select(f => f[0]).ToList(), frames.Select(f => f[1]).ToList());
            var record = Snapshot("cta_begin"); record["source"] = source;
            record["first_after_boundary"] = source == "production_cta" && _first;
            record["index_in_boundary"] = _ctaIndex;
            if (source == "production_cta") { _first = false; _ctaIndex++; }
            Write(record);
            Saves(false);
        }

        private static void End(XRLCore core) { Saves(false); }
        private static void Message(string text)
        {
            if (_session != null) Write(new JObject { ["kind"] = "message", ["text"] = text });
        }
        private static void Render(XRLCore core, ScreenBuffer buffer)
        {
            if (_dieSeen) return;
            var frames = Frames();
            if (!frames.Any(f => R6Policy.IsDieFrame(f[0], f[1]))) return;
            _dieSeen = true;
            var record = Snapshot("die_path"); record["fixture_id"] = _fixtureId;
            record["frames"] = new JArray(frames.Select(f => f[0] + "::" + f[1])); Write(record);
        }

        [CallAfterGameLoaded]
        public static void Loaded()
        {
            if (_session == null) return;
            _boundary++; _first = true; _ctaIndex = 0;
            JObject files = Saves(true);
            var p = files["Primary"]; var c = files["Checkpoint"];
            string basis;
            string selected = R6Policy.ChooseLoadedFile(The.Game.Turns, (long?)p?["json_turn"], (string)p?["sha256"],
                (long?)c?["json_turn"], (string)c?["sha256"], _dieSeen, out basis);
            var record = Snapshot("game_loaded"); record["candidates"] = files;
            record["frames"] = new JArray(Frames().Select(f => f[0] + "::" + f[1]));
            record["loaded_file"] = selected; record["loaded_file_basis"] = basis;
            record["matching_files"] = new JArray(files.Properties().Where(v => (long?)v.Value["json_turn"] == The.Game.Turns).Select(v => v.Name));
            Write(record); _dieSeen = false; _fixtureId = null;
        }

        private static JObject Game()
        {
            var game = The.Game; var player = The.Player; var cell = player == null ? null : player.CurrentCell;
            if (game == null || cell == null) return null;
            return new JObject { ["game_id"] = game.GameID, ["turns"] = game.Turns, ["mode"] = game.gameMode,
                ["running"] = game.Running, ["zone"] = cell.ParentZone.ZoneID, ["x"] = cell.X, ["y"] = cell.Y,
                ["hp"] = player.hitpoints, ["checkpointing"] = CheckpointingSystem.IsCheckpointingEnabled() };
        }

        private static Type ProductionType(string name)
        {
            var types = AppDomain.CurrentDomain.GetAssemblies().Select(a => a.GetType(name, false)).Where(t => t != null).ToList();
            return types.Count == 1 ? types[0] : null;
        }
        private static object Static(Type type, string name)
        {
            return type == null ? null : type.GetField(name, BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public)?.GetValue(null);
        }

        private static JObject Snapshot(string kind)
        {
            Type runtime = ProductionType(R6Policy.ProductionRuntime), bridge = ProductionType(R6Policy.ProductionBridge);
            var pending = Static(runtime, "_pending") as JObject;
            var production = new JObject { ["present"] = runtime != null, ["state"] = JToken.FromObject(Static(runtime, "_state") ?? -1),
                ["run_id"] = (string)Static(runtime, "_runId"), ["seq"] = JToken.FromObject(Static(runtime, "_seq") ?? -1L),
                ["ctas"] = JToken.FromObject(Static(runtime, "_ctas") ?? -1L), ["pending_seq"] = pending?["seq"]?.DeepClone(),
                ["bridge_set"] = Static(runtime, "_bridge") != null, ["fatal"] = Static(runtime, "_fatal") != null };
            object live = bridge?.GetProperty("LiveCount", BindingFlags.Static | BindingFlags.Public)?.GetValue(null, null);
            var manager = The.ActionManager;
            var scheduler = manager == null ? null : new JObject {
                ["energy"] = The.Player?.Energy?.Value,
                ["segment_count"] = JToken.FromObject(Static(typeof(ActionManager), "SegCount") ?? -1),
                ["skip_player_turn"] = manager.SkipPlayerTurn, ["skip_segment"] = manager.SkipSegment,
                ["player_queue_index"] = manager.ActionQueue.IndexOf(The.Player),
                ["sentinel_queue_index"] = manager.ActionQueue.IndexOf(null),
                ["queue_count"] = manager.ActionQueue.Count,
                ["actor_is_player"] = ReferenceEquals(manager.Actor, The.Player) };
            return new JObject { ["kind"] = kind, ["game"] = Game(), ["production"] = production, ["scheduler"] = scheduler,
                ["bridge_live"] = live == null ? null : JToken.FromObject(live), ["callbacks"] = Counts() };
        }

        private static JObject Counts()
        {
            var own = new JObject(); var production = new JObject(); var total = new JObject();
            for (int i = 0; i < Fields.Length; i++)
            {
                var list = (IList)typeof(XRLCore).GetField(Fields[i], BindingFlags.NonPublic | BindingFlags.Static).GetValue(null);
                int a = 0, b = 0;
                foreach (Delegate callback in list)
                {
                    string type = callback.Method.DeclaringType?.FullName;
                    if (type == typeof(Probe).FullName) a++;
                    if (type == R6Policy.ProductionRuntime) b++;
                }
                own[Keys[i]] = a; production[Keys[i]] = b; total[Keys[i]] = list.Count;
            }
            return new JObject { ["own"] = own, ["production"] = production, ["total"] = total, ["error"] = null };
        }

        private static JObject Saves(bool baseline)
        {
            var result = new JObject();
            if (The.Game == null || The.Player == null) return result;
            foreach (string name in new[] { "Primary", "Checkpoint" })
            {
                string path = The.Game.GetCacheDirectory(name + ".sav.gz");
                if (!File.Exists(path)) continue;
                var info = new FileInfo(path);
                string sha;
                using (var stream = File.OpenRead(path)) using (var hash = SHA256.Create()) sha = R6Policy.Hex(hash.ComputeHash(stream));
                string meta = The.Game.GetCacheDirectory(name + ".json");
                long? turn = File.Exists(meta) ? (long?)JObject.Parse(File.ReadAllText(meta))["Turn"] : null;
                var entry = new JObject { ["sha256"] = sha, ["size"] = info.Length,
                    ["mtime_utc"] = info.LastWriteTimeUtc.ToString("o"), ["json_turn"] = turn };
                result[name] = entry;
                string key = The.Game.GameID + ":" + name;
                string prior;
                if (!SaveHashes.TryGetValue(key, out prior) || prior != sha)
                {
                    // A baseline discovered at load is identified as such; it cannot attest a prior save.
                    var record = (JObject)entry.DeepClone(); record["kind"] = "save_observed";
                    record["game_id"] = The.Game.GameID; record["file"] = name; record["baseline"] = baseline;
                    Write(record); SaveHashes[key] = sha;
                }
            }
            return result;
        }

        private static void UiTick()
        {
            try
            {
                long now = Stopwatch.GetTimestamp();
                if (now - _lastHeartbeat >= Stopwatch.Frequency)
                {
                    _lastHeartbeat = now;
                    var record = Snapshot("heartbeat"); record["view"] = GameManager.Instance.CurrentGameView; Write(record);
                }
                foreach (var window in UIManager.instance.windowsByName.Values)
                {
                    var popup = window as PopupMessage;
                    if (popup == null || popup.onHide == null || !popup.gameObject.activeSelf || popup.controller?.menuData == null) continue;
                    var items = popup.controller.menuData;
                    var labels = items.Select(i => R6Policy.CleanLabel(i.text)).ToList();
                    int index = R6Policy.DeathMenuReloadIndex(labels, popup.Title?.text,
                        popup.inputBox != null && popup.inputBox.gameObject.activeSelf);
                    if (index < 0 || !SeenDeathMenus.Add(popup.onHide)) continue;
                    Write(new JObject { ["kind"] = "death_menu_seen", ["fixture_id"] = _fixtureId,
                        ["labels"] = new JArray(labels), ["reload_index"] = index });
                    if (_deathAnswer == "probe_label")
                    {
                        object token = popup.onHide;
                        popup.OnActivateCommand(items[index]);
                        if (!ReferenceEquals(token, popup.onHide)) Write(new JObject { ["kind"] = "death_menu_answered",
                            ["fixture_id"] = _fixtureId, ["label"] = R6Policy.ReloadLabel, ["index"] = index });
                    }
                }
            }
            catch (Exception ex) { MetricsManager.LogException("R6 observer", ex); }
            finally { GameManager.Instance.uiQueue.queueTask(UiTick); }
        }

        // Invoked only by the production runtime's development-only local control entry point.
        // Return true when the current CTA must yield to an engine lifecycle command.
        public static bool RunFixture(JObject control)
        {
            string id = (string)control["fixture_id"], kind = (string)control["fixture"], answer = (string)control["death_answer"] ?? "external";
            string why = R6Policy.ValidateFixture((string)control["nonce"], _nonce, id, kind, answer, Fixtures);
            if (why != null) throw new InvalidOperationException(why);
            if (The.Player == null || The.Player.CurrentCell == null) throw new InvalidOperationException("Live player required");
            if (kind == "death" && (!CheckpointingSystem.IsCheckpointingEnabled() || !File.Exists(The.Game.GetCacheDirectory("Checkpoint.sav.gz"))))
                throw new InvalidOperationException("Roleplay checkpoint required for disposable death fixture");
            Fixtures.Add(id); _fixtureId = id; _deathAnswer = answer;
            Write(new JObject { ["kind"] = "fixture_accepted", ["fixture_id"] = id, ["fixture"] = kind, ["source"] = "local_operator" });
            var begin = Snapshot("fixture_begin"); begin["fixture_id"] = id; begin["fixture"] = kind; Write(begin);
            try
            {
                if (kind == "reload") Wishing.HandleWish(The.Player, "reload");
                else if (kind == "death") { _dieSeen = false; The.Player.Die(Reason: "R6 disposable development fixture", Force: true, AlwaysUsePopups: true); }
                else if (kind == "save" || kind == "save_quit" || kind == "autosave")
                {
                    // Explicit fixture save; never label this as a zone-triggered automatic save.
                    if (kind == "save_quit") XRL.World.ZoneManager.instance.CheckCached(AllowFreeze: true, ForceFreeze: true);
                    // Desktop synchronous success returns null (XRLGame.cs:2381); asynchronous platforms return a task.
                    var save = The.Game.SaveGame("Primary");
                    if (save != null) save.GetAwaiter().GetResult();
                    Saves(false);
                    if (kind == "save_quit")
                    {
                        // Match XRLCore's Save and Quit after saving. Running=false alone
                        // enters BuildScore and deletes the save as a permanent death.
                        The.Game.DeathReason = "<nodeath>";
                        The.Game.DeathCategory = "exit";
                        The.Game.forceNoDeath = true;
                        The.Game.Running = false;
                    }
                }
                Write(new JObject { ["kind"] = "fixture_done", ["fixture_id"] = id, ["fixture"] = kind });
                return kind == "death" || kind == "save_quit";
            }
            catch (Exception ex)
            {
                Write(new JObject { ["kind"] = "fixture_error", ["fixture_id"] = id, ["fixture"] = kind, ["error"] = ex.ToString() });
                throw;
            }
        }

        private static void Write(JObject record)
        {
            if (_path == null) return;
            lock (Sync)
            {
                record["v"] = 1; record["session"] = _session; record["n"] = _n; record["prev"] = _previous;
                record["utc"] = DateTime.UtcNow.ToString("o"); record["thread"] = System.Threading.Thread.CurrentThread.ManagedThreadId.ToString();
                record["epoch"] = _epoch; record["boundary"] = _boundary;
                byte[] raw = Encoding.UTF8.GetBytes(record.ToString(Formatting.None));
                using (var stream = new FileStream(_path, FileMode.Append, FileAccess.Write, FileShare.Read))
                { stream.Write(raw, 0, raw.Length); stream.WriteByte(10); stream.Flush(true); }
                using (var hash = SHA256.Create()) _previous = R6Policy.Hex(hash.ComputeHash(raw));
                _n++;
            }
        }
    }
}
