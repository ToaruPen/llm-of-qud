// R5 runtime probe: Modern-UI modal driver (DRAFT - not built, not deployed, not run).
//
// Purpose: verify at runtime, without Harmony, that a background "bridge" thread can
//   (a) detect which Modern-UI modal the game thread is blocked in,
//   (b) read it as legacy-equivalent text, and
//   (c) answer it through GameManager.uiQueue so that the game thread resumes with the
//       intended value and the view stack is restored.
//
// Rules implemented here (from docs/exploration/modal-verification F1-F7):
//   - Every modal is opened ON THE GAME THREAD by a wish (C-F6-threads-hooks-21).
//   - The answerer thread is armed before the modal opens and starts after ~1500 ms.
//   - Unity objects are only touched inside UI-thread work (C-F1-popup-17).
//   - Hide() is NEVER called first (C-F1-popup-05, C-F1-popup-06, C-F2-conversation-21), except once, on purpose,
//     by probe:cancel (R5-0d) to observe the async-void cancel path.
//   - Each answer is guarded by a token (onHide / commandCallback / protected menucomplete / tutorial PopupCompletion)
//     that is re-checked inside the UI task that answers, plus a global answered-token set.
//   - All log lines go through MetricsManager.LogInfo with the prefix "[R5]".
//   - R5-0 gate probes (cancel / focus / offthread / reload, plus ctl= in "tick alive") run before
//     the family probes; see README section 10.3 and 08 section 6.1.
//
// Source citations are "file:line" in /Users/sankenbisha/Dev/coq-decompiled_stable (2.0.211.56).
// Language level: C# 9 (block-scoped namespace, no global usings, no records).
// No type in this assembly references Harmony, so ModManager does not PatchAll it (C-F6-threads-hooks-23).

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using ConsoleLib.Console;
using Qud.UI;
using XRL;
using XRL.Core;
using XRL.UI;
using XRL.Wish;
using XRL.World;
using XRL.World.Capabilities;
using XRL.World.Parts;

namespace LlmOfQud.ProbeR5
{
    // ------------------------------------------------------------------------------------------
    // Bootstrap: seeds the UI tick. [ModSensitiveCacheInit] methods are invoked by
    // ModManager.ResetModSensitiveStaticCaches (XRL/ModManager.cs:340-372); attributes at
    // XRL/HasModSensitiveStaticCacheAttribute.cs:7 and XRL/ModSensitiveCacheInitAttribute.cs:6.
    // At startup this runs on the UI thread (C-F6-threads-hooks-18); a hotload may run it on
    // another thread, so seeding is idempotent (generation counter, see Bridge.EnsureTick).
    // ------------------------------------------------------------------------------------------
    [HasModSensitiveStaticCache]
    public static class ProbeBootstrap
    {
        [ModSensitiveCacheInit]
        public static void Init()
        {
            Bridge.Log("init thread=" + Bridge.ThreadTag() + " (ModSensitiveCacheInit)");
            Bridge.EnsureTick("init");
        }
    }

    internal sealed class RefEq : IEqualityComparer<object>
    {
        public static readonly RefEq Instance = new RefEq();
        bool IEqualityComparer<object>.Equals(object a, object b) { return ReferenceEquals(a, b); }
        int IEqualityComparer<object>.GetHashCode(object o) { return RuntimeHelpers.GetHashCode(o); }
    }

    internal sealed class UiGate
    {
        public volatile bool Abandoned;
    }

    // Snapshot built on the UI thread by Bridge.Classify(); the bridge only reads this object.
    internal sealed class Snap
    {
        public string Kind = "none"; // tutorial | popup | picker | asknumberscreen | book | pickgameobject | trade | status | *-notready | none
        public string Detail = "";   // legacy-equivalent text
        public string Views = "";
        public string CurrentView = "";
        public bool InConversation;
        public string Hosts = "";    // host views under the top modal (08 section 3.3)
        public long ReadMs;          // UI-thread cost of this Classify() (R5-F7b)
        // tutorial overlay
        public object TutorialToken; // TutorialManager.PopupCompletion reference (TutorialManager.cs:95)
        public bool TutorialLatched; // popupAcceptPressed (TutorialManager.cs:133)
        // popup
        public PopupMessage Pm;
        public string WindowKey;
        public object TokenOnHide;
        public object TokenCommand;
        public object TokenSelect;
        public string PopupID;
        public bool HasInput;
        public string WantsSpecificPrompt;
        public string RestrictChars;
        public int OptionCount;
        public string Title = "";
        public List<string> OptionTexts = new List<string>();
        public List<string> OptionCommands = new List<string>();
        // conversation node (read in the same UI task; option:N == CurrentChoices[N], XRL.UI/ConversationUI.cs:517)
        public string ConvNodeId;
        public object ConvLastChoice;
        public string ConvLastChoiceId;
        public List<object> ConvChoices = new List<object>();
        public List<string> ConvChoiceIds = new List<string>();
        public List<string> ConvChoiceTargets = new List<string>();
        public List<string> ButtonCommands = new List<string>();
        // screens with a protected TaskCompletionSource "menucomplete"
        public object TcsToken;
        // pickers
        public PickTargetWindow.TargetMode Mode;
        public bool PGate;
        public bool InputEmpty;
        public string PickerText = "";
    }

    internal sealed class ProbeRun
    {
        public string Name;
        public volatile bool ModalReturned;
        public volatile bool Finished;   // target answer accepted; stop answering
        public volatile bool Dead;       // timed out; every later UI closure is a no-op
        public int AnswerCount;
        public int BlockedDoubleAnswers;
        public int Step;                 // picker step counter
        public int TargetMatches;        // times the target predicate matched (0 => the probe never recognised its modal)
        public Thread Thread;
        public string Note = "";
        // conversation node verification (08 R5-F2a)
        public object PendingToken;      // onHide token of the node we answered with an option
        public object PendingChoice;     // CurrentChoices[k] we chose (null = Cancel)
        public string PendingChoiceId;
        public int NodeChecksOk;
        public int NodeChecksBad;
        // tutorial overlay
        public int TutorialWaitPolls;
        public bool TutorialIsTarget;    // probe:tutorial only: the overlay IS the target (set by Arm before the thread starts)
        // stale-token probe
        public Snap Saved;
        public string StaleOutcome;
        // R5-F7b
        public long MaxReadMs;
    }

    // ------------------------------------------------------------------------------------------
    // Bridge: UI tick, UI-thread execution with timeout, classification, logging.
    // ------------------------------------------------------------------------------------------
    internal static class Bridge
    {
        // Not [ModSensitiveStaticCache]: survives ResetModSensitiveStaticCaches (XRL/ModManager.cs:345-358).
        private static readonly ConcurrentQueue<Action> UiWork = new ConcurrentQueue<Action>();
        private static int _tickGen;
        private static long _lastTickUtc;
        private static int _tickFrames;
        private static int _lastTickFrame = -1;   // UnityEngine.Time.frameCount of the last live tick (UI thread only)
        private static int _dupTicks;             // live ticks that ran twice in one frame (two chains = double answers)
        private static volatile bool _forceThreadFocus; // probe:focus:force only (08 section 3.8)
        private static volatile bool _forceFocused;     // probe:focus:play only: the field GameManager._focused rewritten each tick
        private static int _focusRewrites;              // ticks that found GameManager._focused == false and rewrote it (focus:play)
        private static volatile string _lastAppFocused = "?"; // UnityEngine.Application.isFocused as last seen by the tick
        private static volatile string _lastRib = "?";    // Application.runInBackground as last seen by the tick
        private static volatile string _lastPPrime = "?"; // P' as last evaluated by the tick
        private static readonly object AnsweredLock = new object();
        private static readonly HashSet<object> AnsweredTokens = new HashSet<object>(RefEq.Instance);

        // MetricsManager.LogInfo(string) -> UnityEngine.Debug.Log("INFO - " + Message) (MetricsManager.cs:411-414).
        public static void Log(string msg)
        {
            try { MetricsManager.LogInfo("[R5] " + msg); } catch { }
        }

        public static void Log(ProbeRun run, string msg)
        {
            Log("[" + run.Name + "][" + ThreadTag() + "] " + msg);
        }

        public static string ThreadTag()
        {
            try
            {
                Thread t = Thread.CurrentThread;
                if (XRLCore.CoreThread != null && ReferenceEquals(t, XRLCore.CoreThread)) return "game"; // XRL.Core/XRLCore.cs:300
                GameManager gm = GameManager.Instance;                                                   // GameManager.cs:142
                if (gm != null && ReferenceEquals(t, gm.uiQueue.threadContext)) return "ui";             // QupKit/ThreadTaskQueue.cs:16, GameManager.cs:868
                return (t.Name ?? "thread") + "#" + t.ManagedThreadId;
            }
            catch { return "?"; }
        }

        // ---------------- UI tick ----------------
        // One self-reposting uiQueue task, queued only from the UI thread, drains UiWork each frame.
        // executeTasks processes only the count present at entry, so a self-repost runs once per frame
        // (QupKit/ThreadTaskQueue.cs:33-42, C-F6-threads-hooks-02). Seeding from the UI thread keeps every
        // taskPool Enqueue/Dequeue of this tick on one thread (QupKit/ThreadTaskQueue.cs:23-26,157-176,
        // C-F6-threads-hooks-05).
        public static bool TickAlive()
        {
            long last = Interlocked.Read(ref _lastTickUtc);
            return last != 0 && DateTime.UtcNow.Ticks - last < TimeSpan.FromSeconds(2).Ticks;
        }

        public static int TickGen { get { return Volatile.Read(ref _tickGen); } }
        public static int TickFrames { get { return Volatile.Read(ref _tickFrames); } }
        public static int DupTicks { get { return Volatile.Read(ref _dupTicks); } }
        public static string LastRib { get { return _lastRib; } }
        public static string LastPPrime { get { return _lastPPrime; } }
        public static bool ForceThreadFocus { get { return _forceThreadFocus; } set { _forceThreadFocus = value; } }
        public static bool ForceFocused { get { return _forceFocused; } set { _forceFocused = value; } }
        public static int FocusRewrites { get { return Volatile.Read(ref _focusRewrites); } }
        public static string LastAppFocused { get { return _lastAppFocused; } }

        public static void EnsureTick(string reason)
        {
            try
            {
                if (TickAlive())
                {
                    // A hotload re-invokes [ModSensitiveCacheInit] in the SAME assembly (XRL.Core/XRLCore.cs:575-577,
                    // XRL/ModManager.cs:340-372), so reason=init while alive is the expected hotload path: no new generation.
                    if (!reason.StartsWith("wish:", StringComparison.Ordinal))
                        Log("tick already alive gen=" + TickGen + " reason=" + reason + " thread=" + ThreadTag() + " (not reseeded)");
                    return;
                }
                GameManager gm = GameManager.Instance;
                if (gm == null)
                {
                    Log("tick seed skipped reason=" + reason + ": GameManager.Instance is null");
                    return;
                }
                int gen = Interlocked.Increment(ref _tickGen);
                bool onUi = GameManager.IsOnUIContext();                     // GameManager.cs:2858-2861
                if (onUi)
                {
                    gm.uiQueue.queueTask(() => Tick(gen));                   // QupKit/ThreadTaskQueue.cs:157
                }
                else
                {
                    SynchronizationContext ui = gm.uiSynchronizationContext; // GameManager.cs:172,869
                    if (ui == null)
                    {
                        Log("tick seed skipped reason=" + reason + ": uiSynchronizationContext is null");
                        return;
                    }
                    // Post to the Unity context captured at GameManager.cs:869 (C-F6-threads-hooks-26, established).
                    ui.Post(_ => GameManager.Instance.uiQueue.queueTask(() => Tick(gen)), null);
                }
                Log("tick seeded gen=" + gen + " onUI=" + onUi + " reason=" + reason + " thread=" + ThreadTag());
            }
            catch (Exception e)
            {
                Log("tick seed failed reason=" + reason + ": " + e);
            }
        }

        private static void Tick(int gen)
        {
            if (gen != Volatile.Read(ref _tickGen))
            {
                Log("tick gen=" + gen + " retired (current gen=" + Volatile.Read(ref _tickGen) + ")");
                return;
            }
            try
            {
                Interlocked.Exchange(ref _lastTickUtc, DateTime.UtcNow.Ticks);
                int frame = UnityEngine.Time.frameCount;
                if (frame == _lastTickFrame) Interlocked.Increment(ref _dupTicks); // a second live chain (R5-0a)
                _lastTickFrame = frame;
                if (_forceThreadFocus && !XRLCore.bThreadFocus) XRLCore.bThreadFocus = true; // probe:focus:force only (08 section 3.8)
                // probe:focus:play only: write the FIELD GameManager._focused (GameManager.cs:118), never the property: its setter
                // runs Keyboard.ClearInput() + ClearMouseEvents() on a false->true change (GameManager.cs:404-418). PlayerTurn waits
                // while it is false (XRL.Core/XRLCore.cs:737-740); OnApplicationFocus(false) clears it through the setter
                // (GameManager.cs:1920-1924). The counter shows the rewrite actually had something to undo.
                if (_forceFocused && !GameManager._focused)
                {
                    GameManager._focused = true;
                    Interlocked.Increment(ref _focusRewrites);
                }
                _lastAppFocused = UnityEngine.Application.isFocused.ToString();
                GameManager gmt = GameManager.Instance;
                _lastRib = UnityEngine.Application.runInBackground.ToString();
                _lastPPrime = (gmt._ActiveGameView == gmt.CurrentGameView && !gmt.bViewUpdated && XRLCore.bThreadFocus).ToString();
                if (Interlocked.Increment(ref _tickFrames) == 1)
                {
                    // Application.runInBackground follows OptionMusicBackground (C-F6-threads-hooks-10).
                    // ctl= is logged here, before any operator input, for R5-0c (default Mouse, ControlManager.cs:337).
                    Log("tick alive gen=" + gen + " thread=" + ThreadTag()
                        + " ctl=" + ControlManager._activeControllerType      // ControlManager.cs:337
                        + " runInBackground=" + UnityEngine.Application.runInBackground
                        + " focused=" + GameManager.focused                // GameManager.cs:404
                        + " bThreadFocus=" + XRLCore.bThreadFocus);        // XRL.Core/XRLCore.cs:223
                }
                int n = 0;
                Action a;
                while (n < 32 && UiWork.TryDequeue(out a))
                {
                    n++;
                    try { a(); }
                    catch (Exception e) { Log("UI work threw: " + e); }
                }
            }
            finally
            {
                GameManager.Instance.uiQueue.queueTask(() => Tick(gen));
            }
        }

        // ---------------- run on UI with timeout ----------------
        // Primary transport: the tick. Fallback (tick stale): one Post to gm.uiSynchronizationContext, the same route
        // EnsureTick uses and the one 08 section 3.1 allows (The.UiContext is this field, XRL/The.cs:41).
        // The fallback exists ONLY to compare against the tick (via=post); it is not a candidate design.
        // queueTask/executeAsync is deliberately NOT called from the bridge: poolEntry enqueues without the lock
        // (QupKit/ThreadTaskQueue.cs:23-26) while queueTask dequeues under it (:157-176) (C-F6-threads-hooks-05, established).
        // Never uses awaitTask (no timeout, C-F6-threads-hooks-04).
        // Fire-and-forget UI work (no result, no wait). Same transport rule as RunOnUi: tick when alive, else one Post.
        public static void QueueUi(Action work)
        {
            if (work == null) return;
            if (TickAlive())
            {
                UiWork.Enqueue(work);
                return;
            }
            GameManager gm = GameManager.Instance;
            SynchronizationContext ui = gm == null ? null : gm.uiSynchronizationContext;
            if (ui == null) { Log("QueueUi dropped: no tick and no uiSynchronizationContext"); return; }
            ui.Post(_ => { try { work(); } catch (Exception e) { Log("QueueUi work EXCEPTION " + e); } }, null);
        }

        public static bool RunOnUi<T>(ProbeRun run, string step, Func<T> f, int timeoutMs, out T result)
        {
            result = default(T);
            UiGate gate = new UiGate();
            TaskCompletionSource<T> tcs = new TaskCompletionSource<T>();
            Action work = () =>
            {
                if (gate.Abandoned || (run != null && run.Dead))
                {
                    tcs.TrySetCanceled();
                    return;
                }
                try { tcs.TrySetResult(f()); }
                catch (Exception e) { tcs.TrySetException(e); }
            };
            string transport;
            _lastTransport = "none";
            if (TickAlive())
            {
                transport = "tick";
                UiWork.Enqueue(work);
            }
            else
            {
                transport = "post";
                GameManager gm = GameManager.Instance;
                SynchronizationContext ui = gm == null ? null : gm.uiSynchronizationContext; // GameManager.cs:172,869
                if (ui == null)
                {
                    if (run != null) Log(run, step + " transport=none: GameManager.Instance or uiSynchronizationContext is null");
                    return false;
                }
                ui.Post(_ => work(), null);
            }
            _lastTransport = transport;
            bool done;
            try
            {
                done = tcs.Task.Wait(timeoutMs);
            }
            catch (AggregateException ae)
            {
                if (run != null) Log(run, step + " transport=" + transport + " FAILED: " + (ae.InnerException ?? ae));
                return false;
            }
            if (!done)
            {
                gate.Abandoned = true;
                if (run != null) Log(run, step + " transport=" + transport + " TIMEOUT " + timeoutMs + "ms (closure abandoned)");
                return false;
            }
            result = tcs.Task.Result;
            return true;
        }

        // Transport actually used by the most recent RunOnUi call on this thread.
        [ThreadStatic] private static string _lastTransport;

        public static string LastTransport()
        {
            return _lastTransport ?? "none";
        }

        // Global double-answer guard, keyed by token reference.
        public static bool ClaimToken(object token)
        {
            if (token == null) return false;
            lock (AnsweredLock)
            {
                return AnsweredTokens.Add(token);
            }
        }

        public static bool IsClaimed(object token)
        {
            if (token == null) return false;
            lock (AnsweredLock)
            {
                return AnsweredTokens.Contains(token);
            }
        }

        // ---------------- reflection helpers (protected / private members) ----------------
        public static object GetField(object inst, Type t, string name)
        {
            FieldInfo fi = t.GetField(name, BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);
            return fi == null ? null : fi.GetValue(inst);
        }

        public static bool TcsPending(object tcs)
        {
            if (tcs == null) return false;
            PropertyInfo pi = tcs.GetType().GetProperty("Task");
            Task t = pi == null ? null : pi.GetValue(tcs, null) as Task;
            return t != null && !t.IsCompleted;
        }

        // ---------------- markup stripper (bridge-local; ColorUtility.StripFormatting is not used off the game thread) ----------------
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

        public static bool Contains(string[] arr, string v)
        {
            if (arr == null) return false;
            for (int i = 0; i < arr.Length; i++) if (arr[i] == v) return true;
            return false;
        }

        // ---------------- tutorial overlay (private members, reflection) ----------------
        // TutorialManager.instance is private static (TutorialManager.cs:65) and is set only in Start() (:149-155);
        // ShowingPopup / PopupText are private (:85,87); PopupCompletion is private static (:95) and is replaced by every
        // ShowCellPopup / ShowCIDPopupAsync (:199, :256), so its reference is the per-popup token.
        // popupAcceptPressed is public (:133); OnPopupAcceptPressed() only sets it (:764-767); Update consumes it only while
        // ShowingPopup is true (:769-789).
        public static TutorialManager TutorialInstance()
        {
            FieldInfo fi = typeof(TutorialManager).GetField("instance", BindingFlags.Static | BindingFlags.NonPublic);
            return fi == null ? null : fi.GetValue(null) as TutorialManager;
        }

