using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace LLMOfQud
{
    [Serializable]
    public sealed class BrainClient
    {
        public const string DefaultEndpoint = "ws://localhost:4040";

        private const int ConnectTimeoutMs = 500;
        private const int IdlePollMs = 100;
        private const int ReconnectPollMs = 250;
        private const int ReceiveBufferBytes = 8192;

        [NonSerialized] private object _gate;
        [NonSerialized] private Queue<PendingRequest> _requests;
        [NonSerialized] private AutoResetEvent _requestReady;
        [NonSerialized] private Thread _workerThread;
        [NonSerialized] private ClientWebSocket _socket;
        [NonSerialized] private CancellationTokenSource _stop;
        [NonSerialized] private Action _onReconnect;
        [NonSerialized] private long _nextSequence;
        [NonSerialized] private bool _hasConnected;
        [NonSerialized] private bool _disconnectedSinceConnect;
        [NonSerialized] private bool _stopped;

        private readonly Uri _endpoint;

        public BrainClient(string endpoint, Action onReconnect)
        {
            _endpoint = new Uri(endpoint ?? DefaultEndpoint);
            _onReconnect = onReconnect;
            InitializeRuntimeFields();
        }

        public void SetReconnectCallback(Action onReconnect)
        {
            _onReconnect = onReconnect;
        }

        public void Start()
        {
            InitializeRuntimeFields();
            lock (_gate)
            {
                if (_workerThread != null && _workerThread.IsAlive)
                {
                    return;
                }
                _stopped = false;
                _stop = new CancellationTokenSource();
                _workerThread = new Thread(RunLoop);
                _workerThread.IsBackground = true;
                _workerThread.Name = "LLMOfQud BrainClient";
                _workerThread.Start();
            }
        }

        public void Stop()
        {
            InitializeRuntimeFields();
            Thread workerThread;
            lock (_gate)
            {
                _stopped = true;
                workerThread = _workerThread;
                FailPendingRequestsLocked(new OperationCanceledException("BrainClient stopped"));
            }

            CancellationTokenSource stop = _stop;
            if (stop != null)
            {
                stop.Cancel();
            }
            AutoResetEvent requestReady = _requestReady;
            if (requestReady != null)
            {
                requestReady.Set();
            }
            ResetSocket();
            if (workerThread != null && workerThread != Thread.CurrentThread)
            {
                workerThread.Join(ConnectTimeoutMs + IdlePollMs + ReconnectPollMs);
            }
            lock (_gate)
            {
                if (_workerThread != null && !_workerThread.IsAlive)
                {
                    _workerThread = null;
                }
            }
        }

        public DecisionRequest SendDecisionInput(string requestJson, int timeoutMs)
        {
            InitializeRuntimeFields();
            PendingRequest pending = new PendingRequest
            {
                Sequence = Interlocked.Increment(ref _nextSequence),
                RequestJson = requestJson,
                TimeoutMs = timeoutMs,
                Completion = new TaskCompletionSource<string>(),
            };

            lock (_gate)
            {
                if (_stopped)
                {
                    throw new DisconnectedException("BrainClient stopped");
                }
                _requests.Enqueue(pending);
            }
            _requestReady.Set();
            // decompiled/MetricsManager.cs:407-409 (LogInfo -> Player.log)
            MetricsManager.LogInfo(
                "[LLMOfQud][decision_request] queued sequence=" + pending.Sequence.ToString());
            return new DecisionRequest(pending.Sequence, pending.Completion.Task);
        }

        private void InitializeRuntimeFields()
        {
            if (_gate == null)
            {
                _gate = new object();
            }
            if (_requests == null)
            {
                _requests = new Queue<PendingRequest>();
            }
            if (_requestReady == null)
            {
                _requestReady = new AutoResetEvent(false);
            }
        }

        private void RunLoop()
        {
            // decompiled/MetricsManager.cs:407-409 (LogInfo -> Player.log)
            MetricsManager.LogInfo(
                "[LLMOfQud][connection_lifecycle] THREAD_START endpoint=" + _endpoint);

            while (_stop == null || !_stop.IsCancellationRequested)
            {
                PendingRequest pending = DequeueOrWait();
                if (pending == null)
                {
                    TryConnectForReadiness();
                    continue;
                }

                try
                {
                    Stopwatch stopwatch = Stopwatch.StartNew();
                    ClientWebSocket socket = EnsureConnected();
                    Send(socket, pending.RequestJson, pending.TimeoutMs);
                    string response = ReceiveDecision(socket, pending.TimeoutMs);
                    stopwatch.Stop();
                    pending.Completion.TrySetResult(response);
                    // decompiled/MetricsManager.cs:407-409 (LogInfo -> Player.log)
                    MetricsManager.LogInfo(
                        "[LLMOfQud][decision_response] received sequence=" +
                        pending.Sequence.ToString() + " elapsed_ms=" +
                        stopwatch.ElapsedMilliseconds.ToString());
                }
                catch (TimeoutException ex)
                {
                    pending.Completion.TrySetException(ex);
                    // decompiled/MetricsManager.cs:407-409 (LogInfo -> Player.log)
                    MetricsManager.LogInfo(
                        "[LLMOfQud][decision_response] TIMEOUT sequence=" +
                        pending.Sequence.ToString() + " timeout_ms=" +
                        pending.TimeoutMs.ToString());
                    ResetSocket();
                }
                catch (DisconnectedException ex)
                {
                    pending.Completion.TrySetException(ex);
                    ResetSocket();
                    MarkDisconnected();
                }
                catch (Exception ex)
                {
                    pending.Completion.TrySetException(
                        new DisconnectedException("BrainClient transport failure", ex));
                    // decompiled/MetricsManager.cs:407-409 (LogInfo -> Player.log)
                    MetricsManager.LogInfo(
                        "[LLMOfQud][connection_lifecycle] DISCONNECT error=" +
                        ex.GetType().Name + " message=" + Sanitize(ex.Message));
                    ResetSocket();
                    MarkDisconnected();
                }
            }

            lock (_gate)
            {
                FailPendingRequestsLocked(new OperationCanceledException("BrainClient stopped"));
            }
            // decompiled/MetricsManager.cs:407-409 (LogInfo -> Player.log)
            MetricsManager.LogInfo("[LLMOfQud][connection_lifecycle] THREAD_STOP");
        }

        private PendingRequest DequeueOrWait()
        {
            lock (_gate)
            {
                if (_requests.Count > 0)
                {
                    return _requests.Dequeue();
                }
            }
            _requestReady.WaitOne(IdlePollMs);
            lock (_gate)
            {
                if (_requests.Count > 0)
                {
                    return _requests.Dequeue();
                }
            }
            return null;
        }

        private void FailPendingRequestsLocked(Exception ex)
        {
            while (_requests != null && _requests.Count > 0)
            {
                PendingRequest pending = _requests.Dequeue();
                if (pending != null && pending.Completion != null)
                {
                    pending.Completion.TrySetException(ex);
                }
            }
        }

        private void TryConnectForReadiness()
        {
            try
            {
                EnsureConnected();
            }
            catch
            {
                Thread.Sleep(ReconnectPollMs);
            }
        }

        private ClientWebSocket EnsureConnected()
        {
            if (_socket != null && _socket.State == WebSocketState.Open)
            {
                return _socket;
            }

            ResetSocket();
            ClientWebSocket socket = new ClientWebSocket();
            using (CancellationTokenSource cts = new CancellationTokenSource(ConnectTimeoutMs))
            {
                Task task = socket.ConnectAsync(_endpoint, cts.Token);
                try
                {
                    task.Wait();
                }
                catch (AggregateException ex)
                {
                    throw new DisconnectedException(
                        "Unable to connect to Brain websocket", ex.InnerException ?? ex);
                }
            }

            _socket = socket;
            if (!_hasConnected)
            {
                _hasConnected = true;
                // decompiled/MetricsManager.cs:407-409 (LogInfo -> Player.log)
                MetricsManager.LogInfo(
                    "[LLMOfQud][connection_lifecycle] CONNECT endpoint=" + _endpoint);
            }
            else if (_disconnectedSinceConnect)
            {
                _disconnectedSinceConnect = false;
                // decompiled/MetricsManager.cs:407-409 (LogInfo -> Player.log)
                MetricsManager.LogInfo(
                    "[LLMOfQud][connection_lifecycle] RECONNECT endpoint=" + _endpoint);
                Action callback = _onReconnect;
                if (callback != null)
                {
                    callback();
                }
            }
            return socket;
        }

        private static void Send(ClientWebSocket socket, string requestJson, int timeoutMs)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(requestJson);
            ArraySegment<byte> segment = new ArraySegment<byte>(bytes);
            using (CancellationTokenSource cts = new CancellationTokenSource(timeoutMs))
            {
                Task task = socket.SendAsync(segment, WebSocketMessageType.Text, true, cts.Token);
                WaitTransportTask(task, cts, "send timed out");
            }
        }

        private static string ReceiveDecision(ClientWebSocket socket, int timeoutMs)
        {
            while (true)
            {
                string responseJson = Receive(socket, timeoutMs);
                if (ToolRouter.IsSupervisorResponseMessage(responseJson))
                {
                    SupervisorResponseEnvelope response =
                        ToolRouter.ParseSupervisorResponseEnvelope(responseJson);
                    throw new DisconnectedException(
                        "Unexpected supervisor_response before final decision: " +
                        (response.MessageId ?? "<null>"));
                }
                if (ToolRouter.IsToolCallMessage(responseJson))
                {
                    ToolCallEnvelope call = ToolRouter.ParseToolCallEnvelope(responseJson);
                    ToolResultEnvelope result = new ToolRouter().Dispatch(call);
                    string resultJson = ToolRouter.BuildToolResultJson(result);
                    Send(socket, resultJson, timeoutMs);
                    continue;
                }
                return responseJson;
            }
        }

        private static string Receive(ClientWebSocket socket, int timeoutMs)
        {
            byte[] bytes = new byte[ReceiveBufferBytes];
            using (MemoryStream stream = new MemoryStream())
            using (CancellationTokenSource cts = new CancellationTokenSource(timeoutMs))
            {
                while (true)
                {
                    ArraySegment<byte> segment = new ArraySegment<byte>(bytes);
                    Task<WebSocketReceiveResult> task = socket.ReceiveAsync(segment, cts.Token);
                    WebSocketReceiveResult result = WaitReceiveTask(task, cts);

                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        throw new DisconnectedException("Brain websocket closed");
                    }
                    stream.Write(bytes, 0, result.Count);
                    if (result.EndOfMessage)
                    {
                        return Encoding.UTF8.GetString(stream.ToArray());
                    }
                }
            }
        }

        private static void WaitTransportTask(Task task, CancellationTokenSource cts, string timeoutMessage)
        {
            try
            {
                task.Wait();
            }
            catch (AggregateException ex)
            {
                if (cts.IsCancellationRequested)
                {
                    throw new TimeoutException(timeoutMessage);
                }
                throw ex.InnerException ?? ex;
            }
        }

        private static WebSocketReceiveResult WaitReceiveTask(
            Task<WebSocketReceiveResult> task, CancellationTokenSource cts)
        {
            try
            {
                task.Wait();
                return task.Result;
            }
            catch (AggregateException ex)
            {
                if (cts.IsCancellationRequested)
                {
                    throw new TimeoutException("receive timed out");
                }
                throw ex.InnerException ?? ex;
            }
        }

        private void ResetSocket()
        {
            ClientWebSocket socket = _socket;
            _socket = null;
            if (socket == null)
            {
                return;
            }
            try { socket.Abort(); } catch { /* swallow transport cleanup */ }
            try { socket.Dispose(); } catch { /* swallow transport cleanup */ }
        }

        private void MarkDisconnected()
        {
            if (_hasConnected && !_disconnectedSinceConnect)
            {
                _disconnectedSinceConnect = true;
                // decompiled/MetricsManager.cs:407-409 (LogInfo -> Player.log)
                MetricsManager.LogInfo(
                    "[LLMOfQud][connection_lifecycle] DISCONNECT endpoint=" + _endpoint);
            }
        }

        private static string Sanitize(string value)
        {
            if (value == null)
            {
                return "";
            }
            return value.Replace('\n', ' ').Replace('\r', ' ');
        }

        private sealed class PendingRequest
        {
            public long Sequence;
            public string RequestJson;
            public int TimeoutMs;
            public TaskCompletionSource<string> Completion;
        }

        public sealed class DecisionRequest
        {
            public readonly long Sequence;
            public readonly Task<string> ResponseTask;

            public DecisionRequest(long sequence, Task<string> responseTask)
            {
                Sequence = sequence;
                ResponseTask = responseTask;
            }
        }
    }
}
