using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Collections.Generic;
using System.Reflection;
using System.Threading.Tasks;
using QupKit;
using Qud.UI;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using ConsoleLib.Console;
using XRL;
using XRL.Core;
using XRL.UI;
using XRL.World;
using XRL.World.Capabilities;

namespace LlmOfQud.ProbeR34
{
    [HasModSensitiveStaticCache]
    public static class Bootstrap
    {
        [ModSensitiveCacheInit]
        public static void Init() { Probe.Init(); }
    }

    [Serializable]
    public sealed class ProbeSystem : IPlayerSystem
    {
        public override void RegisterPlayer(GameObject player, IEventRegistrar registrar)
        {
            registrar.Register(SingletonEvent<CommandTakeActionEvent>.ID);
            base.RegisterPlayer(player, registrar);
        }
        public override bool HandleEvent(CommandTakeActionEvent e) { return Probe.OnCta(); }
    }

    internal sealed class Run
    {
        public string Id, Mode, Focus, Zone;
        public int Seconds, TargetTurns, Decisions, EndPlayerTurns, PlayerTurnEntries;
        public long TurnStart, Turn, Ctas, Moves;
        public int X, Y, StartHp;
        public int AnchorX, AnchorY, OtherX, OtherY;
        public readonly Stopwatch Clock = new Stopwatch();
        public MacroProgress Macro;
        public int MacroDecision;
        public long MacroMoves;
        public string LastMessage;
        public bool StopRequested;
        public int PopupAnswers, PickerIndex, PickerPushes;
        public int PickerAttempts, PickerSimulatedDrops;
        public bool DropFirstPickerPush;
        public long PickerStart, LastPickerPush;
        public bool? PickerFocus;
        public int PickerFocusChanges;
        public XRL.World.Parts.Stomach Stomach;
        public int SavedWater, SavedCookingCounter, SavedWorldMap;
        public StatusScreensScreen HoverWindow;
        public TaskCompletionSource<ScreenReturn> HoverCompletion;
        public InventoryLine HoverLine;
        public HoverExitWitness HoverWitness;
        public string HoverExpectedTask, HoverFailure;
        public string[] HoverQueueBefore, HoverQueueAfter;
        public bool HoverTooltipShown, HoverPointerExitEvent, HoverExited, HoverClosedByProbe;
        public bool HoverPageMismatchLogged, HoverUnknownLogged, HoverEvidenceLogged;
    }

    // Probe-only visible frame code for checking whether OBS receives fresh
    // game frames. It is not an agent observation or a production overlay.
    public sealed class FrameMarker : UnityEngine.MonoBehaviour
    {
        public void OnGUI()
        {
            if (!Probe.IsRunning) return;
            UnityEngine.GUI.depth = -10000;
            for (int bit = -2; bit < 16; bit++)
            {
                UnityEngine.GUI.color = bit < 0 ? UnityEngine.Color.magenta :
                    ((UnityEngine.Time.frameCount >> bit) & 1) == 1 ? UnityEngine.Color.white : UnityEngine.Color.black;
                UnityEngine.GUI.DrawTexture(new UnityEngine.Rect(16 + (bit + 2) * 12, 16, 12, 20),
                    UnityEngine.Texture2D.whiteTexture);
            }
            UnityEngine.GUI.color = UnityEngine.Color.white;
        }
    }

    // Records the actual EventSystem exit on the selected inventory row.
    public sealed class HoverExitWitness : UnityEngine.MonoBehaviour, UnityEngine.EventSystems.IPointerExitHandler
    {
        public Action<UnityEngine.EventSystems.PointerEventData> Notify;
        public void OnPointerExit(UnityEngine.EventSystems.PointerEventData eventData)
        {
            if (Notify != null) Notify(eventData);
        }
    }

    internal static class Probe
    {
        private static Run _run;
        private static int _state; // 0 idle, 1 armed, 2 running
        private static bool _registered, _uiStarted, _previousRib, _ribCaptured;
        private static long _lastPoll, _lastHeartbeat;
        private static int _lastFrame;
        private static readonly FieldInfo QueueField = typeof(ThreadTaskQueue).GetField("taskQueue", BindingFlags.Instance | BindingFlags.NonPublic);
        private static readonly FieldInfo StatusCompletionField = typeof(StatusScreensScreen).GetField("menucomplete", BindingFlags.Instance | BindingFlags.NonPublic);
        public static bool IsRunning { get { return Volatile.Read(ref _state) == 2; } }

        private static void Log(object value) { MetricsManager.LogInfo("[R34] " + JsonConvert.SerializeObject(value)); }
        private static double Since(long ticks) { return (Stopwatch.GetTimestamp() - ticks) * 1000.0 / Stopwatch.Frequency; }

