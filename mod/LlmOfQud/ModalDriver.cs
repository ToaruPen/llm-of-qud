// Production Modern-UI modal driver. Recipes extracted from probes/R5-modal-driver/ModalProbe.cs (runtime-verified,
// docs results 2026-09-26 run1-4). Unity objects are touched ONLY inside Tick() (UI thread). No Harmony, no Hide()-first,
// no awaitTask. Pure validation / token / rule logic lives in ModalPolicy.cs (unit-tested in mod/modal-tests).
// Citations are file:line in coq-decompiled_stable (2.0.211.56).
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Reflection;
using System.Threading.Tasks;
using ConsoleLib.Console;
using Newtonsoft.Json.Linq;
using Qud.UI;
using XRL;
using XRL.Core;
using XRL.UI;
using XRL.World;

namespace LlmOfQud
{
    public sealed class ModalDriver
    {
        private const int SettleFrames = 8;            // a modal must be seen this many frames before any input
        private const int AbsentTicksToClear = 2;
        private const long WatchdogMs = 30000;
        private const int PickerResolveFrames = 45;     // settled frames after a confirm before we call the input lost
        private const int PickerMaxRetries = 2;
        private const int RuleRetryFrames = 30, RuleMaxAttempts = 5;

        private readonly Action<JObject> _emit;
        private readonly Action<string> _addDigest;
        private readonly Action<string> _beforeRule;
        private readonly ModalLedger _ledger = new ModalLedger();
        private readonly ModalTokens _tokens = new ModalTokens();
        private readonly Stopwatch _clock = Stopwatch.StartNew();
        private readonly object _statusLock = new object();

        // ---- UI-thread state ----
        private string _uiRun;
        private long _uiGeneration = -1;
        private bool _uiActive;
        private int _lastFrame = -1;
        private ModalView _current;
        private Live _live;
        private int _seenFrames, _absentTicks, _ruleAttempts, _ruleWait;
        private bool _ruleDone;
        private PickerOp _op;
        private bool _pickerOpen;
        private PickTargetWindow.TargetMode _pickerMode;
        private object _pickerEpisode;
        private long _unknownSinceMs = -1;
        private bool _watchdogFired;
        private string _unknownView;

        // ---- status (plain, locked) ----
        private string _stType = "none", _stToken, _stView = "", _stLastReason, _stWatchdog;
        private long _stSinceMs, _stTicks, _stAnswers, _stRejects, _stAutos;

        private static readonly FieldInfo TutInstance = typeof(TutorialManager).GetField("instance", BindingFlags.Static | BindingFlags.NonPublic);
        private static readonly FieldInfo TutCompletion = typeof(TutorialManager).GetField("PopupCompletion", BindingFlags.Static | BindingFlags.NonPublic);
        private static readonly FieldInfo TutShowing = typeof(TutorialManager).GetField("ShowingPopup", BindingFlags.Instance | BindingFlags.NonPublic);
        private static readonly FieldInfo TutText = typeof(TutorialManager).GetField("PopupText", BindingFlags.Instance | BindingFlags.NonPublic);

        private sealed class Live
        {
            public PopupMessage Pm;
            public object OnHide, Cmd, Sel, Tcs;
            public List<GameObject> Objects; // pick_item
        }

        private sealed class PickerOp
        {
            public ModalAnswer Answer;
            public ModalView View;
            public List<Step> Steps = new List<Step>();
            public int Next, Frames, Retries;
            public bool ConfirmPushed;
        }

        private sealed class Step
        {
            public string Label;
            public Action Push;
            public Func<bool> Done;   // null: done once pushed and consumed; otherwise observable completion
            public bool Confirm;
            public bool Idempotent;   // only idempotent pushes (PointerOver to the same cell) are ever re-pushed
        }

        public ModalDriver(Action<JObject> emit, Action<string> addDigest, Action<string> beforeRule = null)
        {
            _emit = emit ?? (o => { });
            _addDigest = addDigest ?? (s => { });
            _beforeRule = beforeRule ?? (s => { });
        }

        // ================= game / bridge thread entry points (no Unity) =================
        public void SetContext(string runId, long seq, bool active) { _ledger.SetContext(runId, seq, active); }
        public void SuspendAnswers() { _ledger.SuspendAnswers(); }

        public bool EnqueueAnswer(JObject frame)
        {
            string reason;
            ModalAnswer a = ModalPolicy.Parse(frame, out reason);
            if (a == null)
            {
                Reject(frame, reason);
                return false;
            }
            reason = _ledger.Enqueue(a);
            if (reason == null) return true;
            Reject(frame, reason);
            return false;
        }

        private void Reject(JObject frame, string reason)
        {
            lock (_statusLock) { _stRejects++; _stLastReason = reason; }
            JToken id = frame == null ? null : frame["answer_id"];
            if (id == null || id.Type != JTokenType.Integer) return; // cannot correlate; Status() carries the reason
            if (reason == "duplicate_answer_id") return;             // the first use of this id gets (or got) its own result
            JToken r = frame["run_id"], q = frame["seq"], t = frame["token"];
            Emit(new JObject
            {
                ["kind"] = "modal_result",
                ["run_id"] = r != null && r.Type == JTokenType.String ? (string)r : null,
                ["seq"] = q != null && q.Type == JTokenType.Integer ? (long)q : -1,
                ["token"] = t != null && t.Type == JTokenType.String ? (string)t : null,
                ["answer_id"] = (long)id, ["accepted"] = false, ["reason"] = reason,
            });
        }

