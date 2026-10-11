using System.Collections.Generic;
using System.Text;
using Newtonsoft.Json.Linq;
using Qud.API;
using XRL;
using XRL.Rules;
using XRL.UI;
using XRL.World;
using XRL.World.Anatomy;
using XRL.World.Effects;
using XRL.World.Parts;

namespace LlmOfQud
{
    // Production observation: only what the player can see in the modern UI.
    // Names always use GetDisplayName(AsIfKnown:false); other creatures only get WoundLevel text.
    // Item ids ("iN") are ephemeral handles valid for this observation only.
    internal static class ObservationBuilder
    {
        public const int KitMax = 64, GroundMax = 64, EffectsMax = 32;

        public static IEnumerable<GameObject> VisibleCreatures(GameObject player)
        {
            var zone = player.CurrentCell.ParentZone;
            foreach (var obj in zone.GetObjects())
                if (obj != player && obj.CurrentCell != null && obj.CurrentCell.ParentZone == zone && obj.IsVisible() &&
                    (obj.Brain != null || obj.HasPart("Combat"))) yield return obj;
        }

        public static JObject Build(GameObject player, string[] digest, string[] map, long mapFrame,
            Dictionary<string, GameObject> itemHandles)
        {
            var threats = new JArray(); int id = 0;
            foreach (var obj in VisibleCreatures(player))
                threats.Add(new JObject {
                    ["id"] = "e" + (++id), ["name"] = obj.GetDisplayName(AsIfKnown: false),
                    ["wound"] = Strings.WoundLevel(obj), ["x"] = obj.CurrentCell.X, ["y"] = obj.CurrentCell.Y,
                    ["hostile"] = obj.IsHostileTowards(player) });
            var cell = player.CurrentCell;
            return new JObject {
                ["vitals"] = new JObject { ["hp"] = player.hitpoints, ["max_hp"] = player.baseHitpoints,
                    ["x"] = cell.X, ["y"] = cell.Y,
                    ["zone"] = cell.ParentZone.ZoneID, ["turn"] = The.Game.Turns, ["energy"] = player.Energy.Value },
                ["threats"] = threats, ["digest"] = new JArray(digest),
                ["map"] = new JArray(map), ["map_frame"] = mapFrame,
                ["spatial"] = SpatialObservation.Build(player),
                ["kit"] = Kit(player, itemHandles), ["ground"] = Ground(player, itemHandles),
                ["status"] = Status(player), ["place"] = Place(player), ["goals"] = Goals(),
                ["character"] = CharacterGrowth.Build(player),
                ["item_details"] = ItemDetails(player, itemHandles) };
        }

        private static JArray ItemDetails(GameObject player, Dictionary<string, GameObject> handles)
        {
            var details = new JArray();
            var commands = new Dictionary<string, string> {
                { "eat", "Eat" }, { "drink", "Drink" }, { "apply", "Apply" },
                { "equip", "CommandEquipObject" }, { "open", "Open" } };
            foreach (var entry in handles)
            {
                if (!entry.Key.StartsWith("i", System.StringComparison.Ordinal)) continue;
                var item = entry.Value;
                string description = item.GetPart<Description>()?.GetShortDescription(AsIfKnown: false, NoConfusion: false) ?? "";
                if (description.Length > 8192) description = description.Substring(0, 8192);
                var actions = new JArray();
                var available = EquipmentAPI.GetInventoryActions(item, player);
                foreach (var pair in commands)
                {
                    if ((pair.Key == "equip" || pair.Key == "open") && item.InInventory != player) continue;
                    if (pair.Key == "open" && (!item.HasPart<Container>() || item.IsCreature)) continue;
                    int count = 0;
                    if (available != null)
                        foreach (var candidate in available)
                            if (candidate.Command == pair.Value && (pair.Key != "equip" || candidate.Name == "DoEquip")) count++;
                    if (count == 1) actions.Add(pair.Key);
                }
                details.Add(new JObject { ["id"] = entry.Key, ["description"] = description,
                    ["comparison_name"] = ComparisonName(item),
                    ["actions"] = actions, ["effect_details"] = EffectDetails(item, itemView: true) });
            }
            return details;
        }

