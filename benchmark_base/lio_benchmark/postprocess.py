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
    viewer_mode: str = "native",
    viewer_algorithms: str | None = None,
    viewer_language: str = "zh-CN",
    viewer_with_maps: bool = True,
    viewer_pointcloud_mode: str = "anomaly",
    viewer_pointcloud_period_s: float = 1.0,
    viewer_point_step: int = 20,
    viewer_point_lods: str = "10,20,80",
    viewer_world_pointcloud_mode: str = "anomaly",
    viewer_world_algorithm: str | None = None,
    viewer_map_point_step: int = 4,
    viewer_web_profile: str = "full",
    viewer_save: Path | None = None,
    viewer_spawn: bool = True,
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
        "viewer",
    }
    if stage not in allowed:
        raise ValueError(f"unknown postprocess stage: {stage}")
    if scan_step < 1 or point_step < 1 or voxel <= 0:
        raise ValueError("scan_step and point_step must be >= 1; voxel must be > 0")
    if diagnostic_hz <= 0:
        raise ValueError("diagnostic_hz must be > 0")
    if anomaly_window_gap_s < 0:
        raise ValueError("anomaly_window_gap_s must be >= 0")
    if viewer_mode not in {"native", "web"}:
        raise ValueError("viewer_mode must be native or web")
    if viewer_language not in {"zh-CN", "en"}:
        raise ValueError("viewer_language must be zh-CN or en")
    if viewer_pointcloud_mode not in {"none", "anomaly", "sampled"}:
        raise ValueError("viewer_pointcloud_mode must be none, anomaly, or sampled")
    if viewer_world_pointcloud_mode not in {"none", "anomaly", "sampled"}:
        raise ValueError("viewer_world_pointcloud_mode must be none, anomaly, or sampled")
    if viewer_pointcloud_period_s <= 0 or viewer_point_step < 1 or viewer_map_point_step < 1:
        raise ValueError("viewer pointcloud period must be >0 and viewer point steps must be >=1")
    if not str(viewer_point_lods).strip():
        raise ValueError("viewer_point_lods must not be empty")
    if viewer_mode == "web" and viewer_save is not None:
        raise ValueError("web viewer mode does not support --save; use native mode for .rrd output")

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

    if stage == "viewer":
        script = "rerun_diagnostic_viewer.py" if viewer_mode == "native" else "web_diagnostic_viewer.py"
        command = _python(
            script,
            "--run", run,
            "--baseline", baseline,
            "--lang", viewer_language,
            "--pointcloud-mode", viewer_pointcloud_mode,
            "--pointcloud-period", viewer_pointcloud_period_s,
            "--point-step", viewer_point_step,
            "--point-lods", viewer_point_lods,
            "--world-pointcloud-mode", viewer_world_pointcloud_mode,
            "--map-point-step", viewer_map_point_step,
        )
        if viewer_algorithms:
            command.extend(["--algorithms", str(viewer_algorithms)])
        if viewer_world_algorithm:
            command.extend(["--world-algorithm", str(viewer_world_algorithm)])
        if not viewer_with_maps:
            command.append("--no-maps")
        if viewer_mode == "native":
            if viewer_save is not None:
                command.extend(["--save", str(viewer_save)])
            if not viewer_spawn:
                command.append("--no-spawn")
        else:
            command.extend(["--web-profile", str(viewer_web_profile)])
            if not viewer_spawn:
                command.append("--no-browser")
        return [command]

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
    viewer_mode: str = "native",
    viewer_algorithms: str | None = None,
    viewer_language: str = "zh-CN",
    viewer_with_maps: bool = True,
    viewer_pointcloud_mode: str = "anomaly",
    viewer_pointcloud_period_s: float = 1.0,
    viewer_point_step: int = 20,
    viewer_point_lods: str = "10,20,80",
    viewer_world_pointcloud_mode: str = "anomaly",
    viewer_world_algorithm: str | None = None,
    viewer_map_point_step: int = 4,
    viewer_web_profile: str = "full",
    viewer_save: Path | None = None,
    viewer_spawn: bool = True,
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
        viewer_mode=viewer_mode,
        viewer_algorithms=viewer_algorithms,
        viewer_language=viewer_language,
        viewer_with_maps=viewer_with_maps,
        viewer_pointcloud_mode=viewer_pointcloud_mode,
        viewer_pointcloud_period_s=viewer_pointcloud_period_s,
        viewer_point_step=viewer_point_step,
        viewer_point_lods=viewer_point_lods,
        viewer_world_pointcloud_mode=viewer_world_pointcloud_mode,
        viewer_world_algorithm=viewer_world_algorithm,
        viewer_map_point_step=viewer_map_point_step,
        viewer_web_profile=viewer_web_profile,
        viewer_save=viewer_save,
        viewer_spawn=viewer_spawn,
    )
    print(json.dumps({"stage": stage, "run": str(run), "dry_run": dry_run, "commands": commands}, ensure_ascii=False, indent=2))
    if dry_run:
        return 0
    for command in commands:
        result = subprocess.run(command, check=False)
        if result.returncode:
            return int(result.returncode)
    return 0
