using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using ConsoleLib.Console;
using Newtonsoft.Json;
using Qud.API;
using Qud.UI;
using XRL;
using XRL.Core;
using XRL.UI;
using XRL.World;
using XRL.World.Anatomy;
using XRL.World.Parts;

namespace LlmOfQud.ProbeR7
{
    [HasModSensitiveStaticCache]
    public static class Bootstrap
    {
        [ModSensitiveCacheInit]
        public static void Init() { Probe.Init(); }
    }

    [Serializable]
    public sealed class R7System : IPlayerSystem
    {
        public override void RegisterPlayer(GameObject player, IEventRegistrar registrar)
        {
            registrar.Register(SingletonEvent<CommandTakeActionEvent>.ID);
            registrar.Register(SingletonEvent<GetEnergyCostEvent>.ID);
            registrar.Register(SingletonEvent<UseEnergyEvent>.ID);
            base.RegisterPlayer(player, registrar);
        }
        public override bool HandleEvent(CommandTakeActionEvent e) { return Probe.OnCta(); }
        public override bool HandleEvent(GetEnergyCostEvent e) { Probe.EnergyCost(e); return true; }
        public override bool HandleEvent(UseEnergyEvent e) { Probe.EnergyUsed(e); return true; }
    }

    internal sealed class Branch
    {
        public R7Command Cmd;
        public string Phase = "armed"; // armed, push_pending, pushed, screen, done
        public Dictionary<string, object> Before, Load;
        public readonly List<string> Messages = new List<string>();
        public readonly List<object> Popups = new List<object>();
        public readonly List<string> Steps = new List<string>();
        public readonly List<string> Errors = new List<string>();
        public readonly HashSet<object> Answered = new HashSet<object>(RefEq.Instance);
        public readonly Stopwatch Clock = new Stopwatch();
        public int TargetX, TargetY, PickerStep, ScreenPage, ItemCountBefore;
        public bool HandlerInvoked, ExitRequested, DeadlineHit, YesAnswered, AcceptAfterYes;
        public bool LookerClicked, LookerTargetShown, LookerEscaped;
        public bool SkillUiInspected, SkillUiScrolled;
        public long LastActivityMs;
        public GameObject Item;          // inventory item (Drink/Eat/Apply/EquipObject) or Look target on the map
        public List<GameObject> ThrownItems; // retained references for diagnostics only
        public SPNode Node;              // SelectNode (direct only; the ui branch uses the screen's own line)
        public string NodeClass, NodePrompt;
        public BodyPart Part;            // EquipObject
    }

    internal sealed class RefEq : IEqualityComparer<object>
    {
        public static readonly RefEq Instance = new RefEq();
        public new bool Equals(object a, object b) { return ReferenceEquals(a, b); }
        public int GetHashCode(object o) { return System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(o); }
    }

    internal static class Probe
    {
        private static Branch _b;
        private static bool _registered, _uiStarted;
        private static long _lastPoll;
        private const int UiTimeoutMs = 20000;
        private static readonly FieldInfo StatusCompletion =
            typeof(StatusScreensScreen).GetField("menucomplete", BindingFlags.Instance | BindingFlags.NonPublic);

        private static readonly FieldInfo CharacterGo =
            typeof(CharacterStatusScreen).GetField("GO", BindingFlags.Instance | BindingFlags.NonPublic);

        private static void Step(Branch b, string s) { lock (b.Steps) b.Steps.Add(s); }
        private static void Error(Branch b, string s) { lock (b.Errors) b.Errors.Add(s); }
        private static int ErrorCount(Branch b) { lock (b.Errors) return b.Errors.Count; }

        private static void Log(object value) { MetricsManager.LogInfo("[R7] " + JsonConvert.SerializeObject(value)); }

        // Read-only diagnostic records are separate from branch_result. The strict
        // equivalence verdict still compares actual energy deltas without tolerance.
        public static void EnergyCost(GetEnergyCostEvent e)
        {
            Branch b = _b;
            if (b == null || b.Cmd.Case != "ThrowWeapon" || e.Actor != The.Player) return;
            // Other handlers may run later. These are this observer's stage values,
            // not a claim about the final pre-random cost returned by GetFor.
            Log(new { kind = "energy_cost_stage", run = b.Cmd.Id, branch = b.Cmd.Branch,
                phase = b.Phase, type = e.Type, baseAmount = e.BaseAmount, amount = e.Amount,
                percentageReduction = e.PercentageReduction, linearReduction = e.LinearReduction,
                passive = e.Passive });
        }

        public static void EnergyUsed(UseEnergyEvent e)
        {
            Branch b = _b;
            if (b == null || b.Cmd.Case != "ThrowWeapon" || e.Actor != The.Player) return;
            // GameObject.UseEnergy sends this event after randomization and debit.
            Log(new { kind = "energy_used", run = b.Cmd.Id, branch = b.Cmd.Branch,
                phase = b.Phase, type = e.Type, amount = e.Amount, passive = e.Passive,
                energyAfter = e.Actor.Energy.BaseValue });
        }

        public static void Init()
        {
            if (!_registered)
            {
                XRLCore.RegisterOnEndPlayerTurnCallback(OnEndPlayerTurn);
                XRLCore.RegisterNewMessageLogEntryCallback(m =>
                {
                    Branch b = _b;
                    if (b != null && b.Phase != "armed" && b.Phase != "done")
                        lock (b.Messages) b.Messages.Add(ColorUtility.StripFormatting(m));
                });
                _registered = true;
            }
            if (!_uiStarted && GameManager.Instance != null)
            {
                _uiStarted = true;
                GameManager.Instance.uiQueue.queueTask(UiTick);
            }
            Log(new { kind = "init", assembly = typeof(XRLCore).Assembly.GetName().Version.ToString() });
        }

