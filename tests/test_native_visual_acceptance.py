import json
from pathlib import Path

from freeze_rerun import ensure_pointcloud_source
from rerun_diagnostic_viewer import select_environment_preview_frames
from viewer_i18n import native_viewer_language


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_native_viewer_uses_ascii_safe_display_language_for_chinese_reports():
    assert native_viewer_language("zh-CN") == "en"
    assert native_viewer_language("en") == "en"


def test_environment_preview_is_sampled_only_when_static_maps_are_missing():
    frames = [
        {"message_id": index, "bag_time_s": float(index)}
        for index in range(11)
    ]

    preview = select_environment_preview_frames(
        frames,
        static_map_count=0,
        period_s=5.0,
    )
    assert [item["message_id"] for item in preview] == [0, 5, 10]

    assert select_environment_preview_frames(
        frames,
        static_map_count=2,
        period_s=5.0,
    ) == []


def test_historical_pointcloud_index_is_derived_inside_frozen_source(tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "metrics").mkdir(parents=True)
    frozen = tmp_path / "frozen"
    source = frozen / "source"
    source.mkdir(parents=True)
    _write_json(
        frozen / "freeze_manifest.json",
        {
            "schema_version": 1,
            "freeze_state": "INCOMPLETE",
            "source_run": {"path": str(run), "run_id": "legacy", "state": "COMPLETED"},
            "compatibility_artifacts": [],
            "generated_artifacts": [],
        },
    )

    def fake_status(_run, *, index_root=None):
        root = Path(index_root).resolve() if index_root is not None else run.resolve()
        path = root / "metrics/pointcloud_frame_index.json"
        if path.is_file():
            return {
                "available": True,
                "reason": None,
                "index_path": str(path),
                "sqlite_db": "/source/bag.db3",
            }
        return {
            "available": False,
            "reason": "pointcloud_frame_index_missing",
            "index_path": None,
            "sqlite_db": None,
        }

    def fake_build(root):
        root = Path(root)
        _write_json(
            root / "metrics/pointcloud_frame_index.json",
            {
                "sqlite_db": "/source/bag.db3",
                "lidar_topic": "/livox/lidar",
                "lidar_type": "livox_ros_driver2/msg/CustomMsg",
                "frames": [{"message_id": 1, "bag_time_s": 0.0}],
            },
        )
        (root / "metrics/pointcloud_frame_index.csv").write_text(
            "message_id,bag_time_s\n1,0.0\n", encoding="utf-8"
        )
        return {
            "artifacts": [
                "metrics/pointcloud_frame_index.json",
                "metrics/pointcloud_frame_index.csv",
            ]
        }

    captured = []
    monkeypatch.setattr("freeze_rerun.pointcloud_source_status", fake_status)
    monkeypatch.setattr("freeze_rerun.build_pointcloud_frame_index", fake_build)
    monkeypatch.setattr(
        "freeze_rerun.register_compatibility_artifact",
        lambda _frozen, relative, role, derivation: captured.append(
            (relative, role, derivation)
        ) or {},
    )

    status = ensure_pointcloud_source(run, frozen)

    assert status["available"] is True
    assert status["index_source"] == "frozen/source"
    assert status["derived"] is True
    assert captured == [
        (
            "source/metrics/pointcloud_frame_index.json",
            "compatibility_derived_pointcloud_index",
            "source-bag-read-only-index-v1",
        ),
        (
            "source/metrics/pointcloud_frame_index.csv",
            "compatibility_derived_pointcloud_index",
            "source-bag-read-only-index-v1",
        ),
    ]
