// R0 only records the runtime identity, loaded mods, and effective options.
using System;
using System.Collections.Generic;
using Newtonsoft.Json;
using XRL;
using XRL.Core;
using XRL.UI;

namespace LlmOfQud.ProbeR0
{
    [HasModSensitiveStaticCache]
    public static class Bootstrap
    {
        private static readonly Dictionary<string, string> Expected = new Dictionary<string, string>
        {
            { "OptionAutoexploreChests", "No" },
            { "OptionAbilityCooldownWarningAsMessage", "Yes" },
            { "OptionShowScavengeItemAsMessage", "Yes" },
            { "OptionPopupJournalNote", "No" },
            { "OptionDisplayHPWarning", "No Warning" },
            { "OptionDisableTextAnimationEffects", "Yes" },
            { "OptionMusicBackground", "Yes" },
            { "OptionAllowCSMods", "Yes" },
            { "OptionModernUI", "Yes" },
            { "OptionSessionBackups", "None" },
            { "OptionAutosaveInterval", "5" },
            { "OptionEnableMods", "Yes" },
        };

        [ModSensitiveCacheInit]
        public static void Init()
        {
            try
            {
                var activeModIds = new List<string>();
                foreach (ModInfo mod in ModManager.ActiveMods)
                    activeModIds.Add(mod.ID);
                activeModIds.Sort(StringComparer.Ordinal);

                var options = new Dictionary<string, string>();
                var mismatches = new Dictionary<string, string>();
                foreach (var item in Expected)
                {
                    string actual = Options.GetOption(item.Key);
                    options.Add(item.Key, actual);
                    if (actual != item.Value)
                        mismatches.Add(item.Key, actual);
                }

                MetricsManager.LogInfo("[R0] " + JsonConvert.SerializeObject(new
                {
                    kind = "init",
                    assemblyVersion = typeof(XRLCore).Assembly.GetName().Version.ToString(),
                    activeModIds,
                    options,
                    expectedOptions = Expected,
                    optionMismatches = mismatches,
                    optionsMatch = mismatches.Count == 0,
                    steamAppId = Environment.GetEnvironmentVariable("SteamAppId") ?? ""
                }));
            }
            catch (Exception ex)
            {
                MetricsManager.LogInfo("[R0] " + JsonConvert.SerializeObject(new
                {
                    kind = "init_error",
                    error = ex.ToString()
                }));
            }
        }
    }
}
