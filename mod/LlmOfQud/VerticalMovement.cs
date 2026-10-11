// One bounded U/D action, following fixed 2.0.211.56 XRLCore CmdMoveU/CmdMoveD
// (XRLCore.cs:1417-1516). A bare GameObject.Move("U") skips those checks: outdoors
// it flew into the sky and fell back (.runtime/r10-live-20260927/worldmap-ascent-build8-red.json).
// Vanilla autostair ("<", ">") and distant-ascent walking ("M"+ID) start unbounded
// AutoAct, so they are refused with a message instead.
using System;
using System.Collections.Generic;
using ConsoleLib.Console;
using XRL;
using XRL.Messages;
using XRL.UI;
using XRL.World;

namespace LlmOfQud
{
    internal static class VerticalMovement
    {
        public static bool Move(string direction)
        {
            if (direction != "U" && direction != "D")
                throw new ArgumentOutOfRangeException(nameof(direction), direction, "Expected U or D");
            Cell start = The.Player.CurrentCell;
            string zoneId = start.ParentZone.ZoneID;
            int x = start.X, y = start.Y;
            if (direction == "U") Up();
            else Down();
            // Only the player's actual location decides success; event results do not.
            Cell end = The.Player.CurrentCell;
            return end != null && (end.ParentZone.ZoneID != zoneId || end.X != x || end.Y != y);
        }

        private static void Up()
        {
            // Stairs handle ClimbUp themselves (key check, Move("U")) and return false.
            if (!The.Player.CurrentCell.FireEvent(XRL.World.Event.New("ClimbUp", "GO", The.Player))) return;
            Cell cell = The.Player.CurrentCell;
            if (cell != null && !string.IsNullOrEmpty(cell.ParentZone.SpecialUpMessage()))
                Popup.Show(cell.ParentZone.SpecialUpMessage());
            else if (cell != null && !cell.ParentZone.IsWorldMap() && cell.ParentZone.Z <= 10 && !cell.ParentZone.IsInside())
                Ascend(cell);
            else if (!The.Player.CurrentCell.ParentZone.IsWorldMap())
                Refuse("You aren't on a stairway up. Move onto one first, then go up.");
        }

        private static void Down()
        {
            Cell cell = The.Player.CurrentCell;
            if (cell != null && cell.ParentZone.IsWorldMap())
                The.Player.PullDown(AllowAlternate: true);
            // Stairs handle ClimbDown themselves (key, levels, pull-down shafts) and return false.
            else if (cell.FireEvent(XRL.World.Event.New("ClimbDown", "GO", The.Player)) && !cell.ParentZone.IsWorldMap())
                Refuse("You aren't on a stairway down. Move onto one first, then go down.");
        }

        private static void Ascend(Cell cell)
        {
            if (The.Player.AreHostilesNearby() && !The.Player.IsFlying)
            {
                Popup.ShowFail("There are hostiles nearby!");
                return;
            }
            List<GameObject> ascents = cell.ParentZone.FindObjects((GameObject o) => o.CurrentCell.IsExplored()
                && o.HasRegisteredEvent("ClimbUp") && o.Render != null && o.Render.Visible
                && !o.HasTagOrIntProperty("ExcludeFromAscentSelection")
                && GenericQueryEvent.Check(o, "AscentEligible", null, null, 0, BaseResult: true));
            int choice = -1;
            if (ascents.Count > 0)
            {
                string[] names = new string[ascents.Count + 1];
                char[] keys = new char[names.Length];
                IRenderable[] icons = new IRenderable[names.Length];
                char key = 'b';
                names[0] = "world map";
                keys[0] = 'a';
                icons[0] = new Renderable("Mutations/teleport_other.bmp", " ", "&W", null, 'Y');
                for (int i = 1; i <= ascents.Count; i++)
                {
                    GameObject target = ascents[i - 1];
                    names[i] = target.DisplayNameOnlyDirect + " [" + The.Player.DescribeDirectionToward(target, General: true, Short: true) + "]";
                    keys[i] = key <= 'z' ? key++ : ' ';
                    icons[i] = target.RenderForUI();
                }
                choice = Popup.PickOption("Select a destination", null, "", "Sounds/UI/ui_notification", names, keys, icons, null, null, null, null, 1, 78, 0, -1, AllowEscape: true);
                if (choice == -1) return;
                if (choice > 0)
                {
                    Refuse("Move onto " + ascents[choice - 1].DisplayNameOnlyDirect + " first, then go up.");
                    return;
                }
            }
            // Choosing "world map" in the picker skips AskForWorldmap, as in vanilla.
            if (The.Player.CanTravel() && (choice != -1 || !Options.AskForWorldmap || Popup.ShowYesNoCancel("Are you sure you want to go to the world map?") == DialogResult.Yes))
                EnterWorldMap(cell);
        }

        private static void EnterWorldMap(Cell cell)
        {
            try
            {
                string address = cell.GetAddress();
                if (address.Contains(".")) The.Game.SetStringGameState("LastLocationOnSurface", address);
            }
            catch (Exception ex)
            {
                MetricsManager.LogException("[LLM] VerticalMovement LastLocationOnSurface", ex);
            }
            Zone active = The.ZoneManager.ActiveZone;
            Zone world = The.ZoneManager.GetZone(active.GetZoneWorld());
            Cell destination = world.GetCell(active.GetZonewX(), active.GetZonewY());
            GameObject terrain = destination.GetFirstObjectWithPart("TerrainTravel");
            if (!The.Player.DirectMoveTo(destination, 0, Forced: false, IgnoreCombat: false, IgnoreGravity: false, Ignore: terrain)) return;
            The.Player.PlayWorldOrUISound("sfx_worldMap_enter");
            Cell arrived = The.Player.CurrentCell;
            if (arrived != null && arrived.ParentZone == world) The.ZoneManager.SetActiveZone(world);
            The.ZoneManager.ProcessGoToPartyLeader();
        }

        private static void Refuse(string message)
        {
            MessageQueue.AddPlayerMessage(message);
        }
    }
}
