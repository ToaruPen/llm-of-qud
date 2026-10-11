// Pure tests for ModalPolicy / ModalLedger / ModalTokens (no Unity). Run: dotnet run --project mod/modal-tests
using System;
using System.Collections.Generic;
using LlmOfQud;
using Newtonsoft.Json.Linq;

internal static class Program
{
    private static int _count;
    private static void Check(bool value, string label)
    {
        if (!value) throw new Exception("FAIL: " + label);
        _count++;
    }

    private static JObject Answer(string run, long seq, string token, long id, JObject response)
    {
        return new JObject { ["kind"] = "modal_answer", ["run_id"] = run, ["seq"] = seq, ["token"] = token, ["answer_id"] = id, ["response"] = response };
    }

    private static ModalAnswer P(JObject frame)
    {
        string r;
        ModalAnswer a = ModalPolicy.Parse(frame, out r);
        if (a == null) throw new Exception("parse failed: " + r);
        return a;
    }

    private static ModalSnapshot YesNo()
    {
        ModalSnapshot s = new ModalSnapshot { Type = "popup", Identity = new object(), Text = "Really?" };
        s.ButtonLabels.AddRange(new[] { "{{y|Yes}}", "{{y|No}}" });
        s.ButtonCommands.AddRange(new[] { "Yes", "No" });
        return s;
    }

    private static ModalSnapshot AskString(string text, string wants)
    {
        ModalSnapshot s = new ModalSnapshot { Type = "string", InputKind = "string", HasInput = true, Identity = new object(), Text = text, WantsSpecificPrompt = wants };
        s.ButtonLabels.AddRange(new[] { "Submit", "Cancel" });
        s.ButtonCommands.AddRange(new[] { "keep", "Cancel" });
        return s;
    }

    private static ModalSnapshot DeathMenu(bool checkpoint, bool viewFirst)
    {
        ModalSnapshot s = new ModalSnapshot { Type = "popup", Identity = new object(), Text = "You died.", CheckpointingEnabled = checkpoint };
        string[] labels = viewFirst
            ? new[] { "View final messages", "Reload from checkpoint", "Retire character", "Quit to main menu" }
            : new[] { "Reload from checkpoint", "View final messages", "Retire character", "Quit to main menu" };
        // real PickOption format with hotkeys: "{{W|[a]}} {{y|label}}" (Popup.cs:2041); stripped by the driver first
        for (int i = 0; i < 4; i++) { s.ItemLabels.Add(ModalPolicy.Strip("{{W|[" + (char)('a' + i) + "]}} {{y|" + labels[i] + "}}")); s.ItemCommands.Add("option:" + i); }
        return s;
    }

