using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using Newtonsoft.Json.Linq;

namespace LlmOfQud.ProbeR7
{
    // Pure, game-free command validation. The only input is the operator's local
    // r7-command.json; nothing here is reachable from the MCP bridge.
    public sealed class R7Command
    {
        public string Id, Case, Branch, SaveSha256, Fixture, Stat, Blueprint, Node, BodyPart, NoteId;
        public int Dx, Dy;
        public string UnsupportedReason;
    }

    public static class R7Policy
    {
        public static readonly string[] Cases =
            { "BuyStat", "SelectNode", "EquipObject", "Drink", "Eat", "Apply", "CommandGet", "ThrowWeapon", "CmdWait", "Look" };
        public static readonly string[] PrimaryStats =
            { "Strength", "Agility", "Toughness", "Intelligence", "Willpower", "Ego" };

        // Must match verify_r7.py CASES / UNSUPPORTED_UI.
        public static string DirectPath(string c)
        {
            switch (c)
            {
                case "BuyStat": return "StatusScreen.BuyStat";
                case "SelectNode": return "SkillsAndPowersScreen.SelectNode";
                case "EquipObject": return "GameObject.EquipObject+CheckStacks";
                case "Drink": case "Eat": case "Apply": case "Look": return "InventoryAction.Process:" + c;
                case "CommandGet": return "FireEvent:CommandGet+TargetCell";
                case "ThrowWeapon": return "Combat.ThrowWeapon+TargetCell";
                case "CmdWait": return "Shim:CmdWait(XRLCore.cs:1517-1540)";
            }
            return null;
        }

        public static string UiPath(string c)
        {
            switch (c)
            {
                case "BuyStat": return "CharacterStatusScreen.HandleSelectPrimaryAttribute";
                case "SelectNode": return "SkillsAndPowersLine.Accept";
                case "EquipObject": return "InventoryAndEquipmentStatusScreen.HandleDragDrop";
                case "Drink": return "InventoryAndEquipmentStatusScreen.HandleQuickDrink";
                case "Eat": return "InventoryAndEquipmentStatusScreen.HandleQuickEat";
                case "Apply": return "InventoryAndEquipmentStatusScreen.HandleQuickApply";
                case "CommandGet": return "Keyboard.PushCommand:CmdGet";
                case "ThrowWeapon": return "Keyboard.PushCommand:CmdThrow+FireMissileWeapon";
                case "CmdWait": return "Keyboard.PushCommand:CmdWait";
                case "Look": return "Keyboard.PushCommand:CmdLook+Looker";
            }
            return null;
        }

        // Command the UI branch pushes for the engine's PlayerTurn to consume; null for screen cases.
        public static string PushCommandFor(string c)
        {
            switch (c)
            {
                case "CmdWait": return "CmdWait";
                case "CommandGet": return "CmdGet";
                case "ThrowWeapon": return "CmdThrow";
                case "Look": return "CmdLook"; // XRLCore.cs:1682-1698 -> Look.ShowLooker
            }
            return null;
        }

        // Status-screen page for Screens.CurrentScreen (Screens.cs:41-80: 0 Skills, 1 Character, 2 Inventory).
        public static int ScreenPage(string c)
        {
            switch (c)
            {
                case "SelectNode": return 0;
                case "BuyStat": return 1;
                case "Drink": case "Eat": case "Apply": case "EquipObject": return 2;
            }
            return -1;
        }

        // No case lacks a UI route any more; kept so a future unsupported case is reported, not run.
        public static string Unsupported(string c) { return null; }

        // The UI drivers only know the Modern screens. On a classic profile the UI branch is recorded as
        // unsupported instead of being driven (Screens.cs:39-85 falls back to the classic IScreen).
        public static string UiUnavailable(string c, string branch, bool modernUi, bool modernCharacterSheet)
        {
            if (branch != "ui") return null;
            if (ScreenPage(c) >= 0 && !(modernUi && modernCharacterSheet))
                return "UI_UNAVAILABLE: " + c + " ui needs Options.ModernUI and Options.ModernCharacterSheet";
            if (c == "Look" && !modernUi)
                return "UI_UNAVAILABLE: Look ui needs Options.ModernUI (looker tooltip onHideAction, Look.cs:331-401)";
            return null;
        }

        // Exact stripped prompt of SkillsAndPowersScreen.cs:212.
        public static string BuyNodePrompt(string name, int cost)
        {
            return "Are you sure you want to buy " + name + " for " + cost + " sp?";
        }

        private static readonly Regex Hex64 = new Regex("^[0-9a-f]{64}$");
        private static readonly Regex Token = new Regex("^[A-Za-z0-9_.-]{1,64}$");
        // Blueprint and body part names may contain single spaces (e.g. "Witchwood Bark", "Right Hand").
        private static readonly Regex SpacedName = new Regex("^[A-Za-z0-9_.-]+( [A-Za-z0-9_.-]+)*$");
        // Journal IDs are only used as a dictionary key; printable ASCII, no edge spaces.
        private static readonly Regex NoteIdPattern = new Regex("^[\\x21-\\x7E]([\\x20-\\x7E]{0,126}[\\x21-\\x7E])?$");

