using System;
using System.Text;
using System.Threading;
using ConsoleLib.Console;
using XRL;
using XRL.Core;
using XRL.World;

namespace LLMOfQud
{
    [Serializable]
    public class LLMOfQudSystem : IPlayerSystem
    {
        public const string VERSION = "0.0.1";

        private static bool _loadMarkerLogged;
        private static bool _afterRenderRegistered;

        // Snapshot request handshake between HandleEvent (game thread) and
        // AfterRenderCallback (render thread). Non-zero = "next render should
        // snapshot this turn number". Interlocked.Exchange on both sides gives
        // the full memory barrier; a plain int field is sufficient.
        private static int _pendingSnapshotTurn;

        private int _beginTurnCount;

        public override void RegisterPlayer(GameObject Player, IEventRegistrar Registrar)
        {
            if (!Registrar.IsUnregister && !_loadMarkerLogged)
            {
                _loadMarkerLogged = true;
                Logger.buildLog.Info(
                    "[LLMOfQud] loaded v" + VERSION +
                    " at " + DateTime.UtcNow.ToString("o"));
            }
            if (!Registrar.IsUnregister && !_afterRenderRegistered)
            {
                // XRLCore fires this after Zone.Render populates the source buffer
                // (including BackupChar for tile-mode cells) and BEFORE DrawBuffer
                // copies that source into CurrentBuffer through ConsoleChar.Copy,
                // which drops BackupChar. Source buffer is the only buffer from
                // which tile-mode ASCII glyphs are recoverable without mutating
                // game state.
                // decompiled/XRL.Core/XRLCore.cs:624-626 (RegisterAfterRenderCallback)
                // decompiled/XRL.Core/XRLCore.cs:2347-2351, 2380-2383, 2423-2426 (invocation sites)
                XRLCore.RegisterAfterRenderCallback(AfterRenderCallback);
                // Set the guard flag only after a successful Add so a hypothetical
                // throw inside RegisterAfterRenderCallback does not permanently
                // block future re-registration attempts.
                _afterRenderRegistered = true;
            }
            Registrar.Register(SingletonEvent<BeginTakeActionEvent>.ID);
            base.RegisterPlayer(Player, Registrar);
        }

        public override bool HandleEvent(BeginTakeActionEvent E)
        {
            _beginTurnCount++;
            // Ask the next render to snapshot. We cannot snapshot from here:
            // by the time HandleEvent runs, the only buffer we can reach
            // (TextConsole.CurrentBuffer) has already gone through
            // ScreenBuffer.Copy / ConsoleChar.Copy, which drops BackupChar.
            // decompiled/ConsoleLib.Console/TextConsole.cs:31 (CurrentBuffer)
            // decompiled/ConsoleLib.Console/TextConsole.cs:142-163 (DrawBuffer -> CurrentBuffer.Copy(Buffer))
            // decompiled/ConsoleLib.Console/ScreenBuffer.cs:291-308 (Copy dispatches per-cell ConsoleChar.Copy)
            // decompiled/ConsoleLib.Console/ConsoleChar.cs:385-400 (Copy omits BackupChar)
            Interlocked.Exchange(ref _pendingSnapshotTurn, _beginTurnCount);
            if (_beginTurnCount % 10 == 0)
            {
                MetricsManager.LogInfo(
                    "[LLMOfQud] begin_take_action count=" + _beginTurnCount);
            }
            return base.HandleEvent(E);
        }

        // Render a ScreenBuffer as an ASCII grid. Tile-mode cells hold the
        // ASCII glyph in BackupChar (written by Zone.Render when _Tile is set,
        // decompiled/XRL.World/Zone.cs:5411-5418); non-tile cells keep the
        // glyph in Char. Fall back Char -> BackupChar -> space.
        // decompiled/ConsoleLib.Console/ScreenBuffer.cs:21 (Buffer[,]), :79-100 (Width/Height)
        // decompiled/ConsoleLib.Console/ConsoleChar.cs:65 (BackupChar), :116 (Char property)
        private static string SnapshotAscii(ScreenBuffer buf)
        {
            if (buf == null)
            {
                return "<null-buffer>\n";
            }
            int w = buf.Width;
            int h = buf.Height;
            if (w <= 0 || h <= 0 || buf.Buffer == null)
            {
                return "<empty-buffer w=" + w + " h=" + h + ">\n";
            }
            StringBuilder sb = new StringBuilder(w * h + h);
            for (int y = 0; y < h; y++)
            {
                for (int x = 0; x < w; x++)
                {
                    ConsoleChar cell = buf.Buffer[x, y];
                    char c = cell.Char;
                    if (c == '\0') c = cell.BackupChar;
                    sb.Append(c == '\0' ? ' ' : c);
                }
                sb.Append('\n');
            }
            return sb.ToString();
        }

        // Fires on the render thread after Zone.Render but before DrawBuffer.
        // No-op unless HandleEvent requested a snapshot. Interlocked.Exchange
        // atomically captures-and-clears the requested turn so concurrent
        // BeginTakeActionEvent fires cannot double-log the same snapshot.
        // decompiled/MetricsManager.cs:407-409 (LogInfo -> Player.log)
        private static void AfterRenderCallback(XRLCore core, ScreenBuffer buf)
        {
            int turn = Interlocked.Exchange(ref _pendingSnapshotTurn, 0);
            if (turn == 0)
            {
                return;
            }
            try
            {
                int w = buf != null ? buf.Width : 0;
                int h = buf != null ? buf.Height : 0;
                string body = SnapshotAscii(buf);
                MetricsManager.LogInfo(
                    "[LLMOfQud][screen] BEGIN turn=" + turn + " w=" + w + " h=" + h + "\n" +
                    body +
                    "[LLMOfQud][screen] END turn=" + turn);
            }
            catch (Exception ex)
            {
                // Never let observation kill the mod. Each exception is logged
                // verbatim (type + message) so transient and recurring failures
                // both surface in Player.log without crashing the game. Phase 0-B
                // accepted ERROR=0 over 95 turns; if log spam ever shows up here,
                // dedupe at that point rather than pre-engineering a HashSet now.
                MetricsManager.LogInfo(
                    "[LLMOfQud][screen] ERROR turn=" + turn + " " + ex.GetType().Name + ": " + ex.Message);
            }
        }
    }
}