        public JObject Status()
        {
            lock (_statusLock)
            {
                long now = _clock.ElapsedMilliseconds;
                return new JObject
                {
                    ["type"] = _stType, ["token"] = _stToken, ["view"] = _stView,
                    ["elapsed_ms"] = _stToken == null ? 0 : now - _stSinceMs,
                    ["ticks"] = _stTicks, ["answers"] = _stAnswers, ["rejects"] = _stRejects, ["autos"] = _stAutos,
                    ["last_reason"] = _stLastReason, ["watchdog"] = _stWatchdog,
                    ["queued"] = _ledger.QueueCount, ["in_flight"] = _ledger.InFlight,
                };
            }
        }

        private void Emit(JObject o)
        {
            try { _emit((JObject)o.DeepClone()); } catch (Exception) { }
        }

        // ================= UI thread =================
        public void Tick()
        {
            int frame = UnityEngine.Time.frameCount;
            if (frame == _lastFrame) return; // one pass per frame
            _lastFrame = frame;
            lock (_statusLock) _stTicks++;
            string run; long seq; bool active;
            _ledger.Context(out run, out seq, out active);
            long gen = _ledger.Generation;
            DrainDropped();
            if (run != _uiRun || !active || !_uiActive || gen != _uiGeneration)
            {
                if (run != _uiRun || !active || gen != _uiGeneration) ResetUi(run);
                _uiGeneration = gen;
                _uiRun = run;
                _uiActive = active;
                if (!active) { SetStatus("inactive", null, ""); return; }
            }
            try { Step1(run, seq); }
            catch (Exception e)
            {
                lock (_statusLock) _stLastReason = "tick_exception:" + e.GetType().Name;
                MetricsManager.LogError("[LLM] ModalDriver.Tick", e);
            }
        }

        private void DrainDropped()
        {
            foreach (ModalDrop d in _ledger.TakeDropped())
                Emit(new JObject { ["kind"] = "modal_result", ["run_id"] = d.Answer.RunId, ["seq"] = d.Answer.Seq, ["token"] = d.Answer.Token,
                                   ["answer_id"] = d.Answer.AnswerId, ["accepted"] = false, ["reason"] = d.Reason });
        }

        private void ResetUi(string run)
        {
            _tokens.Reset(run ?? "r0");
            _ledger.Unpublish();
            _current = null; _live = null; _op = null;
            _pickerOpen = false; _pickerEpisode = null;
            _unknownSinceMs = -1; _watchdogFired = false;
        }

        private void Step1(string run, long seq)
        {
            GameManager gm = GameManager.Instance;
            if (gm == null) return;
            Live live;
            ModalSnapshot snap = Classify(gm, out live);
            Watchdog(gm, snap, run, seq);

            if (_op != null && _ledger.AnswersSuspended)
            {
                ModalAnswer answer = _op.Answer;
                _op = null;
                _ledger.Release(answer.Token);
                Result(run, answer.Seq, answer.Token, answer.AnswerId, false, "game_not_running");
            }
            if (_op != null) { RunPickerOp(gm, snap, run, seq); return; }

            if (snap == null || !snap.Ready)
            {
                if (_current != null && ++_absentTicks >= AbsentTicksToClear) Clear(run, seq, "closed_without_answer");
                if (_current == null) SetStatus(snap == null ? "none" : snap.Type + "-notready", null, gm.CurrentGameView ?? "");
                return;
            }
            _absentTicks = 0;
            if (_current == null || !ReferenceEquals(snap.Identity, _current.Identity))
            {
                if (_current != null) Clear(run, seq, "replaced_without_answer");
                bool isNew;
                string token = _tokens.For(snap.Identity, out isNew);
                _current = ModalPolicy.Build(snap, token, _clock.ElapsedMilliseconds);
                _live = live;
                _seenFrames = 0; _ruleAttempts = 0; _ruleWait = 0; _ruleDone = false;
                SetStatus(snap.Type, token, gm.CurrentGameView ?? "");
                _current.Seq = seq; // Publish re-stamps under the ledger lock
                if (_current.Rule == null)
                {
                    _ledger.Publish(_current);
                    Emit(new JObject { ["kind"] = "modal", ["run_id"] = run, ["seq"] = _current.Seq, ["token"] = token, ["modal"] = _current.ToDto() });
                }
                return;
            }
            _live = live; // same identity: refresh engine references (identity-equal)
            if (++_seenFrames < SettleFrames) return;
            if (_current.Rule != null) { ApplyRule(gm, run, seq); return; }
            ModalAnswer a = _ledger.Dequeue();
            if (a != null) Answer(gm, a, run, seq);
        }

        private void Clear(string run, long seq, string reason)
        {
            ModalView v = _current;
            _current = null; _live = null;
            _ledger.Unpublish();
            if (v == null) return;
            if (v.Rule == null && !_ledger.Succeeded(v.Token))
                Emit(new JObject { ["kind"] = "modal_clear", ["run_id"] = run, ["seq"] = v.Seq, ["token"] = v.Token, ["reason"] = reason });
            SetStatus("none", null, "");
        }

        private void SetStatus(string type, string token, string view)
        {
            lock (_statusLock)
            {
                if (token != _stToken) _stSinceMs = _clock.ElapsedMilliseconds;
                _stType = type; _stToken = token; _stView = view;
            }
        }