        public static void Init()
        {
            if (!_registered)
            {
                XRLCore.RegisterOnEndPlayerTurnCallback(OnEndPlayerTurn);
                XRLCore.RegisterOnBeginPlayerTurnCallback(OnBeginPlayerTurn);
                XRLCore.RegisterNewMessageLogEntryCallback(message =>
                {
                    Run run = _run;
                    if (run != null && IsRunning)
                    {
                        run.LastMessage = message;
                        Log(new { kind = "message", id = run.Id, turn = run.Turn, text = message });
                    }
                });
                _registered = true;
            }
            if (!_uiStarted && GameManager.Instance != null)
            {
                _uiStarted = true;
                GameManager.Instance.uiQueue.queueTask(() =>
                {
                    var go = new UnityEngine.GameObject("R34 frame marker");
                    UnityEngine.Object.DontDestroyOnLoad(go);
                    go.AddComponent<FrameMarker>();
                    UiTick();
                });
            }
            Log(new { kind = "init", assembly = typeof(XRLCore).Assembly.GetName().Version.ToString() });
        }

        private static void UiTick()
        {
            try
            {
                int state = Volatile.Read(ref _state);
                if (state != 0)
                {
                    if (!_ribCaptured)
                    {
                        _previousRib = UnityEngine.Application.runInBackground;
                        _ribCaptured = true;
                    }
                    UnityEngine.Application.runInBackground = true;
                }
                else if (_ribCaptured)
                {
                    UnityEngine.Application.runInBackground = _previousRib;
                    GameManager._focused = UnityEngine.Application.isFocused;
                    _ribCaptured = false;
                }
                Run run = _run;
                if (state == 2 && run != null)
                {
                    if (run.Mode != "hover") AnswerNotice(run);
                    AnswerPicker(run);
                    try { HoverTick(run); }
                    catch (Exception ex)
                    {
                        run.HoverFailure = "HOVER_UI_ERROR";
                        Log(new { kind = "hover_error", id = run.Id, error = ex.ToString() });
                        CloseHoverModal(run);
                    }
                }
                if (state == 2 && run != null && Since(_lastHeartbeat) >= 1000)
                {
                    int frame = UnityEngine.Time.frameCount;
                    Log(new { kind = "heartbeat", id = run.Id, elapsedMs = run.Clock.ElapsedMilliseconds,
                        turn = Interlocked.Read(ref run.Turn), ctas = Interlocked.Read(ref run.Ctas),
                        moves = Interlocked.Read(ref run.Moves), actualFocused = UnityEngine.Application.isFocused,
                        frame, frameDelta = frame - _lastFrame, heartbeatMs = Since(_lastHeartbeat),
                        view = GameManager.Instance.CurrentGameView,
                        playerTurnEntries = run.PlayerTurnEntries, endPlayerTurns = run.EndPlayerTurns });
                    _lastHeartbeat = Stopwatch.GetTimestamp();
                    _lastFrame = frame;
                }
            }
            catch (Exception ex) { Log(new { kind = "ui_error", error = ex.ToString() }); }
            finally { GameManager.Instance.uiQueue.queueTask(UiTick); }
        }

        // This probe accepts only an informational popup with one Accept button.
        // Any choice or text input remains visible for diagnosis.
        private static void AnswerNotice(Run run)
        {
            if (UIManager.instance == null) return;
            PopupMessage popup = null;
            foreach (var pair in UIManager.instance.windowsByName)
            {
                var candidate = pair.Value as PopupMessage;
                if (candidate == null || candidate.onHide == null || !candidate.gameObject.activeSelf ||
                    (candidate.canvasGroup != null && !candidate.canvasGroup.interactable)) continue;
                if (popup != null) return; // Multiple live windows require a full ModalDriver.
                popup = candidate;
            }
            if (popup == null || popup.commandCallback == null || popup.controller == null ||
                (popup.inputBox != null && popup.inputBox.gameObject.activeSelf)) return;
            var items = new List<QudMenuItem>();
            if (popup.controller.menuData != null) items.AddRange(popup.controller.menuData);
            if (popup.controller.bottomContextOptions != null) items.AddRange(popup.controller.bottomContextOptions);
            if (items.Count != 1 || items[0].command != "Accept" || items[0].text == null) return;
            object token = popup.onHide;
            string message = popup.Message == null ? null : popup.Message.text;
            popup.OnActivateCommand(items[0]);
            bool accepted = !ReferenceEquals(token, popup.onHide);
            if (accepted) run.PopupAnswers++;
            Log(new { kind = "popup_response", id = run.Id, message, accepted, command = items[0].command });
        }

