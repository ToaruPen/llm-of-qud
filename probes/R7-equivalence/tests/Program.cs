using System;
using System.Collections.Generic;
using LlmOfQud.ProbeR7;

int failed = 0;
void Check(string name, bool ok) { Console.WriteLine((ok ? "PASS " : "FAIL ") + name); if (!ok) failed++; }
bool Rejects(string json) { try { R7Policy.Parse(json); return false; } catch (Exception) { return true; } }
string Sha = new string('a', 64);
string Cmd(string c, string b, string args = "{}", string extra = "") =>
    "{\"id\":\"r7-t\",\"case\":\"" + c + "\",\"branch\":\"" + b + "\",\"saveSha256\":\"" + Sha + "\",\"fixture\":\"fx\",\"args\":" + args + extra + "}";

var buy = R7Policy.Parse(Cmd("BuyStat", "ui", "{\"stat\":\"Strength\"}"));
Check("buystat parses", buy.Stat == "Strength" && buy.UnsupportedReason == null);
Check("unknown case rejected", Rejects(Cmd("Wish", "direct")));
Check("bad branch rejected", Rejects(Cmd("CmdWait", "both")));
Check("bad sha rejected", Rejects(Cmd("CmdWait", "direct").Replace(Sha, "xyz")));
Check("unknown top field rejected", Rejects(Cmd("CmdWait", "direct", "{}", ",\"code\":\"x\"")));
Check("non-primary stat rejected", Rejects(Cmd("BuyStat", "direct", "{\"stat\":\"Hitpoints\"}")));
Check("extra arg rejected", Rejects(Cmd("CmdWait", "direct", "{\"stat\":\"Ego\"}")));
Check("blueprint token enforced", Rejects(Cmd("Drink", "ui", "{\"blueprint\":\"a b;c\"}")));
Check("throw range enforced", Rejects(Cmd("ThrowWeapon", "ui", "{\"dx\":9,\"dy\":0}")));
Check("throw zero rejected", Rejects(Cmd("ThrowWeapon", "ui", "{\"dx\":0,\"dy\":0}")));
Check("blueprint with space accepted", R7Policy.Parse(Cmd("Eat", "ui", "{\"blueprint\":\"Witchwood Bark\"}")).Blueprint == "Witchwood Bark");
Check("blueprint double space rejected", Rejects(Cmd("Eat", "ui", "{\"blueprint\":\"a  b\"}")));
Check("blueprint too long rejected", Rejects(Cmd("Eat", "ui", "{\"blueprint\":\"" + new string('a', 65) + "\"}")));
var th = R7Policy.Parse(Cmd("ThrowWeapon", "direct", "{\"dx\":2,\"dy\":-1}"));
Check("throw parses", th.Dx == 2 && th.Dy == -1);
foreach (var c in new[] { "SelectNode", "EquipObject", "Look" })
{
    // Formerly unsupported; now both branches run and neither carries an unsupported reason.
    Check(c + " has ui path", R7Policy.UiPath(c) != null);
    Check(c + " unsupported reason cleared", R7Policy.Unsupported(c) == null);
}
Check("unsupported direct prefixed if reinstated", R7Policy.Parse(Cmd("CmdWait", "direct")).UnsupportedReason == null);
var sn = R7Policy.Parse(Cmd("SelectNode", "ui", "{\"node\":\"Tactics\"}"));
Check("selectnode parses", sn.Node == "Tactics" && sn.UnsupportedReason == null);
Check("selectnode needs node", Rejects(Cmd("SelectNode", "ui")));
Check("selectnode node token", Rejects(Cmd("SelectNode", "ui", "{\"node\":\"Tac tics\"}")));
var eq = R7Policy.Parse(Cmd("EquipObject", "direct", "{\"blueprint\":\"Dagger\",\"bodyPart\":\"Right Hand\"}"));
Check("equip parses", eq.Blueprint == "Dagger" && eq.BodyPart == "Right Hand");
Check("equip needs bodyPart", Rejects(Cmd("EquipObject", "ui", "{\"blueprint\":\"Dagger\"}")));
Check("equip bodyPart token", Rejects(Cmd("EquipObject", "ui", "{\"blueprint\":\"Dagger\",\"bodyPart\":\"a;b\"}")));
var lk = R7Policy.Parse(Cmd("Look", "ui", "{\"dx\":1,\"dy\":0,\"noteId\":\"$note 1\"}"));
Check("look parses", lk.NoteId == "$note 1" && lk.Dx == 1);
Check("look needs noteId", Rejects(Cmd("Look", "direct", "{\"dx\":1,\"dy\":0}")));
Check("look zero offset rejected", Rejects(Cmd("Look", "ui", "{\"dx\":0,\"dy\":0,\"noteId\":\"n\"}")));
Check("look noteId control chars rejected", Rejects(Cmd("Look", "ui", "{\"dx\":1,\"dy\":0,\"noteId\":\"a\\nb\"}")));
Check("look setup without noteId allowed", R7Policy.Parse(Cmd("Look", "setup", "{\"dx\":1,\"dy\":0}")).NoteId == null);
Check("other setup cases rejected", Rejects(Cmd("EquipObject", "setup", "{\"blueprint\":\"Dagger\",\"bodyPart\":\"Hand\"}")));
Check("baseline fixture setup accepted", !Rejects(Cmd("CmdWait", "setup")));
Check("baseline fixture rejects custom args", Rejects(Cmd("CmdWait", "setup", "{\"blueprint\":\"Pig\"}")));
Check("push commands", R7Policy.PushCommandFor("Look") == "CmdLook" && R7Policy.PushCommandFor("ThrowWeapon") == "CmdThrow" &&
    R7Policy.PushCommandFor("SelectNode") == null && R7Policy.PushCommandFor("BuyStat") == null);
