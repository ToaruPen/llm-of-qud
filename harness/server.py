"""Harness process: fresh run directory, ledger, game WebSocket, authenticated MCP.

    python -m harness --run-dir .runtime/RUN [--ws-port 4040] [--mcp-port 8790]
                      [--overlay-port 8080]

The run directory must be new (or an empty directory). It receives ``token`` (0600,
never printed or logged), ``ledger.jsonl`` (0600) and, once both listeners and the MCP
lifespan are up, ``ready.json`` (0600, ports and paths only). Nothing is recovered from
an earlier process: a restarted harness needs a freshly armed game run.

``--overlay-port`` (off by default; 8080 is the documented choice, 0 picks a free port)
also serves the read-only OBS overlay on 127.0.0.1; ``ready.json`` then has overlay_url.
"""

import argparse
import asyncio
import json
import logging
import os
import secrets
import signal
import sys
from pathlib import Path

from harness.broker import Broker
from harness.episode import EpisodeGate
from harness.ledger import Ledger
from harness.memory import MemoryStore
from harness.mcp_app import MCP_PATH, McpHttpServer, build_http_app
from harness.overlay import OverlayFeed, build_overlay_app
from harness.ws_game import GameListener

log = logging.getLogger("harness")

HOST = "127.0.0.1"


class RunDirError(Exception):
    pass


def _prepare_run_dir(run_dir):
    if run_dir.exists():
        if not run_dir.is_dir() or any(run_dir.iterdir()):
            raise RunDirError(f"run dir {run_dir} must be new or empty")
        os.chmod(run_dir, 0o700)
    else:
        run_dir.mkdir(parents=True, mode=0o700)


def _write_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


class Harness:
    def __init__(self, run_dir, *, ws_port=4040, mcp_port=8790, overlay_port=None,
                 act_wait_s=2.0, memory_dir=None, episode_control=False):
        self.run_dir = Path(run_dir)
        self.requested_ws_port = ws_port
        self.requested_mcp_port = mcp_port
        self.requested_overlay_port = overlay_port
        self.act_wait_s = act_wait_s
        self.memory_dir = memory_dir
        self.episode_gate = EpisodeGate(self.run_dir / "episode.json") if episode_control else None
        self.memory = None
        self.ledger = None
        self.broker = None
        self.game = None
        self.http = None
        self.overlay = None
        self.overlay_http = None
        self.ready_path = self.run_dir / "ready.json"
        self._ready_written = False

    @property
    def ws_port(self):
        return self.game.port

    @property
    def mcp_port(self):
        return self.http.port

    @property
    def overlay_url(self):
        """None unless the overlay is enabled and listening."""
        if self.overlay_http is None or not self.overlay_http.sockets:
            return None
        return f"http://{HOST}:{self.overlay_http.port}/"

    @property
    def http_sockets(self):
        return self.http.sockets if self.http else []

    async def start(self):
        _prepare_run_dir(self.run_dir)
        token = secrets.token_urlsafe(32)
        _write_private(self.run_dir / "token", token)
        self.ledger = Ledger.create(self.run_dir / "ledger.jsonl")
        self.broker = Broker(self.ledger, act_wait_s=self.act_wait_s, episode_gate=self.episode_gate)
        if self.memory_dir is not None:
            self.memory = MemoryStore(self.memory_dir, self.broker)
        if self.requested_overlay_port is not None:
            self.overlay = OverlayFeed(self.broker, self.ledger)
        self.game = GameListener(self.broker, HOST, self.requested_ws_port)
        await self.game.start()
        self.http = McpHttpServer(lambda port: build_http_app(self.broker, token, port, self.memory),
                                  HOST, self.requested_mcp_port)
        await self.http.start()
        if self.overlay is not None:
            self.overlay_http = McpHttpServer(lambda port: build_overlay_app(self.overlay, port),
                                              HOST, self.requested_overlay_port)
            await self.overlay_http.start()
        ready = {
            "pid": os.getpid(),
            "ws_url": f"ws://{HOST}:{self.ws_port}",
            "mcp_url": f"http://{HOST}:{self.mcp_port}{MCP_PATH}",
            "token_file": str(self.run_dir / "token"),
            "ledger": str(self.run_dir / "ledger.jsonl"),
        }
        if self.overlay_url is not None:
            ready["overlay_url"] = self.overlay_url
        if self.episode_gate is not None:
            ready["episode_control_file"] = str(self.episode_gate.path.resolve())
        _write_private(self.ready_path, json.dumps(ready) + "\n")
        self._ready_written = True

    async def stop(self):
        """Idempotent; also cleans up after a partial start."""
        if self._ready_written:
            self.ready_path.unlink(missing_ok=True)
            self._ready_written = False
        if self.broker is not None:
            self.broker.shutdown()
        if self.overlay is not None:
            self.overlay.close()  # ends event streams so the listener stops promptly
        if self.overlay_http is not None:
            await self.overlay_http.stop()
        if self.http is not None:
            await self.http.stop()
        if self.game is not None:
            await self.game.stop()
        if self.broker is not None:
            await self.broker.drain()
        if self.ledger is not None:
            self.ledger.close()
        if self.memory is not None:
            try:
                self.memory.sync()
            finally:
                self.memory.close()
                self.memory = None


def _port(text):
    value = int(text)
    if not 0 <= value <= 65535:
        raise argparse.ArgumentTypeError("port must be within 0..65535")
    return value


async def _serve(args):
    harness = Harness(args.run_dir, ws_port=args.ws_port, mcp_port=args.mcp_port,
                      overlay_port=args.overlay_port, memory_dir=args.memory_dir,
                      episode_control=args.episode_control)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await harness.start()
        event = {"event": "ready", "ws_port": harness.ws_port, "mcp_port": harness.mcp_port,
                 "ready_file": str(harness.ready_path)}
        if harness.overlay_url is not None:
            event["overlay_url"] = harness.overlay_url
        print(json.dumps(event), flush=True)
        await stop.wait()
    finally:
        await harness.stop()
    print(json.dumps({"event": "stopped"}), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m harness", description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--ws-port", type=_port, default=4040)
    parser.add_argument("--mcp-port", type=_port, default=8790)
    parser.add_argument("--memory-dir", type=Path,
                        help="persistent memory for this character/campaign; reuse on restart")
    parser.add_argument("--episode-control", action="store_true",
                        help="require supervisor-issued ten-decision windows for act (harness.play)")
    parser.add_argument("--overlay-port", type=_port, default=None,
                        help="serve the read-only OBS overlay (documented: 8080); off by default")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(_serve(args))
    except (RunDirError, OSError) as exc:
        print(f"harness: {exc}", file=sys.stderr)
        return 1
    return 0
