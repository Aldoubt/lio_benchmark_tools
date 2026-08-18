from __future__ import annotations

import hashlib
import json
from pathlib import Path
import signal
import sys
import tempfile
import unittest

from benchmark_base.lib.artifacts import map_artifact_paths
from benchmark_base.lib.bag_probe import build_bag_identity
from benchmark_base.lib.common_map_manifest import build_common_map_manifest, sha256_file
from benchmark_base.lib.map_sampling import SelectedScan, write_scan_manifest
from benchmark_base.lib.suite_plan import build_suite_plan, write_suite_plan
from benchmark_base.tests.suite_test_utils import (
    ALGORITHMS,
    LIDAR_TOPIC,
    create_frozen_run,
    write_csv,
    write_json,
    write_valid_trajectory,
)
import benchmark_base.lib.suite_orchestrator as orchestrator


REQUIRED_INTERFACES = (
    "StageCommand",
    "OrchestratorResult",
    "StopController",
    "build_stage_command",
    "execute_suite",
)


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeStageRunner:
    def __init__(
        self,
        run: Path,
        *,
        stop_controller=None,
        stop_after_stage: str | None = None,
        fail_runtime: str | None = None,
        block_preflight_once: str | None = None,
        mutate_bag_after_runtime: str | None = None,
    ) -> None:
        self.run = run
        self.stop_controller = stop_controller
        self.stop_after_stage = stop_after_stage
        self.fail_runtime = fail_runtime
        self.block_preflight_once = block_preflight_once
        self.blocked_once = False
        self.mutate_bag_after_runtime = mutate_bag_after_runtime
        self.started: list[str] = []

    def __call__(self, argv) -> int:
        args = list(argv)
        stage_id = self._stage_id(args)
        self.started.append(stage_id)
        self._materialize(stage_id)
        if self.stop_after_stage == stage_id and self.stop_controller is not None:
            self.stop_controller.request(signal.SIGINT)
        return 1 if stage_id == f"runtime/{self.fail_runtime}" else 0

    @staticmethod
    def _algorithm_arg(args: list[str]) -> str:
        return args[args.index("--algorithm") + 1]

    def _stage_id(self, args: list[str]) -> str:
        command = args[2:]
        if command[0] == "snapshot":
            return "snapshot"
        if command[0] == "analyze-bag":
            return "analyze_bag"
        if command[0] == "preflight":
            return f"preflight/{self._algorithm_arg(args)}"
        if command[0] == "run":
            return f"runtime/{self._algorithm_arg(args)}"
        if command[:2] == ["standardize", "trajectory-from-run"]:
            return f"trajectory/{self._algorithm_arg(args)}"
        if command[:2] == ["audit", "trajectory-timestamps"]:
            return "audit/trajectory_timestamps"
        if command[:2] == ["audit", "trajectory-frames"]:
            return "audit/trajectory_frames"
        if command[:2] == ["audit", "runtime-provenance"]:
            return "audit/runtime_provenance"
        if command[:2] == ["audit", "trajectory-coverage"]:
            return "audit/trajectory_coverage"
        if command[:2] == ["standardize", "scan-manifest"]:
            return "scan_manifest"
        if command[:2] == ["standardize", "common-map-manifest"]:
            return "common_map_manifest"
        if command[:2] == ["standardize", "map"]:
            return f"unified_map/{self._algorithm_arg(args)}"
        if command[:2] == ["compare", "relative-se3"]:
            return "relative_se3"
        if command[:2] == ["summarize", "same-bag"]:
            return "same_bag_summary"
        raise AssertionError(f"unexpected fake command: {args}")

    def _materialize(self, stage_id: str) -> None:
        if stage_id == "snapshot":
            write_json(self.run / "metadata/environment_snapshot.json", {"python": "3.10"})
            return
        if stage_id == "analyze_bag":
            write_json(self.run / "metrics/bag_analysis.json", {"schema_version": 1, "topics": {}})
            return
        if stage_id.startswith("preflight/"):
            algorithm_id = stage_id.split("/", 1)[1]
            if self.block_preflight_once == algorithm_id and not self.blocked_once:
                self.blocked_once = True
                payload = {
                    "algorithm_id": algorithm_id,
                    "status": "BLOCKED_ENVIRONMENT",
                    "runnable": False,
                    "reasons": ["temporary missing environment"],
                }
            else:
                payload = {
                    "algorithm_id": algorithm_id,
                    "status": "PASS",
                    "runnable": True,
                    "reasons": [],
                }
            write_json(self.run / "metadata/algorithms" / algorithm_id / "preflight.json", payload)
            return
        if stage_id.startswith("runtime/"):
            algorithm_id = stage_id.split("/", 1)[1]
            write_json(
                self.run / "metadata/algorithms" / algorithm_id / "runtime_identity.json",
                {"schema_version": 1, "algorithm_id": algorithm_id, "identity_status": "FROZEN"},
            )
            status = "FAIL_ALGORITHM" if algorithm_id == self.fail_runtime else "PASS"
            write_json(
                self.run / "metadata" / f"run_{algorithm_id}.json",
                {
                    "algorithm_id": algorithm_id,
                    "status": status,
                    "returncode": 1 if status != "PASS" else 0,
                },
            )
            if status == "PASS":
                write_json(
                    self.run / "metrics/runtime" / f"{algorithm_id}.json",
                    {
                        "algorithm_id": algorithm_id,
                        "measurement_method": "LINUX_PROC_PROCESS_SESSION_V1",
                        "wall_time_s": 1.0,
                        "max_rss_kib": 1024,
                    },
                )
            if self.mutate_bag_after_runtime == algorithm_id:
                bag = Path(json.loads((self.run / "manifest.json").read_text())["dataset"]["bag_dir"])
                (bag / "suite_fixture_0.db3").write_bytes(b"mutated-during-runtime-group")
            return
        if stage_id.startswith("trajectory/"):
            write_valid_trajectory(self.run, stage_id.split("/", 1)[1])
            return
        if stage_id == "audit/trajectory_timestamps":
            for algorithm_id in ALGORITHMS:
                write_csv(
                    self.run / "metrics/trajectory_timestamp_audit" / f"{algorithm_id}.csv",
                    ["index", "effective_relation"],
                    [{"index": 0, "effective_relation": "FIRST"}],
                )
                write_json(
                    self.run / "metadata/trajectory_timestamp_audit" / f"{algorithm_id}.json",
                    {
                        "algorithm_id": algorithm_id,
                        "summary": {
                            "classification": "PASS",
                            "sample_count": 1,
                            "effective_regression_count": 0,
                        },
                    },
                )
            return
        if stage_id == "audit/trajectory_frames":
            for algorithm_id in ALGORITHMS:
                write_json(
                    self.run / "metadata/frame_audit" / f"{algorithm_id}.json",
                    {"algorithm_id": algorithm_id, "status": "AVAILABLE"},
                )
            write_csv(
                self.run / "metrics/trajectory_frame_audit.csv",
                ["algorithm_id", "status"],
                [{"algorithm_id": algorithm_id, "status": "AVAILABLE"} for algorithm_id in ALGORITHMS],
            )
            return
        if stage_id == "audit/runtime_provenance":
            fields = [
                "algorithm_id",
                "status",
                "frame_contract_status",
                "identity_evidence_source",
                "runtime_identity_status",
            ]
            rows = []
            for algorithm_id in ALGORITHMS:
                row = {
                    "algorithm_id": algorithm_id,
                    "status": "MATCH",
                    "frame_contract_status": "MATCH",
                    "identity_evidence_source": "RUNTIME_IDENTITY",
                    "runtime_identity_status": "FROZEN",
                }
                rows.append(row)
                write_json(self.run / "metadata/runtime_provenance" / f"{algorithm_id}.json", row)
            write_csv(self.run / "metrics/runtime_provenance.csv", fields, rows)
            return
        if stage_id == "audit/trajectory_coverage":
            rows = []
            for algorithm_id in ALGORITHMS:
                row = {
                    "algorithm_id": algorithm_id,
                    "trajectory_count": 1,
                    "trajectory_large_gap_count": 500,
                }
                rows.append(row)
                write_json(self.run / "metadata/trajectory_coverage" / f"{algorithm_id}.json", row)
            write_csv(
                self.run / "metrics/trajectory_coverage.csv",
                ["algorithm_id", "trajectory_count", "trajectory_large_gap_count"],
                rows,
            )
            return
        if stage_id == "scan_manifest":
            root = self.run / "standardized/map_sampling"
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
            selected = root / "selected_scans.csv"
            write_scan_manifest(selected, rows)
            write_json(
                root / "metadata.json",
                {
                    "schema_version": 3,
                    "lidar_topic": LIDAR_TOPIC,
                    "selected_scan_count": len(rows),
                    "manifest": str(selected),
                },
            )
            return
        if stage_id == "common_map_manifest":
            build_common_map_manifest(self.run)
            return
        if stage_id.startswith("unified_map/"):
            algorithm_id = stage_id.split("/", 1)[1]
            common = self.run / "standardized/map_sampling/common_matched_scans.csv"
            paths = map_artifact_paths(self.run, algorithm_id)
            paths.unified_dir.mkdir(parents=True, exist_ok=True)
            paths.unified_map.write_bytes(b"ply\n")
            metadata = {
                "schema": "lio_benchmark_map/v3",
                "algorithm_id": algorithm_id,
                "map_source": "UNIFIED_RECONSTRUCTION",
                "point_count": 10,
                "scan_set_policy": "STRICT_COMMON_INTERSECTION",
                "common_manifest_sha256": sha256_file(common),
                "timestamp_matching": {
                    "selected_scan_count": 4,
                    "matched_scan_count": 4,
                    "unmatched_scan_count": 0,
                },
            }
            write_json(paths.unified_metadata, metadata)
            paths.compat_unified_map.write_bytes(paths.unified_map.read_bytes())
            write_json(paths.compat_unified_metadata, metadata)
            return
        if stage_id == "relative_se3":
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
            return
        if stage_id == "same_bag_summary":
            write_csv(
                self.run / "reports/algorithm_io_matrix.csv",
                ["algorithm_id"],
                [{"algorithm_id": a} for a in ALGORITHMS],
            )
            (self.run / "reports/algorithm_io_matrix.md").write_text("# matrix\n", encoding="utf-8")
            write_csv(
                self.run / "metrics/runtime_performance.csv",
                ["algorithm_id"],
                [{"algorithm_id": a} for a in ALGORITHMS],
            )
            write_json(
                self.run / "reports/same_bag_mapping_v1.json",
                {
                    "schema": "lio_benchmark_same_bag_mapping/v1",
                    "artifact_role": "CANONICAL_FINAL_SUMMARY",
                    "algorithms": [{"algorithm_id": a} for a in ALGORITHMS],
                },
            )
            return
        raise AssertionError(f"no fake artifact materializer for {stage_id}")


class SuiteOrchestratorContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.run, self.manifest = create_frozen_run(Path(self.tmp.name))
        bag = Path(self.manifest["dataset"]["bag_dir"])
        (bag / "metadata.yaml").write_text("rosbag2_bagfile_information:\n", encoding="utf-8")
        (bag / "suite_fixture_0.db3").write_bytes(b"stable-suite-bag")
        self.manifest["dataset"]["sha256"] = build_bag_identity(bag)["bag_content_sha256"]
        (self.run / "manifest.json").write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.plan = build_suite_plan(
            self.run,
            self.manifest,
            created_at="2026-08-18T00:00:00+00:00",
        )
        write_suite_plan(self.run, self.plan)
        self.cli = Path("/repo/benchmark_base/bin/lio-benchmark")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def require_interfaces(self) -> None:
        missing = [name for name in REQUIRED_INTERFACES if not hasattr(orchestrator, name)]
        if missing:
            self.skipTest(f"orchestrator execution interfaces intentionally absent in RED: {missing}")

    def test_orchestrator_execution_interfaces_exist(self) -> None:
        missing = [name for name in REQUIRED_INTERFACES if not hasattr(orchestrator, name)]
        self.assertEqual([], missing, f"missing P2 orchestrator interfaces: {missing}")

    def test_stage_commands_use_existing_public_cli_without_overrides(self) -> None:
        self.require_interfaces()
        runtime = orchestrator.build_stage_command(
            self.run,
            self.plan,
            "runtime/fast_livo2",
            self.cli,
        )
        self.assertEqual(
            (
                sys.executable,
                str(self.cli),
                "run",
                "--run",
                str(self.run),
                "--algorithm",
                "fast_livo2",
            ),
            runtime.argv,
        )
        relative = orchestrator.build_stage_command(
            self.run,
            self.plan,
            "relative_se3",
            self.cli,
        )
        self.assertEqual(
            (
                sys.executable,
                str(self.cli),
                "compare",
                "relative-se3",
                "--run",
                str(self.run),
                "--algorithms",
                *ALGORITHMS,
            ),
            relative.argv,
        )
        for stage in self.plan["stages"]:
            command = orchestrator.build_stage_command(
                self.run,
                self.plan,
                stage["stage_id"],
                self.cli,
            )
            if command is None:
                continue
            joined = " ".join(command.argv)
            for forbidden in ("--overwrite", "--allow-diagnostic-calibration", "--parallel"):
                self.assertNotIn(forbidden, joined)

    def test_stage_boundary_interrupt_then_resume_never_reruns_fast_livo2(self) -> None:
        self.require_interfaces()
        stop = orchestrator.StopController()
        runner = FakeStageRunner(
            self.run,
            stop_controller=stop,
            stop_after_stage="runtime/fast_livo2",
        )
        first = orchestrator.execute_suite(
            self.run,
            cli_path=self.cli,
            command_runner=runner,
            install_signal_handlers=False,
            stop_controller=stop,
        )
        self.assertEqual(130, first.exit_code)
        self.assertIn("runtime/fast_livo2", runner.started)
        self.assertNotIn("runtime/fast_lio2", runner.started)
        identity = self.run / "metadata/algorithms/fast_livo2/runtime_identity.json"
        status = self.run / "metadata/run_fast_livo2.json"
        identity_sha = file_sha(identity)
        status_sha = file_sha(status)
        before = list(runner.started)

        second = orchestrator.execute_suite(
            self.run,
            cli_path=self.cli,
            command_runner=runner,
            install_signal_handlers=False,
            stop_controller=orchestrator.StopController(),
        )
        self.assertEqual("PASS", second.state)
        self.assertEqual(0, second.exit_code)
        resume_started = runner.started[len(before):]
        self.assertNotIn("runtime/fast_livo2", resume_started)
        self.assertIn("runtime/fast_lio2", resume_started)
        self.assertIn("runtime/kiss_icp", resume_started)
        self.assertEqual(identity_sha, file_sha(identity))
        self.assertEqual(status_sha, file_sha(status))

        before_noop = list(runner.started)
        third = orchestrator.execute_suite(
            self.run,
            cli_path=self.cli,
            command_runner=runner,
            install_signal_handlers=False,
            stop_controller=orchestrator.StopController(),
        )
        self.assertEqual("PASS", third.state)
        self.assertEqual(before_noop, runner.started)

    def test_fail_algorithm_continues_independent_runtime_but_blocks_all_postprocessing(self) -> None:
        self.require_interfaces()
        runner = FakeStageRunner(self.run, fail_runtime="fast_lio2")
        result = orchestrator.execute_suite(
            self.run,
            cli_path=self.cli,
            command_runner=runner,
            install_signal_handlers=False,
        )
        self.assertEqual("FAIL", result.state)
        self.assertIn("runtime/fast_livo2", runner.started)
        self.assertIn("runtime/fast_lio2", runner.started)
        self.assertIn("runtime/kiss_icp", runner.started)
        self.assertFalse(any(stage.startswith("trajectory/") for stage in runner.started))
        self.assertTrue((self.run / "metadata/suite/dataset_identity_post.json").is_file())

    def test_blocked_preflight_allows_other_runtimes_and_resume_only_missing_runtime(self) -> None:
        self.require_interfaces()
        runner = FakeStageRunner(self.run, block_preflight_once="fast_lio2")
        first = orchestrator.execute_suite(
            self.run,
            cli_path=self.cli,
            command_runner=runner,
            install_signal_handlers=False,
        )
        self.assertEqual("BLOCKED", first.state)
        self.assertIn("runtime/fast_livo2", runner.started)
        self.assertNotIn("runtime/fast_lio2", runner.started)
        self.assertIn("runtime/kiss_icp", runner.started)
        before = list(runner.started)

        second = orchestrator.execute_suite(
            self.run,
            cli_path=self.cli,
            command_runner=runner,
            install_signal_handlers=False,
        )
        self.assertEqual("PASS", second.state)
        resume_started = runner.started[len(before):]
        self.assertIn("preflight/fast_lio2", resume_started)
        self.assertIn("runtime/fast_lio2", resume_started)
        self.assertNotIn("runtime/fast_livo2", resume_started)
        self.assertNotIn("runtime/kiss_icp", resume_started)

    def test_pre_identity_mutation_starts_zero_estimators(self) -> None:
        self.require_interfaces()
        bag = Path(self.manifest["dataset"]["bag_dir"])
        (bag / "suite_fixture_0.db3").write_bytes(b"mutated-before-suite")
        runner = FakeStageRunner(self.run)
        result = orchestrator.execute_suite(
            self.run,
            cli_path=self.cli,
            command_runner=runner,
            install_signal_handlers=False,
        )
        self.assertEqual("FAIL", result.state)
        self.assertFalse(any(stage.startswith("runtime/") for stage in runner.started))
        payload = json.loads((self.run / "metadata/suite/dataset_identity_pre.json").read_text())
        self.assertEqual("FAIL", payload["status"])

    def test_post_identity_mutation_blocks_all_trajectory_and_comparison_work(self) -> None:
        self.require_interfaces()
        runner = FakeStageRunner(self.run, mutate_bag_after_runtime="kiss_icp")
        result = orchestrator.execute_suite(
            self.run,
            cli_path=self.cli,
            command_runner=runner,
            install_signal_handlers=False,
        )
        self.assertEqual("FAIL", result.state)
        self.assertTrue(all(f"runtime/{algorithm_id}" in runner.started for algorithm_id in ALGORITHMS))
        self.assertFalse(any(stage.startswith("trajectory/") for stage in runner.started))
        payload = json.loads((self.run / "metadata/suite/dataset_identity_post.json").read_text())
        self.assertEqual("FAIL", payload["status"])

    def test_partial_existing_unified_map_is_never_overwritten_by_orchestrator(self) -> None:
        self.require_interfaces()
        paths = map_artifact_paths(self.run, "fast_livo2")
        paths.unified_dir.mkdir(parents=True, exist_ok=True)
        paths.unified_map.write_bytes(b"historical-partial-map")
        before = paths.unified_map.read_bytes()
        runner = FakeStageRunner(self.run)
        result = orchestrator.execute_suite(
            self.run,
            cli_path=self.cli,
            command_runner=runner,
            install_signal_handlers=False,
        )
        self.assertEqual("FAIL", result.state)
        self.assertNotIn("unified_map/fast_livo2", runner.started)
        self.assertEqual(before, paths.unified_map.read_bytes())


if __name__ == "__main__":
    unittest.main()
