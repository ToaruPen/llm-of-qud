using System.Net;
using System.Net.Sockets;
using System.Net.WebSockets;
using System.Text;
using LlmOfQud;

internal static class BridgeShutdownTests
{
    internal static async Task Run(Action<bool, string> check)
    {
        await CheckDrain(check, WebSocketCloseStatus.NormalClosure);
        await CheckDrain(check, WebSocketCloseStatus.PolicyViolation);
        await CheckDrain(check, null);
    }

    private static async Task CheckDrain(Action<bool, string> check, WebSocketCloseStatus? reply)
    {
        var portReservation = new TcpListener(IPAddress.Loopback, 0);
        portReservation.Start();
        int port = ((IPEndPoint)portReservation.LocalEndpoint).Port;
        portReservation.Stop();
        using var listener = new HttpListener();
        listener.Prefixes.Add($"http://127.0.0.1:{port}/");
        listener.Start();
        string run = Guid.NewGuid().ToString();
        using var bridge = new Bridge(run, _ => false, new Uri($"ws://127.0.0.1:{port}/"));
        var context = await listener.GetContextAsync().WaitAsync(TimeSpan.FromSeconds(5));
        using var socket = (await context.AcceptWebSocketAsync(null)).WebSocket;
        bridge.Publish(1, $"{{\"kind\":\"request\",\"run_id\":\"{run}\",\"seq\":1}}", null);
        check((await Receive(socket)).Contains("\"request\""), "bridge sent request before shutdown");
        check(bridge.Suspend(), "shutdown suspension accepted");
        while (LlmOfQud.Runtime.Messages.TryDequeue(out _)) { }
        var draining = Task.Run(() => bridge.DrainSuspended(reply == null ? 6000 :
            reply == WebSocketCloseStatus.NormalClosure ? 5000 : 1000));
        string next;
        do { next = await Receive(socket); } while (next.Contains("\"heartbeat\""));
        check(next.Contains("\"suspended\""), "bridge sent suspension before shutdown");
        var close = await ReceiveFrame(socket);
        check(close.MessageType == WebSocketMessageType.Close, "bridge sent close after suspension");
        if (reply == WebSocketCloseStatus.NormalClosure)
        {
            check(!draining.IsCompleted, "drain waits for server close acknowledgement");
            await socket.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, "", CancellationToken.None);
            check(await draining.WaitAsync(TimeSpan.FromSeconds(5)), "drain succeeds after server acknowledgement");
        }
        else
        {
            if (reply.HasValue)
                await socket.CloseOutputAsync(reply.Value, "refused", CancellationToken.None);
            check(!await draining.WaitAsync(TimeSpan.FromSeconds(8)), "drain refuses missing or abnormal close acknowledgement");
            if (!reply.HasValue)
                check(LlmOfQud.Runtime.Messages.Any(message => message.Contains("connection_lost")),
                    "unanswered prior receive is interrupted by the bounded transport timeout");
        }
    }

    private static async Task<string> Receive(WebSocket socket)
    {
        var bytes = new byte[8192];
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var frame = await socket.ReceiveAsync(new ArraySegment<byte>(bytes), timeout.Token);
        if (frame.MessageType != WebSocketMessageType.Text || !frame.EndOfMessage)
            throw new Exception("expected one text frame");
        return Encoding.UTF8.GetString(bytes, 0, frame.Count);
    }

    private static async Task<WebSocketReceiveResult> ReceiveFrame(WebSocket socket)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        return await socket.ReceiveAsync(new ArraySegment<byte>(new byte[16]), timeout.Token);
    }
}
