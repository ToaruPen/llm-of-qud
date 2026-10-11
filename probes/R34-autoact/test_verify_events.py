import unittest

from verify_events import Refused, verify_hover, verify_picker_retry


def hover_rows():
    expected = "LookedAt42"
    return [
        {"kind": "begin", "mode": "hover", "focus": "unfocused"},
        {"kind": "hover_status_open", "pending": True},
        {"kind": "hover_target", "name": "vinewafer", "objectHash": 42,
         "expectedTaskId": expected, "clientX": 0.4, "clientYTop": 0.6,
         "screenWidth": 2560, "screenHeight": 1345, "unityX": 1024, "unityY": 538},
        {"kind": "hover_before_exit", "tooltipShown": True, "pointerInside": True,
         "actualFocused": False, "expectedTaskId": expected, "queueTaskIds": ["Other"]},
        {"kind": "hover_pointer_exit_event", "actualFocused": False},
        {"kind": "hover_after_exit", "pointerExitEvent": True, "pointerInside": False,
         "actualFocused": False,
         "expectedTaskId": expected, "queueTaskIds": ["Other", expected], "taskNewlyQueued": True},
        {"kind": "hover_evidence", "tooltipShown": True, "pointerExitObserved": True,
         "taskNewlyQueued": True, "queueBefore": ["Other"],
         "queueAfter": ["Other", expected], "pass": True},
        {"kind": "result", "mode": "hover", "reason": "COMPLETE", "pass": True,
         "playerTurnEntries": 0, "endPlayerTurns": 0},
    ]


class HoverTests(unittest.TestCase):
    def test_valid_actual_exit_and_new_queue_task(self):
        self.assertTrue(verify_hover(hover_rows(), "unfocused")["ok"])

    def test_preexisting_task_is_not_fresh_evidence(self):
        rows = hover_rows()
        rows[3]["queueTaskIds"].append("LookedAt42")
        with self.assertRaises(Refused):
            verify_hover(rows, "unfocused")

    def test_missing_actual_pointer_exit_is_rejected(self):
        rows = [row for row in hover_rows() if row["kind"] != "hover_pointer_exit_event"]
        with self.assertRaises(Refused):
            verify_hover(rows, "unfocused")

    def test_early_diagnostic_exit_does_not_replace_post_tooltip_exit(self):
        rows = hover_rows()
        rows.insert(3, {"kind": "hover_pointer_exit_diagnostic",
                        "reason": "before_tooltip", "actualFocused": False})
        self.assertTrue(verify_hover(rows, "unfocused")["ok"])
        rows = [row for row in rows if row["kind"] != "hover_pointer_exit_event"]
        with self.assertRaises(Refused):
            verify_hover(rows, "unfocused")

    def test_focus_drift_at_exit_is_rejected(self):
        rows = hover_rows()
        rows[4]["actualFocused"] = True
        with self.assertRaises(Refused):
            verify_hover(rows, "unfocused")


def picker_rows():
    rows = [{"kind": "begin", "mode": "picker", "dropFirstPickerPush": True}]
    for seq in range(1, 11):
        rows.extend([
            {"kind": "picker_drop_simulated", "seq": seq, "attempt": 1, "beforeEnqueue": True},
            {"kind": "picker_push", "seq": seq, "attempt": 2, "key": "Keypad6",
             "simulatedLoss": True},
            {"kind": "picker_result", "seq": seq, "expected": "E", "actual": "E",
             "attempts": 2, "pushes": 1, "simulatedDrops": 1,
             "focusChanges": 2, "simulatedLoss": True, "pass": True},
        ])
    rows.append({"kind": "result", "mode": "picker", "reason": "COMPLETE", "pass": True,
                 "playerTurnEntries": 0, "endPlayerTurns": 0})
    return rows


class PickerTests(unittest.TestCase):
    def test_ten_simulated_losses_then_real_retries(self):
        self.assertEqual(verify_picker_retry(picker_rows())["correct_pickers"], 10)

    def test_missing_real_retry_is_rejected(self):
        rows = [row for row in picker_rows() if not (row["kind"] == "picker_push" and row["seq"] == 4)]
        with self.assertRaises(Refused):
            verify_picker_retry(rows)

    def test_normal_picker_cannot_masquerade_as_retry(self):
        rows = picker_rows()
        rows[0]["dropFirstPickerPush"] = False
        with self.assertRaises(Refused):
            verify_picker_retry(rows)

    def test_unpaired_extra_drop_is_rejected(self):
        rows = picker_rows()
        rows.insert(-1, {"kind": "picker_drop_simulated", "seq": 11,
                         "attempt": 1, "beforeEnqueue": True})
        with self.assertRaises(Refused):
            verify_picker_retry(rows)


if __name__ == "__main__":
    unittest.main()
