from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from benchmark_base.lib.manifest import sha256_file
from benchmark_base.tests.suite_test_utils import ALGORITHMS, DATASET_SHA, create_frozen_run


MODULE_NAME = "benchmark_base.lib.suite_plan"
EXPECTED_STAGE_IDS = [
    "snapshot",
    "analyze_bag",
    "preflight/fast_livo2",
    "preflight/fast_lio2",
    "preflight/kiss_icp",
    "dataset_identity/pre",
    "runtime/fast_livo2",
    "runtime/fast_lio2",
    "runtime/kiss_icp",
    "dataset_identity/post",
    "trajectory/fast_livo2",
    "trajectory/fast_lio2",
    "trajectory/kiss_icp",
    "audit/trajectory_timestamps",
    "audit/trajectory_frames",
    "audit/runtime_provenance",
    "audit/trajectory_coverage",
    "scan_manifest",
    "common_map_manifest",
    "unified_map/fast_livo2",
    "unified_map/fast_lio2",
    "unified_map/kiss_icp",
    "relative_se3",
    "same_bag_summary",
]


class SuitePlanContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = importlib.util.find_spec(MODULE_NAME)
        cls.module = importlib.import_module(MODULE_NAME) if cls.spec is not None else None

    def require_module(self):
        if self.module is None:
            self.skipTest("suite_plan production module is intentionally absent in RED")
        return self.module

    def test_suite_plan_module_exists(self) -> None:
        self.assertIsNotNone(
            self.spec,
            "Benchmark Suite Orchestrator V1 requires benchmark_base.lib.suite_plan",
        )

    def test_stage_ids_and_dependencies_are_frozen(self) -> None:
        module = self.require_module()
        stages = module.build_stage_definitions(ALGORITHMS)
        self.assertEqual(EXPECTED_STAGE_IDS, [stage.stage_id for stage in stages])
        self.assertEqual(list(range(1, len(stages) + 1)), [stage.priority for stage in stages])

        by_id = {stage.stage_id: stage for stage in stages}
        self.assertEqual(
            ("dataset_identity/pre", "preflight/fast_lio2"),
            by_id["runtime/fast_lio2"].dependencies,
        )
        self.assertEqual(
            module.SINGLE_RUNTIME_ATTEMPT,
            by_id["runtime/fast_lio2"].recovery_policy,
        )
        self.assertEqual(
            ("snapshot", "analyze_bag"),
            by_id["dataset_identity/pre"].dependencies,
        )
        self.assertEqual(
            tuple(f"trajectory/{algorithm_id}" for algorithm_id in ALGORITHMS),
            by_id["audit/trajectory_timestamps"].dependencies,
        )
        expected_summary_dependencies = (
            tuple(f"runtime/{algorithm_id}" for algorithm_id in ALGORITHMS)
            + tuple(f"trajectory/{algorithm_id}" for algorithm_id in ALGORITHMS)
            + tuple(f"unified_map/{algorithm_id}" for algorithm_id in ALGORITHMS)
            + (
                "relative_se3",
                "audit/trajectory_timestamps",
                "audit/trajectory_frames",
                "audit/runtime_provenance",
                "audit/trajectory_coverage",
            )
        )
        self.assertEqual(
            expected_summary_dependencies,
            by_id["same_bag_summary"].dependencies,
        )

    def test_plan_freezes_manifest_dataset_and_algorithm_order(self) -> None:
        module = self.require_module()
        with tempfile.TemporaryDirectory() as tmp:
            run, manifest = create_frozen_run(Path(tmp))
            plan = module.build_suite_plan(
                run,
                manifest,
                created_at="2026-08-18T00:00:00+00:00",
            )

            self.assertEqual("lio_benchmark_suite_plan/v1", plan["schema"])
            self.assertEqual("SAME_BAG_MAPPING_V1", plan["profile"])
            self.assertEqual(ALGORITHMS, plan["selected_algorithms"])
            self.assertEqual(sha256_file(run / "manifest.json"), plan["manifest_sha256"])
            self.assertEqual(DATASET_SHA, plan["dataset"]["expected_bag_content_sha256"])
            self.assertEqual(str(run.resolve()), plan["run_dir"])
            self.assertEqual(str((run / "manifest.json").resolve()), plan["manifest_path"])
            self.assertEqual(
                EXPECTED_STAGE_IDS,
                [stage["stage_id"] for stage in plan["stages"]],
            )

    def test_missing_or_malformed_dataset_identity_is_rejected(self) -> None:
        module = self.require_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run, manifest = create_frozen_run(root, dataset_sha=None)
            with self.assertRaises(module.SuitePlanError) as ctx:
                module.build_suite_plan(run, manifest)
            self.assertIn("BLOCKED_INPUT_IDENTITY_UNAVAILABLE", str(ctx.exception))

        with tempfile.TemporaryDirectory() as tmp:
            run, manifest = create_frozen_run(Path(tmp), dataset_sha="not-a-sha")
            with self.assertRaises(module.SuitePlanError) as ctx:
                module.build_suite_plan(run, manifest)
            self.assertIn("BLOCKED_INPUT_IDENTITY_UNAVAILABLE", str(ctx.exception))

    def test_plan_is_write_once_and_manifest_mutation_fails_closed(self) -> None:
        module = self.require_module()
        with tempfile.TemporaryDirectory() as tmp:
            run, manifest = create_frozen_run(Path(tmp))
            plan = module.build_suite_plan(run, manifest, created_at="2026-08-18T00:00:00+00:00")
            path = module.write_suite_plan(run, plan)
            self.assertEqual(run / "metadata/suite/plan.json", path)
            self.assertEqual(plan, module.load_and_validate_suite_plan(run))

            with self.assertRaises((FileExistsError, module.SuitePlanError)):
                module.write_suite_plan(run, plan)

            manifest["name"] = "mutated_after_plan"
            (run / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(module.SuitePlanError) as ctx:
                module.validate_manifest_fingerprint(run, plan)
            self.assertIn("FAIL_MANIFEST_MUTATION", str(ctx.exception))

    def test_plan_schema_validation_rejects_algorithm_order_drift(self) -> None:
        module = self.require_module()
        with tempfile.TemporaryDirectory() as tmp:
            run, manifest = create_frozen_run(Path(tmp))
            plan = module.build_suite_plan(run, manifest, created_at="2026-08-18T00:00:00+00:00")
            plan["selected_algorithms"] = list(reversed(ALGORITHMS))
            with self.assertRaises(module.SuitePlanError):
                module.validate_suite_plan_payload(plan)


if __name__ == "__main__":
    unittest.main()
