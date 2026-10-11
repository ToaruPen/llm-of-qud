// Local operator fixtures for testing the production bridge; never exposed by MCP.
using System;
using System.Collections.Generic;
using System.Threading;
using Newtonsoft.Json.Linq;
using XRL;
using XRL.UI;
using XRL.World;

namespace LlmOfQud
{
    internal static class DevelopmentProbe
    {
        internal static void Run(string name, string runId, long seq)
        {
            long before = The.Game.Turns;
            int energy = The.Player.Energy.Value;
            Runtime.Log(new { kind = "development_probe_start", run_id = runId, seq, name,
                turn = before, energy, llm_gameplay = false });
            object actual = null, expected = null;
            bool ok = false;
            bool cancel = name != null && name.EndsWith("_cancel", StringComparison.Ordinal);
            try
            {
                switch (name)
                {
                    case "stray_key":
                        actual = OnUi(() => {
                            int beforeCount, afterCount;
                            lock (ConsoleLib.Console.Keyboard.KeyQueue)
                                beforeCount = ConsoleLib.Console.Keyboard.KeyQueue.Count;
                            ConsoleLib.Console.Keyboard.PushKey(UnityEngine.KeyCode.Keypad6);
                            lock (ConsoleLib.Console.Keyboard.KeyQueue)
                                afterCount = ConsoleLib.Console.Keyboard.KeyQueue.Count;
                            return new JObject { ["queue_before"] = beforeCount, ["queue_after"] = afterCount };
                        });
                        expected = "empty queue receives exactly one key";
                        ok = (int)((JObject)actual)["queue_before"] == 0 && (int)((JObject)actual)["queue_after"] == 1;
                        break;
                    case "goals_visibility":
                        actual = GoalsVisibility(); expected = "all checks true"; ok = true;
                        foreach (var check in ((JObject)actual).Properties()) ok &= (bool)check.Value;
                        break;
                    case "notice":
                        Popup.Show("[Modal integration] Acknowledge this notice.");
                        actual = expected = "returned"; ok = true; break;
                    case "yesno":
                        expected = "No";
                        actual = Popup.ShowYesNo("[Modal integration] Choose No.").ToString();
                        ok = (string)actual == (string)expected; break;
                    case "option":
                        expected = 2;
                        actual = Popup.PickOption(Title: "[Modal integration] Options", Intro: "Choose gamma.",
                            Options: new List<string> { "alpha", "beta", "gamma", "delta" }, AllowEscape: true);
                        ok = (int)actual == 2; break;
                    case "string":
                        // Popup.NewPopupMessageAsync converts submitted Unicode to the game's CP437 representation.
                        expected = Sidebar.ToCP437("名は café 🌿");
                        actual = Popup.AskString("[Modal integration] Enter: 名は café 🌿", Default: "", MaxLength: 200);
                        ok = Equals(actual, expected); break;
                    case "required":
                        expected = "ENTOMB";
                        actual = Popup.AskString("[Modal integration] Enter ENTOMB.", Default: "", WantsSpecificPrompt: "ENTOMB", MaxLength: 7);
                        ok = Equals(actual, expected); break;
                    case "number_keyboard":
                    case "number_controller":
                    case "number_controller_cancel":
                        expected = cancel ? null : (object)7; actual = Number(name == "number_keyboard");
                        ok = Equals(actual, expected); break;
                    case "direction":
                    case "direction_cancel":
                        expected = cancel ? null : "E"; actual = PickDirection.ShowPicker("[Modal integration] Choose east or cancel as requested.");
                        ok = Equals(actual, expected); break;
                    case "cell":
                    case "cell_cancel":
                    {
                        Cell c = The.Player.CurrentCell;
                        int x = c.X < 79 ? c.X + 1 : c.X - 1;
                        expected = cancel ? null : new JObject { ["x"] = x, ["y"] = c.Y };
                        Cell got = PickTarget.ShowPicker(PickTarget.PickStyle.EmptyCell, 0, 9999, c.X, c.Y,
                            Locked: false, VisLevel: AllowVis.Any, Label: "[Modal integration] Choose adjacent east cell.", UseTarget: false);
                        actual = got == null ? null : new JObject { ["x"] = got.X, ["y"] = got.Y };
                        ok = cancel ? got == null : got != null && got.X == x && got.Y == c.Y; break;
                    }
                    case "field":
                    case "field_cancel":
                    {
                        Cell c = The.Player.CurrentCell;
                        int x = c.X < 79 ? c.X + 1 : c.X - 1;
                        expected = cancel ? null : new JArray(new JObject { ["x"] = c.X, ["y"] = c.Y }, new JObject { ["x"] = x, ["y"] = c.Y });
                        List<Cell> got = PickTarget.ShowFieldPicker(3, 1, c.X, c.Y, What: "Wall", StartAdjacent: false, ReturnNullForAbort: true);
                        var cells = new JArray();
                        if (got != null) foreach (Cell item in got) cells.Add(new JObject { ["x"] = item.X, ["y"] = item.Y });
                        actual = got == null ? null : cells;
                        ok = JToken.DeepEquals((JToken)actual, (JToken)expected); break;
                    }
                    case "item":
                    case "item_cancel":
                    {
                        var items = new List<GameObject>(The.Player.Inventory.GetObjects());
                        if (items.Count < 2) throw new InvalidOperationException("Need two inventory items");
                        var target = items[items.Count - 1];
                        var got = PickItem.ShowPicker(items, Title: "[Modal integration] Choose the last item.", PreserveOrder: true);
                        expected = cancel ? null : target.GetDisplayName(AsIfKnown: false);
                        actual = got == null ? null : got.GetDisplayName(AsIfKnown: false);
                        ok = cancel ? got == null : ReferenceEquals(got, target); break;
                    }
                    case "book":
                        BookUI.ShowBook("[Modal integration] Read and close this book.", "[Modal integration] Book");
                        actual = expected = "returned"; ok = true; break;
                    case "status":
                        Screens.ShowPopup("Factions", The.Player);
                        actual = expected = "returned"; ok = true; break;
                    default: throw new ArgumentException("Unknown development probe: " + name);
                }
                Runtime.Log(new { kind = "development_probe_result", run_id = runId, seq, name, ok,
                    actual, expected, turn_before = before, turn_after = The.Game.Turns,
                    energy_before = energy, energy_after = The.Player.Energy.Value });
            }
            catch (Exception ex)
            {
                Runtime.Log(new { kind = "development_probe_result", run_id = runId, seq, name, ok = false, error = ex.ToString() });
            }
        }

