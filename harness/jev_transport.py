"""Retry and diagnose read-only Jev evaluations without dispatching game actions."""
import asyncio
from datetime import timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import random
import time

import httpx2

from harness.play import private_write


class JevError(RuntimeError):
    def __init__(self, message, *, retryable):
        super().__init__(message)
        self.retryable = retryable


def retry_delay(headers, retry):
    for name, scale in (('retry-after-ms', .001), ('retry-after', 1)):
        value = headers.get(name)
        if value is None:
            continue
        try:
            seconds = float(value) * scale
        except ValueError:
            try:
                date = parsedate_to_datetime(value)
                seconds = date.replace(tzinfo=date.tzinfo or timezone.utc).timestamp() - time.time()
            except (ValueError, TypeError, OverflowError):
                continue
        if math.isfinite(seconds):
            return max(0, seconds)
    return .5 * 2**retry * random.uniform(.75, 1)


async def evaluate(client, request, api_key, path):
    payload = json.dumps(request, ensure_ascii=False, separators=(',', ':')).encode()
    record = {'started_unix_s': time.time(), 'request_bytes': len(payload),
              'request_sha256': hashlib.sha256(payload).hexdigest(), 'timeout_s': None,
              'attempts': [], 'status': 'failed'}
    started = time.monotonic()
    allowed_headers = {'server', 'date', 'content-type', 'retry-after', 'retry-after-ms',
                       'cf-ray', 'request-id', 'x-request-id', 'server-timing'}
    try:
        for retry in range(3):
            attempt_start = time.monotonic()
            attempt = {'number': retry + 1, 'trace': []}
            record['attempts'].append(attempt)
            headers = {}
            error = None

            async def trace(name, info, attempt=attempt, attempt_start=attempt_start):
                # Trace info can contain Authorization headers; only retain names and time.
                attempt['trace'].append({'event': name, 'elapsed_s': time.monotonic()-attempt_start})

            try:
                async with client.stream('POST', 'https://api.typesafe.ai/v1/systemone', content=payload,
                                         headers={'Authorization': 'Bearer '+api_key, 'Content-Type': 'application/json'},
                                         extensions={'trace': trace}) as response:
                    headers = response.headers
                    attempt.update(status=response.status_code, http_version=response.http_version,
                                   headers={k: v.replace(api_key, '[REDACTED]') for k, v in headers.items()
                                            if k in allowed_headers})
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 1_048_576:
                            raise JevError('Jev response too large', retryable=False)
                    attempt['response_bytes'] = len(content)
                    if response.status_code == 200:
                        try:
                            result = json.loads(content)
                        except ValueError:
                            result = None
                        if isinstance(result, dict) and isinstance(result.get('answers'), dict):
                            attempt['usage'] = result.get('usage')
                            attempt['model'] = result.get('model')
                            record['status'] = 'succeeded'
                            return result
                        error = JevError('Jev invalid JSON/response schema', retryable=False)
                    else:
                        error = JevError(f'Jev HTTP {response.status_code}',
                                         retryable=response.status_code in (408, 429) or 500 <= response.status_code < 600)
                    attempt['body_excerpt'] = content.decode('utf-8', errors='replace').replace(api_key, '[REDACTED]')[:2048]
            except httpx2.HTTPError as exc:
                error = JevError('Jev transport failure: '+type(exc).__name__, retryable=True)
                attempt['exception_type'] = type(exc).__name__
            except JevError as exc:
                error = exc
            finally:
                attempt['elapsed_s'] = time.monotonic()-attempt_start
            attempt.update(error=str(error), retryable=error.retryable)
            if not error.retryable or retry == 2:
                raise error
            delay = retry_delay(headers, retry)
            attempt['retry_delay_s'] = delay
            await asyncio.sleep(delay)
    except asyncio.CancelledError:
        record['status'] = 'cancelled'
        raise
    finally:
        record['elapsed_s'] = time.monotonic()-started
        private_write(path, record)