        private static void AnswerPicker(Run run)
        {
            if (Volatile.Read(ref run.PickerIndex) == 0) return;
            bool focused = UnityEngine.Application.isFocused;
            if (run.PickerFocus.HasValue && run.PickerFocus.Value != focused) run.PickerFocusChanges++;
            run.PickerFocus = focused;
            GameManager gm = GameManager.Instance;
            if (gm.CurrentGameView != "PickTarget" || PickTargetWindow.currentMode != PickTargetWindow.TargetMode.PickDirection ||
                gm._ActiveGameView != gm.CurrentGameView || gm.bViewUpdated || !XRLCore.bThreadFocus ||
                Keyboard.KeyQueue.Count != 0 || Keyboard.HasMouseEvent() ||
                Since(run.PickerStart) < 1500 || Since(run.LastPickerPush) < 250) return;
            if (ProbePolicy.DiscardPickerAttempt(run.DropFirstPickerPush, run.PickerAttempts))
            {
                run.PickerAttempts++;
                run.PickerSimulatedDrops++;
                run.LastPickerPush = Stopwatch.GetTimestamp();
                Log(new { kind = "picker_drop_simulated", id = run.Id, seq = run.PickerIndex,
                    attempt = run.PickerAttempts, beforeEnqueue = true,
                    actualFocused = focused, focusChanges = run.PickerFocusChanges });
                return;
            }
            UnityEngine.KeyCode key = Since(run.PickerStart) > 10000 ? UnityEngine.KeyCode.Escape : UnityEngine.KeyCode.Keypad6;
            Keyboard.PushKey(key);
            run.LastPickerPush = Stopwatch.GetTimestamp(); run.PickerAttempts++; run.PickerPushes++;
            Log(new { kind = "picker_push", id = run.Id, seq = run.PickerIndex,
                attempt = run.PickerAttempts, key = key.ToString(), actualFocused = focused,
                focusChanges = run.PickerFocusChanges, simulatedLoss = run.DropFirstPickerPush });
        }

        private static string[] PendingGameTaskIds()
        {
            if (QueueField == null) throw new MissingFieldException("ThreadTaskQueue.taskQueue");
            var pending = QueueField.GetValue(GameManager.Instance.gameQueue) as Queue<ThreadTaskQueueEntry>;
            if (pending == null) throw new InvalidOperationException("gameQueue.taskQueue unavailable");
            lock (pending)
            {
                var ids = new string[pending.Count];
                int index = 0;
                foreach (ThreadTaskQueueEntry entry in pending) ids[index++] = entry.TaskID;
                return ids;
            }
        }

        private static bool HoverPoint(InventoryLine line, out UnityEngine.Vector2 screen)
        {
            screen = default(UnityEngine.Vector2);
            var rect = line.transform as UnityEngine.RectTransform;
            var canvas = UIManager.mainCanvas;
            if (rect == null || canvas == null || !line.gameObject.activeInHierarchy ||
                line.itemMode == null || !line.itemMode.activeSelf || line.tooltipGo == null) return false;
            var corners = new UnityEngine.Vector3[4];
            rect.GetWorldCorners(corners);
            var camera = canvas.renderMode == UnityEngine.RenderMode.ScreenSpaceOverlay ? null : canvas.worldCamera;
            screen = UnityEngine.RectTransformUtility.WorldToScreenPoint(camera, (corners[0] + corners[2]) * 0.5f);
            if (screen.x < 8 || screen.y < 8 || screen.x > UnityEngine.Screen.width - 8 ||
                screen.y > UnityEngine.Screen.height - 8) return false;
            var scroller = line.GetComponentInParent<UnityEngine.UI.ScrollRect>();
            if (scroller != null && scroller.viewport != null &&
                !UnityEngine.RectTransformUtility.RectangleContainsScreenPoint(scroller.viewport, screen, camera)) return false;
            return UnityEngine.RectTransformUtility.RectangleContainsScreenPoint(rect, screen, camera);
        }

