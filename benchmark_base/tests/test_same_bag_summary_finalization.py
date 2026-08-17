from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from benchmark_base.lib.same_bag_summary import finalize_stale_same_bag


class SameBagSummaryFinalizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.run = Path(self.temp.name) / "run"
        self.run.mkdir()
        algorithms = {
            "fast_livo2": {
                "algorithm_id": "fast_livo2",
                "display_name": "FAST-LIVO2",
                "sensor_profile": {"lidar": True, "imu": True},
                "topics": {
                    "inputs": {"lidar": "/livox/lidar", "imu": "/livox/imu"},
                    "outputs": {"trajectory": "/aft_mapped_to_init"},
                },
                "evaluation_roles": ["ODOMETRY"],
            },
            "fast_lio2": {
                "algorithm_id": "fast_lio2",
                "display_name": "FAST-LIO2",
                "sensor_profile": {"lidar": True, "imu": True},
                "topics": {
                    "inputs": {"lidar": "/livox/lidar", "imu": "/livox/imu"},
                    "outputs": {"trajectory": "/Odometry"},
                },
                "native_map": {"default_status": "NOT_PROVIDED"},
                "evaluation_roles": ["ODOMETRY"],
            },
            "kiss_icp": {
                "algorithm_id": "kiss_icp",
                "display_name": "KISS-ICP",
                "sensor_profile": {"lidar": True, "imu": False},
                "topics": {
                    "inputs": {"lidar": "/lio_benchmark/kiss_icp_points", "imu": None},
                    "outputs": {"trajectory": "kiss/odometry"},
                },
                "preprocessing": {"native_global_map": "NOT_PROVIDED"},
                "evaluation_roles": ["LIDAR_ONLY_CONTROL"],
            },
        }
        manifest = {
            "run_id": "stale_summary_run",
            "dataset": {"dataset_id": "green_house_mid360"},
            "replay": {"rate": 1.0, "start_offset_s": 0.0, "duration_s": 622.99},
            "algorithms": algorithms,
        }
        (self.run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        for index, algorithm_id in enumerate(algorithms, start=1):
            identity = self.run / "metadata" / "algorithms" / algorithm_id
            identity.mkdir(parents=True, exist_ok=True)
            (identity / "runtime_identity.json").write_text(
                json.dumps(
                    {
                        "identity_status": "FROZEN",
                        "resolution_method": "REGISTRY_DEFAULT_EXECUTION",
                        "resolved_executable": f"/runtime/{algorithm_id}",
                        "executable_sha256": f"sha-{algorithm_id}",
                    }
                ),
                encoding="utf-8",
            )
            (self.run / "metadata" / f"run_{algorithm_id}.json").write_text(
                json.dumps({"status": "PASS", "returncode": 0}), encoding="utf-8"
            )
            trajectory_dir = self.run / "standardized" / "trajectories"
            trajectory_dir.mkdir(parents=True, exist_ok=True)
            (trajectory_dir / f"{algorithm_id}.csv").write_text(
                "timestamp,x,y,z,qx,qy,qz,qw\n0,0,0,0,0,0,0,1\n",
                encoding="utf-8",
            )
            runtime_dir = self.run / "metrics" / "runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            (runtime_dir / f"{algorithm_id}.json").write_text(
                json.dumps(
                    {
                        "schema": "lio_benchmark_runtime_performance/v1",
                        "algorithm_id": algorithm_id,
                        "measurement_method": "LINUX_PROC_PROCESS_SESSION_V1",
                        "wall_time_s": 650.0 + index,
                        "cpu_user_s": 100.0,
                        "cpu_system_s": 10.0,
                        "cpu_total_s": 110.0,
                        "max_rss_kib": 100000 + index,
                        "returncode": 0,
                        "status": "PASS",
                    }
                ),
                encoding="utf-8",
            )
            unified = self.run / "standardized" / "maps" / algorithm_id / "unified"
            unified.mkdir(parents=True, exist_ok=True)
            (unified / "map.ply").write_text("ply\n", encoding="utf-8")
            (unified / "metadata.json").write_text(
                json.dumps(
                    {
                        "point_count": 1000 * index,
                        "scan_set_policy": "STRICT_COMMON_INTERSECTION",
                        "timestamp_matching": {
                            "selected_scan_count": 829,
                            "matched_scan_count": 829,
                            "unmatched_scan_count": 0,
                            "matched_scan_ratio": 1.0,
                        },
                    }
                ),
                encoding="utf-8",
            )

        common = self.run / "standardized" / "map_sampling"
        common.mkdir(parents=True, exist_ok=True)
        (common / "common_matched_metadata.json").write_text(
            json.dumps({"common_matched_scan_count": 829}), encoding="utf-8"
        )

        reports = self.run / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        metrics = self.run / "metrics"
        metrics.mkdir(parents=True, exist_ok=True)
        stale = {
            "schema": "lio_benchmark_same_bag_mapping/v1",
            "scientific_status": "DESCRIPTIVE_NO_GROUND_TRUTH",
            "performance_status": "SINGLE_RUN_DESCRIPTIVE",
            "algorithms": [
                {"algorithm_id": algorithm_id, "unified_map_status": "MISSING"}
                for algorithm_id in algorithms
            ],
        }
        (reports / "same_bag_mapping_v1.json").write_text(
            json.dumps(stale), encoding="utf-8"
        )
        (reports / "algorithm_io_matrix.csv").write_text("legacy-csv\n", encoding="utf-8")
        (reports / "algorithm_io_matrix.md").write_text("legacy-md\n", encoding="utf-8")
        (metrics / "runtime_performance.csv").write_text("legacy-runtime\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_finalization_preserves_stale_outputs_and_writes_append_only_final_package(self) -> None:
        original_paths = (
            self.run / "reports" / "algorithm_io_matrix.csv",
            self.run / "reports" / "algorithm_io_matrix.md",
            self.run / "metrics" / "runtime_performance.csv",
            self.run / "reports" / "same_bag_mapping_v1.json",
        )
        before = {path: path.read_bytes() for path in original_paths}
        source_summary_sha = hashlib.sha256(
            (self.run / "reports" / "same_bag_mapping_v1.json").read_bytes()
        ).hexdigest()

        payload = finalize_stale_same_bag(self.run)

        self.assertEqual(before, {path: path.read_bytes() for path in original_paths})
        rows = payload["algorithms"]
        self.assertEqual(
            ["fast_livo2", "fast_lio2", "kiss_icp"],
            [row["algorithm_id"] for row in rows],
        )
        self.assertTrue(all(row["unified_map_status"] == "AVAILABLE" for row in rows))
        self.assertTrue(
            all(row["strict_common_scan_policy"] == "STRICT_COMMON_INTERSECTION" for row in rows)
        )
        self.assertTrue(all(row["matched_scan_count"] == 829 for row in rows))
        self.assertTrue(all(row["selected_scan_count"] == 829 for row in rows))
        self.assertTrue(all(row["unmatched_scan_count"] == 0 for row in rows))

        final_dir = self.run / "reports" / "same_bag_mapping_v1_finalization"
        expected = {
            final_dir / "algorithm_io_matrix.csv",
            final_dir / "algorithm_io_matrix.md",
            final_dir / "runtime_performance.csv",
            final_dir / "same_bag_mapping_v1.json",
            final_dir / "lineage.json",
        }
        self.assertTrue(all(path.is_file() for path in expected))

        lineage = json.loads((final_dir / "lineage.json").read_text(encoding="utf-8"))
        self.assertEqual("lio_benchmark_same_bag_mapping_finalization/v1", lineage["schema"])
        self.assertEqual("PREMATURE_IMMUTABLE_SUMMARY", lineage["reason"])
        self.assertEqual(source_summary_sha, lineage["source_summary_sha256"])
        self.assertEqual(
            "APPEND_ONLY_FINALIZATION", payload["artifact_role"]
        )

        with self.assertRaises(FileExistsError):
            finalize_stale_same_bag(self.run)

    def test_finalization_requires_a_stale_canonical_summary(self) -> None:
        summary_path = self.run / "reports" / "same_bag_mapping_v1.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        for row in summary["algorithms"]:
            row["unified_map_status"] = "AVAILABLE"
        summary_path.write_text(json.dumps(summary), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "canonical summary is not stale"):
            finalize_stale_same_bag(self.run)


if __name__ == "__main__":
    unittest.main()
