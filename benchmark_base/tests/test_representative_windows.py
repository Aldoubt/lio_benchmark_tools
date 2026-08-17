from __future__ import annotations

import unittest

import numpy as np

from benchmark_base.lib.representative_windows import (
    WINDOW_DURATION_S,
    ImuFeatureSample,
    RepresentativeWindowError,
    WindowFeature,
    build_window_features,
    lidar_scan_feature,
    select_from_window_features,
)


def feature(
    start: float,
    *,
    gyro_rms: float = 0.1,
    gyro_p95: float = 0.2,
    accel_dynamic: float = 0.2,
    scene_change: float = 0.2,
    degeneracy: float = 0.2,
    valid: bool = True,
) -> WindowFeature:
    return WindowFeature(
        start_offset_s=start,
        duration_s=WINDOW_DURATION_S,
        lidar_scan_count=450 if valid else 10,
        imu_sample_count=9000 if valid else 10,
        gyro_rms_rad_s=gyro_rms,
        gyro_p95_rad_s=gyro_p95,
        accel_dynamic_rms_m_s2=accel_dynamic,
        scene_change_mean=scene_change,
        geometric_degeneracy_median=degeneracy,
        geometric_degeneracy_p90=min(1.0, degeneracy + 0.1),
        valid=valid,
    )


class RepresentativeWindowRawFeatureTest(unittest.TestCase):
    def test_lidar_signature_is_normalized_and_line_is_more_degenerate_than_3d_cloud(self) -> None:
        line = np.column_stack(
            (np.linspace(1.0, 10.0, 200), np.zeros(200), np.zeros(200))
        )
        grid = np.asarray(
            [
                [x, y, z]
                for x in (-2.0, 0.0, 2.0)
                for y in (-2.0, 0.0, 2.0)
                for z in (-2.0, 0.0, 2.0)
                if (x, y, z) != (0.0, 0.0, 0.0)
            ],
            dtype=np.float64,
        )
        line_feature = lidar_scan_feature(1.0, line)
        grid_feature = lidar_scan_feature(1.0, grid)
        self.assertAlmostEqual(1.0, float(np.sum(line_feature.range_histogram)), places=12)
        self.assertAlmostEqual(1.0, float(np.sum(grid_feature.range_histogram)), places=12)
        self.assertGreater(
            line_feature.geometric_degeneracy_score,
            grid_feature.geometric_degeneracy_score,
        )

    def test_window_aggregation_uses_raw_counts_and_motion_norms(self) -> None:
        lidar = tuple(
            lidar_scan_feature(
                index * 0.1,
                np.asarray(
                    [
                        [1.0 + 0.01 * index, 0.0, 0.0],
                        [0.0, 2.0, 0.0],
                        [0.0, 0.0, 3.0],
                        [1.0, 1.0, 1.0],
                    ],
                    dtype=np.float64,
                ),
            )
            for index in range(450)
        )
        imu = tuple(
            ImuFeatureSample(index * 0.005, 0.2, 9.8 + 0.1 * ((index % 3) - 1))
            for index in range(9000)
        )
        records = build_window_features(lidar, imu, analysis_end_s=45.0)
        self.assertEqual(1, len(records))
        record = records[0]
        self.assertEqual(450, record.lidar_scan_count)
        self.assertEqual(9000, record.imu_sample_count)
        self.assertTrue(record.valid)
        self.assertAlmostEqual(0.2, record.gyro_rms_rad_s, places=12)
        self.assertGreater(record.accel_dynamic_rms_m_s2, 0.0)


