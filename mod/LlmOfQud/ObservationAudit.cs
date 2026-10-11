using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using XRL;
using XRL.Rules;
using XRL.World;
using XRL.World.Capabilities;
using XRL.World.Effects;
using XRL.World.Parts;

namespace LlmOfQud
{
    // R9 private operator instrumentation. Enabled only by the local llm-control.json arm
    // payload ({"audit":true}); never reachable from the harness/MCP. All capture runs on the
    // game thread at the CTA boundary, right after the outbound request string is built.
    // The oracle deliberately uses different enumeration paths from ObservationBuilder.
    internal sealed class ObservationAudit : IDisposable
    {
        private readonly StreamWriter _writer;
        private readonly int _logBase;
        private readonly List<string> _modal = new List<string>();
        private long _renders;
        public readonly string Path;
        public JObject Fixture;

        public ObservationAudit(string runId)
        {
            string dir = DataManager.SavePath("llm-r9");
            Directory.CreateDirectory(dir);
            Path = System.IO.Path.Combine(dir, runId + ".jsonl");
            _writer = new StreamWriter(new FileStream(Path, FileMode.CreateNew, FileAccess.Write, FileShare.Read),
                new UTF8Encoding(false));
            _logBase = The.Game.Player.Messages.Messages.Count;
        }

        // AfterRender (game thread) counter, independent of Runtime's map frame counter.
        public void CountRender() { _renders++; }
        public long Renders { get { return _renders; } }

        // Called from the UI thread; only stores a string under a lock.
        public void Modal(string text) { lock (_modal) _modal.Add(text ?? ""); }

        public void Write(JObject header, string request, long rendersBefore)
        {
            var record = new JObject {
                ["kind"] = "r9_audit",
                ["header"] = header,
                ["request_sha256"] = Sha256(request),
                ["request"] = request,
                ["renders_before"] = rendersBefore,
                ["renders_after"] = _renders,
                ["oracle"] = Oracle() };
            if (Fixture != null) { record["fixture"] = Fixture; Fixture = null; }
            _writer.WriteLine(record.ToString(Formatting.None));
            _writer.Flush();
        }

        public static string Sha256(string text)
        {
            using (var sha = SHA256.Create())
            {
                var bytes = sha.ComputeHash(new UTF8Encoding(false).GetBytes(text));
                var sb = new StringBuilder(64);
                foreach (byte b in bytes) sb.Append(b.ToString("x2"));
                return sb.ToString();
            }
        }

        private JObject Oracle()
        {
            var player = The.Player;
            var zone = The.ZoneManager.ActiveZone;
            var playerCell = player.Physics.CurrentCell;
            var hp = player.GetStat("Hitpoints");
            var entities = new JArray();
            for (int y = 0; y < zone.Height; y++)
                for (int x = 0; x < zone.Width; x++)
                {
                    var cell = zone.GetCell(x, y);
                    if (cell == null) continue;
                    foreach (var obj in cell.Objects)
                    {
                        if (obj == player || (obj.Brain == null && !obj.HasPart("Combat"))) continue;
                        var stat = obj.GetStat("Hitpoints");
                        entities.Add(new JObject {
                            ["x"] = x, ["y"] = y, ["visible"] = obj.IsVisible(),
                            ["shown"] = obj.GetDisplayName(AsIfKnown: false),
                            ["true_name"] = obj.GetDisplayName(AsIfKnown: true),
                            ["blueprint"] = obj.Blueprint,
                            ["wound"] = Strings.WoundLevel(obj),
                            ["scanned"] = Scanning.HasScanningFor(player, obj),
                            ["hp"] = stat == null ? null : (JToken)stat.Value,
                            ["max_hp"] = stat == null ? null : (JToken)stat.BaseValue,
                            ["hostile"] = obj.IsHostileTowards(player) });
                    }
                }
            var kit = new JArray();
            foreach (var item in player.GetEquippedObjects())
                kit.Add(OracleItem(item, item.EquippedOn()));
            if (player.Inventory != null)
                foreach (var item in player.Inventory.Objects) kit.Add(OracleItem(item, null));
            var log = The.Game.Player.Messages.Messages;
            var tail = new JArray();
            for (int i = Math.Max(_logBase, log.Count - 12); i < log.Count; i++) tail.Add(log[i]);
            JArray modal;
            lock (_modal) modal = new JArray(_modal.ToArray());
            var effects = new JArray();
            foreach (var effect in player.Effects)
                if (effect != null) effects.Add(new JObject { ["class"] = effect.GetType().Name, ["description"] = effect.GetDescription() });
            return new JObject {
                ["vitals"] = new JObject { ["hp"] = hp.Value, ["max_hp"] = hp.BaseValue,
                    ["x"] = playerCell.X, ["y"] = playerCell.Y, ["zone"] = zone.ZoneID,
                    ["turn"] = The.Game.Turns, ["energy"] = player.Statistics["Energy"].Value },
                ["entities"] = entities, ["kit"] = kit,
                ["digest_log_tail"] = tail, ["digest_log_since_arm"] = log.Count - _logBase, ["modal_notices"] = modal,
                ["effects"] = effects, ["zone_name"] = zone.DisplayName ?? "", ["world_map"] = zone.IsWorldMap(),
                ["lost"] = player.HasEffect<Lost>() };
        }

        private static JObject OracleItem(GameObject item, XRL.World.Anatomy.BodyPart part)
        {
            return new JObject {
                ["shown"] = item.GetDisplayName(AsIfKnown: false),
                ["true_name"] = item.GetDisplayName(AsIfKnown: true),
                ["blueprint"] = item.Blueprint, ["understood"] = item.Understood(),
                ["slot"] = part == null ? null : (JToken)part.Name };
        }

        // One-shot disposable-profile fixture, applied at arm on the game thread.
        public static JObject ApplyFixture(GameObject player)
        {
            var result = new JObject();
            var item = GameObject.Create("Vibro Dagger");
            player.ReceiveObject(item);
            result["item"] = new JObject { ["blueprint"] = item.Blueprint, ["understood"] = item.Understood(),
                ["shown"] = item.GetDisplayName(AsIfKnown: false), ["true_name"] = item.GetDisplayName(AsIfKnown: true) };
            var zone = player.CurrentCell.ParentZone;
            Cell hidden = null;
            for (int y = 0; y < zone.Height && hidden == null; y++)
                for (int x = 0; x < zone.Width; x++)
                {
                    var c = zone.GetCell(x, y);
                    if (c != null && !c.IsVisible() && c.IsEmpty() && c.IsPassable()) { hidden = c; break; }
                }
            if (hidden != null)
            {
                var pig = GameObject.Create("Pig");
                hidden.AddObject(pig);
                result["hidden"] = new JObject { ["x"] = hidden.X, ["y"] = hidden.Y, ["visible"] = pig.IsVisible() };
            }
            foreach (string dir in new[] { "E", "W", "N", "S", "NE", "NW", "SE", "SW" })
            {
                var near = player.CurrentCell.GetCellFromDirection(dir);
                if (near == null || !near.IsEmpty() || !near.IsPassable()) continue;
                var pig = GameObject.Create("Pig");
                near.AddObject(pig);
                result["adjacent"] = new JObject { ["x"] = near.X, ["y"] = near.Y, ["visible"] = pig.IsVisible(),
                    ["scanned"] = Scanning.HasScanningFor(player, pig) };
                break;
            }
            return result;
        }

        public void Dispose() { _writer.Dispose(); }
    }
}
