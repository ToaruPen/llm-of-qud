import asyncio
import time
import unittest

from obs_probe import Obs


class SilentPeer:
    async def send(self, data):
        pass

    async def recv(self):
        await asyncio.Future()


class ObsTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_unresponsive_peer_is_bounded_by_request_deadline(self):
        obs = Obs()
        obs.socket = SilentPeer()
        obs.sequence = 0
        obs.request_timeout = 0.01
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(obs.request("GetStats"), timeout=0.2)
        self.assertLess(time.monotonic() - start, 0.15)


if __name__ == "__main__":
    unittest.main()
