from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from benchmark_base.lib.same_bag_summary import summarize_same_bag


class SameBagSummaryContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.run = Path(self.temp.name) / "run"
        self.run.mkdir()
        manifest = {
            "run_id": "synthetic_full_v1",
            "dataset": {
                "dataset_id": "green_house_mid360",
                "topics": {
                    "lidar": "/livox/lidar",
                    "imu": "/livox/imu",
                    "camera": None,
                },
            },
            "replay": {"rate": 1.0, "start_offset_s": 0.0, "duration_s": 622.99},
            "algorithms": {
                "fast_livo2": {
                    "algorithm_id": "fast_livo2",
                    "display_name": "FAST-LIVO2",
                    "sensor_profile": {"lidar": True, "imu": True, "camera": False},
                    "inputs": {"lidar": "/livox/lidar", "imu": "/livox/imu", "camera": None},
                    "outputs": {
                        "trajectory_topic": "/aft_mapped_to_init",
                        "registered_cloud_topic": "/cloud_registered",
                    },
                    "evaluation_roles": ["COMMON_LIDAR_IMU_ODOMETRY"],
                },
                "fast_lio2": {
                    "algorithm_id": "fast_lio2",
                    "display_name": "FAST-LIO2",
                    "sensor_profile": {"lidar": True, "imu": True, "camera": False},
                    "inputs": {"lidar": "/livox/lidar", "imu": "/livox/imu", "camera": None},
                    "outputs": {"trajectory_topic": "/Odometry", "map_topic": "/Laser_map"},
                    "native_map": {"default_status": "NOT_PROVIDED"},
                    "evaluation_roles": ["COMMON_LIDAR_IMU_ODOMETRY"],
                },
                "kiss_icp": {
                    "algorithm_id": "kiss_icp",
                    "display_name": "KISS-ICP",
                    "sensor_profile": {"lidar": True, "imu": False, "camera": False},
                    "inputs": {"lidar": "/lio_benchmark/kiss_icp_points", "imu": None, "camera": None},
                    "outputs": {"trajectory_topic": "kiss/odometry", "local_map_topic": "kiss/local_map"},
                    "preprocessing": {"native_global_map": "NOT_PROVIDED"},
                    "evaluation_roles": ["LIDAR_ONLY_CONTROL"],
                },
            },
        }
        (self.run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        for algorithm_id in manifest["algorithms"]:
            (self.run / "metadata" / "algorithms" / algorithm_id).mkdir(parents=True, exist_ok=True)
            (self.run / "metadata" / "algorithms" / algorithm_id / "runtime_identity.json").write_text(
                json.dumps(
                    {
                        "algorithm_id": algorithm_id,
                        "identity_status": "FROZEN",
                        "resolution_method": "REGISTRY_DEFAULT_EXECUTION",
                        "resolved_executable": f"/runtime/{algorithm_id}",
                        "executable_sha256": f"sha-{algorithm_id}",
                    }
                ),
                encoding="utf-8",
            )
            (self.run / "metadata").mkdir(parents=True, exist_ok=True)
            (self.run / "metadata" / f"run_{algorithm_id}.json").write_text(
                json.dumps({"algorithm_id": algorithm_id, "status": "PASS", "returncode": 0}),
                encoding="utf-8",
            )
            (self.run / "standardized" / "trajectories").mkdir(parents=True, exist_ok=True)
            (self.run / "standardized" / "trajectories" / f"{algorithm_id}.csv").write_text(
                "timestamp,x,y,z,qx,qy,qz,qw\n0,0,0,0,0,0,0,1\n",
                encoding="utf-8",
            )

        runtime_dir = self.run / "metrics" / "runtime"
        runtime_dir.mkdir(parents=True)
        for index, algorithm_id in enumerate(("fast_livo2", "fast_lio2", "kiss_icp"), start=1):
            (runtime_dir / f"{algorithm_id}.json").write_text(
                json.dumps(
                    {
                        "schema": "lio_benchmark_runtime_performance/v1",
                        "algorithm_id": algorithm_id,
                        "measurement_method": "LINUX_PROC_PROCESS_SESSION_V1",
                        "wall_time_s": 620.0 + index,
                        "cpu_user_s": 100.0 + index,
                        "cpu_system_s": 10.0 + index,
                        "cpu_total_s": 110.0 + 2 * index,
                        "max_rss_kib": 100000 + index,
                        "returncode": 0,
                        "status": "PASS",
                    }
                ),
                encoding="utf-8",
            )

        fast_livo_native = self.run / "standardized" / "maps" / "fast_livo2" / "native"
        fast_livo_native.mkdir(parents=True)
        (fast_livo_native / "map.ply").write_text("ply\n", encoding="utf-8")
        (fast_livo_native / "metadata.json").write_text(
            json.dumps({"schema": "lio_benchmark_native_map/v1", "status": "AVAILABLE", "point_count": 42}),
            encoding="utf-8",
        )

        for algorithm_id, point_count in (("fast_livo2", 101), ("fast_lio2", 202), ("kiss_icp", 303)):
            unified = self.run / "standardized" / "maps" / algorithm_id / "unified"
            unified.mkdir(parents=True)
            (unified / "map.ply").write_text("ply\n", encoding="utf-8")
            (unified / "metadata.json").write_text(
                json.dumps(
                    {
                        "schema": "lio_benchmark_map/v3",
                        "map_source": "UNIFIED_RECONSTRUCTION",
                        "point_count": point_count,
                        "scan_set_policy": "STRICT_COMMON_INTERSECTION",
                        "timestamp_matching": {
                            "matched_scan_count": 120,
                            "selected_scan_count": 120,
                            "unmatched_scan_count": 0,
                            "matched_scan_ratio": 1.0,
                        },
                    }
                ),
                encoding="utf-8",
            )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _summary_outputs(self) -> tuple[Path, ...]:
        return (
            self.run / "reports" / "algorithm_io_matrix.csv",
            self.run / "reports" / "algorithm_io_matrix.md",
            self.run / "metrics" / "runtime_performance.csv",
            self.run / "reports" / "same_bag_mapping_v1.json",
        )

    def test_summary_preserves_modalities_final_maps_and_native_missing_evidence(self) -> None:
        payload = summarize_same_bag(self.run)
        rows = payload["algorithms"]
        self.assertEqual(["fast_livo2", "fast_lio2", "kiss_icp"], [row["algorithm_id"] for row in rows])

        fast_livo2, _, kiss = rows
        self.assertEqual("lidar+imu", fast_livo2["effective_modalities"])
        self.assertEqual("lidar", kiss["effective_modalities"])
        self.assertEqual("AVAILABLE", fast_livo2["native_map_status"])
        self.assertEqual(42, fast_livo2["native_map_point_count"])
        self.assertEqual("NOT_PROVIDED", kiss["native_map_status"])
        self.assertEqual("AVAILABLE", fast_livo2["unified_map_status"])
        self.assertEqual(101, fast_livo2["unified_map_point_count"])
        self.assertEqual("STRICT_COMMON_INTERSECTION", fast_livo2["strict_common_scan_policy"])
        self.assertEqual(120, fast_livo2["matched_scan_count"])
        self.assertEqual(120, fast_livo2["selected_scan_count"])
        self.assertEqual(0, fast_livo2["unmatched_scan_count"])
        self.assertEqual(1.0, fast_livo2["matched_scan_ratio"])
        self.assertEqual("AVAILABLE", kiss["unified_map_status"])
        self.assertEqual(303, kiss["unified_map_point_count"])
        self.assertIsNotNone(kiss["wall_time_s"])
        self.assertIsNotNone(kiss["max_rss_kib"])
        for row in rows:
            self.assertNotIn("map_accuracy", row)

        self.assertTrue(all(path.is_file() for path in self._summary_outputs()))

        with (self.run / "reports" / "algorithm_io_matrix.csv").open(newline="", encoding="utf-8") as stream:
            csv_rows = list(csv.DictReader(stream))
        self.assertEqual(3, len(csv_rows))
        self.assertEqual("kiss_icp", csv_rows[2]["algorithm_id"])
        self.assertEqual("0", csv_rows[2]["unmatched_scan_count"])

    def test_summary_refuses_to_freeze_before_all_strict_unified_maps_are_complete(self) -> None:
        unified = self.run / "standardized" / "maps" / "kiss_icp" / "unified"
        (unified / "map.ply").unlink()
        (unified / "metadata.json").unlink()

        with self.assertRaisesRegex(ValueError, "Same-Bag summary is not ready"):
            summarize_same_bag(self.run)

        self.assertTrue(all(not path.exists() for path in self._summary_outputs()))

    def test_summary_outputs_are_immutable(self) -> None:
        summarize_same_bag(self.run)
        with self.assertRaises(FileExistsError):
            summarize_same_bag(self.run)


if __name__ == "__main__":
    unittest.main()
