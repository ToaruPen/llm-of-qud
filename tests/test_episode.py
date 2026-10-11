import json

from harness.episode import EpisodeGate
from harness.memory import MemoryStore
from tests.test_broker import BrokerTestCase
from tests.test_modal_broker import modal_frame, modal_result
from tests.support import OTHER_RUN_ID, request_frame, result_frame


class EpisodeGateTests(BrokerTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.start()
        self.gate = EpisodeGate(self.ledger_path.parent / "episode.json")
        self.broker.episode_gate = self.gate

    async def test_eleventh_action_is_refused_even_after_player_saves_checkpoint(self):
        with self.gate:
            self.gate.publish(self.broker.run_id, 1)
            for seq in range(1, 11):
                self.assertTrue((await self.broker.act(seq, "wait"))["ok"])
                self.broker.handle_frame(self.conn, result_frame(seq, action="wait", turn=seq + 1))
                self.broker.handle_frame(self.conn, request_frame(seq + 1, turn=seq + 1))
            memory = MemoryStore(self.ledger_path.parent / "memory", self.broker)
            try:
                current = memory.status()["current_source"]
                self.assertTrue(memory.checkpoint(11, "Done", "Next", "None", "New evidence", [current])["ok"])
                self.assertFalse(memory.status()["episode_due"])
                before = self.kinds()
                result = await self.broker.act(11, "wait")
                self.assertEqual(result["status"], "episode_complete")
                self.assertEqual(self.kinds(), before)
                self.assertEqual(len(self.conn.sent), 10)
                self.assertTrue(self.broker.get_state()["ok"])
            finally:
                memory.close()
            self.gate.publish(self.broker.run_id, 11)
            self.assertTrue((await self.broker.act(11, "wait"))["ok"])

    async def test_missing_malformed_stale_or_closed_window_cannot_accept_an_action(self):
        self.assertEqual((await self.broker.act(1, "wait"))["status"], "episode_unavailable")
        with self.gate:
            self.gate.publish(OTHER_RUN_ID, 1)
            self.assertEqual((await self.broker.act(1, "wait"))["status"], "episode_unavailable")
            for data in ('{', json.dumps({"run_id": self.broker.run_id, "first_seq": 1, "stop_seq": 999})):
                self.gate.path.write_text(data)
                self.assertEqual((await self.broker.act(1, "wait"))["status"], "episode_unavailable")
            self.gate.publish(self.broker.run_id, 2)
            self.assertEqual((await self.broker.act(1, "wait"))["status"], "episode_unavailable")
        self.assertFalse(self.gate.path.exists())
        self.assertFalse((await self.broker.act(1, "wait"))["ok"])
        self.assertEqual(self.kinds(), [("request", 1)])

    async def test_last_action_can_finish_a_modal_without_granting_another_action(self):
        with self.gate:
            self.gate.publish(self.broker.run_id, 1)
            for seq in range(1, 10):
                await self.broker.act(seq, "wait")
                self.broker.handle_frame(self.conn, result_frame(seq, action="wait"))
                self.broker.handle_frame(self.conn, request_frame(seq + 1))
            await self.broker.act(10, "wait")
            self.broker.handle_frame(self.conn, modal_frame(seq=10))
            self.assertTrue((await self.broker.respond(10, "popup-1", {"choice": "button:1"}))["ok"])
            self.broker.handle_frame(self.conn, modal_result(seq=10))
            self.broker.handle_frame(self.conn, result_frame(10, action="wait"))
            self.broker.handle_frame(self.conn, request_frame(11))
            self.assertTrue((await self.broker.wait_for_turn(10, 0))["completed"])
            self.assertEqual((await self.broker.act(11, "wait"))["status"], "episode_complete")

    async def test_second_controller_cannot_replace_an_active_window(self):
        with self.gate:
            self.gate.publish(self.broker.run_id, 1)
            original = self.gate.path.read_bytes()
            with self.assertRaisesRegex(ValueError, "controller"):
                with EpisodeGate(self.gate.path):
                    pass
            self.assertEqual(self.gate.path.read_bytes(), original)
