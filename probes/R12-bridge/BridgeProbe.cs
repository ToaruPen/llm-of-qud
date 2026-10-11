// Isolated R1/R2 experiment. No game action is selected by the R2 transport.
// R1 calls PassTurn once solely to test the CTA boundary after a timed hold.
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using ConsoleLib.Console;
using XRL;
using XRL.Core;
using XRL.Wish;
using XRL.World;

namespace LlmOfQud.ProbeR12
{
    [HasModSensitiveStaticCache]
    public static class Bootstrap
    {
        [ModSensitiveCacheInit]
        public static void Init() { Bridge.EnsureUiTick(); Bridge.RegisterControl(); }
    }

    [HasWishCommand]
    public static class Wishes
    {
        [WishCommand("probe12")]
        public static void Probe12(string rest)
        {
            try
            {
                string[] parts = (rest ?? "").Split(':');
                if (parts.Length == 3 && parts[0] == "r1")
                {
                    int seconds;
                    if (!int.TryParse(parts[1], out seconds) || (seconds != 60 && seconds != 600) ||
                        (parts[2] != "focused" && parts[2] != "unfocused"))
                        throw new ArgumentException("Use probe12:r1:<60|600>:<focused|unfocused>");
                    Bridge.ArmR1(seconds, parts[2]);
                }
                else if (parts.Length == 1 && parts[0] == "r2") Bridge.StartR2();
                else throw new ArgumentException("Use probe12:r1:<60|600>:<focused|unfocused> or probe12:r2");
            }
            catch (Exception ex) { Bridge.Log(new { kind = "wish_error", error = ex.ToString() }); }
        }
    }

    [Serializable]
    public sealed class ProbeSystem : IPlayerSystem
    {
        public override void RegisterPlayer(GameObject player, IEventRegistrar registrar)
        {
            registrar.Register(SingletonEvent<CommandTakeActionEvent>.ID);
            base.RegisterPlayer(player, registrar);
        }

        public override bool HandleEvent(CommandTakeActionEvent e)
        {
            return Bridge.OnCta();
        }
    }

    internal sealed class UiPulse
    {
        public long SentTicks;
        public readonly ManualResetEventSlim Done = new ManualResetEventSlim(false);
        public double LatencyMs;
        public bool Focused;
    }

    internal sealed class R1Run
    {
        public int Seconds;
        public string Focus;
        public long StartTicks;
        public long TurnStart;
        public int EnergyStart;
        public int EnergyAfter;
        public long ElapsedMs;
        public double MaxUiMs;
        public int UiTimeouts;
        public int Samples;
        public int FocusMismatches;
        public int FocusSamples;
        public int EndPlayerTurns;
        public int Actions;
        public bool TimerFailure;
        public readonly ManualResetEventSlim Released = new ManualResetEventSlim(false);
    }

    internal static class Bridge
    {
        // 0 idle, 1 armed by wish, 2 blocked inside CTA, 3 awaiting next CTA.
        private static int _r1State;
        private static R1Run _r1;
        private static int _r2Running;
        private static int _tickGeneration;
        private static long _lastTickTicks;
        private static bool _endCallbackRegistered;
        private static long _lastControlTicks;
        private static bool _restorePending;
        private static bool _previousRunInBackground;
        private static bool _previousRibCaptured;
        private static readonly ConcurrentQueue<UiPulse> UiPulses = new ConcurrentQueue<UiPulse>();

        public static void Log(object payload)
        {
            MetricsManager.LogInfo("[R12] " + JsonConvert.SerializeObject(payload));
        }

        // Experiment-only control channel; consumed on the game thread at its idle
        // callback, never a public gameplay tool or a production decision fallback.
        public static void RegisterControl()
        {
            if (_endCallbackRegistered) return;
            XRLCore.RegisterOnEndPlayerTurnCallback(OnEndPlayerTurn);
            _endCallbackRegistered = true;
        }

        private static void PollControl()
        {
            if (SinceMs(_lastControlTicks) < 250) return;
            _lastControlTicks = Stopwatch.GetTimestamp();
            string path = DataManager.SavePath("r12-command.txt");
            if (!File.Exists(path)) return;
            string command = File.ReadAllText(path).Trim();
            File.Delete(path);
            Log(new { kind = "control", command });
            Wishes.Probe12(command);
        }

