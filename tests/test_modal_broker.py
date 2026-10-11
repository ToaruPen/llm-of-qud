"""Modal responses must not consume another game action or a stale UI instance."""
import asyncio
import json

from harness.broker import ProtocolViolation
from harness.verify import VerifyError, verify_ledger
from tests.test_ledger_verify import read_rows, write_rows
from tests.support import RUN_ID, request_frame, result_frame
from tests.test_broker import BrokerTestCase, FakeConn, ledger_rows


def modal_frame(token="popup-1", seq=1, **updates):
    value = {"kind": "modal", "run_id": RUN_ID, "seq": seq, "token": token,
             "modal": {"type": "popup", "title": "Question", "text": "Continue?",
                       "choices": [{"id": "button:0", "label": "Yes"},
                                   {"id": "button:1", "label": "No"}],
                       "input_kind": "none", "constraints": {}}}
    value.update(updates)
    return json.dumps(value)


def modal_result(answer_id=1, token="popup-1", seq=1, accepted=True):
    return json.dumps({"kind": "modal_result", "run_id": RUN_ID, "seq": seq,
                       "token": token, "answer_id": answer_id, "accepted": accepted,
                       "reason": "accepted" if accepted else "invalid_input"})


class ModalBrokerTests(BrokerTestCase):
    async def test_watchdog_reports_without_acting_and_recovers_at_next_request(self):
        self.start()
        await self.broker.act(1, "wait")
        frame = json.dumps({"kind": "modal_watchdog", "run_id": RUN_ID, "seq": 1,
                            "reason": "unhandled_modal", "view": "UnrecognizedScreen",
                            "type": "unknown", "elapsed_ms": 30001})
        self.broker.handle_frame(self.conn, frame)
        self.broker.handle_frame(self.conn, frame)
        self.assertEqual(self.broker.get_state()["status"], "unhandled_modal")
        self.assertEqual(len(self.conn.sent), 1)
        self.broker.handle_frame(self.conn, result_frame(1, "wait"))
        self.broker.handle_frame(self.conn, request_frame(2))
        self.assertTrue(self.broker.get_state()["ok"])
        self.assertTrue(verify_ledger(self.ledger_path)["ok"])

    def show(self, **kwargs):
        frame = modal_frame(**kwargs)
        return self.broker.handle_frame(self.conn, frame)

    async def test_rehashed_answer_forgery_is_rejected(self):
        self.start()
        self.show()
        await self.broker.respond(1, "popup-1", {"choice": "button:1"})
        original = read_rows(self.ledger_path)
        import copy
        for key, value in [("modal_hash", "a" * 64), ("token", "old"),
                           ("answer_id", 4), ("response", {"choice": "secret"})]:
            rows = copy.deepcopy(original)
            rows[-1]["body"][key] = value
            write_rows(self.ledger_path, rows)
            with self.subTest(key=key), self.assertRaises(VerifyError):
                verify_ledger(self.ledger_path)

    async def test_closed_modal_is_not_replayed_after_external_close(self):
        self.start()
        self.show()
        await self.broker.respond(1, "popup-1", {"choice": "button:1"})
        self.broker.handle_frame(self.conn, json.dumps({"kind": "modal_clear", "run_id": RUN_ID,
            "seq": 1, "token": "popup-1", "reason": "external_close"}))
        self.assertIsNone(self.show())
        # A sent answer is not evidence of application; only modal_result accepted:true is.
        self.assertEqual(verify_ledger(self.ledger_path)["external_answers"], 1)

    async def test_non_string_modal_discriminators_fault_cleanly(self):
        self.start()
        bad = json.loads(modal_frame())
        bad["modal"]["type"] = []
        with self.assertRaises(ProtocolViolation):
            self.broker.handle_frame(self.conn, json.dumps(bad))

    async def test_modal_during_action_is_visible_and_answer_is_journaled_before_send(self):
        self.start()
        await self.broker.act(1, "wait")
        self.show()
        state = self.broker.get_state()
        self.assertTrue(state["ok"])
        self.assertEqual(state["modal"]["token"], "popup-1")
        observed = []
        self.conn.on_send = lambda _: observed.append(ledger_rows(self.ledger_path))
        answer = await self.broker.respond(1, "popup-1", {"choice": "button:1"})
        self.assertTrue(answer["pending"])
        self.assertEqual(observed[-1][-1]["kind"], "modal_answer")
        frame = json.loads(self.conn.sent[-1])
        self.assertEqual(frame["response"], {"choice": "button:1"})
        self.assertEqual(frame["kind"], "modal_answer")
        self.broker.handle_frame(self.conn, modal_result())
        self.broker.handle_frame(self.conn, result_frame(1, "wait"))
        self.broker.handle_frame(self.conn, request_frame(2))
        self.assertEqual(self.broker.get_state()["seq"], 2)
        self.assertEqual(verify_ledger(self.ledger_path, m1=True)["completed"], 1)
        self.assertEqual(verify_ledger(self.ledger_path)["external_answers"], 0)

    async def test_invalid_responses_do_not_claim_modal_or_append_decisions(self):
        self.start()
        self.show()
        before = self.kinds()
        for seq, token, answer in [(2, "popup-1", {"choice": "button:1"}),
                                   (1, "old", {"choice": "button:1"}),
                                   (True, "popup-1", {"choice": "button:1"}),
                                   (1, "popup-1", {"choice": "unknown"}),
                                   (1, "popup-1", {"choice": "button:1", "cancel": True}),
                                   (1, "popup-1", {"text": "wrong kind"}),
                                   (1, "popup-1", {"cancel": False})]:
            with self.subTest(seq=seq, token=token, answer=answer):
                self.assertFalse((await self.broker.respond(seq, token, answer))["ok"])
        self.assertEqual(self.kinds(), before)
        self.assertEqual(self.conn.sent, [])
        self.assertTrue((await self.broker.respond(1, "popup-1", {"choice": "button:1"}))["ok"])

    async def test_act_is_refused_while_modal_is_open(self):
        self.start()
        self.show()
        result = await self.broker.act(1, "wait")
        self.assertEqual(result["status"], "modal_required")
        self.assertEqual(self.conn.sent, [])

    async def test_rejected_ui_answer_permits_another_answer_but_pending_does_not(self):
        self.start()
        self.show()
        first = await self.broker.respond(1, "popup-1", {"choice": "button:1"})
        second = await self.broker.respond(1, "popup-1", {"choice": "button:0"})
        self.assertEqual(first["answer_id"], 1)
        self.assertEqual(second["status"], "answer_pending")
        self.assertEqual(len(self.conn.sent), 1)
        self.broker.handle_frame(self.conn, modal_result(accepted=False))
        self.assertFalse(self.broker.get_state()["last_modal_result"]["accepted"])
        third = await self.broker.respond(1, "popup-1", {"choice": "button:0"})
        self.assertEqual(third["answer_id"], 2)
        self.broker.handle_frame(self.conn, modal_result(answer_id=2))
        self.assertNotIn("modal", self.broker.get_state())
        self.assertTrue(verify_ledger(self.ledger_path)["ok"])

    async def test_modal_and_result_replays_are_idempotent_and_answer_bytes_are_identical(self):
        self.start()
        self.show()
        await self.broker.respond(1, "popup-1", {"choice": "button:1"})
        original = self.conn.sent[-1]
        self.broker.detach(self.conn)
        self.conn = FakeConn()
        self.broker.attach(self.conn)
        self.broker.handle_frame(self.conn, request_frame(1))
        reply = self.show()
        self.assertEqual(reply, original)
        before = len(ledger_rows(self.ledger_path))
        self.broker.handle_frame(self.conn, modal_result())
        self.broker.handle_frame(self.conn, modal_result())
        self.assertEqual(len(ledger_rows(self.ledger_path)), before + 1)

    async def test_changed_modal_with_same_token_faults(self):
        self.start()
        self.show()
        changed = json.loads(modal_frame())
        changed["modal"]["text"] = "A different question"
        with self.assertRaises(ProtocolViolation):
            self.broker.handle_frame(self.conn, json.dumps(changed))

    async def test_late_ack_after_next_request_does_not_clear_new_modal(self):
        self.start()
        await self.broker.act(1, "wait")
        self.show()
        await self.broker.respond(1, "popup-1", {"choice": "button:1"})
        self.broker.handle_frame(self.conn, result_frame(1, "wait"))
        self.broker.handle_frame(self.conn, request_frame(2))
        self.show(token="popup-2", seq=2)
        self.broker.handle_frame(self.conn, modal_result())
        self.assertEqual(self.broker.get_state()["modal"]["token"], "popup-2")
        self.assertTrue(verify_ledger(self.ledger_path)["ok"])

    async def test_cancelled_tool_wait_does_not_cancel_or_resubmit_accepted_answer(self):
        self.start()
        self.show()
        task = asyncio.create_task(self.broker.respond(1, "popup-1", {"choice": "button:1"}))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await self.broker.drain()
        self.assertEqual(len(self.conn.sent), 1)
        self.broker.handle_frame(self.conn, modal_result())
        self.assertTrue(self.broker.get_state()["last_modal_result"]["accepted"])

    async def test_clear_records_external_disappearance_without_answering(self):
        self.start()
        self.show()
        frame = json.dumps({"kind": "modal_clear", "run_id": RUN_ID, "seq": 1,
                            "token": "popup-1", "reason": "external_close"})
        self.broker.handle_frame(self.conn, frame)
        self.broker.handle_frame(self.conn, frame)
        self.assertNotIn("modal", self.broker.get_state())
        self.assertEqual(self.conn.sent, [])
        self.assertEqual(self.kinds(), [("request", 1), ("modal", 1), ("modal_clear", 1)])
        self.assertEqual(verify_ledger(self.ledger_path)["external_answers"], 1)

    async def test_number_and_required_text_constraints_are_checked_before_send(self):
        self.start()
        value = json.loads(modal_frame())
        value["modal"].update(type="string", choices=[], input_kind="string",
                               constraints={"required_text": "ENTOMB", "restrict_chars": "ABCDEFGHIJKLMNOPQRSTUVWXYZ"})
        self.broker.handle_frame(self.conn, json.dumps(value))
        self.assertFalse((await self.broker.respond(1, "popup-1", {"text": "wrong"}))["ok"])
        self.assertTrue((await self.broker.respond(1, "popup-1", {"text": "ENTOMB"}))["ok"])
