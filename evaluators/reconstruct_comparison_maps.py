#!/usr/bin/env python3
"""Reconstruct comparison maps for every available standardized trajectory.

The legacy map builder defaults to lifecycle SUCCESS runs.  For comparison
work we also want a truncated/crashed trajectory to remain visible in the
`*_all` diagnostic figures when it produced a usable standardized CSV.  This
wrapper discovers current-run CSVs and passes the explicit algorithm list to
`visualize_baseline_maps.py` without changing the reconstruction math.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def discover_reconstructable_algorithms(
    run: Path,
    comparison: dict[str, Any],
) -> list[str]:
    """Return current-run algorithms with standardized CSVs, preserving report order."""
    run = Path(run)
    trajectory_dir = run / "standardized" / "trajectories"
    available = {path.stem for path in trajectory_dir.glob("*.csv")}

    ordered = [
        str(item["algorithm"])
        for item in comparison.get("algorithms", []) or []
        if isinstance(item, dict)
        and item.get("algorithm")
        and str(item["algorithm"]) in available
    ]
    if ordered:
        return ordered
    return sorted(available)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--baseline", default="fast_livo2")
    parser.add_argument("--scan-step", type=int, default=5)
    parser.add_argument("--point-step", type=int, default=20)
    parser.add_argument("--voxel", type=float, default=0.12)
    args = parser.parse_args()

    run = args.run.resolve()
    comparison = load_json(run / "metrics" / "full_comparison.json", {}) or {}
    algorithms = discover_reconstructable_algorithms(run, comparison)
    if not algorithms:
        raise ValueError(f"no standardized trajectories found under {run}")
    if args.baseline not in algorithms:
        raise ValueError(
            f"baseline {args.baseline} has no standardized trajectory in {run}"
        )

    script = Path(__file__).resolve().with_name("visualize_baseline_maps.py")
    command = [
        sys.executable,
        str(script),
        "--run",
        str(run),
        "--baseline",
        args.baseline,
        "--scan-step",
        str(args.scan_step),
        "--point-step",
        str(args.point_step),
        "--voxel",
        str(args.voxel),
        "--algorithms",
        ",".join(algorithms),
    ]
    print(
        json.dumps(
            {
                "stage": "reconstruct-comparison-maps",
                "run": str(run),
                "algorithms": algorithms,
                "command": command,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    completed = subprocess.run(command, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
