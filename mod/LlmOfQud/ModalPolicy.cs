// Pure modal policy: no Unity / engine types. Shared by ModalDriver (game) and mod/modal-tests (dotnet).
// C# 9 only (the game compiles mods with Roslyn C# 9).
using System;
using System.Collections.Generic;
using System.Runtime.CompilerServices;
using System.Text;
using Newtonsoft.Json.Linq;

namespace LlmOfQud
{
    // Plain snapshot of the topmost modal, filled on the UI thread by ModalDriver (or by tests).
    public sealed class ModalSnapshot
    {
        public string Type = "unknown";      // popup, conversation, string, number, direction, cell, field, pick_item, book, trade, status, terminal, summary, tutorial, unknown
        public string InputKind = "none";    // none, string, number, direction, cell, field
        public object Identity;              // engine identity (onHide / menucomplete / PopupCompletion / picker episode)
        public string Title = "";
        public string Text = "";
        public string View = "";
        public string PopupID;
        public string WantsSpecificPrompt;
        public string RestrictChars;
        public bool HasInput;
        public bool Ready = true;            // false: detected but not answerable yet (e.g. screen not current)
        public bool CheckpointingEnabled;
        public int? Min, Max;
        public List<string> ItemLabels = new List<string>();     // menuData[i] (stripped)
        public List<string> ItemCommands = new List<string>();
        public HashSet<int> BlockedItems = new HashSet<int>();   // semantic conversation actions such as Trade
        public List<string> ButtonLabels = new List<string>();   // bottomContextOptions[j] (stripped)
        public List<string> ButtonCommands = new List<string>();
        public List<string> ButtonHotkeys = new List<string>();
    }

    public sealed class ModalChoice
    {
        public string Id, Label, Family, Command; // Family: "item" | "button"; Index is encoded in Id
        public int Index;
    }

    // What the driver publishes / answers. Built once per token.
    public sealed class ModalView
    {
        public string Token;
        public object Identity;
        public ModalSnapshot Snap;
        public List<ModalChoice> Choices = new List<ModalChoice>();
        public JObject Constraints = new JObject();
        public string Rule;       // non-null: handled by a system rule, never published to the LLM
        public string RuleChoice; // choice id the rule activates ("cancel", "button:0", "option:1", "accept", "screen_cancel")
        public long FirstSeenMs;
        public long Seq; // stamped by ModalLedger.Publish; answers must echo the seq of the modal event

        public JObject ToDto()
        {
            JArray choices = new JArray();
            foreach (ModalChoice c in Choices) choices.Add(new JObject { ["id"] = c.Id, ["label"] = c.Label });
            return new JObject
            {
                ["type"] = Snap.Type,
                ["title"] = Snap.Title ?? "",
                ["text"] = Snap.Text ?? "",
                ["choices"] = choices,
                ["input_kind"] = Snap.InputKind,
                ["constraints"] = Constraints.DeepClone(),
            };
        }
    }

    // Parsed, validated answer (plain data; bounded).
    public sealed class ModalAnswer
    {
        public string RunId, Token;
        public long Seq;
        public long AnswerId;
        public string Kind;        // choice | text | number | direction | target | field | cancel
        public string Choice, Text, Direction;
        public int Number, X, Y;
        public List<int[]> Field;
    }

    public static class ModalPolicy
    {
        public const int MaxTextLength = 200;     // AskStringAsync does not enforce MaxLength (Popup.cs:1371-1400); our own cap
        public const int MaxFieldCells = 40;
        public const int MaxQueuedAnswers = 8;
        public const int MaxFrameChars = 4096;
        public const int MaxLabel = 240, MaxText = 4000;
        public static readonly string[] Compass = { "N", "NE", "E", "SE", "S", "SW", "W", "NW" };
        public static readonly string[] DeathLabels = { "Reload from checkpoint", "View final messages", "Retire character", "Quit to main menu" };
        // Buttons that are never exposed: trade (unsupported transaction), Look (nested screen), CmdOptions (refused by
        // OnActivateCommand, PopupMessage.cs:928), Color (color picker).
        private static readonly string[] HiddenCommands = { "trade", "Look", "CmdOptions", "Color" };

