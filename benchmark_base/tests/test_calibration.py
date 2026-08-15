from __future__ import annotations

import math
import unittest

from benchmark_base.lib.calibration import (
    RigidTransform,
    invert_transform,
    resolve_algorithm_extrinsic,
)


class CalibrationContractTest(unittest.TestCase):
    def test_inverse_identity_is_identity(self) -> None:
        transform = RigidTransform(
            rotation=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
            translation=(0.0, 0.0, 0.0),
        )
        self.assertEqual(transform, invert_transform(transform))

    def test_inverse_nontrivial_transform_matches_r_transpose_rule(self) -> None:
        # Lidar -> IMU: +90 deg yaw and translation [1, 2, 3].
        transform = RigidTransform(
            rotation=(0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0),
            translation=(1.0, 2.0, 3.0),
        )
        inverse = invert_transform(transform)
        self.assertEqual(
            (0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 1.0),
            tuple(round(value, 12) for value in inverse.rotation),
        )
        # -R^T t = [-2, 1, -3]
        self.assertEqual((-2.0, 1.0, -3.0), tuple(round(value, 12) for value in inverse.translation))

    def test_resolve_preserves_canonical_lidar_to_imu(self) -> None:
        dataset = self._dataset(status="CONFIRMED")
        algorithm = {"algorithm_id": "x", "extrinsic_convention": "LIDAR_TO_IMU"}
        result = resolve_algorithm_extrinsic(dataset, algorithm)
        self.assertEqual("LIDAR_TO_IMU", result["convention"])
        self.assertEqual(dataset["calibration"]["translation_lidar_to_imu_m"], result["translation_m"])
        self.assertEqual("CONFIRMED", result["calibration_status"])
        self.assertFalse(result["diagnostic_only"])

    def test_resolve_inverts_for_imu_to_lidar(self) -> None:
        dataset = self._dataset(status="CONFIRMED")
        algorithm = {"algorithm_id": "x", "extrinsic_convention": "IMU_TO_LIDAR"}
        result = resolve_algorithm_extrinsic(dataset, algorithm)
        self.assertEqual("IMU_TO_LIDAR", result["convention"])
        self.assertEqual((-2.0, 1.0, -3.0), tuple(round(value, 12) for value in result["translation_m"]))

    def test_none_convention_does_not_require_calibration(self) -> None:
        dataset = {"dataset_id": "lidar_only", "calibration": {"status": "BLOCKED_CALIBRATION"}}
        algorithm = {"algorithm_id": "kiss_icp", "extrinsic_convention": "NONE"}
        result = resolve_algorithm_extrinsic(dataset, algorithm)
        self.assertEqual("NONE", result["convention"])
        self.assertIsNone(result["rotation_row_major"])
        self.assertIsNone(result["translation_m"])
        self.assertFalse(result["diagnostic_only"])

    def test_unconfirmed_lidar_imu_calibration_forces_diagnostic_only(self) -> None:
        dataset = self._dataset(status="BLOCKED_CALIBRATION")
        algorithm = {"algorithm_id": "fast_lio2", "extrinsic_convention": "IMU_TO_LIDAR"}
        result = resolve_algorithm_extrinsic(dataset, algorithm)
        self.assertTrue(result["diagnostic_only"])
        self.assertEqual("BLOCKED_CALIBRATION", result["calibration_status"])

    def test_malformed_rotation_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            RigidTransform(rotation=(1.0,) * 8, translation=(0.0, 0.0, 0.0))

    def test_nonfinite_values_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            RigidTransform(rotation=(1.0, 0.0, 0.0, 0.0, math.nan, 0.0, 0.0, 0.0, 1.0), translation=(0.0, 0.0, 0.0))

    @staticmethod
    def _dataset(status: str) -> dict:
        return {
            "dataset_id": "test",
            "calibration": {
                "rotation_lidar_to_imu_row_major": [0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0],
                "translation_lidar_to_imu_m": [1.0, 2.0, 3.0],
                "source": "unit-test",
                "status": status,
            },
        }


if __name__ == "__main__":
    unittest.main()
