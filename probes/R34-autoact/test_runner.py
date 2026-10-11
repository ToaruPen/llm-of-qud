import tempfile
import unittest
import json
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from run_probe import LogTail, run


class LogTailTests(unittest.TestCase):
    def test_partial_append_is_delivered_once_when_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            path.write_text("old log\n")
            tail = LogTail(path)
            with path.open("a") as stream:
                stream.write('INFO [R34] {"kind":"begin"')
            self.assertEqual([], tail.poll())
            with path.open("a") as stream:
                stream.write('}\nINFO [R34] {"kind":"result"}\n')
            self.assertEqual([{"kind": "begin"}, {"kind": "result"}], tail.poll())
            self.assertEqual([], tail.poll())

    def test_replaced_or_truncated_log_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            path.write_text("original log\n")
            tail = LogTail(path)
            path.write_text("")
            with self.assertRaises(RuntimeError):
                tail.poll()


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_receipt_survives_recording_stop_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "results").mkdir()
            log = root / "Player.log"
            log.write_text("")
            args = SimpleNamespace(id="trial", profile=root, log=log, mode="r3", seconds=60,
                                   focus="focused", background_app="Finder", drop_first_picker_push=False)

            class FakeObs:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    pass

                async def request(self, kind, **data):
                    if kind == "GetRecordStatus":
                        return {"outputActive": False}
                    if kind == "GetInputPropertiesListPropertyItems":
                        return {"propertyItems": [{"itemName": "[CavesOfQud] CavesOfQud", "itemValue": 1}]}
                    if kind == "GetStats":
                        with log.open("a") as stream:
                            stream.write('[R34] {"id":"trial","kind":"begin"}\n')
                            stream.write('[R34] {"id":"trial","kind":"result","reason":"COMPLETE"}\n')
                    if kind == "StopRecord":
                        raise TimeoutError("no reply")
                    return {}

            async def no_wait(_):
                pass

            with patch("run_probe.__file__", str(root / "run_probe.py")), \
                    patch("run_probe.Obs", FakeObs), patch("run_probe.activate"), \
                    patch("run_probe.asyncio.sleep", no_wait):
                with self.assertRaisesRegex(RuntimeError, "stop is unconfirmed"):
                    await run(args)
            receipt = json.loads((root / "results/trial/receipt.json").read_text())
            self.assertEqual("COMPLETE", receipt["result"]["reason"])
            self.assertIn("TimeoutError", receipt["recordingStopError"])

    async def test_covered_trial_activates_selected_background_app_and_records_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "results").mkdir()
            log = root / "Player.log"
            log.write_text("")
            args = SimpleNamespace(id="covered", profile=root, log=log, mode="r3", seconds=60,
                                   focus="unfocused", background_app="OBS", drop_first_picker_push=False)

            class FakeObs:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    pass

                async def request(self, kind, **data):
                    if kind == "GetRecordStatus":
                        return {"outputActive": False}
                    if kind == "GetInputPropertiesListPropertyItems":
                        return {"propertyItems": [{"itemName": "[CavesOfQud] CavesOfQud", "itemValue": 1}]}
                    if kind == "GetStats":
                        with log.open("a") as stream:
                            stream.write('[R34] {"id":"covered","kind":"begin"}\n')
                            stream.write('[R34] {"id":"covered","kind":"result","reason":"COMPLETE"}\n')
                    return {}

            async def no_wait(_):
                pass

            with patch("run_probe.__file__", str(root / "run_probe.py")), \
                    patch("run_probe.Obs", FakeObs), patch("run_probe.activate") as activation, \
                    patch("run_probe.asyncio.sleep", no_wait):
                await run(args)
            self.assertEqual("OBS", activation.call_args_list[-1].args[0])
            receipt = json.loads((root / "results/covered/receipt.json").read_text())
            self.assertEqual("OBS", receipt["backgroundApp"])
            events = [json.loads(line) for line in (root / "results/covered/runner.jsonl").read_text().splitlines()]
            self.assertEqual(["OBS"], [e["app"] for e in events if e["kind"] == "focus" and e["app"] == "OBS"])


if __name__ == "__main__":
    unittest.main()