        internal static JObject Goals()
        {
            const int limit = 16384;
            var text = new StringBuilder();
            foreach (var quest in QuestsAPI.allQuests())
            {
                // Same quest selection and formatter as Modern QuestsStatusScreen /
                // QuestsLine. GetLinesForQuest filters Hidden steps and collapsed text.
                if (quest.Finished) continue;
                var lines = QuestLog.GetLinesForQuest(quest, IncludeTitle: true, Clip: true, ClipWidth: 70);
                lines.Add((quest.QuestGiverName ?? "<unknown>") + " / " +
                    (quest.QuestGiverLocationName ?? "<unknown>"));
                foreach (string line in lines)
                {
                    if (text.Length + line.Length + 1 > limit)
                        return new JObject { ["text"] = text.ToString(), ["truncated"] = true };
                    text.Append(line).Append('\n');
                }
            }
            return new JObject { ["text"] = text.ToString(), ["truncated"] = false };
        }

        public static bool CanGet(GameObject player, GameObject item)
        {
            var here = player.CurrentCell;
            var cell = item.CurrentCell;
            return cell != null && cell.ParentZone == here.ParentZone && !here.ParentZone.IsWorldMap() &&
                ActionPolicy.CanReachCell(here.X, here.Y, cell.X, cell.Y) && item.IsVisible() &&
                Inventory.GetInteractableObjects(player, here, cell, false).Contains(item);
        }

        private static JArray Ground(GameObject player, Dictionary<string, GameObject> handles)
        {
            var items = new JArray();
            var here = player.CurrentCell;
            if (here.ParentZone.IsWorldMap()) return items;
            for (int y = System.Math.Max(0, here.Y - 1); y <= System.Math.Min(24, here.Y + 1); y++)
                for (int x = System.Math.Max(0, here.X - 1); x <= System.Math.Min(79, here.X + 1); x++)
                    foreach (var item in Inventory.GetInteractableObjects(player, here, here.ParentZone.GetCell(x, y), false))
                    {
                        if (items.Count >= GroundMax) return items;
                        if (!item.IsVisible()) continue;
                        string id = "p" + (items.Count + 1);
                        handles.Add(id, item);
                        items.Add(new JObject { ["id"] = id, ["name"] = item.GetDisplayName(AsIfKnown: false),
                            ["x"] = x, ["y"] = y });
                    }
            return items;
        }

        // Equipment screen: equipped items with their body-part slot, then carried inventory.
        private static JArray Kit(GameObject player, Dictionary<string, GameObject> handles)
        {
            handles.Clear();
            var kit = new JArray();
            var seen = new HashSet<GameObject>();
            if (player.Body != null)
                foreach (BodyPart part in player.Body.GetParts())
                {
                    var item = part.Equipped;
                    if (item == null || !seen.Add(item) || kit.Count >= KitMax) continue;
                    kit.Add(Item(kit.Count + 1, item, part.Name, handles));
                }
            foreach (var item in player.GetInventory())
            {
                if (kit.Count >= KitMax) break;
                if (seen.Add(item)) kit.Add(Item(kit.Count + 1, item, null, handles));
            }
            return kit;
        }

        private static JObject Item(int n, GameObject item, string slot, Dictionary<string, GameObject> handles)
        {
            string id = "i" + n;
            handles.Add(id, item);
            return new JObject { ["id"] = id, ["name"] = item.GetDisplayName(AsIfKnown: false),
                ["slot"] = slot == null ? null : (JToken)slot };
        }

        // Character screen effect list (CharacterStatusScreen: non-empty GetDescription) and HUD food/water.
        private static JObject Status(GameObject player)
        {
            var effects = new JArray();
            foreach (var effect in player.Effects)
            {
                if (effects.Count >= EffectsMax) break;
                string text = effect == null ? null : effect.GetDescription();
                if (!string.IsNullOrEmpty(text)) effects.Add(text);
            }
            var stomach = player.GetPart<Stomach>();
            return new JObject { ["effects"] = effects,
                ["effect_details"] = EffectDetails(player, itemView: false),
                ["on_fire"] = player.IsAflame(), ["frozen"] = player.IsFrozen(),
                ["nearby_liquids"] = NearbyLiquids(player),
                ["food_water"] = stomach == null ? "" : stomach.FoodStatus() + " " + stomach.WaterStatus() };
        }

