"""Subprocess test of `python -m harness`: files, readiness, secrecy and clean shutdown."""

import asyncio
import json
import os
import signal
import stat
import sys
import tempfile
import unittest
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from websockets.asyncio.client import connect

from harness.episode import EpisodeGate
from tests.support import request_frame, result_frame, RUN_ID

ROOT = Path(__file__).resolve().parents[1]


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


class EntrypointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.tmp.name) / "runs" / "r1"
        self.proc = None

    async def asyncTearDown(self):
        if self.proc is not None and self.proc.returncode is None:
            self.proc.kill()
            await self.proc.wait()
        self.tmp.cleanup()

    async def spawn(self, run_dir, *args):
        self.proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "harness", "--run-dir", str(run_dir), "--ws-port", "0",
            "--mcp-port", "0", *args, cwd=ROOT, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        return self.proc

    async def test_ready_files_secrecy_and_sigterm_shutdown(self):
        proc = await self.spawn(self.run_dir)
        async with asyncio.timeout(30):
            line = await proc.stdout.readline()
        ready = json.loads(line)
        self.assertEqual(ready["event"], "ready")
        ready_file = Path(ready["ready_file"])
        self.assertEqual(ready_file, self.run_dir / "ready.json")
        details = json.loads(ready_file.read_text())
        self.assertEqual(details["mcp_url"], f"http://127.0.0.1:{ready['mcp_port']}/mcp")
        self.assertEqual(details["ws_url"], f"ws://127.0.0.1:{ready['ws_port']}")

        token_path = self.run_dir / "token"
        token = token_path.read_text()
        self.assertGreaterEqual(len(token), 32)
        self.assertEqual(mode(self.run_dir), 0o700)
        self.assertEqual(mode(token_path), 0o600)
        self.assertEqual(mode(self.run_dir / "ledger.jsonl"), 0o600)
        self.assertEqual(mode(ready_file), 0o600)
        self.assertNotIn(token, line.decode())
        self.assertNotIn(token, ready_file.read_text())

        async with asyncio.timeout(5):
            game = await connect(details["ws_url"])
        await game.send(request_frame(1))
        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http:
            async with Client(streamable_http_client(details["mcp_url"], http_client=http)) as client:
                async with asyncio.timeout(20):
                    names = {tool.name for tool in (await client.list_tools()).tools}
                    state = (await client.call_tool("get_state", {})).structured_content
                    while not state["ok"]:
                        await asyncio.sleep(0.02)
                        state = (await client.call_tool("get_state", {})).structured_content
        self.assertEqual(names, {"get_state", "act", "wait_for_turn", "respond"})
        self.assertEqual(state["seq"], 1)
        async with httpx2.AsyncClient() as http:
            response = await http.post(details["mcp_url"], json={})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(token, response.text)
        await game.close()

        proc.send_signal(signal.SIGTERM)
        async with asyncio.timeout(20):
            stdout, stderr = await proc.communicate()
        self.assertEqual(proc.returncode, 0, stderr.decode())
        self.assertNotIn(token, stdout.decode())
        self.assertNotIn(token, stderr.decode())
        self.assertNotIn("authorization", (stdout + stderr).decode().lower())
        self.assertFalse(ready_file.exists())
        rows = (self.run_dir / "ledger.jsonl").read_text().splitlines()
        self.assertEqual(len(rows), 1)
        self.assertNotIn(token, (self.run_dir / "ledger.jsonl").read_text())
        for port in (ready["ws_port"], ready["mcp_port"]):
            with self.assertRaises(OSError):
                async with asyncio.timeout(5):
                    _, writer = await asyncio.open_connection("127.0.0.1", port)
                    writer.close()

    async def test_existing_non_empty_run_dir_is_refused(self):
        self.run_dir.mkdir(parents=True)
        marker = self.run_dir / "ledger.jsonl"
        marker.write_text("previous run\n")
        proc = await self.spawn(self.run_dir)
        async with asyncio.timeout(30):
            stdout, stderr = await proc.communicate()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("run dir", stderr.decode())
        self.assertEqual(marker.read_text(), "previous run\n")
        self.assertFalse((self.run_dir / "token").exists())

    async def test_episode_control_is_required_before_accepting_mcp_actions(self):
        proc = await self.spawn(self.run_dir, "--episode-control")
        async with asyncio.timeout(30):
            ready = json.loads(await proc.stdout.readline())
        details = json.loads(Path(ready["ready_file"]).read_text())
        gate = EpisodeGate(details["episode_control_file"])
        token = Path(details["token_file"]).read_text()
        async with asyncio.timeout(15):
            async with connect(details["ws_url"]) as game:
                await game.send(request_frame(1))
                async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http:
                    async with Client(streamable_http_client(details["mcp_url"], http_client=http)) as client:
                        while not (await client.call_tool("get_state", {})).structured_content["ok"]:
                            await asyncio.sleep(0.01)
                        result = await client.call_tool("act", {"expect_seq": 1, "action": "wait"})
                        self.assertEqual(result.structured_content["status"], "episode_unavailable")
                        with gate:
                            gate.publish(RUN_ID, 1)
                            async def finish():
                                decision = json.loads(await game.recv())
                                self.assertEqual(decision["seq"], 1)
                                await game.send(result_frame(1, action="wait"))
                                await game.send(request_frame(2))
                            completing = asyncio.create_task(finish())
                            accepted = await client.call_tool("act", {"expect_seq": 1, "action": "wait"})
                            await completing
                            self.assertTrue(accepted.structured_content["ok"])
                        refused = await client.call_tool("act", {"expect_seq": 2, "action": "wait"})
                        self.assertEqual(refused.structured_content["status"], "episode_unavailable")


if __name__ == "__main__":
    unittest.main()