        // ---------------- watchdog: never answers, only reports ----------------
        private void Watchdog(GameManager gm, ModalSnapshot snap, string run, long seq)
        {
            string view = gm.CurrentGameView ?? "";
            bool ending = The.Game != null && !string.IsNullOrEmpty(The.Game.GetStringGameState("EndType"));
            bool unknown = ModalPolicy.ShouldWatchdog(view, Options.StageViewID, snap != null && snap.Ready, ending, _ledger.AnswersSuspended);
            if (!unknown) { _unknownSinceMs = -1; _watchdogFired = false; lock (_statusLock) _stWatchdog = null; return; }
            long now = _clock.ElapsedMilliseconds;
            if (_unknownSinceMs < 0 || view != _unknownView) { _unknownSinceMs = now; _unknownView = view; _watchdogFired = false; }
            if (!_watchdogFired && now - _unknownSinceMs >= WatchdogMs)
            {
                _watchdogFired = true;
                lock (_statusLock) _stWatchdog = "unhandled_modal:" + view;
                // Extra wire kind (task: "unknown-modal watchdog event/status at 30s"); informational, never answers.
                Emit(new JObject { ["kind"] = "modal_watchdog", ["run_id"] = run, ["seq"] = seq, ["reason"] = "unhandled_modal", ["view"] = view,
                                   ["type"] = snap == null ? "unknown" : snap.Type, ["elapsed_ms"] = now - _unknownSinceMs });
            }
        }

        // ================= classification (R5 Bridge.Classify, production subset) =================
        private ModalSnapshot Classify(GameManager gm, out Live live)
        {
            live = null;
            string view = gm.CurrentGameView ?? "";
            ModalSnapshot t = ClassifyTutorial(view);
            if (t != null) return t;

            PopupMessage best = null; string bestKey = null;
            foreach (KeyValuePair<string, WindowBase> kv in UIManager.instance.windowsByName)
            {
                PopupMessage pm = kv.Value as PopupMessage;
                if (pm == null || pm.onHide == null || !pm.gameObject.activeSelf) continue;
                if (pm.canvasGroup != null && !pm.canvasGroup.interactable) continue;
                if (best == null) { best = pm; bestKey = kv.Key; continue; }
                bool cCopy = kv.Key.StartsWith("PopupMessage #", StringComparison.Ordinal), bCopy = bestKey.StartsWith("PopupMessage #", StringComparison.Ordinal);
                bool better = ReferenceEquals(pm.transform.parent, best.transform.parent)
                    ? (pm.transform.GetSiblingIndex() > best.transform.GetSiblingIndex() || (pm.transform.GetSiblingIndex() == best.transform.GetSiblingIndex() && cCopy && !bCopy))
                    : (cCopy && !bCopy);
                if (better) { best = pm; bestKey = kv.Key; }
            }
            if (best != null) { _pickerOpen = false; return ClassifyPopup(best, view, out live); }

            if (view == "PickTarget") return ClassifyPicker(gm, view);
            _pickerOpen = false;

            AskNumberScreen an = SingletonWindowBase<AskNumberScreen>.instance;
            if (an != null && (view == "ModernPopupGamepadAskNumber" || an.isCurrentWindow()))
            {
                object tcs = Field(an, typeof(AskNumberScreen), "menucomplete");
                bool ready = Pending(tcs) && an.isCurrentWindow();
                live = new Live { Tcs = tcs };
                return new ModalSnapshot
                {
                    Type = "number", InputKind = "number", Identity = tcs, View = view, Ready = ready, PopupID = "AskNumberScreen",
                    Text = ModalPolicy.Strip(an.messageText == null ? null : an.messageText.text), Min = an.Min, Max = an.Max,
                };
            }
            BookScreen bk = SingletonWindowBase<BookScreen>.instance;
            if (bk != null && (view == "Book" || bk.isCurrentWindow()))
            {
                object tcs = Field(bk, typeof(BookScreen), "menucomplete");
                live = new Live { Tcs = tcs };
                return new ModalSnapshot { Type = "book", Identity = tcs, View = view, Title = ModalPolicy.Strip(bk.titleText == null ? null : bk.titleText.text),
                                           Ready = Pending(tcs) && bk.isCurrentWindow() && bk.navigationContext.IsActive() };
            }
            if (view == "PickGameObject")
            {
                PickGameObjectScreen pg = SingletonWindowBase<PickGameObjectScreen>.instance;
                if (pg != null)
                {
                    object tcs = Field(pg, typeof(PickGameObjectScreen), "menucomplete");
                    if (_current != null && _live != null && _live.Objects != null && ReferenceEquals(tcs, _current.Identity))
                    {
                        _current.Snap.Ready = Pending(tcs) && pg.isCurrentWindow();
                        live = _live;
                        return _current.Snap;
                    }
                    ModalSnapshot s = new ModalSnapshot { Type = "pick_item", Identity = tcs, View = view, Ready = Pending(tcs) && pg.isCurrentWindow(),
                                                          Title = ModalPolicy.Strip(pg.titleText == null ? null : pg.titleText.text) };
                    List<GameObject> objs = pg.rawGameObjects == null ? new List<GameObject>() : new List<GameObject>(pg.rawGameObjects);
                    for (int i = 0; i < objs.Count && i < 60; i++) s.ItemLabels.Add(objs[i] == null ? "?" : objs[i].ShortDisplayNameStripped);
                    if (objs.Count > 60) objs.RemoveRange(60, objs.Count - 60);
                    live = new Live { Tcs = tcs, Objects = objs };
                    return s;
                }
            }
            string[] stack = gm.GetGameViewStackCopy();
            if (Array.IndexOf(stack, "ModernTrade") >= 0 || view == "ModernTrade")
            {
                TradeScreen ts = SingletonWindowBase<TradeScreen>.instance;
                if (ts != null)
                {
                    object tcs = Field(ts, typeof(TradeScreen), "menucomplete");
                    XRL.UI.Framework.NavigationController nc = XRL.UI.Framework.NavigationController.instance;
                    bool busy = nc != null && ReferenceEquals(nc.activeContext, nc.suspensionContext);
                    live = new Live { Tcs = tcs };
                    return new ModalSnapshot { Type = "trade", Identity = tcs, View = view, Ready = Pending(tcs) && ts.navigationContext.IsActive() && !busy };
                }
            }
            if (Array.IndexOf(stack, "StatusScreensScreen") >= 0 || view == "StatusScreensScreen")
            {
                StatusScreensScreen st = SingletonWindowBase<StatusScreensScreen>.instance;
                if (st != null)
                {
                    object tcs = Field(st, typeof(StatusScreensScreen), "menucomplete");
                    live = new Live { Tcs = tcs };
                    return new ModalSnapshot { Type = "status", Identity = tcs, View = view, Ready = Pending(tcs) && st.navigationContext.IsActive() };
                }
            }
            return null;
        }

