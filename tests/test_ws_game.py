import asyncio
import json
import logging
import tempfile
import unittest
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.protocol import State

from harness.broker import Broker
from harness.ledger import Ledger
from harness.verify import verify_ledger
from harness.ws_game import GameListener
from tests.support import (OTHER_RUN_ID, heartbeat_frame, make_observation, request_frame,
                           result_frame)

logging.getLogger("harness").setLevel(logging.CRITICAL)
logging.getLogger("websockets").setLevel(logging.CRITICAL)


def ledger_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


class GameListenerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger_path = Path(self.tmp.name) / "ledger.jsonl"
        self.ledger = Ledger.create(self.ledger_path)
        self.broker = Broker(self.ledger, act_wait_s=0.2)
        self.listener = GameListener(self.broker, port=0)
        await self.listener.start()
        self.url = f"ws://127.0.0.1:{self.listener.port}"
        self.clients = []

    async def asyncTearDown(self):
        for ws in self.clients:
            # Rejected clients may already have disposed their asyncio transport.
            # Avoid asking websockets to abort that closed transport a second time.
            if ws.state is not State.CLOSED:
                await ws.close()
            await ws.wait_closed()
        self.broker.shutdown()
        await self.listener.stop()
        await self.broker.drain()
        self.ledger.close()
        self.tmp.cleanup()

    async def connect(self, **kwargs):
        async with asyncio.timeout(5):
            ws = await connect(self.url, **kwargs)
        self.clients.append(ws)
        return ws

    async def until(self, predicate, timeout=5):
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(0.01)

    async def recv(self, ws, timeout=5):
        async with asyncio.timeout(timeout):
            return await ws.recv()

    async def assert_nothing_received(self, ws, timeout=0.3):
        with self.assertRaises(TimeoutError):
            async with asyncio.timeout(timeout):
                await ws.recv()

    async def assert_closed_with(self, ws, code):
        with self.assertRaises(ConnectionClosed) as ctx:
            async with asyncio.timeout(5):
                while True:
                    await ws.recv()
        self.assertEqual(ctx.exception.rcvd.code, code)

    def kinds(self):
        return [(row["kind"], row["seq"]) for row in ledger_rows(self.ledger_path)]

    async def test_listener_binds_loopback_only(self):
        self.assertEqual(self.listener.host, "127.0.0.1")
        for sock in self.listener.sockets:
            self.assertEqual(sock.getsockname()[0], "127.0.0.1")

    async def test_full_turn_with_reconnect_replays_identical_decision(self):
        ws1 = await self.connect()
        await ws1.send(heartbeat_frame(0))
        await ws1.send(request_frame(1))
        await self.until(lambda: self.broker.get_state()["ok"])
        state = self.broker.get_state()
        self.assertEqual(state["observation"], make_observation())

        act = asyncio.create_task(self.broker.act(1, "move", "NW"))
        decision = await self.recv(ws1)
        rows_at_receipt = ledger_rows(self.ledger_path)
        self.assertEqual([r["kind"] for r in rows_at_receipt], ["request", "decision"])
        self.assertEqual(rows_at_receipt[1]["body"]["request_hash"], rows_at_receipt[0]["hash"])
        self.assertEqual(json.loads(decision)["dir"], "NW")
        self.assertEqual((await act)["pending"], True)

        await ws1.close()
        await self.until(lambda: self.broker.conn is None)
        self.assertEqual(self.broker.get_state()["status"], "pending")

        ws2 = await self.connect()
        await ws2.send(request_frame(1))
        replayed = await self.recv(ws2)
        self.assertEqual(replayed, decision, "replayed decision must be byte-identical")
        self.assertEqual(self.kinds(), [("request", 1), ("decision", 1)])

        await ws2.send(result_frame(1, "move", px=39, py=11))
        await ws2.send(request_frame(2, px=39, py=11))
        result = await asyncio.wait_for(self.broker.wait_for_turn(1, 5), 6)
        self.assertTrue(result["completed"])
        self.assertEqual(result["next_seq"], 2)
        self.assertEqual(result["result"]["observation"]["vitals"]["x"], 39)

        await ws2.close()
        await self.until(lambda: self.broker.conn is None)
        ws3 = await self.connect()
        await ws3.send(result_frame(1, "move", px=39, py=11))
        await ws3.send(request_frame(2, px=39, py=11))
        await self.assert_nothing_received(ws3)
        self.assertEqual(self.kinds(), [("request", 1), ("decision", 1), ("result", 1), ("request", 2)])
        summary = verify_ledger(self.ledger_path, require_completed=1, m1=True)
        self.assertEqual(summary["pending"], "request")
        self.assertTrue(summary["m1"])

    async def test_second_active_socket_is_refused(self):
        ws1 = await self.connect()
        await ws1.send(request_frame(1))
        await self.until(lambda: self.broker.get_state()["ok"])
        ws2 = await self.connect()
        await self.assert_closed_with(ws2, 1008)
        act = await self.broker.act(1, "wait")
        self.assertTrue(act["ok"])
        self.assertEqual(json.loads(await self.recv(ws1))["action"], "wait")

    async def test_browser_origin_is_rejected(self):
        with self.assertRaises(InvalidStatus) as ctx:
            async with asyncio.timeout(5):
                await connect(self.url, origin="http://evil.example")
        self.assertEqual(ctx.exception.response.status_code, 403)
        self.assertIsNone(self.broker.conn)

    async def test_foreign_run_is_closed_without_faulting(self):
        ws1 = await self.connect()
        await ws1.send(request_frame(1))
        await self.until(lambda: self.broker.get_state()["ok"])
        await ws1.close()
        await self.until(lambda: self.broker.conn is None)
        intruder = await self.connect()
        await intruder.send(request_frame(1, run_id=OTHER_RUN_ID))
        await self.assert_closed_with(intruder, 1008)
        await self.until(lambda: self.broker.conn is None)
        self.assertEqual(self.broker.get_state()["status"], "disconnected")
        ws2 = await self.connect()
        await ws2.send(request_frame(1))
        await self.until(lambda: self.broker.get_state()["ok"])
        self.assertEqual(self.kinds(), [("request", 1)])

    async def test_conflicting_replay_closes_socket_and_faults(self):
        ws1 = await self.connect()
        await ws1.send(request_frame(1))
        await self.until(lambda: self.broker.get_state()["ok"])
        await ws1.close()
        await self.until(lambda: self.broker.conn is None)
        ws2 = await self.connect()
        await ws2.send(request_frame(1, hp=3))
        await self.assert_closed_with(ws2, 1008)
        self.assertEqual(self.broker.get_state()["status"], "faulted")
        self.assertEqual(self.kinds(), [("request", 1)])

    async def test_oversized_frame_is_rejected(self):
        ws = await self.connect(max_size=None)
        await ws.send(request_frame(1)[:-1] + ', "pad": "' + "x" * (1 << 20) + '"}')
        await self.assert_closed_with(ws, 1009)
        self.assertEqual(self.kinds(), [])

    async def test_stop_closes_game_connection(self):
        ws = await self.connect()
        await ws.send(request_frame(1))
        await self.until(lambda: self.broker.get_state()["ok"])
        await self.listener.stop()
        with self.assertRaises(ConnectionClosed):
            async with asyncio.timeout(5):
                await ws.recv()
        with self.assertRaises(OSError):
            async with asyncio.timeout(5):
                await connect(self.url)


if __name__ == "__main__":
    unittest.main()
