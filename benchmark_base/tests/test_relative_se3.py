from __future__ import annotations

import importlib
import importlib.util
import math
import unittest

import numpy as np

from benchmark_base.lib.calibration import RigidTransform
from benchmark_base.lib.trajectory import PoseSample, Trajectory, quaternion_from_rpy


class RelativeSE3MathTest(unittest.TestCase):
    def _api(self, name: str):
        spec = importlib.util.find_spec("benchmark_base.lib.relative_se3")
        self.assertIsNotNone(spec, "relative_se3 production module must exist")
        module = importlib.import_module("benchmark_base.lib.relative_se3")
        self.assertTrue(hasattr(module, name), f"relative_se3.{name} must exist")
        return getattr(module, name)

    @staticmethod
    def _sample(
        timestamp: float,
        x: float,
        y: float,
        z: float,
        roll: float = 0.0,
        pitch: float = 0.0,
        yaw: float = 0.0,
    ) -> PoseSample:
        qx, qy, qz, qw = quaternion_from_rpy(roll, pitch, yaw)
        return PoseSample(
            timestamp_s=timestamp,
            x_m=x,
            y_m=y,
            z_m=z,
            qx=qx,
            qy=qy,
            qz=qz,
            qw=qw,
            roll_rad=roll,
            pitch_rad=pitch,
            yaw_rad=yaw,
            source_topic="/test",
        )

    def test_world_gauge_normalization_removes_only_initial_se3_gauge(self) -> None:
        pose_from_sample = self._api("pose_from_sample")
        compose_pose = self._api("compose_pose")
        invert_pose = self._api("invert_pose")
        relative_pose = self._api("relative_pose")
        rotation_geodesic_rad = self._api("rotation_geodesic_rad")

        identity_motion_0 = pose_from_sample(self._sample(0.0, 0.0, 0.0, 0.0))
        identity_motion_1 = pose_from_sample(self._sample(1.0, 1.0, 0.5, -0.2, yaw=0.3))

        gauge_a = pose_from_sample(self._sample(0.0, 10.0, -4.0, 2.0, roll=0.2, pitch=-0.1, yaw=0.7))
        gauge_b = pose_from_sample(self._sample(0.0, -3.0, 8.0, 1.0, roll=-0.4, pitch=0.15, yaw=-1.0))

        a0 = compose_pose(gauge_a, identity_motion_0)
        a1 = compose_pose(gauge_a, identity_motion_1)
        b0 = compose_pose(gauge_b, identity_motion_0)
        b1 = compose_pose(gauge_b, identity_motion_1)

        da = relative_pose(a0, a1)
        db = relative_pose(b0, b1)
        delta = compose_pose(invert_pose(da), db)

        self.assertTrue(np.allclose(da.translation, db.translation, atol=1e-10))
        self.assertAlmostEqual(0.0, rotation_geodesic_rad(delta.rotation), places=10)

    def test_global_common_time_grid_uses_latest_start_and_earliest_end(self) -> None:
        common_evaluation_times = self._api("common_evaluation_times")
        left = Trajectory([
            self._sample(0.0, 0.0, 0.0, 0.0),
            self._sample(1.0, 1.0, 0.0, 0.0),
            self._sample(2.05, 2.05, 0.0, 0.0),
        ])
        right = Trajectory([
            self._sample(0.15, 0.0, 0.0, 0.0),
            self._sample(1.15, 1.0, 0.0, 0.0),
            self._sample(2.0, 2.0, 0.0, 0.0),
        ])
        start, end, times = common_evaluation_times({"left": left, "right": right})
        self.assertAlmostEqual(0.15, start)
        self.assertAlmostEqual(2.0, end)
        self.assertAlmostEqual(start, times[0])
        self.assertAlmostEqual(end, times[-1])
        self.assertAlmostEqual(0.1, times[1] - times[0])

    def test_lidar_pose_conversion_uses_t_wl_times_inverse_t_il(self) -> None:
        pose_from_sample = self._api("pose_from_sample")
        normalize_pose_to_imu = self._api("normalize_pose_to_imu")

        t_wl = pose_from_sample(self._sample(1.0, 2.0, 3.0, 0.5, yaw=math.pi / 2.0))
        t_il = RigidTransform(
            rotation=(
                0.0, -1.0, 0.0,
                1.0, 0.0, 0.0,
                0.0, 0.0, 1.0,
            ),
            translation=(0.4, -0.2, 0.1),
        )
        actual = normalize_pose_to_imu(t_wl, "LIDAR", t_il)

        r_wl = np.asarray(t_wl.rotation).reshape(3, 3)
        r_il = np.asarray(t_il.rotation).reshape(3, 3)
        t_il_v = np.asarray(t_il.translation)
        r_li = r_il.T
        t_li = -(r_li @ t_il_v)
        expected_r = r_wl @ r_li
        expected_t = np.asarray(t_wl.translation) + r_wl @ t_li

        self.assertTrue(np.allclose(np.asarray(actual.rotation).reshape(3, 3), expected_r, atol=1e-10))
        self.assertTrue(np.allclose(actual.translation, expected_t, atol=1e-10))

    def test_imu_pose_normalization_is_identity_conversion(self) -> None:
        pose_from_sample = self._api("pose_from_sample")
        normalize_pose_to_imu = self._api("normalize_pose_to_imu")
        pose = pose_from_sample(self._sample(1.0, 1.0, 2.0, 3.0, roll=0.1, pitch=0.2, yaw=0.3))
        actual = normalize_pose_to_imu(pose, "IMU_BODY", None)
        self.assertEqual(pose, actual)

    def test_so3_geodesic_is_quaternion_sign_invariant_and_wrap_safe(self) -> None:
        pose_from_sample = self._api("pose_from_sample")
        rotation_geodesic_rad = self._api("rotation_geodesic_rad")
        left = pose_from_sample(self._sample(0.0, 0.0, 0.0, 0.0, yaw=math.pi - 0.01))
        right = pose_from_sample(self._sample(0.0, 0.0, 0.0, 0.0, yaw=-math.pi + 0.01))
        r_left = np.asarray(left.rotation).reshape(3, 3)
        r_right = np.asarray(right.rotation).reshape(3, 3)
        self.assertAlmostEqual(0.02, rotation_geodesic_rad(r_left.T @ r_right), places=9)

    def test_sustained_onset_ignores_spike_and_returns_first_of_three_samples(self) -> None:
        sustained_onset = self._api("sustained_onset")
        times = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
        values = [0.02, 0.12, 0.03, 0.11, 0.13, 0.15]
        onset = sustained_onset(times, values, threshold=0.10, sustain_samples=3)
        self.assertTrue(onset.crossed)
        self.assertAlmostEqual(0.3, onset.onset_relative_time_s)
        self.assertAlmostEqual(0.11, onset.onset_value)

    def test_sustained_onset_reports_no_crossing_when_run_is_too_short(self) -> None:
        sustained_onset = self._api("sustained_onset")
        onset = sustained_onset([0.0, 0.1, 0.2], [0.0, 0.2, 0.3], threshold=0.1, sustain_samples=3)
        self.assertFalse(onset.crossed)
        self.assertIsNone(onset.onset_relative_time_s)
        self.assertIsNone(onset.onset_value)


if __name__ == "__main__":
    unittest.main()