        private static double SinceMs(long ticks)
        {
            return (Stopwatch.GetTimestamp() - ticks) * 1000.0 / Stopwatch.Frequency;
        }

        public static void EnsureUiTick()
        {
            if (Interlocked.Read(ref _lastTickTicks) != 0 && SinceMs(Interlocked.Read(ref _lastTickTicks)) < 2000)
                return;
            GameManager gm = GameManager.Instance;
            if (gm == null) return;
            int generation = Interlocked.Increment(ref _tickGeneration);
            if (GameManager.IsOnUIContext()) gm.uiQueue.queueTask(() => UiTick(generation));
            else if (gm.uiSynchronizationContext != null)
                gm.uiSynchronizationContext.Post(_ =>
                {
                    GameManager current = GameManager.Instance;
                    if (current != null) current.uiQueue.queueTask(() => UiTick(generation));
                }, null);
        }

        private static void UiTick(int generation)
        {
            if (generation != Volatile.Read(ref _tickGeneration)) return;
            try
            {
                Interlocked.Exchange(ref _lastTickTicks, Stopwatch.GetTimestamp());
                int state = Volatile.Read(ref _r1State);
                if (state == 1 || state == 2 || state == 3)
                {
                    if (!_previousRibCaptured)
                    {
                        _previousRunInBackground = UnityEngine.Application.runInBackground;
                        _previousRibCaptured = true;
                    }
                    UnityEngine.Application.runInBackground = true;
                }
                else if (_restorePending)
                {
                    if (_previousRibCaptured) UnityEngine.Application.runInBackground = _previousRunInBackground;
                    GameManager._focused = UnityEngine.Application.isFocused;
                    _restorePending = false;
                    _previousRibCaptured = false;
                }
                UiPulse pulse;
                while (UiPulses.TryDequeue(out pulse))
                {
                    pulse.LatencyMs = SinceMs(pulse.SentTicks);
                    pulse.Focused = UnityEngine.Application.isFocused;
                    pulse.Done.Set();
                }
            }
            catch (Exception ex) { Log(new { kind = "ui_tick_error", error = ex.ToString() }); }
            finally
            {
                GameManager gm = GameManager.Instance;
                if (gm != null) gm.uiQueue.queueTask(() => UiTick(generation));
            }
        }

        public static void ArmR1(int seconds, string focus)
        {
            if (Volatile.Read(ref _r1State) != 0 || Volatile.Read(ref _r2Running) != 0)
                throw new InvalidOperationException("Another R12 probe is active");
            if (The.Game == null || The.Player == null || The.Game.ActionManager == null)
                throw new InvalidOperationException("A live player is required");
            EnsureUiTick();
            The.Game.RequireSystem<ProbeSystem>();
            if (!_endCallbackRegistered)
            {
                XRLCore.RegisterOnEndPlayerTurnCallback(OnEndPlayerTurn);
                _endCallbackRegistered = true;
            }
            _r1 = new R1Run { Seconds = seconds, Focus = focus };
            Volatile.Write(ref _r1State, 1);
            // CmdWish is inside PlayerTurn. Escape it until the first CTA arrives.
            The.Game.ActionManager.SkipPlayerTurn = true;
            Keyboard.KeyEvent.Set();
            Log(new { kind = "r1_armed", requestedSeconds = seconds, focus });
        }

        private static void OnEndPlayerTurn(XRLCore core)
        {
            if (Volatile.Read(ref _r1State) == 0 && Volatile.Read(ref _r2Running) == 0)
                PollControl();
            int state = Volatile.Read(ref _r1State);
            if (state == 1 && The.Game != null && The.Game.ActionManager != null)
            {
                The.Game.ActionManager.SkipPlayerTurn = true;
                Keyboard.KeyEvent.Set();
            }
            // Count callbacks from CTA entry through the next CTA. A callback while
            // blocked is impossible on the game thread, but one after release would
            // reveal an unintended escape into vanilla PlayerTurn.
            if ((state == 2 || state == 3) && _r1 != null)
                Interlocked.Increment(ref _r1.EndPlayerTurns);
        }