        public static object TutorialCompletionToken()
        {
            FieldInfo fi = typeof(TutorialManager).GetField("PopupCompletion", BindingFlags.Static | BindingFlags.NonPublic);
            return fi == null ? null : fi.GetValue(null);
        }

        public static bool TutorialShowing(TutorialManager tm)
        {
            object showing = tm == null ? null : GetField(tm, typeof(TutorialManager), "ShowingPopup");
            return showing is bool && (bool)showing;
        }

        private static bool FillTutorial(Snap s)
        {
            TutorialManager tm = TutorialInstance();
            if (!TutorialShowing(tm)) return false;
            object text = GetField(tm, typeof(TutorialManager), "PopupText");
            s.Kind = "tutorial";
            s.TutorialToken = TutorialCompletionToken();
            s.TutorialLatched = tm.popupAcceptPressed;
            s.Detail = "tutorial popup: " + Strip(text as string)
                       + "\n  token=" + (s.TutorialToken == null ? "null" : "#" + RuntimeHelpers.GetHashCode(s.TutorialToken))
                       + " popupAcceptPressed=" + s.TutorialLatched
                       + " activeInHierarchy=" + tm.gameObject.activeInHierarchy;
            return true;
        }

        // Host screens that may sit under the top modal (08 section 3.3 item 4); logged so layering is visible.
        private static readonly string[] HostViews = { "ModernTrade", "StatusScreensScreen", "PickGameObject", "Book", "ModernPopupGamepadAskNumber", "Conversation" };

        // ---------------- classification (UI thread only) ----------------
        // Order follows 08 section 3.3: tutorial overlay > topmost PopupMessage > the TOP nested modal
        // (PickTarget view, AskNumberScreen, Book, PickGameObject view) > host screens found anywhere in the stack.
        // A nested modal is recognised from CurrentGameView / isCurrentWindow() BEFORE any Contains(stack, host) test,
        // so "PickTarget layered on PickGameObjectScreen" (08 section 2.3; Qud.UI/PickGameObjectScreen.cs:604-612)
        // is answered as a picker, never as the host.
        public static Snap Classify()
        {
            Snap s = new Snap();
            GameManager gm = GameManager.Instance;
            string[] stack = gm.GetGameViewStackCopy();                     // GameManager.cs:1441-1461 (locked copy)
            s.Views = string.Join(">", stack);
            s.CurrentView = gm.CurrentGameView ?? "";                        // GameManager.cs:469
            s.InConversation = ConversationUI.CurrentConversation != null;   // XRL.UI/ConversationUI.cs:145
            StringBuilder hosts = new StringBuilder();
            for (int i = 0; i < HostViews.Length; i++)
            {
                if (Contains(stack, HostViews[i]) && HostViews[i] != s.CurrentView) hosts.Append(hosts.Length == 0 ? "" : ",").Append(HostViews[i]);
            }
            s.Hosts = hosts.ToString();

            if (FillTutorial(s)) return s;

            // F1 detect D(pm): PopupMessage in UIManager.instance.windowsByName (Qud.UI/UIManager.cs:23,25) with
            // onHide != null (Qud.UI/PopupMessage.cs:231), active, interactable (Qud.UI/WindowBase.cs:48,217).
            // Singleton key "PopupMessage" = sync path S, "PopupMessage #N" = async copy path A (Qud.UI/UIManager.cs:323-338).
            // Topmost rule (08 section 2.0 D(w)): compare sibling indexes only among candidates with the SAME parent.
            // Copies are re-parented to UIManager.instance.transform (Qud.UI/UIManager.cs:338); the singleton's parent is not
            // established from source, so across parents a copy (created later) wins over the singleton.
            List<KeyValuePair<string, PopupMessage>> cands = new List<KeyValuePair<string, PopupMessage>>();
            foreach (KeyValuePair<string, WindowBase> kv in UIManager.instance.windowsByName)
            {
                PopupMessage pm = kv.Value as PopupMessage;
                if (pm == null) continue;
                if (pm.onHide == null) continue;
                if (!pm.gameObject.activeSelf) continue;
                if (pm.canvasGroup != null && !pm.canvasGroup.interactable) continue;
                cands.Add(new KeyValuePair<string, PopupMessage>(kv.Key, pm));
            }
            if (cands.Count > 0)
            {
                KeyValuePair<string, PopupMessage> best = cands[0];
                StringBuilder all = new StringBuilder();
                for (int i = 0; i < cands.Count; i++)
                {
                    KeyValuePair<string, PopupMessage> c = cands[i];
                    UnityEngine.Transform parent = c.Value.transform.parent;
                    all.Append(i == 0 ? "" : " ").Append(c.Key).Append("(parent=").Append(parent == null ? "null" : parent.name)
                       .Append(" sib=").Append(c.Value.transform.GetSiblingIndex()).Append(")"); // SetAsLastSibling in ShowPopup (Qud.UI/PopupMessage.cs:775)
                    if (i == 0) continue;
                    bool cIsCopy = c.Key.StartsWith("PopupMessage #", StringComparison.Ordinal);
                    bool bIsCopy = best.Key.StartsWith("PopupMessage #", StringComparison.Ordinal);
                    bool sameParent = ReferenceEquals(parent, best.Value.transform.parent);
                    bool better = sameParent
                        ? (c.Value.transform.GetSiblingIndex() > best.Value.transform.GetSiblingIndex()
                           || (c.Value.transform.GetSiblingIndex() == best.Value.transform.GetSiblingIndex() && cIsCopy && !bIsCopy))
                        : (cIsCopy && !bIsCopy);
                    if (better) best = c;
                }
                FillPopup(s, best.Value, best.Key);
                s.Detail += "\n  D(w) candidates=" + cands.Count + ": " + all + " -> chosen=" + best.Key;
                if (s.Hosts.Length > 0) s.Detail += "\n  layered over hosts=[" + s.Hosts + "]";
                return s;
            }

            // Pickers (F3): PickDirection / PickTarget / PickField push "PickTarget" (XRL.UI/PickDirection.cs:30-31,
            // XRL.UI/PickTarget.cs:86-87, 380-381). Checked BEFORE host screens.
            if (s.CurrentView == "PickTarget")
            {
                s.Kind = "picker";
                s.Mode = PickTargetWindow.currentMode;                                  // Qud.UI/PickTargetWindow.cs:19
                s.PGate = gm._ActiveGameView == gm.CurrentGameView && !gm.bViewUpdated  // GameManager.cs:238,248
                          && XRLCore.bThreadFocus;
                s.InputEmpty = Keyboard.KeyQueue.Count == 0 && !Keyboard.HasMouseEvent(); // ConsoleLib.Console/Keyboard.cs:108,865
                s.PickerText = Strip(PickTargetWindow.currentText);
                s.Detail = "picker mode=" + s.Mode + " text=\"" + s.PickerText + "\" P=" + s.PGate
                           + " inputEmpty=" + s.InputEmpty + " active=" + gm._ActiveGameView + " viewUpdated=" + gm.bViewUpdated
                           + (s.Hosts.Length > 0 ? "\n  layered over hosts=[" + s.Hosts + "] (answer the picker first)" : "");
                return s;
            }

            // AskNumberScreen (non-Keyboard AskNumber): view "ModernPopupGamepadAskNumber" is pushed on the game thread BEFORE
            // showScreen replaces menucomplete (XRL.UI/Popup.cs:1323-1331, Qud.UI/AskNumberScreen.cs:129-130), and TradeScreen
            // opens it WITHOUT pushView (Qud.UI/TradeScreen.cs:245-249), so the top test is the view OR isCurrentWindow()
            // (raycaster, Qud.UI/WindowBase.cs:143-146); a pending TCS alone may be the stale field-initializer one.
            AskNumberScreen an = SingletonWindowBase<AskNumberScreen>.instance; // Qud.UI/SingletonWindowBase.cs:7
            if (an != null && (s.CurrentView == "ModernPopupGamepadAskNumber" || an.isCurrentWindow()))
            {
                FillAskNumber(s, an);
                return s;
            }

            // BookScreen: view "Book" pushed before the UI hop that shows the window (Qud.UI/BookScreen.cs:192-205).
            BookScreen bk = SingletonWindowBase<BookScreen>.instance;
            if (bk != null && (s.CurrentView == "Book" || bk.isCurrentWindow()))
            {
                FillBook(s, bk);
                return s;
            }

            // PickGameObjectScreen as the top view: "PickGameObject" is pushed on the UI thread after the TCS swap
            // (Qud.UI/PickGameObjectScreen.cs:225-233, C-F3-pickers-22).
            if (s.CurrentView == "PickGameObject")
            {
                if (FillPickGameObject(s)) return s;
            }

            // ---- host screens found anywhere in the stack (only when no nested modal is on top) ----
            if (Contains(stack, "ModernPopupGamepadAskNumber") && an != null)
            {
                FillAskNumber(s, an); // view pushed, window not yet current: reported as -notready
                return s;
            }
            if (Contains(stack, "Book") && bk != null)
            {
                FillBook(s, bk);
                return s;
            }
            if (Contains(stack, "PickGameObject"))
            {
                if (FillPickGameObject(s)) return s;
            }

            // TradeScreen (F5): view "ModernTrade"; only Cancel() releases the game thread (Qud.UI/TradeScreen.cs:874-880).
            if (Contains(stack, "ModernTrade"))
            {
                TradeScreen ts = SingletonWindowBase<TradeScreen>.instance;
                if (ts != null)
                {
                    object tcs = GetField(ts, typeof(TradeScreen), "menucomplete");      // protected, :30
                    bool pending = TcsPending(tcs);
                    bool active = ts.navigationContext.IsActive();                       // :36, XRL.UI.Framework/NavigationContext.cs:124
                    XRL.UI.Framework.NavigationController nc = XRL.UI.Framework.NavigationController.instance; // NavigationController.cs:48
                    bool busy = ReferenceEquals(nc.activeContext, nc.suspensionContext);  // :50,60 (C-F5-other-blocking-07)
                    // Game data (TradeUI.GetValue) is read only when nothing runs game code on an APIDispatch thread
                    // (08 section 4.1 "APIDispatch の最中は読まない", C-F7-observation-03).
                    string body = (!busy && active) ? ReadTrade(ts) : "trade busy or navigation inactive, not read";
                    s.Detail = body + "\n  pending=" + pending + " navActive=" + active + " busy=" + busy;
                    s.Kind = (pending && active && !busy) ? "trade" : "trade-notready";
                    s.TcsToken = tcs;
                    return s;
                }
            }

            // StatusScreensScreen (F4): menucomplete is recreated on the UI thread at :177 after the view push at :141,
            // so navigationContext.IsActive() is the mandatory guard (C-F4-status-screens-05).
            if (Contains(stack, "StatusScreensScreen"))
            {
                StatusScreensScreen st = SingletonWindowBase<StatusScreensScreen>.instance;
                if (st != null)
                {
                    object tcs = GetField(st, typeof(StatusScreensScreen), "menucomplete"); // protected, :50
                    bool pending = TcsPending(tcs);
                    bool active = st.navigationContext.IsActive();                         // :22
                    int count = st.Screens == null ? 0 : st.Screens.Count;                 // :32
                    s.Detail = "StatusScreens CurrentScreen=" + st.CurrentScreen + " tabs=" + count      // :54
                        + " tab=" + (count > 0 ? (st.CurrentScreen % count).ToString() : "?")
                        + " Screens.CurrentScreen(static)=" + Screens.CurrentScreen                     // XRL.UI/Screens.cs:12
                        + " pending=" + pending + " navActive=" + active;
                    s.Kind = (pending && active) ? "status" : "status-notready";
                    s.TcsToken = tcs;
                    return s;
                }
            }

            s.Kind = "none";
            s.Detail = "no modal detected";
            return s;
        }

        private static void FillAskNumber(Snap s, AskNumberScreen an)
        {
            object tcs = GetField(an, typeof(AskNumberScreen), "menucomplete"); // protected, Qud.UI/AskNumberScreen.cs:19
            bool pending = TcsPending(tcs);
            bool current = an.isCurrentWindow();
            s.Detail = "AskNumberScreen message=\"" + Strip(an.messageText == null ? null : an.messageText.text)
                + "\" number=\"" + (an.numberText == null ? "" : an.numberText.text) + "\" Current=" + an.Current
                + " Min=" + an.Min + " Max=" + an.Max + " pending=" + pending + " isCurrentWindow=" + current   // :25-33
                + (s.Hosts.Length > 0 ? "\n  layered over hosts=[" + s.Hosts + "]" : "");
            s.Kind = (pending && current) ? "asknumberscreen" : "asknumberscreen-notready";
            s.TcsToken = (pending && current) ? tcs : null;
        }

        private static void FillBook(Snap s, BookScreen bk)
        {
            object tcs = GetField(bk, typeof(BookScreen), "menucomplete");      // protected, Qud.UI/BookScreen.cs:29
            bool pending = TcsPending(tcs);
            bool current = bk.isCurrentWindow();
            bool active = bk.navigationContext.IsActive();                      // :37, titleText :42
            int pages = bk.Book == null || bk.Book.Pages == null ? -1 : bk.Book.Pages.Count; // public Book / BookID (:54,56)
            s.Detail = "Book title=\"" + Strip(bk.titleText == null ? null : bk.titleText.text) + "\" BookID=" + (bk.BookID ?? "null")
                       + " pages=" + pages + " pending=" + pending + " isCurrentWindow=" + current + " navActive=" + active;
            s.Kind = (pending && current && active) ? "book" : "book-notready";
            s.TcsToken = tcs;
        }

        private static bool FillPickGameObject(Snap s)
        {
            PickGameObjectScreen pg = SingletonWindowBase<PickGameObjectScreen>.instance;
            if (pg == null) return false;
            object tcs = GetField(pg, typeof(PickGameObjectScreen), "menucomplete"); // protected, :36
            bool pending = TcsPending(tcs);
            bool current = pg.isCurrentWindow();
            StringBuilder sb = new StringBuilder();
            sb.Append("PickGameObject title=\"").Append(Strip(pg.titleText == null ? null : pg.titleText.text)).Append("\""); // :65
            List<GameObject> raw = pg.rawGameObjects;                                                             // :47
            sb.Append(" raw=").Append(raw == null ? 0 : raw.Count);
            if (raw != null)
            {
                for (int i = 0; i < raw.Count && i < 8; i++)
                {
                    sb.Append("\n  (").Append(i).Append(") ").Append(raw[i] == null ? "null" : raw[i].Blueprint); // XRL.World/GameObject.cs:118
                }
            }
            sb.Append("\n  pending=").Append(pending).Append(" isCurrentWindow=").Append(current);
            if (s.Hosts.Length > 0) sb.Append("\n  layered over hosts=[").Append(s.Hosts).Append("]");
            s.Detail = sb.ToString();
            s.Kind = (pending && current) ? "pickgameobject" : "pickgameobject-notready";
            s.TcsToken = tcs;
            return true;
        }

        private static void FillPopup(Snap s, PopupMessage pm, string key)
        {
            s.Kind = "popup";
            s.Pm = pm;
            s.WindowKey = key;
            s.TokenOnHide = pm.onHide;             // Qud.UI/PopupMessage.cs:231
            s.TokenCommand = pm.commandCallback;   // :22
            s.TokenSelect = pm.selectCallback;     // :24
            s.PopupID = pm.PopupID;                // :247
            s.WantsSpecificPrompt = pm.WantsSpecificPrompt; // :237
            s.RestrictChars = pm.RestrictChars;    // :239
            s.HasInput = pm.inputBox != null && pm.inputBox.gameObject.activeSelf; // :28, shown only with includeInput (:807-817)

            StringBuilder sb = new StringBuilder();
            sb.Append("popup window=").Append(key).Append(" path=").Append(key == "PopupMessage" ? "S" : "A");
            sb.Append(" PopupID=").Append(pm.PopupID ?? "null");
            sb.Append(" lastPopupID=").Append(PopupMessage.lastPopupID ?? "null"); // :249
            sb.Append(" token=#").Append(RuntimeHelpers.GetHashCode(pm.onHide));  // identity of tok(w), for per-node token-change checks
            string title = pm.Title == null ? "" : Strip(pm.Title.text);          // :42, UITextSkin.text XRL.UI/UITextSkin.cs:54
            s.Title = title;
            if (title.Length > 0) sb.Append("\n  Title: ").Append(title);
            if (pm.contextText != null && pm.contextText.gameObject.activeSelf)   // :34
            {
                string ctx = Strip(pm.contextText.text);
                if (ctx.Length > 0) sb.Append("\n  Context: ").Append(ctx);
            }
            sb.Append("\n  Message: ").Append(pm.Message == null ? "" : Strip(pm.Message.text)); // :20
            List<QudMenuItem> items = pm.controller == null ? null : pm.controller.menuData;      // Qud.UI/QudBaseMenuController.cs:50
            if (items != null)
            {
                for (int i = 0; i < items.Count; i++)
                {
                    s.OptionCommands.Add(items[i].command);                                       // Qud.UI/QudMenuItem.cs:10-14
                    s.OptionTexts.Add(Strip(items[i].text));
                    sb.Append("\n  ").Append(Strip(items[i].text)).Append("   <").Append(items[i].command).Append(">");
                }
                s.OptionCount = items.Count;
            }
            List<QudMenuItem> buttons = pm.controller == null ? null : pm.controller.bottomContextOptions; // :65
            if (buttons != null && buttons.Count > 0)
            {
                sb.Append("\n  Buttons:");
                for (int i = 0; i < buttons.Count; i++)
                {
                    s.ButtonCommands.Add(buttons[i].command);
                    sb.Append(" [").Append(Strip(buttons[i].text)).Append(" <").Append(buttons[i].command)
                      .Append("/").Append(buttons[i].hotkey).Append(">]");
                }
            }
            if (s.HasInput)
            {
                sb.Append("\n  Input: \"").Append(pm.inputBox.text).Append("\" RestrictChars=\"").Append(pm.RestrictChars ?? "")
                  .Append("\" WantsSpecificPrompt=").Append(pm.WantsSpecificPrompt ?? "null");
            }
            sb.Append("\n  callbacks: command=").Append(pm.commandCallback != null).Append(" select=").Append(pm.selectCallback != null);
            if (pm.PopupID != null && pm.PopupID.StartsWith("Conversation:", StringComparison.Ordinal))
            {
                // Read in this UI task while the game thread waits in ShowConversation (08 section 2.2 M1). IDs are plain
                // fields (XRL.World.Conversations/IConversationElement.cs:34); Target is a plain property (Choice.cs:42-55).
                // Hash / Visited are not read (lazy writes, C-F2-conversation-14).
                XRL.World.Conversations.Node cn = ConversationUI.CurrentNode;                     // XRL.UI/ConversationUI.cs:149
                s.ConvNodeId = cn == null ? null : cn.ID;
                XRL.World.Conversations.Choice lc = ConversationUI.LastChoice;                   // :151
                s.ConvLastChoice = lc;
                s.ConvLastChoiceId = lc == null ? null : lc.ID;
                List<XRL.World.Conversations.Choice> cc = ConversationUI.CurrentChoices;         // :153
                sb.Append("\n  conv node=").Append(s.ConvNodeId ?? "null").Append(" lastChoice=").Append(s.ConvLastChoiceId ?? "null");
                for (int i = 0; cc != null && i < cc.Count; i++)
                {
                    s.ConvChoices.Add(cc[i]);
                    s.ConvChoiceIds.Add(cc[i] == null ? null : cc[i].ID);
                    s.ConvChoiceTargets.Add(cc[i] == null ? null : cc[i].Target);
                    sb.Append("\n    choice[").Append(i).Append("] id=").Append(s.ConvChoiceIds[i] ?? "null").Append(" target=").Append(s.ConvChoiceTargets[i] ?? "null");
                }
            }
            s.Detail = sb.ToString();
        }