        private ModalSnapshot ClassifyTutorial(string view)
        {
            TutorialManager tm = TutInstance == null ? null : TutInstance.GetValue(null) as TutorialManager;
            if (tm == null || TutShowing == null) return null;
            object showing = TutShowing.GetValue(tm);
            if (!(showing is bool) || !(bool)showing) return null;
            object token = TutCompletion == null ? null : TutCompletion.GetValue(null);
            return new ModalSnapshot { Type = "tutorial", Identity = token, View = view, Ready = token != null,
                                       Text = ModalPolicy.Strip(TutText == null ? null : TutText.GetValue(tm) as string) };
        }

        private ModalSnapshot ClassifyPopup(PopupMessage pm, string view, out Live live)
        {
            live = new Live { Pm = pm, OnHide = pm.onHide, Cmd = pm.commandCallback, Sel = pm.selectCallback };
            bool input = pm.inputBox != null && pm.inputBox.gameObject.activeSelf;
            bool conversation = pm.PopupID != null && pm.PopupID.StartsWith("Conversation:", StringComparison.Ordinal);
            ModalSnapshot s = new ModalSnapshot
            {
                Identity = pm.onHide, View = view, PopupID = pm.PopupID, HasInput = input,
                WantsSpecificPrompt = pm.WantsSpecificPrompt, RestrictChars = pm.RestrictChars,
                Title = pm.Title == null ? "" : ModalPolicy.Strip(pm.Title.text),
                Text = pm.Message == null ? "" : ModalPolicy.Strip(pm.Message.text),
                CheckpointingEnabled = _current != null && ReferenceEquals(pm.onHide, _current.Identity) ? _current.Snap.CheckpointingEnabled : SafeCheckpointing(),
                Ready = pm.commandCallback != null || pm.selectCallback != null,
            };
            // contextText is deliberately NOT used as a title: the death-menu rule requires the real (empty) Title.
            List<QudMenuItem> items = pm.controller == null ? null : pm.controller.menuData;
            for (int i = 0; items != null && i < items.Count; i++)
            {
                s.ItemLabels.Add(items[i].text == null ? null : ModalPolicy.Strip(items[i].text));
                string command = items[i].command;
                s.ItemCommands.Add(command);
                // Trade can be an ordinary conversation choice (option:N), as well as the
                // bottom "trade" button. Match the engine part, independent of displayed text.
                int index;
                if (conversation && command != null && command.StartsWith("option:", StringComparison.Ordinal) &&
                    int.TryParse(command.Substring(7), out index) && index >= 0 &&
                    ConversationUI.CurrentChoices != null && index < ConversationUI.CurrentChoices.Count &&
                    ConversationUI.CurrentChoices[index].HasPart<XRL.World.Conversations.Parts.Trade>())
                    s.BlockedItems.Add(i);
            }
            List<QudMenuItem> buttons = pm.controller == null ? null : pm.controller.bottomContextOptions;
            for (int j = 0; buttons != null && j < buttons.Count; j++)
            {
                s.ButtonLabels.Add(buttons[j].text == null ? null : ModalPolicy.Strip(buttons[j].text));
                s.ButtonCommands.Add(buttons[j].command);
                s.ButtonHotkeys.Add(buttons[j].hotkey);
            }
            if (input)
            {
                // AskNumberAsync keyboard path: askingNumber popup with digit RestrictChars (Popup.cs:1349, PopupMessage.cs:785-792).
                bool number = pm.RestrictChars == "0123456789" || pm.RestrictChars == "0123456789-";
                s.Type = number ? "number" : "string";
                s.InputKind = number ? "number" : "string";
                if (!number) s.RestrictChars = null; // AskStringAsync passes "" (Popup.cs:1396); nothing to publish
                // Submit button is the {text}/{number} path, not a choice.
                for (int j = s.ButtonCommands.Count - 1; j >= 0; j--)
                    if (s.ButtonHotkeys[j] == "Submit" || s.ButtonCommands[j] == "keep") { s.ButtonLabels[j] = null; }
            }
            else s.Type = conversation ? "conversation" : "popup";
            return s;
        }

        private static bool SafeCheckpointing()
        {
            try { return CheckpointingSystem.IsCheckpointingEnabled(); } catch (Exception) { return false; }
        }