        private static void HoverTick(Run run)
        {
            if (run.Mode != "hover") return;
            var status = StatusScreensScreen.instance;
            if (run.HoverWindow == null)
            {
                if (status == null || !status.gameObject.activeInHierarchy ||
                    GameManager.Instance.CurrentGameView != "StatusScreensScreen" ||
                    StatusScreensScreen.GO != The.Player)
                {
                    if (!run.HoverUnknownLogged && run.Clock.Elapsed.TotalSeconds >= run.Seconds)
                    {
                        run.HoverUnknownLogged = true;
                        Log(new { kind = "hover_status_unknown", id = run.Id,
                            elapsedMs = run.Clock.ElapsedMilliseconds,
                            view = GameManager.Instance.CurrentGameView });
                    }
                    return;
                }
                if (StatusCompletionField == null) throw new MissingFieldException("StatusScreensScreen.menucomplete");
                var completion = StatusCompletionField.GetValue(status) as TaskCompletionSource<ScreenReturn>;
                if (completion == null || completion.Task.IsCompleted) return;
                // The active status view and its pending completion source identify this probe's modal.
                run.HoverWindow = status;
                run.HoverCompletion = completion;
                Log(new { kind = "hover_status_open", id = run.Id, elapsedMs = run.Clock.ElapsedMilliseconds,
                    view = GameManager.Instance.CurrentGameView, currentPage = status.CurrentScreen,
                    pending = true });
            }
            if (run.HoverCompletion.Task.IsCompleted)
            {
                if (run.HoverWitness != null)
                {
                    run.HoverWitness.Notify = null;
                    UnityEngine.Object.Destroy(run.HoverWitness);
                    run.HoverWitness = null;
                }
                return;
            }
            if (!ReferenceEquals(status, run.HoverWindow) ||
                !ReferenceEquals(StatusCompletionField.GetValue(status), run.HoverCompletion)) return;

            if (status.CurrentScreen != 2 && !run.HoverPageMismatchLogged)
            {
                run.HoverPageMismatchLogged = true;
                run.HoverFailure = "HOVER_PAGE_CHANGED";
                Log(new { kind = "hover_page_mismatch", id = run.Id,
                    elapsedMs = run.Clock.ElapsedMilliseconds, currentPage = status.CurrentScreen });
            }
            if (run.HoverLine == null && status.CurrentScreen == 2)
            {
                foreach (InventoryLine line in status.GetComponentsInChildren<InventoryLine>(false))
                {
                    UnityEngine.Vector2 point;
                    if (!HoverPoint(line, out point)) continue;
                    string expected = "LookedAt" + line.tooltipGo.GetHashCode();
                    string[] initialTasks = PendingGameTaskIds();
                    if (Array.IndexOf(initialTasks, expected) >= 0) continue;
                    run.HoverLine = line;
                    run.HoverExpectedTask = expected;
                    run.HoverWitness = line.gameObject.AddComponent<HoverExitWitness>();
                    run.HoverWitness.Notify = pointer =>
                    {
                        if (!run.HoverTooltipShown || run.HoverPointerExitEvent || run.HoverExited)
                        {
                            Log(new { kind = "hover_pointer_exit_diagnostic", id = run.Id,
                                reason = !run.HoverTooltipShown ? "before_tooltip" :
                                    run.HoverExited ? "after_observed" : "duplicate",
                                elapsedMs = run.Clock.ElapsedMilliseconds,
                                frame = UnityEngine.Time.frameCount,
                                pointerX = pointer.position.x, pointerY = pointer.position.y,
                                actualFocused = UnityEngine.Application.isFocused });
                            return;
                        }
                        run.HoverPointerExitEvent = true;
                        Log(new { kind = "hover_pointer_exit_event", id = run.Id,
                            elapsedMs = run.Clock.ElapsedMilliseconds, frame = UnityEngine.Time.frameCount,
                            pointerX = pointer.position.x, pointerY = pointer.position.y,
                            actualFocused = UnityEngine.Application.isFocused });
                    };
                    // Unity coordinates are bottom-left client pixels; the pointer helper must
                    // convert client top-left fractions using the native title-bar bounds.
                    Log(new { kind = "hover_target", id = run.Id,
                        name = line.tooltipGo.DisplayNameOnlyStripped,
                        objectHash = line.tooltipGo.GetHashCode(), expectedTaskId = expected,
                        unityX = point.x, unityY = point.y,
                        screenWidth = UnityEngine.Screen.width, screenHeight = UnityEngine.Screen.height,
                        clientX = point.x / UnityEngine.Screen.width,
                        clientYTop = 1f - point.y / UnityEngine.Screen.height,
                        actualFocused = UnityEngine.Application.isFocused,
                        initialQueueTaskIds = initialTasks });
                    break;
                }
            }

            InventoryLine target = run.HoverLine;
            if (target != null && !run.HoverTooltipShown && target.Inside && target.tooltip != null &&
                target.tooltip.onHideAction != null && target.tooltip.Tooltip != null &&
                target.tooltip.Tooltip.GameObject.activeInHierarchy)
            {
                run.HoverQueueBefore = PendingGameTaskIds();
                run.HoverPointerExitEvent = false;
                run.HoverTooltipShown = true;
                Log(new { kind = "hover_before_exit", id = run.Id,
                    elapsedMs = run.Clock.ElapsedMilliseconds, tooltipShown = true,
                    pointerInside = target.Inside, actualFocused = UnityEngine.Application.isFocused,
                    mouseX = UnityEngine.Input.mousePosition.x, mouseY = UnityEngine.Input.mousePosition.y,
                    expectedTaskId = run.HoverExpectedTask, queueTaskIds = run.HoverQueueBefore });
            }
            if (target != null && run.HoverTooltipShown && run.HoverPointerExitEvent && !run.HoverExited &&
                status.CurrentScreen == 2 && target.gameObject.activeInHierarchy &&
                !target.Inside && target.tooltip == null &&
                !UnityEngine.RectTransformUtility.RectangleContainsScreenPoint(
                    target.transform as UnityEngine.RectTransform, UnityEngine.Input.mousePosition,
                    UIManager.mainCanvas.renderMode == UnityEngine.RenderMode.ScreenSpaceOverlay ? null : UIManager.mainCanvas.worldCamera))
            {
                run.HoverQueueAfter = PendingGameTaskIds();
                run.HoverExited = true;
                Log(new { kind = "hover_after_exit", id = run.Id,
                    elapsedMs = run.Clock.ElapsedMilliseconds, pointerInside = false,
                    pointerExitEvent = run.HoverPointerExitEvent,
                    actualFocused = UnityEngine.Application.isFocused,
                    mouseX = UnityEngine.Input.mousePosition.x, mouseY = UnityEngine.Input.mousePosition.y,
                    expectedTaskId = run.HoverExpectedTask, queueTaskIds = run.HoverQueueAfter,
                    taskNewlyQueued = ProbePolicy.NewTaskAppeared(run.HoverQueueBefore, run.HoverQueueAfter, run.HoverExpectedTask) });
            }

            if (run.Clock.Elapsed.TotalSeconds < run.Seconds || run.HoverClosedByProbe) return;
            bool queued = run.HoverExited && ProbePolicy.NewTaskAppeared(
                run.HoverQueueBefore, run.HoverQueueAfter, run.HoverExpectedTask);
            if (run.HoverFailure == null)
                run.HoverFailure = !run.HoverTooltipShown ? "HOVER_NO_TOOLTIP" :
                    !run.HoverExited ? "HOVER_NO_POINTER_EXIT" :
                    !queued ? "HOVER_TASK_NOT_NEWLY_QUEUED" : null;
            if (!run.HoverEvidenceLogged)
            {
                run.HoverEvidenceLogged = true;
                Log(new { kind = "hover_evidence", id = run.Id, elapsedMs = run.Clock.ElapsedMilliseconds,
                    tooltipShown = run.HoverTooltipShown, pointerExitObserved = run.HoverExited,
                    expectedTaskId = run.HoverExpectedTask, taskNewlyQueued = queued,
                    queueBefore = run.HoverQueueBefore, queueAfter = run.HoverQueueAfter,
                    pass = run.HoverFailure == null, failure = run.HoverFailure });
            }
            CloseHoverModal(run);
        }

