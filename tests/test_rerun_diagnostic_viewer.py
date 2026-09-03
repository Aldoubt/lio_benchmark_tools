import json
import math
import struct
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from freeze_rerun_visual_qa import classify_extent_xyz, default_spatial_visibility
from rerun_diagnostic_viewer import (
    algorithm_entity_paths,
    apply_alignment,
    initial_yaw_translation_transform,
    load_binary_little_endian_ply,
    nearest_frame,
    parse_point_lods,
    point_lod_clouds,
    resolve_algorithms,
    scan_from_livox_message,
    select_pointcloud_frames,
    world_entity_paths,
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


def test_map_extent_qa_marks_point_lio_scale_as_suspect():
    baseline = [139.8955954339839, 138.00446113415796, 40.98942551677813]
    point_lio = [59472.02826405508, 8087.60167741251, 15140.702544203477]

    qa = classify_extent_xyz(point_lio, baseline)

    assert qa["status"] == "suspect_extent"
    assert qa["ratio_xyz"][0] > 400
    assert qa["ratio_xyz"][1] > 50
    assert qa["ratio_xyz"][2] > 300
    assert qa["max_ratio"] == pytest.approx(max(qa["ratio_xyz"]))


def test_map_extent_qa_keeps_moderate_dlio_height_as_non_suspect():
    baseline = [139.8955954339839, 138.00446113415796, 40.98942551677813]
    dlio = [96.87232369661749, 115.9204388565068, 148.5479131342942]

    qa = classify_extent_xyz(dlio, baseline)

    assert qa["status"] == "ok"
    assert qa["max_ratio"] < 5.0


def test_default_spatial_visibility_is_baseline_map_first_and_hides_suspect_algorithm():
    algorithms = ["fast_livo2", "dlio", "point_lio"]
    map_qa = {
        "fast_livo2": {"status": "ok"},
        "dlio": {"status": "ok"},
        "point_lio": {"status": "suspect_extent"},
    }

    policy = default_spatial_visibility(
        algorithms,
        baseline="fast_livo2",
        visible_algorithms=set(algorithms),
        map_qa=map_qa,
    )

    assert policy["fast_livo2"] == {
        "algorithm_visible": True,
        "map_visible": True,
        "reason": "baseline",
    }
    assert policy["dlio"] == {
        "algorithm_visible": True,
        "map_visible": False,
        "reason": "nonbaseline_map_hidden",
    }
    assert policy["point_lio"] == {
        "algorithm_visible": False,
        "map_visible": False,
        "reason": "suspect_extent",
    }


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


def test_parse_point_lods_requires_three_increasing_multiples():
    assert parse_point_lods("10,20,80") == {
        "dense": 10,
        "medium": 20,
        "sparse": 80,
    }

    for value in ("10,20", "20,10,80", "10,25,80", "0,20,80"):
        try:
            parse_point_lods(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid point LODs must be rejected: {value}")


def test_point_lod_clouds_reuses_dense_cloud_for_coarser_levels():
    dense = np.arange(16 * 3, dtype=np.float64).reshape(16, 3)
    lods = point_lod_clouds(
        dense,
        {"dense": 10, "medium": 20, "sparse": 80},
    )
    assert len(lods["dense"]) == 16
    assert len(lods["medium"]) == 8
    assert len(lods["sparse"]) == 2
    assert np.array_equal(lods["medium"], dense[::2])
    assert np.array_equal(lods["sparse"], dense[::8])


def test_algorithm_entity_paths_group_spatial_items_by_algorithm():
    paths = algorithm_entity_paths("point_lio")
    assert paths == {
        "root": "world/algorithms/point_lio",
        "trajectory": "world/algorithms/point_lio/trajectory",
        "current": "world/algorithms/point_lio/current",
        "map": "world/algorithms/point_lio/map",
    }


def test_world_entity_paths_are_grouped_by_algorithm():
    assert world_entity_paths("glim_full_slam") == {
        "dense": "world_lidar/glim_full_slam/dense",
        "medium": "world_lidar/glim_full_slam/medium",
        "sparse": "world_lidar/glim_full_slam/sparse",
    }


def test_livox_scan_preserves_header_plus_offset_time():
    stamp = SimpleNamespace(sec=100, nanosec=0)
    message = SimpleNamespace(
        header=SimpleNamespace(stamp=stamp),
        points=[
            SimpleNamespace(
                x=float(i),
                y=0.0,
                z=0.0,
                offset_time=i * 1000,
                reflectivity=i,
            )
            for i in range(21)
        ],
    )
    frame = {"message_id": 11, "bag_time_s": 0.0}
    scan = scan_from_livox_message(message, frame, dense_step=10)
    assert scan.points_xyz.shape == (3, 3)
    assert scan.point_times_s.tolist() == pytest.approx(
        [100.0, 100.00001, 100.00002]
    )
    assert scan.intensity.tolist() == [0.0, 10.0, 20.0]


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