        public static bool OnCta()
        {
            int state = Volatile.Read(ref _r1State);
            if (state == 0) return true;
            R1Run run = _r1;
            if (run == null) return true;
            if (state == 3)
            {
                long turnEnd = The.Game != null ? The.Game.Turns : -1;
                bool pass = !run.TimerFailure && run.ElapsedMs >= run.Seconds * 1000L &&
                    run.MaxUiMs < 1000 && run.UiTimeouts == 0 && run.Samples >= run.Seconds - 1 &&
                    run.FocusSamples > 0 && run.FocusMismatches == 0 && run.Actions == 1 &&
                    run.EndPlayerTurns == 0 && turnEnd > run.TurnStart;
                Log(new { kind = "r1_result", requestedSeconds = run.Seconds, focus = run.Focus,
                    elapsedMs = run.ElapsedMs, maxUiMs = run.MaxUiMs, uiTimeouts = run.UiTimeouts,
                    samples = run.Samples, focusSamples = run.FocusSamples,
                    focusMismatches = run.FocusMismatches, actions = run.Actions,
                    endPlayerTurns = run.EndPlayerTurns, turnStart = run.TurnStart,
                    turnEnd, energyStart = run.EnergyStart, energyAfter = run.EnergyAfter, pass });
                Volatile.Write(ref _r1State, 0);
                _r1 = null;
                _restorePending = true;
                return true;
            }
            if (state != 1) return true;

            run.TurnStart = The.Game.Turns;
            run.EnergyStart = The.Player.Energy != null ? The.Player.Energy.Value : -1;
            run.StartTicks = Stopwatch.GetTimestamp();
            Volatile.Write(ref _r1State, 2);
            Log(new { kind = "r1_begin", requestedSeconds = run.Seconds, focus = run.Focus,
                turnStart = run.TurnStart, energyStart = run.EnergyStart });
            Thread worker = new Thread(() => HoldR1(run));
            worker.IsBackground = true;
            worker.Name = "R12 R1 bridge timer";
            worker.Start();
            if (!run.Released.Wait(TimeSpan.FromSeconds(run.Seconds + 10)))
            {
                run.TimerFailure = true;
                Volatile.Write(ref _r1State, 0);
                _r1 = null;
                _restorePending = true;
                Log(new { kind = "r1_result", requestedSeconds = run.Seconds, focus = run.Focus,
                    elapsedMs = (long)SinceMs(run.StartTicks), maxUiMs = run.MaxUiMs,
                    uiTimeouts = run.UiTimeouts, samples = run.Samples,
                    focusMismatches = run.FocusMismatches, actions = 0,
                    endPlayerTurns = run.EndPlayerTurns, turnStart = run.TurnStart,
                    turnEnd = The.Game.Turns, pass = false, error = "timer_timeout" });
                return true;
            }
            run.ElapsedMs = (long)SinceMs(run.StartTicks);
            Log(new { kind = "r1_release", requestedSeconds = run.Seconds, focus = run.Focus,
                elapsedMs = run.ElapsedMs, maxUiMs = run.MaxUiMs, uiTimeouts = run.UiTimeouts,
                samples = run.Samples, focusMismatches = run.FocusMismatches });
            if (run.TimerFailure)
            {
                Volatile.Write(ref _r1State, 0);
                _r1 = null;
                _restorePending = true;
                Log(new { kind = "r1_result", requestedSeconds = run.Seconds, focus = run.Focus,
                    elapsedMs = run.ElapsedMs, maxUiMs = run.MaxUiMs, uiTimeouts = run.UiTimeouts,
                    samples = run.Samples, focusMismatches = run.FocusMismatches,
                    actions = 0, endPlayerTurns = run.EndPlayerTurns,
                    turnStart = run.TurnStart, turnEnd = The.Game.Turns,
                    pass = false, error = "bridge_timer_failed" });
                return true;
            }
            // Probe action only. Production decisions must supply their own action.
            The.Player.PassTurn();
            run.Actions = 1;
            run.EnergyAfter = The.Player.Energy != null ? The.Player.Energy.Value : -1;
            Volatile.Write(ref _r1State, 3);
            return false;
        }

