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


def _diagnostic_timeline_command(
    run: Path,
    baseline: str,
    hz: float,
    window_gap_s: float,
) -> list[str]:
    return _python(
        "diagnostic_timeline.py",
        "--run", run,
        "--baseline", baseline,
        "--hz", hz,
        "--window-gap", window_gap_s,
    )


def build_stage_commands(
    run: Path,
    stage: str,
    *,
    with_maps: bool = False,
    baseline: str = "fast_livo2",
    no_plot: bool = False,
    phase_params: list[str] | None = None,
    scan_step: int = 5,
    point_step: int = 20,
    voxel: float = 0.12,
    diagnostic_hz: float = 10.0,
    anomaly_window_gap_s: float = 1.0,
    with_pointcloud_index: bool = False,
) -> list[list[str]]:
    """Build deterministic post-processing commands without executing them."""
    run = run.resolve()
    allowed = {
        "standardize",
        "evaluate",
        "visualize",
        "report",
        "compare",
        "phase-analysis",
        "diagnostics",
    }
    if stage not in allowed:
        raise ValueError(f"unknown postprocess stage: {stage}")
    if scan_step < 1 or point_step < 1 or voxel <= 0:
        raise ValueError("scan_step and point_step must be >= 1; voxel must be > 0")
    if diagnostic_hz <= 0:
        raise ValueError("diagnostic_hz must be > 0")
    if anomaly_window_gap_s < 0:
        raise ValueError("anomaly_window_gap_s must be >= 0")

    commands: list[list[str]] = []
    if stage == "phase-analysis":
        command = _python("phase_analysis.py", "--run", run, "--baseline", baseline)
        for value in phase_params or []:
            command.extend(["--phase-param", value])
        commands.append(command)
        if not no_plot:
            commands.append(_python("plot_phase_analysis.py", "--run", run))
        return commands

    if stage == "diagnostics":
        commands.append(_python("trajectory_discontinuity.py", "--run", run, "--baseline", baseline))
        commands.append(
            _diagnostic_timeline_command(
                run,
                baseline,
                diagnostic_hz,
                anomaly_window_gap_s,
            )
        )
        if with_pointcloud_index:
            commands.append(_python("pointcloud_frame_index.py", "--run", run))
        return commands

    metrics_ready = (run / "metrics" / "full_comparison.json").is_file()
    if stage in {"standardize", "evaluate"}:
        return [_summary_command(run)]

    if stage == "compare" or not metrics_ready:
        commands.append(_summary_command(run))

    if stage in {"visualize", "compare"}:
        commands.append(_python("plot_comparison_dashboard.py", "--run", run, "--baseline", baseline))
        commands.append(_python("plot_resource_curves.py", "--run", run))
        commands.append(_python("trajectory_discontinuity.py", "--run", run, "--baseline", baseline))
        commands.append(
            _diagnostic_timeline_command(
                run,
                baseline,
                diagnostic_hz,
                anomaly_window_gap_s,
            )
        )
        if with_maps:
            commands.append(_python(
                "reconstruct_comparison_maps.py",
                "--run", run,
                "--baseline", baseline,
                "--scan-step", scan_step,
                "--point-step", point_step,
                "--voxel", voxel,
            ))
            commands.append(_python(
                "enhance_map_comparison.py",
                "--run", run,
                "--baseline", baseline,
            ))

    if stage in {"report", "compare"}:
        command = _python(
            "current_run_report.py",
            "--run", run,
            "--baseline", baseline,
        )
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
    phase_params: list[str] | None = None,
    scan_step: int = 5,
    point_step: int = 20,
    voxel: float = 0.12,
    diagnostic_hz: float = 10.0,
    anomaly_window_gap_s: float = 1.0,
    with_pointcloud_index: bool = False,
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
        phase_params=phase_params,
        scan_step=scan_step,
        point_step=point_step,
        voxel=voxel,
        diagnostic_hz=diagnostic_hz,
        anomaly_window_gap_s=anomaly_window_gap_s,
        with_pointcloud_index=with_pointcloud_index,
    )
    print(json.dumps({"stage": stage, "run": str(run), "dry_run": dry_run, "commands": commands}, ensure_ascii=False, indent=2))
    if dry_run:
        return 0
    for command in commands:
        result = subprocess.run(command, check=False)
        if result.returncode:
            return int(result.returncode)
    return 0
