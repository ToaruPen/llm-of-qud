using System;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using XRL;
using XRL.UI;
using XRL.World;
using XRL.World.Parts;
using XRL.World.Skills;

namespace LlmOfQud
{
    // Mirrors the entries and purchase gates of the fixed build's Modern Skills and Attributes screens.
    internal static class CharacterGrowth
    {
        private const int CatalogMax = 512, CatalogBytesMax = 250000, DescriptionMax = 4096;
        private const int RequirementMax = 32, RequirementTextMax = 1024;
        private static readonly string[] Attributes = { "Strength", "Agility", "Toughness", "Intelligence", "Willpower", "Ego" };

        public static JObject Build(GameObject player)
        {
            var attributes = new JObject();
            foreach (string name in Attributes)
            {
                Statistic stat = player.GetStat(name);
                attributes[name] = new JObject { ["value"] = stat.Value, ["base"] = stat.BaseValue };
            }
            var owned = new JArray();
            var catalog = new JArray();
            bool truncated = false;
            foreach (SkillEntry skill in SkillFactory.Factory.SkillList.Values)
            {
                if (string.IsNullOrEmpty(skill.Class)) continue;
                bool hasSkill = player.HasPart(skill.Class);
                if (skill.Hidden && !hasSkill) continue;
                if (hasSkill) owned.Add(skill.Class);
                AddEntry(catalog, skill, null, player, ref truncated);
                foreach (PowerEntry power in skill.PowerList)
                {
                    if (string.IsNullOrEmpty(power.Class) || (skill.Hidden && !player.HasPart(power.Class))) continue;
                    if (player.HasPart(power.Class)) owned.Add(SkillId(power, skill));
                    AddEntry(catalog, power, skill, player, ref truncated);
                }
            }
            while (catalog.Count > 0 && Encoding.UTF8.GetByteCount(catalog.ToString(Formatting.None)) > CatalogBytesMax)
            { catalog.RemoveAt(catalog.Count - 1); truncated = true; }
            var mutations = new JArray();
            bool mutationsTruncated = false;
            // The same public list and text used by Modern CharacterStatusScreen.
            foreach (var mutation in StatusScreen.GetMutationList(player))
            {
                if (mutations.Count >= 128) { mutationsTruncated = true; break; }
                string description = mutation.GetDescription() ?? "";
                string levelText = mutation.GetLevelText(mutation.Level) ?? "";
                if (description.Length > DescriptionMax || levelText.Length > DescriptionMax) mutationsTruncated = true;
                mutations.Add(new JObject {
                    ["name"] = mutation.GetDisplayName(), ["level"] = mutation.Level,
                    ["description"] = description.Length > DescriptionMax ? description.Substring(0, DescriptionMax) : description,
                    ["level_text"] = levelText.Length > DescriptionMax ? levelText.Substring(0, DescriptionMax) : levelText,
                    ["defect"] = mutation.IsDefect() });
            }
            return new JObject {
                ["genotype"] = player.GetGenotype(), ["subtype"] = player.GetSubtype(),
                ["mutation_points"] = player.Stat("MP"), ["mutations"] = mutations,
                ["mutations_truncated"] = mutationsTruncated,
                ["level"] = player.Level, ["xp"] = player.Stat("XP"),
                ["next_level_xp"] = Leveler.GetXPForLevel(player.Stat("Level") + 1),
                ["skill_points"] = player.Stat("SP"), ["attribute_points"] = player.Stat("AP"),
                ["attributes"] = attributes, ["owned_skills"] = owned,
                ["skill_catalog"] = catalog, ["catalog_truncated"] = truncated };
        }

        private static void AddEntry(JArray catalog, IBaseSkillEntry entry, SkillEntry parent,
            GameObject player, ref bool truncated)
        {
            if (catalog.Count >= CatalogMax) { truncated = true; return; }
            bool has = player.HasPart(entry.Class);
            bool eligible = CanPurchase(entry, parent, player);
            string description = entry.GetFormattedDescription() ?? "";
            if (description.Length > DescriptionMax) description = description.Substring(0, DescriptionMax);
            var requirements = new JArray();
            if (parent != null) AddRequirement(requirements, "Requires " + parent.Name);
            if (entry is PowerEntry power)
            {
                AddPowerRequirements(requirements, power, player, "");
            }
            else if (entry is SkillEntry skill)
                foreach (PowerEntry freePower in skill.PowerList)
                    if (freePower.Cost == 0) AddPowerRequirements(requirements, freePower, player, freePower.Name + ": ");
            catalog.Add(new JObject {
                ["id"] = parent == null ? entry.Class : SkillId((PowerEntry)entry, parent), ["name"] = entry.Name,
                ["kind"] = parent == null ? "skill" : "power",
                ["parent_id"] = parent == null ? null : (JToken)parent.Class,
                ["cost"] = entry.Cost, ["description"] = description,
                ["requirements"] = requirements, ["owned"] = has, ["eligible"] = eligible });
        }

