import csv

import numpy as np
from scipy.spatial.transform import Rotation

from viewer_projection import (
    initial_yaw_translation_alignment,
    load_standardized_trajectory,
    pose_at,
    project_points_to_display_world,
)


def _write_test_trajectory(path, times=(100.0, 100.1)):
    quats = Rotation.from_euler(
        "xyz",
        [[0.0, 0.0, 0.0], [10.0, 20.0, 30.0]],
        degrees=True,
    ).as_quat()
    rows = [
        [times[0], 0.0, 0.0, 0.0, *quats[0]],
        [times[1], 1.0, 0.5, 0.2, *quats[1]],
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["timestamp_s", "x_m", "y_m", "z_m", "qx", "qy", "qz", "qw"]
        )
        writer.writerows(rows)


def test_world_projection_uses_per_point_time_full_3d_pose_and_extrinsic(tmp_path):
    path = tmp_path / "trajectory.csv"
    _write_test_trajectory(path)
    trajectory = load_standardized_trajectory(path)
    points = np.array([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    times = np.array([100.02, 100.08])
    extrinsic_rotation = Rotation.from_euler("y", 30.0, degrees=True).as_matrix()
    world, valid = project_points_to_display_world(
        points,
        times,
        trajectory,
        extrinsic_rotation,
        np.array([0.2615, 0.0, 0.3]),
        np.eye(3),
        np.zeros(3),
        np.zeros(3),
        0.25,
    )
    assert valid.tolist() == [True, True]
    assert not np.allclose(world[0], world[1])


def test_pose_gap_limit_rejects_large_interpolation_interval(tmp_path):
    path = tmp_path / "trajectory.csv"
    _write_test_trajectory(path, times=(100.0, 101.0))
    trajectory = load_standardized_trajectory(path)
    _, _, valid = pose_at(trajectory, np.array([100.5]), max_gap_s=0.25)
    assert valid.tolist() == [False]


def test_shared_projection_matches_legacy_map_formula(tmp_path):
    path = tmp_path / "trajectory.csv"
    _write_test_trajectory(path)
    trajectory = load_standardized_trajectory(path)
    points = np.array([[1.0, 0.2, -0.1], [0.8, -0.3, 0.2]])
    times = np.array([100.02, 100.08])
    extrinsic_rotation = Rotation.from_euler("y", 30.0, degrees=True).as_matrix()
    extrinsic_translation = np.array([0.2615, 0.0, 0.3])
    alignment_rotation = Rotation.from_euler("z", 5.0, degrees=True).as_matrix()
    alignment_translation = np.array([0.5, -0.2, 0.1])
    origin = np.array([0.1, 0.2, 0.3])

    shared_world, shared_valid = project_points_to_display_world(
        points,
        times,
        trajectory,
        extrinsic_rotation,
        extrinsic_translation,
        alignment_rotation,
        alignment_translation,
        origin,
        None,
    )
    positions, rotations, valid = pose_at(trajectory, times, max_gap_s=None)
    lidar_in_body = (extrinsic_rotation @ points.T).T + extrinsic_translation
    legacy_world = np.einsum("nij,nj->ni", rotations, lidar_in_body) + positions
    legacy_aligned = (
        (alignment_rotation @ legacy_world.T).T + alignment_translation - origin
    )

    assert valid.tolist() == [True, True]
    assert shared_valid.tolist() == [True, True]
    assert np.allclose(shared_world, legacy_aligned, atol=1e-9)


def test_initial_alignment_keeps_baseline_identity(tmp_path):
    path = tmp_path / "trajectory.csv"
    _write_test_trajectory(path)
    trajectory = load_standardized_trajectory(path)
    rotation, translation, metrics = initial_yaw_translation_alignment(
        trajectory, trajectory
    )
    assert np.allclose(rotation, np.eye(3))
    assert np.allclose(translation, np.zeros(3))
    assert metrics["rmse_m"] == 0.0
