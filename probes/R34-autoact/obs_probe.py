"""Small authenticated OBS v5 peer for the isolated Qud measurement scene."""

import base64
import asyncio
import hashlib
import json
from pathlib import Path

from websockets.asyncio.client import connect


class Obs:
    request_timeout = 5.0

    async def __aenter__(self):
        config = json.loads((Path.home() / "Library/Application Support/obs-studio/"
                             "plugin_config/obs-websocket/config.json").read_text())
        if not config["server_enabled"] or not config["auth_required"]:
            raise RuntimeError("Existing authenticated OBS endpoint required")
        self.socket = await connect(f"ws://127.0.0.1:{config['server_port']}",
                                    max_size=16 * 1024 * 1024, open_timeout=5, close_timeout=3)
        hello = json.loads(await asyncio.wait_for(self.socket.recv(), self.request_timeout))
        challenge = hello["d"]["authentication"]
        def digest(text):
            return base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()
        secret = digest(config["server_password"] + challenge["salt"])
        auth = digest(secret + challenge["challenge"])
        await asyncio.wait_for(self.socket.send(json.dumps({"op": 1, "d": {"rpcVersion": 1,
            "authentication": auth, "eventSubscriptions": 0}})), self.request_timeout)
        identified = json.loads(await asyncio.wait_for(self.socket.recv(), self.request_timeout))
        if identified["op"] != 2:
            raise RuntimeError("OBS authentication failed")
        self.sequence = 0
        return self

    async def __aexit__(self, *args):
        await self.socket.close()

    async def request(self, kind, **data):
        async with asyncio.timeout(self.request_timeout):
            return await self._request(kind, **data)

    async def _request(self, kind, **data):
        self.sequence += 1
        request_id = str(self.sequence)
        await self.socket.send(json.dumps({"op": 6, "d": {"requestType": kind,
            "requestId": request_id, "requestData": data}}))
        while True:
            message = json.loads(await self.socket.recv())
            if message["op"] != 7 or message["d"]["requestId"] != request_id:
                continue
            reply = message["d"]
            if not reply["requestStatus"]["result"]:
                raise RuntimeError(f"{kind}: {reply['requestStatus']}")
            return reply.get("responseData", {})