        // ---- entry point: operator-only local file, polled while idle ----
        private static void OnEndPlayerTurn(XRLCore core)
        {
            Branch b = _b;
            if (b == null) { PollControl(); return; }
            if (b.Phase == "armed" || b.Phase == "done") return;
            // Look spends no energy (CmdLook -> CmdNone, XRLCore.cs:1682-1698, 2335-2348): the first EndPlayerTurn after the
            // Looker Escape runs only once ShowLooker has returned, because the game thread was blocked in its loop.
            bool consumed = b.Cmd.Case == "Look" ? b.LookerEscaped : The.Player.Energy.Value < (int)b.Before["energy"];
            if (b.Phase == "pushed" && consumed)
            {
                Step(b, "consumed_by_PlayerTurn energy=" + The.Player.Energy.Value + (b.Cmd.Case == "Look" ? " looker_closed" : ""));
                Finish(b, ErrorCount(b) == 0 ? "executed" : "error", null, true);
            }
            else if ((b.Phase == "pushed" || b.Phase == "push_pending") && (b.DeadlineHit || b.Clock.ElapsedMilliseconds > UiTimeoutMs))
            {
                Error(b, "UI_TIMEOUT phase=" + b.Phase);
                Finish(b, "error", "UI command not consumed", true);
            }
        }

        private static void PollControl()
        {
            if (Stopwatch.GetTimestamp() - _lastPoll < Stopwatch.Frequency / 4) return;
            _lastPoll = Stopwatch.GetTimestamp();
            string path = DataManager.SavePath("r7-command.json");
            if (!File.Exists(path)) return;
            string raw = File.ReadAllText(path);
            File.Delete(path);
            try
            {
                R7Command cmd = R7Policy.Parse(raw);
                if (cmd.Branch == "setup")
                {
                    if (cmd.Case == "CmdWait") BaselineFixtureSetup(cmd);
                    else LookFixtureSetup(cmd);
                    return;
                }
                var b = new Branch { Cmd = cmd };
                if (cmd.UnsupportedReason != null)
                {
                    b.Before = Fingerprint(); b.Load = LoadIdentity();
                    Finish(b, "unsupported", cmd.UnsupportedReason, false);
                    return;
                }
                if (The.Player == null || The.Player.CurrentCell == null) throw new InvalidOperationException("live player required");
                The.Game.RequireSystem<R7System>();
                Keyboard.ClearInput();
                _b = b;
                // Leave the vanilla input loop without spending energy. Registering the
                // CTA system alone does not wake Keyboard.IdleWait (XRLCore.PlayerTurn).
                The.ActionManager.SkipPlayerTurn = true;
                Keyboard.KeyEvent.Set();
                Log(new { kind = "armed", run = cmd.Id, @case = cmd.Case, branch = cmd.Branch });
            }
            catch (Exception ex) { Log(new { kind = "control_error", error = ex.Message }); }
        }

        // ---- game thread: begin the branch at the next CTA ----
        public static bool OnCta()
        {
            Branch b = _b;
            if (b == null || b.Phase != "armed") return true;
            try
            {
                b.Load = LoadIdentity();
                b.Before = Fingerprint();
                b.Clock.Start();
                R7Command c = b.Cmd;
                Cell here = The.Player.CurrentCell;
                if (c.Case == "ThrowWeapon")
                {
                    b.TargetX = here.X + c.Dx; b.TargetY = here.Y + c.Dy;
                    Cell t = here.ParentZone.GetCell(b.TargetX, b.TargetY);
                    if (t == null) return Precondition(b, "target cell outside zone");
                    if (The.Player.GetThrownWeapons().IsNullOrEmpty()) return Precondition(b, "no thrown weapon equipped");
                    b.ThrownItems = The.Player.GetThrownWeapons().ToList();
                }
                if (c.Case == "BuyStat" && The.Player.Stat("AP") < 1) return Precondition(b, "AP<1");
                string unavailable = R7Policy.UiUnavailable(c.Case, c.Branch, Options.ModernUI, Options.ModernCharacterSheet);
                if (unavailable != null) { Finish(b, "unsupported", unavailable, false); return true; }
                if (c.Case == "SelectNode" && !PrepareNode(b)) return true;
                if (c.Case == "Look" && !PrepareLookTarget(b, here)) return true;
                if (c.Blueprint != null)
                {
                    var hits = The.Player.Inventory.GetObjects().Where(o => o.Blueprint == c.Blueprint).ToList();
                    if (hits.Count != 1) return Precondition(b, "inventory blueprint matches=" + hits.Count);
                    b.Item = hits[0];
                    b.ItemCountBefore = b.Item.Count;
                }
                if (c.Case == "EquipObject")
                {
                    var parts = The.Player.Body.GetParts().Where(x => x.Name == c.BodyPart).ToList();
                    if (parts.Count != 1) return Precondition(b, "body part matches=" + parts.Count);
                    // An occupied slot would add an unequip (and its popups) to one route only.
                    if (parts[0].Equipped != null) return Precondition(b, "body part occupied");
                    b.Part = parts[0];
                }
                if (c.Branch == "direct") RunDirect(b, here);
                else StartUi(b);
            }
            catch (Exception ex)
            {
                Error(b, ex.GetType().Name + ": " + ex.Message);
                Finish(b, "error", "exception in CTA", true);
            }
            return true;
        }

        private static bool Precondition(Branch b, string why) { Finish(b, "precondition_failed", why, false); return true; }