        private static string ReadTrade(TradeScreen ts)
        {
            StringBuilder sb = new StringBuilder();
            sb.Append("trade Trader=").Append(TradeScreen.Trader == null ? "null" : TradeScreen.Trader.Blueprint); // Qud.UI/TradeScreen.cs:87
            if (ts.Totals != null && ts.Totals.Length >= 2)                                                        // :51
            {
                sb.Append(" Totals=").Append(ts.Totals[0]).Append("/").Append(ts.Totals[1]);
            }
            for (int side = 0; side < 2; side++)
            {
                List<TradeEntry> entries = ts.tradeEntries == null ? null : ts.tradeEntries[side];                // :53
                int goods = 0;
                StringBuilder names = new StringBuilder();
                if (entries != null)
                {
                    for (int i = 0; i < entries.Count; i++)
                    {
                        GameObject go = entries[i].GO;                                                             // XRL.UI/TradeEntry.cs:7
                        if (go == null) continue;
                        goods++;
                        if (goods <= 5)
                        {
                            // TradeUI.GetValue is what TradeLine calls on the UI thread (XRL.UI/TradeUI.cs:232, Qud.UI/TradeLine.cs:473).
                            names.Append("\n    ").Append(go.Blueprint).Append(" value=")
                                 .Append(TradeUI.GetValue(go, side == 0).ToString("0.00"));
                        }
                    }
                }
                sb.Append("\n  side").Append(side).Append(side == 0 ? "(trader)" : "(player)").Append(" goods=").Append(goods).Append(names);
            }
            return sb.ToString();
        }
    }

    // ------------------------------------------------------------------------------------------
    // Answer recipes. Each one runs on the answerer thread and performs exactly one UI task that
    // re-checks the token captured by Classify() before touching the modal. Hide() is never called.
    // ------------------------------------------------------------------------------------------
    internal static class Answer
    {
        private static bool FindItem(PopupMessage pm, string command, out QudMenuItem found)
        {
            found = default(QudMenuItem);
            List<QudMenuItem> items = pm.controller == null ? null : pm.controller.menuData;            // Qud.UI/QudBaseMenuController.cs:50
            if (items != null)
            {
                for (int i = 0; i < items.Count; i++)
                {
                    if (items[i].command == command) { found = items[i]; return true; }
                }
            }
            List<QudMenuItem> buttons = pm.controller == null ? null : pm.controller.bottomContextOptions; // :65
            if (buttons != null)
            {
                for (int i = 0; i < buttons.Count; i++)
                {
                    if (buttons[i].command == command) { found = buttons[i]; return true; }
                }
            }
            return false;
        }

        // F1 A(item): OnActivateCommand(real item) (Qud.UI/PopupMessage.cs:926-934). The item must come from
        // menuData / bottomContextOptions with non-null text, because the sync callback calls i.text.Replace
        // (XRL.UI/Popup.cs:834-852, C-F1-popup-04). CmdOptions is refused by OnActivateCommand (:928).
        // Success (08 section 2.0 tok(w)): within this task, the callback is nulled (:931) and Hide() nulls onHide
        // (:1083-1103) exactly when the gate at :928 passes, so "onHide != token" alone decides success; cbNulled is
        // logged as the equivalent secondary check (C-F1-popup-08).
        // R5-UNCERTAIN: C-F1-popup-21 (prefab UnityEvent wiring is bypassed; F1 section 6 item 3: activeContext / input state after a direct call)
        public static bool PopupCommand(ProbeRun run, Snap s, string command, bool countAsTarget)
        {
            string outcome = PopupCommandRaw(run, s, command);
            bool ok = outcome != null && outcome.StartsWith("accepted", StringComparison.Ordinal);
            if (outcome == "double-answer-blocked") Interlocked.Increment(ref run.BlockedDoubleAnswers);
            if (ok && countAsTarget) Interlocked.Increment(ref run.AnswerCount);
            return ok;
        }

        // Returns the raw outcome ("accepted cbNulled=..", "token-mismatch(onHide)", ..., or "ui-task-failed").
        // probe:stale replays an old Snap through this and expects a token-mismatch.
        public static string PopupCommandRaw(ProbeRun run, Snap s, string command)
        {
            PopupMessage pm = s.Pm;
            object tOnHide = s.TokenOnHide;
            object tCmd = s.TokenCommand;
            string outcome;
            bool ran = Bridge.RunOnUi(run, "answer-popup-command:" + command, () =>
            {
                if (!ReferenceEquals(pm.onHide, tOnHide)) return "token-mismatch(onHide)";
                if (!ReferenceEquals(pm.commandCallback, tCmd)) return "token-mismatch(commandCallback)";
                if (pm.commandCallback == null) return "commandCallback-null";
                if (!pm.gameObject.activeSelf) return "inactive";
                QudMenuItem item;
                if (!FindItem(pm, command, out item)) return "no-item";
                if (item.text == null) return "item-text-null";
                if (!Bridge.ClaimToken(tOnHide)) return "double-answer-blocked"; // claim only after every guard passed
                pm.OnActivateCommand(item);
                bool cbNulled = !ReferenceEquals(pm.commandCallback, tCmd);
                return (ReferenceEquals(pm.onHide, tOnHide) ? "not-accepted" : "accepted") + " cbNulled=" + cbNulled;
            }, 3000, out outcome);
            string res = ran ? outcome : "ui-task-failed";
            Bridge.Log(run, "ANSWER popup command=" + command + " token=#" + RuntimeHelpers.GetHashCode(tOnHide)
                            + " via=" + Bridge.LastTransport() + " outcome=" + res);
            return res;
        }

        // F1 I(s): inputBox.text = s, read back, OnInputSubmit(s) (Qud.UI/PopupMessage.cs:946-958, C-F1-popup-12).
        // OnInputSubmit selects the first Submit/Accept/CmdOptions button via OnSelect (:936-944), so the token
        // re-check includes selectCallback. For WantsSpecificPrompt this is the same path as the 2 s hold (:1024-1030,
        // C-F1-popup-13); OnActivateCommand(CmdOptions) would be refused (:928).
        public static bool PopupInput(ProbeRun run, Snap s, string value)
        {
            PopupMessage pm = s.Pm;
            object tOnHide = s.TokenOnHide;
            object tSel = s.TokenSelect;
            string outcome;
            bool ran = Bridge.RunOnUi(run, "answer-popup-input", () =>
            {
                if (!ReferenceEquals(pm.onHide, tOnHide)) return "token-mismatch(onHide)";
                if (!ReferenceEquals(pm.selectCallback, tSel)) return "token-mismatch(selectCallback)";
                if (pm.selectCallback == null) return "selectCallback-null";
                if (pm.inputBox == null || !pm.inputBox.gameObject.activeSelf) return "no-input";
                // ControlledTMPInputField : TMP_InputField (Qud.UI/ControlledTMPInputField.cs:9); text is the TMP property.
                // Runtime check (08 section 2.1 AskString row, column 実機): readBack shows whether the TMP setter or the
                // RestrictChars filter in Update (PopupMessage.cs:992-1001) altered the value (C-F1-popup-12 is established).
                if (!Bridge.ClaimToken(tOnHide)) return "double-answer-blocked"; // claim only after every guard passed
                pm.inputBox.text = value;
                string readBack = pm.inputBox.text;
                pm.OnInputSubmit(value);
                bool selNulled = !ReferenceEquals(pm.selectCallback, tSel);
                return (ReferenceEquals(pm.onHide, tOnHide) ? "not-accepted" : "accepted") + " selNulled=" + selNulled + " readBack=\"" + readBack + "\"";
            }, 3000, out outcome);
            Bridge.Log(run, "ANSWER popup input=\"" + value + "\" via=" + Bridge.LastTransport() + " outcome=" + (ran ? outcome : "ui-task-failed"));
            bool ok = ran && outcome != null && outcome.StartsWith("accepted", StringComparison.Ordinal);
            if (ran && outcome == "double-answer-blocked") Interlocked.Increment(ref run.BlockedDoubleAnswers);
            if (ok) Interlocked.Increment(ref run.AnswerCount);
            return ok;
        }

        // Nested / unexpected PopupMessage: conservative choice No > Cancel > Accept; otherwise leave it to the operator.
        public static void NestedPopup(ProbeRun run, Snap s)
        {
            string cmd = null;
            if (s.ButtonCommands.Contains("No")) cmd = "No";
            else if (s.ButtonCommands.Contains("Cancel")) cmd = "Cancel";
            else if (s.ButtonCommands.Contains("Accept")) cmd = "Accept";
            if (cmd == null)
            {
                Bridge.Log(run, "NESTED popup has no No/Cancel/Accept button; not answering (operator must answer manually)");
                return;
            }
            Bridge.Log(run, "NESTED popup -> " + cmd);
            PopupCommand(run, s, cmd, false);
        }

        // Tutorial overlay: OnPopupAcceptPressed() (TutorialManager.cs:764-767) only latches popupAcceptPressed; Update
        // consumes it only while ShowingPopup (:769-789). Token = the PopupCompletion reference (:95, replaced per popup at
        // :199/:256). Press ONCE per token: if Update is not running the latch would silently accept the NEXT popup.
        // R5-UNCERTAIN: C-F5-other-blocking-17 (条件付き: Update runs only while the GameObject is active; decided at runtime)
        public static bool Tutorial(ProbeRun run, object token)
        {
            string outcome;
            bool ran = Bridge.RunOnUi(run, "answer-tutorial", () =>
            {
                TutorialManager tm = Bridge.TutorialInstance();
                if (tm == null) return "no-instance";
                if (!Bridge.TutorialShowing(tm)) return "not-showing";
                if (!ReferenceEquals(Bridge.TutorialCompletionToken(), token)) return "token-mismatch";
                if (tm.popupAcceptPressed) return "already-latched";
                if (!Bridge.ClaimToken(token)) return "double-answer-blocked";
                tm.OnPopupAcceptPressed();
                return "accept-pressed activeInHierarchy=" + tm.gameObject.activeInHierarchy;
            }, 3000, out outcome);
            string res = ran ? outcome : "ui-task-failed";
            Bridge.Log(run, "ANSWER tutorial overlay token=#" + RuntimeHelpers.GetHashCode(token) + " via=" + Bridge.LastTransport() + " outcome=" + res);
            if (res == "double-answer-blocked") Interlocked.Increment(ref run.BlockedDoubleAnswers);
            bool ok = res.StartsWith("accept-pressed", StringComparison.Ordinal);
            if (ok) Interlocked.Increment(ref run.AnswerCount);
            return ok;
        }

        // Probe-only recovery when TutorialManager.Update is not running: clear the latch so it cannot accept a later
        // popup, clear ShowingPopup (it gates every Push*, 08 section 3.3 item 1) and release the awaiting Task.
        // Never part of the agent design.
        // run is passed as null to RunOnUi: after the answerer timeout run.Dead is set and RunOnUi would cancel the work.
        public static void TutorialRecovery(ProbeRun run)
        {
            string outcome;
            bool ran = Bridge.RunOnUi(null, "tutorial-recovery", () =>
            {
                TutorialManager tm = Bridge.TutorialInstance();
                if (tm == null) return "no-instance";
                tm.popupAcceptPressed = false;
                FieldInfo sp = typeof(TutorialManager).GetField("ShowingPopup", BindingFlags.Instance | BindingFlags.NonPublic);
                if (sp != null) sp.SetValue(tm, false);
                object pc = Bridge.TutorialCompletionToken();
                TaskCompletionSource<bool> tcs = pc as TaskCompletionSource<bool>;
                bool released = tcs != null && tcs.TrySetResult(true);
                return "cleared latch+ShowingPopup released=" + released;
            }, 3000, out outcome);
            Bridge.Log(run, "RECOVERY tutorial (probe-only) outcome=" + (ran ? outcome : "ui-task-failed"));
        }

        // R5-0d only: Hide() FIRST on a sync-path popup, to observe the async-void cancel path
        // (Qud.UI/PopupMessage.cs:1083-1103 -> onHide -> complete.TrySetCanceled, XRL.UI/Popup.cs:873-876; Wait() throws at
        // :908 inside the async void method :801, so PopGameView at :910 is skipped). The agent design never does this.
        // R5-UNCERTAIN: C-F1-popup-06 (条件付き: how Mono handles the pool-thread rethrow is runtime-only)
        public static bool HideFirst(ProbeRun run, Snap s)
        {
            PopupMessage pm = s.Pm;
            object tOnHide = s.TokenOnHide;
            string outcome;
            bool ran = Bridge.RunOnUi(run, "hide-first", () =>
            {
                if (!ReferenceEquals(pm.onHide, tOnHide)) return "token-mismatch(onHide)";
                if (!Bridge.ClaimToken(tOnHide)) return "double-answer-blocked";
                pm.Hide();
                return ReferenceEquals(pm.onHide, tOnHide) ? "hide-no-effect" : "hidden";
            }, 3000, out outcome);
            string res = ran ? outcome : "ui-task-failed";
            Bridge.Log(run, "ANSWER popup Hide() FIRST via=" + Bridge.LastTransport() + " outcome=" + res);
            bool ok = res == "hidden";
            if (ok) Interlocked.Increment(ref run.AnswerCount);
            return ok;
        }

        // BookScreen: Cancel() (Qud.UI/BookScreen.cs:368-374). Guards: token unchanged and pending, isCurrentWindow(),
        // navigationContext.IsActive() (08 section 2.5 BookScreen row).
        public static bool BookCancel(ProbeRun run, Snap s)
        {
            object token = s.TcsToken;
            string outcome;
            bool ran = Bridge.RunOnUi(run, "answer-book-cancel", () =>
            {
                BookScreen bk = SingletonWindowBase<BookScreen>.instance;
                if (bk == null) return "no-instance";
                object cur = Bridge.GetField(bk, typeof(BookScreen), "menucomplete");
                if (!ReferenceEquals(cur, token)) return "token-mismatch";
                if (!Bridge.TcsPending(cur)) return "already-completed";
                if (!bk.isCurrentWindow()) return "not-current-window";
                if (!bk.navigationContext.IsActive()) return "nav-inactive";
                if (!Bridge.ClaimToken(token)) return "double-answer-blocked";
                bk.Cancel();
                return Bridge.TcsPending(cur) ? "not-accepted" : "accepted";
            }, 3000, out outcome);
            Bridge.Log(run, "ANSWER Book Cancel via=" + Bridge.LastTransport() + " outcome=" + (ran ? outcome : "ui-task-failed"));
            bool ok = ran && outcome == "accepted";
            if (ran && outcome == "double-answer-blocked") Interlocked.Increment(ref run.BlockedDoubleAnswers);
            if (ok) Interlocked.Increment(ref run.AnswerCount);
            return ok;
        }

        // AskNumberScreen: numberText.SetText(n); Accept() (Qud.UI/AskNumberScreen.cs:213-220, XRL.UI/UITextSkin.cs:158-167,
        // C-F1-popup-20). Token = protected menucomplete, re-checked with isCurrentWindow().
        public static bool AskNumberScreenAccept(ProbeRun run, Snap s, int n)
        {
            object token = s.TcsToken;
            string outcome;
            bool ran = Bridge.RunOnUi(run, "answer-asknumberscreen", () =>
            {
                AskNumberScreen an = SingletonWindowBase<AskNumberScreen>.instance;
                if (an == null) return "no-instance";
                object cur = Bridge.GetField(an, typeof(AskNumberScreen), "menucomplete");
                if (!ReferenceEquals(cur, token)) return "token-mismatch";
                if (!Bridge.TcsPending(cur)) return "already-completed";
                if (!an.isCurrentWindow()) return "not-current-window";
                if (!Bridge.ClaimToken(token)) return "double-answer-blocked"; // claim only after every guard passed
                an.Current = n;
                an.numberText.SetText(n.ToString());
                an.Accept();
                return Bridge.TcsPending(cur) ? "not-accepted" : "accepted";
            }, 3000, out outcome);
            Bridge.Log(run, "ANSWER AskNumberScreen n=" + n + " via=" + Bridge.LastTransport() + " outcome=" + (ran ? outcome : "ui-task-failed"));
            bool ok = ran && outcome == "accepted";
            if (ran && outcome == "double-answer-blocked") Interlocked.Increment(ref run.BlockedDoubleAnswers);
            if (ok) Interlocked.Increment(ref run.AnswerCount);
            return ok;
        }

        // PickGameObjectScreen: HandleSelectItem(new PickGameObjectLineData().set(Item, go: x)) (Qud.UI/PickGameObjectScreen.cs:577-594,
        // Qud.UI/PickGameObjectLineData.cs:24, public ctor via new() constraint XRL.UI.Framework/PooledFrameworkDataElement.cs:5).
        // HandleSelectItem does not validate membership, so the probe validates against rawGameObjects itself (C-F3-pickers-20).
        public static bool PickGameObject(ProbeRun run, Snap s, GameObject target)
        {
            object token = s.TcsToken;
            string outcome;
            bool ran = Bridge.RunOnUi(run, "answer-pickgameobject", () =>
            {
                PickGameObjectScreen pg = SingletonWindowBase<PickGameObjectScreen>.instance;
                if (pg == null) return "no-instance";
                object cur = Bridge.GetField(pg, typeof(PickGameObjectScreen), "menucomplete");
                if (!ReferenceEquals(cur, token)) return "token-mismatch";
                if (!Bridge.TcsPending(cur)) return "already-completed";
                if (!pg.isCurrentWindow()) return "not-current-window";
                bool member = false;
                List<GameObject> raw = pg.rawGameObjects;
                for (int i = 0; raw != null && i < raw.Count; i++)
                {
                    if (ReferenceEquals(raw[i], target)) { member = true; break; }
                }
                if (!member) return "target-not-in-rawGameObjects";
                if (!Bridge.ClaimToken(token)) return "double-answer-blocked"; // claim only after every guard passed
                pg.HandleSelectItem(new PickGameObjectLineData().set(PickGameObjectLineDataType.Item, go: target));
                return Bridge.TcsPending(cur) ? "not-accepted" : "accepted";
            }, 3000, out outcome);
            Bridge.Log(run, "ANSWER PickGameObject target=" + (target == null ? "null" : target.Blueprint) + " via=" + Bridge.LastTransport()
                            + " outcome=" + (ran ? outcome : "ui-task-failed"));
            if (ran && outcome == "double-answer-blocked") Interlocked.Increment(ref run.BlockedDoubleAnswers);
            bool ok = ran && outcome == "accepted";
            if (ok) Interlocked.Increment(ref run.AnswerCount);
            return ok;
        }

