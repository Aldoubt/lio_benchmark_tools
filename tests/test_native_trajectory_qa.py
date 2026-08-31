from types import SimpleNamespace

import json
import numpy as np

import freeze_rerun_trajectory_qa as visual_qa
import freeze_rerun_visual_qa as map_qa_adapter


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


def test_adapter_combines_map_and_trajectory_visibility_without_recursion(tmp_path, monkeypatch):
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    (frozen / "freeze_manifest.json").write_text(
        json.dumps(
            {
                "freeze_state": "INCOMPLETE",
                "algorithms": ["fast_livo2", "dlio"],
                "baseline": "fast_livo2",
            }
        ),
        encoding="utf-8",
    )
    map_qa = {
        "fast_livo2": {"status": "ok"},
        "dlio": {"status": "ok"},
    }
    trajectory_qa = {
        "fast_livo2": {"status": "ok"},
        "dlio": {"status": "suspect_trajectory_extent"},
    }

    monkeypatch.setattr(
        map_qa_adapter,
        "collect_map_extent_qa",
        lambda *args, **kwargs: map_qa,
    )
    monkeypatch.setattr(
        visual_qa,
        "collect_trajectory_extent_qa",
        lambda *args, **kwargs: trajectory_qa,
    )

    original_visibility = map_qa_adapter.default_spatial_visibility

    def fake_map_builder(_frozen):
        collected = map_qa_adapter.collect_map_extent_qa(
            tmp_path,
            algorithms=["fast_livo2", "dlio"],
            baseline="fast_livo2",
        )
        visibility = map_qa_adapter.default_spatial_visibility(
            ["fast_livo2", "dlio"],
            baseline="fast_livo2",
            visible_algorithms={"fast_livo2", "dlio"},
            map_qa=collected,
        )
        manifest = json.loads((frozen / "freeze_manifest.json").read_text(encoding="utf-8"))
        manifest["rerun_recording"] = {
            "builder_summary": {"default_spatial_visibility": visibility}
        }
        (frozen / "freeze_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        return {"recording": manifest["rerun_recording"]}

    monkeypatch.setattr(map_qa_adapter, "build_frozen_rerun", fake_map_builder)

    result = visual_qa.build_frozen_rerun(frozen)

    visibility = result["recording"]["builder_summary"]["default_spatial_visibility"]
    assert visibility["dlio"]["reason"] == "suspect_trajectory_extent"
    assert visibility["dlio"]["algorithm_visible"] is False
    assert result["recording"]["builder_summary"]["trajectory_extent_qa"] == trajectory_qa
    assert map_qa_adapter.default_spatial_visibility is original_visibility
