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

    def test_smoke_execution_sources_match_audited_target_machine(self) -> None:
        registry = Registry()
        fast_livo = registry.load_algorithm("fast_livo2")
        livo_impl = fast_livo["execution_implementation"]
        self.assertEqual("Aldoubt/agt_navigation_v2", livo_impl["repository"])
        self.assertEqual("third_party/fast_livo2_ros2", livo_impl["source_subpath"])

        fast_lio = registry.load_algorithm("fast_lio2")
        lio_impl = fast_lio["execution_implementation"]
        self.assertEqual("PolarisXQ/SCURM_SentryNavigation", lio_impl["repository"])
        self.assertEqual("FAST_LIO", lio_impl["source_subpath"])
        contract = fast_lio["trajectory_contract"]
        self.assertEqual(["odom"], contract["expected_parent_frames"])
        self.assertEqual(["sensor"], contract["expected_child_frames"])


if __name__ == "__main__":
    unittest.main()
