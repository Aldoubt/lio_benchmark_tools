from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from benchmark_base.lib.suite_plan import build_suite_plan, write_suite_plan
from benchmark_base.lib.suite_status import derive_suite_status
from benchmark_base.tests.suite_test_utils import create_frozen_run, write_json


class SuiteIdentityStatusGateTest(unittest.TestCase):
    def test_pre_identity_pass_must_match_plan_expected_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run, manifest = create_frozen_run(Path(tmp))
            plan = build_suite_plan(run, manifest, created_at="2026-08-18T00:00:00+00:00")
            write_suite_plan(run, plan)
            write_json(run / "metadata/environment_snapshot.json", {"python": "3.10"})
            write_json(run / "metrics/bag_analysis.json", {"schema_version": 1})
            write_json(
                run / "metadata/suite/dataset_identity_pre.json",
                {
                    "schema": "lio_benchmark_suite_dataset_identity/v1",
                    "phase": "pre",
                    "status": "PASS",
                    "expected_bag_content_sha256": "b" * 64,
                    "observed_bag_content_sha256": "b" * 64,
                },
            )

            status = derive_suite_status(run)
            stage = next(row for row in status.stages if row.stage_id == "dataset_identity/pre")
            self.assertEqual("FAIL", stage.state)
            self.assertEqual("FAIL_ARTIFACT_INVALID", stage.reason_code)
            self.assertIn("plan", (stage.detail or "").lower())

    def test_post_identity_pass_must_match_pre_observed_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run, manifest = create_frozen_run(Path(tmp))
            plan = build_suite_plan(run, manifest, created_at="2026-08-18T00:00:00+00:00")
            write_suite_plan(run, plan)
            write_json(run / "metadata/environment_snapshot.json", {"python": "3.10"})
            write_json(run / "metrics/bag_analysis.json", {"schema_version": 1})
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
            write_json(
                run / "metadata/suite/dataset_identity_post.json",
                {
                    "schema": "lio_benchmark_suite_dataset_identity/v1",
                    "phase": "post",
                    "status": "PASS",
                    "expected_bag_content_sha256": "a" * 64,
                    "observed_bag_content_sha256": "a" * 64,
                    "pre_observed_bag_content_sha256": "b" * 64,
                },
            )

            status = derive_suite_status(run)
            stage = next(row for row in status.stages if row.stage_id == "dataset_identity/post")
            self.assertEqual("FAIL", stage.state)
            self.assertEqual("FAIL_ARTIFACT_INVALID", stage.reason_code)
            self.assertIn("pre", (stage.detail or "").lower())


if __name__ == "__main__":
    unittest.main()
