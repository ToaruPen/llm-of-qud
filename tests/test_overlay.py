"""Loopback OBS overlay: read-only projection, SSE, Host/Origin/method gate and lifecycle."""

import asyncio
import contextlib
import json
import logging
import re
import signal
import socket
import sys
import tempfile
import unittest
from pathlib import Path

import httpx2
from websockets.asyncio.client import connect

from harness.broker import Broker
from harness.ledger import GENESIS_HASH, Ledger
from harness.overlay import CSP, OverlayApp, OverlayFeed
from harness.server import Harness
from tests.support import (SAVE_SHA256, game_fault_frame, make_observation, recovery_frame,
                           request_frame, result_frame, suspended_frame)
from tests.test_broker import FakeConn

logging.getLogger("harness").setLevel(logging.CRITICAL)

ROOT = Path(__file__).resolve().parents[1]
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HOSTILE = "<img src=x onerror=alert(1)></script><script>alert(2)</script>\"'&amp;\r\nnext end"
SECRET_PATH = "/Users/someone/private/save.sav"
METHODS = ("POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD")
PATHS = ("/", "/overlay.js", "/overlay.css", "/state", "/events")
FORBIDDEN_SINKS = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                   "Function(", "setAttribute(\"on", "srcdoc")


async def raw_request(port, method="GET", path="/state", host=None, extra=(), version="HTTP/1.1"):
    """One request on a fresh socket; returns (status, [(name, value)], body)."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        lines = [f"{method} {path} {version}"]
        if host is not False:
            lines.append(f"Host: {host or f'127.0.0.1:{port}'}")
        lines.extend(extra)
        lines.append("Connection: close")
        writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
        await writer.drain()
        async with asyncio.timeout(10):
            data = await reader.read()
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
    head, _, body = data.partition(b"\r\n\r\n")
    status_line, *header_lines = head.decode("latin-1").split("\r\n")
    headers = []
    for line in header_lines:
        name, _, value = line.partition(":")
        headers.append((name.strip().lower(), value.strip()))
    return int(status_line.split()[1]), headers, body


class Sse:
    """Minimal EventSource-like reader over httpx2 (one JSON data line per event)."""

    def __init__(self, url):
        self.url = url
        self.data_lines = []

    async def __aenter__(self):
        self._client = httpx2.AsyncClient(timeout=None)
        self._stream = self._client.stream("GET", self.url)
        self.response = await self._stream.__aenter__()
        self._lines = self.response.aiter_lines()
        return self

    async def __aexit__(self, *exc):
        await self._stream.__aexit__(*exc)
        await self._client.aclose()

    async def next(self, timeout=5):
        data = []
        async with asyncio.timeout(timeout):
            while True:
                line = await anext(self._lines)
                if line.startswith("data:"):
                    data.append(line[5:].removeprefix(" "))
                elif line == "" and data:
                    break
        self.data_lines.extend(data)
        return json.loads("\n".join(data))

    async def until(self, predicate, timeout=5):
        async with asyncio.timeout(timeout):
            while True:
                snapshot = await self.next(timeout)
                if predicate(snapshot):
                    return snapshot


def leftover_tasks():
    current = asyncio.current_task()
    return {task for task in asyncio.all_tasks() if task is not current and not task.done()}


class OverlayTestCase(unittest.IsolatedAsyncioTestCase):
    overlay_port = 0

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.tmp.name) / "run"
        self.harness = Harness(self.run_dir, ws_port=0, mcp_port=0,
                               overlay_port=self.overlay_port, act_wait_s=0.3)
        async with asyncio.timeout(10):
            await self.harness.start()
        self.token = (self.run_dir / "token").read_text()
        self.ws_url = f"ws://127.0.0.1:{self.harness.ws_port}"
        if self.harness.overlay is not None:
            self.harness.overlay.poll_s = 0.05
            self.port = self.harness.overlay_http.port
            self.base = f"http://127.0.0.1:{self.port}"

    async def asyncTearDown(self):
        async with asyncio.timeout(15):
            await self.harness.stop()
        self.tmp.cleanup()

    def sse(self):
        return Sse(self.base + "/events")

    async def state(self):
        status, _, body = await raw_request(self.port)
        self.assertEqual(status, 200)
        return json.loads(body)

    def assert_private_absent(self, text):
        for secret in (self.token, str(self.run_dir), self.tmp.name, "ledger.jsonl", "token_file",
                       "telemetry", "game_queue", "XRL.Core", SAVE_SHA256, "Roleplay-7f3a",
                       "request_hash", "decision_hash", "frame_sha256", SECRET_PATH):
            self.assertNotIn(secret, text)

    def assert_head(self, snapshot):
        self.assertRegex(snapshot["head_hash"], HEX64)
        self.assertEqual(snapshot["head_hash"], self.harness.ledger.head_hash)
        self.assertEqual(snapshot["rows"], self.harness.ledger.next_index)


class ReadyAndStaticTests(OverlayTestCase):
    async def test_ephemeral_port_ready_metadata_and_initial_state(self):
        self.assertNotEqual(self.port, 0)
        ready = json.loads((self.run_dir / "ready.json").read_text())
        self.assertEqual(ready["overlay_url"], f"http://127.0.0.1:{self.port}/")
        self.assertEqual(self.harness.overlay_url, ready["overlay_url"])
        snapshot = await self.state()
        self.assertEqual(snapshot["status"], "not_ready")
        self.assertEqual(snapshot["head_hash"], GENESIS_HASH)
        self.assertEqual(snapshot["rows"], 0)
        self.assertIsNone(snapshot["sitrep"])
        self.assertIsNone(snapshot["decision"])
        self.assertTrue(snapshot["projection_ok"])

    async def test_static_page_is_text_only_and_locked_down(self):
        bodies = {}
        for path in ("/", "/overlay.js", "/overlay.css", "/state"):
            status, headers, body = await raw_request(self.port, path=path)
            self.assertEqual(status, 200, path)
            names = dict(headers)
            self.assertEqual(names["content-security-policy"], CSP)
            self.assertEqual(names["cache-control"], "no-store")
            self.assertEqual(names["x-content-type-options"], "nosniff")
            self.assertFalse([n for n, _ in headers if n.startswith("access-control-")])
            bodies[path] = body.decode("utf-8")
        self.assertIn("script-src 'self'", CSP)
        self.assertNotIn("unsafe", CSP)
        self.assertIn('lang="ja"', bodies["/"])
        self.assertIn("<script src=\"/overlay.js\"", bodies["/"])
        self.assertNotIn("<script>", bodies["/"])
        for sink in FORBIDDEN_SINKS:
            self.assertNotIn(sink, bodies["/overlay.js"])
        self.assertIn("textContent", bodies["/overlay.js"])
        self.assertIn("未記録", bodies["/"])
        self.assertIn('suspended: "ゲーム停止中（セーブ再読込待ち）"', bodies["/overlay.js"])
        self.assertIn("モデルの判断理由ではありません", bodies["/"])
        for text in bodies.values():
            self.assert_private_absent(text)
        status, _, _ = await raw_request(self.port, path="/nope")
        self.assertEqual(status, 404)


class DisabledOverlayTests(OverlayTestCase):
    overlay_port = None

    async def test_overlay_is_opt_in(self):
        self.assertIsNone(self.harness.overlay)
        self.assertIsNone(self.harness.overlay_http)
        self.assertIsNone(self.harness.overlay_url)
        self.assertIsNone(self.harness.ledger.on_append)
        ready = json.loads((self.run_dir / "ready.json").read_text())
        self.assertNotIn("overlay_url", ready)


class TransitionTests(OverlayTestCase):
    async def test_decision_is_retained_across_result_and_next_request(self):
        async with self.sse() as events, connect(self.ws_url) as game:
            first = await events.next()
            self.assertEqual(first["status"], "not_ready")
            self.assertEqual(first["head_hash"], GENESIS_HASH)

            await game.send(request_frame(1))
            waiting = await events.until(lambda s: s["status"] == "awaiting_decision")
            self.assert_head(waiting)
            self.assertEqual(waiting["sitrep"]["seq"], 1)
            self.assertEqual(waiting["sitrep"]["basis"], "request")
            self.assertTrue(waiting["sitrep"]["current"])
            self.assertEqual(len(waiting["sitrep"]["digest"]), 6)
            self.assertEqual(waiting["sitrep"]["digest"][-1], make_observation()["digest"][-1])
            self.assertIsNone(waiting["decision"])

            act = asyncio.create_task(self.harness.broker.act(1, "move", "N"))
            async with asyncio.timeout(5):
                decision = json.loads(await game.recv())
            self.assertEqual((decision["seq"], decision["action"]), (1, "move"))
            pending = await events.until(lambda s: s["status"] == "pending")
            self.assert_head(pending)
            self.assertFalse(pending["sitrep"]["current"])
            self.assertEqual(pending["decision"]["outcome"], "pending")
            self.assertIsNone(pending["decision"]["rationale"])

            await game.send(result_frame(1, "move", reason=HOSTILE, turn=2))
            recorded = await events.until(lambda s: s["status"] == "result_recorded")
            self.assert_head(recorded)
            self.assertEqual(recorded["sitrep"]["basis"], "result")
            self.assertTrue(recorded["sitrep"]["current"])
            self.assertEqual(recorded["decision"]["outcome"], "completed")

            await game.send(request_frame(2, turn=2))
            nxt = await events.until(lambda s: s["seq"] == 2 and s["status"] == "awaiting_decision")
            async with asyncio.timeout(5):
                report = await act
            self.assertTrue(report["ok"])
            self.assertEqual(await self.state(), nxt)
        self.assert_head(nxt)
        self.assertEqual(nxt["rows"], 4)
        self.assertEqual((nxt["sitrep"]["seq"], nxt["sitrep"]["basis"]), (2, "request"))
        self.assertTrue(nxt["sitrep"]["current"])
        decision = nxt["decision"]
        self.assertEqual({k: decision[k] for k in ("seq", "action", "dir", "budget", "outcome")},
                         {"seq": 1, "action": "move", "dir": "N", "budget": 1, "outcome": "completed"})
        self.assertIn("rationale", decision)
        self.assertIsNone(decision["rationale"])
        self.assertNotIn("reason", decision)
        self.assertEqual(decision["result"]["engine_reason"],
                         HOSTILE.replace("\r", "�").replace("\n", "�").replace(" ", "�"))
        self.assertTrue(decision["result"]["executed"])
        self.assert_private_absent(json.dumps(nxt))

    async def test_recovery_interrupts_decision_and_voids_sitrep(self):
        async with self.sse() as events, connect(self.ws_url) as game:
            await game.send(request_frame(1))
            await events.until(lambda s: s["status"] == "awaiting_decision")
            act = asyncio.create_task(self.harness.broker.act(1, "explore", budget=7))
            async with asyncio.timeout(5):
                await game.recv()
            await events.until(lambda s: s["status"] == "pending")
            await game.send(recovery_frame(1))
            recovering = await events.until(lambda s: s["status"] == "recovering")
            async with asyncio.timeout(5):
                self.assertEqual((await act)["status"], "interrupted")
            self.assert_head(recovering)
            self.assertFalse(recovering["sitrep"]["current"])
            self.assertEqual(recovering["decision"]["outcome"], "interrupted")
            self.assertEqual(recovering["decision"]["budget"], 7)
            self.assertIsNone(recovering["decision"]["result"])
            self.assert_private_absent(json.dumps(recovering))

            await game.send(request_frame(2, turn=100))
            fresh = await events.until(lambda s: s["status"] == "awaiting_decision")
        self.assert_head(fresh)
        self.assertTrue(fresh["sitrep"]["current"])
        self.assertEqual(fresh["decision"]["seq"], 1)
        self.assertEqual(fresh["decision"]["outcome"], "interrupted")

    async def test_suspension_stops_showing_an_accepted_decision_as_executing(self):
        async with self.sse() as events, connect(self.ws_url) as game:
            await game.send(request_frame(1))
            await events.until(lambda s: s["status"] == "awaiting_decision")
            act = asyncio.create_task(self.harness.broker.act(1, "wait"))
            async with asyncio.timeout(5):
                await game.recv()
            await game.send(suspended_frame(1))
            paused = await events.until(lambda s: s["status"] == "suspended")
            await act
            self.assertFalse(paused["sitrep"]["current"])
            self.assertEqual(paused["decision"]["outcome"], "suspended")
            self.assertIsNone(paused["decision"]["result"])
            self.assert_head(paused)
            await game.send(recovery_frame(1, reason="save_reload"))
            recovered = await events.until(lambda s: s["status"] == "recovering")
            self.assertEqual(recovered["decision"]["outcome"], "interrupted")

    async def test_suspension_without_a_current_decision_keeps_the_completed_one(self):
        """save_quit after seq 1 completed and seq 2 was requested (live build7 run9)."""
        async with self.sse() as events, connect(self.ws_url) as game:
            await game.send(request_frame(1))
            await events.until(lambda s: s["status"] == "awaiting_decision")
            act = asyncio.create_task(self.harness.broker.act(1, "move", "N"))
            async with asyncio.timeout(5):
                await game.recv()
            await game.send(result_frame(1, "move", turn=2))
            await game.send(request_frame(2, turn=2))
            await events.until(lambda s: s["seq"] == 2 and s["status"] == "awaiting_decision")
            async with asyncio.timeout(5):
                self.assertTrue((await act)["ok"])

            await game.send(suspended_frame(2))
            stopped = await events.until(lambda s: s["status"] == "suspended")
            self.assertEqual(self.harness.broker.get_state()["suspended_seq"], 2)
            self.assert_head(stopped)
            self.assertEqual(stopped["seq"], 2)
            self.assertTrue(stopped["connected"])
            self.assertEqual((stopped["sitrep"]["seq"], stopped["sitrep"]["basis"]), (2, "request"))
            self.assertFalse(stopped["sitrep"]["current"])
            decision = stopped["decision"]
            self.assertEqual((decision["seq"], decision["outcome"]), (1, "completed"))
            self.assertTrue(decision["result"]["executed"])
            self.assertNotIn("suspended_seq", stopped)
            self.assertNotIn("observation", json.dumps(stopped))
            self.assert_private_absent(json.dumps(stopped))

            rows = self.harness.ledger.next_index
            rejected = await self.harness.broker.act(2, "wait")
            self.assertEqual((rejected["ok"], rejected["status"]), (False, "not_ready"))
            self.assertEqual(self.harness.ledger.next_index, rows)
            self.assertEqual((await self.state())["status"], "suspended")

            await game.send(recovery_frame(2, reason="save_reload"))
            await events.until(lambda s: s["status"] == "recovering")
            await game.send(request_frame(3, turn=100))
            resumed = await events.until(lambda s: s["seq"] == 3 and s["status"] == "awaiting_decision")
        self.assert_head(resumed)
        self.assertTrue(resumed["sitrep"]["current"])
        self.assertEqual((resumed["decision"]["seq"], resumed["decision"]["outcome"]), (1, "completed"))

    async def test_disconnect_and_fault_keep_head_hash_and_mark_state_not_current(self):
        async with self.sse() as events:
            async with connect(self.ws_url) as game:
                await game.send(request_frame(1))
                await events.until(lambda s: s["status"] == "awaiting_decision")
            gone = await events.until(lambda s: s["status"] == "disconnected")
            self.assert_head(gone)
            self.assertFalse(gone["connected"])
            self.assertFalse(gone["sitrep"]["current"])

            async with connect(self.ws_url) as game:
                await game.send(request_frame(1))
                await events.until(lambda s: s["status"] == "awaiting_decision")
                await game.send(game_fault_frame(1, reason=f"{SECRET_PATH} {HOSTILE}"))
                faulted = await events.until(lambda s: s["status"] == "faulted")
        self.assert_head(faulted)
        self.assertEqual(faulted["rows"], 2)
        self.assertFalse(faulted["sitrep"]["current"])
        self.assert_private_absent(json.dumps(faulted))
        self.assertNotIn("alert", json.dumps(faulted))


class HostileTextTests(OverlayTestCase):
    async def test_untrusted_strings_are_bounded_json_data(self):
        observation = make_observation()
        observation["digest"] = [HOSTILE, "x" * 5000] + [f"line {i}" for i in range(4)]
        observation["vitals"]["zone"] = HOSTILE
        observation["place"] = {"name": HOSTILE * 3, "world_map": False, "lost": True}
        async with self.sse() as events, connect(self.ws_url) as game:
            await game.send(request_frame(1, observation=observation))
            snapshot = await events.until(lambda s: s["status"] == "awaiting_decision")
        cleaned = HOSTILE.replace("\r", "�").replace("\n", "�").replace(" ", "�")
        sitrep = snapshot["sitrep"]
        self.assertEqual(sitrep["zone"], cleaned)
        self.assertEqual(sitrep["place"], {"name": (cleaned * 3)[:159] + "…", "world_map": False,
                                           "lost": True})
        self.assertEqual(sitrep["digest"][0], cleaned)
        self.assertEqual(len(sitrep["digest"][1]), 160)
        for line in events.data_lines:
            self.assertTrue(line.isascii())
            self.assertNotIn("\r", line)
            self.assertNotIn("<", line)
        status, _, page = await raw_request(self.port, path="/")
        self.assertEqual(status, 200)
        self.assertNotIn(b"onerror", page)


class GateTests(OverlayTestCase):
    async def test_bad_host_and_origin_are_rejected(self):
        port = self.port
        ok = f"http://127.0.0.1:{port}"
        cases = {
            "evil host": ({"host": "evil.example"}, 421),
            "wrong port": ({"host": "127.0.0.1:1"}, 421),
            "no port": ({"host": "127.0.0.1"}, 421),
            "ipv6 host": ({"host": f"[::1]:{port}"}, 421),
            "suffix host": ({"host": f"127.0.0.1:{port}.evil"}, 421),
            "no host http/1.0": ({"host": False, "version": "HTTP/1.0"}, 421),
            "duplicate host": ({"extra": (f"Host: 127.0.0.1:{port}",)}, 400),
            "evil origin": ({"extra": ("Origin: http://evil.example",)}, 403),
            "null origin": ({"extra": ("Origin: null",)}, 403),
            "origin no port": ({"extra": ("Origin: http://127.0.0.1",)}, 403),
            "origin wrong port": ({"extra": ("Origin: http://127.0.0.1:1",)}, 403),
            "https origin": ({"extra": (f"Origin: https://127.0.0.1:{port}",)}, 403),
            "origin with path": ({"extra": (f"Origin: {ok}/",)}, 403),
            "duplicate origin": ({"extra": (f"Origin: {ok}", f"Origin: {ok}")}, 403),
            "localhost ok": ({"host": f"localhost:{port}"}, 200),
            "origin ok": ({"extra": (f"Origin: {ok}",)}, 200),
            "localhost origin ok": ({"extra": (f"Origin: http://localhost:{port}",)}, 200),
        }
        for name, (kwargs, expected) in cases.items():
            with self.subTest(name):
                # h11 answers a duplicate Host with 400 (logged) before the app sees it.
                logs = (self.assertLogs("uvicorn.error", "WARNING") if expected == 400
                        else contextlib.nullcontext())
                with logs:
                    status, headers, _ = await raw_request(port, path="/state", **kwargs)
                self.assertEqual(status, expected)
                self.assertFalse([n for n, _ in headers if n.startswith("access-control-")])

    async def test_app_rejects_missing_or_duplicate_host_itself(self):
        app = OverlayApp(self.harness.overlay, self.port)
        good = (b"host", f"127.0.0.1:{self.port}".encode())
        for headers, expected in (([], 421), ([good, good], 421), ([good], 200)):
            sent = []

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message, sent=sent):
                sent.append(message)

            await app({"type": "http", "method": "GET", "path": "/state", "headers": headers},
                      receive, send)
            self.assertEqual(sent[0]["status"], expected)

    async def test_reads_and_rejected_methods_never_advance_the_game(self):
        async with connect(self.ws_url) as game:
            await game.send(request_frame(1))
            async with self.sse() as events:
                before = await events.until(lambda s: s["status"] == "awaiting_decision")
                rows = self.harness.ledger.next_index
                for path in PATHS:
                    for method in METHODS:
                        with self.subTest(path=path, method=method):
                            status, headers, _ = await raw_request(
                                self.port, method=method, path=path,
                                extra=("Content-Type: application/json", "Content-Length: 2"))
                            self.assertEqual(status, 405)
                            self.assertEqual(dict(headers)["allow"], "GET")
                    if path != "/events":
                        status, _, _ = await raw_request(self.port, path=path)
                        self.assertEqual(status, 200)
                await asyncio.sleep(0.2)
                after = await self.state()
            with self.assertRaises(TimeoutError):
                async with asyncio.timeout(0.3):
                    await game.recv()
        self.assertEqual(self.harness.ledger.next_index, rows)
        self.assertEqual(after, before)
        self.assertEqual(self.harness.broker.seq, 1)
        self.assertIsNone(self.harness.broker.fault)


class LifecycleTests(OverlayTestCase):
    async def test_client_disconnect_releases_the_stream(self):
        feed = self.harness.overlay
        async with self.sse() as events:
            await events.next()
            self.assertEqual(feed.clients, 1)
        async with asyncio.timeout(5):
            while feed.clients or feed._waiters:
                await asyncio.sleep(0.02)
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(f"GET /events HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n\r\n".encode())
        async with asyncio.timeout(5):
            while b"data: " not in await reader.read(4096):
                pass
        self.assertEqual(feed.clients, 1)
        writer.close()
        async with asyncio.timeout(5):
            while feed.clients or feed._waiters:
                await asyncio.sleep(0.02)

    async def test_graceful_shutdown_ends_open_streams_without_leaks(self):
        async with self.sse() as events:
            await events.next()
            # A stream still open at uvicorn's 2 s graceful timeout is force-cancelled:
            # that logs at ERROR and breaks the chunked body (RemoteProtocolError).
            with self.assertNoLogs("uvicorn.error", level="ERROR"):
                stopping = asyncio.create_task(self.harness.stop())
                seen = []
                with contextlib.suppress(StopAsyncIteration):
                    while True:
                        seen.append(await events.next(timeout=5))
                async with asyncio.timeout(10):
                    await stopping
        self.assertEqual(seen[-1]["status"], "shutdown")
        self.assertRegex(seen[-1]["head_hash"], HEX64)
        self.assertFalse((self.run_dir / "ready.json").exists())
        await asyncio.sleep(0)
        self.assertEqual(leftover_tasks(), set())
        with self.assertRaises(OSError):
            async with asyncio.timeout(5):
                await asyncio.open_connection("127.0.0.1", self.port)


class ObserverFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_projection_error_hides_data_without_faulting_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger.create(Path(tmp) / "ledger.jsonl")
            broker = Broker(ledger)
            feed = OverlayFeed(broker, ledger)
            with self.assertRaises(ValueError):
                OverlayFeed(broker, ledger)

            def boom(row):
                raise RuntimeError(SECRET_PATH)

            feed._project = boom
            conn = FakeConn()
            broker.attach(conn)
            broker.handle_frame(conn, request_frame(1))
            ledger.close()
        self.assertIsNone(broker.fault)
        self.assertEqual((broker.seq, ledger.next_index), (1, 1))
        snapshot = feed.snapshot()
        self.assertFalse(snapshot["projection_ok"])
        self.assertIsNone(snapshot["sitrep"])
        self.assertIsNone(snapshot["decision"])
        self.assertEqual(snapshot["head_hash"], ledger.head_hash)
        self.assertNotIn(SECRET_PATH, json.dumps(snapshot))


class StartupFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_overlay_bind_failure_cleans_up_everything(self):
        with tempfile.TemporaryDirectory() as tmp, socket.socket() as occupier:
            occupier.bind(("127.0.0.1", 0))
            occupier.listen()
            busy = occupier.getsockname()[1]
            run_dir = Path(tmp) / "run"
            harness = Harness(run_dir, ws_port=0, mcp_port=0, overlay_port=busy)
            with self.assertRaises(OSError):
                await harness.start()
            ports = (harness.ws_port, harness.mcp_port)
            async with asyncio.timeout(15):
                await harness.stop()
            self.assertFalse((run_dir / "ready.json").exists())
            self.assertIsNone(harness.overlay_url)
            for port in ports:
                with self.assertRaises(OSError):
                    async with asyncio.timeout(5):
                        await asyncio.open_connection("127.0.0.1", port)
            await asyncio.sleep(0)
            self.assertEqual(leftover_tasks(), set())


class CliTests(unittest.IsolatedAsyncioTestCase):
    async def test_overlay_port_flag_publishes_url_and_stops_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "harness", "--run-dir", str(run_dir), "--ws-port", "0",
                "--mcp-port", "0", "--overlay-port", "0", cwd=ROOT,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                async with asyncio.timeout(30):
                    line = await proc.stdout.readline()
                event = json.loads(line)
                ready = json.loads((run_dir / "ready.json").read_text())
                url = ready["overlay_url"]
                self.assertEqual(event["overlay_url"], url)
                port = int(re.fullmatch(r"http://127\.0\.0\.1:(\d+)/", url).group(1))
                self.assertNotIn(port, (0, event["ws_port"], event["mcp_port"]))
                status, _, body = await raw_request(port)
                self.assertEqual(status, 200)
                snapshot = json.loads(body)
                self.assertEqual((snapshot["status"], snapshot["head_hash"]), ("not_ready", GENESIS_HASH))
                self.assertNotIn((run_dir / "token").read_text(), body.decode())
                proc.send_signal(signal.SIGTERM)
                async with asyncio.timeout(20):
                    _, stderr = await proc.communicate()
                self.assertEqual(proc.returncode, 0, stderr.decode())
                self.assertFalse((run_dir / "ready.json").exists())
                with self.assertRaises(OSError):
                    async with asyncio.timeout(5):
                        await asyncio.open_connection("127.0.0.1", port)
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()


if __name__ == "__main__":
    unittest.main()