        public static R7Command Parse(string raw)
        {
            JObject o = JObject.Parse(raw);
            foreach (var p in o.Properties())
                if (Array.IndexOf(new[] { "id", "case", "branch", "saveSha256", "fixture", "args" }, p.Name) < 0)
                    throw new ArgumentException("unknown field " + p.Name);
            var cmd = new R7Command
            {
                Id = Require(o, "id"), Case = Require(o, "case"), Branch = Require(o, "branch"),
                SaveSha256 = Require(o, "saveSha256"), Fixture = Require(o, "fixture")
            };
            if (Array.IndexOf(Cases, cmd.Case) < 0) throw new ArgumentException("case not allowed");
            bool setup = cmd.Branch == "setup";
            if (cmd.Branch != "direct" && cmd.Branch != "ui" && !(setup && (cmd.Case == "Look" || cmd.Case == "CmdWait")))
                throw new ArgumentException("branch must be direct or ui (setup only for Look or CmdWait baseline)");
            if (!Hex64.IsMatch(cmd.SaveSha256)) throw new ArgumentException("saveSha256 must be 64 lowercase hex");
            if (!Token.IsMatch(cmd.Id) || !Token.IsMatch(cmd.Fixture)) throw new ArgumentException("id/fixture token invalid");
            JObject args = o["args"] as JObject ?? new JObject();
            var allowed = new List<string>();
            if (cmd.Case == "BuyStat")
            {
                allowed.Add("stat");
                cmd.Stat = (string)args["stat"];
                if (Array.IndexOf(PrimaryStats, cmd.Stat) < 0) throw new ArgumentException("stat must be a primary attribute");
            }
            else if (cmd.Case == "SelectNode")
            {
                allowed.Add("node");
                cmd.Node = (string)args["node"];
                if (cmd.Node == null || !Token.IsMatch(cmd.Node)) throw new ArgumentException("node must be a skill/power class token");
            }
            else if (cmd.Case == "Drink" || cmd.Case == "Eat" || cmd.Case == "Apply" || cmd.Case == "EquipObject")
            {
                allowed.Add("blueprint");
                cmd.Blueprint = (string)args["blueprint"];
                if (!IsSpacedName(cmd.Blueprint)) throw new ArgumentException("blueprint token invalid");
                if (cmd.Case == "EquipObject")
                {
                    allowed.Add("bodyPart");
                    cmd.BodyPart = (string)args["bodyPart"];
                    if (!IsSpacedName(cmd.BodyPart)) throw new ArgumentException("bodyPart token invalid");
                }
            }
            else if (cmd.Case == "ThrowWeapon" || cmd.Case == "Look")
            {
                allowed.Add("dx"); allowed.Add("dy");
                cmd.Dx = (int?)args["dx"] ?? 0; cmd.Dy = (int?)args["dy"] ?? 0;
                if (Math.Abs(cmd.Dx) > 6 || Math.Abs(cmd.Dy) > 6 || (cmd.Dx == 0 && cmd.Dy == 0))
                    throw new ArgumentException("dx/dy must be within 6 and non-zero");
                if (cmd.Case == "Look")
                {
                    allowed.Add("noteId");
                    cmd.NoteId = (string)args["noteId"];
                    // setup without noteId only lists candidates; direct/ui must name the note.
                    if (cmd.NoteId == null ? !setup : !NoteIdPattern.IsMatch(cmd.NoteId))
                        throw new ArgumentException("noteId required (printable ASCII, <=128)");
                }
            }
            foreach (var p in args.Properties())
                if (!allowed.Contains(p.Name)) throw new ArgumentException("arg not allowed: " + p.Name);
            cmd.UnsupportedReason = Unsupported(cmd.Case);
            if (cmd.UnsupportedReason != null && cmd.Branch == "direct")
                cmd.UnsupportedReason = "DIRECT_NOT_RUN: " + cmd.UnsupportedReason;
            return cmd;
        }

        private static bool IsSpacedName(string s) { return s != null && s.Length <= 64 && SpacedName.IsMatch(s); }

        // Only these popups are answered, and only while a branch is active.
        // expected: BuyStat -> the stat name; SelectNode -> BuyNodePrompt(name, cost) resolved at the CTA.
        public static string PopupAnswer(string caseName, string expected, string text, ICollection<string> commands)
        {
            if (text == null) return null;
            bool yesNo = commands.Count == 2 && commands.Contains("Yes") && commands.Contains("No");
            if (caseName == "BuyStat" && yesNo && text.Contains("attribute point to increase " + expected + " by 1")) return "Yes";
            if (caseName == "SelectNode" && yesNo && expected != null && text.Trim() == expected) return "Yes";
            if (commands.Count == 1 && commands.Contains("Accept")) return "Accept";
            return null;
        }

        private static string Require(JObject o, string key)
        {
            string value = (string)o[key];
            if (string.IsNullOrEmpty(value)) throw new ArgumentException(key + " required");
            return value;
        }
    }
}