        private static void RunDirect(Branch b, Cell here)
        {
            b.Phase = "direct";
            R7Command c = b.Cmd;
            GameObject p = The.Player;
            switch (c.Case)
            {
                case "BuyStat": StatusScreen.BuyStat(p, c.Stat); Step(b, "direct_call BuyStat returned"); break;
                case "CommandGet":
                    Step(b, "direct_call CommandGet returned=" + p.FireEvent(Event.New("CommandGet", "TargetCell", here))); break;
                case "ThrowWeapon":
                    Step(b, "direct_call ThrowWeapon returned=" + Combat.ThrowWeapon(p, null, here.ParentZone.GetCell(b.TargetX, b.TargetY))); break;
                case "CmdWait": WaitShim(p); Step(b, "direct_call CmdWait shim returned"); break;
                case "SelectNode":
                    SkillsAndPowersScreen.SelectNode(b.Node, p); // purchase Yes/No is answered by the UI tick
                    Step(b, "direct_call SelectNode returned owned=" + p.HasPart(b.NodeClass)); break;
                case "EquipObject":
                {
                    // Same arguments the UI reaches via EquipmentAPI.cs:473-499 (Object, BodyPart; not Silent, no EnergyCost),
                    // followed by the CheckStacks the UI runs inside the same dispatch (InventoryAndEquipmentStatusScreen.cs:355-363).
                    bool equipped = p.EquipObject(b.Item, b.Part, Silent: false, EnergyCost: null);
                    int merged = p.CheckStacks();
                    Step(b, "direct_call EquipObject returned=" + equipped + " CheckStacks=" + merged); break;
                }
                default:
                {
                    var actions = EquipmentAPI.GetInventoryActions(b.Item, p);
                    var match = actions.Where(a => a.Command == c.Case).ToList();
                    Step(b, "actions=" + string.Join(",", actions.Select(a => a.Name + ":" + a.Command)));
                    if (match.Count != 1) { Precondition(b, "inventory action matches=" + match.Count); return; }
                    IEvent sent = match[0].Process(b.Item, p);
                    Step(b, "direct_call Process returned event=" + (sent == null ? "null" : sent.GetType().Name));
                    break;
                }
            }
            Finish(b, "executed", null, true);
        }

        // Same body as the production wait shim, which mirrors XRLCore.cs:1517-1540.
        private static void WaitShim(GameObject p)
        {
            int cost = 1000;
            if (p.IsAflame()) { if (XRL.World.Capabilities.Firefighting.AttemptFirefighting(p, p, 1000, Automatic: true)) cost = 0; }
            else if (p.IsFrozen()) p.TemperatureChange(20);
            else p.Physics.Search();
            p.FireEvent("PassedTurn");
            if (cost > 0) p.PassTurn();
        }

        private static void StartUi(Branch b)
        {
            string c = b.Cmd.Case;
            if (R7Policy.PushCommandFor(c) != null) { b.Phase = "push_pending"; return; }
            // Screen-based UI: the game thread blocks in the engine's own status screen until the UI tick exits it.
            b.ScreenPage = R7Policy.ScreenPage(c); // Screens.ShowPopup maps 0 Skills, 1 Character, 2 Inventory
            b.Phase = "screen";
            Screens.CurrentScreen = b.ScreenPage;
            Step(b, "Screens.ShowPopup page=" + b.ScreenPage);
            Screens.ShowPopup("R7", The.Player);
            Step(b, "ShowPopup returned view=" + GameManager.Instance.CurrentGameView);
            if (!b.HandlerInvoked) Error(b, "UI_HANDLER_NOT_INVOKED");
            Finish(b, ErrorCount(b) == 0 ? "executed" : "error", null, true);
        }

        // ---- UI thread tick ----
        private static void UiTick()
        {
            try
            {
                Branch b = _b;
                if (b != null && b.Phase != "armed" && b.Phase != "done")
                {
                    AnswerPopup(b);
                    if (!b.DeadlineHit && b.Clock.ElapsedMilliseconds > UiTimeoutMs) Deadline(b);
                    if (b.DeadlineHit)
                    {
                        // Only the safe close of the owned status screen is retried; nothing else is driven.
                        StatusScreensScreen st = SingletonWindowBase<StatusScreensScreen>.instance;
                        if (b.Phase == "screen" && st != null && GameManager.Instance.CurrentGameView == "StatusScreensScreen") Exit(b, st);
                        return;
                    }
                    if (b.Phase == "push_pending") Push(b);
                    else if (b.Phase == "pushed" && b.Cmd.Case == "ThrowWeapon") Picker(b);
                    else if (b.Phase == "pushed" && b.Cmd.Case == "Look") Looker(b);
                    else if (b.Phase == "screen") ScreenTick(b);
                }
            }
            catch (Exception ex) { Log(new { kind = "ui_error", error = ex.ToString() }); }
            finally { GameManager.Instance.uiQueue.queueTask(UiTick); }
        }

        // Runs on the UI thread, so it also fires while the game thread is blocked in a screen or picker.
        // Unanswered popups are never answered here: the operator quits without saving (README).
        private static void Deadline(Branch b)
        {
            b.DeadlineHit = true;
            Error(b, "UI_DEADLINE phase=" + b.Phase + " view=" + GameManager.Instance.CurrentGameView);
            if (b.Phase == "screen")
            {
                StatusScreensScreen st = SingletonWindowBase<StatusScreensScreen>.instance;
                if (st != null && GameManager.Instance.CurrentGameView == "StatusScreensScreen") Exit(b, st);
            }
            else if (b.Phase == "pushed" && (GameManager.Instance.CurrentGameView == "FireMissileWeapon" || GameManager.Instance.CurrentGameView == "Looker"))
            {
                // R5 PickerEscape / R34 10 s Escape; Look.cs:747-750 also exits the Looker on Escape.
                Keyboard.PushKey(UnityEngine.KeyCode.Escape);
                Step(b, "deadline Escape on " + GameManager.Instance.CurrentGameView);
            }
            Log(new { kind = "deadline", run = b.Cmd.Id, phase = b.Phase });
        }

