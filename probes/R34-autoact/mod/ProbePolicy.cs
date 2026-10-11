using System.Collections.Generic;

namespace LlmOfQud.ProbeR34
{
    // Pure probe policy, also exercised without the game runtime.
    public static class ProbePolicy
    {
        public static bool DiscardPickerAttempt(bool enabled, int previousAttempts)
        {
            return enabled && previousAttempts == 0;
        }

        public static bool NewTaskAppeared(IEnumerable<string> before, IEnumerable<string> after, string expected)
        {
            if (string.IsNullOrEmpty(expected)) return false;
            foreach (string id in before)
                if (id == expected) return false;
            foreach (string id in after)
                if (id == expected) return true;
            return false;
        }
    }
}