        // TradeScreen: Cancel() is the only exit that releases the game thread (Qud.UI/TradeScreen.cs:874-880, C-F5-other-blocking-02).
        // Guards: token unchanged and pending, navigationContext active, not busy (C-F5-other-blocking-07).
        public static bool TradeCancel(ProbeRun run, Snap s)
        {
            object token = s.TcsToken;
            string outcome;
            bool ran = Bridge.RunOnUi(run, "answer-trade-cancel", () =>
            {
                TradeScreen ts = SingletonWindowBase<TradeScreen>.instance;
                if (ts == null) return "no-instance";
                object cur = Bridge.GetField(ts, typeof(TradeScreen), "menucomplete");
                if (!ReferenceEquals(cur, token)) return "token-mismatch";
                if (!Bridge.TcsPending(cur)) return "already-completed";
                if (!ts.navigationContext.IsActive()) return "nav-inactive";
                XRL.UI.Framework.NavigationController nc = XRL.UI.Framework.NavigationController.instance;
                if (ReferenceEquals(nc.activeContext, nc.suspensionContext)) return "busy";
                if (!Bridge.ClaimToken(token)) return "double-answer-blocked"; // claim only after every guard passed
                ts.Cancel();
                return Bridge.TcsPending(cur) ? "not-accepted" : "accepted";
            }, 3000, out outcome);
            Bridge.Log(run, "ANSWER Trade Cancel via=" + Bridge.LastTransport() + " outcome=" + (ran ? outcome : "ui-task-failed"));
            bool ok = ran && outcome == "accepted";
            if (ran && outcome == "double-answer-blocked") Interlocked.Increment(ref run.BlockedDoubleAnswers);
            if (ok) Interlocked.Increment(ref run.AnswerCount);
            return ok;
        }

        // StatusScreensScreen: Exit() (Qud.UI/StatusScreensScreen.cs:225-238, C-F4-status-screens-04), guarded by
        // navigationContext.IsActive() and an unchanged pending menucomplete (C-F4-status-screens-05).
        // R5-UNCERTAIN: C-F4-status-screens-21 (whether the release chain runs inline inside Exit()/TrySetResult on the UI thread)
        public static bool StatusExit(ProbeRun run, Snap s)
        {
            object token = s.TcsToken;
            string outcome;
            bool ran = Bridge.RunOnUi(run, "answer-status-exit", () =>
            {
                StatusScreensScreen st = SingletonWindowBase<StatusScreensScreen>.instance;
                if (st == null) return "no-instance";
                object cur = Bridge.GetField(st, typeof(StatusScreensScreen), "menucomplete");
                if (!ReferenceEquals(cur, token)) return "token-mismatch";
                if (!Bridge.TcsPending(cur)) return "already-completed";
                if (!st.navigationContext.IsActive()) return "nav-inactive";
                if (!Bridge.ClaimToken(token)) return "double-answer-blocked"; // claim only after every guard passed
                st.Exit();
                return Bridge.TcsPending(cur) ? "not-accepted" : "accepted";
            }, 3000, out outcome);
            Bridge.Log(run, "ANSWER Status Exit via=" + Bridge.LastTransport() + " outcome=" + (ran ? outcome : "ui-task-failed"));
            bool ok = ran && outcome == "accepted";
            if (ran && outcome == "double-answer-blocked") Interlocked.Increment(ref run.BlockedDoubleAnswers);
            if (ok) Interlocked.Increment(ref run.AnswerCount);
            return ok;
        }

        // getvk pickers: push ONE event from inside a UI task, only when precondition P' holds and the input queues are
        // empty (C-F3-pickers-04, C-F6-threads-hooks-13). Keyboard.PushKey(KeyCode) / PushMouseEvent(string,int,int) /
        // PushCommand(string) are at ConsoleLib.Console/Keyboard.cs:772,825,723.
        // R5-UNCERTAIN: C-F6-threads-hooks-12 (whether P' is sufficient, i.e. no other ClearInput path drops the event)
        public static string PickerPush(ProbeRun run, PickTargetWindow.TargetMode mode, string label, Action push)
        {
            string outcome;
            bool ran = Bridge.RunOnUi(run, "picker-push:" + label, () =>
            {
                GameManager gm = GameManager.Instance;
                if (gm.CurrentGameView != "PickTarget") return "view=" + gm.CurrentGameView;
                if (PickTargetWindow.currentMode != mode) return "mode=" + PickTargetWindow.currentMode;
                if (!(gm._ActiveGameView == gm.CurrentGameView && !gm.bViewUpdated && XRLCore.bThreadFocus)) return "P-false";
                if (!(Keyboard.KeyQueue.Count == 0 && !Keyboard.HasMouseEvent())) return "input-not-empty";
                push();
                return "pushed";
            }, 3000, out outcome);
            string res = ran ? outcome : "ui-task-failed";
            Bridge.Log(run, "PUSH " + label + " via=" + Bridge.LastTransport() + " outcome=" + res);
            return res;
        }
    }

    // ------------------------------------------------------------------------------------------
    // Wishes. [HasWishCommand] class + [WishCommand("probe")] on a one-string method:
    // attributes XRL.Wish/HasWishCommand.cs:6, XRL.Wish/WishCommand.cs:6-16; the regex is
    // ^probe(?::|\s+)(.*)$ and Groups[1] is passed (XRL.Wish/WishManager.cs:67-74,152-155).
    // A typed wish runs on the game thread (CmdWish -> AskWish -> Wishing.HandleWish,
    // XRL.Wish/WishManager.cs:106-121, XRL.World.Capabilities/Wishing.cs:45-49, C-F6-threads-hooks-20/21).
    // ------------------------------------------------------------------------------------------
    [HasWishCommand]
    public static class ProbeWishes
    {
        private const int AnswerDelayMs = 1500;
        private const int ProbeTimeoutMs = 20000;
        private const int MaxConversationAnswers = 8;

        // 0 = not the target (nested popups get the conservative answer), 1 = progress / wait, 2 = target answered.
        private delegate int TargetHandler(ProbeRun run, Snap s);

        [WishCommand("probe")]
        public static void Probe(string rest)
        {
            try
            {
                Dispatch(rest ?? "");
            }
            catch (Exception e)
            {
                Bridge.Log("probe:" + rest + " EXCEPTION " + e);
            }
            finally
            {
                DrainLeftoverInput(rest);
            }
        }

        // Operator hygiene (runs 2-3 finding). Letters typed into the wish prompt by the automation tool also reach the
        // new input system, which turns bound keys into Adventure-layer FrameCommands ('a' => CmdAbilities) and parks
        // them in ControlManager.CommandQueue (ControlManager.cs:349). That queue drains ONE command per frame
        // (UpdateTheCommandQueue, ControlManager.cs:1965-1987) into FrameDownCommand, which the game thread's getvk
        // consumes; so after the wish returns the leftovers open the AbilityManager etc. Keyboard.ClearInput(clearFrameDown)
        // only drops KeyQueue/MouseEventQueue/FrameDownCommand (Keyboard.cs:877-891, ControlManager.cs:1470-1477);
        // only ControlManager.ConsumeAllInput() clears CommandQueue (ControlManager.cs:1461-1468). CommandQueue is a
        // plain Queue owned by the UI thread, so clear it there, and repeat for a few frames because the popup->Adventure
        // layer switch and the per-frame drain overlap the wish's return.
        private static int _drainGen;
        private static void DrainLeftoverInput(string rest)
        {
            try
            {
                ConsoleLib.Console.Keyboard.ClearInput(false, true);          // game thread; same call Popup.AskString makes
                int gen = Interlocked.Increment(ref _drainGen);
                int steps = 0;
                var sw = System.Diagnostics.Stopwatch.StartNew();
                Action step = null;
                step = () =>
                {
                    if (Volatile.Read(ref _drainGen) != gen) return;          // a newer wish took over
                    ControlManager.ConsumeAllInput();
                    ConsoleLib.Console.Keyboard.ClearInput(false, true);
                    steps++;
                    if (sw.ElapsedMilliseconds < 400 && steps < 120)
                    {
                        // Re-arm through uiQueue so the next step lands in a LATER frame: re-enqueueing into UiWork
                        // directly would be dequeued by the same tick loop (Tick drains up to 32 items per frame).
                        GameManager.Instance.uiQueue.queueTask(() => Bridge.QueueUi(step));
                    }
                    else
                    {
                        Bridge.Log("probe:" + rest + " drained leftover input: steps=" + steps + " over " + sw.ElapsedMilliseconds + "ms (ConsumeAllInput+ClearInput on UI)");
                    }
                };
                Bridge.QueueUi(step);
            }
            catch (Exception e)
            {
                Bridge.Log("probe:" + rest + " DrainLeftoverInput EXCEPTION " + e);
            }
        }

        private static bool Dispatch(string rest)
        {
            string name = rest;
            string arg = null;
            int colon = rest.IndexOf(':');
            if (colon >= 0)
            {
                name = rest.Substring(0, colon);
                arg = rest.Substring(colon + 1);
            }
            name = name.Trim().ToLowerInvariant();
            Bridge.EnsureTick("wish:" + name);
            if (Bridge.ThreadTag() != "game")
            {
                // From the UI thread WaitNewPopupMessage returns immediately (XRL.UI/Popup.cs:804-821, C-F6-threads-hooks-22).
                Bridge.Log("probe:" + rest + " refused: not on the game thread (thread=" + Bridge.ThreadTag() + ")");
                return false;
            }
            switch (name)
            {
                // R5-0 gate (08 section 6.1: if R5-0 fails, no other probe counts)
                case "cancel": return CancelProbe();                      // R5-0d
                case "focus": return arg == "play" ? FocusPlayProbe() : FocusProbe(arg); // R5-0b ("force" = mitigation run, "play" = R5-0b-play)
                case "offthread": return OffThreadProbe();                // R5-0e
                case "reload": return ReloadProbe();                      // R5-0a
                // family probes
                case "yesno": return YesNo();
                case "askstring": return AskStringSpecific();
                case "pickoption": return PickOptionProbe();
                case "stale": return StaleProbe();
                case "asknumber": return AskNumberProbe(arg);
                case "death": return DeathProbe();
                case "pickitem": return PickItemProbe();
                case "pickdir": return PickDirProbe();
                case "picktarget": return PickTargetProbe();
                case "imposter": return ImposterProbe();                  // R5-F3c (tiles + imposters only; not in probe:all)
                case "field": return FieldProbe(arg == "cancel");
                case "conv": return string.IsNullOrEmpty(arg) ? ConvSynthetic() : ConvById(arg);
                case "talk": return TalkProbe(string.IsNullOrEmpty(arg) ? "Mehmet" : arg);
                case "trade": return TradeProbe(string.IsNullOrEmpty(arg) ? "Tam" : arg);
                case "status": return StatusProbe();
                case "book": return BookProbe();
                case "tutorial": return TutorialProbe();
                case "endturn": return EndTurnProbe(arg);
                case "map": return MapProbe();
                case "all": return All();
                default:
                    Bridge.Log("probe:" + rest + " unknown. Known: cancel focus[:force|:play] offthread reload | yesno askstring pickoption stale asknumber[:kb|:pad|:mouse] death pickitem pickdir picktarget imposter field[:cancel] conv[:<ConversationID>] talk[:<Blueprint>] trade[:<Blueprint>] status book tutorial endturn[:spent|:run:<probe>] map all");
                    return false;
            }
        }

        private static bool All()
        {
            // Excludes the R5-0 gate probes (operator actions, may kill the process), death (reloads the checkpoint),
            // tutorial (probe-only recovery path) and endturn / map (need a following player turn or render).
            string[] names = { "yesno", "askstring", "pickoption", "stale", "asknumber:mouse", "asknumber:kb", "pickitem", "pickdir",
                               "picktarget", "field", "field:cancel", "conv", "status", "book", "talk", "trade" };
            int pass = 0;
            StringBuilder fails = new StringBuilder();
            for (int i = 0; i < names.Length; i++)
            {
                bool ok = false;
                try { ok = Dispatch(names[i]); }
                catch (Exception e) { Bridge.Log("[all] " + names[i] + " EXCEPTION " + e); }
                if (ok) pass++; else fails.Append(' ').Append(names[i]);
                Thread.Sleep(500); // let views settle on the game thread between probes
            }
            Bridge.Log("[all] SUMMARY pass=" + pass + "/" + names.Length + " fail=[" + fails.ToString().Trim() + "]");
            return pass == names.Length;
        }

        // ---------------- common scaffolding ----------------
        private static string[] Begin(string name)
        {
            GameManager gm = GameManager.Instance;
            string[] before = gm.GetGameViewStackCopy();
            string ids;
            string idKey = name.IndexOf(':') >= 0 ? name.Substring(0, name.IndexOf(':')) : name;
            Bridge.Log("[" + name + "][" + Bridge.ThreadTag() + "] BEGIN r5=" + (R5Ids.TryGetValue(name, out ids) || R5Ids.TryGetValue(idKey, out ids) ? ids : "?")
                       + " ModernUI=" + Options.ModernUI                                                                   // XRL.UI/Options.cs:34
                       + " ModernCharacterSheet=" + Options.ModernCharacterSheet                                        // :37
                       + " controller=" + ControlManager.activeControllerType                                            // ControlManager.cs:611
                       + " capInputBuffer=" + GameManager.bCapInputBuffer                                                 // GameManager.cs:152
                       + " focused=" + GameManager.focused
                       + " tickAlive=" + Bridge.TickAlive()
                       + " stack=[" + string.Join(">", before) + "]");
            return before;
        }

        // Mapping to 08 section 6.2 (logged in BEGIN so every RESULT can be tied to an R5 ID).
        private static readonly Dictionary<string, string> R5Ids = new Dictionary<string, string>
        {
            { "cancel", "R5-0d" }, { "focus", "R5-0b" }, { "offthread", "R5-0e" }, { "reload", "R5-0a" },
            { "yesno", "R5-F1a" }, { "pickoption", "R5-F1b" }, { "stale", "R5-F1b(stale)" }, { "askstring", "R5-F1d" },
            { "asknumber", "R5-F1e" }, { "death", "R5-F1f" }, { "conv", "R5-F2b(partial)" }, { "conv-id", "R5-F2a" }, { "talk", "R5-F2a" },
            { "pickdir", "R5-F3a" }, { "picktarget", "R5-F3b" }, { "field", "R5-F3d" }, { "pickitem", "R5-F3e" },
            { "status", "R5-F4a" }, { "trade", "R5-F5a(cancel only)" }, { "book", "R5-F5b" }, { "tutorial", "R5-F5d" },
            { "endturn", "R5-F6a" }, { "map", "R5-F7a" },
            { "focus:play", "R5-0b-play" }, { "imposter", "R5-F3c" }  // exact names win over the part before ':' (Begin)
        };

        private static ProbeRun Arm(string name, TargetHandler handler, Action<ProbeRun> onTimeout, bool tutorialIsTarget = false)
        {
            ProbeRun run = new ProbeRun();
            run.Name = name;
            run.TutorialIsTarget = tutorialIsTarget; // written before Thread.Start, so the answerer sees it
            Thread t = new Thread(() => AnswererLoop(run, handler, onTimeout));
            t.IsBackground = true;
            t.Name = "R5-answerer-" + name;
            run.Thread = t;
            t.Start();
            return run;
        }

        private static void AnswererLoop(ProbeRun run, TargetHandler handler, Action<ProbeRun> onTimeout)
        {
            try
            {
                Bridge.Log(run, "answerer armed; first look in " + AnswerDelayMs + "ms");
                Thread.Sleep(AnswerDelayMs);
                System.Diagnostics.Stopwatch sw = System.Diagnostics.Stopwatch.StartNew();
                string lastKey = null;
                while (!run.ModalReturned)
                {
                    if (sw.ElapsedMilliseconds > ProbeTimeoutMs)
                    {
                        Bridge.Log(run, "TIMEOUT after " + ProbeTimeoutMs + "ms with the modal still open: answer it manually. Hide() was NOT called.");
                        if (onTimeout != null) onTimeout(run);
                        run.Dead = true;
                        return;
                    }
                    Snap s;
                    // R5-F7b: time the whole UI-thread read.
                    if (!Bridge.RunOnUi(run, "classify", () =>
                        {
                            System.Diagnostics.Stopwatch rsw = System.Diagnostics.Stopwatch.StartNew();
                            Snap r = Bridge.Classify();
                            r.ReadMs = rsw.ElapsedMilliseconds;
                            return r;
                        }, 3000, out s))
                    {
                        Thread.Sleep(250);
                        continue;
                    }
                    if (s.ReadMs > run.MaxReadMs) run.MaxReadMs = s.ReadMs;
                    string key = s.Kind + "|" + s.Views + "|" + s.Detail;
                    if (key != lastKey)
                    {
                        Bridge.Log(run, "DETECT kind=" + s.Kind + " view=" + s.CurrentView + " stack=[" + s.Views + "] inConversation="
                                        + s.InConversation + " readMs=" + s.ReadMs + "\n" + s.Detail);
                        lastKey = key;
                    }
                    if (s.Kind == "tutorial")
                    {
                        // Highest priority (08 section 3.3 item 1). One press per PopupCompletion token; if the popup is still
                        // showing ~3 s after the press, TutorialManager.Update is not running: report it and never press again.
                        if (s.TutorialToken == null)
                        {
                            Bridge.Log(run, "tutorial popup without a PopupCompletion token; not pressing");
                        }
                        else if (!Bridge.IsClaimed(s.TutorialToken))
                        {
                            run.TutorialWaitPolls = 0;
                            // probe:tutorial: this branch runs before the handler, so the handler never sees its target; count
                            // the recognition here, as "handler returned non-zero" does below (README 7.1 (1) targetMatched>=1).
                            if (run.TutorialIsTarget) run.TargetMatches++;
                            Answer.Tutorial(run, s.TutorialToken);
                        }
                        else if (++run.TutorialWaitPolls == 20)
                        {
                            Bridge.Log(run, "tutorial Update not running: ShowingPopup still true ~3 s after the press (popupAcceptPressed="
                                            + s.TutorialLatched + "); not pressing again");
                        }
                        Thread.Sleep(150);
                        continue;
                    }
                    if (!run.Finished)
                    {
                        if ((s.Kind == "popup" && Bridge.IsClaimed(s.TokenOnHide)) || (s.TcsToken != null && Bridge.IsClaimed(s.TcsToken)))
                        {
                            // Already answered by us; wait for the modal to go away instead of answering twice.
                            Thread.Sleep(150);
                            continue;
                        }
                        int r = handler(run, s);
                        if (r != 0) run.TargetMatches++;
                        if (r == 2)
                        {
                            run.Finished = true;
                            Bridge.Log(run, "target answered; waiting for the game thread to return");
                        }
                        else if (r == 0 && s.Kind == "popup")
                        {
                            Answer.NestedPopup(run, s);
                        }
                    }
                    Thread.Sleep(150);
                }
                Bridge.Log(run, "answerer exit: modal returned (answers=" + run.AnswerCount + ") uiread maxMs=" + run.MaxReadMs);
            }
            catch (Exception e)
            {
                Bridge.Log(run, "answerer EXCEPTION " + e);
            }
        }

        private static bool SameStack(string[] a, string[] b)
        {
            if (a.Length != b.Length) return false;
            for (int i = 0; i < a.Length; i++) if (a[i] != b[i]) return false;
            return true;
        }

        private static bool Finish(ProbeRun run, string[] before, bool valueOk, string expected, string got)
        {
            run.ModalReturned = true;
            if (run.Thread != null) run.Thread.Join(3000);
            GameManager gm = GameManager.Instance;
            string[] after = gm.GetGameViewStackCopy();
            for (int i = 0; i < 10 && !SameStack(before, after); i++)
            {
                Thread.Sleep(100);
                after = gm.GetGameViewStackCopy();
            }
            // A leaked "PopupMessage" here is the async-void cancel signature (XRL.UI/Popup.cs:801,908-910, C-F1-popup-06).
            bool viewsOk = SameStack(before, after);
            bool answeredOk = run.AnswerCount >= 1 && !run.Dead;
            bool pass = valueOk && viewsOk && answeredOk && run.BlockedDoubleAnswers == 0;
            Bridge.Log(run, "RESULT expected=" + expected + " got=" + got + " value=" + (valueOk ? "ok" : "MISMATCH")
                            + " views=" + (viewsOk ? "restored" : "LEAKED") + " before=[" + string.Join(">", before) + "] after=[" + string.Join(">", after) + "]"
                            + " targetMatched=" + run.TargetMatches + " answers=" + run.AnswerCount + " blockedDouble=" + run.BlockedDoubleAnswers + " timedOut=" + run.Dead
                            + " -> " + (pass ? "PASS" : "FAIL"));
            return pass;
        }