        private static bool InputIdle()
        {
            GameManager gm = GameManager.Instance;
            return Keyboard.KeyQueue.Count == 0 && !Keyboard.HasMouseEvent() && gm._ActiveGameView == gm.CurrentGameView && !gm.bViewUpdated;
        }

        private static void Push(Branch b)
        {
            if (!InputIdle() || GameManager.Instance.CurrentGameView != Options.StageViewID) return;
            string cmd = R7Policy.PushCommandFor(b.Cmd.Case);
            Keyboard.PushCommand(cmd);
            b.Phase = "pushed";
            Step(b, "Keyboard.PushCommand(" + cmd + ") view=" + GameManager.Instance.CurrentGameView + " frame=" + UnityEngine.Time.frameCount);
        }

        // ThrowWeapon uses MissileWeapon.ShowPicker, not PickTarget. Its first PointerOver
        // clears the initial lock; the second positions the cursor, then CmdFire confirms (:827-837,1080-1091).
        private static void Picker(Branch b)
        {
            GameManager gm = GameManager.Instance;
            if (gm.CurrentGameView != "FireMissileWeapon" ||
                !InputIdle() || !XRLCore.bThreadFocus || b.Clock.ElapsedMilliseconds - b.LastActivityMs < 300) return;
            b.LastActivityMs = b.Clock.ElapsedMilliseconds;
            if (b.PickerStep < 2) Keyboard.PushMouseEvent("PointerOver", b.TargetX, b.TargetY);
            else if (b.PickerStep == 2) Keyboard.PushCommand("CmdFire");
            else return;
            Step(b, "FireMissileWeapon " + (b.PickerStep < 2 ? "PointerOver(" + b.TargetX + "," + b.TargetY + ")" : "CmdFire"));
            b.PickerStep++;
        }

        private static void ScreenTick(Branch b)
        {
            StatusScreensScreen st = SingletonWindowBase<StatusScreensScreen>.instance;
            if (st == null || !st.gameObject.activeInHierarchy || GameManager.Instance.CurrentGameView != "StatusScreensScreen") return;
            var tcs = StatusCompletion == null ? null : StatusCompletion.GetValue(st) as TaskCompletionSource<ScreenReturn>;
            if (tcs == null || tcs.Task.IsCompleted) return;
            long now = b.Clock.ElapsedMilliseconds;
            if (!b.HandlerInvoked)
            {
                if (st.CurrentScreen != b.ScreenPage) { Error(b, "SCREEN_PAGE=" + st.CurrentScreen); Exit(b, st); return; }
                if (b.Cmd.Case == "BuyStat")
                {
                    var screens = st.GetComponentsInChildren<CharacterStatusScreen>(false);
                    if (screens.Length != 1 || CharacterGo == null || CharacterGo.GetValue(screens[0]) != The.Player) return;
                    // Same data type the screen builds (CharacterStatusScreen.cs:214); the handler reads only data.Name (:343-351).
                    var data = new CharacterAttributeLineData { category = CharacterAttributeLineData.Category.primary,
                        go = The.Player, data = The.Player.Statistics[b.Cmd.Stat] };
                    screens[0].HandleSelectPrimaryAttribute(data);
                }
                else if (b.Cmd.Case == "SelectNode")
                {
                    var screens = st.GetComponentsInChildren<SkillsAndPowersStatusScreen>(false);
                    if (!b.SkillUiInspected && now > 1000)
                    {
                        b.SkillUiInspected = true;
                        Log(new { kind = "skills_ui_probe", run = b.Cmd.Id, node = b.NodeClass,
                            screens = screens.Select(screen => new { playerMatches = screen.GO == The.Player,
                                choices = screen.controller.choices.OfType<SkillsAndPowersLineData>().Select(d => NodeClassOf(d.entry)).ToArray(),
                                clones = screen.controller.selectionClones.Select(clone => new {
                                    active = clone != null && clone.gameObject.activeInHierarchy,
                                    control = clone == null || clone.FrameworkControl == null ? null : clone.FrameworkControl.GetType().Name
                                }).ToArray() }).ToArray() });
                    }
                    if (screens.Length != 1 || screens[0].GO != The.Player) return;
                    SkillsAndPowersLine line = FindSkillLine(screens[0], b.NodeClass);
                    if (line == null)
                    {
                        // VisibleWindowScroller materializes only the current viewport. Select the real
                        // choice through the same navigation context used by the screen, then let Update scroll.
                        var choices = screens[0].controller.choices;
                        var indices = Enumerable.Range(0, choices.Count).Where(i =>
                            choices[i] is SkillsAndPowersLineData &&
                            NodeClassOf(((SkillsAndPowersLineData)choices[i]).entry) == b.NodeClass).ToList();
                        if (!b.SkillUiScrolled && indices.Count == 1)
                        {
                            screens[0].controller.scrollContext.SelectIndex(indices[0]);
                            b.SkillUiScrolled = true;
                            Step(b, "SkillsAndPowers scroll SelectIndex=" + indices[0]);
                        }
                        return;
                    }
                    // Make the screen's own line the active one (same call HandleDragDrop uses), then invoke the handler
                    // bound to its "Accept" command (SkillsAndPowersLine.cs:72-81, 143), which reads the live context.data.
                    line.GetNavigationContext().Activate();
                    Step(b, "SkillsAndPowersLine active=" + line.selected + " node=" + b.NodeClass);
                    if (!line.selected) { Error(b, "SKILL_LINE_NOT_ACTIVE"); Exit(b, st); return; }
                    line.Accept();
                }
                else if (b.Cmd.Case == "EquipObject")
                {
                    var screens = st.GetComponentsInChildren<InventoryAndEquipmentStatusScreen>(false);
                    if (screens.Length != 1 || screens[0].GO != The.Player) return;
                    // Live data elements the screen built (UpdateViewFromData), not fabricated ones.
                    var from = screens[0].inventoryController.choices.OfType<InventoryLineData>()
                        .Where(l => !l.category && l.go == b.Item).ToList();
                    var to = screens[0].lines.Where(l => l.bodyPart == b.Part && !l.showCybernetics).ToList();
                    if (from.Count != 1 || to.Count != 1) return;
                    screens[0].HandleDragDrop(from[0], to[0]);
                }
                else
                {
                    var screens = st.GetComponentsInChildren<InventoryAndEquipmentStatusScreen>(false);
                    if (screens.Length != 1 || screens[0].GO != The.Player) return;
                    var line = new InventoryLineData { go = b.Item, category = false };
                    if (b.Cmd.Case == "Drink") screens[0].HandleQuickDrink(line);
                    else if (b.Cmd.Case == "Eat") screens[0].HandleQuickEat(line);
                    else screens[0].HandleQuickApply(line);
                }
                b.HandlerInvoked = true;
                b.LastActivityMs = now;
                Step(b, R7Policy.UiPath(b.Cmd.Case) + " invoked on UI thread page=" + st.CurrentScreen);
                return;
            }
            // Exit only on a positive completion signal; otherwise the UI-tick deadline closes the screen as an error.
            string signal = CompletionSignal(b);
            if (signal != null && now - b.LastActivityMs > 300 && ActivePopup() == null)
            {
                Step(b, "completion_signal " + signal);
                Exit(b, st);
            }
        }