        private static string SkillId(PowerEntry power, SkillEntry parent) { return parent.Class + ":" + power.Class; }

        private static void AddPowerRequirements(JArray requirements, PowerEntry power, GameObject player, string prefix)
        {
            foreach (PowerEntryRequirement requirement in power.requirements)
            {
                var text = new StringBuilder();
                requirement.Render(player, text);
                AddRequirement(requirements, prefix + text);
            }
            AddNamedRequirements(requirements, power.Requires, prefix + "Requires ");
            AddNamedRequirements(requirements, power.Exclusion, prefix + "Excludes ");
        }

        private static void AddNamedRequirements(JArray requirements, string ids, string prefix)
        {
            if (string.IsNullOrEmpty(ids)) return;
            foreach (string id in ids.Split(','))
            {
                string name = id.Trim();
                if (SkillFactory.Factory.TryGetFirstEntry(name, out IBaseSkillEntry known)) name = known.Name;
                else if (MutationFactory.HasMutation(name)) name = MutationFactory.GetMutationEntryByName(name).Name;
                AddRequirement(requirements, prefix + name);
            }
        }

        private static void AddRequirement(JArray requirements, string text)
        {
            if (requirements.Count >= RequirementMax || string.IsNullOrEmpty(text)) return;
            requirements.Add(text.Length > RequirementTextMax ? text.Substring(0, RequirementTextMax) : text);
        }

        private static bool CanPurchase(IBaseSkillEntry entry, SkillEntry parent, GameObject player)
        {
            string id = parent == null ? entry.Class : SkillId((PowerEntry)entry, parent);
            if (!ActionPolicy.IsSkillId(id) || entry.Cost < 0 || player.HasPart(entry.Class) ||
                player.Stat("SP") < entry.Cost)
                return false;
            Type type = ModManager.ResolveType("XRL.World.Parts.Skill." + entry.Class);
            if (type == null || !typeof(XRL.World.Parts.Skill.BaseSkill).IsAssignableFrom(type)) return false;
            if (entry is SkillEntry skill)
                return !skill.Initiatory && skill.MeetsRequirements(player);
            var power = (PowerEntry)entry;
            return parent != null && player.HasPart(parent.Class) && !power.IsSkillInitiatory && power.MeetsRequirements(player);
        }

        public static bool Learn(GameObject player, string id, out string reason)
        {
            bool published = false;
            foreach (JObject entry in (JArray)Build(player)["skill_catalog"])
                if ((string)entry["id"] == id) { published = true; break; }
            if (!published) { reason = "skill_unavailable"; return false; }
            foreach (SkillEntry skill in SkillFactory.Factory.SkillList.Values)
            {
                if (string.IsNullOrEmpty(skill.Class)) continue;
                bool hasSkill = player.HasPart(skill.Class);
                if (skill.Hidden && !hasSkill) continue;
                if (skill.Class == id)
                {
                    if (!CanPurchase(skill, null, player)) { reason = "skill_unavailable"; return false; }
                    SkillsAndPowersScreen.SelectNode(new SPNode(skill, null, false, null), player);
                    bool purchased = player.HasPart(skill.Class);
                    reason = purchased ? "purchased" : "not_purchased";
                    return purchased;
                }
                foreach (PowerEntry power in skill.PowerList)
                {
                    if (SkillId(power, skill) != id || (skill.Hidden && !player.HasPart(power.Class))) continue;
                    if (!CanPurchase(power, skill, player)) { reason = "skill_unavailable"; return false; }
                    var parent = new SPNode(skill, null, false, null);
                    SkillsAndPowersScreen.SelectNode(new SPNode(null, power, true, parent), player);
                    bool purchased = player.HasPart(power.Class);
                    reason = purchased ? "purchased" : "not_purchased";
                    return purchased;
                }
            }
            reason = "skill_unavailable";
            return false;
        }

        public static bool Raise(GameObject player, string attribute, out string reason)
        {
            if (Array.IndexOf(Attributes, attribute) < 0 || player.Stat("AP") < 1 ||
                player.GetStat(attribute).BaseValue >= 100)
            { reason = "attribute_unavailable"; return false; }
            int before = player.GetStat(attribute).BaseValue;
            StatusScreen.BuyStat(player, attribute);
            bool purchased = player.GetStat(attribute).BaseValue > before;
            reason = purchased ? "purchased" : "not_purchased";
            return purchased;
        }
    }
}