        // Picker token: no per-instance engine object exists (PickDirection.cs:28-31, PickTarget.cs:84-87,378-381 only set a
        // static mode and push "PickTarget"). A new episode starts when the view enters PickTarget, the mode changes, or a
        // resolved answer/confirm closed the previous one.
        private ModalSnapshot ClassifyPicker(GameManager gm, string view)
        {
            PickTargetWindow.TargetMode mode = PickTargetWindow.currentMode;
            if (!_pickerOpen || mode != _pickerMode || _pickerEpisode == null) { _pickerEpisode = new object(); _pickerMode = mode; _pickerOpen = true; }
            ModalSnapshot s = new ModalSnapshot { Identity = _pickerEpisode, View = view, Text = ModalPolicy.Strip(PickTargetWindow.currentText) };
            if (mode == PickTargetWindow.TargetMode.PickDirection) { s.Type = "direction"; s.InputKind = "direction"; }
            else if (mode == PickTargetWindow.TargetMode.PickCells) { s.Type = "cell"; s.InputKind = "cell"; }
            else if (mode == PickTargetWindow.TargetMode.PickField)
            { s.Type = "field"; s.InputKind = "field"; s.Ready = ModalPolicy.FieldPromptReady(PickTargetWindow.currentText); }
            else { s.Type = "unknown"; s.Ready = false; }
            return s;
        }

        // ================= answers (popup / screens) =================
        private void Answer(GameManager gm, ModalAnswer a, string run, long ctxSeq)
        {
            ModalView v = _current;
            long seq = v.Seq;
            Live live = _live;
            string ik = v.Snap.InputKind;
            if (ik == "direction" || ik == "cell" || ik == "field") { StartPickerOp(gm, a, v, run, seq); return; }
            string guard = GuardLive(v, live);
            if (guard != null) { Result(run, seq, v.Token, a.AnswerId, false, guard); return; }
            string claim = _ledger.Claim(a, v);
            if (claim != null) { Result(run, seq, v.Token, a.AnswerId, false, claim); return; }
            bool ok; string reason;
            try { ok = Apply(v, live, a.Kind, a.Choice, a.Text ?? (a.Kind == "number" ? a.Number.ToString() : null), a.Number, out reason); }
            catch (Exception e) { ok = false; reason = "exception:" + e.GetType().Name; }
            if (ok) { _ledger.Succeed(v.Token); lock (_statusLock) _stAnswers++; }
            else _ledger.Release(v.Token);
            Result(run, seq, v.Token, a.AnswerId, ok, reason);
        }

        private void Result(string run, long seq, string token, long answerId, bool ok, string reason)
        {
            if (!ok) lock (_statusLock) { _stRejects++; _stLastReason = reason; }
            Emit(new JObject { ["kind"] = "modal_result", ["run_id"] = run, ["seq"] = seq, ["token"] = token, ["answer_id"] = answerId, ["accepted"] = ok, ["reason"] = reason });
        }

        private static string GuardLive(ModalView v, Live live)
        {
            if (live == null) return "no_live_modal";
            if (live.Pm != null)
            {
                if (!ReferenceEquals(live.Pm.onHide, v.Identity)) return "token_mismatch_onhide";
                if (!live.Pm.gameObject.activeSelf) return "inactive";
            }
            else if (live.Tcs != null && !ReferenceEquals(live.Tcs, v.Identity)) return "token_mismatch_tcs";
            return null;
        }

        // Performs exactly one engine callback. choiceId in {option:i, button:j, cancel}; returns accepted when the token
        // provably advanced (onHide nulled by Hide() inside OnActivateCommand/OnSelect, PopupMessage.cs:926-944,1083-1103;
        // menucomplete completed for screens).
        private bool Apply(ModalView v, Live live, string kind, string choiceId, string text, int number, out string reason)
        {
            reason = "accepted";
            if (live.Pm != null)
            {
                PopupMessage pm = live.Pm;
                object token = live.OnHide;
                if (kind == "text" || kind == "number")
                {
                    if (!ReferenceEquals(pm.selectCallback, live.Sel) || pm.selectCallback == null) { reason = "token_mismatch_select"; return false; }
                    if (pm.inputBox == null || !pm.inputBox.gameObject.activeSelf) { reason = "no_input"; return false; }
                    pm.inputBox.text = text;
                    if (pm.inputBox.text != text) { reason = "input_rewritten"; return false; }
                    pm.OnInputSubmit(text); // R5 PopupInput (verified askstring/asknumber:kb)
                    if (ReferenceEquals(pm.onHide, token)) { reason = "refused_by_ui"; return false; }
                    return true;
                }
                QudMenuItem item;
                string why = FindItem(v, pm, kind == "cancel" ? CancelChoice(v) : choiceId, out item);
                if (why != null) { reason = why; return false; }
                if (!ReferenceEquals(pm.commandCallback, live.Cmd) || pm.commandCallback == null) { reason = "token_mismatch_command"; return false; }
                pm.OnActivateCommand(item); // R5 PopupCommand (verified pickoption/conv/death/yesno)
                if (ReferenceEquals(pm.onHide, token)) { reason = "refused_by_ui"; return false; }
                return true;
            }
            if (v.Snap.Type == "number" && live.Tcs != null)
            {
                AskNumberScreen an = SingletonWindowBase<AskNumberScreen>.instance;
                if (an == null) { reason = "no_instance"; return false; }
                object cur = Field(an, typeof(AskNumberScreen), "menucomplete");
                if (!ReferenceEquals(cur, live.Tcs) || !Pending(cur)) { reason = "token_mismatch_tcs"; return false; }
                if (!an.isCurrentWindow()) { reason = "not_current_window"; return false; }
                if (kind == "cancel") an.Cancel(); // AskNumberScreen.cs:222-227 resolves the same TCS with null.
                else
                {
                    an.Current = number;
                    an.numberText.SetText(number.ToString());
                    an.Accept(); // AskNumberScreen.cs:213-220, R5 asknumber:mouse/pad verified
                }
                if (Pending(cur)) { reason = "refused_by_ui"; return false; }
                return true;
            }
            if (v.Snap.Type == "pick_item" && live.Tcs != null)
            {
                PickGameObjectScreen pg = SingletonWindowBase<PickGameObjectScreen>.instance;
                if (pg == null) { reason = "no_instance"; return false; }
                object cur = Field(pg, typeof(PickGameObjectScreen), "menucomplete");
                if (!ReferenceEquals(cur, live.Tcs) || !Pending(cur)) { reason = "token_mismatch_tcs"; return false; }
                if (!pg.isCurrentWindow()) { reason = "not_current_window"; return false; }
                if (kind == "cancel")
                {
                    pg.Cancel(); // PickGameObjectScreen.cs:512-516 resolves the selection with default(Result).
                    if (Pending(cur)) { reason = "refused_by_ui"; return false; }
                    return true;
                }
                int idx = ChoiceIndex(choiceId, "option:");
                if (idx < 0 || live.Objects == null || idx >= live.Objects.Count) { reason = "unknown_choice"; return false; }
                GameObject target = live.Objects[idx];
                if (target == null || pg.rawGameObjects == null || !pg.rawGameObjects.Contains(target)) { reason = "target_not_listed"; return false; }
                pg.HandleSelectItem(new PickGameObjectLineData().set(PickGameObjectLineDataType.Item, go: target)); // R5 pickitem verified
                if (Pending(cur)) { reason = "refused_by_ui"; return false; }
                return true;
            }
            reason = "unsupported_modal";
            return false;
        }

