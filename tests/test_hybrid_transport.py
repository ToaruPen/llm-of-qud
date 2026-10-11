import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest

from harness.hybrid import play
from tests.test_hybrid import state


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def run_cli(self, code, **limits):
        from harness.hybrid_transport import run_cli
        record = {}
        try:
            value = await run_cli([sys.executable, "-c", code], "input", record,
                                  wall_seconds=limits.get("wall", 3), idle_seconds=limits.get("idle", 2))
            return value, record
        except BaseException:
            self.failed_record = record
            raise

    async def test_stream_metadata_does_not_retain_private_content(self):
        events = [{"type": "system", "subtype": "init"},
                  {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True,
                    "content": "PRIVATE_SCHEMA_DETAILS"}]}},
                  {"type": "stream_event", "event": {"type": "message_start", "message": {
                      "usage": {"input_tokens": 10, "cache_read_input_tokens": 800, "unsafe": "SECRET"}}}},
                  {"type": "stream_event", "event": {"type": "content_block_delta",
                    "delta": {"type": "thinking_delta", "thinking": "PRIVATE_CONTENT"}}},
                  {"type": "result", "subtype": "success", "structured_output": {"ok": True},
                   "usage": {"input_tokens": 10, "output_tokens": 20, "unsafe": "SECRET"}}]
        value, record = await self.run_cli("import json,sys\n"
            "print('PRIVATE_STDERR',file=sys.stderr)\n"
            f"for e in {events!r}: print(json.dumps(e),flush=True)\n")
        self.assertEqual(value["structured_output"], {"ok": True})
        self.assertEqual(record["exit_code"], 0)
        self.assertEqual(record["events"]["stream_event.content_block_delta"], 1)
        self.assertGreater(record["stderr_bytes"], 0)
        self.assertNotIn("PRIVATE", json.dumps(record))
        self.assertIsNotNone(record["first_event_s"])
        self.assertEqual(record["partial_usage"][0]["cache_read_input_tokens"], 800)
        self.assertNotIn("SECRET", json.dumps(record))
        self.assertEqual(record.get("tool_result_errors"), 1)
        self.assertEqual(record.get("final_usage"), {"input_tokens": 10, "output_tokens": 20})

    async def test_idle_and_wall_deadlines_are_distinct_and_reap_process(self):
        for code, limits, kind in [
            ("import time;time.sleep(10)", {"idle": .08}, "idle"),
            ("import time,json\nwhile True:\n print(json.dumps({'type':'system'}),flush=True)\n time.sleep(.02)",
             {"wall": .15}, "wall")]:
            with self.subTest(kind=kind), self.assertRaises(TimeoutError):
                await self.run_cli(code, **limits)
            record = self.failed_record
            self.assertEqual(record["timeout_kind"], kind)
            self.assertIsNotNone(record["exit_code"])

    async def test_incomplete_or_invalid_stream_is_never_a_plan(self):
        for code in ["print('not json')", "print('{}')", "print('{',end='')",
                     "import json;print(json.dumps({'type':'result'}));raise SystemExit(2)"]:
            with self.subTest(code=code), self.assertRaises(RuntimeError):
                await self.run_cli(code)

    async def test_unbounded_inference_wait_accepts_silent_processing(self):
        value, record = await self.run_cli(
            "import time,json;time.sleep(.1);print(json.dumps({'type':'result','subtype':'success'}))",
            wall=None, idle=None)
        self.assertEqual(value['subtype'], 'success')
        self.assertIsNone(record['wall_limit_s'])
        self.assertNotIn('timeout_kind', record)

    async def test_default_inference_limits_are_unset_and_cancellation_reaps(self):
        from harness.hybrid_transport import run_cli
        record = {}
        task = asyncio.create_task(run_cli([sys.executable, '-c', 'import time;time.sleep(10)'], '', record))
        while 'pid' not in record:
            await asyncio.sleep(.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNone(record['wall_limit_s'])
        self.assertIsNone(record['idle_limit_s'])
        self.assertIsNotNone(record['exit_code'])
        self.assertTrue(record['cancelled'])

    async def test_retry_environment_is_bounded_and_does_not_mutate_parent(self):
        import os
        from unittest.mock import patch
        from harness.hybrid_transport import cli_environment
        with patch.dict(os.environ, {"CLAUDE_CODE_RETRY_WATCHDOG": "1"}):
            env = cli_environment()
            self.assertEqual(env["CLAUDE_CODE_RETRY_WATCHDOG"], "0")
            self.assertEqual(env["CLAUDE_CODE_MAX_RETRIES"], "1")
            self.assertEqual(env.get("API_TIMEOUT_MS"), os.environ.get("API_TIMEOUT_MS"))
            self.assertEqual(env["MAX_STRUCTURED_OUTPUT_RETRIES"], "2")
            self.assertEqual(os.environ["CLAUDE_CODE_RETRY_WATCHDOG"], "1")

    async def test_duration_budget_cancels_planning_before_any_action(self):
        class SlowModels:
            jev_calls = 0
            claude_calls = 0

            async def claude(self, request):
                self.claude_calls += 1
                await asyncio.sleep(.2)
                return {"goal": "Test", "guidance": "Proceed", "horizon": 2, "target": None,
                        "selection": request["candidates"][0]["id"], "stop": False}

            async def jev(self, request):
                raise AssertionError("Initial plan goes to Claude")

        async def call(name, **args):
            self.assertEqual(name, "get_state", "An expired plan must not dispatch an action")
            return state()

        with tempfile.TemporaryDirectory() as directory:
            report = await play(call, SlowModels(), Path(directory), duration=.03)
        self.assertEqual(report["stop_reason"], "duration_limit")
        self.assertEqual(report["accepted_actions"], 0)


if __name__ == "__main__":
    unittest.main()
