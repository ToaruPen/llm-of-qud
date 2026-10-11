using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Net.WebSockets;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using XRL.Core;

namespace LlmOfQud
{
    // The bridge owns the socket and synchronization flags, never game objects.
    internal sealed class Bridge : IDisposable
    {
        private readonly string _runId;
        private readonly object _sync = new object();
        private readonly CancellationTokenSource _stop = new CancellationTokenSource();
        private readonly ManualResetEventSlim _suspensionDrained = new ManualResetEventSlim(false);
        private readonly Uri _endpoint;
        private readonly DecisionGate _gate = new DecisionGate();
        private readonly AutoResetEvent _ready = new AutoResetEvent(false);
        private readonly Thread _thread;
        private string _request, _result, _recovery, _fault, _suspended;
        private long _recoverySeq;
        private int _recoveryModalCut;
        private int _revision;
        private bool _drainSuspended;
        private long _seq;
        private JObject _decision;
        private readonly Func<JObject, bool> _answerModal;
        private readonly List<ModalFrame> _modalHistory = new List<ModalFrame>();
        private int _modalBytes;
        private static int _liveCount;
        public static int LiveCount { get { return Volatile.Read(ref _liveCount); } }
        private sealed class ModalFrame { public long Seq; public string Raw; }

        public Bridge(string runId, Func<JObject, bool> answerModal, Uri endpoint = null)
        {
            _runId = runId;
            _answerModal = answerModal;
            _endpoint = endpoint ?? new Uri("ws://127.0.0.1:4040");
            _thread = new Thread(Loop) { IsBackground = true, Name = "LLM CTA bridge" };
            _thread.Start();
        }

        public void PublishModal(JObject message)
        {
            string raw = message.ToString(Formatting.None);
            int bytes = Encoding.UTF8.GetByteCount(raw);
            lock (_sync)
            {
                if ((string)message["run_id"] != _runId) throw new InvalidDataException("Foreign modal run");
                // Load invalidation replaces old UI acknowledgements with an explicit
                // interruption. A late UI tick must not resurrect the obsolete modal.
                if (_fault != null || (_recovery != null && (long)message["seq"] <= _recoverySeq)) return;
                if (_modalHistory.Count >= 4096 || _modalBytes + bytes > 16 * 1024 * 1024)
                    throw new InvalidDataException("Modal replay history capacity reached");
                _modalHistory.Add(new ModalFrame { Seq = (long)message["seq"], Raw = raw });
                _modalBytes += bytes;
            }
        }

        public void Publish(long seq, string request, string result)
        {
            lock (_sync)
            {
                if (_fault != null) throw new InvalidOperationException("Cannot publish after game fault");
                if (_suspended != null) throw new InvalidOperationException("Cannot publish before the suspended game reloads");
                _seq = seq; _request = request; _result = result;
                _decision = null; _gate.Open(seq); _revision++;
            }
        }

        public void PublishRecovery(JObject message)
        {
            lock (_sync)
            {
                if (_fault != null || _seq < 1 || (long)message["seq"] != _seq || _request == null)
                    throw new InvalidOperationException("Recovery requires a live published request");
                _recovery = message.ToString(Formatting.None);
                _recoverySeq = _seq; _recoveryModalCut = _modalHistory.Count;
                _request = _result = _suspended = null; _decision = null; _gate.Close(); _revision++;
            }
        }

        // The controlled game stopped running while the current request was open. Void it
        // until a verified reload publishes its recovery (or a fault ends the run). The
        // request bytes stay for reconnect replay and PublishRecovery's precondition.
        public bool Suspend()
        {
            lock (_sync)
            {
                if (_fault != null || _request == null || _suspended != null) return false;
                _suspended = JsonConvert.SerializeObject(new { kind = "suspended", run_id = _runId, seq = _seq, reason = "game_not_running" });
                _decision = null; _gate.Close();
                return true;
            }
        }

        // Save-and-quit keeps the socket alive through a bounded transport flush.
        // A close handshake does not prove that the harness persisted the frame.
        public bool DrainSuspended(int timeoutMilliseconds)
        {
            lock (_sync)
            {
                if (_suspended == null) throw new InvalidOperationException("No suspension to drain");
                _drainSuspended = true;
            }
            bool drained = _suspensionDrained.Wait(timeoutMilliseconds);
            if (!drained) Runtime.Log(new { kind = "suspended_drain_timeout", run_id = _runId, seq = _seq });
            return drained;
        }

        public void PublishFault(string reason)
        {
            lock (_sync)
            {
                if (_fault != null) return;
                _decision = null; _gate.Close();
                if (_seq > 0) _fault = JsonConvert.SerializeObject(new { kind = "game_fault", run_id = _runId, seq = _seq, reason });
            }
        }