        private static bool PreconditionFail(string name, string why)
        {
            Bridge.Log("[" + name + "][" + Bridge.ThreadTag() + "] RESULT FAIL precondition: " + why);
            return false;
        }

        private static bool RequireModern(string name)
        {
            return Options.ModernUI || PreconditionFail(name, "Options.ModernUI is false (UIManager.UseNewPopups => Options.ModernUI, Qud.UI/UIManager.cs:55)");
        }

        // ---------------- F1: Yes/No ----------------
        // ShowYesNo -> sync path S; default result is Yes and Cancel maps to No (XRL.UI/Popup.cs:2251-2276).
        // The answerer chooses No so that a silent cancel (returns defaultResult=Yes, C-F1-popup-06) cannot pass.
        private static bool YesNo()
        {
            const string name = "yesno";
            if (!RequireModern(name)) return false;
            string[] before = Begin(name);
            ProbeRun run = Arm(name, (r, s) =>
            {
                if (s.Kind == "popup" && !s.HasInput && s.ButtonCommands.Contains("Yes") && s.ButtonCommands.Contains("No"))
                {
                    return Answer.PopupCommand(r, s, "No", true) ? 2 : 1;
                }
                return 0;
            }, null);
            DialogResult got = Popup.ShowYesNo("[R5] probe:yesno - the answerer will choose No (the silent default is Yes).");
            return Finish(run, before, got == DialogResult.No, "No", got.ToString());
        }

        // ---------------- F1: AskString with WantsSpecificPrompt ----------------
        // AskString -> AskStringAsync(...).Result, async copy path A (XRL.UI/Popup.cs:1433-1443,1371-1431).
        // On PC the buttons are keep(Submit)/Cancel/CmdOptions (:1374-1385). Cancel returns "" here, a fault returns null.
        private static bool AskStringSpecific()
        {
            const string name = "askstring";
            if (!RequireModern(name)) return false;
            string[] before = Begin(name);
            ProbeRun run = Arm(name, (r, s) =>
            {
                if (s.Kind == "popup" && s.HasInput && !string.IsNullOrEmpty(s.WantsSpecificPrompt))
                {
                    return Answer.PopupInput(r, s, s.WantsSpecificPrompt) ? 2 : 1;
                }
                return 0;
            }, null);
            string got = Popup.AskString("[R5] probe:askstring - the answerer will type RETIRE", Default: "", WantsSpecificPrompt: "RETIRE", MaxLength: 7);
            return Finish(run, before, got == "RETIRE", "RETIRE", got == null ? "null" : "\"" + got + "\"");
        }

        // ---------------- F1: PickOption ----------------
        // PickOption -> sync path S, items "option:N" (XRL.UI/Popup.cs:1650-1760,2011-2044); DefaultSelected=0, Escape=-1.
        private static bool PickOptionProbe()
        {
            const string name = "pickoption";
            if (!RequireModern(name)) return false;
            string[] before = Begin(name);
            ProbeRun run = Arm(name, (r, s) =>
            {
                if (s.Kind == "popup" && !s.HasInput && s.PopupID == null && s.OptionCommands.Contains("option:2"))
                {
                    return Answer.PopupCommand(r, s, "option:2", true) ? 2 : 1;
                }
                return 0;
            }, null);
            int got = Popup.PickOption(Title: "[R5] probe:pickoption", Intro: "The answerer will choose gamma (index 2).",
                                       Options: new List<string> { "alpha", "beta", "gamma", "delta" }, AllowEscape: true);
            return Finish(run, before, got == 2, "2", got.ToString());
        }

        // ---------------- F1 / F3-M7: AskNumber ----------------
        // Keyboard: copy popup path A under "ModernPopup:AskNumber"; otherwise AskNumberScreen under
        // "ModernPopupGamepadAskNumber" (XRL.UI/Popup.cs:1320-1349, branch at :1323).
        // _activeControllerType has no initializer, so it starts as Mouse (ControlManager.cs:74-80,337). Only real InputSystem
        // events rewrite it: InputSystem.onEvent -> OnInputSystemEvent -> setLastUsedDevice sets Keyboard for any non-mouse,
        // non-gamepad device (ControlManager.cs:846-861, 809-835, 898). Typing the wish (Ctrl+W) therefore leaves Keyboard,
        // so an argument-less probe:asknumber takes the COPY path, while the unattended agent (Keyboard.Push* never reaches
        // InputSystem) stays on Mouse and takes the AskNumberScreen path. probe:asknumber:mouse reproduces the agent surface.
        // A forced value is sticky: OnInputSystemEvent / setLastUsedDevice return early while lastUsedDevice == device
        // (ControlManager.cs:848-851, 811), so a later key press does NOT undo it; the restore below is mandatory.
        // The field is written and restored only inside UI tasks, and the restore is in finally.
        private static bool AskNumberProbe(string arg)
        {
            string name = "asknumber" + (string.IsNullOrEmpty(arg) ? "" : ":" + arg);
            if (!RequireModern(name)) return false;
            ControlManager.InputDeviceType? forced = null;
            if (arg == "kb") forced = ControlManager.InputDeviceType.Keyboard;
            else if (arg == "pad") forced = ControlManager.InputDeviceType.Gamepad;
            else if (arg == "mouse") forced = ControlManager.InputDeviceType.Mouse;
            else if (!string.IsNullOrEmpty(arg)) return PreconditionFail(name, "unknown argument \"" + arg + "\" (use kb, pad or mouse)");
            ControlManager.InputDeviceType prior = ControlManager.InputDeviceType.Unknown;
            bool overridden = false;
            try
            {
                if (forced.HasValue)
                {
                    ControlManager.InputDeviceType want = forced.Value;
                    // R5-UNCERTAIN: C-F3-pickers-23 (条件付き: whether anything rewrites the override before AskNumberAsync reads it)
                    if (!Bridge.RunOnUi(null, "asknumber-force", () =>
                        {
                            ControlManager.InputDeviceType p = ControlManager._activeControllerType;
                            ControlManager._activeControllerType = want;
                            return p;
                        }, 3000, out prior))
                    {
                        return PreconditionFail(name, "could not set _activeControllerType in a UI task");
                    }
                    overridden = true;
                }
                Bridge.Log("[" + name + "] controller before=" + (overridden ? prior.ToString() : ControlManager._activeControllerType.ToString())
                           + " forced=" + (arg ?? "none") + " effective=" + ControlManager.activeControllerType
                           + " expectedSurface=" + (ControlManager.activeControllerType == ControlManager.InputDeviceType.Keyboard ? "copy-popup" : "AskNumberScreen"));
                string[] before = Begin(name);
                ProbeRun run = Arm(name, (r, s) =>
                {
                    if (s.Kind == "popup" && s.HasInput && (s.RestrictChars == "0123456789" || s.RestrictChars == "0123456789-"))
                    {
                        return Answer.PopupInput(r, s, "7") ? 2 : 1;
                    }
                    if (s.Kind == "asknumberscreen")
                    {
                        return Answer.AskNumberScreenAccept(r, s, 7) ? 2 : 1;
                    }
                    return 0;
                }, null);
                int? got = Popup.AskNumber("[R5] probe:" + name + " - the answerer will enter 7", Start: 3, Min: 0, Max: 10);
                return Finish(run, before, got.HasValue && got.Value == 7, "7", got.HasValue ? got.Value.ToString() : "null");
            }
            finally
            {
                if (overridden)
                {
                    ControlManager.InputDeviceType restoreTo = prior;
                    ControlManager.InputDeviceType after;
                    bool restored = Bridge.RunOnUi(null, "asknumber-restore", () =>
                    {
                        ControlManager._activeControllerType = restoreTo; // ControlManager.cs:337
                        return ControlManager._activeControllerType;
                    }, 3000, out after);
                    Bridge.Log("[" + name + "] controller restored=" + (restored ? after.ToString() : "FAILED (UI task did not run; the forced value may persist)"));
                }
            }
        }

        // ---------------- F3-M6: PickGameObjectScreen ----------------
        // PickItem.ShowPicker(IList<GameObject>, ..., Title, PreserveOrder) (XRL.UI/PickItem.cs:263) -> PickGameObjectScreen.show(...).Result
        // (C-F3-pickers-17). Expected: the LAST item (never the first/default one).
        private static bool PickItemProbe()
        {
            const string name = "pickitem";
            if (!RequireModern(name)) return false;
            List<GameObject> items = new List<GameObject>();
            if (The.Player != null && The.Player.Inventory != null)                // XRL/The.cs:23, XRL.World/GameObject.cs:134
            {
                items.AddRange(The.Player.Inventory.GetObjects());                  // XRL.World.Parts/Inventory.cs:524
            }
            if (items.Count < 2) return PreconditionFail(name, "player inventory has " + items.Count + " items; need at least 2");
            GameObject target = items[items.Count - 1];
            string[] before = Begin(name);
            ProbeRun run = Arm(name, (r, s) =>
            {
                if (s.Kind == "pickgameobject")
                {
                    return Answer.PickGameObject(r, s, target) ? 2 : 1;
                }
                return 0;
            }, null);
            GameObject got = PickItem.ShowPicker(items, Title: "[R5] probe:pickitem", PreserveOrder: true);
            return Finish(run, before, ReferenceEquals(got, target), target.Blueprint, got == null ? "null" : got.Blueprint);
        }

        // ---------------- F3-M1: PickDirection ----------------
        // PickDirection.ShowPicker (XRL.UI/PickDirection.cs:28-106): getvk loop; NumPad6 -> "E"; Escape -> null.
        // KeyCode.Keypad6 maps to Keys.NumPad6 (ConsoleLib.Console/Keyboard.cs:540).
        private static bool PickDirProbe()
        {
            const string name = "pickdir";
            if (!RequireModern(name)) return false;
            string[] before = Begin(name);
            ProbeRun run = Arm(name, (r, s) =>
            {
                if (s.Kind == "picker" && s.Mode == PickTargetWindow.TargetMode.PickDirection)
                {
                    string o = Answer.PickerPush(r, PickTargetWindow.TargetMode.PickDirection, "Keypad6",
                                                 () => Keyboard.PushKey(UnityEngine.KeyCode.Keypad6));
                    if (o == "pushed")
                    {
                        Interlocked.Increment(ref r.AnswerCount);
                        return 2;
                    }
                    return 1;
                }
                return 0;
            }, PickerEscape);
            string got = PickDirection.ShowPicker("[R5] probe:pickdir");
            return Finish(run, before, got == "E", "E", got ?? "null");
        }

        // ---------------- F3-M2: PickTarget.ShowPicker (cells) ----------------
        // XRL.UI/PickTarget.cs:378-990. The first "PointerOver" is swallowed (flag3, :402,792-808), the second moves the
        // cursor; "Command:CmdFire" confirms at the cursor (:965-984). Cursor position is not readable (C-F3-pickers-11).
        // R5-UNCERTAIN: C-F7-observation-11 / C-F3-pickers-26 (PointerOver x2 then CmdFire confirms at (x,y); a real mouse over the map may interfere)
        private static bool PickTargetProbe()
        {
            const string name = "picktarget";
            if (!RequireModern(name)) return false;
            Cell c = The.Player == null ? null : The.Player.CurrentCell;           // XRL.World/GameObject.cs:510
            if (c == null) return PreconditionFail(name, "player has no cell");
            Cell tgt = c.GetCellFromDirection("E") ?? c.GetCellFromDirection("W"); // XRL.World/Cell.cs:8006
            if (tgt == null) return PreconditionFail(name, "no E/W neighbour cell");
            int tx = tgt.X, ty = tgt.Y;                                              // XRL.World/Cell.cs:248,250
            string[] before = Begin(name);
            Bridge.Log("[" + name + "] player=(" + c.X + "," + c.Y + ") target=(" + tx + "," + ty + ")");
            ProbeRun run = Arm(name, (r, s) =>
            {
                if (s.Kind != "picker" || s.Mode != PickTargetWindow.TargetMode.PickCells) return 0;
                string o;
                if (r.Step < 2)
                {
                    o = Answer.PickerPush(r, PickTargetWindow.TargetMode.PickCells, "PointerOver#" + (r.Step + 1) + "(" + tx + "," + ty + ")",
                                          () => Keyboard.PushMouseEvent("PointerOver", tx, ty));
                    if (o == "pushed") r.Step++;
                    return 1;
                }
                o = Answer.PickerPush(r, PickTargetWindow.TargetMode.PickCells, "Command:CmdFire",
                                      () => Keyboard.PushCommand("CmdFire"));
                if (o == "pushed")
                {
                    Interlocked.Increment(ref r.AnswerCount);
                    return 2;
                }
                return 1;
            }, PickerEscape);
            Cell got = PickTarget.ShowPicker(PickTarget.PickStyle.EmptyCell, 0, 9999, c.X, c.Y, Locked: false, VisLevel: AllowVis.Any,
                                             Label: "[R5] probe:picktarget", UseTarget: false);
            return Finish(run, before, got != null && got.X == tx && got.Y == ty, "(" + tx + "," + ty + ")",
                          got == null ? "null" : "(" + got.X + "," + got.Y + ")");
        }

        // ---------------- R5-F3c: aiming reticle imposter (tile mode) ----------------
        // Same picker, target cell and pushes as probe:picktarget (R5-F3b). Between PointerOver#2 and CmdFire the probe checks
        // that exactly ONE cell of the rendered map carries the imposter "Prefabs/Imposters/TargetReticle" and that it is the
        // pushed cell. Style EmptyCell adds it only at the cursor (x,y), and only when Options.UseImposters; otherwise it writes
        // "X" (XRL.UI/PickTarget.cs:424-487; UseImposters => !DisableImposters, XRL.UI/Options.cs:238,604).
        //
        // Where imposterExtra can be read (source finding, 2.0.211.56):
        //   NOT in an AfterRender callback. Each ShowPicker iteration first calls XRLCore.Core.RenderMapToBuffer(Buffer)
        //   (XRL.UI/PickTarget.cs:412), which runs the AfterRender callbacks at its very end (XRL.Core/XRLCore.cs:2407-2434,
        //   loop :2430-2433), i.e. BEFORE the switch adds the reticle (PickTarget.cs:424-487). The previous iteration's reticle is
        //   already gone then: Zone.Render calls Buf.Clear() (XRL.World/Zone.cs:5708; ConsoleLib.Console/ScreenBuffer.cs:280-290
        //   -> ConsoleChar.Clear -> extras[i].Clear(), ConsoleLib.Console/ConsoleChar.cs:255-274 -> ImposterExtra.Clear,
        //   ConsoleLib.Console/ImposterExtra.cs:104-107), and ConsoleChar.Set clears every cell's imposters again
        //   (Zone.cs:5737, ConsoleChar.cs:392-401).
        //   YES in TextConsole.CurrentBuffer, on the UI thread. After the switch, ShowPicker calls _TextConsole.DrawBuffer(Buffer)
        //   (PickTarget.cs:786), which copies it into TextConsole.CurrentBuffer under lock(TextConsole.BufferCS)
        //   (ConsoleLib.Console/TextConsole.cs:142-160; ScreenBuffer.Copy -> ConsoleChar.Copy -> imposterExtra.CopyFrom,
        //   ScreenBuffer.cs:303-318, ConsoleChar.cs:360-374, ImposterExtra.cs:85-95). The renderer reads exactly that buffer under
        //   lock(GameViewStack) + lock(TextConsole.BufferCS) and hands each cell to ConsoleChar.AfterRender -> ImposterExtra.AfterRender,
        //   which spawns the prefabs (GameManager.cs:3172-3176, 3212, 3334; ConsoleChar.cs:587-595; ImposterExtra.cs:109-171).
        //   Nothing clears CurrentBuffer's imposters until the next DrawBuffer, so the scan runs in a UI task under lock(BufferCS).
        //   An AfterRender callback is still registered (once, no Remove API) and armed once as an informational cross-check that
        //   is expected to report cells=0; cells>0 there means this reading is wrong. It never gates PASS.
        // R5-UNCERTAIN: C-F7-observation-11 / C-F3-pickers-26 (same PointerOver x2 + CmdFire path as probe:picktarget)
        private const string ReticlePrefab = "Prefabs/Imposters/TargetReticle";
        private const int ImposterScanPolls = 10;   // answerer polls (~200 ms each) allowed for the reticle to reach the target
        private const int ImposterArWaitPolls = 5;  // answerer polls allowed for the armed AfterRender callback to run

        private sealed class ReticleScan
        {
            public string Pending;                  // non-null: not scanned (reason); the caller retries
            public int Cells;                       // cells whose imposters contain ReticlePrefab
            public int X = -1, Y = -1;              // first such cell
            public int[] Xs = new int[4], Ys = new int[4]; // up to 4 such cells, for the log
            public string ViewTag;                  // CurrentGameView at DrawBuffer time (ConsoleLib.Console/TextConsole.cs:154)
        }

        private sealed class ImposterState          // answerer thread only, except Verdict (read after ShowPicker returns)
        {
            public bool InitialLogged;
            public int ScanPolls;
            public int ArWaitPolls;
            public volatile string Verdict = "none"; // ok | MISMATCH | none
        }

        private static volatile bool _imposterArArmed;
        private static volatile string _imposterArResult; // null until the armed callback ran
        private static volatile int _imposterArCells = -1;
        private static bool _imposterArRegistered;         // game thread only

        private static string Pt(int x, int y)
        {
            return "(" + x + "," + y + ")";
        }

        // Counts reticle cells. The caller guarantees nobody writes buf meanwhile (BufferCS held, or the writing thread itself).
        private static void CountReticle(ScreenBuffer buf, ReticleScan r)
        {
            for (int x = 0; x < buf.Width; x++)
            {
                for (int y = 0; y < buf.Height; y++)
                {
                    ConsoleChar ch = buf[x, y];                                             // ConsoleLib.Console/ScreenBuffer.cs:103-116
                    ImposterExtra ie = ch == null ? null : ch.imposterExtra;                // ConsoleLib.Console/ConsoleChar.cs:69, set in the ctor :216-218 (requireExtra :551-573)
                    List<ImposterExtra.ImposterInfo> list = ie == null ? null : ie.imposters; // ConsoleLib.Console/ImposterExtra.cs:55 (prefab :13)
                    if (list == null) continue;
                    for (int k = 0; k < list.Count; k++)
                    {
                        if (list[k].prefab != ReticlePrefab) continue;
                        if (r.Cells == 0) { r.X = x; r.Y = y; }
                        if (r.Cells < r.Xs.Length) { r.Xs[r.Cells] = x; r.Ys[r.Cells] = y; }
                        r.Cells++;
                        break; // one count per cell
                    }
                }
            }
        }

        private static string AllCells(ReticleScan r)
        {
            if (r.Cells <= 1) return "";
            StringBuilder sb = new StringBuilder(" all=[");
            for (int i = 0; i < r.Cells && i < r.Xs.Length; i++) sb.Append(i == 0 ? "" : ",").Append(Pt(r.Xs[i], r.Ys[i]));
            return sb.Append(r.Cells > r.Xs.Length ? ",...]" : "]").ToString();
        }

