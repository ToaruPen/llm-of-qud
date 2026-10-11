"""Loopback WebSocket listener for the game bridge (the game is the client).

Only 127.0.0.1 is bound and handshakes carrying any Origin header are rejected, which
keeps browsers out. The socket is not authenticated: any process running as the same
user can connect. The broker admits one active connection and one run per process.
"""

import logging

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from harness import wire
from harness.broker import ProtocolViolation, Refused

log = logging.getLogger("harness.ws_game")

CLOSE_POLICY_VIOLATION = 1008


def _close_reason(exc):
    return str(exc).encode("utf-8")[:120].decode("utf-8", "ignore")


class GameListener:
    def __init__(self, broker, host="127.0.0.1", port=4040):
        self.broker = broker
        self.host = host
        self.port = port
        self._server = None

    @property
    def sockets(self):
        return list(self._server.sockets) if self._server else []

    async def start(self):
        self._server = await serve(
            self._handle, self.host, self.port,
            origins=[None],
            max_size=wire.MAX_FRAME_BYTES,
            ping_interval=None,
            compression=None,
        )
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self):
        server, self._server = self._server, None
        if server is not None:
            server.close(close_connections=True)
            await server.wait_closed()

    async def _handle(self, ws):
        try:
            self.broker.attach(ws)
        except Refused as exc:
            log.warning("game connection refused: %s", exc)
            await ws.close(CLOSE_POLICY_VIOLATION, _close_reason(exc))
            return
        try:
            async for frame in ws:
                try:
                    reply = self.broker.handle_frame(ws, frame)
                except (Refused, ProtocolViolation) as exc:
                    log.warning("closing game connection: %s", exc)
                    await ws.close(CLOSE_POLICY_VIOLATION, _close_reason(exc))
                    return
                if reply is not None:
                    await ws.send(reply)
        except ConnectionClosed as exc:
            if exc.rcvd is None and exc.sent is not None and exc.sent.code != 1000:
                log.warning("game connection closed by harness: code %s", exc.sent.code)
        finally:
            self.broker.detach(ws)