        // answersSuspended: the controlled game stopped running (ModalLedger.AnswersSuspended). Its menus (e.g. MainMenu
        // after save_quit) are not active-play modals; system rules such as the death reload still run meanwhile.
        public static bool ShouldWatchdog(string view, string stage, bool ready, bool ending, bool answersSuspended)
        {
            return !answersSuspended && !ending && !ready && !string.IsNullOrEmpty(view) && view != stage && view != "GameSummary";
        }

        public static bool FieldSelectionStarted(string text)
        {
            return Strip(text).Contains("Escape-Clear");
        }

        public static bool FieldPromptReady(string text)
        {
            string plain = Strip(text);
            return plain.Contains("Escape-Cancel") || plain.Contains("Escape-Clear");
        }

        // ---------------- text helpers ----------------
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

        // Option labels from ShowConversation carry a "[n] " hotkey prefix and trailing blank lines (Popup.cs:1588-1592).
        public static string CleanLabel(string s)
        {
            string t = Collapse(Strip(s));
            // "[a] " from PickOption hotkeys (Popup.cs:2041) or "[1] " from ShowConversation (Popup.cs:1590)
            if (t.Length >= 4 && t[0] == '[')
            {
                int close = t.IndexOf(']');
                if (close > 1 && close <= 3 && close + 1 < t.Length && t[close + 1] == ' ') t = t.Substring(close + 2).TrimStart();
            }
            return Clip(t, MaxLabel);
        }

        public static string Clip(string s, int max) { return s == null ? "" : (s.Length <= max ? s : s.Substring(0, max)); }

        // ---------------- classification of system rules ----------------
        // Returns the rule name, or null when the LLM must answer. ruleChoice receives the choice id to activate.
        public static string Rule(ModalSnapshot s, out string ruleChoice)
        {
            ruleChoice = null;
            string text = Collapse(Strip(s.Text));
            string title = Collapse(Strip(s.Title));
            if (s.Type == "tutorial") { ruleChoice = "accept"; return "tutorial_accept"; }
            if (s.Type == "book" || s.Type == "trade" || s.Type == "status") { ruleChoice = "screen_cancel"; return "screen_cancel"; }
            if (s.Type != "popup" && s.Type != "string" && s.Type != "conversation" && s.Type != "number") return null;
            // wish prompts (WishManager.cs:109, WishMenu.cs:146)
            if (s.HasInput && text.StartsWith("Your wish is my command!", StringComparison.Ordinal)) { ruleChoice = CancelId(s); return ruleChoice == null ? "wish_unanswerable" : "wish_cancel"; }
            if (!s.HasInput && title == "Wish Menu") { ruleChoice = CancelId(s); return ruleChoice == null ? "wish_unanswerable" : "wish_cancel"; }
            // destructive confirmations: RETIRE (CheckpointingSystem.cs:135), ABANDON / QUIT (XRLCore.cs:995,1751), CROSS (ThinWorld.cs:62)
            if (s.HasInput)
            {
                string w = s.WantsSpecificPrompt;
                bool destructive = w == "RETIRE" || w == "ABANDON" || w == "QUIT" || w == "CROSS"
                    || text.IndexOf("Type 'CROSS' to confirm", StringComparison.OrdinalIgnoreCase) >= 0
                    || text.IndexOf("Type 'ABANDON' to confirm", StringComparison.OrdinalIgnoreCase) >= 0
                    || text.IndexOf("Type 'RETIRE' to confirm", StringComparison.OrdinalIgnoreCase) >= 0
                    || text.IndexOf("Type 'QUIT' to confirm", StringComparison.OrdinalIgnoreCase) >= 0;
                if (destructive) { ruleChoice = CancelId(s); return ruleChoice == null ? "destructive_unanswerable" : "destructive_cancel"; }
            }
            // Roleplay death menu (CheckpointingSystem.cs:111-114): exact 4-label set, empty title, no input, checkpointing on.
            if (s.CheckpointingEnabled && !s.HasInput && title.Length == 0 && s.ItemLabels.Count == 4)
            {
                bool[] seen = new bool[4];
                int reload = -1;
                bool exact = true;
                for (int i = 0; i < 4; i++)
                {
                    int k = Array.IndexOf(DeathLabels, CleanLabel(s.ItemLabels[i]));
                    if (k < 0 || seen[k]) { exact = false; break; }
                    seen[k] = true;
                    if (k == 0) reload = i;
                }
                if (exact && reload >= 0) { ruleChoice = "option:" + reload; return "death_reload_checkpoint"; }
            }
            // single Accept notice: no items, no input, exactly one button whose command is Accept (PopupMessage._SingleButton :79-87)
            if (!s.HasInput && s.ItemLabels.Count == 0 && s.ButtonCommands.Count == 1 && s.ButtonCommands[0] == "Accept")
            {
                ruleChoice = "button:0";
                return "notice_accept";
            }
            return null;
        }