        private static void CloseHoverModal(Run run)
        {
            try
            {
                StatusScreensScreen status = run.HoverWindow;
                if (status == null || run.HoverCompletion == null || run.HoverClosedByProbe ||
                    !ReferenceEquals(StatusScreensScreen.instance, status) ||
                    !ReferenceEquals(StatusCompletionField.GetValue(status), run.HoverCompletion) ||
                    run.HoverCompletion.Task.IsCompleted || !status.gameObject.activeInHierarchy ||
                    GameManager.Instance.CurrentGameView != "StatusScreensScreen") return;
                run.HoverClosedByProbe = true;
                if (run.HoverWitness != null)
                {
                    run.HoverWitness.Notify = null;
                    UnityEngine.Object.Destroy(run.HoverWitness);
                    run.HoverWitness = null;
                }
                status.Exit();
            }
            catch (Exception ex)
            {
                if (run.HoverCompletion != null && !run.HoverCompletion.Task.IsCompleted)
                    run.HoverClosedByProbe = false;
                run.HoverFailure = "HOVER_CLOSE_ERROR";
                Log(new { kind = "hover_close_error", id = run.Id, error = ex.ToString() });
            }
        }

        private static void OnBeginPlayerTurn(XRLCore core)
        {
            Run run = _run;
            if (!IsRunning || run == null) return;
            // AutoAct also invokes this callback. Inspect the current game-thread
            // stack to distinguish it from PlayerTurn before its focus wait.
            foreach (StackFrame frame in new StackTrace(false).GetFrames())
            {
                var method = frame.GetMethod();
                if (method.DeclaringType == typeof(XRLCore) && method.Name == "PlayerTurn")
                {
                    run.PlayerTurnEntries++;
                    Log(new { kind = "player_turn_entered", id = run.Id, turn = The.Game.Turns });
                    break;
                }
            }
        }

