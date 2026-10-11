using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;

namespace LlmOfQud
{
    internal sealed class BackgroundStart
    {
        internal string RunId, GameId, SaveHash;
        internal string Pregen, RandomGenotype, CharacterName;
        internal bool NewGame { get { return Pregen != null || RandomGenotype != null; } }
        internal long SaveTurn;
        internal bool Audit, Development;

        internal static bool IsEmbarkNotice(string text, bool hasInput, int buttons, string command)
        {
            return text == "You embark for the caves of Qud." && !hasInput && buttons == 1 && command == "Accept";
        }

        internal static BackgroundStart Parse(JObject value)
        {
            if (value == null) throw new ArgumentException("Missing background start");
            var allowed = new HashSet<string> { "run_id", "game_id", "save_sha256", "save_turn", "audit", "development", "new_game" };
            foreach (var property in value.Properties())
                if (!allowed.Contains(property.Name)) throw new ArgumentException("Unknown background start field");
            Guid id;
            if (value["new_game"] != null)
            {
                if (value["run_id"]?.Type != JTokenType.String || !Guid.TryParse((string)value["run_id"], out id))
                    throw new ArgumentException("run_id must be UUID");
                if (value["game_id"] != null || value["save_sha256"] != null || value["save_turn"] != null)
                    throw new ArgumentException("New game cannot carry a save identity");
                var fresh = value["new_game"] as JObject;
                if (fresh == null || fresh.Count != 2) throw new ArgumentException("Invalid new_game");
                string kind = fresh["random_genotype"] != null ? "random_genotype" : "pregen";
                foreach (string key in new[] { kind, "name" })
                    if (fresh[key]?.Type != JTokenType.String || string.IsNullOrWhiteSpace((string)fresh[key]) ||
                        ((string)fresh[key]).Length > 80) throw new ArgumentException("Invalid new_game " + key);
                if (kind == "random_genotype" && (string)fresh[kind] != "Mutated Human")
                    throw new ArgumentException("Unsupported random genotype");
                foreach (string key in new[] { "audit", "development" })
                    if (value[key] != null && value[key].Type != JTokenType.Boolean) throw new ArgumentException("Invalid " + key);
                return new BackgroundStart { RunId = (string)value["run_id"], Pregen = (string)fresh["pregen"],
                    RandomGenotype = (string)fresh["random_genotype"],
                    CharacterName = (string)fresh["name"], Audit = (bool?)value["audit"] ?? false,
                    Development = (bool?)value["development"] ?? false };
            }
            foreach (string key in new[] { "run_id", "game_id" })
                if (value[key]?.Type != JTokenType.String || !Guid.TryParse((string)value[key], out id))
                    throw new ArgumentException(key + " must be UUID");
            string hash = value["save_sha256"]?.Type == JTokenType.String ? (string)value["save_sha256"] : null;
            if (hash == null || hash.Length != 64) throw new ArgumentException("Invalid save hash");
            foreach (char c in hash)
                if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) throw new ArgumentException("Invalid save hash");
            if (value["save_turn"]?.Type != JTokenType.Integer || (long)value["save_turn"] < 0)
                throw new ArgumentException("Invalid save turn");
            foreach (string key in new[] { "audit", "development" })
                if (value[key] != null && value[key].Type != JTokenType.Boolean) throw new ArgumentException("Invalid " + key);
            return new BackgroundStart { RunId = (string)value["run_id"], GameId = (string)value["game_id"],
                SaveHash = hash, SaveTurn = (long)value["save_turn"],
                Audit = (bool?)value["audit"] ?? false, Development = (bool?)value["development"] ?? false };
        }

        internal void ValidateSave(string game, long turn, string hash, IEnumerable<string> savedMods, IEnumerable<string> runningMods)
        {
            if (game != GameId || turn != SaveTurn || hash != SaveHash) throw new ArgumentException("Background save identity changed");
            if (!new HashSet<string>(savedMods ?? Array.Empty<string>()).SetEquals(runningMods ?? Array.Empty<string>()))
                throw new ArgumentException("Background load requires matching mods");
        }

        internal static void ValidateStop(JObject control, string run, long seq, bool idle)
        {
            if (!idle || (string)control["run_id"] != run || control["expect_seq"]?.Type != JTokenType.Integer ||
                (long)control["expect_seq"] != seq) throw new ArgumentException("Stop requires the current idle decision");
        }
    }
}
