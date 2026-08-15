from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from reporting.contracts import collect_summary, ffmpeg_gif_command, write_summary_csv


class ReportingContractTest(unittest.TestCase):
    def test_missing_artifacts_remain_missing_not_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            row = collect_summary(Path(temp), "fast_livo2")
            self.assertEqual("MISSING", row.run_status)
            self.assertEqual("MISSING", row.trajectory_status)
            self.assertEqual("MISSING", row.map_status)
            self.assertIsNone(row.path_length_m)
            self.assertIsNone(row.map_points)

    def test_map_metadata_is_summarized(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            map_dir = run / "standardized/maps/a"
            map_dir.mkdir(parents=True)
            (map_dir / "map_metadata.json").write_text(json.dumps({
                "map_source": "UNIFIED_RECONSTRUCTION",
                "point_count": 42,
                "timestamp_matching": {"matched_scan_count": 10, "unmatched_scan_count": 2}
            }), encoding="utf-8")
            row = collect_summary(run, "a")
            self.assertEqual("AVAILABLE", row.map_status)
            self.assertEqual(42, row.map_points)
            self.assertEqual(10, row.matched_scans)
            self.assertEqual(2, row.unmatched_scans)

    def test_ffmpeg_command_is_deterministic(self) -> None:
        command = ffmpeg_gif_command(Path("frames/frame_%05d.png"), Path("demo.gif"), fps=8, width_px=800)
        self.assertEqual("ffmpeg", command[0])
        self.assertIn("frames/frame_%05d.png", command)
        self.assertEqual("demo.gif", command[-1])
        self.assertIn("fps=8", command[command.index("-vf") + 1])


if __name__ == "__main__":
    unittest.main()