        private static void OnEndPlayerTurn(XRLCore core)
        {
            if (Volatile.Read(ref _state) == 0) PollControl();
            Run run = _run;
            if (run == null) return;
            if (IsRunning) run.EndPlayerTurns++;
            The.ActionManager.SkipPlayerTurn = true;
            Keyboard.KeyEvent.Set();
        }

        private static void PollControl()
        {
            if (Since(_lastPoll) < 250) return;
            _lastPoll = Stopwatch.GetTimestamp();
            string path = DataManager.SavePath("r34-command.json");
            if (!File.Exists(path)) return;
            string raw = File.ReadAllText(path);
            File.Delete(path);
            try
            {
                JObject request = JObject.Parse(raw);
                string mode = (string)request["mode"];
                if (mode == "stop" && _run != null) { _run.StopRequested = true; return; }
                if (_run != null) throw new InvalidOperationException("An R34 run is already active");
                if (mode != "r3" && mode != "r4" && mode != "picker" && mode != "hover")
                    throw new ArgumentException("mode must be r3, r4, picker or hover");
                int seconds = (int?)request["seconds"] ?? 60;
                int turns = (int?)request["turns"] ?? 500;
                bool dropFirst = (bool?)request["dropFirstPickerPush"] ?? false;
                if (dropFirst && mode != "picker") throw new ArgumentException("dropFirstPickerPush is picker-only");
                if (seconds < 10 || seconds > 3600 || turns < 10 || turns > 5000)
                    throw new ArgumentException("seconds 10..3600 and turns 10..5000 required");
                if (mode == "hover" && seconds > 60)
                    throw new ArgumentException("hover seconds 10..60 required");
                if (The.Player == null || The.Player.CurrentCell == null)
                    throw new InvalidOperationException("Live player required");
                _run = new Run { Id = (string)request["id"] ?? Guid.NewGuid().ToString(),
                    Mode = mode, Focus = (string)request["focus"] ?? "focused", Seconds = seconds,
                    TargetTurns = turns, DropFirstPickerPush = dropFirst };
                The.Game.RequireSystem<ProbeSystem>();
                Keyboard.ClearInput();
                Volatile.Write(ref _state, 1);
                Run captured = _run;
                var thread = new Thread(() => MaintainFocus(captured)) { IsBackground = true, Name = "R34 focus bridge" };
                thread.Start();
                Log(new { kind = "armed", id = _run.Id, mode, seconds, turns, focus = _run.Focus,
                    dropFirstPickerPush = dropFirst });
            }
            catch (Exception ex) { Log(new { kind = "control_error", error = ex.ToString() }); }
        }

        private static void MaintainFocus(Run run)
        {
            while (ReferenceEquals(_run, run) && Volatile.Read(ref _state) != 0)
            {
                XRLCore.bThreadFocus = true;
                GameManager._focused = true;
                GameManager.focusedEvent.Set();
                Thread.Sleep(100);
            }
        }

