import json
from pathlib import Path

from reconstruct_comparison_maps import discover_reconstructable_algorithms


def test_reconstruction_uses_all_standardized_trajectories_not_only_success(tmp_path):
    run = tmp_path / "run"
    trajectory_dir = run / "standardized" / "trajectories"
    trajectory_dir.mkdir(parents=True)
    for algorithm in ("fast_livo2", "point_lio", "dlio"):
        (trajectory_dir / f"{algorithm}.csv").write_text("placeholder\n", encoding="utf-8")

    comparison = {
        "algorithms": [
            {"algorithm": "fast_livo2", "status": "SUCCESS", "health_flags": []},
            {"algorithm": "point_lio", "status": "SUCCESS", "health_flags": []},
            {
                "algorithm": "dlio",
                "status": "RUNTIME_CRASH",
                "health_flags": ["trajectory_short"],
            },
            {"algorithm": "missing_csv", "status": "SUCCESS", "health_flags": []},
        ]
    }

    selected = discover_reconstructable_algorithms(run, comparison)
    assert selected == ["fast_livo2", "point_lio", "dlio"]
