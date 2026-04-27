using System;
using System.Collections.Generic;
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

        [NonSerialized] private readonly object _gate = new object();
        [NonSerialized] private readonly Queue<PendingRequest> _requests = new Queue<PendingRequest>();
        [NonSerialized] private AutoResetEvent _requestReady;
        [NonSerialized] private Thread _workerThread;
        [NonSerialized] private ClientWebSocket _socket;
        [NonSerialized] private CancellationTokenSource _stop;
        [NonSerialized] private Action _onReconnect;
        [NonSerialized] private long _nextSequence;
        [NonSerialized] private bool _hasConnected;
        [NonSerialized] private bool _disconnectedSinceConnect;

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
                _stop = new CancellationTokenSource();
                _workerThread = new Thread(RunLoop);
                _workerThread.IsBackground = true;
                _workerThread.Name = "LLMOfQud BrainClient";
                _workerThread.Start();
            }
        }

        public void Stop()
        {
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
                _requests.Enqueue(pending);
            }
            _requestReady.Set();
            MetricsManager.LogInfo(
                "[LLMOfQud][decision_request] queued sequence=" + pending.Sequence.ToString());
            return new DecisionRequest(pending.Sequence, pending.Completion.Task);
        }

        private void InitializeRuntimeFields()
        {
            if (_requestReady == null)
            {
                _requestReady = new AutoResetEvent(false);
            }
        }

        private void RunLoop()
        {
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
                    ClientWebSocket socket = EnsureConnected();
                    Send(socket, pending.RequestJson, pending.TimeoutMs);
                    string response = Receive(socket, pending.TimeoutMs);
                    pending.Completion.TrySetResult(response);
                    MetricsManager.LogInfo(
                        "[LLMOfQud][decision_response] received sequence=" +
                        pending.Sequence.ToString());
                }
                catch (TimeoutException ex)
                {
                    pending.Completion.TrySetException(ex);
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
                    MetricsManager.LogInfo(
                        "[LLMOfQud][connection_lifecycle] DISCONNECT error=" +
                        ex.GetType().Name + " message=" + Sanitize(ex.Message));
                    ResetSocket();
                    MarkDisconnected();
                }
            }

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
                MetricsManager.LogInfo(
                    "[LLMOfQud][connection_lifecycle] CONNECT endpoint=" + _endpoint);
            }
            else if (_disconnectedSinceConnect)
            {
                _disconnectedSinceConnect = false;
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
