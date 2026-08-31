import datetime as dt
import json
from pathlib import Path

import pytest

from freeze_experiment import prepare_freeze


def _make_core_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    (run / "metadata").mkdir(parents=True)
    (run / "metrics/diagnostic_timeline").mkdir(parents=True)
    (run / "standardized/trajectories").mkdir(parents=True)
    manifest = {
        "dataset": {"bag_dir": str(tmp_path / "bag"), "ground_truth": None},
        "evaluation": {"ground_truth_available": False},
        "algorithms": {"fast_livo2": {"commit": "abc"}},
    }
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "metadata/run_status.json").write_text(
        json.dumps({"run_id": "run-001", "state": "COMPLETED"}), encoding="utf-8"
    )
    (run / "metrics/full_comparison.json").write_text("{}", encoding="utf-8")
    (run / "metrics/trajectory_discontinuity.json").write_text("{}", encoding="utf-8")
    (run / "metrics/diagnostic_timeline.json").write_text(
        json.dumps({"algorithm_order": ["fast_livo2"], "anomaly_windows": []}), encoding="utf-8"
    )
    (run / "standardized/trajectories/fast_livo2.csv").write_text(
        "timestamp,x,y,z\n0,0,0,0\n", encoding="utf-8"
    )
    (run / "metrics/diagnostic_timeline/fast_livo2.csv").write_text(
        "bag_time_s,x_m,y_m,z_m\n0,0,0,0\n", encoding="utf-8"
    )
    bag = tmp_path / "bag"
    bag.mkdir()
    (bag / "metadata.yaml").write_text("bag", encoding="utf-8")
    return run


def test_prepare_freeze_preserves_auditable_incomplete_manifest_when_dataset_hashing_fails(tmp_path, monkeypatch):
    run = _make_core_run(tmp_path)
    bag = tmp_path / "bag"
    for child in bag.iterdir():
        child.unlink()
    bag.rmdir()
    monkeypatch.setattr(
        "freeze_experiment.resolve_git_identity",
        lambda _: {"branch": "feat/test", "commit": "0123456789abcdef", "short_sha": "01234567"},
    )
    created = dt.datetime(2026, 8, 30, 15, 40, 5, tzinfo=dt.timezone.utc)

    with pytest.raises(FileNotFoundError, match="dataset bag_dir"):
        prepare_freeze(
            run,
            baseline="fast_livo2",
            language="en",
            repo_root=tmp_path,
            created_at=created,
        )

    bundles = list((run / "frozen").iterdir())
    assert len(bundles) == 1
    payload = json.loads((bundles[0] / "freeze_manifest.json").read_text(encoding="utf-8"))
    assert payload["freeze_state"] == "INCOMPLETE"
    assert payload["failure"]["stage"] == "dataset_source"
    assert "does not exist" in payload["failure"]["message"]