        private static string CancelChoice(ModalView v)
        {
            for (int j = 0; j < v.Snap.ButtonCommands.Count; j++) if (v.Snap.ButtonCommands[j] == "Cancel") return "button:" + j;
            return null;
        }

        private static int ChoiceIndex(string id, string prefix)
        {
            int n;
            if (id == null || !id.StartsWith(prefix, StringComparison.Ordinal)) return -1;
            return int.TryParse(id.Substring(prefix.Length), out n) ? n : -1;
        }

        // option:i = menuData[i], button:j = bottomContextOptions[j]; the command at that index must still equal the one
        // captured at publish time, and the item must have text (sync callback calls i.text.Replace, Popup.cs:834-852).
        private static string FindItem(ModalView v, PopupMessage pm, string id, out QudMenuItem item)
        {
            item = default(QudMenuItem);
            if (id == null) return "no_cancel_button";
            bool isItem = id.StartsWith("option:", StringComparison.Ordinal);
            int idx = ChoiceIndex(id, isItem ? "option:" : "button:");
            List<string> captured = isItem ? v.Snap.ItemCommands : v.Snap.ButtonCommands;
            List<QudMenuItem> list = pm.controller == null ? null : (isItem ? pm.controller.menuData : pm.controller.bottomContextOptions);
            if (idx < 0 || list == null || idx >= list.Count || idx >= captured.Count) return "unknown_choice";
            if (list[idx].command != captured[idx]) return "choice_changed";
            if (list[idx].text == null) return "item_text_null";
            item = list[idx];
            return null;
        }

        // ================= system rules (never ask the LLM) =================
        private void ApplyRule(GameManager gm, string run, long seq)
        {
            if (_ruleDone) return;
            if (_ruleWait > 0) { _ruleWait--; return; }
            ModalView v = _current;
            bool ok = false; string reason = "not_attempted";
            try
            {
                if (v.Rule == "tutorial_accept") ok = TutorialAccept(v, out reason);
                else if (v.Rule == "screen_cancel") ok = ScreenCancel(v, out reason);
                else if (v.RuleChoice == null) reason = "no_safe_choice";
                else
                {
                    string guard = GuardLive(v, _live);
                    if (guard != null) reason = guard;
                    else
                    {
                        _beforeRule(v.Rule);
                        ok = Apply(v, _live, "choice", v.RuleChoice, null, 0, out reason);
                    }
                }
            }
            catch (Exception e) { reason = "exception:" + e.GetType().Name; }
            _ruleAttempts++;
            if (!ok && _ruleAttempts < RuleMaxAttempts) { _ruleWait = RuleRetryFrames; lock (_statusLock) _stLastReason = "rule_retry:" + reason; return; }
            _ruleDone = true;
            if (ok)
            {
                _ledger.Succeed(v.Token);
                lock (_statusLock) _stAutos++;
                if (v.Rule == "notice_accept" || v.Rule == "tutorial_accept") _addDigest(ModalPolicy.Collapse(v.Snap.Text));
            }
            Emit(new JObject { ["kind"] = "modal_auto", ["run_id"] = run, ["seq"] = v.Seq, ["token"] = v.Token, ["rule"] = v.Rule,
                               ["modal"] = v.ToDto(), ["accepted"] = ok, ["reason"] = reason });
        }