        // UI thread only (runs inside a UI task). Counts are taken inside the lock; strings are built by the caller.
        private static ReticleScan ScanLiveReticle()
        {
            ReticleScan r = new ReticleScan();
            GameManager gm = GameManager.Instance;
            if (gm.CurrentGameView != "PickTarget") { r.Pending = "view=" + gm.CurrentGameView; return r; }
            // The pushed PointerOver must already be consumed by getvk (XRL.UI/PickTarget.cs:791-808) before the frame is read.
            if (!(Keyboard.KeyQueue.Count == 0 && !Keyboard.HasMouseEvent())) { r.Pending = "input-not-consumed"; return r; }
            ScreenBuffer cb = TextConsole.CurrentBuffer;                                  // ConsoleLib.Console/TextConsole.cs:31
            if (cb == null) { r.Pending = "CurrentBuffer-null"; return r; }
            // DrawBuffer copies under this lock on the game thread (TextConsole.cs:149); never scan unlocked.
            if (!System.Threading.Monitor.TryEnter(TextConsole.BufferCS, 200)) { r.Pending = "BufferCS-busy"; return r; } // TextConsole.cs:29
            try
            {
                r.ViewTag = cb.ViewTag;                                                   // ScreenBuffer.cs:17
                CountReticle(cb, r);
            }
            finally
            {
                System.Threading.Monitor.Exit(TextConsole.BufferCS);
            }
            return r;
        }

        // Informational cross-check (see above): runs on the game thread at the end of RenderMapToBuffer (XRL.Core/XRLCore.cs:2430-2433).
        private static void AfterRenderImposter(XRLCore core, ScreenBuffer buf)
        {
            if (!_imposterArArmed) return;
            _imposterArArmed = false;
            try
            {
                ReticleScan r = new ReticleScan();
                CountReticle(buf, r); // buf is written only by this (game) thread
                _imposterArCells = r.Cells;
                _imposterArResult = "cells=" + r.Cells + " at=" + Pt(r.X, r.Y) + AllCells(r)
                                    + " sameAsCurrentBuffer=" + ReferenceEquals(buf, TextConsole.CurrentBuffer)
                                    + " view=" + GameManager.Instance.CurrentGameView + " thread=" + Bridge.ThreadTag();
            }
            catch (Exception ex)
            {
                _imposterArResult = "EXCEPTION " + ex.GetType().Name + ": " + ex.Message;
            }
        }

        private static bool ImposterProbe()
        {
            const string name = "imposter";
            if (!RequireModern(name)) return false;
            if (!Options.UseTiles || !Options.UseImposters)
            {
                return PreconditionFail(name, "needs tiles and imposters: UseTiles=" + Options.UseTiles
                    + " (Globals.RenderMode from OptionUseTiles, XRL.UI/Options.cs:606,1288-1295) UseImposters=" + Options.UseImposters
                    + " (!DisableImposters, XRL.UI/Options.cs:238,604; PickTarget adds the reticle only when it is true, XRL.UI/PickTarget.cs:429-487)");
            }
            Cell c = The.Player == null ? null : The.Player.CurrentCell;           // XRL.World/GameObject.cs:510
            if (c == null) return PreconditionFail(name, "player has no cell");
            Cell tgt = c.GetCellFromDirection("E") ?? c.GetCellFromDirection("W"); // XRL.World/Cell.cs:8006
            if (tgt == null) return PreconditionFail(name, "no E/W neighbour cell");
            int tx = tgt.X, ty = tgt.Y, px = c.X, py = c.Y;                          // XRL.World/Cell.cs:248,250
            if (!_imposterArRegistered)
            {
                // No Remove API (XRL.Core/XRLCore.cs:652-655): register once from the game thread, arm per use (as probe:map).
                XRLCore.RegisterAfterRenderCallback(AfterRenderImposter);
                _imposterArRegistered = true;
            }
            _imposterArArmed = false;
            _imposterArResult = null;
            _imposterArCells = -1;
            string[] before = Begin(name);
            Bridge.Log("[" + name + "] player=" + Pt(px, py) + " target=" + Pt(tx, ty) + " UseTiles=" + Options.UseTiles + " UseImposters=" + Options.UseImposters);
            ImposterState st = new ImposterState();
            ProbeRun run = Arm(name, (r, s) =>
            {
                if (s.Kind != "picker" || s.Mode != PickTargetWindow.TargetMode.PickCells) return 0;
                string o;
                if (!st.InitialLogged)
                {
                    // Diagnostic only, tried once so it can never block the flow: before any push the cursor is the start cell,
                    // the player's (UseTarget:false, XRL.UI/PickTarget.cs:391-400).
                    st.InitialLogged = true;
                    ReticleScan i0;
                    bool ran0 = Bridge.RunOnUi(r, "imposter-scan-initial", ScanLiveReticle, 3000, out i0);
                    Bridge.Log(r, !ran0 ? "IMPOSTER-INITIAL ui-task-failed (diagnostic only)"
                                  : "IMPOSTER-INITIAL cells=" + i0.Cells + " at=" + Pt(i0.X, i0.Y) + " expected=" + Pt(px, py) + AllCells(i0)
                                    + " viewTag=" + (i0.ViewTag ?? "null") + (i0.Pending != null ? " pending=" + i0.Pending : "")
                                    + " (start cell = player; diagnostic only)");
                }
                if (r.Step < 2)
                {
                    o = Answer.PickerPush(r, PickTargetWindow.TargetMode.PickCells, "PointerOver#" + (r.Step + 1) + Pt(tx, ty),
                                          () => Keyboard.PushMouseEvent("PointerOver", tx, ty));
                    if (o == "pushed") r.Step++;
                    return 1;
                }
                if (r.Step == 2)
                {
                    // The reticle moves on the first frame drawn after getvk consumed PointerOver#2 (the loop re-renders,
                    // XRL.UI/PickTarget.cs:410-786), so a mismatch is retried for a bounded number of polls before it is recorded;
                    // CmdFire is pushed either way so that RESULT prints instead of a TIMEOUT.
                    ReticleScan sc;
                    if (!Bridge.RunOnUi(r, "imposter-scan", ScanLiveReticle, 3000, out sc)) return 1;
                    st.ScanPolls++;
                    bool match = sc.Pending == null && sc.Cells == 1 && sc.X == tx && sc.Y == ty;
                    if (!match && st.ScanPolls < ImposterScanPolls) return 1;
                    st.Verdict = match ? "ok" : (sc.Pending != null || sc.Cells == 0 ? "none" : "MISMATCH");
                    Bridge.Log(r, "IMPOSTER cells=" + sc.Cells + " at=" + Pt(sc.X, sc.Y) + " expected=" + Pt(tx, ty) + AllCells(sc)
                                  + " viewTag=" + (sc.ViewTag ?? "null") + " polls=" + st.ScanPolls
                                  + (sc.Pending != null ? " pending=" + sc.Pending : "") + " via=" + Bridge.LastTransport() + " -> " + st.Verdict);
                    _imposterArArmed = true; // the next RenderMapToBuffer of this picker reports what AfterRender sees
                    r.Step = 3;
                    return 1;
                }
                if (r.Step == 3)
                {
                    string ar = _imposterArResult;
                    if (ar == null && ++st.ArWaitPolls < ImposterArWaitPolls) return 1;
                    _imposterArArmed = false;
                    int arCells = _imposterArCells;
                    Bridge.Log(r, "IMPOSTER-AFTERRENDER " + (ar ?? "not called within " + ImposterArWaitPolls + " polls")
                                  + (arCells > 0 ? " UNEXPECTED: AfterRender DOES see the reticle; the source reading above ImposterProbe is wrong"
                                     : ar == null ? " (informational)"
                                     : " (informational; cells=0 expected: AfterRender runs before PickTarget adds the reticle)"));
                    r.Step = 4;
                }
                o = Answer.PickerPush(r, PickTargetWindow.TargetMode.PickCells, "Command:CmdFire", () => Keyboard.PushCommand("CmdFire"));
                if (o == "pushed")
                {
                    Interlocked.Increment(ref r.AnswerCount);
                    return 2;
                }
                return 1;
            }, PickerEscape);
            Cell got = PickTarget.ShowPicker(PickTarget.PickStyle.EmptyCell, 0, 9999, c.X, c.Y, Locked: false, VisLevel: AllowVis.Any,
                                             Label: "[R5] probe:imposter", UseTarget: false);
            // Disarm whether or not it fired: a later RenderBaseToBuffer passes XRLCore._Buffer instead (XRL.Core/XRLCore.cs:2464,2508).
            _imposterArArmed = false;
            string verdict = st.Verdict;
            bool cellOk = got != null && got.X == tx && got.Y == ty;
            return Finish(run, before, cellOk && verdict == "ok", Pt(tx, ty),
                          (got == null ? "null" : Pt(got.X, got.Y)) + " imposter=" + verdict);
        }

        // Timeout recovery for getvk pickers only: Escape cancels both pickers (XRL.UI/PickDirection.cs:64-67, XRL.UI/PickTarget.cs:809-812).
        private static void PickerEscape(ProbeRun run)
        {
            string o;
            Bridge.RunOnUi(run, "picker-escape", () =>
            {
                if (GameManager.Instance.CurrentGameView != "PickTarget") return "not-in-picker";
                Keyboard.PushKey(UnityEngine.KeyCode.Escape);
                return "escape-pushed";
            }, 3000, out o);
            Bridge.Log(run, "RECOVERY picker Escape outcome=" + (o ?? "ui-task-failed"));
        }

        // ---------------- F2: conversation ----------------
        // Synthetic node through Popup.ShowConversation (XRL.UI/Popup.cs:1571-1616): PopupID "Conversation:"+Title, options
        // "option:i", result defaults to 0 (C-F2-conversation-07). The Title-only call binds to the IRenderable overload because the
        // GameObject overload (:1566) has no default for Context.
        private static bool ConvSynthetic()
        {
            const string name = "conv";
            if (!RequireModern(name)) return false;
            string[] before = Begin(name);
            ProbeRun run = Arm(name, (r, s) =>
            {
                if (s.Kind == "popup" && s.PopupID != null && s.PopupID.StartsWith("Conversation:", StringComparison.Ordinal)
                    && s.OptionCommands.Contains("option:1"))
                {
                    return Answer.PopupCommand(r, s, "option:1", true) ? 2 : 1;
                }
                return 0;
            }, null);
            int got = Popup.ShowConversation("[R5] probe:conv", Intro: "The answerer will choose the second option.",
                                             Options: new List<string> { "first", "second", "third" }, AllowTrade: false, AllowEscape: true);
            return Finish(run, before, got == 1, "1", got.ToString());
        }

        // Real conversation node answerer (08 R5-F2a). Never calls ConversationUI.Select itself (C-F2-conversation-04): the
        // path option:k -> ShowConversation result -> Render -> Select(k) on the game thread (XRL.UI/ConversationUI.cs:514-537)
        // is exercised and then VERIFIED at the next node:
        //   - token-changed: the next node's onHide token differs from the one we answered;
        //   - LastChoice: Select sets LastChoice = CurrentChoices[k] (:564), read in the next node's Classify UI task.
        // LastChoice cannot be checked after the conversation returns: HaveConversation's finally calls Reset() (:385-392),
        // which nulls it (:436-443). Choices whose Target is "End" sort last (Priority -= 999999, Choice.cs:42-55) and end
        // the conversation, so the first answers pick the first choice whose Target is neither empty (self-transition,
        // :592-595) nor "End"; after ConversationOptionAnswers answers the answerer uses Cancel (Escape(), :573-587) or the
        // last option. A navigating choice may have side effects (quests); run talk in a throwaway game.
        // R5-UNCERTAIN: C-F2-conversation-26 (end-to-end OnActivateCommand(menuData[k]) behaviour on a real conversation)
        private const int ConversationOptionAnswers = 3;

        private static int ConversationNode(ProbeRun r, Snap s)
        {
            if (s.Kind != "popup" || s.PopupID == null || !s.PopupID.StartsWith("Conversation:", StringComparison.Ordinal)) return 0;
            if (r.PendingToken != null && !ReferenceEquals(s.TokenOnHide, r.PendingToken))
            {
                bool lastOk = r.PendingChoice == null || ReferenceEquals(s.ConvLastChoice, r.PendingChoice);
                Bridge.Log(r, "conv node=" + (s.ConvNodeId ?? "null") + " token-changed=True token=#" + RuntimeHelpers.GetHashCode(s.TokenOnHide)
                              + " lastChoice=" + (s.ConvLastChoiceId ?? "null") + " expected=" + (r.PendingChoice == null ? "(cancel)" : (r.PendingChoiceId ?? "null"))
                              + " -> " + (lastOk ? "ok" : "BAD"));
                if (!lastOk) r.NodeChecksBad++;
                else if (r.PendingChoice != null) r.NodeChecksOk++;
                r.PendingToken = null;
                r.PendingChoice = null;
                r.PendingChoiceId = null;
            }
            if (r.AnswerCount >= MaxConversationAnswers) return 1; // let the timeout report it
            string cmd = null;
            object choice = null;
            string choiceId = null;
            if (r.AnswerCount < ConversationOptionAnswers)
            {
                for (int i = 0; i < s.ConvChoiceTargets.Count; i++)
                {
                    string t = s.ConvChoiceTargets[i];
                    if (!string.IsNullOrEmpty(t) && t != "End" && s.OptionCommands.Contains("option:" + i))
                    {
                        cmd = "option:" + i;
                        choice = s.ConvChoices[i];
                        choiceId = s.ConvChoiceIds[i];
                        break;
                    }
                }
            }
            if (cmd == null)
            {
                if (s.ButtonCommands.Contains("Cancel"))
                {
                    cmd = "Cancel";
                }
                else if (s.OptionCount > 0)
                {
                    int last = s.OptionCount - 1;
                    cmd = s.OptionCommands[last];
                    if (last < s.ConvChoices.Count) { choice = s.ConvChoices[last]; choiceId = s.ConvChoiceIds[last]; }
                }
            }
            if (cmd == null) return 1;
            if (Answer.PopupCommand(r, s, cmd, true))
            {
                r.PendingToken = s.TokenOnHide;
                r.PendingChoice = choice;
                r.PendingChoiceId = choiceId;
                Bridge.Log(r, "conv answered node=" + (s.ConvNodeId ?? "null") + " with " + cmd + " choice=" + (choiceId ?? "null"));
            }
            return 1; // the conversation ends only when the game thread returns
        }

        // Value criterion shared by conv-id and talk: every verified transition matched LastChoice, at least one did.
        private static bool ConversationVerdict(ProbeRun run, out string got)
        {
            if (run.PendingToken != null)
            {
                Bridge.Log(run, "conv end after " + (run.PendingChoice == null ? "Cancel" : "choice=" + (run.PendingChoiceId ?? "null"))
                                + " (not verifiable by LastChoice: Reset() nulls it, XRL.UI/ConversationUI.cs:391,443)");
            }
            got = "nodeOk=" + run.NodeChecksOk + " nodeBad=" + run.NodeChecksBad + " inConversationAfter=" + (ConversationUI.CurrentConversation != null);
            return run.NodeChecksBad == 0 && run.NodeChecksOk >= 1;
        }

        // conv:<ID> through the engine wish (XRL.World.Capabilities/Wishing.cs:52-57): speaker is not on the map, so no trade (C-F2-conversation-17).
        private static bool ConvById(string conversationId)
        {
            const string name = "conv-id";
            if (!RequireModern(name)) return false;
            string[] before = Begin(name);
            ProbeRun run = Arm(name, ConversationNode, null);
            Wishing.HandleWish(The.Player, "conv:" + conversationId);
            string got;
            bool ok = ConversationVerdict(run, out got);
            return Finish(run, before, ok, "nodeOk>=1 nodeBad=0", got);
        }

        // Returns null for four distinct reasons; each one is logged so that the caller's single "no reachable object"
        // precondition FAIL is diagnosable (run 1-3 finding: Tam was found but no adjacent cell was empty).
        private static GameObject FindAndApproach(string name, string blueprint)
        {
            GameObject player = The.Player;
            Zone zone = player == null ? null : player.CurrentZone;                  // XRL.World/GameObject.cs:525
            if (zone == null)
            {
                Bridge.Log("[" + name + "] player " + (player == null ? "is null" : "has no zone") + "; cannot look for " + blueprint);
                return null;
            }
            GameObject npc = zone.FindObject(blueprint);                             // XRL.World/Zone.cs:3446
            if (npc == null)
            {
                Bridge.Log("[" + name + "] target " + blueprint + " not found in zone " + zone.ZoneID);   // XRL.World/Zone.cs:440
                return null;
            }
            Cell nc = npc.CurrentCell;                                               // XRL.World/GameObject.cs:510
            if (nc == null)
            {
                Bridge.Log("[" + name + "] target " + blueprint + " found but has no CurrentCell");
                return null;
            }
            Cell pc = player.CurrentCell;
            int dist = Math.Max(Math.Abs(pc.X - nc.X), Math.Abs(pc.Y - nc.Y));
            if (dist > 1)
            {
                Cell dest = nc.GetFirstEmptyAdjacentCell();                          // XRL.World/Cell.cs:7207
                if (dest == null)
                {
                    Bridge.Log("[" + name + "] target " + blueprint + " found at (" + nc.X + "," + nc.Y + ") but no empty adjacent cell"
                               + " (player at (" + pc.X + "," + pc.Y + ") dist=" + dist + ")");
                    return null;
                }
                bool moved = player.SystemMoveTo(dest);                              // XRL.World/GameObject.cs:2807
                Bridge.Log("[" + name + "] moved next to " + blueprint + " ok=" + moved + " to=(" + dest.X + "," + dest.Y + ")");
            }
            return npc;
        }

        // Real conversation with a map NPC via ConversationScript.AttemptConversation() (XRL.World.Parts/ConversationScript.cs:528).
        private static bool TalkProbe(string blueprint)
        {
            const string name = "talk";
            if (!RequireModern(name)) return false;
            GameObject npc = FindAndApproach(name, blueprint);
            if (npc == null) return PreconditionFail(name, "no reachable object with blueprint \"" + blueprint + "\" in the current zone (pass probe:talk:<Blueprint>)");
            ConversationScript cs = npc.GetPart<ConversationScript>();               // XRL.World/GameObject.cs:9879
            if (cs == null) return PreconditionFail(name, blueprint + " has no ConversationScript");
            string[] before = Begin(name);
            ProbeRun run = Arm(name, ConversationNode, null);
            bool attempted = cs.AttemptConversation();
            string got;
            bool ok = ConversationVerdict(run, out got);
            return Finish(run, before, ok, "nodeOk>=1 nodeBad=0", "AttemptConversation=" + attempted + " " + got);
        }

        // ---------------- F5: trade ----------------
        // TradeUI.ShowTradeScreen (XRL.UI/TradeUI.cs:344) -> TradeScreen.show(...).Result (:456-463). Popups may appear first (:357-409).
        private static bool TradeProbe(string blueprint)
        {
            const string name = "trade";
            if (!RequireModern(name)) return false;
            GameObject npc = FindAndApproach(name, blueprint);
            if (npc == null) return PreconditionFail(name, "no reachable object with blueprint \"" + blueprint + "\" in the current zone (pass probe:trade:<Blueprint>)");
            string[] before = Begin(name);
            ProbeRun run = Arm(name, (r, s) =>
            {
                if (s.Kind == "trade")
                {
                    return Answer.TradeCancel(r, s) ? 2 : 1;
                }
                return 0;
            }, null);
            TradeUI.ShowTradeScreen(npc);
            return Finish(run, before, true, "returned", "returned");
        }

