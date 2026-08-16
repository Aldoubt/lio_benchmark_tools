from __future__ import annotations

import csv
import hashlib
import importlib
import json
import tempfile
import unittest
from pathlib import Path

from benchmark_base.lib.trajectory import PoseSample, Trajectory, quaternion_from_rpy


class RelativeSE3RunContractTest(unittest.TestCase):
    def _api(self, name: str):
        module = importlib.import_module("benchmark_base.lib.relative_se3")
        self.assertTrue(hasattr(module, name), f"relative_se3.{name} must exist")
        return getattr(module, name)

    @staticmethod
    def _sample(timestamp: float, x: float, y: float = 0.0, z: float = 0.0) -> PoseSample:
        qx, qy, qz, qw = quaternion_from_rpy(0.0, 0.0, 0.0)
        return PoseSample(
            timestamp_s=timestamp,
            x_m=x,
            y_m=y,
            z_m=z,
            qx=qx,
            qy=qy,
            qz=qz,
            qw=qw,
            roll_rad=0.0,
            pitch_rad=0.0,
            yaw_rad=0.0,
            source_topic="/test",
        )

    def _write_trajectory(self, run: Path, algorithm_id: str, x_offset: float = 0.0) -> Path:
        path = run / "standardized" / "trajectories" / f"{algorithm_id}.csv"
        Trajectory([
            self._sample(0.0, x_offset + 0.0),
            self._sample(0.5, x_offset + 0.5),
            self._sample(1.0, x_offset + 1.0),
        ]).write_csv(path)
        return path

    @staticmethod
    def _algorithm(algorithm_id: str, tracked: str, child: str, extrinsic: str) -> dict:
        return {
            "algorithm_id": algorithm_id,
            "extrinsic_convention": extrinsic,
            "sensor_profile": {"lidar": True, "imu": tracked == "IMU_BODY"},
            "trajectory_contract": {
                "pose_semantics": "T_PARENT_TRACKED",
                "tracked_frame_physical": tracked,
                "world_gauge": "INITIAL_BODY_ALIGNED" if tracked == "IMU_BODY" else "INITIAL_LIDAR_ALIGNED",
                "expected_parent_frames": ["world"],
                "expected_child_frames": [child],
            },
        }

    def _build_run(self, root: Path, *, calibration: dict | None = None) -> Path:
        run = root / "run"
        (run / "standardized" / "trajectories").mkdir(parents=True)
        (run / "metadata" / "algorithms").mkdir(parents=True)
        (run / "metadata" / "frame_audit").mkdir(parents=True)
        (run / "metrics").mkdir(parents=True)

        if calibration is None:
            calibration = {
                "rotation_lidar_to_imu_row_major": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
                "translation_lidar_to_imu_m": [0.1, 0.0, 0.0],
                "status": "BLOCKED_CALIBRATION",
                "source": "test",
            }
        algorithms = {
            "imu_a": self._algorithm("imu_a", "IMU_BODY", "body_a", "LIDAR_TO_IMU"),
            "imu_b": self._algorithm("imu_b", "IMU_BODY", "body_b", "LIDAR_TO_IMU"),
            "lidar_c": self._algorithm("lidar_c", "LIDAR", "lidar", "NONE"),
        }
        manifest = {
            "schema_version": 2,
            "run_id": "relative_se3_test",
            "dataset": {"dataset_id": "test", "calibration": calibration},
            "algorithms": algorithms,
        }
        (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        self._write_trajectory(run, "imu_a", 0.0)
        self._write_trajectory(run, "imu_b", 0.0)
        # With identity rotation and t_IL=(0.1,0,0), T_WL = T_WI * T_IL.
        self._write_trajectory(run, "lidar_c", 0.1)

        provenance_rows = []
        for algorithm_id, algorithm in algorithms.items():
            identity_dir = run / "metadata" / "algorithms" / algorithm_id
            identity_dir.mkdir(parents=True)
            (identity_dir / "runtime_identity.json").write_text(
                json.dumps({"algorithm_id": algorithm_id, "identity_status": "FROZEN"}),
                encoding="utf-8",
            )
            contract = algorithm["trajectory_contract"]
            (run / "metadata" / "frame_audit" / f"{algorithm_id}.json").write_text(
                json.dumps({
                    "algorithm_id": algorithm_id,
                    "status": "AVAILABLE",
                    "parent_frame_ids": contract["expected_parent_frames"],
                    "child_frame_ids": contract["expected_child_frames"],
                }),
                encoding="utf-8",
            )
            provenance_rows.append({
                "algorithm_id": algorithm_id,
                "status": "MATCH",
                "identity_evidence_source": "RUNTIME_IDENTITY",
                "runtime_identity_status": "FROZEN",
                "frame_contract_status": "MATCH",
                "tracked_frame_physical": contract["tracked_frame_physical"],
            })
        with (run / "metrics" / "runtime_provenance.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(provenance_rows[0]))
            writer.writeheader()
            writer.writerows(provenance_rows)
        return run

    @staticmethod
    def _sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_run_writes_five_artifacts_and_preserves_standardized_trajectories(self) -> None:
        compare_run = self._api("compare_run")
        with tempfile.TemporaryDirectory() as temp:
            run = self._build_run(Path(temp))
            inputs = sorted((run / "standardized" / "trajectories").glob("*.csv"))
            before = {path.name: self._sha(path) for path in inputs}
            output = compare_run(run)
            self.assertEqual(run / "metrics" / "relative_se3", output)
            expected = {
                "metadata.json",
                "normalized_motion.csv",
                "pairwise_samples.csv",
                "pairwise_summary.csv",
                "onset_thresholds.csv",
            }
            self.assertEqual(expected, {path.name for path in output.iterdir()})
            after = {path.name: self._sha(path) for path in inputs}
            self.assertEqual(before, after)

            metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual("IMU_BODY", metadata["target_physical_frame"])
            self.assertEqual(0.1, metadata["sample_period_s"])
            self.assertEqual(3, metadata["sustain_samples"])
            self.assertEqual([0.05, 0.1, 0.2, 0.5], metadata["translation_thresholds_m"])
            self.assertEqual([1.0, 2.0, 5.0, 10.0], metadata["rotation_thresholds_deg"])
            self.assertEqual("T(t0)^-1 * T(t)", metadata["world_gauge_normalization"])
            self.assertEqual("SO3_GEODESIC", metadata["rotation_disagreement"])
            self.assertEqual("NONE", metadata["ground_truth"])
            self.assertEqual("PAIRWISE_DISAGREEMENT", metadata["terminology"])

            with (output / "normalized_motion.csv").open(newline="", encoding="utf-8") as stream:
                normalized = list(csv.DictReader(stream))
            for algorithm_id in ("imu_a", "imu_b", "lidar_c"):
                first = next(row for row in normalized if row["algorithm_id"] == algorithm_id)
                self.assertAlmostEqual(0.0, float(first["x_m"]), places=9)
                self.assertAlmostEqual(0.0, float(first["y_m"]), places=9)
                self.assertAlmostEqual(0.0, float(first["z_m"]), places=9)
                self.assertAlmostEqual(1.0, float(first["qw"]), places=9)

            with (output / "pairwise_summary.csv").open(newline="", encoding="utf-8") as stream:
                summary = list(csv.DictReader(stream))
            self.assertEqual(3, len(summary))
            self.assertTrue(all(row["scientific_status"] == "DIAGNOSTIC_ONLY" for row in summary))
            lidar_rows = [row for row in summary if "lidar_c" in (row["left_algorithm_id"], row["right_algorithm_id"])]
            self.assertTrue(all(row["physical_frame_normalization_uses_calibration"] == "True" for row in lidar_rows))

    def test_missing_lidar_calibration_blocks_lidar_and_keeps_imu_pair(self) -> None:
        compare_run = self._api("compare_run")
        with tempfile.TemporaryDirectory() as temp:
            run = self._build_run(Path(temp), calibration={"status": "UNKNOWN"})
            output = compare_run(run)
            metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
            self.assertIn("lidar_c", metadata["blocked_algorithms"])
            self.assertIn("calibration", " ".join(metadata["blocked_algorithms"]["lidar_c"]["reasons"]).lower())
            with (output / "pairwise_summary.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(1, len(rows))
            self.assertEqual({"imu_a", "imu_b"}, {rows[0]["left_algorithm_id"], rows[0]["right_algorithm_id"]})

    def test_identity_provenance_and_frame_contract_each_fail_closed_for_one_algorithm(self) -> None:
        compare_run = self._api("compare_run")
        cases = ("identity", "provenance", "frame")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                run = self._build_run(Path(temp))
                if case == "identity":
                    path = run / "metadata" / "algorithms" / "lidar_c" / "runtime_identity.json"
                    path.write_text(json.dumps({"identity_status": "BLOCKED_EXECUTION"}), encoding="utf-8")
                elif case == "provenance":
                    path = run / "metrics" / "runtime_provenance.csv"
                    with path.open(newline="", encoding="utf-8") as stream:
                        rows = list(csv.DictReader(stream))
                        fields = list(rows[0])
                    for row in rows:
                        if row["algorithm_id"] == "lidar_c":
                            row["status"] = "UNRESOLVED"
                    with path.open("w", newline="", encoding="utf-8") as stream:
                        writer = csv.DictWriter(stream, fieldnames=fields)
                        writer.writeheader(); writer.writerows(rows)
                else:
                    path = run / "metadata" / "frame_audit" / "lidar_c.json"
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    payload["child_frame_ids"] = ["wrong"]
                    path.write_text(json.dumps(payload), encoding="utf-8")

                output = compare_run(run)
                metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
                self.assertIn("lidar_c", metadata["blocked_algorithms"])
                with (output / "pairwise_summary.csv").open(newline="", encoding="utf-8") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(1, len(rows))

    def test_existing_output_directory_is_refused(self) -> None:
        compare_run = self._api("compare_run")
        error_type = self._api("RelativeSE3Error")
        with tempfile.TemporaryDirectory() as temp:
            run = self._build_run(Path(temp))
            compare_run(run)
            with self.assertRaises(error_type):
                compare_run(run)


if __name__ == "__main__":
    unittest.main()
