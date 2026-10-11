using System.Collections.Concurrent;
using System.Threading;
using Newtonsoft.Json;

public static class GameManager
{
    public static bool _focused;
    public static readonly ManualResetEvent focusedEvent = new ManualResetEvent(false);
}

namespace XRL.Core
{
    public static class XRLCore { public static bool bThreadFocus; }
}

namespace LlmOfQud
{
    internal static class Runtime
    {
        public static readonly ConcurrentQueue<string> Messages = new ConcurrentQueue<string>();
        public static void Log(object value) { Messages.Enqueue(JsonConvert.SerializeObject(value)); }
    }
}