        public static bool OnCta()
        {
            Run run = _run;
            if (run == null) return true;
            try
            {
                Cell cell = The.Player.CurrentCell;
                if (Volatile.Read(ref _state) == 1)
                {
                    run.Zone = cell.ParentZone.ZoneID; run.TurnStart = run.Turn = The.Game.Turns;
                    run.X = cell.X; run.Y = cell.Y; run.StartHp = The.Player.Stat("Hitpoints");
                    run.AnchorX = cell.X; run.AnchorY = cell.Y;
                    if (run.Mode == "r3" || run.Mode == "r4") SelectOtherAnchor(run, cell);
                    if (run.Mode == "r3")
                    {
                        run.Stomach = The.Player.GetPart<XRL.World.Parts.Stomach>();
                        if (run.Stomach != null)
                        {
                            run.SavedWater = run.Stomach.Water;
                            run.SavedCookingCounter = run.Stomach.CookingCounter;
                            run.SavedWorldMap = run.Stomach.WasOnWorldMap;
                            run.Stomach.ClearHunger();
                        }
                    }
                    run.Clock.Start(); _lastHeartbeat = Stopwatch.GetTimestamp();
                    Volatile.Write(ref _state, 2);
                    Log(new { kind = "begin", id = run.Id, mode = run.Mode, focus = run.Focus,
                        seconds = run.Seconds, targetTurns = run.TargetTurns, turn = run.TurnStart,
                        zone = run.Zone, x = cell.X, y = cell.Y, hp = run.StartHp,
                        otherX = run.OtherX, otherY = run.OtherY,
                        autoexploreRate = Options.AutoexploreRate,
                        sustenanceFixture = run.Stomach != null,
                        dropFirstPickerPush = run.DropFirstPickerPush });
                    if (run.Mode == "picker")
                    {
                        for (int i = 1; i <= 10; i++)
                        {
                            run.PickerPushes = 0; run.PickerAttempts = 0; run.PickerSimulatedDrops = 0;
                            run.PickerFocusChanges = 0; run.PickerFocus = null;
                            run.PickerStart = Stopwatch.GetTimestamp(); run.LastPickerPush = 0;
                            Volatile.Write(ref run.PickerIndex, i);
                            string answer = PickDirection.ShowPicker("R3 focus transition " + i);
                            Volatile.Write(ref run.PickerIndex, 0);
                            Log(new { kind = "picker_result", id = run.Id, seq = i, expected = "E", actual = answer,
                                attempts = run.PickerAttempts, pushes = run.PickerPushes,
                                simulatedDrops = run.PickerSimulatedDrops,
                                focusChanges = run.PickerFocusChanges,
                                elapsedMs = Since(run.PickerStart), simulatedLoss = run.DropFirstPickerPush,
                                pass = answer == "E" && (!run.DropFirstPickerPush ||
                                    (run.PickerSimulatedDrops == 1 && run.PickerPushes >= 1)) });
                            if (answer != "E" || (run.DropFirstPickerPush &&
                                (run.PickerSimulatedDrops != 1 || run.PickerPushes < 1)))
                                return Finish(run, "PICKER_WRONG_ANSWER");
                        }
                        return Finish(run, "COMPLETE");
                    }
                    if (run.Mode == "hover")
                    {
                        if (!Options.ModernUI || !Options.ModernCharacterSheet ||
                            GameManager.Instance.CurrentGameView != "Stage")
                            return Finish(run, "HOVER_NOT_MODERN_STAGE");
                        int priorScreen = Screens.CurrentScreen;
                        try
                        {
                            Screens.CurrentScreen = 2;
                            Screens.Show(The.Player); // Synchronous game-thread wait; UI tick observes the modal.
                        }
                        finally
                        {
                            Screens.CurrentScreen = priorScreen;
                            HoverExitWitness witness = run.HoverWitness;
                            if (witness != null)
                                GameManager.Instance.uiQueue.queueTask(() =>
                                {
                                    if (witness != null)
                                    {
                                        witness.Notify = null;
                                        UnityEngine.Object.Destroy(witness);
                                    }
                                });
                        }
                        return Finish(run, run.HoverClosedByProbe && run.HoverFailure == null ?
                            "COMPLETE" : (run.HoverFailure ?? "HOVER_CLOSED_EXTERNALLY"));
                    }
                }
                PollControl();
                if (run.Stomach != null)
                {
                    run.Stomach.CookingCounter = 0;
                    run.Stomach.Water = 30000;
                }
                run.Ctas++;
                Interlocked.Exchange(ref run.Turn, The.Game.Turns);
                if (cell.X != run.X || cell.Y != run.Y) Interlocked.Increment(ref run.Moves);
                run.X = cell.X; run.Y = cell.Y;
                long turns = run.Turn - run.TurnStart;
                string finish = null;
                if (run.StopRequested) finish = "STOP_REQUESTED";
                else if (run.PlayerTurnEntries > 0 || run.EndPlayerTurns > 0) finish = "PLAYER_TURN_LEAK";
                else if (cell.ParentZone.ZoneID != run.Zone) finish = "ZONE_CHANGED";
                else if (The.Player.Stat("Hitpoints") < run.StartHp) finish = "HP_LOSS";
                else if (AutoAct.ShouldHostilesInterrupt()) finish = "HOSTILE";
                else if (run.Ctas > 1000000) finish = "CTA_BUDGET";
                else if (run.Mode == "r4" && turns >= run.TargetTurns) finish = "COMPLETE";
                else if (run.Mode == "r3" && run.Clock.Elapsed.TotalSeconds >= run.Seconds) finish = "COMPLETE";
                else if (run.Mode == "r4" && run.Clock.Elapsed.TotalSeconds > 600) finish = "WALL_TIMEOUT";
                if (finish != null) return Finish(run, finish);

                if (run.Macro != null)
                {
                    string reason = run.Macro.Observe(run.Turn, cell.X, cell.Y, AutoAct.IsActive());
                    if (reason != null) FinishMacro(run, reason);
                }
                if (run.Macro == null) StartMacro(run, cell);
                // ActionManager.cs:1584 consumes this only after AutoAct stops.
                // Reassert it on every delegation, including the starting CTA.
                The.ActionManager.SkipPlayerTurn = true;
                return true;
            }
            catch (Exception ex)
            {
                Log(new { kind = "game_error", id = run.Id, error = ex.ToString() });
                return Finish(run, "EXCEPTION");
            }
        }