class RepresentativeWindowSelectionTest(unittest.TestCase):
    def test_initialization_is_fixed_zero_window(self) -> None:
        selected = select_from_window_features(
            [
                feature(0.0),
                feature(60.0, gyro_p95=0.5),
                feature(110.0, degeneracy=0.8, scene_change=0.3),
                feature(160.0, scene_change=0.9, gyro_rms=0.02),
            ]
        )
        first = selected[0]
        self.assertEqual("initialization", first.label)
        self.assertEqual(0.0, first.start_offset_s)
        self.assertEqual(45.0, first.duration_s)

    def test_high_angular_motion_selects_maximum_gyro_p95(self) -> None:
        selected = select_from_window_features(
            [
                feature(0.0),
                feature(60.0, gyro_p95=0.4),
                feature(110.0, gyro_p95=2.4),
                feature(160.0, degeneracy=0.85, scene_change=0.4),
                feature(210.0, scene_change=0.9, gyro_rms=0.01),
            ]
        )
        high = next(item for item in selected if item.label == "high_angular_motion")
        self.assertEqual(110.0, high.start_offset_s)

    def test_selected_windows_are_pairwise_non_overlapping(self) -> None:
        selected = select_from_window_features(
            [
                feature(0.0),
                feature(60.0, gyro_p95=2.5),
                feature(100.0, degeneracy=0.99, scene_change=0.8),
                feature(110.0, degeneracy=0.8, scene_change=0.6),
                feature(160.0, scene_change=0.9, gyro_rms=0.01),
                feature(210.0, scene_change=0.7, gyro_rms=0.03),
            ]
        )
        intervals = sorted((item.start_offset_s, item.start_offset_s + item.duration_s) for item in selected)
        for (_, left_end), (right_start, _) in zip(intervals, intervals[1:]):
            self.assertLessEqual(left_end, right_start)

    def test_geometric_candidate_prefers_high_structure_score_with_scene_change(self) -> None:
        selected = select_from_window_features(
            [
                feature(0.0),
                feature(60.0, gyro_p95=3.0),
                feature(110.0, degeneracy=0.95, scene_change=0.01),
                feature(160.0, degeneracy=0.82, scene_change=0.45),
                feature(210.0, scene_change=0.9, gyro_rms=0.02),
                feature(260.0, scene_change=0.8, gyro_rms=0.03),
            ]
        )
        geometric = next(
            item for item in selected if item.label == "geometric_degeneracy_candidate"
        )
        self.assertEqual(160.0, geometric.start_offset_s)

    def test_steady_translation_prefers_scene_change_and_low_motion_dynamics(self) -> None:
        selected = select_from_window_features(
            [
                feature(0.0),
                feature(60.0, gyro_p95=3.0),
                feature(110.0, degeneracy=0.85, scene_change=0.5),
                feature(160.0, scene_change=0.95, gyro_rms=0.03, accel_dynamic=0.08),
                feature(210.0, scene_change=0.30, gyro_rms=0.01, accel_dynamic=0.05),
                feature(260.0, scene_change=0.80, gyro_rms=0.30, accel_dynamic=0.60),
            ]
        )
        steady = next(item for item in selected if item.label == "steady_translation_candidate")
        self.assertEqual(160.0, steady.start_offset_s)

    def test_ties_resolve_to_earlier_start(self) -> None:
        selected = select_from_window_features(
            [
                feature(0.0),
                feature(60.0, gyro_p95=2.0),
                feature(110.0, gyro_p95=2.0),
                feature(160.0, degeneracy=0.8, scene_change=0.5),
                feature(210.0, scene_change=0.9, gyro_rms=0.01),
            ]
        )
        high = next(item for item in selected if item.label == "high_angular_motion")
        self.assertEqual(60.0, high.start_offset_s)

    def test_insufficient_non_overlapping_candidates_fail_closed(self) -> None:
        with self.assertRaisesRegex(RepresentativeWindowError, "four pairwise non-overlapping"):
            select_from_window_features(
                [
                    feature(0.0),
                    feature(60.0, gyro_p95=3.0),
                    feature(70.0, degeneracy=0.9),
                    feature(80.0, scene_change=0.9),
                ]
            )


if __name__ == "__main__":
    unittest.main()
