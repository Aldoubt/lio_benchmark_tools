import json
import math
import struct
from pathlib import Path

import numpy as np

from rerun_diagnostic_viewer import (
    apply_alignment,
    initial_yaw_translation_transform,
    load_binary_little_endian_ply,
    nearest_frame,
    resolve_algorithms,
    select_pointcloud_frames,
)


def test_load_binary_little_endian_ply_reads_xyz_intensity(tmp_path):
    path = tmp_path / "map.ply"
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        "element vertex 2\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "property float intensity\n"
        "end_header\n"
    ).encode("ascii")
    payload = struct.pack("<ffffffff", 1.0, 2.0, 3.0, 4.0, -1.0, -2.0, -3.0, 8.0)
    path.write_bytes(header + payload)

    cloud = load_binary_little_endian_ply(path)

    assert cloud.shape == (2, 4)
    assert np.allclose(cloud[0], [1.0, 2.0, 3.0, 4.0])
    assert np.allclose(cloud[1], [-1.0, -2.0, -3.0, 8.0])


def test_nearest_frame_uses_closest_bag_time_not_only_previous():
    frames = [
        {"message_id": 10, "bag_time_s": 1.0},
        {"message_id": 20, "bag_time_s": 2.0},
        {"message_id": 30, "bag_time_s": 3.0},
    ]
    assert nearest_frame(frames, 2.8)["message_id"] == 30
    assert nearest_frame(frames, 2.2)["message_id"] == 20


def test_select_pointcloud_frames_combines_periodic_and_anomaly_frames_without_duplicates():
    frames = [
        {"message_id": index, "bag_time_s": float(index)}
        for index in range(7)
    ]
    windows = [
        {"start_bag_time_s": 1.9, "end_bag_time_s": 2.1},
        {"start_bag_time_s": 5.0, "end_bag_time_s": 5.0},
    ]

    selected = select_pointcloud_frames(
        frames,
        windows,
        period_s=3.0,
        include_anomalies=True,
    )

    assert [item["message_id"] for item in selected] == [0, 2, 3, 5, 6]


def test_initial_yaw_translation_transform_aligns_candidate_start_and_heading():
    baseline_start = np.asarray([0.0, 0.0, 0.0])
    candidate_start = np.asarray([10.0, 0.0, 0.0])
    rotation, translation = initial_yaw_translation_transform(
        baseline_start,
        baseline_yaw_rad=0.0,
        candidate_start=candidate_start,
        candidate_yaw_rad=math.pi / 2.0,
    )
    candidate = np.asarray([[10.0, 0.0, 0.0], [10.0, 1.0, 0.0]])
    aligned = apply_alignment(candidate, rotation, translation)
    assert np.allclose(aligned, [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], atol=1e-9)


def test_resolve_algorithms_defaults_to_recorded_order_and_validates_requested(tmp_path):
    run = tmp_path / "run"
    (run / "metrics").mkdir(parents=True)
    (run / "metrics" / "diagnostic_timeline.json").write_text(
        json.dumps({"algorithm_order": ["fast_livo2", "point_lio", "glim_full_slam"]}),
        encoding="utf-8",
    )

    assert resolve_algorithms(run, None) == ["fast_livo2", "point_lio", "glim_full_slam"]
    assert resolve_algorithms(run, "point_lio,fast_livo2") == ["point_lio", "fast_livo2"]

    try:
        resolve_algorithms(run, "unknown")
    except ValueError as exc:
        assert "unknown algorithms" in str(exc)
    else:
        raise AssertionError("unknown algorithm must be rejected")
