"""Real HTTP tests: token gate, Host/Origin protection and the three MCP tools."""

import asyncio
import contextlib
import json
import logging
import tempfile
import unittest
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from websockets.asyncio.client import connect

from harness.server import Harness
from harness.verify import verify_ledger
from tests.support import contains_key, request_frame, result_frame
from tests.test_modal_broker import modal_frame, modal_result
from tests.test_character import character

logging.getLogger("harness").setLevel(logging.CRITICAL)

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}


class McpHttpTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.tmp.name) / "run"
        self.harness = Harness(self.run_dir, ws_port=0, mcp_port=0, act_wait_s=0.3)
        async with asyncio.timeout(10):
            await self.harness.start()
        self.token = (self.run_dir / "token").read_text()
        self.mcp_port = self.harness.mcp_port
        self.url = f"http://127.0.0.1:{self.mcp_port}/mcp"
        self.ws_url = f"ws://127.0.0.1:{self.harness.ws_port}"

    async def asyncTearDown(self):
        async with asyncio.timeout(15):
            await self.harness.stop()
        self.tmp.cleanup()

    @contextlib.asynccontextmanager
    async def mcp(self):
        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {self.token}"}) as http:
            async with Client(streamable_http_client(self.url, http_client=http)) as client:
                yield client

    async def call(self, client, name, **arguments):
        async with asyncio.timeout(60):
            result = await client.call_tool(name, arguments)
        self.assertFalse(contains_key(result.structured_content, "telemetry"))
        for block in result.content:
            self.assertNotIn("telemetry", getattr(block, "text", ""))
            self.assertNotIn("game_queue", getattr(block, "text", ""))
        return result

    async def post_status(self, headers):
        base = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        base.update(headers)
        async with httpx2.AsyncClient() as http:
            async with asyncio.timeout(10):
                async with http.stream("POST", self.url, content=json.dumps(INITIALIZE),
                                       headers=base) as response:
                    return response.status_code


