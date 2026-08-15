from __future__ import annotations

import unittest

from benchmark_base.lib.algorithm_roles import primary_evaluation_role


class AlgorithmRoleTest(unittest.TestCase):
    def test_single_system_mapping_role_is_preserved(self) -> None:
        self.assertEqual(
            "SYSTEM_MAPPING",
            primary_evaluation_role({"evaluation_roles": ["SYSTEM_MAPPING"]}),
        )

    def test_multi_role_algorithm_uses_declared_primary_order(self) -> None:
        self.assertEqual(
            "ODOMETRY",
            primary_evaluation_role({"evaluation_roles": ["ODOMETRY", "SYSTEM_MAPPING"]}),
        )

    def test_missing_role_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            primary_evaluation_role({"evaluation_roles": []})


if __name__ == "__main__":
    unittest.main()