        private static string CompletionSignal(Branch b)
        {
            switch (b.Cmd.Case)
            {
                case "BuyStat": return b.AcceptAfterYes ? "Yes+Accept answered" : null;
                case "SelectNode": return b.YesAnswered && The.Player.HasPart(b.NodeClass) ? "Yes answered+skill part present" : null;
                case "EquipObject":
                    // Blueprint, not reference: a stack may split on equip.
                    return b.Part.Equipped != null && b.Part.Equipped.Blueprint == b.Cmd.Blueprint ? "body part equipped" : null;
                case "Apply":
                    // Tonic.cs:185-201 spends energy only for edible tonics; an injected tonic
                    // completes by consuming its item. Count the blueprint so destroyed/split stacks are safe.
                    if (The.Player.Inventory.GetObjects().Where(o => o.Blueprint == b.Cmd.Blueprint).Sum(o => o.Count) < b.ItemCountBefore)
                        return "inventory item consumed";
                    break;
            }
            return The.Player.Energy.Value < (int)b.Before["energy"] ? "energy spent" : null;
        }

        private static string NodeClassOf(SPNode n)
        {
            return n == null ? null : n.Power != null ? n.Power.Class : n.Skill != null ? n.Skill.Class : null;
        }

        private static SkillsAndPowersLine FindSkillLine(SkillsAndPowersStatusScreen screen, string nodeClass)
        {
            var hits = new List<SkillsAndPowersLine>();
            foreach (var clone in screen.controller.selectionClones)
            {
                var line = clone == null || !clone.gameObject.activeInHierarchy ? null : clone.FrameworkControl as SkillsAndPowersLine;
                var ctx = line == null ? null : line.GetNavigationContext() as SkillsAndPowersLine.Context;
                if (ctx == null || ctx.data == null || ctx.data.entry == null || ctx.data.screen != screen) continue;
                if (NodeClassOf(ctx.data.entry) == nodeClass) hits.Add(line);
            }
            return hits.Count == 1 ? hits[0] : null;
        }

        // Game thread (CTA). Rejects every state in which SelectNode would show a popup other than the purchase
        // Yes/No (SkillsAndPowersScreen.cs:141-227), so a no-op pair cannot be recorded as executed.
        private static bool PrepareNode(Branch b)
        {
            GameObject p = The.Player;
            SkillsAndPowersScreen.BuildNodes(p); // the screen's UpdateData does the same (SkillsAndPowersStatusScreen.cs:333-340)
            var nodes = SkillsAndPowersScreen.Nodes.Where(n => NodeClassOf(n) == b.Cmd.Node).ToList();
            if (nodes.Count != 1) { Precondition(b, "skill node matches=" + nodes.Count); return false; }
            SPNode node = nodes[0];
            string name; int cost; bool initiatory;
            if (node.Power == null) { name = node.Skill.Name; cost = node.Skill.Cost; initiatory = node.Skill.Initiatory; }
            else
            {
                if (!p.HasSkill(node.ParentNode.Skill.Class)) { Precondition(b, "power parent skill not owned"); return false; }
                name = node.Power.Name; cost = node.Power.Cost; initiatory = node.Power.IsSkillInitiatory;
            }
            if (p.HasPart(b.Cmd.Node)) { Precondition(b, "already owned"); return false; }
            if (initiatory) { Precondition(b, "initiatory"); return false; }
            if (p.Stat("SP") < cost) { Precondition(b, "SP<" + cost); return false; }
            b.Node = node; b.NodeClass = b.Cmd.Node; b.NodePrompt = R7Policy.BuyNodePrompt(name, cost);
            return true;
        }

        // Game thread (CTA). The Looker shows the first visible Description object of the cell (Look.cs:466-484, 343-352),
        // so the fixture cell must hold exactly one such object, carrying an unlooked RevealNoteOnLook for noteId.
        private static bool PrepareLookTarget(Branch b, Cell here)
        {
            b.TargetX = here.X + b.Cmd.Dx; b.TargetY = here.Y + b.Cmd.Dy;
            string why = LookTargetProblem(here, b.Cmd.Dx, b.Cmd.Dy, b.Cmd.NoteId, true, out GameObject target);
            if (why != null) { Precondition(b, why); return false; }
            b.Item = target;
            return true;
        }