        private static string CancelId(ModalSnapshot s)
        {
            for (int j = 0; j < s.ButtonCommands.Count; j++) if (s.ButtonCommands[j] == "Cancel") return "button:" + j;
            return null;
        }

        // Choices from actual item positions; hidden commands and null/empty labels are omitted.
        public static List<ModalChoice> Choices(ModalSnapshot s)
        {
            List<ModalChoice> list = new List<ModalChoice>();
            if (s.Type == "pick_item")
            {
                for (int i = 0; i < s.ItemLabels.Count; i++)
                    list.Add(new ModalChoice { Id = "option:" + i, Label = CleanLabel(s.ItemLabels[i]), Family = "item", Index = i, Command = null });
                return list;
            }
            if (s.Type != "popup" && s.Type != "conversation") return list;
            for (int i = 0; i < s.ItemLabels.Count && i < s.ItemCommands.Count; i++)
            {
                if (s.BlockedItems.Contains(i)) continue;
                if (s.ItemLabels[i] == null || s.ItemCommands[i] == null) continue;
                if (Array.IndexOf(HiddenCommands, s.ItemCommands[i]) >= 0) continue;
                list.Add(new ModalChoice { Id = "option:" + i, Label = CleanLabel(s.ItemLabels[i]), Family = "item", Index = i, Command = s.ItemCommands[i] });
            }
            for (int j = 0; j < s.ButtonLabels.Count && j < s.ButtonCommands.Count; j++)
            {
                if (s.ButtonLabels[j] == null || s.ButtonCommands[j] == null) continue;
                if (Array.IndexOf(HiddenCommands, s.ButtonCommands[j]) >= 0) continue;
                list.Add(new ModalChoice { Id = "button:" + j, Label = CleanLabel(s.ButtonLabels[j]), Family = "button", Index = j, Command = s.ButtonCommands[j] });
            }
            return list;
        }

        public static JObject Constraints(ModalSnapshot s)
        {
            JObject c = new JObject();
            if (s.InputKind == "number")
            {
                if (s.Min.HasValue) c["min"] = s.Min.Value;
                if (s.Max.HasValue) c["max"] = s.Max.Value;
                if (!string.IsNullOrEmpty(s.RestrictChars)) c["restrict_chars"] = s.RestrictChars;
            }
            else if (s.InputKind == "string")
            {
                if (!string.IsNullOrEmpty(s.WantsSpecificPrompt)) c["required_text"] = s.WantsSpecificPrompt;
                c["max"] = MaxTextLength; // max length of the text (our cap)
            }
            return c;
        }

        public static ModalView Build(ModalSnapshot s, string token, long nowMs)
        {
            ModalView v = new ModalView { Token = token, Identity = s.Identity, Snap = s, FirstSeenMs = nowMs };
            string rc;
            v.Rule = Rule(s, out rc);
            v.RuleChoice = rc;
            v.Choices = Choices(s);
            v.Constraints = Constraints(s);
            s.Title = Clip(Collapse(s.Title), MaxLabel);
            s.Text = Clip(s.Text ?? "", MaxText);
            return v;
        }

