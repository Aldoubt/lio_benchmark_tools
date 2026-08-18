from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from benchmark_base.lib.suite_plan import build_suite_plan, write_suite_plan
from benchmark_base.lib.suite_status import derive_suite_status
from benchmark_base.tests.suite_test_utils import ALGORITHMS, create_frozen_run, write_csv, write_json, write_valid_trajectory


class SuiteTimestampGateTest(unittest.TestCase):
    def test_effective_timestamp_regression_is_not_a_pass_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run, manifest = create_frozen_run(Path(tmp))
            plan = build_suite_plan(run, manifest, created_at="2026-08-18T00:00:00+00:00")
            write_suite_plan(run, plan)

            write_json(run / "metadata/environment_snapshot.json", {"python": "3.10"})
            write_json(run / "metrics/bag_analysis.json", {"schema_version": 1})
            for algorithm_id in ALGORITHMS:
                write_json(
                    run / "metadata/algorithms" / algorithm_id / "preflight.json",
                    {"algorithm_id": algorithm_id, "status": "PASS", "runnable": True},
                )
            write_json(
                run / "metadata/suite/dataset_identity_pre.json",
                {
                    "schema": "lio_benchmark_suite_dataset_identity/v1",
                    "phase": "pre",
                    "status": "PASS",
                    "expected_bag_content_sha256": "a" * 64,
                    "observed_bag_content_sha256": "a" * 64,
                },
            )
            for algorithm_id in ALGORITHMS:
                write_json(
                    run / "metadata/algorithms" / algorithm_id / "runtime_identity.json",
                    {"algorithm_id": algorithm_id, "identity_status": "FROZEN"},
                )
                write_json(
                    run / "metadata" / f"run_{algorithm_id}.json",
                    {"algorithm_id": algorithm_id, "status": "PASS"},
                )
                write_json(
                    run / "metrics/runtime" / f"{algorithm_id}.json",
                    {
                        "algorithm_id": algorithm_id,
                        "measurement_method": "LINUX_PROC_PROCESS_SESSION_V1",
                        "wall_time_s": 1.0,
                        "max_rss_kib": 1024,
                    },
                )
            write_json(
                run / "metadata/suite/dataset_identity_post.json",
                {
                    "schema": "lio_benchmark_suite_dataset_identity/v1",
                    "phase": "post",
                    "status": "PASS",
                    "expected_bag_content_sha256": "a" * 64,
                    "observed_bag_content_sha256": "a" * 64,
                },
            )
            for algorithm_id in ALGORITHMS:
                write_valid_trajectory(run, algorithm_id)
                write_csv(
                    run / "metrics/trajectory_timestamp_audit" / f"{algorithm_id}.csv",
                    ["index", "effective_relation"],
                    [{"index": 0, "effective_relation": "FIRST"}],
                )
                write_json(
                    run / "metadata/trajectory_timestamp_audit" / f"{algorithm_id}.json",
                    {
                        "algorithm_id": algorithm_id,
                        "summary": {
                            "classification": "PASS",
                            "sample_count": 1,
                            "effective_regression_count": 0,
                        },
                    },
                )

            write_json(
                run / "metadata/trajectory_timestamp_audit/fast_lio2.json",
                {
                    "algorithm_id": "fast_lio2",
                    "summary": {
                        "classification": "HEADER_REGRESSION",
                        "sample_count": 2,
                        "effective_regression_count": 1,
                    },
                },
            )

            status = derive_suite_status(run)
            stage = next(row for row in status.stages if row.stage_id == "audit/trajectory_timestamps")
            self.assertEqual("FAIL", stage.state)
            self.assertEqual("FAIL_ARTIFACT_INVALID", stage.reason_code)
            self.assertIn("regression", (stage.detail or "").lower())


if __name__ == "__main__":
    unittest.main()