        private static string LookTargetProblem(Cell here, int dx, int dy, string noteId, bool needPart, out GameObject target)
        {
            target = null;
            if (The.Player.GetTotalConfusion() > 0) return "confused (XRLCore.cs:1683-1693)";
            Cell t = here.ParentZone.GetCell(here.X + dx, here.Y + dy);
            if (t == null) return "target cell outside zone";
            if (t.IsSolid()) return "target cell solid";
            var looks = t.GetObjectsInCell().Where(o => o.HasPart<Description>() && o.IsVisible()).ToList();
            if (looks.Count != 1 || looks[0] == The.Player) return "visible Description objects=" + looks.Count;
            target = looks[0];
            if (target.HasStringProperty("Story")) return "target has Story (second popup button)";
            if (noteId == null || !JournalAPI.HasUnrevealedNote(noteId)) return "note not unrevealed: " + noteId;
            var part = target.GetPart<RevealNoteOnLook>();
            if (needPart && (part == null || part.LookedAt || part.NoteID != noteId)) return "target lacks unlooked RevealNoteOnLook(" + noteId + ")";
            if (!needPart && part != null) return "target already has RevealNoteOnLook";
            return null;
        }

        // Fixed, operator-only disposable fixture. This is never exposed through MCP.
        // Persist preparation once; every measured branch must reload the resulting golden save.
        private static void BaselineFixtureSetup(R7Command cmd)
        {
            GameObject p = The.Player;
            Cell here = p == null ? null : p.CurrentCell;
            if (here == null) throw new InvalidOperationException("live player required");
            if (The.Game.GetIntGameState("R7BaselineFixture") != 0)
                throw new InvalidOperationException("baseline already prepared; restore original save");
            var free = new List<Cell>();
            foreach (string direction in new[] { "E", "W", "N", "S", "NE", "NW", "SE", "SW" })
            {
                Cell cell = here.GetCellFromDirection(direction);
                if (cell != null && cell.IsVisible() && cell.IsEmpty() && !cell.IsSolid() &&
                    !cell.GetObjectsInCell().Any(o => o.HasPart<Description>() && o.IsVisible())) free.Add(cell);
            }
            if (free.Count < 2) throw new InvalidOperationException("two empty visible adjacent cells required");
            var notes = new List<string>();
            foreach (KeyValuePair<string, IBaseJournalEntry> kv in JournalAPI.NotesByID)
                if (kv.Value != null && !kv.Value.Revealed) notes.Add(kv.Key);
            notes.Sort(StringComparer.Ordinal);
            string note = notes.FirstOrDefault();
            if (note == null) throw new InvalidOperationException("unrevealed journal note required");
            BodyPart thrown = p.Body.GetFirstPart("Thrown Weapon");
            BodyPart head = p.Body.GetFirstPart("Head");
            if (thrown == null || thrown.Equipped != null || head == null || head.Equipped != null)
                throw new InvalidOperationException("empty head and thrown weapon slots required");
            string[] items = { "FullWaterskin", "Starapple", "SalveTonic", "Leather Cap", "ThrowingAxe" };
            if (p.Inventory.GetObjects().Any(o => Array.IndexOf(items, o.Blueprint) >= 0))
                throw new InvalidOperationException("fixture inventory already present");
            // Mark before any mutation so a partial failure cannot be silently repeated.
            The.Game.SetIntGameState("R7BaselineFixture", 1);
            p.GetStat("AP").BaseValue = 1;
            p.GetStat("SP").BaseValue = 1000;
            foreach (string blueprint in items)
            {
                GameObject item = GameObject.Create(blueprint);
                item.MakeUnderstood();
                p.Inventory.AddObject(item, Silent: true, NoStack: true);
                if (blueprint == "ThrowingAxe" && !p.EquipObject(item, thrown, Silent: true, EnergyCost: 0))
                    throw new InvalidOperationException("fixture thrown weapon equip failed");
            }
            GameObject pickup = GameObject.Create("Dagger");
            pickup.MakeUnderstood();
            here.AddObject(pickup);
            GameObject look = GameObject.Create("Dagger2");
            look.MakeUnderstood();
            look.AddPart(new RevealNoteOnLook(note));
            free[0].AddObject(look);
            p.Energy.BaseValue = 1000;
            var save = The.Game.SaveGame("Primary");
            if (save != null) save.GetAwaiter().GetResult();
            Log(new { kind = "fixture_setup", run = cmd.Id, status = "applied", mutated = true,
                gameId = The.Game.GameID, saved = "Primary", inventoryBlueprints = items,
                pickupBlueprint = "Dagger", lookBlueprint = "Dagger2", node = "Acrobatics", bodyPart = head.Name,
                look = new { dx = free[0].X - here.X, dy = free[0].Y - here.Y, noteId = note },
                throwing = new { dx = free[1].X - here.X, dy = free[1].Y - here.Y },
                fingerprint = Fingerprint() });
        }

