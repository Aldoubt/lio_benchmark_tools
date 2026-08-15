from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmark_base.lib.artifacts import build_map_metadata, merge_standardization_report


class ArtifactMetadataTest(unittest.TestCase):
    def test_map_source_is_explicit(self) -> None:
        payload = build_map_metadata(
            map_source="UNIFIED_RECONSTRUCTION",
            algorithm_id="point_lio",
            dataset_id="gaas_a",
            trajectory_source="trajectory.csv",
            voxel_m=0.1,
            point_count=123,
            generation_command="unit",
            generated_at="2026-08-15T00:00:00+08:00",
            timestamp_matching={"matched_scan_count": 10, "unmatched_scan_count": 1},
        )
        self.assertEqual("UNIFIED_RECONSTRUCTION", payload["map_source"])
        self.assertEqual(10, payload["timestamp_matching"]["matched_scan_count"])

    def test_invalid_map_source_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid map_source"):
            build_map_metadata(
                map_source="UNKNOWN",
                algorithm_id="x",
                dataset_id="d",
                trajectory_source="t",
                voxel_m=0.1,
                point_count=0,
                generation_command="unit",
                generated_at="now",
            )

    def test_standardization_report_merges_algorithms(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "report.json"
            merge_standardization_report(path, "a", {"value": 1})
            merge_standardization_report(path, "b", {"value": 2})
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual({"a", "b"}, set(payload["algorithms"]))


if __name__ == "__main__":
    unittest.main()
