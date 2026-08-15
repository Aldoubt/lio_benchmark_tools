from __future__ import annotations

import copy
import unittest

from benchmark_base.lib.registry import Registry
from benchmark_base.lib.scoreboards import (
    COMMON_LIO,
    CONTROL_EXTENSION,
    SYSTEM_MAPPING,
    eligible_scoreboards,
    group_manifest_algorithms,
)


class ScoreboardContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = Registry()

    def test_kiss_icp_is_control_not_common_lio(self) -> None:
        boards = eligible_scoreboards(self.registry.load_algorithm("kiss_icp"))
        self.assertIn(CONTROL_EXTENSION, boards)
        self.assertNotIn(COMMON_LIO, boards)

    def test_fast_lio2_is_common_lio(self) -> None:
        boards = eligible_scoreboards(self.registry.load_algorithm("fast_lio2"))
        self.assertIn(COMMON_LIO, boards)
        self.assertNotIn(CONTROL_EXTENSION, boards)

    def test_visual_fast_livo2_profile_is_not_mixed_into_common_lio(self) -> None:
        record = copy.deepcopy(self.registry.load_algorithm("fast_livo2"))
        record["sensor_profile"]["camera"] = True
        boards = eligible_scoreboards(record)
        self.assertNotIn(COMMON_LIO, boards)
        self.assertIn(CONTROL_EXTENSION, boards)

    def test_glim_full_slam_is_system_mapping_only(self) -> None:
        boards = eligible_scoreboards(self.registry.load_algorithm("glim_full_slam"))
        self.assertIn(SYSTEM_MAPPING, boards)
        self.assertNotIn(COMMON_LIO, boards)

    def test_leg_kilo_can_contribute_frontend_and_backend_roles(self) -> None:
        boards = eligible_scoreboards(self.registry.load_algorithm("leg_kilo"))
        self.assertIn(COMMON_LIO, boards)
        self.assertIn(SYSTEM_MAPPING, boards)

    def test_group_manifest_keeps_missing_or_blocked_algorithms_visible(self) -> None:
        algorithms = {
            algorithm_id: self.registry.load_algorithm(algorithm_id)
            for algorithm_id in ("fast_lio2", "kiss_icp", "glim_full_slam")
        }
        grouped = group_manifest_algorithms({"algorithms": algorithms})
        self.assertEqual(["fast_lio2"], grouped[COMMON_LIO])
        self.assertEqual(["glim_full_slam"], grouped[SYSTEM_MAPPING])
        self.assertEqual(["kiss_icp"], grouped[CONTROL_EXTENSION])


if __name__ == "__main__":
    unittest.main()
