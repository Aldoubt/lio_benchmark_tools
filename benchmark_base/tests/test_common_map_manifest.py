from __future__ import annotations

import csv
import json
import tempfile
import time
import unittest
from pathlib import Path

from benchmark_base.lib.common_map_manifest import (
    build_common_map_manifest,
    sha256_file,
    validate_common_map_manifest,
)
from benchmark_base.lib.map_sampling import SelectedScan, read_scan_manifest, write_scan_manifest
from benchmark_base.lib.trajectory import PoseSample, Trajectory


class CommonMapManifestTest(unittest.TestCase):
    def _write_trajectory(self, path: Path, timestamps: list[float]) -> None:
        samples = [
            PoseSample(
                timestamp_s=value,
                x_m=value,
                y_m=0.0,
                z_m=0.0,
                qx=0.0,
                qy=0.0,
                qz=0.0,
                qw=1.0,
                roll_rad=0.0,
                pitch_rad=0.0,
                yaw_rad=0.0,
                source_topic="/test",
            )
            for value in timestamps
        ]
        Trajectory(samples).write_csv(path)

    def _make_run(
        self,
        root: Path,
        *,
        selected_times: list[float] | None = None,
        tolerance_s: float | None = 0.05,
        trajectories: dict[str, list[float]] | None = None,
    ) -> Path:
        run = root / "run"
        sampling = run / "standardized" / "map_sampling"
        trajectories_root = run / "standardized" / "trajectories"
        sampling.mkdir(parents=True)
        trajectories_root.mkdir(parents=True)

        selected_times = selected_times or [0.0, 1.0, 2.0, 3.0]
        rows = [
            SelectedScan(
                scan_index=index * 5,
                timestamp_s=value,
                timestamp_source="HEADER",
                bag_record_time_s=100.0 + value,
                lidar_topic="/livox/lidar",
                selected=True,
            )
            for index, value in enumerate(selected_times)
        ]
        write_scan_manifest(sampling / "selected_scans.csv", rows)

        trajectories = trajectories or {
            "alg_a": [-0.1, 0.0, 1.0, 2.0, 3.0, 3.1],
            "alg_b": [-0.1, 0.0, 1.0, 2.0, 3.0, 3.1],
            "alg_c": [-0.1, 0.0, 1.0, 2.0, 3.0, 3.1],
        }
        for algorithm_id, timestamps in trajectories.items():
            self._write_trajectory(trajectories_root / f"{algorithm_id}.csv", timestamps)

        standardization = {}
        if tolerance_s is not None:
            standardization["trajectory_time_tolerance_s"] = tolerance_s
        manifest = {
            "algorithms": {algorithm_id: {} for algorithm_id in trajectories},
            "standardization": standardization,
        }
        (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return run

    def test_all_algorithms_match_preserves_selected_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = self._make_run(Path(tmp))
            source = run / "standardized" / "map_sampling" / "selected_scans.csv"
            source_before = source.read_bytes()
            trajectory_hashes = {
                path.name: sha256_file(path)
                for path in sorted((run / "standardized" / "trajectories").glob("*.csv"))
            }

            output = build_common_map_manifest(run)

            self.assertEqual(source_before, source.read_bytes())
            self.assertEqual(
                [0, 5, 10, 15],
                [row.scan_index for row in read_scan_manifest(output)],
            )
            self.assertEqual(
                trajectory_hashes,
                {
                    path.name: sha256_file(path)
                    for path in sorted((run / "standardized" / "trajectories").glob("*.csv"))
                },
            )

    def test_different_algorithm_rejections_form_exact_intersection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = self._make_run(
                Path(tmp),
                trajectories={
                    "alg_a": [-0.1, 0.0, 0.2, 2.0, 3.0, 3.1],
                    "alg_b": [-0.1, 0.0, 1.0, 1.2, 3.0, 3.1],
                    "alg_c": [-0.1, 0.0, 1.0, 2.0, 3.0, 3.1],
                },
            )

            output = build_common_map_manifest(run)
            metadata = json.loads(output.with_name("common_matched_metadata.json").read_text())

            self.assertEqual([0, 15], [row.scan_index for row in read_scan_manifest(output)])
            self.assertEqual([5], metadata["algorithms"]["alg_a"]["rejected_scan_indices"])
            self.assertEqual([10], metadata["algorithms"]["alg_b"]["rejected_scan_indices"])
            self.assertEqual([], metadata["algorithms"]["alg_c"]["rejected_scan_indices"])
            self.assertEqual(4, metadata["original_selected_scan_count"])
            self.assertEqual(2, metadata["common_matched_scan_count"])
            self.assertEqual("STRICT_ALL_ALGORITHM_TRAJECTORY_INTERSECTION", metadata["policy"])

    def test_metadata_fingerprints_selected_manifest_and_every_trajectory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = self._make_run(Path(tmp))
            output = build_common_map_manifest(run)
            metadata = json.loads(output.with_name("common_matched_metadata.json").read_text())
            source = run / "standardized" / "map_sampling" / "selected_scans.csv"

            self.assertEqual(sha256_file(source), metadata["source_selected_manifest_sha256"])
            self.assertEqual(sha256_file(output), metadata["common_manifest_sha256"])
            for algorithm_id in ("alg_a", "alg_b", "alg_c"):
                trajectory = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
                record = metadata["algorithms"][algorithm_id]
                self.assertEqual(sha256_file(trajectory), record["trajectory_sha256"])
                self.assertEqual(6, record["trajectory_sample_count"])
                self.assertIn("rejected_scan_indices", record)

    def test_missing_selected_algorithm_trajectory_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = self._make_run(Path(tmp))
            (run / "standardized" / "trajectories" / "alg_b.csv").unlink()
            with self.assertRaisesRegex(ValueError, "trajectory"):
                build_common_map_manifest(run)

    def test_missing_or_invalid_tolerance_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = self._make_run(Path(tmp) / "missing", tolerance_s=None)
            with self.assertRaisesRegex(ValueError, "trajectory_time_tolerance_s"):
                build_common_map_manifest(missing)

        with tempfile.TemporaryDirectory() as tmp:
            invalid = self._make_run(Path(tmp) / "invalid", tolerance_s=-0.1)
            with self.assertRaisesRegex(ValueError, "trajectory_time_tolerance_s"):
                build_common_map_manifest(invalid)

    def test_identical_rerun_returns_existing_artifacts_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = self._make_run(Path(tmp))
            output = build_common_map_manifest(run)
            metadata_path = output.with_name("common_matched_metadata.json")
            before = (output.read_bytes(), metadata_path.read_bytes())
            mtimes = (output.stat().st_mtime_ns, metadata_path.stat().st_mtime_ns)
            time.sleep(0.01)

            again = build_common_map_manifest(run)

            self.assertEqual(output, again)
            self.assertEqual(before, (output.read_bytes(), metadata_path.read_bytes()))
            self.assertEqual(mtimes, (output.stat().st_mtime_ns, metadata_path.stat().st_mtime_ns))
            self.assertEqual("STRICT_ALL_ALGORITHM_TRAJECTORY_INTERSECTION", validate_common_map_manifest(run)["policy"])

    def test_partial_existing_common_artifacts_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = self._make_run(Path(tmp))
            output = build_common_map_manifest(run)
            output.with_name("common_matched_metadata.json").unlink()
            with self.assertRaisesRegex(ValueError, "new run"):
                build_common_map_manifest(run)

    def test_changed_trajectory_after_common_manifest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = self._make_run(Path(tmp))
            build_common_map_manifest(run)
            trajectory = run / "standardized" / "trajectories" / "alg_a.csv"
            with trajectory.open("a", encoding="utf-8") as stream:
                stream.write("\n")
            with self.assertRaisesRegex(ValueError, "new run"):
                validate_common_map_manifest(run)
            with self.assertRaisesRegex(ValueError, "new run"):
                build_common_map_manifest(run)


if __name__ == "__main__":
    unittest.main()