        private static void SelectOtherAnchor(Run run, Cell cell)
        {
            foreach (int direction in new[] { 1, -1 })
            {
                int target = cell.X + direction * 4;
                if (target < 1 || target > 78) continue;
                bool clear = true;
                for (int step = 1; step <= 4; step++)
                {
                    Cell candidate = cell.ParentZone.GetCell(cell.X + direction * step, cell.Y);
                    if (candidate.IsSolidFor(The.Player) || candidate.HasObjectWithPart("LiquidVolume")) clear = false;
                }
                if (clear) { run.OtherX = target; run.OtherY = cell.Y; return; }
            }
            throw new InvalidOperationException("No four-cell test corridor near starting cell");
        }

        private static void StartMacro(Run run, Cell cell)
        {
            int index = run.Decisions++;
            string kind = run.Mode == "r3" ? "goto" : new[] { "explore", "goto", "rest", "rest" }[index % 4];
            int x = -1, y = -1, budget = kind == "explore" ? 40 : 30;
            string setting;
            if (kind == "goto")
            {
                bool atAnchor = cell.X == run.AnchorX && cell.Y == run.AnchorY;
                x = atAnchor ? run.OtherX : run.AnchorX;
                y = atAnchor ? run.OtherY : run.AnchorY;
                setting = "M" + x + "," + y;
            }
            else if (kind == "explore") setting = "?"; // XRLCore.PlayerTurn CmdAutoExplore.
            else setting = index % 4 == 3 ? "r" : ".20";
            run.Macro = new MacroProgress(kind, run.Turn, cell.X, cell.Y, budget, x, y);
            run.MacroDecision = index + 1; run.MacroMoves = run.Moves; run.LastMessage = null;
            AutoAct.ClearAutoMoveStop();
            AutoAct.Setting = setting;
            Log(new { kind = "decision", id = run.Id, seq = run.MacroDecision,
                action = kind, setting, turn = run.Turn, x = cell.X, y = cell.Y, targetX = x, targetY = y });
            if (kind == "rest")
            {
                // XRLCore.PlayerTurn CmdWait20/CmdWaitUntilHealed, 2.0.211.56.
                if (setting == "r")
                {
                    The.ActionManager.RestingUntilHealed = true;
                    The.ActionManager.RestingUntilHealedCount = 0;
                }
                The.Player.PassTurn();
            }
        }

        private static void FinishMacro(Run run, string reason)
        {
            MacroProgress macro = run.Macro;
            string engineReason = GameObject.AutomoveInterruptBecause;
            if (AutoAct.IsActive()) AutoAct.Interrupt();
            Log(new { kind = "macro_result", id = run.Id, seq = run.MacroDecision,
                action = macro.Kind, reason, engineReason, message = run.LastMessage,
                turnStart = macro.StartTurn, turnEnd = run.Turn, turns = run.Turn - macro.StartTurn,
                moves = run.Moves - run.MacroMoves, x = run.X, y = run.Y });
            run.Macro = null;
        }

        private static bool Finish(Run run, string reason)
        {
            if (run.Macro != null) FinishMacro(run, reason == "COMPLETE" ? "RUN_BUDGET" : reason);
            if (run.Stomach != null)
            {
                run.Stomach.Water = run.SavedWater;
                run.Stomach.CookingCounter = run.SavedCookingCounter;
                run.Stomach.WasOnWorldMap = run.SavedWorldMap;
            }
            Log(new { kind = "result", id = run.Id, mode = run.Mode, focus = run.Focus,
                reason, elapsedMs = run.Clock.ElapsedMilliseconds,
                turnStart = run.TurnStart, turnEnd = run.Turn, turns = run.Turn - run.TurnStart,
                moves = run.Moves, ctas = run.Ctas, decisions = run.Decisions,
                popupAnswers = run.PopupAnswers,
                playerTurnEntries = run.PlayerTurnEntries, endPlayerTurns = run.EndPlayerTurns,
                pass = reason == "COMPLETE" && run.PlayerTurnEntries == 0 && run.EndPlayerTurns == 0 });
            Volatile.Write(ref _state, 0); _run = null;
            The.ActionManager.SkipPlayerTurn = false;
            return true;
        }
    }
}
