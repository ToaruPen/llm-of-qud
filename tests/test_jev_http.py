"""Exercise the real transport policy with simulated provider responses."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx2

from harness.hybrid_models import Models
from harness.jev_transport import retry_delay


REQUEST = {'model': 'jev-latest', 'state': {'hp': 12}, 'questions': {}}
ANSWER = {'model': 'jev-1.13.0', 'answers': {}, 'usage': {'input_tokens': 10, 'output_tokens': 1}}


class JevHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.clients = []
        self.requests = []
        self.responses = []
        real_client = httpx2.AsyncClient

        async def handler(request):
            self.requests.append(request)
            result = self.responses.pop(0)
            if isinstance(result, Exception):
                raise result
            if callable(result):
                return await result(request)
            return result

        def factory(**kwargs):
            client = real_client(transport=httpx2.MockTransport(handler), **kwargs)
            self.clients.append(client)
            return client

        self.factory = patch('harness.hybrid_models.httpx2.AsyncClient', factory)
        self.factory.start()
        self.addCleanup(self.factory.stop)
        self.models = Models(self.directory, 'secret-api-key', 'unused')

    async def asyncTearDown(self):
        for client in self.clients:
            await client.aclose()

    async def test_transient_failures_retry_identical_state_before_returning_success(self):
        self.responses = [httpx2.Response(503, json={'detail': 'busy'}, headers={'Retry-After': '0'}),
                          httpx2.Response(529, json={'detail': 'overloaded'}, headers={'Retry-After': '0'}),
                          httpx2.Response(200, json=ANSWER)]
        try:
            result = await self.models.jev(REQUEST)
        except RuntimeError as exc:
            result = str(exc)
        self.assertEqual(result, ANSWER)
        self.assertEqual([json.loads(r.content) for r in self.requests], [REQUEST]*3)
        self.assertEqual(self.models.jev_calls, 1)

    async def test_unbounded_requests_reuse_connection_pool_across_decisions(self):
        self.responses = [httpx2.Response(200, json=ANSWER), httpx2.Response(200, json=ANSWER)]
        await self.models.jev(REQUEST)
        await self.models.jev(REQUEST)
        self.assertEqual(len(self.clients), 1)
        self.assertEqual(self.requests[0].extensions['timeout'],
                         {'connect': None, 'read': None, 'write': None, 'pool': None})

    async def test_permanent_error_preserves_diagnostic_and_does_not_retry(self):
        self.responses = [httpx2.Response(400, json={'detail': {'error_type': 'max_tokens_exceeded'},
                                                    'echo': 'secret-api-key'},
                                          headers={'x-request-id': 'req-123', 'set-cookie': 'private'})]
        with self.assertRaises(RuntimeError) as caught:
            await self.models.jev(REQUEST)
        self.assertFalse(getattr(caught.exception, 'retryable', True))
        self.assertEqual(len(self.requests), 1)
        logs = list(self.directory.glob('jev-*.json'))
        self.assertEqual(len(logs), 1)
        raw = logs[0].read_text()
        self.assertNotIn('secret-api-key', raw)
        self.assertNotIn('set-cookie', raw)
        record = json.loads(raw)
        self.assertEqual(record['attempts'][0]['headers']['x-request-id'], 'req-123')
        self.assertIn('max_tokens_exceeded', record['attempts'][0]['body_excerpt'])

    async def test_retry_exhaustion_is_bounded_and_classified(self):
        self.responses = [httpx2.Response(503, json={'detail': 'busy'}, headers={'Retry-After': '0'}) for _ in range(3)]
        with self.assertRaises(RuntimeError) as caught:
            await self.models.jev(REQUEST)
        self.assertEqual(len(self.requests), 3)
        self.assertTrue(getattr(caught.exception, 'retryable', False))

    async def test_retry_after_is_respected_and_cancellation_leaves_evidence(self):
        self.responses = [httpx2.Response(429, json={'detail': 'limited'}, headers={'Retry-After': '3600'})]
        task = asyncio.create_task(self.models.jev(REQUEST))
        await asyncio.sleep(.02)
        self.assertFalse(task.done(), 'Retry-After must wait without delegating or retrying immediately')
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(self.requests), 1)
        logs = list(self.directory.glob('jev-*.json'))
        self.assertEqual(len(logs), 1)
        self.assertEqual(json.loads(logs[0].read_text())['status'], 'cancelled')

    async def test_invalid_json_is_recorded_as_protocol_failure(self):
        self.responses = [httpx2.Response(200, text='<html>gateway response</html>')]
        with self.assertRaises(RuntimeError) as caught:
            await self.models.jev(REQUEST)
        self.assertFalse(getattr(caught.exception, 'retryable', True))
        logs = list(self.directory.glob('jev-*.json'))
        self.assertEqual(len(logs), 1)
        self.assertIn('gateway response', logs[0].read_text())

    async def test_connection_failure_retries_but_permanent_statuses_do_not(self):
        self.responses = [httpx2.ConnectError('connection unavailable'), httpx2.Response(200, json=ANSWER)]
        self.assertEqual(await self.models.jev(REQUEST), ANSWER)
        for status in (401, 403, 422):
            self.responses = [httpx2.Response(status, json={'detail': 'invalid request'})]
            count = len(self.requests)
            with self.assertRaises(RuntimeError) as caught:
                await self.models.jev(REQUEST)
            self.assertFalse(caught.exception.retryable)
            self.assertEqual(len(self.requests), count+1)

    async def test_client_shutdown_releases_owned_connection_pool(self):
        self.responses = [httpx2.Response(200, json=ANSWER)]
        await self.models.jev(REQUEST)
        await self.models.aclose()
        self.assertTrue(self.clients[0].is_closed)

    async def test_response_wait_can_be_cancelled_without_starting_another_attempt(self):
        receiving = asyncio.Event()
        async def delayed(request):
            receiving.set()
            await asyncio.Event().wait()
        self.responses = [delayed]
        task = asyncio.create_task(self.models.jev(REQUEST))
        await receiving.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        record = json.loads(next(self.directory.glob('jev-*.json')).read_text())
        self.assertEqual(record['status'], 'cancelled')
        self.assertEqual(len(record['attempts']), 1)
        self.assertIn('elapsed_s', record['attempts'][0])

    def test_provider_retry_after_formats_and_nonfinite_values(self):
        self.assertEqual(retry_delay({'retry-after-ms': '250'}, 0), .25)
        with patch('harness.jev_transport.time.time', return_value=95):
            self.assertEqual(retry_delay({'retry-after': 'Thu, 01 Jan 1970 00:01:40 GMT'}, 0), 5)
        for value in ('nan', 'inf', 'invalid'):
            delay = retry_delay({'retry-after': value}, 0)
            self.assertGreater(delay, 0)
            self.assertLessEqual(delay, 1)


if __name__ == '__main__':
    unittest.main()
