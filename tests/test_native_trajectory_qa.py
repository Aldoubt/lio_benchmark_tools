from types import SimpleNamespace

import numpy as np

import freeze_rerun_trajectory_qa as visual_qa


def test_trajectory_extent_qa_uses_floor_for_near_planar_baseline():
    result = visual_qa.classify_trajectory_extent_xyz(
        [100.0, 80.0, 30.0],
        [100.0, 80.0, 1.0],
    )

    assert result["reference_extent_xyz_m"] == [100.0, 80.0, 5.0]
    assert result["ratio_xyz"] == [1.0, 1.0, 6.0]
    assert result["status"] == "suspect_trajectory_extent"


def test_default_visibility_hides_suspect_trajectory_even_when_map_is_ok():
    policy = visual_qa.default_spatial_visibility(
        ["fast_livo2", "dlio"],
        baseline="fast_livo2",
        visible_algorithms={"fast_livo2", "dlio"},
        map_qa={
            "fast_livo2": {"status": "ok"},
            "dlio": {"status": "ok"},
        },
        trajectory_qa={
            "fast_livo2": {"status": "ok"},
            "dlio": {"status": "suspect_trajectory_extent"},
        },
    )

    assert policy["fast_livo2"] == {
        "algorithm_visible": True,
        "map_visible": True,
        "reason": "baseline",
    }
    assert policy["dlio"] == {
        "algorithm_visible": False,
        "map_visible": False,
        "reason": "suspect_trajectory_extent",
    }


def test_collect_aligned_trajectory_extent_qa_uses_viewer_alignment(monkeypatch, tmp_path):
    baseline_positions = np.asarray(
        [[0.0, 0.0, 0.0], [100.0, 80.0, 1.0]], dtype=np.float64
    )
    dlio_positions = np.asarray(
        [[10.0, 10.0, 0.0], [110.0, 90.0, 30.0]], dtype=np.float64
    )
    trajectories = {
        "fast_livo2": SimpleNamespace(positions=baseline_positions),
        "dlio": SimpleNamespace(positions=dlio_positions),
    }
    alignments = {
        "fast_livo2": (np.eye(3), np.zeros(3)),
        "dlio": (np.eye(3), np.asarray([-10.0, -10.0, 0.0])),
    }

    import rerun_diagnostic_viewer as viewer

    monkeypatch.setattr(
        viewer,
        "_projection_context",
        lambda run, algorithms, baseline: (
            trajectories,
            alignments,
            np.zeros(3),
        ),
    )

    qa = visual_qa.collect_trajectory_extent_qa(
        tmp_path,
        algorithms=["fast_livo2", "dlio"],
        baseline="fast_livo2",
    )

    assert qa["fast_livo2"]["status"] == "ok"
    assert qa["fast_livo2"]["extent_xyz_m"] == [100.0, 80.0, 1.0]
    assert qa["dlio"]["extent_xyz_m"] == [100.0, 80.0, 30.0]
    assert qa["dlio"]["status"] == "suspect_trajectory_extent"
