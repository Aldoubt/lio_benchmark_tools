from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from benchmark_base.lib.map_sampling import (
    SelectedScan,
    read_scan_manifest,
    select_scan_indices,
    write_scan_manifest,
)


class MapSamplingContractTest(unittest.TestCase):
    def test_deterministic_scan_step_selection(self) -> None:
        self.assertEqual((0, 3, 6, 9), select_scan_indices(total_scans=10, scan_step=3))
        self.assertEqual((0, 5, 10), select_scan_indices(total_scans=11, scan_step=5))

    def test_green_house_selection_count_semantics(self) -> None:
        indices = select_scan_indices(total_scans=6230, scan_step=5)
        self.assertEqual(1246, len(indices))
        self.assertEqual(0, indices[0])
        self.assertEqual(6225, indices[-1])

    def test_manifest_round_trip_preserves_exact_selected_set(self) -> None:
        rows = [
            SelectedScan(0, 100.0, "HEADER_STAMP", 100.001, "/lidar", True),
            SelectedScan(5, 100.5, "HEADER_STAMP", 100.501, "/lidar", True),
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "selected_scans.csv"
            write_scan_manifest(path, rows)
            loaded = read_scan_manifest(path)
        self.assertEqual(tuple(rows), loaded)

    def test_duplicate_scan_index_fails_closed(self) -> None:
        rows = [
            SelectedScan(0, 1.0, "HEADER_STAMP", 1.0, "/lidar", True),
            SelectedScan(0, 2.0, "HEADER_STAMP", 2.0, "/lidar", True),
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "selected_scans.csv"
            with self.assertRaises(ValueError):
                write_scan_manifest(path, rows)

    def test_invalid_scan_step_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            select_scan_indices(total_scans=10, scan_step=0)

    def test_nonfinite_timestamp_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            SelectedScan(0, float("nan"), "HEADER_STAMP", 1.0, "/lidar", True)


if __name__ == "__main__":
    unittest.main()
