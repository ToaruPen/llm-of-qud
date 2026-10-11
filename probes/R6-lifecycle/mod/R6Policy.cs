using System;
using System.Collections.Generic;
using System.Text;

namespace LlmOfQud.ProbeR6
{
    // Pure decisions of the R6 probe. No game types, so tests/Program.cs runs them without the game.
    public static class R6Policy
    {
        public const string ReloadLabel = "Reload from checkpoint";
        public static readonly string[] DeathLabels = { "Reload from checkpoint", "View final messages", "Retire character", "Quit to main menu" };
        public static readonly string[] FixtureKinds = { "status", "save", "autosave", "save_quit", "reload", "death" };
        public static readonly string[] DeathAnswers = { "probe_label", "external" };
        public const string ProductionRuntime = "LlmOfQud.Runtime";
        public const string ProductionBridge = "LlmOfQud.Bridge";
        public const string ProductionTurnSystem = "LlmOfQud.TurnSystem";

        // ---------------- labels (same rules as the production ModalPolicy, copied to stay standalone)
        public static string Strip(string s)
        {
            if (s == null) return "";
            StringBuilder sb = new StringBuilder(s.Length);
            int i = 0;
            while (i < s.Length)
            {
                char c = s[i];
                if (c == '{' && i + 1 < s.Length && s[i + 1] == '{')
                {
                    int bar = s.IndexOf('|', i + 2);
                    int close = s.IndexOf("}}", i + 2, StringComparison.Ordinal);
                    if (bar > 0 && (close < 0 || bar < close)) { i = bar + 1; continue; }
                    i += 2;
                    continue;
                }
                if (c == '}' && i + 1 < s.Length && s[i + 1] == '}') { i += 2; continue; }
                if ((c == '&' || c == '^') && i + 1 < s.Length)
                {
                    if (s[i + 1] == c) sb.Append(c);
                    i += 2;
                    continue;
                }
                sb.Append(c);
                i++;
            }
            return sb.ToString().Trim();
        }

        public static string Collapse(string s)
        {
            if (s == null) return "";
            StringBuilder sb = new StringBuilder(s.Length);
            bool space = false;
            foreach (char c in s)
            {
                if (char.IsWhiteSpace(c)) { space = true; continue; }
                if (space && sb.Length > 0) sb.Append(' ');
                space = false;
                sb.Append(c);
            }
            return sb.ToString();
        }

        // PickOption hotkeys render as "[a] label" (Popup.cs:2041).
        public static string CleanLabel(string s)
        {
            string t = Collapse(Strip(s));
            if (t.Length >= 4 && t[0] == '[')
            {
                int close = t.IndexOf(']');
                if (close > 1 && close <= 3 && close + 1 < t.Length && t[close + 1] == ' ') t = t.Substring(close + 2).TrimStart();
            }
            return t;
        }

        // Roleplay death menu (CheckpointingSystem.cs:111-114): exactly the four labels in either order,
        // empty title, no input box. Returns the index of "Reload from checkpoint", or -1.
        public static int DeathMenuReloadIndex(IList<string> labels, string title, bool hasInput)
        {
            if (labels == null || labels.Count != 4 || hasInput || Collapse(Strip(title)).Length != 0) return -1;
            bool[] seen = new bool[4];
            int reload = -1;
            for (int i = 0; i < 4; i++)
            {
                int k = Array.IndexOf(DeathLabels, CleanLabel(labels[i]));
                if (k < 0 || seen[k]) return -1;
                seen[k] = true;
                if (k == 0) reload = i;
            }
            return reload;
        }

        // ---------------- opt-in and control
        public static string NormalizePath(string path)
        {
            if (string.IsNullOrEmpty(path)) return "";
            string t = path.TrimEnd('/', '\\');
            return t.Length == 0 ? path.Substring(0, 1) : t;
        }

