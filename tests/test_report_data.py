import json
from pathlib import Path

import pytest

from report_data import build_report_data, select_representative_anomalies


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_representative_anomalies_are_deterministic_cover_types_and_unhealthy_algorithms():
    windows = [
        {"window_id": "ok:p-low", "algorithm": "ok", "types": ["position_jump"], "severity": 2.0, "start_bag_time_s": 20.0},
        {"window_id": "ok:y-high", "algorithm": "ok", "types": ["yaw_jump"], "severity": 9.0, "start_bag_time_s": 9.0},
        {"window_id": "bad:p", "algorithm": "bad", "types": ["position_jump"], "severity": 1.0, "start_bag_time_s": 30.0},
        {"window_id": "ok:p-high", "algorithm": "ok", "types": ["position_jump"], "severity": 8.0, "start_bag_time_s": 8.0},
        {"window_id": "bad:p", "algorithm": "bad", "types": ["position_jump"], "severity": 100.0, "start_bag_time_s": 30.0},
        {"window_id": "other:y", "algorithm": "other", "types": ["yaw_jump"], "severity": 7.0, "start_bag_time_s": 7.0},
        {"window_id": "other:p", "algorithm": "other", "types": ["position_jump"], "severity": 6.0, "start_bag_time_s": 6.0},
    ]
    selected = select_representative_anomalies(
        windows,
        unhealthy_algorithms={"bad"},
        limit=4,
    )
    ids = [item["window_id"] for item in selected]
    assert len(ids) == len(set(ids)) == 4
    assert "bad:p" in ids
    assert any("position_jump" in item["types"] for item in selected)
    assert any("yaw_jump" in item["types"] for item in selected)
    assert ids == [
        item["window_id"]
        for item in sorted(
            selected,
            key=lambda item: (
                -float(item["severity"]),
                item["algorithm"],
                float(item["start_bag_time_s"]),
                item["window_id"],
            ),
        )
    ]


def _make_frozen(tmp_path: Path) -> Path:
    frozen = tmp_path / "frozen"
    source = frozen / "source"
    (frozen / "viewer").mkdir(parents=True)
    (frozen / "viewer/diagnostic.rrd").write_bytes(b"rrd")
    _write_json(
        frozen / "freeze_manifest.json",
        {
            "schema_version": 1,
            "freeze_state": "INCOMPLETE",
            "created_at_utc": "2026-08-31T09:00:00+00:00",
            "source_run": {"path": "/mutable/live/run", "run_id": "run-001", "state": "COMPLETED"},
            "benchmark": {"branch": "feat/phase-aware-benchmark", "commit": "abc123", "short_sha": "abc123"},
            "baseline": "fast_livo2",
            "language": "zh-CN",
            "metric_class": "relative-to-baseline/diagnostic/non-ground-truth",
            "ground_truth_available": False,
            "algorithms": ["fast_livo2", "bad_algo"],
            "algorithm_provenance": {"fast_livo2": {"commit": "f1"}, "bad_algo": {"commit": "b1"}},
            "optional_evidence": {"maps": False, "phase_analysis": True, "pointcloud_index": False, "resource_timelines": True},
            "dataset_source": {"path": "/bags/source", "size_bytes": 123, "sha256": "bagsha"},
            "source_artifacts": [{"bundle_path": "source/manifest.json", "sha256": "source"}],
            "generated_artifacts": [{"path": "viewer/diagnostic.rrd", "role": "native_rerun_recording", "size_bytes": 3, "sha256": "fake"}],
            "rerun_recording": {"sdk_version": "0.36.3", "pointcloud_evidence": {"enabled": False, "omission_reason": "pointcloud_frame_index_missing"}},
        },
    )
    _write_json(
        source / "manifest.json",
        {
            "playback_rate": 1.0,
            "dataset": {"duration_s": 100.0, "ground_truth": None, "lidar_topic": "/lidar", "imu_topic": "/imu"},
            "calibration": {"source": "test calibration", "confidence": "mixed", "lidar_to_imu": {"translation": [1, 2, 3]}},
        },
    )
    _write_json(
        source / "metrics/diagnostic_timeline.json",
        {
            "algorithm_order": ["fast_livo2", "bad_algo"],
            "anomaly_windows": [
                {"window_id": "fast_livo2:window_0001", "algorithm": "fast_livo2", "types": ["yaw_jump"], "severity": 5.0, "start_bag_time_s": 10.0, "end_bag_time_s": 10.2, "view_start_bag_time_s": 9.5, "view_end_bag_time_s": 10.7},
                {"window_id": "bad_algo:window_0001", "algorithm": "bad_algo", "types": ["position_jump"], "severity": 1.2, "start_bag_time_s": 20.0, "end_bag_time_s": 20.1, "view_start_bag_time_s": 19.5, "view_end_bag_time_s": 20.6},
            ],
            "algorithms": {
                "fast_livo2": {"timeline_samples": 1000, "event_count": 1, "window_count": 1, "resource_alignment_mode": "strict/clock-anchored", "resource_samples": 200},
                "bad_algo": {"timeline_samples": 400, "event_count": 1, "window_count": 1, "resource_alignment_mode": "trajectory-only", "resource_samples": 0},
            },
        },
    )
    _write_json(
        source / "metrics/phase_analysis.json",
        {"schema_version": 1, "baseline": "fast_livo2", "time_alignment_mode": "trajectory-only", "phases": [{"id": "phase_000", "state": "STRAIGHT"}], "algorithms": {}},
    )
    return frozen