        // Operator-only Look fixture setup. RevealNoteOnLook is in no blueprint of 2.0.211.56
        // (only VillageCoda.cs:458 adds it), so the disposable save gets it here once; the operator then saves the
        // golden copy. Without noteId this only lists unrevealed candidates and changes nothing.
        private static void LookFixtureSetup(R7Command cmd)
        {
            GameObject p = The.Player;
            Cell here = p == null ? null : p.CurrentCell;
            if (here == null) { Log(new { kind = "fixture_setup", run = cmd.Id, status = "rejected", reason = "live player required" }); return; }
            if (cmd.NoteId == null)
            {
                var candidates = new List<string>();
                foreach (KeyValuePair<string, IBaseJournalEntry> kv in JournalAPI.NotesByID)
                    if (kv.Value != null && !kv.Value.Revealed) candidates.Add(kv.Value.GetType().Name + ":" + kv.Key);
                candidates.Sort(StringComparer.Ordinal);
                Log(new { kind = "fixture_setup", run = cmd.Id, status = "candidates", mutated = false,
                          count = candidates.Count, candidates = candidates.Take(60).ToList() });
                return;
            }
            string why = LookTargetProblem(here, cmd.Dx, cmd.Dy, cmd.NoteId, false, out GameObject target);
            if (why != null) { Log(new { kind = "fixture_setup", run = cmd.Id, status = "rejected", reason = why, mutated = false }); return; }
            target.AddPart(new RevealNoteOnLook(cmd.NoteId));
            string noteType = null; // StringMap's indexer/TryGetValue have Span overloads the compile check cannot bind
            foreach (KeyValuePair<string, IBaseJournalEntry> kv in JournalAPI.NotesByID)
                if (kv.Key == cmd.NoteId && kv.Value != null) noteType = kv.Value.GetType().Name;
            Log(new { kind = "fixture_setup", run = cmd.Id, status = "applied", mutated = true, gameId = The.Game.GameID,
                      target = target.Blueprint, cell = here.ParentZone.ZoneID + "@" + (here.X + cmd.Dx) + "," + (here.Y + cmd.Dy),
                      noteId = cmd.NoteId, noteType });
        }

        // Looker driver (UI thread). LeftClick is the event TileAreaHandler.cs:179 pushes for a map click outside the
        // adventure view; the Looker moves its reticle on it (Look.cs:672-684, 679-683). Escape is pressed only after the target's
        // looker tooltip carries its onHideAction (Look.cs:359-400, 393); hiding it queues AfterLookedAt (ModelShark/TooltipTrigger.cs:253-258),
        // which HideTooltips runs on the game thread (Look.cs:903-908, 925-935).
        private static void Looker(Branch b)
        {
            GameManager gm = GameManager.Instance;
            if (gm.CurrentGameView != "Looker" || !XRLCore.bThreadFocus || b.LookerEscaped) return;
            long now = b.Clock.ElapsedMilliseconds;
            if (!b.LookerClicked)
            {
                if (!InputIdle() || now - b.LastActivityMs < 300) return;
                Keyboard.PushMouseEvent("LeftClick", b.TargetX, b.TargetY);
                b.LookerClicked = true; b.LastActivityMs = now;
                Step(b, "Looker LeftClick(" + b.TargetX + "," + b.TargetY + ")");
                return;
            }
            bool shown = Look.lookingAt == b.Item && gm.lookerTooltip != null && gm.lookerTooltip.onHideAction != null;
            if (!shown) return;
            if (!b.LookerTargetShown)
            {
                b.LookerTargetShown = true; b.LastActivityMs = now;
                Step(b, "Looker target tooltip shown");
                return;
            }
            if (!InputIdle() || now - b.LastActivityMs < 300) return;
            Keyboard.PushKey(UnityEngine.KeyCode.Escape);
            b.LookerEscaped = true; b.LastActivityMs = now;
            Step(b, "Looker Escape");
        }

        private static void Exit(Branch b, StatusScreensScreen st)
        {
            if (b.ExitRequested || !st.navigationContext.IsActive()) return;
            b.ExitRequested = true;
            // Exit releases ShowPopup on the game thread. Keep its receipt atomic
            // with that release so Finish cannot snapshot a partial UI trace.
            lock (b.Steps)
            {
                st.Exit(); // R5-F4a recipe
                Step(b, "StatusScreensScreen.Exit");
            }
        }

        private static PopupMessage ActivePopup()
        {
            PopupMessage found = null;
            foreach (var pair in UIManager.instance.windowsByName)
            {
                var pm = pair.Value as PopupMessage;
                if (pm == null || pm.onHide == null || !pm.gameObject.activeSelf) continue;
                if (found != null) return null; // several live popups: do not guess
                found = pm;
            }
            return found;
        }

        private static void AnswerPopup(Branch b)
        {
            PopupMessage pm = ActivePopup();
            if (pm == null || pm.controller == null || pm.commandCallback == null || b.Answered.Contains(pm.onHide)) return;
            if (pm.inputBox != null && pm.inputBox.gameObject.activeSelf) return;
            var items = new List<QudMenuItem>();
            if (pm.controller.menuData != null) items.AddRange(pm.controller.menuData);
            if (pm.controller.bottomContextOptions != null) items.AddRange(pm.controller.bottomContextOptions);
            var commands = items.Select(i => i.command).ToList();
            string text = pm.Message == null ? null : ColorUtility.StripFormatting(pm.Message.text);
            string answer = R7Policy.PopupAnswer(b.Cmd.Case, b.Cmd.Case == "SelectNode" ? b.NodePrompt : b.Cmd.Stat, text, commands);
            if (answer == null)
            {
                bool logged;
                lock (b.Errors) logged = b.Errors.Contains("UNHANDLED_POPUP");
                if (b.Clock.ElapsedMilliseconds - b.LastActivityMs > 5000 && !logged)
                {
                    Error(b, "UNHANDLED_POPUP");
                    Log(new { kind = "unhandled_popup", run = b.Cmd.Id, text, commands });
                }
                return;
            }
            QudMenuItem item = items.First(i => i.command == answer);
            if (item.text == null) return;
            object token = pm.onHide;
            b.Answered.Add(token);
            // Answering can release a synchronous direct call just like Exit.
            lock (b.Popups)
            {
                pm.OnActivateCommand(item);
                b.Popups.Add(new { text, answer, accepted = !ReferenceEquals(token, pm.onHide) });
            }
            if (answer == "Yes") b.YesAnswered = true;
            else if (b.YesAnswered) b.AcceptAfterYes = true;
            b.LastActivityMs = b.Clock.ElapsedMilliseconds;
        }

