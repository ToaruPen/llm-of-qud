import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import r6_operator as op

class OperatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.profile = Path(self.temp.name).resolve()
        self.config = {"v":1,"development":True,"disposable":True,"savepath":str(self.profile),"nonce":"a"*32}
        self.write_config()
    def write_config(self):
        (self.profile / "r6-dev-optin.json").write_text(json.dumps(self.config))
    def test_fixture_targets_real_control_and_redacts_nonce(self):
        receipt = op.fixture(self.profile, "save")
        value = json.loads((self.profile / "llm-control.json").read_text())
        self.assertEqual(value["command"], "probe_lifecycle")
        self.assertEqual(value["nonce"], "a"*32)
        self.assertNotIn("nonce", receipt)
        self.assertEqual(receipt["fixture_id"], value["fixture_id"])
    def test_never_overwrites_pending_control(self):
        op.fixture(self.profile, "save")
        before = (self.profile / "llm-control.json").read_bytes()
        with self.assertRaises(FileExistsError): op.fixture(self.profile, "death")
        self.assertEqual((self.profile / "llm-control.json").read_bytes(), before)
    def test_copied_optin_is_rejected(self):
        self.config["savepath"] += "-other"; self.write_config()
        with self.assertRaises(ValueError): op.fixture(self.profile, "save")
    def test_no_disposable_no_operation(self):
        self.config["disposable"] = False; self.write_config()
        with self.assertRaises(ValueError): op.fixture(self.profile, "death")
    def test_unknown_fixture_is_rejected(self):
        with self.assertRaises(ValueError): op.fixture(self.profile, "wish")
    def test_process_identity_requires_exact_argv(self):
        init = {"pid":123,"argv":["/game/CoQ", "-savepath", str(self.profile)]}
        with patch.object(op, "process_command", return_value="/other/CoQ -savepath " + str(self.profile)):
            with self.assertRaises(ValueError): op.verify_process(self.profile, init)
        with patch.object(op, "process_command", return_value=" ".join(init["argv"])):
            self.assertEqual(op.verify_process(self.profile, init), 123)
    def test_stale_heartbeat_is_rejected(self):
        with self.assertRaises(ValueError): op.check_heartbeat({"utc":"2000-01-01T00:00:00Z"})
