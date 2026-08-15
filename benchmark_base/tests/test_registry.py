from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmark_base.lib.registry import FIXED_BASELINES, Registry, RegistryError, validate_fixed_baselines


CORE_BASELINES = {
    "fast_livo2",
    "fast_lio2",
    "point_lio",
    "dlio",
    "lio_sam",
    "glim_odometry",
    "glim_full_slam",
    "leg_kilo",
    "kiss_icp",
}
RESEARCH_BASELINES = {"faster_lio", "slict"}
LEGACY_BASELINES = {"leg_kilo2_lidar_imu"}


class RegistryTest(unittest.TestCase):
    def test_tracked_fixed_baselines_are_valid(self) -> None:
        registry = Registry()
        self.assertTrue(set(FIXED_BASELINES).issubset(set(registry.list_algorithms())))
        validate_fixed_baselines(registry)
        for algorithm_id in FIXED_BASELINES:
            record = registry.load_algorithm(algorithm_id)
            self.assertEqual(algorithm_id, record["algorithm_id"])

    def test_baseline_suite_records_expose_family_tier_roles_and_sensor_profile(self) -> None:
        registry = Registry()
        expected = CORE_BASELINES | RESEARCH_BASELINES | LEGACY_BASELINES
        self.assertTrue(expected.issubset(set(registry.list_algorithms())))
        for algorithm_id in expected:
            record = registry.load_algorithm(algorithm_id)
            self.assertIn(record["tier"], {"CORE", "RESEARCH", "LEGACY"})
            self.assertTrue(record["family_id"])
            self.assertTrue(record["family"])
            self.assertTrue(record["evaluation_roles"])
            self.assertIsInstance(record["sensor_profile"], dict)
            self.assertIn("lidar", record["sensor_profile"])
            self.assertIn(record["adapter_status"], {"PASS", "FAIL_IMPLEMENTATION", "FAIL_ALGORITHM", "BLOCKED_ENVIRONMENT", "BLOCKED_DEPENDENCY", "BLOCKED_INPUT", "BLOCKED_CALIBRATION", "NOT_TESTED"})

    def test_baseline_suite_tiers_are_stable(self) -> None:
        registry = Registry()
        for algorithm_id in CORE_BASELINES:
            self.assertEqual("CORE", registry.load_algorithm(algorithm_id)["tier"])
        for algorithm_id in RESEARCH_BASELINES:
            self.assertEqual("RESEARCH", registry.load_algorithm(algorithm_id)["tier"])
        for algorithm_id in LEGACY_BASELINES:
            self.assertEqual("LEGACY", registry.load_algorithm(algorithm_id)["tier"])

    def test_research_baselines_declare_environment_and_runner_contracts(self) -> None:
        registry = Registry()
        repo_root = Path(__file__).resolve().parents[2]
        for algorithm_id in RESEARCH_BASELINES:
            record = registry.load_algorithm(algorithm_id)
            requirements = record.get("environment_requirements", {})
            self.assertTrue(requirements.get("ros_distros"), algorithm_id)
            runner = record.get("runner", {}).get("adapter")
            self.assertTrue(runner, algorithm_id)
            self.assertTrue((repo_root / runner).is_file(), f"{algorithm_id}: {runner}")

    def test_current_leg_kilo_is_distinct_from_historical_v2(self) -> None:
        registry = Registry()
        current = registry.load_algorithm("leg_kilo")
        historical = registry.load_algorithm("leg_kilo2_lidar_imu")
        self.assertEqual("master", current["source"]["branch"])
        self.assertNotEqual(current["algorithm_generation"], historical["algorithm_generation"])
        self.assertEqual("leg_kilo", current["family_id"])

    def test_glim_runnable_ids_share_one_family_but_different_roles(self) -> None:
        registry = Registry()
        odom = registry.load_algorithm("glim_odometry")
        full = registry.load_algorithm("glim_full_slam")
        self.assertEqual("glim", odom["family_id"])
        self.assertEqual("glim", full["family_id"])
        self.assertIn("ODOMETRY", odom["evaluation_roles"])
        self.assertIn("SYSTEM_MAPPING", full["evaluation_roles"])

    def test_example_dataset_is_valid(self) -> None:
        record = Registry().load_dataset("example_mid360")
        self.assertTrue(record["portable_example"])
        self.assertEqual("/livox/lidar", record["topics"]["lidar"])

    def test_unknown_record_fails_closed(self) -> None:
        with self.assertRaises(RegistryError):
            Registry().load_algorithm("not_a_real_algorithm")

    def test_record_id_must_match_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "algorithms").mkdir(); (root / "datasets").mkdir()
            record = Registry().load_algorithm("fast_livo2")
            record["algorithm_id"] = "wrong_id"
            (root / "algorithms" / "fast_livo2.json").write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(RegistryError, "algorithm_id mismatch"):
                Registry(root).load_algorithm("fast_livo2")

    def test_malformed_json_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "algorithms").mkdir(); (root / "datasets").mkdir()
            (root / "algorithms" / "broken.json").write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(RegistryError, "invalid JSON"):
                Registry(root).load_algorithm("broken")


if __name__ == "__main__":
    unittest.main()