class ToolTests(McpHttpTestCase):
    async def test_growth_purchase_roundtrip_preserves_exact_fields_and_confirmed_state(self):
        async with asyncio.timeout(10):
            async with connect(self.ws_url) as game, self.mcp() as client:
                frame = json.loads(request_frame(1))
                frame["observation"]["character"] = character()
                await game.send(json.dumps(frame))
                while not (await self.call(client, "get_state")).structured_content.get("ok"):
                    await asyncio.sleep(.01)
                for seq, args in [(1, {"action": "learn_skill", "skill": "LongBlades_Test"}),
                                  (2, {"action": "raise_attribute", "attribute": "Strength"})]:
                    async def complete(seq=seq, args=args):
                        sent = json.loads(await game.recv())
                        self.assertEqual({k: sent[k] for k in args}, args)
                        self.assertEqual(sent["budget"], 1)
                        growth = frame["observation"]["character"]
                        if seq == 1:
                            growth["skill_points"] -= 50
                            growth["owned_skills"].append("LongBlades_Test")
                            growth["skill_catalog"][1].update(owned=True, eligible=False)
                        else:
                            growth["attribute_points"] -= 1
                            growth["attributes"]["Strength"] = {"base": 19, "value": 19}
                        result = json.loads(result_frame(seq, action=args["action"], reason="purchased"))
                        result["observation"]["character"] = growth
                        await game.send(json.dumps(result))
                        frame["seq"] = seq + 1
                        await game.send(json.dumps(frame))
                    task = asyncio.create_task(complete())
                    result = (await self.call(client, "act", expect_seq=seq, **args)).structured_content
                    await task
                    self.assertTrue(result["completed"])
                    observed = (await self.call(client, "get_state")).structured_content["observation"]["character"]
                    self.assertEqual(observed, frame["observation"]["character"])
                    repeated = (await self.call(client, "act", expect_seq=seq+1, **args)).structured_content
                    self.assertEqual(repeated["status"], "invalid")
        self.assertEqual(verify_ledger(self.run_dir / "ledger.jsonl", require_completed=2)["completed"], 2)

    async def test_modal_response_over_http_and_websocket(self):
        async with asyncio.timeout(10):
            async with connect(self.ws_url) as game, self.mcp() as client:
                await game.send(request_frame(1))
                await game.send(modal_frame())
                while True:
                    state = (await self.call(client, "get_state")).structured_content
                    if "modal" in state:
                        break
                    await asyncio.sleep(0.01)
                async def acknowledge():
                    answer = json.loads(await game.recv())
                    self.assertEqual(answer["kind"], "modal_answer")
                    self.assertEqual(answer["response"], {"choice": "button:1"})
                    await game.send(modal_result(answer_id=answer["answer_id"]))
                ack = asyncio.create_task(acknowledge())
                result = (await self.call(client, "respond", expect_seq=1,
                                          token=state["modal"]["token"],
                                          response={"choice": "button:1"})).structured_content
                await ack
                self.assertTrue(result["accepted"])
                self.assertTrue(result["completed"])
                state = (await self.call(client, "get_state")).structured_content
                self.assertEqual(state["seq"], 1)
                self.assertNotIn("modal", state)
                self.assertTrue(verify_ledger(self.run_dir / "ledger.jsonl")["ok"])

    async def test_only_four_tools_are_exposed(self):
        async with self.mcp() as client:
            async with asyncio.timeout(20):
                tools = (await client.list_tools()).tools
        by_name = {tool.name: tool for tool in tools}
        self.assertEqual(set(by_name), {"get_state", "act", "wait_for_turn", "respond"})
        self.assertEqual(sorted(by_name["respond"].input_schema["required"]),
                         ["expect_seq", "response", "token"])
        act = by_name["act"].input_schema
        self.assertEqual(act["properties"]["action"]["enum"], ["move", "attack", "wait", "explore", "goto", "rest", "talk", "eat", "drink", "apply", "get", "equip", "open", "learn_skill", "raise_attribute"])
        self.assertEqual(sorted(act["required"]), ["action", "expect_seq"])
        self.assertIn("rationale", act["properties"])
        self.assertEqual(act["properties"]["budget"]["default"], 20)
        wait = by_name["wait_for_turn"].input_schema
        self.assertEqual(wait["properties"]["timeout_s"]["default"], 45)

    async def test_get_state_without_game_is_not_ready(self):
        async with self.mcp() as client:
            result = await self.call(client, "get_state")
            self.assertEqual(result.structured_content["status"], "not_ready")
            act = await self.call(client, "act", expect_seq=1, action="wait")
            self.assertFalse(act.structured_content["ok"])
            self.assertEqual(act.structured_content["status"], "not_ready")

    async def test_turn_via_mcp_with_fake_game(self):
        async with asyncio.timeout(5):
            game = await connect(self.ws_url)
        try:
            await game.send(request_frame(1))

            async def play_turn():
                decision = await game.recv()
                await asyncio.sleep(0.6)  # longer than act_wait_s: act must return pending
                message = json.loads(decision)
                await game.send(result_frame(message["seq"], message["action"], px=41))
                await game.send(request_frame(2, px=41))
                return decision

            async with self.mcp() as client:
                for _ in range(100):
                    state = (await self.call(client, "get_state")).structured_content
                    if state["ok"]:
                        break
                    await asyncio.sleep(0.02)
                self.assertEqual(state["seq"], 1)
                self.assertEqual(len(state["observation"]["map"]), 25)

                stale = await self.call(client, "act", expect_seq=2, action="wait")
                self.assertEqual(stale.structured_content["status"], "stale_seq")
                bad_dir = await self.call(client, "act", expect_seq=1, action="wait", dir="N")
                self.assertEqual(bad_dir.structured_content["status"], "invalid")
                bool_seq = await self.call(client, "act", expect_seq=True, action="wait")
                self.assertTrue(bool_seq.is_error)
                wish = await self.call(client, "act", expect_seq=1, action="wish")
                self.assertTrue(wish.is_error)

                player = asyncio.create_task(play_turn())
                purpose = "階段へ向かうため東へ移動する。"
                act = (await self.call(client, "act", expect_seq=1, action="move", dir="E",
                                       rationale=purpose)).structured_content
                self.assertEqual(act, {"ok": True, "pending": True, "op_id": 1})
                again = (await self.call(client, "act", expect_seq=1, action="move", dir="E")).structured_content
                self.assertEqual(again["status"], "already_accepted")
                done = (await self.call(client, "wait_for_turn", op_id=1, timeout_s=10)).structured_content
                self.assertTrue(done["completed"])
                self.assertEqual(done["next_seq"], 2)
                self.assertEqual(done["result"]["observation"]["vitals"]["x"], 41)
                decision = await asyncio.wait_for(player, 5)
                self.assertEqual(json.loads(decision),
                                 {"kind": "decision", "run_id": json.loads(request_frame(1))["run_id"],
                                  "seq": 1, "action": "move", "dir": "E", "budget": 1})
                rows = [json.loads(line) for line in (self.run_dir / "ledger.jsonl").read_text().splitlines()]
                self.assertEqual(next(row["body"]["rationale"] for row in rows
                                      if row["kind"] == "decision"), purpose)
                state = (await self.call(client, "get_state")).structured_content
                self.assertEqual(state["seq"], 2)
                too_long = (await self.call(client, "wait_for_turn", op_id=1, timeout_s=46)).structured_content
                self.assertFalse(too_long["ok"])
        finally:
            await game.close()
        summary = verify_ledger(self.run_dir / "ledger.jsonl", require_completed=1, m1=True)
        self.assertEqual(summary["pending"], "request")