Check("screen pages", R7Policy.ScreenPage("SelectNode") == 0 && R7Policy.ScreenPage("BuyStat") == 1 &&
    R7Policy.ScreenPage("EquipObject") == 2 && R7Policy.ScreenPage("Look") == -1);
Check("classic sheet -> screen ui unavailable", R7Policy.UiUnavailable("SelectNode", "ui", true, false).StartsWith("UI_UNAVAILABLE"));
Check("classic ui -> look ui unavailable", R7Policy.UiUnavailable("Look", "ui", false, true).StartsWith("UI_UNAVAILABLE"));
Check("direct never unavailable", R7Policy.UiUnavailable("SelectNode", "direct", false, false) == null);
Check("modern -> available", R7Policy.UiUnavailable("EquipObject", "ui", true, true) == null && R7Policy.UiUnavailable("Look", "ui", true, false) == null);
foreach (var c in R7Policy.Cases) Check(c + " direct path", R7Policy.DirectPath(c) != null);
var yn = new List<string> { "Yes", "No" };
string q = "It will cost 1 attribute point to increase Strength by 1.";
Check("yes only for matching stat", R7Policy.PopupAnswer("BuyStat", "Strength", q, yn) == "Yes");
Check("no yes for other stat", R7Policy.PopupAnswer("BuyStat", "Ego", q, yn) == null);
Check("no yes outside BuyStat", R7Policy.PopupAnswer("Drink", null, "Are you sure you want to drink?", yn) == null);
Check("accept single notice", R7Policy.PopupAnswer("Drink", null, "x", new List<string> { "Accept" }) == "Accept");
Check("no answer to multi", R7Policy.PopupAnswer("Look", null, "x", new List<string> { "Accept", "Story" }) == null);
string prompt = R7Policy.BuyNodePrompt("Tactics", 50);
Check("buy prompt text", prompt == "Are you sure you want to buy Tactics for 50 sp?");
Check("selectnode yes on exact prompt", R7Policy.PopupAnswer("SelectNode", prompt, prompt, yn) == "Yes");
Check("selectnode no yes on other node", R7Policy.PopupAnswer("SelectNode", prompt, R7Policy.BuyNodePrompt("Axe", 50), yn) == null);
Check("selectnode no yes on cost mismatch", R7Policy.PopupAnswer("SelectNode", prompt, R7Policy.BuyNodePrompt("Tactics", 60), yn) == null);
Check("buy prompt not answered in other case", R7Policy.PopupAnswer("EquipObject", prompt, prompt, yn) == null);
Check("selectnode yes-no-cancel not answered", R7Policy.PopupAnswer("SelectNode", prompt,
    "You do not have the skill associated with that power. Would you like to purchase the required skill?", new List<string> { "Yes", "No", "Cancel" }) == null);
Console.WriteLine(failed == 0 ? "ALL PASS" : failed + " FAILED");
return failed == 0 ? 0 : 1;