        // ---------------- answers ----------------
        // Shape-only parse (bridge thread). Returns null + reason on failure.
        public static ModalAnswer Parse(JObject frame, out string reason)
        {
            reason = null;
            if (frame == null) { reason = "no_frame"; return null; }
            if (frame.ToString(Newtonsoft.Json.Formatting.None).Length > MaxFrameChars) { reason = "frame_too_large"; return null; }
            if ((string)frame["kind"] != "modal_answer") { reason = "wrong_kind"; return null; }
            JToken run = frame["run_id"], seq = frame["seq"], token = frame["token"], aid = frame["answer_id"];
            if (run == null || run.Type != JTokenType.String) { reason = "bad_run_id"; return null; }
            if (seq == null || seq.Type != JTokenType.Integer) { reason = "bad_seq"; return null; }
            if (token == null || token.Type != JTokenType.String) { reason = "bad_token"; return null; }
            if (aid == null || aid.Type != JTokenType.Integer) { reason = "bad_answer_id"; return null; }
            JObject resp = frame["response"] as JObject;
            if (resp == null || resp.Count != 1) { reason = "response_must_have_one_key"; return null; }
            ModalAnswer a = new ModalAnswer { RunId = (string)run, Seq = (long)seq, Token = (string)token, AnswerId = (long)aid };
            JProperty p = resp.First as JProperty;
            JToken v = p.Value;
            switch (p.Name)
            {
                case "choice":
                    if (v.Type != JTokenType.String) { reason = "bad_choice"; return null; }
                    a.Kind = "choice"; a.Choice = (string)v; break;
                case "text":
                    if (v.Type != JTokenType.String) { reason = "bad_text"; return null; }
                    a.Kind = "text"; a.Text = (string)v; break;
                case "number":
                    if (v.Type != JTokenType.Integer) { reason = "bad_number"; return null; }
                    long n = (long)v;
                    if (n < int.MinValue || n > int.MaxValue) { reason = "number_out_of_int"; return null; }
                    a.Kind = "number"; a.Number = (int)n; break;
                case "direction":
                    if (v.Type != JTokenType.String || Array.IndexOf(Compass, (string)v) < 0) { reason = "bad_direction"; return null; }
                    a.Kind = "direction"; a.Direction = (string)v; break;
                case "target":
                    int tx, ty;
                    if (!Xy(v, out tx, out ty)) { reason = "bad_target"; return null; }
                    a.Kind = "target"; a.X = tx; a.Y = ty; break;
                case "field":
                    JArray arr = v as JArray;
                    if (arr == null || arr.Count == 0 || arr.Count > MaxFieldCells) { reason = "bad_field"; return null; }
                    a.Kind = "field"; a.Field = new List<int[]>();
                    foreach (JToken cell in arr)
                    {
                        int fx, fy;
                        if (!Xy(cell, out fx, out fy)) { reason = "bad_field"; return null; }
                        a.Field.Add(new[] { fx, fy });
                    }
                    break;
                case "cancel":
                    if (v.Type != JTokenType.Boolean || !(bool)v) { reason = "bad_cancel"; return null; }
                    a.Kind = "cancel"; break;
                default:
                    reason = "unknown_response"; return null;
            }
            return a;
        }

        private static bool Xy(JToken t, out int x, out int y)
        {
            x = y = 0;
            JObject o = t as JObject;
            if (o == null || o.Count != 2) return false;
            JToken jx = o["x"], jy = o["y"];
            if (jx == null || jy == null || jx.Type != JTokenType.Integer || jy.Type != JTokenType.Integer) return false;
            long lx = (long)jx, ly = (long)jy;
            if (lx < 0 || ly < 0 || lx > 79 || ly > 24) return false; // zone is 80x25
            x = (int)lx; y = (int)ly;
            return true;
        }