        // ---------------- F4: status screens ----------------
        // Screens.ShowPopup("Factions", GO) -> StatusScreensScreen.show(...).Result when ModernCharacterSheet && ModernUI (XRL.UI/Screens.cs:39-86).
        private static bool StatusProbe()
        {
            const string name = "status";
            if (!RequireModern(name)) return false;
            if (!Options.ModernCharacterSheet) return PreconditionFail(name, "Options.ModernCharacterSheet is false (XRL.UI/Screens.cs:45)");
            string[] before = Begin(name);
            ProbeRun run = Arm(name, (r, s) =>
            {
                if (s.Kind == "status")
                {
                    return Answer.StatusExit(r, s) ? 2 : 1;
                }
                return 0;
            }, null);
            Screens.ShowPopup("Factions", The.Player);
            return Finish(run, before, true, "returned", "returned");
        }

        // =====================================================================================================
        // R5-0 gate probes (08 section 6.1: if R5-0 fails, no other probe counts). README section 10.3.
        // =====================================================================================================

        // ---------------- R5-0d: async-void cancel (Hide FIRST, once, on a throwaway ShowYesNo) ----------------
        // Expected findings, not failures: got=Yes (ShowYesNo's default, XRL.UI/Popup.cs:2251-2276) and views=LEAKED
        // ("PopupMessage" left on the stack because PopGameView at :910 is skipped). PASS = the RESULT line is printed and
        // the UI tick is still alive 3 s later (the process survived the pool-thread rethrow, F-2). Run it LAST in its own
        // launch and relaunch the game afterwards; the operator also greps for "ERROR:" / "Exception" after BEGIN.
        private static bool CancelProbe()
        {
            const string name = "cancel";
            if (!RequireModern(name)) return false;
            string[] before = Begin(name);
            ProbeRun run = Arm(name, (r, s) =>
            {
                if (s.Kind == "popup" && !s.HasInput && s.ButtonCommands.Contains("Yes") && s.ButtonCommands.Contains("No")
                    && s.Detail.Contains("probe:cancel"))
                {
                    return Answer.HideFirst(r, s) ? 2 : 1;
                }
                return 0;
            }, null);
            DialogResult got = DialogResult.No;
            string thrown = "none";
            try
            {
                got = Popup.ShowYesNo("[R5] probe:cancel (R5-0d) - the answerer will call Hide() FIRST. Expect Yes and a leaked PopupMessage view.");
            }
            catch (Exception e)
            {
                thrown = e.GetType().Name;
            }
            run.ModalReturned = true;
            if (run.Thread != null) run.Thread.Join(3000);
            string[] after = GameManager.Instance.GetGameViewStackCopy();
            bool leaked = !SameStack(before, after);
            Thread.Sleep(3000);
            bool tickAfter = Bridge.TickAlive();
            bool pass = run.AnswerCount >= 1 && tickAfter;
            Bridge.Log(run, "RESULT r5=R5-0d got=" + got + " (Yes expected) thrownToCaller=" + thrown
                            + " views=" + (leaked ? "LEAKED" : "restored") + " (LEAKED expected) before=[" + string.Join(">", before) + "] after=[" + string.Join(">", after) + "]"
                            + " hidden=" + run.AnswerCount + " tickAliveAfter3s=" + tickAfter + " -> " + (pass ? "PASS" : "FAIL")
                            + " | relaunch the game before any other probe");
            return pass;
        }

        // ---------------- R5-0b: focus / runInBackground ----------------
        // probe:focus       = baseline (OptionMusicBackground decides runInBackground, XRL.UI/Options.cs:1445-1453).
        // probe:focus:force = mitigation of 08 section 3.8: while still focused, a UI task sets runInBackground=true, and every
        //                     tick rewrites XRLCore.bThreadFocus=true (GameManager.cs:3108-3113 sleeps 250 ms and returns when
        //                     it is false). GameManager.focused is NOT rewritten: its setter clears input on false->true
        //                     (GameManager.cs:404-418), and PlayerTurn still waits on it (XRL.Core/XRLCore.cs:737-740).
        // The wish returns at once; a monitor thread samples tick Hz from the tick counter (no UI task needed), and the
        // rib / P' values the tick stored. PASS (gate) = probe:focus:force with >=20 unfocused samples, avg >= 3.5 Hz and
        // P'=True at least once. Run both with OptionMusicBackground=Yes and =No.
        private static bool FocusProbe(string arg)
        {
            bool force = arg == "force";
            string name = force ? "focus:force" : "focus";
            Begin(name);
            string prevRib = null;
            if (force)
            {
                string o;
                if (!Bridge.RunOnUi(null, "focus-force-on", () =>
                    {
                        string p = UnityEngine.Application.runInBackground.ToString();
                        UnityEngine.Application.runInBackground = true;
                        Bridge.ForceThreadFocus = true;
                        return p;
                    }, 3000, out o))
                {
                    return PreconditionFail(name, "UI task did not run");
                }
                prevRib = o;
            }
            Bridge.Log("[" + name + "] unfocus the game window NOW (click another app) and keep it unfocused for ~35 s"
                       + (force ? "; mitigation on: runInBackground=true (was " + prevRib + "), bThreadFocus rewritten each tick" : "; baseline, no mitigation"));
            Thread t = new Thread(() => FocusMonitor(name, force, prevRib));
            t.IsBackground = true;
            t.Name = "R5-focus";
            t.Start();
            return true;
        }

        private static void FocusMonitor(string name, bool force, string prevRib)
        {
            try
            {
                Thread.Sleep(5000);
                int unfocused = 0, pTrue = 0;
                double hzSum = 0;
                int last = Bridge.TickFrames;
                for (int i = 0; i < 30; i++)
                {
                    Thread.Sleep(1000);
                    int now = Bridge.TickFrames;
                    int hz = now - last;
                    last = now;
                    bool foc = GameManager.focused;          // plain static, read as a hint (GameManager.cs:404)
                    bool tf = XRLCore.bThreadFocus;          // XRL.Core/XRLCore.cs:223
                    Bridge.Log("[" + name + "] t=" + (i + 1) + "s tickHz=" + hz + " focused=" + foc + " bThreadFocus=" + tf
                               + " rib=" + Bridge.LastRib + " P'=" + Bridge.LastPPrime + (hz == 0 ? " (rib/P' stale: tick not running)" : ""));
                    if (!foc)
                    {
                        unfocused++;
                        hzSum += hz;
                        if (hz > 0 && Bridge.LastPPrime == "True") pTrue++;
                    }
                }
                double avg = unfocused == 0 ? -1 : hzSum / unfocused;
                bool pass = unfocused >= 20 && avg >= 3.5 && (!force || pTrue >= 1);
                Bridge.Log("[" + name + "] RESULT r5=R5-0b unfocusedSamples=" + unfocused + " avgTickHz=" + avg.ToString("0.0") + " P'TrueSamples=" + pTrue
                           + " rib=" + Bridge.LastRib + " -> " + (pass ? "PASS" : "FAIL") + (force ? "" : " (baseline; the R5-0 gate uses probe:focus:force)"));
            }
            catch (Exception e)
            {
                Bridge.Log("[" + name + "] monitor EXCEPTION " + e);
            }
            finally
            {
                if (force)
                {
                    Bridge.ForceThreadFocus = false;
                    string o;
                    bool ran = Bridge.RunOnUi(null, "focus-force-off", () =>
                    {
                        bool v;
                        if (bool.TryParse(prevRib, out v)) UnityEngine.Application.runInBackground = v;
                        return UnityEngine.Application.runInBackground.ToString();
                    }, 5000, out o);
                    Bridge.Log("[" + name + "] mitigation off; runInBackground now=" + (ran ? o : "unknown (UI task did not run; refocus the window)"));
                }
            }
        }

        // ---------------- R5-0b-play: does PlayerTurn advance while the window is unfocused? ----------------
        // R5-0b only shows that the UI tick survives unfocus. The game thread's PlayerTurn also waits in
        // while (!GameManager.focused && Game.Running) Thread.Sleep(200) (XRL.Core/XRLCore.cs:737-740), which probe:focus:force
        // leaves alone. probe:focus:play = probe:focus:force (runInBackground=true, bThreadFocus rewritten each tick) PLUS the tick
        // rewrites the FIELD GameManager._focused=true while armed (GameManager.cs:118); the property setter is bypassed because it
        // clears input on false->true (GameManager.cs:404-418). GameManager.focusedEvent (:146) is only Set/Reset by that setter
        // (:421,:425) and has no reader, so it is left alone.
        // Once per second while Application.isFocused is false (read on the UI thread), no modal is up (view "Stage" and
        // Classify()=none) and P' holds with empty input queues, ONE Keyboard.PushCommand("CmdWait") is queued from a UI task, as the
        // engine itself does from the UI thread (GameManager.cs:2742; Keyboard.PushCommand -> PushMouseEvent locks the queue,
        // ConsoleLib.Console/Keyboard.cs:723-726, 825-849). PlayerTurn pops "Command:CmdWait" (XRL.Core/XRLCore.cs:763-779) and
        // passes the turn (:1517-1541; GameObject.PassTurn = UseEnergy(1000), XRL.World/GameObject.cs:18058-18061).
        // Turn counter: XRLGame.Turns (XRL/XRLGame.cs:58), incremented once per 10 segments = one game turn
        // (XRL.Core/ActionManager.cs:1653-1665); at Speed 100 one CmdWait (1000 energy) is one turn, so Speed is logged.
        // Not used: XRLCore.CurrentTurn returns TimeTicks (XRL.Core/XRLCore.cs:428-437), which wishes and terrain travel also bump
        // (XRL.World.Capabilities/Wishing.cs:4024-4028, XRL.World.Parts/TerrainTravel.cs:232); the EndPlayerTurn callback runs per
        // PlayerTurn loop iteration, not per action (XRL.Core/XRLCore.cs:2355-2359).
        // PASS = >= 10 unfocused samples AND Turns advanced >= 8 over 1 s intervals whose BOTH ends were unfocused samples (an
        // interval that straddles the refocus never counts). focusRewrites (ticks that found _focused false) is corroboration.
        // Operator: unfocus within ~12 s of the wish, keep it unfocused until the RESULT line (~35 s after the wish), then refocus.
        private static bool FocusPlayProbe()
        {
            const string name = "focus:play";
            Begin(name);
            int speed = The.Player == null ? -1 : The.Player.Speed; // game thread; XRL.World/GameObject.cs:544
            int rewrites0 = Bridge.FocusRewrites;
            string prevRib;
            if (!Bridge.RunOnUi(null, "focus-play-on", () =>
                {
                    string p = UnityEngine.Application.runInBackground.ToString();
                    UnityEngine.Application.runInBackground = true;
                    Bridge.ForceThreadFocus = true;
                    Bridge.ForceFocused = true;
                    return p;
                }, 3000, out prevRib))
            {
                return PreconditionFail(name, "UI task did not run");
            }
            Bridge.Log("[" + name + "] armed: unfocus the game window within ~12 s (click another app) and keep it unfocused until the RESULT line (~35 s after the wish)"
                       + "; mitigation on: runInBackground=true (was " + prevRib + "), bThreadFocus and GameManager._focused rewritten each tick"
                       + "; one CmdWait per second while unfocused; player Speed=" + speed + " turns=" + ReadTurns());
            Thread t = new Thread(() => FocusPlayMonitor(name, prevRib, speed, rewrites0));
            t.IsBackground = true;
            t.Name = "R5-focus-play";
            t.Start();
            return true;
        }

        private static long ReadTurns()
        {
            XRLGame g = The.Game;                                    // XRL/The.cs:19
            return g == null ? -1 : Interlocked.Read(ref g.Turns);   // XRL/XRLGame.cs:58 (written by the game thread)
        }

        // One UI task per unfocused sample; returns "pushed" or the skip reason.
        private static string FocusPlayPush()
        {
            string o;
            bool ran = Bridge.RunOnUi(null, "focus-play-push", () =>
            {
                if (UnityEngine.Application.isFocused) return "skip(focused)";
                GameManager gm = GameManager.Instance;
                // PlayerTurn sets the view to "Stage" each iteration (XRL.Core/XRLCore.cs:741, XRL.UI/Options.cs:1063).
                if (gm.CurrentGameView != Options.StageViewID) return "skip(view=" + gm.CurrentGameView + ")";
                Snap s = Bridge.Classify();
                if (s.Kind != "none") return "skip(modal=" + s.Kind + ")";
                if (!(gm._ActiveGameView == gm.CurrentGameView && !gm.bViewUpdated && XRLCore.bThreadFocus)) return "skip(P'-false)"; // GameManager.cs:238,248
                if (!(Keyboard.KeyQueue.Count == 0 && !Keyboard.HasMouseEvent())) return "skip(input-not-empty)";           // Keyboard.cs:108,865
                Keyboard.PushCommand("CmdWait");                                                                             // Keyboard.cs:723
                return "pushed";
            }, 900, out o);
            return ran ? o : "ui-task-failed";
        }

        private static void FocusPlayMonitor(string name, string prevRib, int speed, int rewrites0)
        {
            int unfocused = 0, pushes = 0;
            long turnsAdvanced = 0, turnsStart = -1, turnsEnd = -1;
            double hzSum = 0;
            try
            {
                // Nothing is pushed before the wish prompt is gone and DrainLeftoverInput (<= 400 ms) has finished.
                Thread.Sleep(5000);
                int last = Bridge.TickFrames;
                long prevTurns = ReadTurns();
                turnsStart = prevTurns;
                bool prevUnfocused = false;
                for (int i = 0; i < 30; i++)
                {
                    Thread.Sleep(1000);
                    int now = Bridge.TickFrames;
                    int hz = now - last;
                    last = now;
                    long turns = ReadTurns();
                    long delta = turns - prevTurns;
                    prevTurns = turns;
                    string app = Bridge.LastAppFocused;                // Application.isFocused as stored by the tick (UI thread)
                    bool unf = app == "False";
                    bool counted = prevUnfocused && unf && delta > 0;  // both ends of this interval unfocused
                    if (counted) turnsAdvanced += delta;
                    string push = "none(focused)";
                    if (unf)
                    {
                        unfocused++;
                        hzSum += hz;
                        push = FocusPlayPush();
                        if (push == "pushed") pushes++;
                    }
                    Bridge.Log("[" + name + "] t=" + (i + 1) + "s tickHz=" + hz + " appFocused=" + app
                               + " focused=" + GameManager.focused + " bThreadFocus=" + XRLCore.bThreadFocus   // plain statics, read as hints
                               + " P'=" + Bridge.LastPPrime + " turns=" + turns + " dTurns=" + delta + (counted ? "(counted)" : "")
                               + " rewrites=" + (Bridge.FocusRewrites - rewrites0) + " push=" + push
                               + (hz == 0 ? " (appFocused/P' stale: tick not running)" : ""));
                    prevUnfocused = unf;
                }
                turnsEnd = prevTurns;
                double avg = unfocused == 0 ? -1 : hzSum / unfocused;
                bool pass = unfocused >= 10 && turnsAdvanced >= 8;
                Bridge.Log("[" + name + "] RESULT r5=R5-0b-play unfocusedSamples=" + unfocused + " turnsAdvanced=" + turnsAdvanced + " pushes=" + pushes
                           + " avgTickHz=" + avg.ToString("0.0") + " -> " + (pass ? "PASS" : "FAIL")
                           + " | focusRewrites=" + (Bridge.FocusRewrites - rewrites0) + " turnsStart=" + turnsStart + " turnsEnd=" + turnsEnd + " speed=" + speed);
            }
            catch (Exception e)
            {
                Bridge.Log("[" + name + "] monitor EXCEPTION " + e);
            }
            finally
            {
                // Flags first, so no tick re-forces after the restore task; then restore on the UI thread. XRLCore.bThreadFocus is
                // left as the last forced value, exactly as probe:focus:force does (the next OnApplicationFocus rewrites it).
                Bridge.ForceFocused = false;
                Bridge.ForceThreadFocus = false;
                string o;
                bool ran = Bridge.RunOnUi(null, "focus-play-off", () =>
                {
                    bool v;
                    if (bool.TryParse(prevRib, out v)) UnityEngine.Application.runInBackground = v;
                    bool real = UnityEngine.Application.isFocused;
                    GameManager._focused = real; // the field, not the setter: no ClearInput (GameManager.cs:404-418)
                    return "runInBackground=" + UnityEngine.Application.runInBackground + " _focused=" + real + " (= Application.isFocused)";
                }, 5000, out o);
                Bridge.Log("[" + name + "] mitigation off; " + (ran ? o : "restore UI task did not run (GameManager._focused may stay true until the next focus change; refocus the window)"));
            }
        }

        // ---------------- R5-0e: a Unity getter off the UI thread ----------------
        // Informational (08 R5-0e): the design reads Unity state only inside UI tasks. PASS = the result line is printed.
        // R5-UNCERTAIN: C-F1-popup-17 (whether the bridge may touch Unity getters / windowsByName at all)
        private static bool OffThreadProbe()
        {
            const string name = "offthread";
            Begin(name);
            Thread t = new Thread(() =>
            {
                PopupMessage pm;
                if (!Bridge.RunOnUi(null, "offthread-get", () => UIManager.getWindow("PopupMessage") as PopupMessage, 3000, out pm) || pm == null)
                {
                    Bridge.Log("[offthread] RESULT FAIL precondition: PopupMessage window not found in a UI task");
                    return;
                }
                string res;
                try
                {
                    bool a = pm.gameObject.activeSelf;
                    res = "ok:" + a;
                }
                catch (Exception e)
                {
                    res = "exception:" + e.GetType().Name + ": " + e.Message;
                }
                Bridge.Log("[offthread][" + Bridge.ThreadTag() + "] RESULT r5=R5-0e offthread activeSelf=" + res + " -> PASS (informational)");
            });
            t.IsBackground = true;
            t.Name = "R5-offthread";
            t.Start();
            return true;
        }

        // ---------------- R5-0a: hotload keeps exactly one tick chain ----------------
        // wish "reload" runs HotloadConfiguration inside uiQueue.awaitTask (XRL.World.Capabilities/Wishing.cs:1006-1013), which
        // re-invokes [ModSensitiveCacheInit] in the SAME assembly (XRL.Core/XRLCore.cs:575-577, XRL/ModManager.cs:340-372).
        // Expected: a "tick already alive ... reason=init" line, the generation unchanged, and no frame with two live ticks.
        private static bool ReloadProbe()
        {
            const string name = "reload";
            Begin(name);
            int gen0 = Bridge.TickGen;
            int dup0 = Bridge.DupTicks;
            Bridge.Log("[reload] before gen=" + gen0 + " dupTicks=" + dup0 + " tickAlive=" + Bridge.TickAlive());
            Wishing.HandleWish(The.Player, "reload");
            Thread t = new Thread(() =>
            {
                Thread.Sleep(3000);
                int gen1 = Bridge.TickGen;
                int dup1 = Bridge.DupTicks;
                bool alive = Bridge.TickAlive();
                bool pass = gen1 == gen0 && dup1 == dup0 && alive;
                Bridge.Log("[reload] RESULT r5=R5-0a gen before=" + gen0 + " after=" + gen1 + " dupTicksDelta=" + (dup1 - dup0)
                           + " tickAlive=" + alive + " -> " + (pass ? "PASS" : "FAIL"));
            });
            t.IsBackground = true;
            t.Name = "R5-reload";
            t.Start();
            return true;
        }