        // R5 Answer.Tutorial: one press per PopupCompletion token (TutorialManager.cs:764-789).
        private bool TutorialAccept(ModalView v, out string reason)
        {
            TutorialManager tm = TutInstance == null ? null : TutInstance.GetValue(null) as TutorialManager;
            if (tm == null) { reason = "no_instance"; return false; }
            object showing = TutShowing.GetValue(tm);
            if (!(showing is bool) || !(bool)showing) { reason = "not_showing"; return false; }
            if (!ReferenceEquals(TutCompletion.GetValue(null), v.Identity)) { reason = "token_mismatch"; return false; }
            if (tm.popupAcceptPressed) { reason = "already_latched"; _ruleAttempts = RuleMaxAttempts; return false; }
            tm.OnPopupAcceptPressed();
            reason = "accept_pressed";
            return true;
        }

        // R5 BookCancel / TradeCancel / StatusExit (all verified).
        private bool ScreenCancel(ModalView v, out string reason)
        {
            if (v.Snap.Type == "book")
            {
                BookScreen bk = SingletonWindowBase<BookScreen>.instance;
                object cur = bk == null ? null : Field(bk, typeof(BookScreen), "menucomplete");
                if (!ReferenceEquals(cur, v.Identity) || !Pending(cur)) { reason = "token_mismatch"; return false; }
                if (!bk.isCurrentWindow() || !bk.navigationContext.IsActive()) { reason = "not_current"; return false; }
                bk.Cancel();
                reason = Pending(cur) ? "refused_by_ui" : "cancelled";
                return !Pending(cur);
            }
            if (v.Snap.Type == "trade")
            {
                TradeScreen ts = SingletonWindowBase<TradeScreen>.instance;
                object cur = ts == null ? null : Field(ts, typeof(TradeScreen), "menucomplete");
                if (!ReferenceEquals(cur, v.Identity) || !Pending(cur)) { reason = "token_mismatch"; return false; }
                XRL.UI.Framework.NavigationController nc = XRL.UI.Framework.NavigationController.instance;
                if (!ts.navigationContext.IsActive() || (nc != null && ReferenceEquals(nc.activeContext, nc.suspensionContext))) { reason = "busy"; return false; }
                ts.Cancel();
                reason = Pending(cur) ? "refused_by_ui" : "cancelled";
                return !Pending(cur);
            }
            if (v.Snap.Type == "status")
            {
                StatusScreensScreen st = SingletonWindowBase<StatusScreensScreen>.instance;
                object cur = st == null ? null : Field(st, typeof(StatusScreensScreen), "menucomplete");
                if (!ReferenceEquals(cur, v.Identity) || !Pending(cur)) { reason = "token_mismatch"; return false; }
                if (!st.navigationContext.IsActive()) { reason = "nav_inactive"; return false; }
                st.Exit();
                reason = Pending(cur) ? "refused_by_ui" : "exited";
                return !Pending(cur);
            }
            reason = "unsupported_screen";
            return false;
        }

        // ================= pickers: one input per settled frame =================
        private static bool Settled(GameManager gm)
        {
            return gm._ActiveGameView == gm.CurrentGameView && !gm.bViewUpdated && XRLCore.bThreadFocus
                   && Keyboard.KeyQueue.Count == 0 && !Keyboard.HasMouseEvent();
        }

        // 1 = readback valid and at (x,y); 0 = readback invalid/unknown; -1 = valid and elsewhere.
        // PickTarget.Buffer.focusPosition is written by the picker loops (PickTarget.cs:157,784) but was never read in R5.
        private static int Cursor(int x, int y)
        {
            if (PickTarget.Buffer == null) return 0;
            Genkit.Point2D p = PickTarget.Buffer.focusPosition;
            Genkit.Point2D inv = Genkit.Point2D.invalid;
            if (p.x == inv.x && p.y == inv.y) return 0;
            if (p.x < 0 || p.y < 0 || p.x > 79 || p.y > 24) return 0;
            return p.x == x && p.y == y ? 1 : -1;
        }

        private static readonly Dictionary<string, UnityEngine.KeyCode> Keypad = new Dictionary<string, UnityEngine.KeyCode>
        {
            { "N", UnityEngine.KeyCode.Keypad8 }, { "NE", UnityEngine.KeyCode.Keypad9 }, { "E", UnityEngine.KeyCode.Keypad6 }, { "SE", UnityEngine.KeyCode.Keypad3 },
            { "S", UnityEngine.KeyCode.Keypad2 }, { "SW", UnityEngine.KeyCode.Keypad1 }, { "W", UnityEngine.KeyCode.Keypad4 }, { "NW", UnityEngine.KeyCode.Keypad7 },
        };