def _semantic_report(run: Path, baseline="fast_livo2"):
    assert run.name == "source"
    assert baseline == "fast_livo2"
    return {
        "schema_version": 3,
        "run_id": "run-001",
        "run_state": "COMPLETED",
        "baseline": baseline,
        "metric_class": "relative-to-baseline/diagnostic/non-ground-truth",
        "ground_truth_available": False,
        "dataset": {"duration_s": 100.0, "ground_truth": None},
        "algorithms": [
            {
                "algorithm": "fast_livo2",
                "status": "SUCCESS",
                "health_flags": [],
                "health_pass": True,
                "trajectory_health_pass": True,
                "map_health_pass": None,
                "map_health_flags": [],
                "recommendation_eligible": True,
                "trajectory": {"duration_s": 100.0, "path_length_m": 50.0, "z_range_m": 0.5},
                "resource": {"mean_cpu_percent": 120.0, "peak_rss_mib": 500.0},
                "relative_to_baseline": {"rmse_m": 0.0, "p95_m": 0.0, "metric_class": "relative-to-baseline/diagnostic/non-ground-truth"},
                "map": {"available": False},
                "trajectory_diagnostics": {"position_jump_count": 0, "yaw_jump_count": 1},
            },
            {
                "algorithm": "bad_algo",
                "status": "FAILED",
                "health_flags": ["trajectory_short"],
                "health_pass": False,
                "trajectory_health_pass": False,
                "map_health_pass": None,
                "map_health_flags": [],
                "recommendation_eligible": False,
                "trajectory": {"duration_s": 40.0, "path_length_m": 20.0, "z_range_m": 3.0},
                "resource": {},
                "relative_to_baseline": {"rmse_m": 1.5, "p95_m": 2.0, "metric_class": "relative-to-baseline/diagnostic/non-ground-truth"},
                "map": {"available": False},
                "trajectory_diagnostics": {"position_jump_count": 1, "yaw_jump_count": 0},
            },
        ],
        "recommendations": {"health_valid_algorithms": ["fast_livo2"], "closest_to_baseline": None, "not_recommended_this_run": ["bad_algo"]},
        "limitations": ["existing semantic limitation"],
    }


def test_build_report_data_reuses_frozen_source_semantics_and_registers_root_json(tmp_path):
    frozen = _make_frozen(tmp_path)
    result = build_report_data(frozen, semantic_builder=_semantic_report)
    data = result["report_data"]
    assert data["schema_version"] == 1
    assert data["experiment"]["run_id"] == "run-001"
    assert data["experiment"]["generated_at_utc"] == "2026-08-31T09:00:00+00:00"
    assert data["metric_class"] == "relative-to-baseline/diagnostic/non-ground-truth"
    assert data["ground_truth_available"] is False
    assert data["calibration"]["source"] == "test calibration"
    assert data["algorithm_provenance"]["bad_algo"]["commit"] == "b1"
    assert data["runtime_health"]["bad_algo"]["status"] == "FAILED"
    assert data["trajectory_summary"]["fast_livo2"]["path_length_m"] == 50.0
    assert data["baseline_relative_diagnostics"]["bad_algo"]["rmse_m"] == 1.5
    assert data["phase_summary"]["available"] is True
    assert data["anomaly_summary"]["selected_window_ids"] == [
        "fast_livo2:window_0001",
        "bad_algo:window_0001",
    ]
    assert "not ATE/RPE" in data["ground_truth_disclaimer"]
    assert data["evidence_based_conclusions"]["scope"] == "baseline-relative diagnostic only"
    assert data["reproducibility_checklist"]["dataset_sha256_recorded"] is True
    assert data["optional_evidence"]["pointcloud_index"] is False
    assert (frozen / "report_data.json").is_file()
    manifest = json.loads((frozen / "freeze_manifest.json").read_text())
    assert manifest["freeze_state"] == "INCOMPLETE"
    assert manifest["selected_anomaly_window_ids"] == data["anomaly_summary"]["selected_window_ids"]
    assert any(
        item["path"] == "report_data.json" and item["role"] == "shared_report_data"
        for item in manifest["generated_artifacts"]
    )


def test_build_report_data_refuses_complete_bundle(tmp_path):
    frozen = _make_frozen(tmp_path)
    manifest_path = frozen / "freeze_manifest.json"
    payload = json.loads(manifest_path.read_text())
    payload["freeze_state"] = "COMPLETE"
    manifest_path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="already COMPLETE"):
        build_report_data(frozen, semantic_builder=_semantic_report)
