from __future__ import annotations

import unittest

from benchmark_base.lib.map_sampling import ScanWindow, in_scan_window, resolve_scan_window


class ScanWindowTest(unittest.TestCase):
    def test_duration_window_is_relative_to_first_lidar_record_time(self) -> None:
        window = ScanWindow(start_offset_s=0.0, duration_s=15.0)
        first = 100.0
        self.assertTrue(in_scan_window(100.0, first, window))
        self.assertTrue(in_scan_window(114.999, first, window))
        self.assertFalse(in_scan_window(115.001, first, window))

    def test_nonzero_offset_excludes_earlier_scans(self) -> None:
        window = ScanWindow(start_offset_s=5.0, duration_s=10.0)
        first = 100.0
        self.assertFalse(in_scan_window(104.999, first, window))
        self.assertTrue(in_scan_window(105.0, first, window))
        self.assertTrue(in_scan_window(114.999, first, window))
        self.assertFalse(in_scan_window(115.001, first, window))

    def test_invalid_windows_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            ScanWindow(start_offset_s=-1.0, duration_s=10.0)
        with self.assertRaises(ValueError):
            ScanWindow(start_offset_s=0.0, duration_s=0.0)

    def test_scan_window_defaults_to_frozen_run_replay(self) -> None:
        window, source = resolve_scan_window(
            replay={"rate": 1.0, "start_offset_s": 3.0, "duration_s": 15.0},
            legacy_replay_window=None,
            start_offset_override=None,
            duration_override=None,
        )
        self.assertEqual(3.0, window.start_offset_s)
        self.assertEqual(15.0, window.duration_s)
        self.assertEqual("RUN_MANIFEST_REPLAY", source)

    def test_cli_scan_window_is_labeled_override_and_inherits_unspecified_dimension(self) -> None:
        window, source = resolve_scan_window(
            replay={"rate": 1.0, "start_offset_s": 2.0, "duration_s": 15.0},
            legacy_replay_window=None,
            start_offset_override=None,
            duration_override=5.0,
        )
        self.assertEqual(2.0, window.start_offset_s)
        self.assertEqual(5.0, window.duration_s)
        self.assertEqual("CLI_OVERRIDE", source)

    def test_legacy_replay_window_remains_explicitly_labeled(self) -> None:
        window, source = resolve_scan_window(
            replay=None,
            legacy_replay_window={"start_offset_s": 1.0, "duration_s": 7.0},
            start_offset_override=None,
            duration_override=None,
        )
        self.assertEqual(1.0, window.start_offset_s)
        self.assertEqual(7.0, window.duration_s)
        self.assertEqual("LEGACY_REPLAY_WINDOW", source)

    def test_missing_replay_contract_means_full_bag_default(self) -> None:
        window, source = resolve_scan_window(
            replay=None,
            legacy_replay_window=None,
            start_offset_override=None,
            duration_override=None,
        )
        self.assertEqual(0.0, window.start_offset_s)
        self.assertIsNone(window.duration_s)
        self.assertEqual("FULL_BAG_DEFAULT", source)


if __name__ == "__main__":
    unittest.main()