class HttpSecurityTests(McpHttpTestCase):
    async def test_missing_and_wrong_token_are_rejected(self):
        self.assertEqual(await self.post_status({}), 401)
        self.assertEqual(await self.post_status({"Authorization": "Bearer wrong"}), 401)
        self.assertEqual(await self.post_status({"Authorization": self.token}), 401)
        self.assertEqual(await self.post_status({"Authorization": f"Bearer {self.token}x"}), 401)

    async def test_gate_runs_before_sdk_host_check(self):
        self.assertEqual(await self.post_status({"Host": "evil.example"}), 401)

    async def test_host_and_origin_protection_with_valid_token(self):
        auth = {"Authorization": f"Bearer {self.token}"}
        self.assertEqual(await self.post_status(auth), 200)
        self.assertEqual(await self.post_status({**auth, "Origin": f"http://127.0.0.1:{self.mcp_port}"}), 200)
        self.assertEqual(await self.post_status({**auth, "Host": "evil.example"}), 421)
        self.assertEqual(await self.post_status({**auth, "Host": "127.0.0.1:1"}), 421)
        self.assertEqual(await self.post_status({**auth, "Origin": "http://evil.example"}), 403)

    async def raw_status(self, auth_lines):
        body = json.dumps(INITIALIZE).encode()
        head = (
            f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{self.mcp_port}\r\n"
            + "".join(f"Authorization: {value}\r\n" for value in auth_lines)
            + "Content-Type: application/json\r\nAccept: application/json, text/event-stream\r\n"
            + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        )
        async with asyncio.timeout(10):
            reader, writer = await asyncio.open_connection("127.0.0.1", self.mcp_port)
            try:
                writer.write(head.encode() + body)
                await writer.drain()
                status_line = await reader.readline()
            finally:
                writer.close()
                await writer.wait_closed()
        return int(status_line.split()[1])

    async def test_duplicate_authorization_is_rejected(self):
        valid = f"Bearer {self.token}"
        self.assertEqual(await self.raw_status([valid]), 200)
        self.assertEqual(await self.raw_status([valid, valid]), 401)
        self.assertEqual(await self.raw_status([valid, "Bearer wrong"]), 401)

    async def test_http_listener_is_loopback_only(self):
        for sock in self.harness.http_sockets:
            self.assertEqual(sock.getsockname()[0], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
