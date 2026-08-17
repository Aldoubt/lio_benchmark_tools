from __future__ import annotations

import unittest

from benchmark_base.lib.calibration import (
    CONFIRMED_CALIBRATION_STATUSES,
    calibration_status,
    canonical_lidar_to_imu,
    invert_transform,
    resolve_algorithm_extrinsic,
)
from benchmark_base.lib.registry import Registry


class Mid360FactoryExtrinsicContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset = Registry().load_dataset("green_house_mid360")

    def test_registry_freezes_canonical_lidar_to_imu_transform(self) -> None:
        calibration = self.dataset["calibration"]
        self.assertEqual("LIDAR_TO_IMU", calibration["canonical_convention"])
        self.assertEqual(
            "p_I = R_IL * p_L + t_IL",
            calibration["canonical_equation"],
        )
        canonical = canonical_lidar_to_imu(self.dataset)
        self.assertEqual(
            (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
            canonical.rotation,
        )
        self.assertEqual((-0.011, -0.02329, 0.04412), canonical.translation)

    def test_registry_keeps_manufacturer_point_location_separate(self) -> None:
        calibration = self.dataset["calibration"]
        self.assertEqual(
            [0.011, 0.02329, -0.04412],
            calibration["manufacturer_imu_origin_in_lidar_m"],
        )
        self.assertEqual("MANUFACTURER_SPEC", calibration["source_type"])
        self.assertEqual("Livox Mid-360", calibration["sensor_model"])
        self.assertEqual("INTERNAL_IMU", calibration["imu_relation"])
        self.assertFalse(calibration["online_extrinsic_estimation"])

    def test_manufacturer_spec_is_usable_not_diagnostic(self) -> None:
        self.assertEqual("MANUFACTURER_SPEC", calibration_status(self.dataset))
        self.assertIn("MANUFACTURER_SPEC", CONFIRMED_CALIBRATION_STATUSES)
        algorithm = {
            "algorithm_id": "fast_lio2",
            "extrinsic_convention": "LIDAR_TO_IMU",
        }
        resolved = resolve_algorithm_extrinsic(self.dataset, algorithm)
        self.assertFalse(resolved["diagnostic_only"])
        self.assertEqual("MANUFACTURER_SPEC", resolved["calibration_status"])
        self.assertEqual("MANUFACTURER_SPEC", resolved["calibration_source_type"])
        self.assertEqual("Livox Mid-360", resolved["sensor_model"])
        self.assertEqual("INTERNAL_IMU", resolved["imu_relation"])
        self.assertEqual(
            "p_I = R_IL * p_L + t_IL",
            resolved["canonical_equation"],
        )

    def test_inverse_is_manufacturer_positive_vector(self) -> None:
        inverse = invert_transform(canonical_lidar_to_imu(self.dataset))
        self.assertEqual((0.011, 0.02329, -0.04412), inverse.translation)


if __name__ == "__main__":
    unittest.main()
