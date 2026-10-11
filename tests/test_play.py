import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from harness.play import _play, assess_episode


class EpisodeTests(unittest.TestCase):
    def test_context_cannot_continue_without_saved_summary(self):
        before = {"seq": 1}
        after = {"ok": True, "seq": 11, "memory": {"episode_due": True}}
        self.assertEqual(assess_episode(before, after, 0), "missing_summary")

    def test_failed_or_incomplete_episode_does_not_restart_automatically(self):
        self.assertEqual(assess_episode({"seq": 1}, {"ok": True, "seq": 11}, 1), "player_failed")
        self.assertEqual(assess_episode({"seq": 1}, {"ok": False, "status": "pending"}, 0), "game_pending")
        self.assertEqual(assess_episode({"seq": 1}, {"ok": True, "seq": 1}, 0), "no_progress")

    def test_ten_decisions_and_summary_allow_fresh_context(self):
        self.assertEqual(assess_episode({"seq": 1}, {"ok": True, "seq": 11,
                         "memory": {"episode_due": False, "decisions_since_summary": 0}}, 0), "continue")

    def test_summary_written_before_final_action_is_insufficient(self):
        self.assertEqual(assess_episode({"seq": 1}, {"ok": True, "seq": 11,
                         "memory": {"episode_due": False, "decisions_since_summary": 1}}, 0), "missing_summary")


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_modal_cannot_be_counted_as_first_player_decision(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.call_tool.return_value = SimpleNamespace(structured_content={
            "ok": True, "seq": 7, "modal": {"type": "choice"},
            "memory": {"ok": True, "run_id": "current-run"},
        })
        gate = Mock()
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            token = directory / "token"
            token.write_text("test-token")
            args = SimpleNamespace(output_dir=directory / "episodes", duration_seconds=1)
            ready = {"token_file": str(token), "mcp_url": "http://127.0.0.1:1/mcp"}
            with patch("harness.play.Client", return_value=client), \
                    patch("harness.play.streamable_http_client"), \
                    patch("harness.play.run_episode", new_callable=AsyncMock,
                          return_value={"returncode": 0}) as player:
                with self.assertRaisesRegex(ValueError, "decision boundary"):
                    await _play(args, ready, gate)
                player.assert_not_awaited()
            gate.publish.assert_not_called()
            self.assertFalse((args.output_dir / "mcp.json").exists())
