from __future__ import annotations

import unittest

import numpy as np

from benchmark_base.lib.map_frame_contract import lidar_points_in_tracked_frame


class MapFrameContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.points = np.array([[1.0, 2.0, 3.0], [-1.0, 0.5, 2.0]], dtype=np.float64)
        self.calibration = {
            "rotation_lidar_to_imu_row_major": [
                0.0, -1.0, 0.0,
                1.0, 0.0, 0.0,
                0.0, 0.0, 1.0,
            ],
            "translation_lidar_to_imu_m": [0.1, 0.2, 0.3],
        }

    def test_lidar_tracked_trajectory_does_not_apply_lidar_to_imu_extrinsic(self) -> None:
        result = lidar_points_in_tracked_frame(
            self.points,
            tracked_frame_physical="LIDAR",
            calibration=self.calibration,
        )
        np.testing.assert_allclose(self.points, result)
        self.assertIsNot(self.points, result)

    def test_imu_body_tracked_trajectory_applies_canonical_lidar_to_imu(self) -> None:
        result = lidar_points_in_tracked_frame(
            self.points,
            tracked_frame_physical="IMU_BODY",
            calibration=self.calibration,
        )
        rotation = np.asarray(self.calibration["rotation_lidar_to_imu_row_major"]).reshape(3, 3)
        translation = np.asarray(self.calibration["translation_lidar_to_imu_m"])
        expected = (rotation @ self.points.T).T + translation
        np.testing.assert_allclose(expected, result)

    def test_unknown_tracked_frame_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "tracked frame"):
            lidar_points_in_tracked_frame(
                self.points,
                tracked_frame_physical="UNKNOWN",
                calibration=self.calibration,
            )

    def test_bad_calibration_is_rejected_for_imu_body(self) -> None:
        with self.assertRaises(ValueError):
            lidar_points_in_tracked_frame(
                self.points,
                tracked_frame_physical="IMU_BODY",
                calibration={"rotation_lidar_to_imu_row_major": [1.0]},
            )


if __name__ == "__main__":
    unittest.main()