        // ---- evidence ----
        private static Dictionary<string, object> LoadIdentity()
        {
            return new Dictionary<string, object>
            {
                ["gameId"] = The.Game.GameID,
                ["zoneId"] = The.Player.CurrentZone == null ? null : The.Player.CurrentZone.ZoneID,
                ["turns"] = The.Game.Turns,
                ["randomSeed"] = The.Game.GetIntGameState("RandomSeed"),
                ["nextRandomSeed"] = The.Game.GetIntGameState("NextRandomSeed"),
            };
        }

        private static Dictionary<string, object> Fingerprint()
        {
            GameObject p = The.Player;
            var stats = new SortedDictionary<string, int[]>(StringComparer.Ordinal);
            foreach (var pair in p.Statistics)
                if (pair.Key != "Energy") stats[pair.Key] = new[] { pair.Value.BaseValue, pair.Value.Value, pair.Value.Penalty };
            var inventory = p.Inventory.GetObjects().Select(Describe).OrderBy(s => s, StringComparer.Ordinal).ToList();
            var equipment = new List<string>();
            foreach (BodyPart part in p.Body.GetParts())
                if (part.Equipped != null) equipment.Add(part.Name + ":" + Describe(part.Equipped));
            equipment.Sort(StringComparer.Ordinal);
            var skills = p.PartsList.Where(x => x is XRL.World.Parts.Skill.BaseSkill).Select(x => x.Name)
                .OrderBy(s => s, StringComparer.Ordinal).ToList();
            Cell cell = p.CurrentCell;
            return new Dictionary<string, object>
            {
                ["energy"] = p.Energy.Value,
                ["turns"] = The.Game.Turns,
                ["stats"] = stats,
                ["inventory"] = inventory,
                ["equipment"] = equipment,
                ["skills"] = skills,
                ["position"] = cell.ParentZone.ZoneID + "@" + cell.X + "," + cell.Y,
                ["journal"] = JournalFingerprint(),
                ["askForOneItem"] = Options.AskForOneItem,
                ["confirmDangerousLiquid"] = Options.GetOption("OptionConfirmDangerousLiquid"),
            };
        }

        // Revealed journal entries as "Type:ID" (JournalAPI.cs:165-181 keys TryRevealNote by ID); ID-less revealed
        // accomplishments by text. A list, so the verifier reports added/removed entries.
        private static List<string> JournalFingerprint()
        {
            var revealed = new List<string>();
            foreach (KeyValuePair<string, IBaseJournalEntry> kv in JournalAPI.NotesByID)
                if (kv.Value != null && kv.Value.Revealed) revealed.Add(kv.Value.GetType().Name + ":" + kv.Key);
            foreach (JournalAccomplishment a in JournalAPI.Accomplishments)
                if (a != null && a.Revealed && string.IsNullOrEmpty(a.ID)) revealed.Add("JournalAccomplishment~" + ColorUtility.StripFormatting(a.Text));
            revealed.Sort(StringComparer.Ordinal);
            return revealed;
        }

        private static string Describe(GameObject o)
        {
            var lv = o.GetPart<LiquidVolume>();
            return o.Blueprint + "|x" + o.Count + (lv == null ? "" : "|lv=" + lv.Volume + ":" +
                string.Join(",", lv.ComponentLiquids.OrderBy(k => k.Key, StringComparer.Ordinal).Select(k => k.Key + "=" + k.Value)));
        }

        private static void Finish(Branch b, string status, string reason, bool captureAfter)
        {
            if (b.Phase == "done") return;
            b.Phase = "done";
            Dictionary<string, object> after = null;
            try { if (captureAfter) after = Fingerprint(); }
            catch (Exception ex) { Error(b, "after: " + ex.Message); }
            R7Command c = b.Cmd;
            bool ui = c.Branch == "ui";
            List<string> messages, steps, errors;
            lock (b.Messages) messages = b.Messages.ToList();
            lock (b.Steps) steps = b.Steps.ToList();
            lock (b.Errors) errors = b.Errors.ToList();
            List<object> popups;
            lock (b.Popups) popups = b.Popups.ToList();
            if (b.ThrownItems != null)
                Log(new { kind = "throw_locations", run = c.Id, branch = c.Branch,
                    target = new { x = b.TargetX, y = b.TargetY },
                    items = b.ThrownItems.Select(item => new { blueprint = item.Blueprint,
                        zone = item.CurrentCell?.ParentZone?.ZoneID,
                        x = item.CurrentCell?.X, y = item.CurrentCell?.Y }).ToArray() });
            Log(new
            {
                kind = "branch_result", run = c.Id, @case = c.Case, branch = c.Branch, status, reason,
                path = ui ? R7Policy.UiPath(c.Case) : R7Policy.DirectPath(c.Case),
                saveSha256 = c.SaveSha256, saveShaSource = "parent-attested (command file)", fixture = c.Fixture,
                args = new { stat = c.Stat, blueprint = c.Blueprint, dx = c.Dx, dy = c.Dy, node = c.Node, bodyPart = c.BodyPart, noteId = c.NoteId },
                load = b.Load, before = b.Before, after, messages, popups,
                elapsedMs = b.Clock.ElapsedMilliseconds, errors, mutatesLoadedSave = true,
                directSteps = ui ? null : steps,
                uiReceipt = ui && status != "unsupported" ? new
                {
                    path = R7Policy.UiPath(c.Case), completed = status == "executed", directCall = false,
                    engineSteps = steps, pickerSteps = b.PickerStep, handlerInvoked = b.HandlerInvoked
                } : null,
            });
            if (ReferenceEquals(_b, b)) _b = null;
        }
    }
}