        // Semantic validation against the published view. Pure; called on the bridge thread (early reject) and again on the
        // UI thread (authoritative). Returns null when valid.
        public static string Validate(ModalAnswer a, ModalView v, string runId, long seq)
        {
            if (v == null) return "no_pending_modal";
            if (a.RunId != runId) return "stale_run";
            if (a.Seq != seq) return "stale_seq";
            if (a.Token != v.Token) return "stale_token";
            if (v.Rule != null) return "system_rule_modal";
            if (!v.Snap.Ready) return "modal_not_ready";
            string ik = v.Snap.InputKind;
            switch (a.Kind)
            {
                case "cancel":
                    if (ik == "direction" || ik == "cell" || ik == "field" || v.Snap.Type == "pick_item") return null;
                    if (v.Snap.PopupID == "AskNumberScreen") return null;
                    return HasCancelButton(v.Snap) ? null : "no_cancel_button";
                case "choice":
                    if (ik != "none") return "response_type_mismatch";
                    foreach (ModalChoice c in v.Choices) if (c.Id == a.Choice) return null;
                    return "unknown_choice";
                case "text":
                    if (ik != "string") return "response_type_mismatch";
                    if (a.Text.Length > MaxTextLength) return "text_too_long";
                    foreach (char ch in a.Text) if (char.IsControl(ch)) return "text_contains_control";
                    if (!string.IsNullOrEmpty(v.Snap.WantsSpecificPrompt) && a.Text != v.Snap.WantsSpecificPrompt) return "required_text_mismatch";
                    return null;
                case "number":
                    if (ik != "number") return "response_type_mismatch";
                    if (v.Snap.Min.HasValue && a.Number < v.Snap.Min.Value) return "below_min";
                    if (v.Snap.Max.HasValue && a.Number > v.Snap.Max.Value) return "above_max";
                    if (!string.IsNullOrEmpty(v.Snap.RestrictChars))
                        foreach (char ch in a.Number.ToString()) if (v.Snap.RestrictChars.IndexOf(ch) < 0) return "restrict_chars";
                    return null;
                case "direction":
                    return ik == "direction" ? null : "response_type_mismatch";
                case "target":
                    return ik == "cell" ? null : "response_type_mismatch";
                case "field":
                    if (ik != "field") return "response_type_mismatch";
                    for (int i = 1; i < a.Field.Count; i++)
                    {
                        int dx = a.Field[i][0] - a.Field[i - 1][0], dy = a.Field[i][1] - a.Field[i - 1][1];
                        if (Math.Max(Math.Abs(dx), Math.Abs(dy)) != 1) return "field_not_contiguous";
                        for (int k = 0; k < i; k++) if (a.Field[k][0] == a.Field[i][0] && a.Field[k][1] == a.Field[i][1]) return "field_repeats_cell";
                    }
                    return null;
            }
            return "unknown_response";
        }

        private static bool HasCancelButton(ModalSnapshot s)
        {
            return s.ButtonCommands.Contains("Cancel");
        }

        public static string DirectionFrom(int dx, int dy)
        {
            if (dx == 0 && dy == -1) return "N";
            if (dx == 1 && dy == -1) return "NE";
            if (dx == 1 && dy == 0) return "E";
            if (dx == 1 && dy == 1) return "SE";
            if (dx == 0 && dy == 1) return "S";
            if (dx == -1 && dy == 1) return "SW";
            if (dx == -1 && dy == 0) return "W";
            if (dx == -1 && dy == -1) return "NW";
            return null;
        }
    }

    // Token registry keyed by engine object identity. UI thread only (ModalLedger locks around it).
    public sealed class ModalTokens
    {
        private object _identity;
        private string _token;
        private long _counter;
        private string _prefix = "r0";

        public void Reset(string prefix) { _identity = null; _token = null; _prefix = prefix ?? "r0"; }

        // Same identity -> same token (harmless redraws); new identity -> new token.
        public string For(object identity, out bool isNew)
        {
            if (identity != null && ReferenceEquals(identity, _identity)) { isNew = false; return _token; }
            _identity = identity;
            _counter++;
            _token = _prefix + "-m" + _counter;
            isNew = true;
            return _token;
        }

        public object CurrentIdentity { get { return _identity; } }
        public string CurrentToken { get { return _token; } }
        public void Forget() { _identity = null; _token = null; }
    }

    // Thread-safe ledger of the published modal and answers: validation before claim, bounded queue, duplicate detection,
    // at most one success per token. Pure; unit-tested.
    public sealed class ModalDrop
    {
        public ModalAnswer Answer;
        public string Reason;
    }

    public sealed class ModalLedger
    {
        private readonly List<ModalDrop> _dropped = new List<ModalDrop>();
        private readonly object _lock = new object();
        private readonly Queue<ModalAnswer> _queue = new Queue<ModalAnswer>();
        private readonly Queue<long> _seenIds = new Queue<long>();
        private readonly HashSet<long> _seenSet = new HashSet<long>();
        private readonly HashSet<string> _succeeded = new HashSet<string>();
        private readonly Queue<string> _succeededOrder = new Queue<string>();
        private string _runId;
        private long _seq;
        private bool _active;
        private bool _answersSuspended;
        private ModalView _published;
        private string _claimed; // token currently claimed by an in-flight UI callback
        private long _generation;  // bumped whenever run change / inactive wipes the state