        private static void HoldR1(R1Run run)
        {
            try
            {
                long nextSampleMs = 1000;
                while (SinceMs(run.StartTicks) < run.Seconds * 1000.0 && Volatile.Read(ref _r1State) == 2)
                {
                    KeepGameFocused();
                    if (SinceMs(run.StartTicks) >= nextSampleMs)
                    {
                        UiPulse pulse = new UiPulse { SentTicks = Stopwatch.GetTimestamp() };
                        UiPulses.Enqueue(pulse);
                        while (!pulse.Done.IsSet && SinceMs(pulse.SentTicks) < 1000)
                        {
                            KeepGameFocused();
                            pulse.Done.Wait(100);
                        }
                        bool completed = pulse.Done.IsSet;
                        int elapsedSecond = (int)(SinceMs(run.StartTicks) / 1000.0);
                        if (completed)
                        {
                            run.Samples++;
                            if (pulse.LatencyMs > run.MaxUiMs) run.MaxUiMs = pulse.LatencyMs;
                            if (elapsedSecond >= 3)
                            {
                                run.FocusSamples++;
                                if (pulse.Focused != (run.Focus == "focused")) run.FocusMismatches++;
                            }
                            Log(new { kind = "r1_sample", requestedSeconds = run.Seconds,
                                focus = run.Focus, elapsedMs = (long)SinceMs(run.StartTicks),
                                uiMs = pulse.LatencyMs, actualFocused = pulse.Focused,
                                maxUiMs = run.MaxUiMs, uiTimeouts = run.UiTimeouts,
                                samples = run.Samples, focusMismatches = run.FocusMismatches });
                        }
                        else
                        {
                            run.UiTimeouts++;
                            Log(new { kind = "r1_sample", requestedSeconds = run.Seconds,
                                focus = run.Focus, elapsedMs = (long)SinceMs(run.StartTicks),
                                uiTimeout = true, uiTimeouts = run.UiTimeouts,
                                samples = run.Samples, focusMismatches = run.FocusMismatches });
                        }
                        nextSampleMs += 1000;
                    }
                    Thread.Sleep(100);
                }
            }
            catch (Exception ex)
            {
                run.TimerFailure = true;
                Log(new { kind = "r1_bridge_error", error = ex.ToString() });
            }
            finally { run.Released.Set(); }
        }

        private static void KeepGameFocused()
        {
            // These are plain engine synchronization flags, not Unity APIs.
            XRLCore.bThreadFocus = true;
            GameManager._focused = true;
            GameManager.focusedEvent.Set();
        }

        public static void StartR2()
        {
            if (Volatile.Read(ref _r1State) != 0 || Interlocked.CompareExchange(ref _r2Running, 1, 0) != 0)
                throw new InvalidOperationException("Another R12 probe is active");
            try
            {
                if (The.Game == null || The.Player == null) throw new InvalidOperationException("A live player is required");
                GameObject player = The.Player;
                Cell cell = player.CurrentCell;
                // A fixed UTF-8 payload exercises fragmented receive and Newtonsoft
                // at a representative wire size without reading render state from a
                // worker. It is explicitly synthetic; game facts are captured here.
                object observation = new {
                    turns = The.Game.Turns,
                    playerName = The.Game.PlayerName,
                    x = cell != null ? cell.X : -1,
                    y = cell != null ? cell.Y : -1,
                    zone = cell != null && cell.ParentZone != null ? cell.ParentZone.ZoneID : null,
                    payloadKind = "synthetic_unicode_3kb",
                    probeText = new string('界', 1024)
                };
                Thread worker = new Thread(() => RunR2(observation));
                worker.IsBackground = true;
                worker.Name = "R12 R2 websocket";
                worker.Start();
                Log(new { kind = "r2_begin", count = 1000 });
            }
            catch
            {
                Interlocked.Exchange(ref _r2Running, 0);
                throw;
            }
        }

