import json
from pathlib import Path

import pytest

from report_evidence import build_report_evidence


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _make_bundle(tmp_path: Path) -> tuple[Path, Path]:
    run = tmp_path / "live_run"
    for rel, content in {
        "figures/comparison_dashboard/diagnostic_dashboard.png": b"dashboard",
        "figures/comparison_dashboard/trajectory_xy_overlay_all.png": b"xy",
        "figures/trajectory_discontinuity/position_step.png": b"pos",
        "figures/trajectory_discontinuity/yaw_step.png": b"yaw",
        "figures/resource_curves/cpu.png": b"cpu",
        "figures/fast_livo2_baseline_maps/map_xy.png": b"map",
        "figures/phase_analysis/phase_z.png": b"phase",
    }.items():
        path = run / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (run / "figures/comparison_dashboard/README.md").write_text("ignore")

    frozen = tmp_path / "frozen"
    (frozen / "source").mkdir(parents=True)
    _write_json(
        frozen / "freeze_manifest.json",
        {
            "freeze_state": "INCOMPLETE",
            "source_run": {"path": str(run), "run_id": "run-001", "state": "COMPLETED"},
            "optional_evidence": {"maps": True, "phase_analysis": True, "pointcloud_index": False, "resource_timelines": True},
            "generated_artifacts": [],
        },
    )
    _write_json(
        frozen / "report_data.json",
        {
            "schema_version": 1,
            "anomaly_summary": {
                "selected_window_ids": ["bad:window_0002", "ok:window_0001"],
                "representative_cases": [
                    {"window_id": "bad:window_0002", "algorithm": "bad", "types": ["position_jump"], "severity": 4.0, "view_start_bag_time_s": 20.0, "view_end_bag_time_s": 21.0},
                    {"window_id": "ok:window_0001", "algorithm": "ok", "types": ["yaw_jump"], "severity": 3.0, "view_start_bag_time_s": 10.0, "view_end_bag_time_s": 11.0},
                ],
            },
            "optional_evidence": {"rerun_pointcloud": {"enabled": False, "omission_reason": "pointcloud_frame_index_missing"}},
        },
    )
    return frozen, run


def test_build_report_evidence_copies_only_known_static_images_and_writes_cases(tmp_path):
    frozen, run = _make_bundle(tmp_path)
    result = build_report_evidence(frozen)
    assert (
        frozen / "evidence/overview/comparison_dashboard/diagnostic_dashboard.png"
    ).read_bytes() == b"dashboard"
    assert (
        frozen / "evidence/trajectories/trajectory_discontinuity/position_step.png"
    ).read_bytes() == b"pos"
    assert (
        frozen / "evidence/resources/resource_curves/cpu.png"
    ).read_bytes() == b"cpu"
    assert (
        frozen / "evidence/maps/fast_livo2_baseline_maps/map_xy.png"
    ).read_bytes() == b"map"
    assert (frozen / "evidence/overview/phase_analysis/phase_z.png").read_bytes() == b"phase"
    assert not (
        frozen / "evidence/overview/comparison_dashboard/README.md"
    ).exists()

    cases = result["manifest"]["anomaly_cases"]
    assert [item["window_id"] for item in cases] == [
        "bad:window_0002",
        "ok:window_0001",
    ]
    first_case = frozen / cases[0]["bundle_path"]
    assert json.loads(first_case.read_text())["window"]["algorithm"] == "bad"
    assert result["manifest"]["pointcloud_case_evidence"]["available"] is False
    assert (
        result["manifest"]["pointcloud_case_evidence"]["reason"]
        == "pointcloud_frame_index_missing"
    )
    assert (frozen / "evidence/evidence_manifest.json").is_file()

    freeze_manifest = json.loads((frozen / "freeze_manifest.json").read_text())
    paths = {item["path"] for item in freeze_manifest["generated_artifacts"]}
    assert "evidence/evidence_manifest.json" in paths
    assert "evidence/anomalies/case_01_bad_window_0002.json" in paths
    assert "evidence/maps/fast_livo2_baseline_maps/map_xy.png" in paths
    assert freeze_manifest["freeze_state"] == "INCOMPLETE"


def test_build_report_evidence_survives_unavailable_live_figure_source(tmp_path):
    frozen, run = _make_bundle(tmp_path)
    for path in sorted(run.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    run.rmdir()
    result = build_report_evidence(frozen)
    assert result["manifest"]["static_figures"] == []
    assert result["manifest"]["static_figure_source"]["available"] is False
    assert len(result["manifest"]["anomaly_cases"]) == 2


def test_build_report_evidence_refuses_complete_bundle(tmp_path):
    frozen, _ = _make_bundle(tmp_path)
    path = frozen / "freeze_manifest.json"
    payload = json.loads(path.read_text())
    payload["freeze_state"] = "COMPLETE"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="already COMPLETE"):
        build_report_evidence(frozen)