        public static bool IsNonce(string s)
        {
            if (s == null || s.Length < 32 || s.Length > 64) return false;
            foreach (char c in s) if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || c == '-')) return false;
            return true;
        }

        public static bool IsUuid(string s)
        {
            Guid parsed;
            return s != null && s.Length == 36 && Guid.TryParse(s, out parsed);
        }

        // The opt-in file lives in the profile and names that same profile, so a copied file does not
        // enable the probe elsewhere.
        public static string ValidateOptIn(int version, bool development, bool disposable, string savepath, string nonce, string actualSavePath)
        {
            if (version != 1) return "opt-in version must be 1";
            if (!development) return "opt-in lacks development:true";
            if (!disposable) return "opt-in lacks disposable:true";
            if (!IsNonce(nonce)) return "opt-in nonce is not 32-64 lowercase hex characters";
            if (string.IsNullOrEmpty(savepath) || NormalizePath(savepath) != NormalizePath(actualSavePath))
                return "opt-in savepath differs from the running profile";
            return null;
        }

        public static string ValidateFixture(string nonce, string expectedNonce, string fixtureId, string kind, string deathAnswer, ICollection<string> seen)
        {
            if (expectedNonce == null || nonce != expectedNonce) return "nonce does not match the profile opt-in";
            if (!IsUuid(fixtureId)) return "fixture_id must be a UUID";
            if (seen != null && seen.Contains(fixtureId)) return "fixture_id was already used";
            if (Array.IndexOf(FixtureKinds, kind) < 0) return "unknown fixture";
            if (Array.IndexOf(DeathAnswers, deathAnswer) < 0) return "death_answer must be probe_label or external";
            return null;
        }

        // ---------------- stack classification (frames innermost first; outer declaring type names)
        public static string CtaSource(IList<string> outerTypes, IList<string> methods)
        {
            bool actionManager = false;
            for (int i = 0; i < outerTypes.Count; i++)
            {
                string t = outerTypes[i] ?? "";
                if (t.StartsWith("LlmOfQud.ProbeR6.", StringComparison.Ordinal)) continue;
                if (t == ProductionRuntime) return "production_cta";
                if (t == "XRL.Core.XRLCore" && methods[i] == "PlayerTurn") return "player_turn";
                if (t == "XRL.Core.ActionManager") actionManager = true;
            }
            return actionManager ? "autoact_step" : "other";
        }

        public static bool IsHotloadFrame(string outerType, string method) { return outerType == "XRL.Core.XRLCore" && method == "HotloadConfiguration"; }
        // The reload wish runs HotloadConfiguration in a lambda declared in Wishing (Wishing.cs:1006-1013),
        // queued with uiQueue.awaitTask, so on the UI thread the lambda is the Wishing frame.
        public static bool IsWishFrame(string outerType, string method) { return outerType == "XRL.World.Capabilities.Wishing"; }
        public static bool IsDieFrame(string outerType, string method) { return outerType == "XRL.World.GameObject" && method == "Die"; }

        // ---------------- loaded-file identity
        // XRLGame.LoadGame does not keep its path; SaveGame writes the same Turns into <name>.json
        // (XRLGame.cs:2239-2243, 2337-2340). A checkpoint restore copies Checkpoint to Primary only after
        // CallAfterGameLoaded (XRLGame.cs:1954, CheckpointingSystem.cs:61-71), so both are hashed at the hook.
        public static string ChooseLoadedFile(long turns, long? primaryTurn, string primarySha, long? checkpointTurn, string checkpointSha, bool deathContext, out string basis)
        {
            bool p = primaryTurn.HasValue && primaryTurn.Value == turns;
            bool c = checkpointTurn.HasValue && checkpointTurn.Value == turns;
            if (p && !c) { basis = "json_turn_unique"; return "Primary"; }
            if (c && !p) { basis = "json_turn_unique"; return "Checkpoint"; }
            if (p && c)
            {
                basis = primarySha != null && primarySha == checkpointSha ? "json_turn_tie_identical_hash" : "json_turn_tie_different_hash";
                return deathContext ? "Checkpoint" : "Primary";
            }
            basis = "no_json_turn_match";
            return null;
        }

        public static string Hex(byte[] bytes)
        {
            StringBuilder sb = new StringBuilder(bytes.Length * 2);
            foreach (byte b in bytes) sb.Append(b.ToString("x2"));
            return sb.ToString();
        }
    }
}
