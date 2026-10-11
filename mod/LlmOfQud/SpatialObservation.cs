using Newtonsoft.Json.Linq;
using XRL.World;
using XRL.World.Effects;
using XRL.World.Parts;

namespace LlmOfQud
{
    internal static class SpatialObservation
    {
        // Read only visible objects. Never query native pathfinding or hidden solids.
        public static JObject Build(GameObject player)
        {
            var here = player.CurrentCell;
            var zone = here.ParentZone;
            bool confused = player.HasEffect<Confused>();
            var visibility = new JArray();
            var terrain = new JArray();
            var nearby = new JArray();
            for (int y = 0; y < 25; y++)
            {
                var seen = new char[80];
                var kinds = new char[80];
                for (int x = 0; x < 80; x++)
                {
                    var cell = zone.GetCell(x, y);
                    bool visible = cell.IsVisible() && cell.IsExplored() && cell.IsLit();
                    seen[x] = visible ? 'v' : cell.IsExplored() ? 'm' : 'u';
                    kinds[x] = '?';
                    if (!visible || confused) continue;
                    bool solid = false, door = false, liquid = false, up = false, down = false;
                    var names = new JArray();
                    bool adjacent = System.Math.Max(System.Math.Abs(x - here.X), System.Math.Abs(y - here.Y)) <= 1;
                    foreach (var obj in cell.GetObjectsInCell())
                    {
                        if (obj == player || !obj.IsVisible() || obj.Brain != null || obj.HasPart("Combat")) continue;
                        solid |= obj.ConsiderSolidFor(player);
                        door |= obj.HasPart("Door");
                        liquid |= obj.GetPart<LiquidVolume>()?.IsOpenVolume() == true;
                        up |= obj.HasPart("StairsUp");
                        down |= obj.HasPart("StairsDown");
                        if (adjacent && names.Count < 4)
                        {
                            string name = obj.GetDisplayName(AsIfKnown: false);
                            if (!string.IsNullOrEmpty(name)) names.Add(name.Length > 256 ? name.Substring(0, 256) : name);
                        }
                    }
                    kinds[x] = ActionPolicy.TerrainGlyph(visible, confused, solid, door, liquid, up, down);
                    if (adjacent && names.Count > 0)
                        nearby.Add(new JObject { ["x"] = x, ["y"] = y, ["names"] = names });
                }
                visibility.Add(new string(seen));
                terrain.Add(new string(kinds));
            }
            return new JObject { ["visibility"] = visibility, ["terrain"] = terrain, ["nearby"] = nearby };
        }
    }
}
