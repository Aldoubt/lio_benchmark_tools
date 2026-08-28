"""Post-processing orchestration for benchmark comparison and visualization."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVALUATORS = REPO_ROOT / "evaluators"


def _python(script: str, *args: object) -> list[str]:
    return [sys.executable, str(EVALUATORS / script), *(str(arg) for arg in args)]


def _summary_command(run: Path) -> list[str]:
    return _python("summarize_smoke_run.py", run, "--name", "full_comparison")


def build_stage_commands(
    run: Path,
    stage: str,
    *,
    with_maps: bool = False,
    baseline: str = "fast_livo2",
    no_plot: bool = False,
    scan_step: int = 5,
    point_step: int = 20,
    voxel: float = 0.12,
) -> list[list[str]]:
    """Build deterministic post-processing commands without executing them."""
    run = run.resolve()
    if stage not in {"standardize", "evaluate", "visualize", "report", "compare"}:
        raise ValueError(f"unknown postprocess stage: {stage}")
    if scan_step < 1 or point_step < 1 or voxel <= 0:
        raise ValueError("scan_step and point_step must be >= 1; voxel must be > 0")

    metrics_ready = (run / "metrics" / "full_comparison.json").is_file()
    commands: list[list[str]] = []
    if stage in {"standardize", "evaluate"}:
        return [_summary_command(run)]

    if stage == "compare" or not metrics_ready:
        commands.append(_summary_command(run))

    if stage in {"visualize", "compare"}:
        commands.append(_python("plot_comparison_dashboard.py", "--run", run, "--baseline", baseline))
        commands.append(_python("plot_resource_curves.py", "--run", run))
        if with_maps:
            commands.append(_python(
                "visualize_baseline_maps.py",
                "--run", run,
                "--baseline", baseline,
                "--scan-step", scan_step,
                "--point-step", point_step,
                "--voxel", voxel,
            ))

    if stage in {"report", "compare"}:
        command = _python("generate_comprehensive_report.py", "--run", run)
        if no_plot:
            command.append("--no-plot")
        commands.append(command)
    return commands


def execute_stage(
    run: Path,
    stage: str,
    *,
    dry_run: bool = False,
    with_maps: bool = False,
    baseline: str = "fast_livo2",
    no_plot: bool = False,
    scan_step: int = 5,
    point_step: int = 20,
    voxel: float = 0.12,
) -> int:
    run = run.resolve()
    if not run.is_dir():
        raise ValueError(f"run directory does not exist: {run}")
    if not (run / "manifest.json").is_file():
        raise ValueError(f"run is missing manifest.json: {run}")
    commands = build_stage_commands(
        run,
        stage,
        with_maps=with_maps,
        baseline=baseline,
        no_plot=no_plot,
        scan_step=scan_step,
        point_step=point_step,
        voxel=voxel,
    )
    print(json.dumps({"stage": stage, "run": str(run), "dry_run": dry_run, "commands": commands}, ensure_ascii=False, indent=2))
    if dry_run:
        return 0
    for command in commands:
        result = subprocess.run(command, check=False)
        if result.returncode:
            return int(result.returncode)
    return 0
