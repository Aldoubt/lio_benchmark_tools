from __future__ import annotations

import unittest

from benchmark_base.lib.registry import Registry
from benchmark_base.lib.trajectory_semantics import validate_trajectory_contract


class RegistryTrajectorySemanticsTest(unittest.TestCase):
    def test_three_smoke_baselines_have_source_backed_trajectory_contracts(self) -> None:
        registry = Registry()
        expected = {
            "fast_livo2": ("IMU_BODY", "GRAVITY_ALIGNED"),
            "fast_lio2": ("IMU_BODY", "INITIAL_BODY_ALIGNED"),
            "kiss_icp": ("LIDAR", "INITIAL_LIDAR_ALIGNED"),
        }
        for algorithm_id, (tracked, world) in expected.items():
            contract = registry.load_algorithm(algorithm_id).get("trajectory_contract")
            self.assertIsInstance(contract, dict, algorithm_id)
            validate_trajectory_contract(contract)
            self.assertEqual(tracked, contract["tracked_frame_physical"], algorithm_id)
            self.assertEqual(world, contract["world_gauge"], algorithm_id)
            self.assertTrue(contract.get("evidence"), algorithm_id)

    def test_fast_lio2_keeps_runtime_mismatch_warning(self) -> None:
        contract = Registry().load_algorithm("fast_lio2")["trajectory_contract"]
        self.assertIn("runtime_warning", contract)
        self.assertIn("odom->sensor", contract["runtime_warning"])


if __name__ == "__main__":
    unittest.main()