        public JObject WaitDecision()
        {
            _ready.WaitOne(100);
            lock (_sync)
            {
                JObject value = _decision;
                _decision = null;
                return value;
            }
        }

        private void Focus()
        {
            XRLCore.bThreadFocus = true;
            GameManager._focused = true;
            GameManager.focusedEvent.Set();
        }

        private void Await(Task task, CancellationToken timeout = default(CancellationToken))
        {
            while (!task.IsCompleted)
            {
                _stop.Token.ThrowIfCancellationRequested();
                timeout.ThrowIfCancellationRequested();
                Focus();
                Thread.Sleep(25);
            }
            timeout.ThrowIfCancellationRequested();
            task.GetAwaiter().GetResult();
        }

        private void Send(ClientWebSocket ws, string raw)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(raw);
            using (var timeout = CancellationTokenSource.CreateLinkedTokenSource(_stop.Token))
            {
                timeout.CancelAfter(5000);
                Await(ws.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, timeout.Token));
            }
        }

        private void CloseAfterSuspension(ClientWebSocket ws, Task<WebSocketReceiveResult> receive, byte[] buffer)
        {
            using (var timeout = CancellationTokenSource.CreateLinkedTokenSource(_stop.Token))
            {
                timeout.CancelAfter(5000);
                Await(ws.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, "suspended", timeout.Token), timeout.Token);
                while (true)
                {
                    if (receive == null)
                        receive = ws.ReceiveAsync(new ArraySegment<byte>(buffer), timeout.Token);
                    Await(receive, timeout.Token);
                    var frame = receive.GetAwaiter().GetResult();
                    if (frame.MessageType == WebSocketMessageType.Close)
                    {
                        if (frame.CloseStatus != WebSocketCloseStatus.NormalClosure)
                            throw new IOException("Suspension transport closed without normal acknowledgement");
                        return;
                    }
                    receive = null;
                }
            }
        }

        private void Accept(string raw)
        {
            JObject message = JObject.Parse(raw, new JsonLoadSettings { DuplicatePropertyNameHandling = DuplicatePropertyNameHandling.Error });
            if ((string)message["kind"] == "modal_answer")
            {
                if ((string)message["run_id"] != _runId) throw new InvalidDataException("Foreign modal answer");
                _answerModal(message);
                return;
            }
            if ((string)message["kind"] != "decision" || (string)message["run_id"] != _runId ||
                message["seq"] == null || message["seq"].Type != JTokenType.Integer ||
                message["action"] == null || message["action"].Type != JTokenType.String ||
                message["budget"] == null || message["budget"].Type != JTokenType.Integer ||
                (message["dir"] != null && message["dir"].Type != JTokenType.Null && message["dir"].Type != JTokenType.String))
                throw new InvalidDataException("Invalid decision fields");
            var target = message["target"];
            if (target != null && (!(target is JObject) || ((JObject)target).Count != 2 ||
                target["x"] == null || target["x"].Type != JTokenType.Integer ||
                target["y"] == null || target["y"].Type != JTokenType.Integer))
                throw new InvalidDataException("Invalid decision target");
            if (message["until"] != null && message["until"].Type != JTokenType.String)
                throw new InvalidDataException("Invalid rest mode");
            if (message["item"] != null && message["item"].Type != JTokenType.String)
                throw new InvalidDataException("Invalid item handle");
            if (message["skill"] != null && message["skill"].Type != JTokenType.String)
                throw new InvalidDataException("Invalid skill id");
            if (message["attribute"] != null && message["attribute"].Type != JTokenType.String)
                throw new InvalidDataException("Invalid attribute id");
            foreach (var field in message.Properties())
                if (field.Name != "kind" && field.Name != "run_id" && field.Name != "seq" &&
                    field.Name != "action" && field.Name != "dir" && field.Name != "budget" &&
                    field.Name != "target" && field.Name != "until" && field.Name != "item" &&
                    field.Name != "skill" && field.Name != "attribute")
                    throw new InvalidDataException("Unexpected decision field");
            lock (_sync)
            {
                if (!_gate.Accept((long)message["seq"]))
                {
                    Runtime.Log(new { kind = "rejected_decision", reason = "stale_or_duplicate", seq = (long)message["seq"] });
                    return;
                }
                _decision = message;
                _ready.Set();
            }
        }

        private void Loop()
        {
            Interlocked.Increment(ref _liveCount);
            try { SocketLoop(); }
            finally { Interlocked.Decrement(ref _liveCount); }
        }

        private void SocketLoop()
        {
            while (!_stop.IsCancellationRequested)
            {
                try
                {
                    using (var ws = new ClientWebSocket())
                    using (var connect = CancellationTokenSource.CreateLinkedTokenSource(_stop.Token))
                    using (var incoming = new MemoryStream())
                    {
                        connect.CancelAfter(5000);
                        Await(ws.ConnectAsync(_endpoint, connect.Token));
                        Runtime.Log(new { kind = "connected", run_id = _runId });
                        byte[] buffer = new byte[8192];
                        Task<WebSocketReceiveResult> receive = null;
                        int sentRevision = -1;
                        int sentModal = 0;
                        long sentSeq = 0;
                        string sentRecovery = null, sentFault = null, sentSuspended = null;
                        DateTime heartbeatAt = DateTime.UtcNow;
                        while (!_stop.IsCancellationRequested && ws.State == WebSocketState.Open)
                        {
                            Focus();
                            string request, result, recovery, fault, suspended; int revision, modalCut; long seq, recoverySeq;
                            bool drainSuspended;
                            lock (_sync)
                            {
                                request = _request; result = _result; revision = _revision; seq = _seq;
                                recovery = _recovery; recoverySeq = _recoverySeq; modalCut = _recoveryModalCut; fault = _fault;
                                suspended = _suspended;
                                drainSuspended = _drainSuspended;
                            }
                            if (recovery != null && recovery != sentRecovery)
                            {
                                // Preserve the death-menu evidence before the load event.
                                // All cached events use exact bytes, including on reconnect.
                                while (sentModal < modalCut)
                                {
                                    ModalFrame modal;
                                    lock (_sync) modal = _modalHistory[sentModal];
                                    Send(ws, modal.Raw); sentModal++;
                                }
                                Send(ws, recovery); sentRecovery = recovery; sentSeq = recoverySeq;
                            }
                            if (request != null && revision != sentRevision)
                            {
                                if (result != null) Send(ws, result);
                                Send(ws, request);
                                sentRevision = revision;
                                sentSeq = seq;
                            }
                            // After its request (also on reconnect) and before any fault of that seq.
                            if (suspended != null && suspended != sentSuspended && sentRevision == revision)
                            {
                                Send(ws, suspended); sentSuspended = suspended;
                                Runtime.Log(new { kind = "suspended_sent", run_id = _runId, seq });
                            }
                            if (drainSuspended && suspended != null && sentSuspended == suspended)
                            {
                                CloseAfterSuspension(ws, receive, buffer);
                                Runtime.Log(new { kind = "suspended_closed", run_id = _runId, seq });
                                _suspensionDrained.Set();
                                return;
                            }
                            if (fault != null && fault != sentFault) { Send(ws, fault); sentFault = fault; }
                            // Main request/result must precede modal events belonging to that seq.
                            // Keep exact bytes for reconnect: callbacks can finish before a socket
                            // write's outcome is known, so a successful write alone is not an ACK.
                            while (true)
                            {
                                ModalFrame modal;
                                lock (_sync)
                                    modal = sentModal < _modalHistory.Count ? _modalHistory[sentModal] : null;
                                if (modal == null || modal.Seq > sentSeq) break;
                                Send(ws, modal.Raw);
                                sentModal++;
                            }
                            if (DateTime.UtcNow >= heartbeatAt && seq > 0)
                            {
                                Send(ws, JsonConvert.SerializeObject(new { kind = "heartbeat", run_id = _runId, seq }));
                                heartbeatAt = DateTime.UtcNow.AddSeconds(2);
                            }
                            if (receive == null)
                                receive = ws.ReceiveAsync(new ArraySegment<byte>(buffer), _stop.Token);
                            if (receive.IsCompleted)
                            {
                                var part = receive.GetAwaiter().GetResult();
                                if (part.MessageType != WebSocketMessageType.Text) throw new IOException("Socket closed or non-text message");
                                incoming.Write(buffer, 0, part.Count);
                                if (incoming.Length > 1024 * 1024) throw new InvalidDataException("Decision too large");
                                if (part.EndOfMessage)
                                {
                                    Accept(new UTF8Encoding(false, true).GetString(incoming.ToArray()));
                                    incoming.SetLength(0);
                                }
                                receive = null;
                            }
                            Thread.Sleep(25);
                        }
                    }
                }
                catch (Exception ex)
                {
                    if (!_stop.IsCancellationRequested)
                        Runtime.Log(new { kind = "connection_lost", error = ex.GetType().Name, run_id = _runId });
                }
                // Keep the game paused, while preserving the focus heartbeat.
                for (int i = 0; i < 10 && !_stop.IsCancellationRequested; i++) { Focus(); Thread.Sleep(100); }
            }
        }

        public void Dispose()
        {
            _stop.Cancel();
            _ready.Set();
            if (!_thread.Join(6000)) throw new TimeoutException("Bridge did not stop");
            _ready.Dispose(); _stop.Dispose();
            _suspensionDrained.Dispose();
        }
    }
}
