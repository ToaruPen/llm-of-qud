using System.Collections.Generic;

namespace LlmOfQud
{
    internal static class CallbackRegistration
    {
        // The engine may replace the list during hotload; never cache a registration flag.
        public static void Ensure<T>(IList<T> callbacks, T own)
        {
            for (int i = callbacks.Count - 1; i >= 0; i--)
                if (EqualityComparer<T>.Default.Equals(callbacks[i], own)) callbacks.RemoveAt(i);
            callbacks.Add(own);
        }
    }
}
