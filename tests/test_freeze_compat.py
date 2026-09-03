import json
from pathlib import Path

from freeze_compat import build_compat_diagnostic_timeline
from freeze_rerun import build_frozen_rerun


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_trajectory(path: Path, *, offset: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "timestamp_s,x_m,y_m,z_m,yaw_rad\n"
        f"100.0,{offset},0,0,0\n"
        f"101.0,{offset + 1.0},0,0,0\n"
        f"102.0,{offset + 2.0},0,0,0\n",
        encoding="utf-8",
    )


def test_compat_builder_materializes_unified_timeline_from_standardized_trajectories(tmp_path):
    source = tmp_path / "source"
    _write_json(
        source / "manifest.json",
        {"dataset": {"lidar_topic": "/livox/lidar"}, "algorithms": {"fast_livo2": {}, "dlio": {}}},
    )
    _write_trajectory(source / "standardized/trajectories/fast_livo2.csv")
    _write_trajectory(source / "standardized/trajectories/dlio.csv", offset=0.2)

    result = build_compat_diagnostic_timeline(
        source,
        algorithms=["fast_livo2", "dlio"],
        baseline="fast_livo2",
    )

    payload = json.loads((source / "metrics/diagnostic_timeline.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["algorithm_order"] == ["fast_livo2", "dlio"]
    assert payload["baseline"] == "fast_livo2"
    assert payload["compatibility_derivation"]["method"] == "standardized-trajectories-fixed-rate-v1"
    assert (source / "metrics/diagnostic_timeline/fast_livo2.csv").is_file()
    assert (source / "metrics/diagnostic_timeline/dlio.csv").is_file()
    assert result["derived"] is True
    assert set(result["artifacts"]) == {
        "metrics/diagnostic_timeline.json",
        "metrics/diagnostic_timeline/fast_livo2.csv",
        "metrics/diagnostic_timeline/dlio.csv",
    }


def test_frozen_rerun_uses_frozen_source_for_diagnostics_but_original_run_for_pointcloud(tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "metrics").mkdir(parents=True)
    frozen = tmp_path / "frozen"
    (frozen / "viewer").mkdir(parents=True)
    (frozen / "source").mkdir(parents=True)
    _write_json(
        frozen / "freeze_manifest.json",
        {
            "schema_version": 1,
            "freeze_state": "INCOMPLETE",
            "source_run": {"path": str(run), "run_id": "legacy-run", "state": "completed"},
            "baseline": "fast_livo2",
            "language": "zh-CN",
            "algorithms": ["fast_livo2"],
            "generated_artifacts": [],
        },
    )
    captured = {}

    def fake_builder(**kwargs):
        captured.update(kwargs)
        Path(kwargs["save"]).write_bytes(b"rrd")
        return {}

    monkeypatch.setattr(
        "freeze_rerun._viewer_api",
        lambda: (fake_builder, lambda _: {"dense": 10, "medium": 20, "sparse": 80}, "10,20,80"),
    )
    monkeypatch.setattr("freeze_rerun.finalize_saved_rerun_recording", lambda: "0.36.3")

    build_frozen_rerun(frozen)

    assert captured["run"] == run.resolve()
    assert captured["diagnostic_run"] == (frozen / "source").resolve()
