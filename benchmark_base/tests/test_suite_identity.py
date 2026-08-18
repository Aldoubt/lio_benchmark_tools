from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from benchmark_base.lib.bag_probe import build_bag_identity
from benchmark_base.lib.suite_plan import build_suite_plan, write_suite_plan
from benchmark_base.tests.suite_test_utils import create_frozen_run


MODULE_NAME = "benchmark_base.lib.suite_orchestrator"


class SuiteDatasetIdentityContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = importlib.util.find_spec(MODULE_NAME)
        cls.module = importlib.import_module(MODULE_NAME) if cls.spec is not None else None

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.run, self.manifest = create_frozen_run(Path(self.tmp.name))
        self.bag = Path(self.manifest["dataset"]["bag_dir"])
        (self.bag / "metadata.yaml").write_text("rosbag2_bagfile_information:\n", encoding="utf-8")
        (self.bag / "part_0.db3").write_bytes(b"first-storage")
        (self.bag / "part_1.db3").write_bytes(b"second-storage")
        self.identity = build_bag_identity(self.bag)
        self.expected = self.identity["bag_content_sha256"]
        self.manifest["dataset"]["sha256"] = self.expected
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

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def require_module(self):
        if self.module is None:
            self.skipTest("suite_orchestrator production module is intentionally absent in RED")
        return self.module

    def test_suite_orchestrator_module_exists_for_identity_gates(self) -> None:
        self.assertIsNotNone(
            self.spec,
            "Benchmark Suite Orchestrator V1 requires benchmark_base.lib.suite_orchestrator",
        )

    def test_pre_identity_captures_exact_p1_bag_fingerprint_once(self) -> None:
        module = self.require_module()
        path = module.capture_dataset_identity(
            self.run,
            self.plan,
            "pre",
            captured_at="2026-08-18T00:00:01+00:00",
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual("lio_benchmark_suite_dataset_identity/v1", payload["schema"])
        self.assertEqual("pre", payload["phase"])
        self.assertEqual("PASS", payload["status"])
        self.assertEqual(self.expected, payload["expected_bag_content_sha256"])
        self.assertEqual(self.expected, payload["observed_bag_content_sha256"])
        self.assertEqual(self.identity["metadata_yaml"], payload["metadata_yaml"])
        self.assertEqual(self.identity["storage_files"], payload["storage_files"])
        self.assertEqual(payload, module.validate_dataset_identity_record(self.run, self.plan, "pre"))

        before = path.read_bytes()
        with self.assertRaises(module.SuiteOrchestratorError):
            module.capture_dataset_identity(self.run, self.plan, "pre")
        self.assertEqual(before, path.read_bytes())

    def test_pre_identity_mismatch_is_preserved_and_fails_before_runtime(self) -> None:
        module = self.require_module()
        (self.bag / "part_0.db3").write_bytes(b"mutated-before-pre")
        with self.assertRaises(module.SuiteOrchestratorError) as ctx:
            module.capture_dataset_identity(
                self.run,
                self.plan,
                "pre",
                captured_at="2026-08-18T00:00:01+00:00",
            )
        self.assertEqual("FAIL_INPUT_MUTATION", ctx.exception.reason_code)
        path = self.run / "metadata/suite/dataset_identity_pre.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual("FAIL", payload["status"])
        self.assertEqual("FAIL_INPUT_MUTATION", payload["reason_code"])
        self.assertNotEqual(self.expected, payload["observed_bag_content_sha256"])
        self.assertFalse(any((self.run / "metadata/algorithms").glob("*/runtime_identity.json")))

    def test_post_identity_requires_expected_and_pre_observed_hash(self) -> None:
        module = self.require_module()
        module.capture_dataset_identity(
            self.run,
            self.plan,
            "pre",
            captured_at="2026-08-18T00:00:01+00:00",
        )
        (self.bag / "part_1.db3").write_bytes(b"mutated-between-pre-and-post")

        with self.assertRaises(module.SuiteOrchestratorError) as ctx:
            module.capture_dataset_identity(
                self.run,
                self.plan,
                "post",
                captured_at="2026-08-18T00:00:02+00:00",
            )
        self.assertEqual("FAIL_INPUT_MUTATION", ctx.exception.reason_code)
        payload = json.loads(
            (self.run / "metadata/suite/dataset_identity_post.json").read_text(encoding="utf-8")
        )
        self.assertEqual("FAIL", payload["status"])
        self.assertEqual(self.expected, payload["pre_observed_bag_content_sha256"])
        self.assertNotEqual(payload["pre_observed_bag_content_sha256"], payload["observed_bag_content_sha256"])

    def test_post_identity_passes_when_bag_is_unchanged(self) -> None:
        module = self.require_module()
        module.capture_dataset_identity(self.run, self.plan, "pre")
        path = module.capture_dataset_identity(self.run, self.plan, "post")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual("PASS", payload["status"])
        self.assertEqual(self.expected, payload["pre_observed_bag_content_sha256"])
        self.assertEqual(self.expected, payload["observed_bag_content_sha256"])
        self.assertEqual(payload, module.validate_dataset_identity_record(self.run, self.plan, "post"))


if __name__ == "__main__":
    unittest.main()