        // =====================================================================================================
        // Additional family probes (08 section 6.2)
        // =====================================================================================================

        // ---------------- R5-F1b stale-token rejection ----------------
        // Two sync PickOptions in a row reuse the singleton window. After answering #1, the answerer replays #1's Snap
        // against #2: the onHide token differs, so the replay must return token-mismatch and #2 must stay open.
        private static bool StaleProbe()
        {
            const string name = "stale";
            if (!RequireModern(name)) return false;
            string[] before = Begin(name);
            ProbeRun run = Arm(name, (r, s) =>
            {
                if (s.Kind != "popup" || s.HasInput || s.PopupID != null) return 0;
                if (r.Step == 0 && s.Detail.Contains("probe:stale #1") && s.OptionCommands.Contains("option:1"))
                {
                    if (Answer.PopupCommand(r, s, "option:1", true))
                    {
                        r.Saved = s;
                        r.Step = 1;
                    }
                    return 1;
                }
                if (r.Step == 1 && s.Detail.Contains("probe:stale #2") && s.OptionCommands.Contains("option:2"))
                {
                    r.StaleOutcome = Answer.PopupCommandRaw(r, r.Saved, "option:0");
                    Bridge.Log(r, (r.StaleOutcome.StartsWith("token-mismatch", StringComparison.Ordinal) ? "stale-answer rejected" : "STALE ANSWER NOT REJECTED")
                                  + " outcome=" + r.StaleOutcome + " oldToken=#" + RuntimeHelpers.GetHashCode(r.Saved.TokenOnHide)
                                  + " newToken=#" + RuntimeHelpers.GetHashCode(s.TokenOnHide));
                    r.Step = 2;
                    return 1;
                }
                if (r.Step == 2 && s.Detail.Contains("probe:stale #2"))
                {
                    return Answer.PopupCommand(r, s, "option:2", true) ? 2 : 1;
                }
                return 1;
            }, null);
            List<string> opts = new List<string> { "alpha", "beta", "gamma" };
            int first = Popup.PickOption(Title: "[R5] probe:stale #1", Intro: "[R5] probe:stale #1 - the answerer will choose beta (1).", Options: opts, AllowEscape: true);
            int second = Popup.PickOption(Title: "[R5] probe:stale #2", Intro: "[R5] probe:stale #2 - a stale answer (alpha) must be rejected; then gamma (2).", Options: opts, AllowEscape: true);
            bool rejected = run.StaleOutcome != null && run.StaleOutcome.StartsWith("token-mismatch", StringComparison.Ordinal);
            return Finish(run, before, first == 1 && second == 2 && rejected, "1,2,stale=token-mismatch",
                          first + "," + second + ",stale=" + (run.StaleOutcome ?? "not-tried"));
        }

        // ---------------- R5-F1f death menu (Roleplay, checkpointing on) ----------------
        // CheckpointingSystem.ShowDeathMessage (XRL/CheckpointingSystem.cs:85-154): PickOption loop whose order depends on
        // OptionDefaultDeathToViewFinalMessages (:113-114), so choices are found by STRING. Sequence: "Retire character" ->
        // RETIRE AskString answered with Cancel ("" because ReturnNullForEscape:false, :135) -> the loop shows the menu again
        // (new token) -> "Reload from checkpoint" -> break -> QueueRestore() -> LoadCommand.Issue() (:152, :261-263).
        // Side effect: the checkpoint is reloaded. Not in probe:all; run it last.
        private static bool DeathProbe()
        {
            const string name = "death";
            if (!RequireModern(name)) return false;
            if (!CheckpointingSystem.IsCheckpointingEnabled()) return PreconditionFail(name, "checkpointing is off (start a Roleplay game; XRL/CheckpointingSystem.cs:165-173)");
            if (Options.AllowReallydie) return PreconditionFail(name, "Options.AllowReallydie is on (the DEBUG ShowYesNo at XRL/CheckpointingSystem.cs:106 would come first)");
            string[] before = Begin(name);
            ProbeRun run = Arm(name, (r, s) =>
            {
                if (s.Kind != "popup") return 0;
                int retire = s.OptionTexts.FindIndex(t => t.Contains("Retire character"));
                int reload = s.OptionTexts.FindIndex(t => t.Contains("Reload from checkpoint"));
                bool deathMenu = retire >= 0 && reload >= 0 && s.OptionCount == 4;
                if (r.Step == 0 && deathMenu)
                {
                    if (Answer.PopupCommand(r, s, s.OptionCommands[retire], true))
                    {
                        r.Saved = s;
                        r.Step = 1;
                    }
                    return 1;
                }
                if (r.Step == 1 && s.HasInput && s.WantsSpecificPrompt == "RETIRE")
                {
                    if (Answer.PopupCommand(r, s, "Cancel", true)) r.Step = 2;
                    return 1;
                }
                if (r.Step == 2 && deathMenu)
                {
                    Bridge.Log(r, "retire-loop ok newToken=" + !ReferenceEquals(s.TokenOnHide, r.Saved.TokenOnHide));
                    // Run 3 finding: the game thread wakes from PickOption inside OnActivateCommand, i.e. before
                    // PopupCommand returns, so Finish() could read Step==2 (RESULT ... got=True step=2 -> FAIL although the
                    // checkpoint reloaded). Record the step BEFORE dispatching and roll back only if the answer is refused.
                    r.Step = 3;
                    if (Answer.PopupCommand(r, s, s.OptionCommands[reload], true))
                    {
                        return 2;
                    }
                    r.Step = 2;
                    return 1;
                }
                return 0;
            }, null);
            bool ret = CheckpointingSystem.ShowDeathMessage("You died.\n\n[R5] probe:death (not a real death)");
            return Finish(run, before, ret && run.Step == 3, "true step=3 (Retire -> Cancel -> menu again -> Reload)", ret + " step=" + run.Step);
        }

        // ---------------- R5-F3d PickField ----------------
        // PickTarget.ShowFieldPicker is public static (XRL.UI/PickTarget.cs:84), so no Force Projector is needed. Keypad5 at
        // the start cell starts the field only when StartAdjacent is false (:322-336); Escape clears a started field, a
        // second Escape aborts (:165-186) and ReturnNullForAbort returns null (:371-375). currentText ("... Escape-Clear" when
        // started, "... Escape-Cancel" otherwise, :111) is written only under ModernUI (:117-119) and confirms each step.
        // Keypad5 / CmdTargetSelf are start/commit here, never cancel (08 section 2.3 PickField row).
        private static bool FieldProbe(bool cancel)
        {
            string name = cancel ? "field:cancel" : "field";
            if (!RequireModern(name)) return false;
            Cell c = The.Player == null ? null : The.Player.CurrentCell;
            if (c == null) return PreconditionFail(name, "player has no cell");
            Cell e = c.GetCellFromDirection("E");
            Cell next = e ?? c.GetCellFromDirection("W");
            if (next == null) return PreconditionFail(name, "no E/W neighbour cell");
            UnityEngine.KeyCode moveKey = e != null ? UnityEngine.KeyCode.Keypad6 : UnityEngine.KeyCode.Keypad4;
            string[] before = Begin(name);
            ProbeRun run = Arm(name, (r, s) =>
            {
                if (s.Kind != "picker" || s.Mode != PickTargetWindow.TargetMode.PickField) return 0;
                bool started = s.PickerText.Contains("Escape-Clear");
                string o;
                if (r.Step == 0)
                {
                    if (started) return 1;
                    o = Answer.PickerPush(r, PickTargetWindow.TargetMode.PickField, "Keypad5(start)", () => Keyboard.PushKey(UnityEngine.KeyCode.Keypad5));
                    if (o == "pushed") r.Step = 1;
                    return 1;
                }
                if (r.Step == 1)
                {
                    if (!started) return 1; // wait until the start was processed
                    o = cancel
                        ? Answer.PickerPush(r, PickTargetWindow.TargetMode.PickField, "Escape(clear)", () => Keyboard.PushKey(UnityEngine.KeyCode.Escape))
                        : Answer.PickerPush(r, PickTargetWindow.TargetMode.PickField, moveKey + "(extend)", () => Keyboard.PushKey(moveKey));
                    if (o == "pushed") r.Step = 2;
                    return 1;
                }
                if (r.Step == 2)
                {
                    if (cancel && started) return 1; // wait until the clear was processed
                    o = cancel
                        ? Answer.PickerPush(r, PickTargetWindow.TargetMode.PickField, "Escape(abort)", () => Keyboard.PushKey(UnityEngine.KeyCode.Escape))
                        : Answer.PickerPush(r, PickTargetWindow.TargetMode.PickField, "Keypad5(end)", () => Keyboard.PushKey(UnityEngine.KeyCode.Keypad5));
                    if (o == "pushed")
                    {
                        Interlocked.Increment(ref r.AnswerCount);
                        return 2;
                    }
                    return 1;
                }
                return 1;
            }, PickerEscape);
            List<Cell> got = PickTarget.ShowFieldPicker(3, 1, c.X, c.Y, What: "Wall", StartAdjacent: false, ReturnNullForAbort: true);
            string gotS = got == null ? "null" : DescribeCells(got);
            if (cancel) return Finish(run, before, got == null, "null", gotS);
            bool ok = got != null && got.Count == 2 && ReferenceEquals(got[0], c) && ReferenceEquals(got[1], next);
            return Finish(run, before, ok, "[(" + c.X + "," + c.Y + "),(" + next.X + "," + next.Y + ")]", gotS);
        }

        private static string DescribeCells(List<Cell> cells)
        {
            StringBuilder sb = new StringBuilder("[");
            for (int i = 0; i < cells.Count; i++)
            {
                sb.Append(i == 0 ? "" : ",").Append(cells[i] == null ? "null" : "(" + cells[i].X + "," + cells[i].Y + ")");
            }
            return sb.Append("]").ToString();
        }

        // ---------------- R5-F5b BookScreen ----------------
        // BookUI.ShowBook(string, string) (XRL.UI/BookUI.cs:500-511) -> ShowBook(MarkovBook) -> BookScreen.show(...).Result
        // under ModernUI (:462-466). Answer: Answer.BookCancel.
        private static bool BookProbe()
        {
            const string name = "book";
            if (!RequireModern(name)) return false;
            string[] before = Begin(name);
            ProbeRun run = Arm(name, (r, s) =>
            {
                if (s.Kind == "book")
                {
                    return Answer.BookCancel(r, s) ? 2 : 1;
                }
                return 0;
            }, null);
            BookUI.ShowBook("[R5] probe:book - the answerer reads the page count and calls Cancel().", "[R5] probe:book");
            return Finish(run, before, true, "returned", "returned");
        }

        // ---------------- R5-F5d tutorial overlay outside Tutorial mode ----------------
        // TutorialManager.ShowIntermissionPopupAsync (TutorialManager.cs:237-240) is the call the end-game coda uses
        // (XRL.UI/FadeText.cs:68-76); the game thread waits on the returned Task like EndGame.cs:495 waits on the coda.
        // The AnswererLoop's tutorial branch answers it (one press per PopupCompletion token). If TutorialManager.Update is
        // not running the Task never completes: the probe then applies the probe-only recovery and reports FAIL.
        private static bool TutorialProbe()
        {
            const string name = "tutorial";
            string pre;
            bool ran = Bridge.RunOnUi(null, "tutorial-precheck", () =>
            {
                TutorialManager tm = Bridge.TutorialInstance();
                if (tm == null) return "no-instance";
                return "activeSelf=" + tm.gameObject.activeSelf + " activeInHierarchy=" + tm.gameObject.activeInHierarchy
                       + " showing=" + Bridge.TutorialShowing(tm) + " latched=" + tm.popupAcceptPressed;
            }, 3000, out pre);
            if (!ran || pre == "no-instance")
            {
                return PreconditionFail(name, "TutorialManager.instance is null or the UI task did not run (instance is set only in Start(), TutorialManager.cs:149-155): " + (pre ?? "ui-task-failed"));
            }
            Bridge.Log("[tutorial] precheck " + pre);
            string[] before = Begin(name);
            int[] afterRan = { 0 };
            ProbeRun run = Arm(name, (r, s) => 0, null, true); // the AnswererLoop tutorial branch answers and counts the target
            bool done = false;
            string err = "none";
            try
            {
                Task t = TutorialManager.ShowIntermissionPopupAsync("[R5] probe:tutorial - the answerer presses Accept once", () => Interlocked.Exchange(ref afterRan[0], 1));
                done = t.Wait(ProbeTimeoutMs + AnswerDelayMs + 2000);
            }
            catch (AggregateException ae)
            {
                err = (ae.InnerException ?? ae).GetType().Name;
            }
            if (!done)
            {
                Bridge.Log("[tutorial] popup not released: tutorial Update not running or no answer (err=" + err + ")");
                Answer.TutorialRecovery(run);
            }
            return Finish(run, before, done, "released", "released=" + done + " after=" + (Volatile.Read(ref afterRan[0]) == 1) + " err=" + err);
        }

        // ---------------- R5-F6a EndPlayerTurn intake (and the EndPlayerTurn trigger of 08 section 6.1) ----------------
        // XRLCore.RegisterOnEndPlayerTurnCallback (XRL.Core/XRLCore.cs:614-624) runs every PlayerTurn iteration (:2355-2359).
        // probe:endturn        : at the next callback with Energy >= 1000, push Command:CmdWish (Keyboard.cs:723-726). Expected
        //                        consumed (the wish prompt of WishManager.AskWish, XRL.Wish/WishManager.cs:107-109, appears and is
        //                        cancelled).
        // probe:endturn:spent  : arm, then the operator takes one energy-spending action; the push happens with Energy < 1000
        //                        and is expected to be DROPPED by ClearMouseEvents at the next PlayerTurn entry (:733-735).
        // probe:endturn:run:<p>: at the next callback with Energy >= 1000, dispatch probe:<p> from the callback (the trigger
        //                        08 section 6.1 names). Dispatch still refuses a non-game thread.
        // The callback is registered once (no hotload re-registration: a second assembly would add a second callback).
        // R5-UNCERTAIN: C-F6-threads-hooks-14 (条件付き: which iterations read an End-pushed command is decided at runtime)
        private static volatile int _endTurnMode;   // 0 off, 1 waiting push, 2 spent push, 3 dispatch
        private static volatile string _endTurnProbe;
        private static bool _endTurnRegistered;     // game thread only

        private static bool EndTurnProbe(string arg)
        {
            if (!_endTurnRegistered)
            {
                XRLCore.RegisterOnEndPlayerTurnCallback(EndTurnCallback);
                _endTurnRegistered = true;
            }
            if (arg != null && arg.StartsWith("run:", StringComparison.Ordinal))
            {
                _endTurnProbe = arg.Substring(4);
                _endTurnMode = 3;
                Bridge.Log("[endturn] armed: the next EndPlayerTurn callback with Energy>=1000 dispatches probe:" + _endTurnProbe);
                return true;
            }
            _endTurnMode = arg == "spent" ? 2 : 1;
            Bridge.Log("[endturn] armed mode=" + (arg == "spent" ? "spent: now take ONE action that spends energy (move one cell)" : "waiting"));
            return true;
        }

        private static void EndTurnCallback(XRLCore core)
        {
            int mode = _endTurnMode;
            if (mode == 0) return;
            int energy = The.Player == null || The.Player.Energy == null ? -1 : The.Player.Energy.Value; // XRL.World/GameObject.cs:140
            if ((mode == 1 || mode == 3) && energy < 1000) return;
            if (mode == 2 && energy >= 1000) return;
            _endTurnMode = 0;
            string thread = Bridge.ThreadTag();
            if (mode == 3)
            {
                string p = _endTurnProbe;
                Bridge.Log("[endturn][" + thread + "] dispatching probe:" + p + " from EndPlayerTurn energy=" + energy);
                try { Dispatch(p ?? ""); }
                catch (Exception ex) { Bridge.Log("[endturn] dispatch EXCEPTION " + ex); }
                return;
            }
            string label = mode == 1 ? "waiting" : "spent";
            bool expected = mode == 1;
            ProbeRun run = Arm("endturn:" + label, (r, s) =>
            {
                if (s.Kind == "popup" && s.HasInput && s.Detail.Contains("Your wish is my command"))
                {
                    return Answer.PopupCommand(r, s, "Cancel", true) ? 2 : 1;
                }
                return 0;
            }, null);
            Keyboard.PushCommand("CmdWish");
            Bridge.Log(run, "pushed Command:CmdWish from EndPlayerTurn mode=" + label + " energy=" + energy + " thread=" + thread);
            Thread w = new Thread(() =>
            {
                System.Diagnostics.Stopwatch sw = System.Diagnostics.Stopwatch.StartNew();
                while (sw.ElapsedMilliseconds < 8000 && Volatile.Read(ref run.AnswerCount) == 0) Thread.Sleep(100);
                bool consumed = Volatile.Read(ref run.AnswerCount) > 0;
                run.ModalReturned = true;
                Bridge.Log(run, "RESULT r5=R5-F6a endturn push consumed=" + consumed + " energy=" + energy + " expected=" + expected
                                + " -> " + (consumed == expected ? "PASS" : "FAIL"));
            });
            w.IsBackground = true;
            w.Name = "R5-endturn-watch";
            w.Start();
        }

        // ---------------- R5-F7a map from AfterRender ----------------
        // XRLCore.RegisterAfterRenderCallback (XRL.Core/XRLCore.cs:652-655) has no Remove API: register once, arm per wish.
        // The callback gets the render buffer (:2430-2433). ASCII profile: glyphs are in Char; BackupChar is the tile-mode
        // fallback character (ConsoleLib.Console/ConsoleChar.cs:65, 406). Both are counted.
        // R5-UNCERTAIN: C-F7-observation-12 (AfterRender frequency / which buffer is passed)
        private static volatile bool _mapArmed;
        private static bool _mapRegistered; // game thread only

        private static bool MapProbe()
        {
            if (!_mapRegistered)
            {
                XRLCore.RegisterAfterRenderCallback(AfterRenderMap);
                _mapRegistered = true;
            }
            _mapArmed = true;
            Bridge.Log("[map] armed: the next AfterRender callback counts glyphs (move one cell if nothing is logged)");
            return true;
        }

        private static void AfterRenderMap(XRLCore core, ScreenBuffer buf)
        {
            if (!_mapArmed) return;
            _mapArmed = false;
            try
            {
                System.Diagnostics.Stopwatch sw = System.Diagnostics.Stopwatch.StartNew();
                int backup = 0, chars = 0;
                for (int x = 0; x < buf.Width; x++)
                {
                    for (int y = 0; y < buf.Height; y++)
                    {
                        ConsoleChar ch = buf[x, y];                   // ConsoleLib.Console/ScreenBuffer.cs:103-116
                        if (ch == null) continue;
                        if (ch.BackupChar != '\0') backup++;
                        if (ch.Char != ' ' && ch.Char != '\0') chars++;
                    }
                }
                Bridge.Log("[map][" + Bridge.ThreadTag() + "] RESULT r5=R5-F7a size=" + buf.Width + "x" + buf.Height + " glyphs(Char)=" + chars
                           + " glyphs(BackupChar)=" + backup + " ms=" + sw.ElapsedMilliseconds + " -> " + (chars > 0 || backup > 0 ? "PASS" : "FAIL"));
            }
            catch (Exception ex)
            {
                Bridge.Log("[map] EXCEPTION " + ex);
            }
        }
    }
}
