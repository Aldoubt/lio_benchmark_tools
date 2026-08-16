from __future__ import annotations

import unittest

from benchmark_base.lib.map_sampling import ScanWindow, in_scan_window


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


if __name__ == "__main__":
    unittest.main()
