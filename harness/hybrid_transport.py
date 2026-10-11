"""Cancellable CLI streaming with metadata-only diagnostics; never persist raw events."""

import asyncio
import json
import os
import signal
import time


def cli_environment():
    return os.environ | {"CLAUDE_CODE_MAX_RETRIES": "1",
                         "CLAUDE_CODE_RETRY_WATCHDOG": "0", "MAX_STRUCTURED_OUTPUT_RETRIES": "2"}


async def run_cli(command, payload, record, *, wall_seconds=None, idle_seconds=None):
    started = time.monotonic()
    record.update(started_unix_s=time.time(), wall_limit_s=wall_seconds, idle_limit_s=idle_seconds,
                  api_timeout_ms=cli_environment().get('API_TIMEOUT_MS'), max_api_retries=1, max_structured_output_retries=2,
                  stdout_bytes=0, stderr_bytes=0,
                  events={}, first_event_s=None, last_event_s=None, phase="launch")
    proc = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=cli_environment(), start_new_session=True)
    record["pid"] = proc.pid
    last_activity = time.monotonic()
    final = None

    def event(line):
        nonlocal final, last_activity
        try:
            value = json.loads(line)
        except (ValueError, UnicodeError):
            raise RuntimeError("Claude emitted invalid stream JSON") from None
        if not isinstance(value, dict):
            raise RuntimeError("Claude emitted a non-object event")
        last_activity = time.monotonic()
        elapsed = last_activity - started
        if record["first_event_s"] is None:
            record["first_event_s"] = elapsed
        record["last_event_s"] = elapsed
        kind = value.get("type")
        kind = kind if kind in ("system", "assistant", "user", "result", "stream_event") else "other"
        if kind == "stream_event":
            subtype = value.get("event", {}).get("type")
            if subtype in ("message_start", "message_delta", "message_stop", "content_block_start",
                           "content_block_delta", "content_block_stop", "ping", "error"):
                kind += "." + subtype
            source = value.get("event", {})
            usage = source.get("message", {}).get("usage", source.get("usage", {}))
            partial = {k: usage[k] for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                       "cache_creation_input_tokens") if type(usage.get(k)) is int}
            if partial:
                record.setdefault("partial_usage", []).append({"elapsed_s": elapsed, **partial})
        record["events"][kind] = record["events"].get(kind, 0) + 1
        record["phase"] = kind
        if kind == "user":
            blocks = value.get("message", {}).get("content", [])
            if isinstance(blocks, list):
                errors = sum(isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error") is True
                             for b in blocks)
                if errors:
                    record["tool_result_errors"] = record.get("tool_result_errors", 0) + errors
        if value.get("type") == "system" and value.get("subtype") == "api_retry":
            record["api_retry_events"] = record.get("api_retry_events", 0) + 1
            for key in ("attempt", "max_retries", "retry_delay_ms", "error_status"):
                if type(value.get(key)) is int:
                    record["retry_" + key] = value[key]
        if kind == "result":
            if final is not None:
                raise RuntimeError("Claude emitted multiple final results")
            final = value
            usage = value.get("usage") or {}
            record["final_usage"] = {k: usage[k] for k in ("input_tokens", "output_tokens",
                "cache_read_input_tokens", "cache_creation_input_tokens") if type(usage.get(k)) is int}
            # Only allow protocol labels, never arbitrary error text or raw thinking.
            subtype = value.get("subtype")
            record["result_subtype"] = subtype if subtype in (
                "success", "error_during_execution", "error_max_turns",
                "error_max_structured_output_retries", "error_max_budget_usd") else "other"

    async def consume(stream, name):
        buffer = bytearray()
        while chunk := await stream.read(65536):
            record[name + "_bytes"] += len(chunk)
            if record[name + "_bytes"] > 4_194_304:
                raise RuntimeError("Claude output limit")
            if name == "stdout":
                buffer.extend(chunk)
                while b"\n" in buffer:
                    line, _, buffer = buffer.partition(b"\n")
                    if line.strip():
                        event(line)
        if buffer.strip():
            event(buffer)
        record[name + "_eof_s"] = time.monotonic() - started

    async def exchange():
        record["phase"] = "stdin"
        proc.stdin.write(payload.encode())
        await proc.stdin.drain()
        proc.stdin.close()
        record["input_sent_s"] = time.monotonic() - started
        await proc.wait()

    tasks = [asyncio.create_task(consume(proc.stdout, "stdout")),
             asyncio.create_task(consume(proc.stderr, "stderr")), asyncio.create_task(exchange())]
    try:
        pending = set(tasks)
        while pending:
            now = time.monotonic()
            wall_left = float('inf') if wall_seconds is None else started + wall_seconds - now
            idle_left = float('inf') if idle_seconds is None else last_activity + idle_seconds - now
            if min(wall_left, idle_left) <= 0:
                record["timeout_kind"] = "wall" if wall_left <= idle_left else "idle"
                raise TimeoutError("Claude " + record["timeout_kind"] + " deadline")
            done, pending = await asyncio.wait(pending, timeout=min(wall_left, idle_left, .5),
                                               return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        if proc.returncode:
            raise RuntimeError(f"Claude process exited {proc.returncode}")
        if final is None:
            raise RuntimeError("Claude stream ended without a final result")
        return final
    except asyncio.CancelledError:
        record["cancelled"] = True
        raise
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except TimeoutError:
            os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
        record.update(exit_code=proc.returncode, elapsed_s=time.monotonic() - started)
