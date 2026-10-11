"""Synthetic barcode and recorded-frame tests for the OBS R34 verifier."""

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("verify_capture.py")


def load_module():
    spec = importlib.util.spec_from_file_location("verify_capture", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(code=None, *, broken_bit=None, broken_anchor=False):
    pixels = bytearray((22, 22, 22) * 108)
    if code is None:
        return bytes(pixels)

    def paint(x, rgb):
        pixels[x * 3:x * 3 + 3] = bytes(rgb)

    paint(3, (253, 1, 252))
    paint(9, (20, 20, 20) if broken_anchor else (255, 0, 255))
    for bit in range(16):
        color = ((254, 254, 254) if code & (1 << bit) else (1, 1, 2))
        if bit == broken_bit:
            color = (128, 128, 128)
        paint(15 + 6 * bit, color)
    return bytes(pixels)


class CaptureVerifierTests(unittest.TestCase):
    def test_decodes_low_16_bits_and_anchor_presence(self):
        verifier = load_module()
        self.assertEqual(verifier.decode_row(row(0xA53C)), ("valid", 0xA53C))
        self.assertEqual(verifier.decode_row(row()), ("absent", None))
        self.assertEqual(verifier.decode_row(row(7, broken_bit=3))[0], "invalid")
        self.assertEqual(verifier.decode_row(row(7, broken_anchor=True))[0], "invalid")

    def test_repeated_codes_are_not_fresh_source_frames(self):
        verifier = load_module()
        rows = [row(), row(1), row(1), row(2), row(2), row(3), row()]
        metrics = verifier.analyze_rows(rows, fps=2)
        self.assertTrue(metrics["ok"])
        self.assertEqual(metrics["active_frames"], 5)
        self.assertEqual(metrics["fresh_transitions"], 2)
        self.assertEqual(metrics["repeat_frames"], 2)
        self.assertEqual(metrics["output_fps"], 2)
        self.assertAlmostEqual(metrics["fresh_source_fps"], 0.8)
        self.assertAlmostEqual(metrics["worst_freeze_seconds"], 0.5)

    def test_internal_missing_marker_is_reported_and_rejected(self):
        verifier = load_module()
        rows = [row(), row(1), row(2), row(), row(3), row()]
        metrics = verifier.analyze_rows(rows, fps=2)
        self.assertFalse(metrics["ok"])
        self.assertEqual(metrics["internal_gaps"], [
            {"start_frame": 3, "end_frame": 3, "frames": 1,
             "seconds": 0.5, "reason": "absent"}])

    def test_invalid_present_bar_is_never_silently_accepted(self):
        verifier = load_module()
        rows = [row(1), row(2, broken_bit=0), row(3)]
        metrics = verifier.analyze_rows(rows, fps=2)
        self.assertFalse(metrics["ok"])
        self.assertEqual(metrics["invalid_marker_frames"], 1)
        self.assertEqual(metrics["internal_gaps"][0]["reason"], "invalid")

    def test_per_ten_second_windows_measure_fresh_rate(self):
        verifier = load_module()
        rows = [row(i // 2) for i in range(25)]
        metrics = verifier.analyze_rows(rows, fps=2)
        self.assertEqual(len(metrics["per_10_seconds"]), 2)
        self.assertEqual(metrics["per_10_seconds"][0]["output_frames"], 20)
        self.assertAlmostEqual(metrics["per_10_seconds"][0]["fresh_source_fps"], 0.9)
        self.assertEqual(metrics["per_minute"][0]["output_frames"], 25)

    def test_duration_and_focused_baseline_ratio_are_real_gates(self):
        verifier = load_module()
        rows = [row(i // 2) for i in range(20)]
        short = verifier.analyze_rows(rows, fps=2, min_active_seconds=11)
        self.assertFalse(short["ok"])
        self.assertIn("duration", " ".join(short["failures"]))
        slow = verifier.analyze_rows(rows, fps=2, baseline_fresh_source_fps=2.0,
                                     min_ratio=0.8)
        self.assertFalse(slow["ok"])
        self.assertLess(slow["fresh_source_ratio"], 0.8)

    def test_declared_container_count_is_disclosed_but_decoded_count_is_authoritative(self):
        verifier = load_module()
        metrics = verifier.analyze_rows([row(1), row(2)], fps=2)
        verifier.reconcile_frame_counts(metrics, declared=3, decodable=2)
        self.assertTrue(metrics["ok"])
        self.assertEqual(metrics["container_declared_frames"], 3)
        self.assertEqual(metrics["ffprobe_decodable_frames"], 2)
        self.assertIn("discrepancy", " ".join(metrics["warnings"]))
        verifier.reconcile_frame_counts(metrics, declared=3, decodable=3)
        self.assertFalse(metrics["ok"])
        self.assertIn("decoded frame count", " ".join(metrics["failures"]))

    def test_full_ten_second_freeze_fails_even_when_overall_ratio_passes(self):
        verifier = load_module()
        rows = [row(i) for i in range(20)] + [row(20)] * 20
        metrics = verifier.analyze_rows(rows, fps=2, baseline_fresh_source_fps=1.0)
        self.assertGreaterEqual(metrics["fresh_source_ratio"], 0.8)
        self.assertFalse(metrics["ok"])
        self.assertIn("window", " ".join(metrics["failures"]))
        self.assertEqual(metrics["window_ratio_checks"][1]["checked"], True)

    def test_short_trailing_window_is_visible_but_not_ratio_gated(self):
        verifier = load_module()
        rows = [row(i) for i in range(20)] + [row(20)] * 10
        metrics = verifier.analyze_rows(rows, fps=2, baseline_fresh_source_fps=1.0)
        self.assertTrue(metrics["ok"])
        self.assertEqual(metrics["per_10_seconds"][-1]["duration_seconds"], 5.0)
        self.assertFalse(metrics["window_ratio_checks"][-1]["checked"])

    def test_ffmpeg_decode_diagnostic_is_not_ignored_on_zero_exit(self):
        verifier = load_module()
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "fake_ffmpeg"
            fake.write_text("#!/bin/sh\nprintf 'decoder error on frame 1\\n' >&2\nexit 0\n")
            fake.chmod(0o700)
            with self.assertRaisesRegex(verifier.Refused, "decoder error"):
                list(verifier.cropped_rows(Path("unused.mov"), str(fake)))


if __name__ == "__main__":
    unittest.main()
