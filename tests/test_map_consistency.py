import numpy as np

from map_consistency import (
    map_health_flags,
    robust_extent_xyz,
    symmetric_nn_metrics,
    voxel_iou,
)


def test_robust_extent_rejects_isolated_outlier():
    core = np.vstack(
        [
            np.zeros((500, 3), dtype=np.float64),
            np.tile(np.array([[10.0, 20.0, 30.0]]), (500, 1)),
        ]
    )
    cloud = np.vstack([core, np.array([[1000.0, 1000.0, 1000.0]])])
    extent = robust_extent_xyz(cloud)
    assert np.allclose(extent, [10.0, 20.0, 30.0])


def test_voxel_iou_is_one_for_identical_and_zero_for_disjoint_clouds():
    cloud = np.array(
        [[0.1, 0.1, 0.1], [1.1, 0.1, 0.1], [0.1, 1.1, 0.1]],
        dtype=np.float64,
    )
    assert voxel_iou(cloud, cloud.copy(), voxel_m=0.5) == 1.0
    assert voxel_iou(cloud, cloud + np.array([100.0, 0.0, 0.0]), voxel_m=0.5) == 0.0


def test_symmetric_nn_metrics_report_known_translation():
    reference = np.array([[0.0, 0.0, 0.0], [0.0, 10.0, 0.0]], dtype=np.float64)
    candidate = reference + np.array([1.0, 0.0, 0.0])
    metrics = symmetric_nn_metrics(reference, candidate, max_points=100)
    assert np.isclose(metrics["mean_m"], 1.0)
    assert np.isclose(metrics["rmse_m"], 1.0)
    assert np.isclose(metrics["p95_m"], 1.0)
    assert metrics["samples_reference"] == 2
    assert metrics["samples_candidate"] == 2


def test_map_health_flags_are_conservative_and_baseline_relative():
    baseline = {
        "robust_extent_xyz_m": [50.0, 70.0, 10.0],
        "baseline_voxel_iou": 1.0,
        "symmetric_nn_p95_m": 0.0,
    }
    bad = {
        "robust_extent_xyz_m": [55.0, 72.0, 25.0],
        "baseline_voxel_iou": 0.05,
        "symmetric_nn_p95_m": 3.0,
    }
    assert map_health_flags(bad, baseline) == [
        "excessive_robust_z_span",
        "low_baseline_voxel_iou",
        "high_symmetric_nn_p95",
    ]

    healthy = {
        "robust_extent_xyz_m": [52.0, 69.0, 12.0],
        "baseline_voxel_iou": 0.5,
        "symmetric_nn_p95_m": 0.5,
    }
    assert map_health_flags(healthy, baseline) == []