        private static void RunR2(object observation)
        {
            List<double> rtts = new List<double>(1000);
            int reconnects = 0;
            bool replayed501 = false;
            string error = null;
            ClientWebSocket socket = null;
            Stopwatch overall = Stopwatch.StartNew();
            try
            {
                for (int seq = 1; seq <= 1000; seq++)
                {
                    // Keep these exact bytes across all attempts for this seq.
                    string request = JsonConvert.SerializeObject(new { kind = "observation", seq, observation });
                    int attempt = 0;
                    while (true)
                    {
                        if (overall.ElapsedMilliseconds > 60000)
                            throw new TimeoutException("R2 exceeded 60 second overall deadline at seq " + seq);
                        attempt++;
                        try
                        {
                            if (socket == null) socket = Connect();
                            long started = Stopwatch.GetTimestamp();
                            Send(socket, request);
                            string response = Receive(socket);
                            JObject message = JObject.Parse(response);
                            if ((string)message["kind"] != "decision" ||
                                (int?)message["seq"] != seq ||
                                (string)message["action"] != "probe_ack")
                                throw new InvalidDataException("Invalid decision for seq " + seq + ": " + response);
                            double rtt = SinceMs(started);
                            if (seq == 501 && attempt > 1) replayed501 = true;
                            rtts.Add(rtt);
                            Log(new { kind = "r2_roundtrip", seq, rttMs = rtt, attempt });
                            break;
                        }
                        catch (InvalidDataException) { throw; }
                        catch (Exception ex)
                        {
                            if (attempt >= 10) throw new IOException("R2 retry limit at seq " + seq, ex);
                            reconnects++;
                            Log(new { kind = "r2_reconnect", seq, attempt,
                                elapsedMs = overall.ElapsedMilliseconds, error = ex.GetType().Name });
                            if (socket != null) { try { socket.Abort(); socket.Dispose(); } catch { } socket = null; }
                            Thread.Sleep(200);
                        }
                    }
                }
            }
            catch (Exception ex) { error = ex.ToString(); }
            finally
            {
                if (socket != null) { try { socket.Abort(); socket.Dispose(); } catch { } }
                rtts.Sort();
                double p95 = rtts.Count == 0 ? -1 : rtts[(int)Math.Ceiling(rtts.Count * 0.95) - 1];
                double max = rtts.Count == 0 ? -1 : rtts[rtts.Count - 1];
                bool pass = error == null && rtts.Count == 1000 && reconnects >= 1 && replayed501 && p95 < 5;
                Log(new { kind = "r2_result", count = rtts.Count, p95Ms = p95, maxMs = max,
                    reconnects, replayed501, elapsedMs = overall.ElapsedMilliseconds, pass, error });
                Interlocked.Exchange(ref _r2Running, 0);
            }
        }

        private static ClientWebSocket Connect()
        {
            ClientWebSocket socket = new ClientWebSocket();
            try
            {
                using (CancellationTokenSource cts = new CancellationTokenSource(5000))
                    socket.ConnectAsync(new Uri("ws://127.0.0.1:4040"), cts.Token).GetAwaiter().GetResult();
                return socket;
            }
            catch { socket.Dispose(); throw; }
        }

        private static void Send(ClientWebSocket socket, string message)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(message);
            using (CancellationTokenSource cts = new CancellationTokenSource(5000))
                socket.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, cts.Token)
                    .GetAwaiter().GetResult();
        }

        private static string Receive(ClientWebSocket socket)
        {
            byte[] buffer = new byte[8192];
            using (CancellationTokenSource cts = new CancellationTokenSource(5000))
            using (MemoryStream stream = new MemoryStream())
            {
                while (true)
                {
                    WebSocketReceiveResult result = socket.ReceiveAsync(new ArraySegment<byte>(buffer), cts.Token)
                        .GetAwaiter().GetResult();
                    if (result.MessageType == WebSocketMessageType.Close)
                        throw new IOException("WebSocket close before decision");
                    if (result.MessageType != WebSocketMessageType.Text)
                        throw new InvalidDataException("Non-text WebSocket response");
                    stream.Write(buffer, 0, result.Count);
                    if (result.EndOfMessage) return Encoding.UTF8.GetString(stream.ToArray());
                }
            }
        }
    }
}
