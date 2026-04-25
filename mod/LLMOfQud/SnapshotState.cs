using System.Collections.Generic;
using System.Globalization;
using System.Text;
using XRL;
using XRL.UI;
using XRL.World;
using XRL.World.Anatomy;
using XRL.World.Parts;
using XRL.World.Parts.Mutation;

namespace LLMOfQud
{
    internal sealed class PendingSnapshot
    {
        public int Turn;
        public string StateJson;
        // Captured on the game thread alongside StateJson. AfterRenderCallback
        // MUST consume this rather than re-reading Options.UseTiles, which can
        // flip between turns and would otherwise produce inconsistent
        // mode= (in [screen]) vs display_mode= (in [state]) framing for the
        // same turn. See ADR 0002 + game-thread routing rule
        // docs/architecture-v5.md:1787-1790.
        public string DisplayMode;
        // Phase 0-D: RuntimeCapabilityProfile JSON for this turn. Built on the
        // game thread inside HandleEvent so all CoQ API reads stay on the
        // game queue (docs/architecture-v5.md:1787-1790). Render thread emits
        // verbatim. Per docs/memo/phase-0-c-exit-2026-04-25.md:117, future
        // observation fields thread through this object, never as parallel
        // Interlocked.Exchange slots.
        public string CapsJson;
    }