        public void SetContext(string runId, long seq, bool active)
        {
            lock (_lock)
            {
                if (runId != _runId || seq != _seq || !active) _answersSuspended = false;
                if (runId != _runId || !active) { Drop("context_reset"); _published = null; _claimed = null; _generation++; }
                _runId = runId; _seq = seq; _active = active;
            }
        }

        public void Context(out string runId, out long seq, out bool active)
        {
            lock (_lock) { runId = _runId; seq = _seq; active = _active; }
        }

        public void Publish(ModalView v) { lock (_lock) { v.Seq = _seq; _published = v; _claimed = null; } }
        public long Generation { get { lock (_lock) return _generation; } }
        public void Unpublish() { lock (_lock) { _published = null; Drop("modal_cleared"); _claimed = null; } }

        // Every enqueued answer gets exactly one modal_result: queued answers that can no longer apply are moved here.
        private void Drop(string reason)
        {
            while (_queue.Count > 0)
            {
                ModalAnswer a = _queue.Dequeue();
                if (_dropped.Count < 64) _dropped.Add(new ModalDrop { Answer = a, Reason = reason });
            }
        }

        public List<ModalDrop> TakeDropped()
        {
            lock (_lock)
            {
                List<ModalDrop> d = new List<ModalDrop>(_dropped);
                _dropped.Clear();
                return d;
            }
        }
        public ModalView Published { get { lock (_lock) return _published; } }
        public int QueueCount { get { lock (_lock) return _queue.Count; } }

        // Leave the context active for system rules (notably checkpoint reload), while
        // refusing socket answers and dropping any that have not reached the UI yet.
        public void SuspendAnswers()
        {
            lock (_lock) { _answersSuspended = true; Drop("game_not_running"); _claimed = null; }
        }
        public bool AnswersSuspended { get { lock (_lock) return _answersSuspended; } }

        // Bridge thread: early validation; nothing is claimed here. Returns reason or null (enqueued).
        public string Enqueue(ModalAnswer a)
        {
            lock (_lock)
            {
                if (!_active) return "inactive";
                if (_answersSuspended) return "game_not_running";
                if (_seenSet.Contains(a.AnswerId)) return "duplicate_answer_id";
                string r = ModalPolicy.Validate(a, _published, _runId, _published == null ? _seq : _published.Seq);
                if (r != null) return r;
                if (_succeeded.Contains(a.Token)) return "already_answered";
                if (_queue.Count >= ModalPolicy.MaxQueuedAnswers) return "queue_full";
                Remember(a.AnswerId);
                _queue.Enqueue(a);
                return null;
            }
        }

        private void Remember(long id)
        {
            _seenSet.Add(id);
            _seenIds.Enqueue(id);
            while (_seenIds.Count > 256) _seenSet.Remove(_seenIds.Dequeue());
        }

        public ModalAnswer Dequeue()
        {
            lock (_lock) return _queue.Count == 0 ? null : _queue.Dequeue();
        }

        // UI thread: authoritative re-validation, then claim. Returns reason or null (claimed).
        public string Claim(ModalAnswer a, ModalView current)
        {
            lock (_lock)
            {
                if (_answersSuspended) return "game_not_running";
                if (!ReferenceEquals(current, _published)) return "stale_token";
                string r = ModalPolicy.Validate(a, current, _runId, current.Seq);
                if (r != null) return r;
                if (_succeeded.Contains(a.Token)) return "already_answered";
                if (_claimed != null) return "answer_in_flight";
                _claimed = a.Token;
                return null;
            }
        }

        // Callback provably had no effect: release so a later valid answer can still be applied.
        public void Release(string token) { lock (_lock) { if (_claimed == token) _claimed = null; } }

        public void Succeed(string token)
        {
            lock (_lock)
            {
                if (_succeeded.Add(token)) { _succeededOrder.Enqueue(token); while (_succeededOrder.Count > 256) _succeeded.Remove(_succeededOrder.Dequeue()); }
                _claimed = null;
                Drop("already_answered");
            }
        }

        public bool Succeeded(string token) { lock (_lock) return _succeeded.Contains(token); }
        public bool InFlight { get { lock (_lock) return _claimed != null; } }
    }
}
