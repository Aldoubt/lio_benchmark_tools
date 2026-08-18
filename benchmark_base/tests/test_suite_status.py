from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from benchmark_base.lib.artifacts import map_artifact_paths
from benchmark_base.lib.common_map_manifest import build_common_map_manifest, sha256_file
from benchmark_base.lib.map_sampling import SelectedScan, write_scan_manifest
from benchmark_base.lib.suite_plan import build_suite_plan, write_suite_plan
from benchmark_base.tests.suite_test_utils import (
    ALGORITHMS,
    DATASET_SHA,
    LIDAR_TOPIC,
    create_frozen_run,
    write_csv,
    write_json,
    write_valid_trajectory,
)


MODULE_NAME = "benchmark_base.lib.suite_status"


class SuiteStatusContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = importlib.util.find_spec(MODULE_NAME)
        cls.module = importlib.import_module(MODULE_NAME) if cls.spec is not None else None

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.run, self.manifest = create_frozen_run(Path(self.tmp.name))
        plan = build_suite_plan(self.run, self.manifest, created_at="2026-08-18T00:00:00+00:00")
        write_suite_plan(self.run, plan)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def require_module(self):
        if self.module is None:
            self.skipTest("suite_status production module is intentionally absent in RED")
        return self.module

    def stage(self, stage_id: str):
        module = self.require_module()
        status = module.derive_suite_status(self.run)
        return next(row for row in status.stages if row.stage_id == stage_id)

    def pass_setup(self) -> None:
        write_json(self.run / "metadata/environment_snapshot.json", {"python": "3.10"})
        write_json(self.run / "metrics/bag_analysis.json", {"schema_version": 1, "topics": {}})

    def pass_preflight(self, algorithm_id: str) -> None:
        write_json(
            self.run / "metadata/algorithms" / algorithm_id / "preflight.json",
            {"algorithm_id": algorithm_id, "status": "PASS", "runnable": True, "reasons": []},
        )

    def pass_preflights(self) -> None:
        for algorithm_id in ALGORITHMS:
            self.pass_preflight(algorithm_id)

    def pass_identity(self, phase: str) -> None:
        write_json(
            self.run / "metadata/suite" / f"dataset_identity_{phase}.json",
            {
                "schema": "lio_benchmark_suite_dataset_identity/v1",
                "phase": phase,
                "status": "PASS",
                "expected_bag_content_sha256": DATASET_SHA,
                "observed_bag_content_sha256": DATASET_SHA,
            },
        )

    def pass_runtime(self, algorithm_id: str) -> None:
        write_json(
            self.run / "metadata/algorithms" / algorithm_id / "runtime_identity.json",
            {"schema_version": 1, "algorithm_id": algorithm_id, "identity_status": "FROZEN"},
        )
        write_json(
            self.run / "metadata" / f"run_{algorithm_id}.json",
            {"algorithm_id": algorithm_id, "status": "PASS", "returncode": 0},
        )
        write_json(
            self.run / "metrics/runtime" / f"{algorithm_id}.json",
            {
                "schema": "lio_benchmark_runtime_performance/v1",
                "algorithm_id": algorithm_id,
                "measurement_method": "LINUX_PROC_PROCESS_SESSION_V1",
                "wall_time_s": 1.0,
                "max_rss_kib": 1024,
            },
        )

    def pass_runtimes(self) -> None:
        for algorithm_id in ALGORITHMS:
            self.pass_runtime(algorithm_id)

    def pass_trajectories(self) -> None:
        for algorithm_id in ALGORITHMS:
            write_valid_trajectory(self.run, algorithm_id)

    def pass_audits(self) -> None:
        for algorithm_id in ALGORITHMS:
            write_csv(
                self.run / "metrics/trajectory_timestamp_audit" / f"{algorithm_id}.csv",
                ["index", "effective_relation"],
                [{"index": 0, "effective_relation": "FIRST"}],
            )
            write_json(
                self.run / "metadata/trajectory_timestamp_audit" / f"{algorithm_id}.json",
                {
                    "schema_version": 1,
                    "algorithm_id": algorithm_id,
                    "summary": {"sample_count": 1, "effective_regression_count": 0},
                },
            )
            write_json(
                self.run / "metadata/frame_audit" / f"{algorithm_id}.json",
                {"algorithm_id": algorithm_id, "status": "AVAILABLE"},
            )
            write_json(
                self.run / "metadata/runtime_provenance" / f"{algorithm_id}.json",
                {
                    "algorithm_id": algorithm_id,
                    "status": "MATCH",
                    "frame_contract_status": "MATCH",
                    "identity_evidence_source": "RUNTIME_IDENTITY",
                    "runtime_identity_status": "FROZEN",
                },
            )
            write_json(
                self.run / "metadata/trajectory_coverage" / f"{algorithm_id}.json",
                {
                    "schema_version": 1,
                    "algorithm_id": algorithm_id,
                    "trajectory_count": 1,
                    "trajectory_large_gap_count": 999,
                },
            )

        write_csv(
            self.run / "metrics/trajectory_frame_audit.csv",
            ["algorithm_id", "status"],
            [{"algorithm_id": alg, "status": "AVAILABLE"} for alg in ALGORITHMS],
        )
        provenance_fields = [
            "algorithm_id",
            "status",
            "frame_contract_status",
            "identity_evidence_source",
            "runtime_identity_status",
        ]
        write_csv(
            self.run / "metrics/runtime_provenance.csv",
            provenance_fields,
            [
                {
                    "algorithm_id": alg,
                    "status": "MATCH",
                    "frame_contract_status": "MATCH",
                    "identity_evidence_source": "RUNTIME_IDENTITY",
                    "runtime_identity_status": "FROZEN",
                }
                for alg in ALGORITHMS
            ],
        )
        write_csv(
            self.run / "metrics/trajectory_coverage.csv",
            ["algorithm_id", "trajectory_count", "trajectory_large_gap_count"],
            [
                {"algorithm_id": alg, "trajectory_count": 1, "trajectory_large_gap_count": 999}
                for alg in ALGORITHMS
            ],
        )

    def pass_scan_and_common_manifest(self) -> Path:
        sampling = self.run / "standardized/map_sampling"
        rows = [
            SelectedScan(
                scan_index=index * 5,
                timestamp_s=value,
                timestamp_source="HEADER",
                bag_record_time_s=100.0 + value,
                lidar_topic=LIDAR_TOPIC,
                selected=True,
            )
            for index, value in enumerate((0.0, 1.0, 2.0, 3.0))
        ]
        selected = sampling / "selected_scans.csv"
        write_scan_manifest(selected, rows)
        write_json(
            sampling / "metadata.json",
            {
                "schema_version": 3,
                "dataset_id": "suite_test_dataset",
                "lidar_topic": LIDAR_TOPIC,
                "selected_scan_count": len(rows),
                "manifest": str(selected),
            },
        )
        return build_common_map_manifest(self.run)

    def pass_unified_maps(self, common_manifest: Path) -> None:
        common_sha = sha256_file(common_manifest)
        for algorithm_id in ALGORITHMS:
            paths = map_artifact_paths(self.run, algorithm_id)
            paths.unified_dir.mkdir(parents=True, exist_ok=True)
            paths.unified_map.write_bytes(b"ply\n")
            metadata = {
                "schema": "lio_benchmark_map/v3",
                "algorithm_id": algorithm_id,
                "map_source": "UNIFIED_RECONSTRUCTION",
                "point_count": 10,
                "scan_set_policy": "STRICT_COMMON_INTERSECTION",
                "common_manifest_sha256": common_sha,
                "timestamp_matching": {
                    "selected_scan_count": 4,
                    "matched_scan_count": 4,
                    "unmatched_scan_count": 0,
                },
            }
            write_json(paths.unified_metadata, metadata)
            paths.compat_unified_map.write_bytes(paths.unified_map.read_bytes())
            write_json(paths.compat_unified_metadata, metadata)

    def pass_relative_se3(self) -> None:
        root = self.run / "metrics/relative_se3"
        write_json(
            root / "metadata.json",
            {
                "schema": "lio_benchmark_relative_se3/v1",
                "requested_algorithms": ALGORITHMS,
                "eligible_algorithms": ALGORITHMS,
                "blocked_algorithms": {},
                "terminology": "PAIRWISE_DISAGREEMENT",
            },
        )
        for name in (
            "normalized_motion.csv",
            "pairwise_samples.csv",
            "pairwise_summary.csv",
            "onset_thresholds.csv",
        ):
            write_csv(root / name, ["value"], [{"value": 1}])

    def pass_summary(self) -> None:
        write_csv(self.run / "reports/algorithm_io_matrix.csv", ["algorithm_id"], [{"algorithm_id": a} for a in ALGORITHMS])
        (self.run / "reports/algorithm_io_matrix.md").write_text("# matrix\n", encoding="utf-8")
        write_csv(self.run / "metrics/runtime_performance.csv", ["algorithm_id"], [{"algorithm_id": a} for a in ALGORITHMS])
        write_json(
            self.run / "reports/same_bag_mapping_v1.json",
            {
                "schema": "lio_benchmark_same_bag_mapping/v1",
                "artifact_role": "CANONICAL_FINAL_SUMMARY",
                "algorithms": [{"algorithm_id": a} for a in ALGORITHMS],
            },
        )

    def pass_through_trajectories(self) -> None:
        self.pass_setup()
        self.pass_preflights()
        self.pass_identity("pre")
        self.pass_runtimes()
        self.pass_identity("post")
        self.pass_trajectories()

    def test_suite_status_module_exists(self) -> None:
        self.assertIsNotNone(
            self.spec,
            "Benchmark Suite Orchestrator V1 requires benchmark_base.lib.suite_status",
        )

    def test_setup_stages_are_ready_then_pass_only_from_valid_artifacts(self) -> None:
        self.require_module()
        self.assertEqual("READY", self.stage("snapshot").state)
        self.assertEqual("READY", self.stage("analyze_bag").state)

        self.pass_setup()
        self.assertEqual("PASS", self.stage("snapshot").state)
        self.assertEqual("PASS", self.stage("analyze_bag").state)

        (self.run / "metadata/environment_snapshot.json").write_text("[]\n", encoding="utf-8")
        state = self.stage("snapshot")
        self.assertEqual("FAIL", state.state)
        self.assertEqual("FAIL_ARTIFACT_INVALID", state.reason_code)

    def test_blocked_preflight_is_recoverable_and_does_not_block_other_preflights(self) -> None:
        self.require_module()
        self.pass_setup()
        write_json(
            self.run / "metadata/algorithms/fast_livo2/preflight.json",
            {
                "algorithm_id": "fast_livo2",
                "status": "BLOCKED_ENVIRONMENT",
                "runnable": False,
                "reasons": ["missing package"],
            },
        )
        self.pass_preflight("fast_lio2")
        self.pass_preflight("kiss_icp")

        blocked = self.stage("preflight/fast_livo2")
        self.assertEqual("BLOCKED", blocked.state)
        self.assertEqual("BLOCKED_ENVIRONMENT", blocked.reason_code)
        self.assertEqual("PASS", self.stage("preflight/fast_lio2").state)
        self.assertEqual("PASS", self.stage("preflight/kiss_icp").state)
        self.assertEqual("READY", self.stage("dataset_identity/pre").state)

    def test_runtime_identity_is_authoritative_and_fail_algorithm_is_terminal(self) -> None:
        self.require_module()
        self.pass_setup()
        self.pass_preflights()
        self.pass_identity("pre")
        self.pass_runtime("fast_livo2")

        write_json(
            self.run / "metadata/algorithms/fast_lio2/runtime_identity.json",
            {"schema_version": 1, "algorithm_id": "fast_lio2", "identity_status": "FROZEN"},
        )
        write_json(
            self.run / "metadata/run_fast_lio2.json",
            {"algorithm_id": "fast_lio2", "status": "FAIL_ALGORITHM", "returncode": 1},
        )

        self.assertEqual("PASS", self.stage("runtime/fast_livo2").state)
        failed = self.stage("runtime/fast_lio2")
        self.assertEqual("FAIL", failed.state)
        self.assertEqual("FAIL_ALGORITHM", failed.reason_code)
        self.assertEqual("READY", self.stage("runtime/kiss_icp").state)
        self.assertNotEqual("READY", self.stage("trajectory/fast_lio2").state)

    def test_runtime_identity_without_run_status_fails_closed(self) -> None:
        self.require_module()
        self.pass_setup()
        self.pass_preflights()
        self.pass_identity("pre")
        write_json(
            self.run / "metadata/algorithms/fast_livo2/runtime_identity.json",
            {"schema_version": 1, "algorithm_id": "fast_livo2", "identity_status": "FROZEN"},
        )
        state = self.stage("runtime/fast_livo2")
        self.assertEqual("FAIL", state.state)
        self.assertEqual("FAIL_ARTIFACT_INVALID", state.reason_code)

    def test_partial_trajectory_is_terminal_and_not_reusable(self) -> None:
        self.require_module()
        self.pass_setup()
        self.pass_preflights()
        self.pass_identity("pre")
        self.pass_runtimes()
        self.pass_identity("post")
        path = self.run / "standardized/trajectories/fast_livo2.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("timestamp_s,x_m\n", encoding="utf-8")

        state = self.stage("trajectory/fast_livo2")
        self.assertEqual("FAIL", state.state)
        self.assertEqual("FAIL_PARTIAL_ARTIFACT", state.reason_code)

    def test_audits_preserve_frame_semantics_and_coverage_is_descriptive(self) -> None:
        self.require_module()
        self.pass_through_trajectories()
        self.pass_audits()

        self.assertEqual("PASS", self.stage("audit/trajectory_timestamps").state)
        self.assertEqual("PASS", self.stage("audit/trajectory_frames").state)
        self.assertEqual("PASS", self.stage("audit/runtime_provenance").state)
        self.assertEqual("PASS", self.stage("audit/trajectory_coverage").state)

        rows = (self.run / "metrics/runtime_provenance.csv").read_text(encoding="utf-8")
        self.assertIn("MATCH", rows)
        self.assertEqual("PASS", self.stage("audit/trajectory_coverage").state)

    def test_strict_common_map_stale_evidence_is_detected(self) -> None:
        self.require_module()
        self.pass_through_trajectories()
        common = self.pass_scan_and_common_manifest()
        self.assertTrue(common.is_file())
        self.assertEqual("PASS", self.stage("scan_manifest").state)
        self.assertEqual("PASS", self.stage("common_map_manifest").state)

        trajectory = self.run / "standardized/trajectories/fast_livo2.csv"
        with trajectory.open("a", encoding="utf-8") as stream:
            stream.write("\n")
        state = self.stage("common_map_manifest")
        self.assertEqual("FAIL", state.state)
        self.assertEqual("FAIL_ARTIFACT_STALE", state.reason_code)

    def test_complete_postprocessing_and_canonical_summary_reach_pass(self) -> None:
        self.require_module()
        self.pass_through_trajectories()
        self.pass_audits()
        common = self.pass_scan_and_common_manifest()
        self.pass_unified_maps(common)
        self.pass_relative_se3()
        self.pass_summary()

        for algorithm_id in ALGORITHMS:
            self.assertEqual("PASS", self.stage(f"unified_map/{algorithm_id}").state)
        self.assertEqual("PASS", self.stage("relative_se3").state)
        self.assertEqual("PASS", self.stage("same_bag_summary").state)
        self.assertEqual("PASS", self.require_module().derive_suite_status(self.run).state)

    def test_partial_unified_map_and_relative_se3_fail_closed(self) -> None:
        self.require_module()
        self.pass_through_trajectories()
        self.pass_audits()
        common = self.pass_scan_and_common_manifest()
        paths = map_artifact_paths(self.run, "fast_livo2")
        paths.unified_dir.mkdir(parents=True, exist_ok=True)
        paths.unified_map.write_bytes(b"ply\n")
        state = self.stage("unified_map/fast_livo2")
        self.assertEqual("FAIL", state.state)
        self.assertEqual("FAIL_PARTIAL_ARTIFACT", state.reason_code)

        root = self.run / "metrics/relative_se3"
        write_json(root / "metadata.json", {"requested_algorithms": ALGORITHMS, "terminology": "PAIRWISE_DISAGREEMENT"})
        relative = self.stage("relative_se3")
        self.assertEqual("FAIL", relative.state)
        self.assertEqual("FAIL_PARTIAL_ARTIFACT", relative.reason_code)

    def test_status_is_strictly_read_only(self) -> None:
        module = self.require_module()
        before = sorted((path.relative_to(self.run).as_posix(), path.read_bytes()) for path in self.run.rglob("*") if path.is_file())
        module.derive_suite_status(self.run)
        after = sorted((path.relative_to(self.run).as_posix(), path.read_bytes()) for path in self.run.rglob("*") if path.is_file())
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