        private void StartPickerOp(GameManager gm, ModalAnswer a, ModalView v, string run, long ctxSeq)
        {
            long seq = v.Seq;
            PickerOp op = new PickerOp { Answer = a, View = v };
            if (a.Kind == "cancel")
            {
                // A started field first clears its selection; abort is a distinct subsequent Escape (R5 field-cancel).
                if (v.Snap.InputKind == "field" && ModalPolicy.FieldSelectionStarted(PickTargetWindow.currentText))
                    op.Steps.Add(new Step { Label = "clear", Push = () => Keyboard.PushKey(UnityEngine.KeyCode.Escape),
                        Done = () => !ModalPolicy.FieldSelectionStarted(PickTargetWindow.currentText) });
                op.Steps.Add(new Step { Label = "cancel", Push = () => Keyboard.PushKey(UnityEngine.KeyCode.Escape), Confirm = true });
            }
            else if (a.Kind == "direction")
            {
                UnityEngine.KeyCode k = Keypad[a.Direction];
                op.Steps.Add(new Step { Label = "dir:" + a.Direction, Push = () => Keyboard.PushKey(k), Confirm = true }); // PickDirection.cs:60-95
            }
            else if (a.Kind == "target")
            {
                int x = a.X, y = a.Y;
                // First PointerOver per ShowPicker is swallowed (PickTarget.cs:402,792-808); R5 picktarget verified x2 + CmdFire.
                op.Steps.Add(new Step { Label = "pointer#1", Push = () => Keyboard.PushMouseEvent("PointerOver", x, y), Idempotent = true });
                op.Steps.Add(new Step { Label = "pointer#2", Push = () => Keyboard.PushMouseEvent("PointerOver", x, y), Done = () => Cursor(x, y) != -1, Idempotent = true }); // invalid readback: R5 behaviour
                op.Steps.Add(new Step { Label = "CmdFire", Push = () => Keyboard.PushCommand("CmdFire"), Confirm = true });
            }
            else if (a.Kind == "field")
            {
                // PointerOver's first event is swallowed, and mouse motion deliberately stops focusPosition updates
                // (PickTarget.cs:157,203-219). Keypad5 restores that readback; verify it before extending the field.
                int sx = a.Field[0][0], sy = a.Field[0][1];
                op.Steps.Add(new Step { Label = "field_pointer#1", Push = () => Keyboard.PushMouseEvent("PointerOver", sx, sy), Idempotent = true });
                op.Steps.Add(new Step { Label = "field_pointer#2", Push = () => Keyboard.PushMouseEvent("PointerOver", sx, sy), Idempotent = true });
                op.Steps.Add(new Step { Label = "start", Push = () => Keyboard.PushKey(UnityEngine.KeyCode.Keypad5),
                                        Done = () => ModalPolicy.FieldSelectionStarted(PickTargetWindow.currentText) && Cursor(sx, sy) == 1 });
                for (int i = 1; i < a.Field.Count; i++)
                {
                    string d = ModalPolicy.DirectionFrom(a.Field[i][0] - a.Field[i - 1][0], a.Field[i][1] - a.Field[i - 1][1]);
                    UnityEngine.KeyCode k = Keypad[d];
                    int fx = a.Field[i][0], fy = a.Field[i][1];
                    op.Steps.Add(new Step { Label = "extend:" + d, Push = () => Keyboard.PushKey(k), Done = () => Cursor(fx, fy) != -1 });
                }
                op.Steps.Add(new Step { Label = "end", Push = () => Keyboard.PushKey(UnityEngine.KeyCode.Keypad5), Confirm = true });
            }
            else { Result(run, seq, v.Token, a.AnswerId, false, "response_type_mismatch"); return; }
            string claim = _ledger.Claim(a, v);
            if (claim != null) { Result(run, seq, v.Token, a.AnswerId, false, claim); return; }
            _op = op;
        }

        private void RunPickerOp(GameManager gm, ModalSnapshot snap, string run, long ctxSeq)
        {
            PickerOp op = _op;
            long seq = op.View.Seq;
            string token = op.View.Token;
            bool samePicker = snap != null && ReferenceEquals(snap.Identity, op.View.Identity);
            if (!samePicker)
            {
                // Picker closed (or a popup covered it). After the confirm was pushed this is the expected outcome.
                _op = null;
                _pickerEpisode = null; // any later PickTarget is a new episode
                if (op.ConfirmPushed) { _ledger.Succeed(token); lock (_statusLock) _stAnswers++; Result(run, seq, token, op.Answer.AnswerId, true, "confirm_consumed_view_changed"); }
                else { _ledger.Succeed(token); Result(run, seq, token, op.Answer.AnswerId, false, "picker_closed_before_confirm"); }
                _current = null; _live = null; _ledger.Unpublish();
                SetStatus("none", null, gm.CurrentGameView ?? "");
                return;
            }
            if (!Settled(gm)) return;
            if (op.Next > 0 && op.Next <= op.Steps.Count)
            {
                Step prev = op.Steps[op.Next - 1];
                bool observed = prev.Confirm ? false : (prev.Done == null || prev.Done());
                if (!observed)
                {
                    if (++op.Frames < PickerResolveFrames) return;
                    // Known lost (observable state did not change / picker still open after confirm). Only idempotent pushes are
                    // retried; a confirm / start / extend key is never re-pushed (no double confirmed action).
                    if (!prev.Idempotent || op.Retries >= PickerMaxRetries)
                    {
                        _op = null;
                        _ledger.Succeed(token); // input was delivered: this token is spent; whatever is open now gets a new token
                        Result(run, seq, token, op.Answer.AnswerId, false, prev.Confirm ? "picker_open_after_confirm" : "picker_step_not_applied:" + prev.Label);
                        _pickerEpisode = null; _current = null; _live = null; _ledger.Unpublish();
                        return;
                    }
                    op.Retries++;
                    op.Frames = 0;
                    prev.Push();
                    return;
                }
            }
            if (op.Next >= op.Steps.Count) return;
            Step s = op.Steps[op.Next];
            op.Next++;
            op.Frames = 0;
            op.Retries = 0;
            if (s.Confirm) op.ConfirmPushed = true;
            s.Push();
        }

        // ================= reflection helpers =================
        private static object Field(object inst, Type t, string name)
        {
            FieldInfo fi = t.GetField(name, BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);
            return fi == null ? null : fi.GetValue(inst);
        }

        private static bool Pending(object tcs)
        {
            if (tcs == null) return false;
            PropertyInfo pi = tcs.GetType().GetProperty("Task");
            Task t = pi == null ? null : pi.GetValue(tcs, null) as Task;
            return t != null && !t.IsCompleted;
        }
    }
}
