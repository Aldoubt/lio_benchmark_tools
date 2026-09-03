import json
import types
from pathlib import Path

import numpy as np

from report_evidence import build_report_evidence


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _make_bundle(tmp_path: Path) -> tuple[Path, Path]:
    run = tmp_path / "live_run"
    run.mkdir()
    frozen = tmp_path / "frozen"
    (frozen / "source").mkdir(parents=True)
    _write_json(
        frozen / "freeze_manifest.json",
        {
            "freeze_state": "INCOMPLETE",
            "source_run": {"path": str(run), "run_id": "run-001", "state": "COMPLETED"},
            "baseline": "fast_livo2",
            "algorithms": ["fast_livo2", "bad", "ok"],
            "calibration": {
                "lidar_to_imu": {
                    "rotation": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
                    "translation": [0.0, 0.0, 0.0],
                }
            },
            "generated_artifacts": [],
        },
    )
    _write_json(
        frozen / "source/manifest.json",
        {
            "evaluation": {
                "minimum_range_m": 0.5,
                "maximum_range_m": 70.0,
                "max_pose_interpolation_gap_s": 0.25,
            }
        },
    )
    _write_json(
        frozen / "report_data.json",
        {
            "anomaly_summary": {
                "representative_cases": [
                    {
                        "window_id": "bad:window_0002",
                        "algorithm": "bad",
                        "types": ["position_jump"],
                        "severity": 4.0,
                        "view_start_bag_time_s": 20.0,
                        "view_end_bag_time_s": 21.0,
                    },
                    {
                        "window_id": "ok:window_0001",
                        "algorithm": "ok",
                        "types": ["yaw_jump"],
                        "severity": 3.0,
                        "view_start_bag_time_s": 10.0,
                        "view_end_bag_time_s": 11.0,
                    },
                ]
            },
            "optional_evidence": {"rerun_pointcloud": {"enabled": True, "omission_reason": None}},
        },
    )
    return frozen, run


def test_build_report_evidence_materializes_pointcloud_cases_when_source_is_usable(tmp_path, monkeypatch):
    frozen, run = _make_bundle(tmp_path)
    sqlite_db = run / "bag.db3"
    sqlite_db.write_bytes(b"sqlite")
    _write_json(
        run / "metrics/pointcloud_frame_index.json",
        {
            "sqlite_db": str(sqlite_db),
            "lidar_topic": "/livox/lidar",
            "lidar_type": "livox_ros_driver2/msg/CustomMsg",
            "frames": [
                {"message_id": 10, "bag_time_s": 10.5},
                {"message_id": 20, "bag_time_s": 20.5},
            ],
        },
    )
    scans = {
        10.5: types.SimpleNamespace(
            bag_time_s=10.5,
            points_xyz=np.asarray([[1.0, 0.0, 0.0], [2.0, 0.2, 0.0]]),
            point_times_s=np.asarray([100.0, 100.01]),
            intensity=np.asarray([10.0, 20.0]),
        ),
        20.5: types.SimpleNamespace(
            bag_time_s=20.5,
            points_xyz=np.asarray([[1.0, 0.0, 0.0], [2.0, -0.2, 0.0]]),
            point_times_s=np.asarray([200.0, 200.01]),
            intensity=np.asarray([30.0, 40.0]),
        ),
    }
    projected_algorithms = []

    def nearest_frame(frames, target):
        return min(frames, key=lambda item: abs(float(item["bag_time_s"]) - float(target)))

    def read_scans(sqlite, topic, topic_type, frames, **kwargs):
        assert Path(sqlite) == sqlite_db
        assert topic == "/livox/lidar"
        return [scans[float(frame["bag_time_s"])] for frame in frames]

    def projection_context(source_run, algorithms, baseline):
        assert source_run == run.resolve()
        trajectories = {algorithm: algorithm for algorithm in algorithms}
        alignments = {algorithm: (np.eye(3), np.zeros(3)) for algorithm in algorithms}
        return trajectories, alignments, np.zeros(3)

    def project(points, point_times, trajectory, *args, **kwargs):
        projected_algorithms.append(trajectory)
        offset = 0.0 if trajectory == "fast_livo2" else 1.0
        values = np.asarray(points, dtype=float) + np.asarray([offset, 0.0, 0.0])
        return values, np.ones(len(values), dtype=bool)

    monkeypatch.setattr(
        "report_evidence._pointcloud_runtime_api",
        lambda: (nearest_frame, read_scans, projection_context, project),
    )

    def fake_figure(path, **kwargs):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")

    monkeypatch.setattr("report_evidence._write_pointcloud_case_figure", fake_figure)
    result = build_report_evidence(frozen)

    pointcloud = result["manifest"]["pointcloud_case_evidence"]
    assert pointcloud["available"] is True
    assert [item["window_id"] for item in pointcloud["cases"]] == [
        "bad:window_0002",
        "ok:window_0001",
    ]
    assert projected_algorithms.count("fast_livo2") == 2
    assert "bad" in projected_algorithms and "ok" in projected_algorithms
    registered = {
        item["path"]
        for item in json.loads((frozen / "freeze_manifest.json").read_text())["generated_artifacts"]
    }
    assert "evidence/anomalies/case_01_bad_window_0002_pointcloud.png" in registered
    assert "evidence/anomalies/case_02_ok_window_0001_pointcloud.png" in registered


def test_build_report_evidence_discloses_pointcloud_render_failure_without_failing_freeze(tmp_path, monkeypatch):
    frozen, _ = _make_bundle(tmp_path)
    monkeypatch.setattr(
        "report_evidence._render_pointcloud_cases",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("ROS runtime unavailable")),
    )

    result = build_report_evidence(frozen)

    pointcloud = result["manifest"]["pointcloud_case_evidence"]
    assert pointcloud["available"] is False
    assert pointcloud["source_available"] is True
    assert pointcloud["reason"].startswith("static_pointcloud_render_failed:RuntimeError:")