    internal static class SnapshotState
    {
        // JSON string escape per RFC 8259 §7. Wrapping quotes are appended.
        // Handles: \", \\, \b, \f, \n, \r, \t, U+0000..U+001F as \u00XX,
        // and U+2028/U+2029 escaped to <U+2028> / <U+2029> because some downstream
        // JSON parsers treat the raw bytes as line terminators which would
        // break a single-line LogInfo emission.
        internal static void AppendJsonString(StringBuilder sb, string value)
        {
            sb.Append('"');
            if (value == null)
            {
                sb.Append('"');
                return;
            }
            int len = value.Length;
            for (int i = 0; i < len; i++)
            {
                char c = value[i];
                switch (c)
                {
                    case '\\': sb.Append("\\\\"); break;
                    case '"':  sb.Append("\\\""); break;
                    case '\b': sb.Append("\\b"); break;
                    case '\f': sb.Append("\\f"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    case '\u2028': sb.Append("\\u2028"); break;
                    case '\u2029': sb.Append("\\u2029"); break;
                    default:
                        if (c < 0x20)
                        {
                            sb.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                        }
                        else
                        {
                            sb.Append(c);
                        }
                        break;
                }
            }
            sb.Append('"');
        }

        // Small JSON object for the ascii-source counter. Takes raw counts
        // (not a struct) so the caller can wire it into either the [screen]
        // line metadata or a future structured framing without SnapshotState
        // knowing about either. Currently unused — Tasks 2-3's [screen] BEGIN
        // line uses an inline `src=char:N,backup:N,blank:N` format. Retained
        // for Phase 0-D+ structured-framing reuse.
        internal static void AppendAsciiSourcesJson(
            StringBuilder sb, int charCount, int backupCount, int blankCount)
        {
            sb.Append("{\"char\":").Append(charCount.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"backup_char\":").Append(backupCount.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"blank\":").Append(blankCount.ToString(CultureInfo.InvariantCulture));
            sb.Append('}');
        }

        // Single entity record. Caller is responsible for separating multiple
        // records with commas. Schema:
        //   {
        //     "id": "e1",                  // snapshot-local; regenerated per turn
        //     "name": "snapjaw",            // ShortDisplayNameStripped
        //     "glyph": "s",                 // Render.RenderString first char, or "?"
        //     "pos": {"x": 41, "y": 13},   // absolute Cell coordinates
        //     "rel": {"dx": 1, "dy": 1},   // relative to player
        //     "distance": 2,                // path distance via DistanceTo
        //     "adjacent": false,            // distance == 1
        //     "hostile_to_player": true,    // GameObject.IsHostileTowards(player)
        //     "hp": [12, 18]                // [current, max]; null if no Statistics
        //   }
        // decompiled/XRL.World/GameObject.cs:766 (ShortDisplayNameStripped)
        // decompiled/XRL.World/GameObject.cs:1177-1213 (baseHitpoints / hitpoints)
        // decompiled/XRL.World/GameObject.cs:2972-2986 (DistanceTo(GameObject))
        // decompiled/XRL.World/GameObject.cs:10887-10894 (IsHostileTowards)
        // decompiled/XRL.World.Parts/Render.cs:42 (RenderString)
        internal static void AppendEntity(
            StringBuilder sb, int idOrdinal, GameObject player, GameObject obj)
        {
            Cell pCell = player?.CurrentCell;
            Cell oCell = obj?.CurrentCell;
            int px = pCell != null ? pCell.X : 0;
            int py = pCell != null ? pCell.Y : 0;
            int ox = oCell != null ? oCell.X : 0;
            int oy = oCell != null ? oCell.Y : 0;
            int distance = (player != null && obj != null) ? player.DistanceTo(obj) : 9999999;
            bool adjacent = (distance == 1);
            bool hostile = (player != null && obj != null) ? obj.IsHostileTowards(player) : false;
            int hp = obj?.hitpoints ?? 0;
            int hpMax = obj?.baseHitpoints ?? 0;
            bool hasHp = (obj != null) && (hpMax > 0);

            string name = obj?.ShortDisplayNameStripped ?? "<unknown>";
            Render render = obj?.Render;
            string glyphSource = render != null ? render.RenderString : null;
            char glyphChar = (!string.IsNullOrEmpty(glyphSource)) ? glyphSource[0] : '?';

            sb.Append("{\"id\":\"e").Append(idOrdinal.ToString(CultureInfo.InvariantCulture)).Append('"');
            sb.Append(",\"name\":");
            AppendJsonString(sb, name);
            sb.Append(",\"glyph\":");
            AppendJsonString(sb, glyphChar.ToString());
            sb.Append(",\"pos\":{\"x\":").Append(ox.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"y\":").Append(oy.ToString(CultureInfo.InvariantCulture)).Append('}');
            sb.Append(",\"rel\":{\"dx\":").Append((ox - px).ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"dy\":").Append((oy - py).ToString(CultureInfo.InvariantCulture)).Append('}');
            sb.Append(",\"distance\":").Append(distance.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"adjacent\":").Append(adjacent ? "true" : "false");
            sb.Append(",\"hostile_to_player\":").Append(hostile ? "true" : "false");
            if (hasHp)
            {
                sb.Append(",\"hp\":[").Append(hp.ToString(CultureInfo.InvariantCulture));
                sb.Append(',').Append(hpMax.ToString(CultureInfo.InvariantCulture)).Append(']');
            }
            else
            {
                sb.Append(",\"hp\":null");
            }
            sb.Append('}');
        }

        // Entry point used by HandleEvent. Returns the full state-line payload
        // (the value of the [LLMOfQud][state] line; caller adds the prefix).
        // Schema:
        //   {
        //     "turn": N,
        //     "player": {"id": "p", "name": "@", "hp": [cur, max]},
        //     "pos": {"x": X, "y": Y, "zone": "<ZoneID or null>"},
        //     "display_mode": "tile" | "ascii",
        //     "entities": [ ...AppendEntity records... ]
        //   }
        // decompiled/XRL/The.cs:23 (Player), :31 (ZoneManager)
        // decompiled/XRL.World/ZoneManager.cs:58 (ActiveZone field)
        // decompiled/XRL.World/Zone.cs:388-398 (ZoneID property), :1982-2010 (GetObjects)
        // decompiled/XRL.World/Cell.cs:210 (X), :212 (Y), :214 (ParentZone)
        // decompiled/XRL.UI/Options.cs:574-576 (UseTiles)
        // decompiled/XRL.World/GameObject.cs:9930- (IsVisible)
        internal static string BuildStateJson(int turn, out string displayMode)
        {
            GameObject player = The.Player;
            Cell pCell = player?.CurrentCell;
            Zone zone = pCell?.ParentZone ?? The.ZoneManager?.ActiveZone;
            string zoneId = zone?.ZoneID;
            int px = pCell != null ? pCell.X : 0;
            int py = pCell != null ? pCell.Y : 0;
            int hp = player?.hitpoints ?? 0;
            int hpMax = player?.baseHitpoints ?? 0;
            displayMode = Options.UseTiles ? "tile" : "ascii";

            StringBuilder sb = new StringBuilder(2048);
            sb.Append("{\"turn\":").Append(turn.ToString(CultureInfo.InvariantCulture));

            // Player block.
            sb.Append(",\"player\":{\"id\":\"p\",\"name\":");
            AppendJsonString(sb, player?.ShortDisplayNameStripped ?? "<no-player>");
            if (player != null && hpMax > 0)
            {
                sb.Append(",\"hp\":[").Append(hp.ToString(CultureInfo.InvariantCulture));
                sb.Append(',').Append(hpMax.ToString(CultureInfo.InvariantCulture)).Append(']');
            }
            else
            {
                sb.Append(",\"hp\":null");
            }
            sb.Append('}');

            // Position block.
            sb.Append(",\"pos\":{\"x\":").Append(px.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"y\":").Append(py.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"zone\":");
            if (zoneId != null) AppendJsonString(sb, zoneId); else sb.Append("null");
            sb.Append('}');

            // Display mode.
            sb.Append(",\"display_mode\":");
            AppendJsonString(sb, displayMode);

            // Entities (visible, non-player, with Brain-or-Combat-or-HP).
            sb.Append(",\"entities\":[");
            if (zone != null && player != null)
            {
                int ordinal = 0;
                foreach (GameObject obj in zone.GetObjects())
                {
                    if (obj == null) continue;
                    if (obj == player) continue;
                    if (obj.CurrentCell == null) continue;
                    if (!obj.IsVisible()) continue;
                    // Entity gate: must be a creature-like object. Brain present
                    // OR HasPart("Combat") OR has positive baseHitpoints. This
                    // excludes terrain, items, and decorative objects without
                    // committing to a fixed taxonomy.
                    bool isCreatureLike = (obj.Brain != null) || obj.HasPart("Combat") || obj.baseHitpoints > 0;
                    if (!isCreatureLike) continue;

                    ordinal++;
                    if (ordinal > 1) sb.Append(',');
                    AppendEntity(sb, ordinal, player, obj);
                }
            }
            sb.Append(']');

            sb.Append('}');
            return sb.ToString();
        }

        // Schema:
        //   [
        //     {
        //       "class": "Carapace",                  // BaseMutation type-name
        //       "name": "Carapace",                    // Mutation entry Name
        //       "display_name": "Carapace",            // Stripped display string
        //       "base_level": 4,                       // Player-invested level
        //       "level": 4,                            // Resolved level (CalcLevel)
        //       "ui_display_level": 4,                 // m.GetUIDisplayLevel():
        //                                              //   the actual UI-displayed
        //                                              //   value. Default returns
        //                                              //   Level, but specific
        //                                              //   mutation subclasses
        //                                              //   override it (CoQ's
        //                                              //   own character-sheet UI
        //                                              //   consumes this method).
        //       "type": "Physical",                    // Mutation category
        //       "can_level": true,                     // Whether further leveling
        //                                              //   is possible
        //       "is_active": true                      // Level > 0 (matches
        //                                              //   ActiveMutationList filter)
        //     }
        //   ]
        // decompiled/XRL.World.Parts/Mutations.cs:86 (MutationList)
        // decompiled/XRL.World.Parts.Mutation/BaseMutation.cs:117-130 (Level/BaseLevel)
        internal static void AppendMutations(StringBuilder sb, GameObject player)
        {
            sb.Append('[');
            Mutations mutPart = player?.GetPart<Mutations>();
            List<BaseMutation> list = mutPart?.MutationList;
            if (list != null && list.Count > 0)
            {
                int i = 0;
                foreach (BaseMutation m in list)
                {
                    if (m == null) continue;
                    if (i > 0) sb.Append(',');
                    i++;

                    string className = m.GetType().Name;
                    string name = m.Name ?? "";
                    string displayName = (m.DisplayName ?? m.Name ?? "").Strip() ?? "";
                    int baseLevel = m.BaseLevel;
                    int level = m.Level;
                    int uiDisplayLevel = m.GetUIDisplayLevel(); // base default is Level; subclasses override
                    string type = m.Type ?? "";
                    bool canLevel = m.CanLevel();
                    bool isActive = level > 0;

                    sb.Append("{\"class\":");
                    AppendJsonString(sb, className);
                    sb.Append(",\"name\":");
                    AppendJsonString(sb, name);
                    sb.Append(",\"display_name\":");
                    AppendJsonString(sb, displayName);
                    sb.Append(",\"base_level\":").Append(baseLevel.ToString(CultureInfo.InvariantCulture));
                    sb.Append(",\"level\":").Append(level.ToString(CultureInfo.InvariantCulture));
                    sb.Append(",\"ui_display_level\":").Append(uiDisplayLevel.ToString(CultureInfo.InvariantCulture));
                    sb.Append(",\"type\":");
                    AppendJsonString(sb, type);
                    sb.Append(",\"can_level\":").Append(canLevel ? "true" : "false");
                    sb.Append(",\"is_active\":").Append(isActive ? "true" : "false");
                    sb.Append('}');
                }
            }
            sb.Append(']');
        }

        // Schema:
        //   [
        //     {
        //       "guid": "5e4f3...e",                  // ActivatedAbilityEntry.ID
        //       "command": "CommandFireMissileWeapon",
        //       "display_name": "Fire Missile Weapon",
        //       "class": "Carapace",                   // ActivatedAbilityEntry.Class
        //       "enabled": true,
        //       "toggleable": false,
        //       "toggle_state": false,
        //       "active_toggle": false,
        //       "always_allow_toggle_off": false,
        //       "visible": true,                       // ActivatedAbilityEntry.Visible
        //                                              //   (UI surfacing, separate
        //                                              //   from enabled / usability)
        //       "cooldown_segments_raw": 0,            // CommandCooldown.Segments
        //                                              //   (true storage; bypasses
        //                                              //   the toggle special-case
        //                                              //   in the Cooldown getter)
        //       "cooldown_segments_effective": 0,      // ActivatedAbilityEntry.Cooldown
        //                                              //   getter: returns Segments
        //                                              //   in the normal case;
        //                                              //   returns 0 ONLY when
        //                                              //   AlwaysAllowToggleOff &&
        //                                              //   ToggleState &&
        //                                              //   Toggleable (toggle is
        //                                              //   currently ON for an
        //                                              //   indefinitely-on ability)
        //       "cooldown_rounds": 0,                  // ceil(cooldown_segments_effective/10)
        //                                              //   matches the in-game UI
        //                                              //   "rounds remaining" value
        //       "is_usable": true                      // Enabled && (cooldown_effective==0 ||
        //                                              //   (toggle_state && active_toggle))
        //     }
        //   ]
        // decompiled/XRL.World.Parts/ActivatedAbilities.cs:181 (AbilityByGuid)
        // decompiled/XRL.World.Parts/ActivatedAbilityEntry.cs:195 (Visible)
        // decompiled/XRL.World.Parts/ActivatedAbilityEntry.cs:259-308 (Cooldown/CooldownRounds/IsUsable)
        // decompiled/XRL.World/CommandCooldown.cs:11-13 (Command/Segments)
        internal static void AppendAbilities(StringBuilder sb, GameObject player)
        {
            sb.Append('[');
            ActivatedAbilities aaPart = player?.GetPart<ActivatedAbilities>();
            Dictionary<System.Guid, ActivatedAbilityEntry> map = aaPart?.AbilityByGuid;
            if (map != null && map.Count > 0)
            {
                int i = 0;
                foreach (KeyValuePair<System.Guid, ActivatedAbilityEntry> kv in map)
                {
                    ActivatedAbilityEntry e = kv.Value;
                    if (e == null) continue;
                    if (i > 0) sb.Append(',');
                    i++;

                    string guid = kv.Key.ToString();
                    string command = e.Command ?? "";
                    string displayName = (e.DisplayName ?? e.Command ?? "").Strip() ?? "";
                    string className = e.Class ?? "";
                    bool enabled = e.Enabled;
                    bool toggleable = e.Toggleable;
                    bool toggleState = e.ToggleState;
                    bool activeToggle = e.ActiveToggle;
                    bool alwaysAllowToggleOff = e.AlwaysAllowToggleOff;
                    bool visible = e.Visible;
                    int cooldownRaw = (e.CommandCooldown != null) ? e.CommandCooldown.Segments : 0;
                    int cooldownEffective = e.Cooldown; // getter returns 0 for AlwaysAllowToggleOff && ToggleState && Toggleable
                    int cooldownRounds = e.CooldownRounds;
                    bool isUsable = e.IsUsable;

                    sb.Append("{\"guid\":");
                    AppendJsonString(sb, guid);
                    sb.Append(",\"command\":");
                    AppendJsonString(sb, command);
                    sb.Append(",\"display_name\":");
                    AppendJsonString(sb, displayName);
                    sb.Append(",\"class\":");
                    AppendJsonString(sb, className);
                    sb.Append(",\"enabled\":").Append(enabled ? "true" : "false");
                    sb.Append(",\"toggleable\":").Append(toggleable ? "true" : "false");
                    sb.Append(",\"toggle_state\":").Append(toggleState ? "true" : "false");
                    sb.Append(",\"active_toggle\":").Append(activeToggle ? "true" : "false");
                    sb.Append(",\"always_allow_toggle_off\":").Append(alwaysAllowToggleOff ? "true" : "false");
                    sb.Append(",\"visible\":").Append(visible ? "true" : "false");
                    sb.Append(",\"cooldown_segments_raw\":").Append(cooldownRaw.ToString(CultureInfo.InvariantCulture));
                    sb.Append(",\"cooldown_segments_effective\":").Append(cooldownEffective.ToString(CultureInfo.InvariantCulture));
                    sb.Append(",\"cooldown_rounds\":").Append(cooldownRounds.ToString(CultureInfo.InvariantCulture));
                    sb.Append(",\"is_usable\":").Append(isUsable ? "true" : "false");
                    sb.Append('}');
                }
            }
            sb.Append(']');
        }

        // Entry point used by HandleEvent to build the caps line payload
        // (the value of the [LLMOfQud][caps] line; caller adds the prefix).
        // Schema runtime_caps.v1 = {turn, schema, mutations, abilities,
        // effects, equipment}. Schema bumps (v2+) require an ADR. Field
        // order is locked; reordering requires an ADR.
        internal static string BuildCapsJson(int turn, GameObject player)
        {
            StringBuilder sb = new StringBuilder(8192);
            sb.Append("{\"turn\":").Append(turn.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"schema\":\"runtime_caps.v1\"");

            sb.Append(",\"mutations\":");
            AppendMutations(sb, player);

            sb.Append(",\"abilities\":");
            AppendAbilities(sb, player);

            sb.Append('}');
            return sb.ToString();
        }
    }
}