        private static JObject GoalsVisibility()
        {
            string id = "llm-goals-probe-" + Guid.NewGuid();
            string doneId = id + "-done";
            var active = new Quest { ID = id, Name = "VISIBLE_GOAL_PROBE",
                QuestGiverName = "Visible giver", QuestGiverLocationName = "Visible place",
                StepsByID = new Dictionary<string, QuestStep> {
                    { "visible", new QuestStep { Name = "VISIBLE_STEP_PROBE", Text = "Visible instructions", Ordinal = 1 } },
                    { "hidden", new QuestStep { Name = "HIDDEN_STEP_PROBE", Text = "HIDDEN_BODY_PROBE", Hidden = true, Ordinal = 2 } },
                    { "collapsed", new QuestStep { Name = "FINISHED_STEP_PROBE", Text = "COLLAPSED_BODY_PROBE", Finished = true, Collapse = true, Ordinal = 3 } } } };
            var finished = new Quest { ID = doneId, Name = "FINISHED_GOAL_PROBE", Finished = true,
                StepsByID = new Dictionary<string, QuestStep>() };
            try
            {
                The.Game.Quests.Add(id, active); The.Game.Quests.Add(doneId, finished);
                var goals = ObservationBuilder.Goals();
                string text = (string)goals["text"];
                var checks = new JObject {
                    ["visible_text"] = !(bool)goals["truncated"] && text.Contains("VISIBLE_GOAL_PROBE") &&
                        text.Contains("VISIBLE_STEP_PROBE") && text.Contains("Visible instructions"),
                    ["visible_giver"] = text.Contains("Visible giver / Visible place"),
                    ["hidden_steps_excluded"] = !text.Contains("HIDDEN_STEP_PROBE") && !text.Contains("HIDDEN_BODY_PROBE"),
                    ["finished_quest_excluded"] = !text.Contains("FINISHED_GOAL_PROBE"),
                    ["collapsed_body_excluded"] = text.Contains("FINISHED_STEP_PROBE") && !text.Contains("COLLAPSED_BODY_PROBE") };
                active.StepsByID["visible"].Text = new string('x', 17000);
                var longGoals = ObservationBuilder.Goals();
                checks["truncation_marked"] = (bool)longGoals["truncated"] && ((string)longGoals["text"]).Length <= 16384;
                return checks;
            }
            finally { The.Game.Quests.Remove(id); The.Game.Quests.Remove(doneId); }
        }

        private static T OnUi<T>(Func<T> action)
        {
            T result = default(T);
            Exception error = null;
            using (var done = new ManualResetEventSlim())
            {
                // Wait for completion: abandoning this task could apply an override after restoration.
                GameManager.Instance.uiQueue.queueTask(() =>
                {
                    try { result = action(); } catch (Exception ex) { error = ex; }
                    finally { done.Set(); }
                });
                done.Wait();
            }
            if (error != null) throw error;
            return result;
        }

        private static int? Number(bool keyboard)
        {
            var previous = OnUi(() =>
            {
                var prior = ControlManager._activeControllerType;
                ControlManager._activeControllerType = keyboard ? ControlManager.InputDeviceType.Keyboard : ControlManager.InputDeviceType.Gamepad;
                return prior;
            });
            try { return Popup.AskNumber("[Modal integration] Enter 7.", Start: 3, Min: 0, Max: 10); }
            finally { OnUi(() => ControlManager._activeControllerType = previous); }
        }
    }
}