    public static int Main()
    {

        string choice;
        Check(ModalPolicy.FieldSelectionStarted("{{W|Escape}}-Clear"), "field selection state strips markup");
        Check(!ModalPolicy.FieldSelectionStarted("{{W|Escape}}-Cancel"), "field not started");
        Check(!ModalPolicy.FieldPromptReady("Space-select | unlock (F1)"), "stale cell prompt is not a ready field");
        Check(ModalPolicy.FieldPromptReady("{{W|Escape}}-Cancel"), "initialized field prompt ready");
        Check(!ModalPolicy.ShouldWatchdog("EndGameCredits", "Stage", false, true, false), "ending credits never trigger modal watchdog");
        Check(!ModalPolicy.ShouldWatchdog("EndGameCredits", "Stage", false, true, true), "ending credits exempt while stopped too");
        Check(!ModalPolicy.ShouldWatchdog("GameSummary", "Stage", false, false, false), "summary key wait exempt");
        Check(!ModalPolicy.ShouldWatchdog("Popup", "Stage", true, false, false), "recognized modal can wait for LLM");
        Check(ModalPolicy.ShouldWatchdog("Unrecognized", "Stage", false, false, false), "unknown live view is watched");
        Check(ModalPolicy.ShouldWatchdog("MainMenu", "Stage", false, false, false), "unknown view during active play is watched");
        Check(!ModalPolicy.ShouldWatchdog("MainMenu", "Stage", false, false, true), "stopped game's main menu is not an active-play modal");
        Check(!ModalPolicy.ShouldWatchdog("Unrecognized", "Stage", false, false, true), "no watchdog while answers are suspended");

        // ---------- parse shape ----------
        string reason;
        Check(ModalPolicy.Parse(Answer("r", 1, "t", 1, new JObject { ["choice"] = "button:0", ["text"] = "x" }), out reason) == null && reason == "response_must_have_one_key", "two response keys rejected");
        Check(ModalPolicy.Parse(Answer("r", 1, "t", 1, new JObject { ["number"] = "7" }), out reason) == null, "number must be int");
        Check(ModalPolicy.Parse(Answer("r", 1, "t", 1, new JObject { ["direction"] = "UP" }), out reason) == null, "direction must be compass");
        Check(ModalPolicy.Parse(Answer("r", 1, "t", 1, new JObject { ["cancel"] = false }), out reason) == null, "cancel must be true");
        Check(ModalPolicy.Parse(Answer("r", 1, "t", 1, new JObject { ["command"] = "CmdWish" }), out reason) == null && reason == "unknown_response", "engine command rejected");
        Check(ModalPolicy.Parse(Answer("r", 1, "t", 1, new JObject { ["target"] = new JObject { ["x"] = 90, ["y"] = 3 } }), out reason) == null, "target outside zone");
        Check(ModalPolicy.Parse(Answer("r", 1, "t", 1, new JObject { ["text"] = new string('a', 5000) }), out reason) == null && reason == "frame_too_large", "frame size bounded");
        JArray bigField = new JArray();
        for (int i = 0; i < 41; i++) bigField.Add(new JObject { ["x"] = i % 80, ["y"] = 1 });
        Check(ModalPolicy.Parse(Answer("r", 1, "t", 1, new JObject { ["field"] = bigField }), out reason) == null, "field size bounded");

        // ---------- yes/no popup through the ledger ----------
        ModalTokens tokens = new ModalTokens();
        tokens.Reset("run1");
        ModalLedger ledger = new ModalLedger();
        ledger.SetContext("run1", 5, true);
        ModalSnapshot yn = YesNo();
        bool isNew;
        string tok = tokens.For(yn.Identity, out isNew);
        Check(isNew, "first token new");
        ModalView v = ModalPolicy.Build(yn, tok, 0);
        Check(v.Rule == null, "yes/no goes to LLM (never auto-selected)");
        Check(v.Choices.Count == 2 && v.Choices[0].Id == "button:0" && v.Choices[0].Label == "Yes", "choices from positions, labels stripped");
        JObject dto = v.ToDto();
        Check((string)dto["type"] == "popup" && (string)dto["input_kind"] == "none" && !dto.ToString().Contains("\"Yes\",\n") , "dto shape");
        Check(dto["choices"][0]["id"] != null && dto["choices"][0]["command"] == null, "no engine command in dto");
        ledger.Publish(v);

        Check(ledger.Enqueue(P(Answer("run1", 5, tok, 1, new JObject { ["text"] = "Yes" }))) == "response_type_mismatch", "wrong response type");
        Check(ledger.Enqueue(P(Answer("run1", 5, tok, 2, new JObject { ["choice"] = "button:7" }))) == "unknown_choice", "unknown choice");
        Check(ledger.Enqueue(P(Answer("run1", 5, tok, 3, new JObject { ["choice"] = "Yes" }))) == "unknown_choice", "command string is not an id");
        Check(ledger.Enqueue(P(Answer("run0", 5, tok, 4, new JObject { ["choice"] = "button:1" }))) == "stale_run", "stale run");
        Check(ledger.Enqueue(P(Answer("run1", 4, tok, 5, new JObject { ["choice"] = "button:1" }))) == "stale_seq", "stale seq");
        Check(ledger.Enqueue(P(Answer("run1", 5, "other", 6, new JObject { ["choice"] = "button:1" }))) == "stale_token", "stale token");
        Check(ledger.Enqueue(P(Answer("run1", 5, tok, 7, new JObject { ["cancel"] = true }))) == "no_cancel_button", "no cancel button on yes/no");
        Check(ledger.QueueCount == 0, "rejects never enqueue");
        // valid answer after rejects to the same pending modal
        Check(ledger.Enqueue(P(Answer("run1", 5, tok, 8, new JObject { ["choice"] = "button:1" }))) == null, "valid answer after rejects accepted into queue");
        Check(ledger.Enqueue(P(Answer("run1", 5, tok, 8, new JObject { ["choice"] = "button:1" }))) == "duplicate_answer_id", "duplicate answer id");
        ModalAnswer q = ledger.Dequeue();
        Check(q != null && q.AnswerId == 8, "dequeue");
        Check(ledger.Claim(q, v) == null, "claim on UI thread");
        ModalAnswer second = P(Answer("run1", 5, tok, 9, new JObject { ["choice"] = "button:0" }));
        Check(ledger.Claim(second, v) == "answer_in_flight", "no second claim while in flight");
        // refused by UI -> release -> a later answer can succeed
        ledger.Release(tok);
        Check(ledger.Claim(second, v) == null, "claim after release");
        ledger.Succeed(tok);
        Check(ledger.Enqueue(P(Answer("run1", 5, tok, 10, new JObject { ["choice"] = "button:0" }))) == "already_answered", "at most one success per token");
        Check(ledger.Claim(P(Answer("run1", 5, tok, 11, new JObject { ["choice"] = "button:0" })), v) == "already_answered", "claim after success rejected");

        // stale view object on UI thread
        ModalView other = ModalPolicy.Build(YesNo(), "x", 0);
        Check(ledger.Claim(P(Answer("run1", 5, tok, 12, new JObject { ["choice"] = "button:0" })), other) == "stale_token", "claim against non-published view");

        // ---------- token identity ----------
        string again = tokens.For(yn.Identity, out isNew);
        Check(!isNew && again == tok, "same identity keeps token (harmless redraw)");
        object reopened = new object();
        string t2 = tokens.For(reopened, out isNew);
        Check(isNew && t2 != tok, "close/reopen gets a new token");
        tokens.Reset("run2");
        string t3 = tokens.For(reopened, out isNew);
        Check(isNew && t3.StartsWith("run2-", StringComparison.Ordinal), "run change resets identity");

        // ---------- queue bound ----------
        ModalLedger bounded = new ModalLedger();
        bounded.SetContext("r", 1, true);
        ModalView bv = ModalPolicy.Build(YesNo(), "tb", 0);
        bounded.Publish(bv);
        for (int i = 0; i < ModalPolicy.MaxQueuedAnswers; i++) Check(bounded.Enqueue(P(Answer("r", 1, "tb", 100 + i, new JObject { ["choice"] = "button:0" }))) == null, "fill queue");
        Check(bounded.Enqueue(P(Answer("r", 1, "tb", 200, new JObject { ["choice"] = "button:0" }))) == "queue_full", "queue bounded");
        bounded.SetContext("r", 1, false);
        Check(bounded.QueueCount == 0 && bounded.Published == null, "inactive clears state");
        Check(bounded.Enqueue(P(Answer("r", 1, "tb", 201, new JObject { ["choice"] = "button:0" }))) == "inactive", "inactive rejects");

        // ---------- AskString with required word ----------
        ModalSnapshot inscribe = AskString("Enter an inscription", null);
        ModalView iv = ModalPolicy.Build(inscribe, "ts", 0);
        Check(iv.Rule == null && iv.Choices.Count == 0 && (string)iv.ToDto()["input_kind"] == "string", "askstring for LLM");
        Check(iv.Constraints["restrict_chars"] == null, "askstring does not publish restrict_chars");
        ModalLedger sl = new ModalLedger();
        sl.SetContext("r", 1, true);
        sl.Publish(iv);
        Check(ModalPolicy.Validate(P(Answer("r", 1, "ts", 1, new JObject { ["text"] = "名は café 🌿" })), iv, "r", 1) == null, "Unicode inscription accepted");
        Check(sl.Enqueue(P(Answer("r", 1, "ts", 1, new JObject { ["text"] = "bad\ntext" }))) == "text_contains_control", "control character rejected");
        Check(sl.Enqueue(P(Answer("r", 1, "ts", 2, new JObject { ["text"] = new string('a', ModalPolicy.MaxTextLength + 1) }))) == "text_too_long", "text cap");
        Check(sl.Enqueue(P(Answer("r", 1, "ts", 3, new JObject { ["number"] = 3 }))) == "response_type_mismatch", "number to string");
        Check(sl.Enqueue(P(Answer("r", 1, "ts", 4, new JObject { ["cancel"] = true }))) == null, "askstring cancel allowed");

        ModalSnapshot entomb = AskString("Type ENTOMB to confirm", "ENTOMB");
        ModalView ev = ModalPolicy.Build(entomb, "te", 0);
        Check(ev.Rule == null && (string)ev.Constraints["required_text"] == "ENTOMB", "required text exposed, not auto");
        ModalLedger el = new ModalLedger();
        el.SetContext("r", 1, true);
        el.Publish(ev);
        Check(el.Enqueue(P(Answer("r", 1, "te", 1, new JObject { ["text"] = "entomb" }))) == "required_text_mismatch", "wrong required word");
        Check(el.Enqueue(P(Answer("r", 1, "te", 2, new JObject { ["text"] = "ENTOMB" }))) == null, "right required word after wrong");

        // ---------- numbers ----------
        ModalSnapshot num = new ModalSnapshot { Type = "number", InputKind = "number", Identity = new object(), Min = 0, Max = 10, PopupID = "AskNumberScreen" };
        ModalView nv = ModalPolicy.Build(num, "tn", 0);
        Check((int)nv.Constraints["min"] == 0 && (int)nv.Constraints["max"] == 10, "number range published");
        ModalLedger nl = new ModalLedger();
        nl.SetContext("r", 1, true);
        nl.Publish(nv);
        Check(nl.Enqueue(P(Answer("r", 1, "tn", 1, new JObject { ["number"] = 11 }))) == "above_max", "above max");
        Check(nl.Enqueue(P(Answer("r", 1, "tn", 2, new JObject { ["number"] = -1 }))) == "below_min", "below min");
        Check(nl.Enqueue(P(Answer("r", 1, "tn", 3, new JObject { ["cancel"] = true }))) == null, "asknumberscreen cancel allowed");
        Check(nl.Enqueue(P(Answer("r", 1, "tn", 4, new JObject { ["number"] = 7 }))) == null, "valid number");
        ModalSnapshot kbnum = new ModalSnapshot { Type = "number", InputKind = "number", HasInput = true, Identity = new object(), RestrictChars = "0123456789" };
        kbnum.ButtonLabels.AddRange(new[] { "Submit", "Cancel" });
        kbnum.ButtonCommands.AddRange(new[] { "keep", "Cancel" });
        ModalView kv = ModalPolicy.Build(kbnum, "tk", 0);
        Check(ModalPolicy.Validate(P(Answer("r", 1, "tk", 1, new JObject { ["number"] = -3 })), kv, "r", 1) == "restrict_chars", "restrict chars on negative");
        Check(ModalPolicy.Validate(P(Answer("r", 1, "tk", 1, new JObject { ["cancel"] = true })), kv, "r", 1) == null, "keyboard number cancel");

        // ---------- system rules ----------
        ModalSnapshot wish = AskString("Your wish is my\ncommand!", null);
        Check(ModalPolicy.Rule(wish, out choice) == "wish_cancel" && choice == "button:1", "wish prompt cancelled");
        ModalSnapshot wishMenu = new ModalSnapshot { Type = "popup", Identity = new object(), Title = "{{W|Wish Menu}}" };
        wishMenu.ItemLabels.Add("a"); wishMenu.ItemCommands.Add("option:0");
        wishMenu.ButtonLabels.Add("Cancel"); wishMenu.ButtonCommands.Add("Cancel");
        Check(ModalPolicy.Rule(wishMenu, out choice) == "wish_cancel" && choice == "button:0", "wish menu cancelled");
        ModalSnapshot cross = AskString("Crossing into Brightsheol will retire your character. Are you sure you want to do it? Type\n'CROSS' to confirm.", null);
        Check(ModalPolicy.Rule(cross, out choice) == "destructive_cancel" && choice == "button:1", "CROSS with line break cancelled");
        Check(ModalPolicy.Build(cross, "tc", 0).Rule == "destructive_cancel", "CROSS never published");
        Check(ModalPolicy.Rule(AskString("...", "RETIRE"), out choice) == "destructive_cancel", "RETIRE cancelled");
        Check(ModalPolicy.Rule(AskString("...", "ABANDON"), out choice) == "destructive_cancel", "ABANDON cancelled");
        Check(ModalPolicy.Rule(AskString("...", "QUIT"), out choice) == "destructive_cancel", "QUIT cancelled");
        Check(ModalPolicy.Validate(P(Answer("r", 1, "tc", 1, new JObject { ["text"] = "CROSS" })), ModalPolicy.Build(cross, "tc", 0), "r", 1) == "system_rule_modal", "LLM cannot answer CROSS");

        Check(ModalPolicy.Rule(DeathMenu(true, false), out choice) == "death_reload_checkpoint" && choice == "option:0", "death reload (default order)");
        Check(ModalPolicy.Rule(DeathMenu(true, true), out choice) == "death_reload_checkpoint" && choice == "option:1", "death reload by label, not index");
        Check(ModalPolicy.Rule(DeathMenu(false, false), out choice) == null, "death rule needs checkpointing");
        ModalSnapshot npc = new ModalSnapshot { Type = "conversation", Identity = new object(), Title = "Mehmet", CheckpointingEnabled = true };
        npc.ItemLabels.AddRange(new[] { "Reload from checkpoint, you say?", "View final messages", "Retire character", "Quit to main menu" });
        npc.ItemCommands.AddRange(new[] { "option:0", "option:1", "option:2", "option:3" });
        Check(ModalPolicy.Rule(npc, out choice) == null, "NPC dialogue with similar labels is not the death menu");
        ModalSnapshot npc2 = DeathMenu(true, false);
        npc2.Title = "Mehmet";
        Check(ModalPolicy.Rule(npc2, out choice) == null, "titled menu is not the death menu");

        ModalSnapshot notice = new ModalSnapshot { Type = "popup", Identity = new object(), Text = "You feel better." };
        notice.ButtonLabels.Add("{{y|Continue}}"); notice.ButtonCommands.Add("Accept");
        Check(ModalPolicy.Rule(notice, out choice) == "notice_accept" && choice == "button:0", "single accept notice");
        Check(ModalPolicy.Rule(YesNo(), out choice) == null, "yes/no never a rule");
        Check(ModalPolicy.Rule(new ModalSnapshot { Type = "tutorial" }, out choice) == "tutorial_accept", "tutorial rule");
        Check(ModalPolicy.Rule(new ModalSnapshot { Type = "book" }, out choice) == "screen_cancel", "book cancel rule");
        Check(ModalPolicy.Rule(new ModalSnapshot { Type = "unknown" }, out choice) == null, "unknown never auto");

        // conversation: trade / Look omitted, option prefixes stripped
        ModalSnapshot conv = new ModalSnapshot { Type = "conversation", Identity = new object(), Title = "Mehmet", PopupID = "Conversation:Mehmet" };
        conv.ItemLabels.AddRange(new[] { "{{w|[1]}} Live and drink.\n\n", "{{w|[2]}} Farewell.\n\n" });
        conv.ItemCommands.AddRange(new[] { "option:0", "option:1" });
        conv.ButtonLabels.AddRange(new[] { "Look", "Trade", "Cancel" });
        conv.ButtonCommands.AddRange(new[] { "Look", "trade", "Cancel" });
        ModalView cv = ModalPolicy.Build(conv, "tv", 0);
        Check(cv.Rule == null && cv.Choices.Count == 3, "trade and Look omitted");
        Check(cv.Choices[0].Label == "Live and drink." && cv.Choices[2].Id == "button:2", "labels cleaned, ids positional");
        Check(ModalPolicy.Validate(P(Answer("r", 1, "tv", 1, new JObject { ["choice"] = "button:1" })), cv, "r", 1) == "unknown_choice", "trade not answerable");
        conv.ItemLabels.Insert(1, "Let's trade. [begin trade]");
        conv.ItemCommands.Clear(); conv.ItemCommands.AddRange(new[] { "option:0", "option:1", "option:2" });
        conv.BlockedItems.Add(1);
        ModalView inlineTrade = ModalPolicy.Build(conv, "ti", 0);
        Check(inlineTrade.Choices.Count == 3 && inlineTrade.Choices[1].Id == "option:2", "inline trade hidden without reindexing later choices");
        Check(ModalPolicy.Validate(P(Answer("r", 1, "ti", 1, new JObject { ["choice"] = "option:1" })), inlineTrade, "r", 1) == "unknown_choice", "forged inline trade answer rejected");

        // pickers
        ModalSnapshot dir = new ModalSnapshot { Type = "direction", InputKind = "direction", Identity = new object() };
        ModalView dv = ModalPolicy.Build(dir, "td", 0);
        Check(ModalPolicy.Validate(P(Answer("r", 1, "td", 1, new JObject { ["direction"] = "NE" })), dv, "r", 1) == null, "direction ok");
        Check(ModalPolicy.Validate(P(Answer("r", 1, "td", 1, new JObject { ["target"] = new JObject { ["x"] = 1, ["y"] = 1 } })), dv, "r", 1) == "response_type_mismatch", "target to direction");
        Check(ModalPolicy.Validate(P(Answer("r", 1, "td", 1, new JObject { ["cancel"] = true })), dv, "r", 1) == null, "direction cancel allowed");
        foreach (string type in new[] { "cell", "field", "pick_item" })
        {
            var cancelView = ModalPolicy.Build(new ModalSnapshot { Type = type, InputKind = type == "pick_item" ? "none" : type, Identity = new object() }, "cancel", 0);
            Check(ModalPolicy.Validate(P(Answer("r", 1, "cancel", 1, new JObject { ["cancel"] = true })), cancelView, "r", 1) == null, type + " cancel allowed");
        }
        ModalSnapshot fld = new ModalSnapshot { Type = "field", InputKind = "field", Identity = new object() };
        ModalView fv = ModalPolicy.Build(fld, "tf", 0);
        JArray gap = new JArray(new JObject { ["x"] = 1, ["y"] = 1 }, new JObject { ["x"] = 3, ["y"] = 1 });
        Check(ModalPolicy.Validate(P(Answer("r", 1, "tf", 1, new JObject { ["field"] = gap })), fv, "r", 1) == "field_not_contiguous", "field contiguity");
        JArray rep = new JArray(new JObject { ["x"] = 1, ["y"] = 1 }, new JObject { ["x"] = 2, ["y"] = 1 }, new JObject { ["x"] = 1, ["y"] = 1 });
        Check(ModalPolicy.Validate(P(Answer("r", 1, "tf", 1, new JObject { ["field"] = rep })), fv, "r", 1) == "field_repeats_cell", "field repeat");
        Check(ModalPolicy.DirectionFrom(1, -1) == "NE" && ModalPolicy.DirectionFrom(2, 0) == null, "direction deltas");

        // seq stamped at publish: a later context seq does not strand the pending modal; wipe bumps generation
        ModalLedger sq = new ModalLedger();
        sq.SetContext("r", 3, true);
        ModalView sv = ModalPolicy.Build(YesNo(), "tq", 0);
        sq.Publish(sv);
        Check(sv.Seq == 3, "seq stamped");
        sq.SetContext("r", 4, true);
        Check(sq.Enqueue(P(Answer("r", 4, "tq", 1, new JObject { ["choice"] = "button:0" }))) == "stale_seq", "answer must echo the modal seq");
        Check(sq.Enqueue(P(Answer("r", 3, "tq", 2, new JObject { ["choice"] = "button:0" }))) == null, "modal seq accepted after context advance");
        long g = sq.Generation;
        sq.SetContext("r2", 1, true);
        Check(sq.Generation == g + 1 && sq.Published == null && sq.QueueCount == 0, "run change wipes and bumps generation");

        // plain PickOption format without hotkeys ("{{y|label}}", Popup.cs:2033) also matches
        ModalSnapshot plain = DeathMenu(true, true);
        for (int i = 0; i < 4; i++) plain.ItemLabels[i] = ModalPolicy.CleanLabel(plain.ItemLabels[i]);
        Check(ModalPolicy.Rule(plain, out choice) == "death_reload_checkpoint" && choice == "option:1", "death plain labels");
        Check(ModalPolicy.CleanLabel("[x]y") == "[x]y", "bracket without space kept");

        // every enqueued answer gets a result: queued answers dropped on success / clear / reset
        ModalLedger dl = new ModalLedger();
        dl.SetContext("r", 1, true);
        ModalView dv2 = ModalPolicy.Build(YesNo(), "tdrop", 0);
        dl.Publish(dv2);
        Check(dl.Enqueue(P(Answer("r", 1, "tdrop", 1, new JObject { ["choice"] = "button:0" }))) == null, "q1");
        Check(dl.Enqueue(P(Answer("r", 1, "tdrop", 2, new JObject { ["choice"] = "button:1" }))) == null, "q2");
        ModalAnswer first = dl.Dequeue();
        Check(dl.Claim(first, dv2) == null, "claim q1");
        dl.Succeed("tdrop");
        List<ModalDrop> drops = dl.TakeDropped();
        Check(drops.Count == 1 && drops[0].Answer.AnswerId == 2 && drops[0].Reason == "already_answered", "second answer dropped with reason");
        Check(dl.TakeDropped().Count == 0, "drops drained once");
        ModalView dv3 = ModalPolicy.Build(YesNo(), "tdrop2", 0);
        dl.Publish(dv3);
        Check(dl.Enqueue(P(Answer("r", 1, "tdrop2", 3, new JObject { ["choice"] = "button:1" }))) == null, "q3");
        dl.Unpublish();
        drops = dl.TakeDropped();
        Check(drops.Count == 1 && drops[0].Reason == "modal_cleared", "clear drops queued answer");
        dl.Publish(ModalPolicy.Build(YesNo(), "tdrop3", 0));
        Check(dl.Enqueue(P(Answer("r", 1, "tdrop3", 4, new JObject { ["choice"] = "button:1" }))) == null, "q4");
        dl.SetContext("r", 1, false);
        drops = dl.TakeDropped();
        Check(drops.Count == 1 && drops[0].Reason == "context_reset", "reset drops queued answer");

        // Ended games keep automatic death rules active, but lose all external answers.
        ModalLedger stopped = new ModalLedger();
        stopped.SetContext("r", 1, true);
        ModalView stoppedView = ModalPolicy.Build(YesNo(), "stopped", 0);
        stopped.Publish(stoppedView);
        ModalAnswer queued = P(Answer("r", 1, "stopped", 11, new JObject { ["choice"] = "button:0" }));
        Check(stopped.Enqueue(queued) == null, "answer queued before game exit");
        stopped.SuspendAnswers();
        Check(stopped.QueueCount == 0, "game exit drops queued answers");
        drops = stopped.TakeDropped();
        Check(drops.Count == 1 && drops[0].Reason == "game_not_running", "game exit reports dropped answer");
        Check(stopped.Claim(queued, stoppedView) == "game_not_running", "dequeued late answer cannot claim");
        Check(stopped.Enqueue(P(Answer("r", 1, "stopped", 12, new JObject { ["choice"] = "button:0" }))) == "game_not_running", "late socket answer refused");
        string stoppedRun; long stoppedSeq; bool stillActive;
        stopped.Context(out stoppedRun, out stoppedSeq, out stillActive);
        Check(stillActive && stoppedRun == "r" && stoppedSeq == 1, "automatic rules retain their context");
        stopped.SetContext("r", 1, true);
        Check(stopped.Enqueue(P(Answer("r", 1, "stopped", 13, new JObject { ["choice"] = "button:0" }))) == "game_not_running", "same seq cannot revive answers");
        // Stopped game (save_quit to MainMenu): the watchdog is quiet, the death reload rule still applies.
        Check(stopped.AnswersSuspended, "suspension is visible to the driver");
        Check(!ModalPolicy.ShouldWatchdog("MainMenu", "Stage", false, false, stopped.AnswersSuspended), "suspended ledger silences the MainMenu watchdog");
        Check(ModalPolicy.Build(DeathMenu(true, false), "death", 0).Rule == "death_reload_checkpoint", "death reload rule still applies while stopped");
        stopped.SetContext("r", 2, true);
        Check(!stopped.AnswersSuspended, "a newer seq clears suspension");
        Check(ModalPolicy.ShouldWatchdog("MainMenu", "Stage", false, false, stopped.AnswersSuspended), "resumed play watches unknown views again");
        stopped.Publish(ModalPolicy.Build(YesNo(), "fresh", 0));
        Check(stopped.Enqueue(P(Answer("r", 2, "fresh", 14, new JObject { ["choice"] = "button:0" }))) == null, "fresh post-load context accepts answers");

        // no timeout default: a pending view never produces an answer by itself
        ModalView old = ModalPolicy.Build(YesNo(), "old", 0);
        ModalLedger idle = new ModalLedger();
        idle.SetContext("r", 1, true);
        idle.Publish(old);
        Check(idle.Dequeue() == null && old.Rule == null, "no timeout answer exists");

        BackgroundTests.Run();
        Console.WriteLine("modal tests passed: " + _count);
        return 0;
    }
}