        internal static HashSet<string> MacroEffects(GameObject player)
        {
            var result = new HashSet<string>();
            foreach (var effect in player.Effects)
            {
                string description = effect == null ? null : effect.GetDescription();
                if (string.IsNullOrEmpty(description) || effect is LiquidStained) continue;
                string name = ConsoleLib.Console.ColorUtility.StripFormatting(description).Trim().ToLowerInvariant();
                if (!MacroGuard.IsRoutineEffect(name)) result.Add(name);
            }
            if (player.IsAflame()) result.Add("burning");
            if (player.IsFrozen()) result.Add("frozen");
            return result;
        }

        private static JArray EffectDetails(GameObject target, bool itemView)
        {
            var details = new JArray();
            foreach (var effect in target.Effects)
            {
                if (details.Count >= EffectsMax) break;
                string name = effect == null ? null : effect.GetDescription();
                if (string.IsNullOrEmpty(name)) continue;
                if (itemView && effect.SuppressInLookDisplay() &&
                    !(effect is LiquidCovered) && !(effect is LiquidStained)) continue;
                string description = "";
                if (!itemView)
                    description = Campfire.ProcessEffectDescription(effect.GetDetails() ?? "", target);
                // An item's look text hides suppressed effects' details (including exact coating drams).
                // Its display-name adjective still exposes the coating name.
                details.Add(new JObject {
                    ["name"] = name.Length > 512 ? name.Substring(0, 512) : name,
                    ["description"] = description.Length > 4096 ? description.Substring(0, 4096) : description });
            }
            return details;
        }

        private static string ComparisonName(GameObject item)
        {
            // The normal public name retains visible stat tags and known modifiers. Single removes stack count.
            string name = item.GetDisplayName(AsIfKnown: false, Single: true, NoColor: true, Stripped: true);
            string baseName = item.GetDisplayName(AsIfKnown: false, Single: true, NoColor: true,
                Stripped: true, BaseOnly: true);
            foreach (var effect in item.Effects)
            {
                if (!(effect is LiquidCovered) && !(effect is LiquidStained)) continue;
                string adjective = effect.GetDescription()?.Strip();
                // Only remove the exact visible prefix before the item's epistemic base name.
                // If the shape is ambiguous, keep the full name and allow an extra review.
                name = ActionPolicy.WithoutVisibleAdjective(name, baseName, adjective);
            }
            return name.Length > 8192 ? name.Substring(0, 8192) : name;
        }

        private static JArray NearbyLiquids(GameObject player)
        {
            var liquids = new JArray();
            var here = player.CurrentCell;
            if (here.ParentZone.IsWorldMap()) return liquids;
            for (int y = System.Math.Max(0, here.Y - 1); y <= System.Math.Min(24, here.Y + 1); y++)
                for (int x = System.Math.Max(0, here.X - 1); x <= System.Math.Min(79, here.X + 1); x++)
                {
                    Cell cell = here.ParentZone.GetCell(x, y);
                    if (!cell.IsVisible()) continue;
                    GameObject liquid = cell.GetOpenLiquidVolume();
                    if (liquid == null || !liquid.IsVisible()) continue;
                    string name = liquid.GetDisplayName(AsIfKnown: false);
                    liquids.Add(new JObject { ["x"] = x, ["y"] = y,
                        ["name"] = name.Length > 512 ? name.Substring(0, 512) : name });
                }
            return liquids;
        }

        // HUD zone line (PlayerStatusBar: ParentZone.DisplayName).
        private static JObject Place(GameObject player)
        {
            var zone = player.CurrentCell.ParentZone;
            return new JObject { ["name"] = zone.DisplayName ?? "", ["world_map"] = zone.IsWorldMap(),
                ["lost"] = player.HasEffect<Lost>() };
        }
    }
}
