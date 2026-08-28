#!/usr/bin/env python3
"""Generate a comprehensive report using only the current run's artifacts.

All trajectory/resource/map/diagnostic values come from the selected run.
Without independent ground truth, baseline-relative quantities remain
relative-to-baseline/diagnostic/non-ground-truth and are not ATE/RPE.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path
from typing import Any

from plot_comparison_dashboard import align_candidate_to_baseline, load_trajectory


LABELS = {
    "kiss_icp": "KISS-ICP",
    "mola_lo": "MOLA-LO",
    "mola_lio": "MOLA-LIO",
    "fast_livo2": "FAST-LIVO2",
    "point_lio": "Point-LIO",
    "dlio": "DLIO",
    "glim_odometry": "GLIM odometry",
    "glim_full_slam": "GLIM full SLAM",
    "lio_sam_no_loop": "LIO-SAM no-loop",
    "lio_sam_loop": "LIO-SAM loop",
}

METRIC_CLASS = "relative-to-baseline/diagnostic/non-ground-truth"


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def health_valid(item: dict[str, Any]) -> bool:
    return item.get("status") == "SUCCESS" and not list(item.get("health_flags") or [])


def _format(value: Any, digits: int = 3) -> str:
    if value is None or value == "":
        return "N/A"
    return f"{float(value):.{digits}f}"


def _algorithm_config(manifest: dict[str, Any], algorithm: str) -> dict[str, Any]:
    algorithms = manifest.get("algorithms") or {}
    if not isinstance(algorithms, dict):
        return {}
    value = algorithms.get(algorithm) or {}
    return value if isinstance(value, dict) else {}


def _map_items(run: Path) -> dict[str, dict[str, Any]]:
    """Prefer enhanced current-run map metrics, then legacy current-run metadata."""
    output = run / "figures" / "fast_livo2_baseline_maps"
    enhanced = load_json(output / "map_comparison_metrics.json", {}) or {}
    items = enhanced.get("algorithms") or {}
    if isinstance(items, dict) and items:
        return items

    legacy = load_json(output / "visualization_metadata.json", {}) or {}
    maps = legacy.get("maps") or {}
    if not isinstance(maps, dict):
        return {}
    return {
        algorithm: {"available": True, **item}
        for algorithm, item in maps.items()
        if isinstance(item, dict)
    }


def _trajectory_diagnostics(run: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(run / "metrics" / "trajectory_discontinuity.json", {}) or {}
    items = payload.get("algorithms") or {}
    return items if isinstance(items, dict) else {}


def _relative_metrics(
    run: Path,
    algorithms: list[str],
    baseline: str,
) -> dict[str, dict[str, Any]]:
    """Recompute whole-run baseline-relative RMSE/P95 from current CSVs."""
    trajectory_dir = run / "standardized" / "trajectories"
    baseline_path = trajectory_dir / f"{baseline}.csv"
    if not baseline_path.is_file():
        return {}

    baseline_trajectory = load_trajectory(baseline_path)
    metrics: dict[str, dict[str, Any]] = {}
    for algorithm in algorithms:
        path = trajectory_dir / f"{algorithm}.csv"
        if not path.is_file():
            continue
        if algorithm == baseline:
            metrics[algorithm] = {
                "rmse_m": 0.0,
                "p95_m": 0.0,
                "metric_class": METRIC_CLASS,
            }
            continue
        try:
            _, alignment = align_candidate_to_baseline(
                baseline_trajectory,
                load_trajectory(path),
            )
        except (KeyError, OSError, ValueError):
            continue
        metrics[algorithm] = {
            "rmse_m": alignment.get("relative_rmse_m"),
            "p95_m": alignment.get("relative_p95_m"),
            "metric_class": METRIC_CLASS,
        }
    return metrics


def _best_algorithm(
    rows: list[dict[str, Any]],
    field: str,
    *,
    section: str,
    baseline: str,
    exclude_baseline: bool = False,
) -> str | None:
    candidates: list[tuple[float, str]] = []
    for row in rows:
        if not row.get("recommendation_eligible", row.get("health_pass", False)):
            continue
        if exclude_baseline and row["algorithm"] == baseline:
            continue
        value = (row.get(section) or {}).get(field)
        if value is None:
            continue
        candidates.append((float(value), row["algorithm"]))
    return min(candidates)[1] if candidates else None


def build_report(run: Path, baseline: str = "fast_livo2") -> dict[str, Any]:
    run = Path(run).resolve()
    manifest = load_json(run / "manifest.json", {}) or {}
    comparison = load_json(run / "metrics" / "full_comparison.json", {}) or {}
    run_status = load_json(run / "metadata" / "run_status.json", {}) or {}

    comparison_items = [
        item
        for item in comparison.get("algorithms", []) or []
        if isinstance(item, dict) and item.get("algorithm")
    ]
    algorithms = [str(item["algorithm"]) for item in comparison_items]
    relative = _relative_metrics(run, algorithms, baseline)
    maps = _map_items(run)
    discontinuities = _trajectory_diagnostics(run)

    rows: list[dict[str, Any]] = []
    for item in comparison_items:
        algorithm = str(item["algorithm"])
        trajectory = item.get("trajectory") or {}
        resource = item.get("resource_monitor") or item.get("resource") or {}
        trajectory_valid = health_valid(item)
        map_item = dict(maps.get(algorithm) or {})
        map_item.setdefault("available", bool(map_item))
        map_health_pass = (
            bool(map_item.get("map_health_pass"))
            if map_item.get("available") and "map_health_pass" in map_item
            else None
        )
        map_health_flags = list(map_item.get("map_health_flags") or [])
        recommendation_eligible = trajectory_valid and map_health_pass is not False
        rows.append(
            {
                "algorithm": algorithm,
                "label": LABELS.get(algorithm, algorithm),
                "group": _algorithm_config(manifest, algorithm).get("group"),
                "status": item.get("status"),
                "health_flags": list(item.get("health_flags") or []),
                "health_pass": trajectory_valid,
                "trajectory_health_pass": trajectory_valid,
                "map_health_pass": map_health_pass,
                "map_health_flags": map_health_flags,
                "recommendation_eligible": recommendation_eligible,
                "trajectory": trajectory,
                "resource": resource,
                "relative_to_baseline": relative.get(
                    algorithm,
                    {
                        "rmse_m": None,
                        "p95_m": None,
                        "metric_class": METRIC_CLASS,
                    },
                ),
                "map": map_item,
                "trajectory_diagnostics": dict(discontinuities.get(algorithm) or {}),
            }
        )

    full_slam_candidates = [
        row["algorithm"]
        for row in rows
        if row["recommendation_eligible"] and row.get("group") == "full_slam"
    ]
    recommendations = {
        "health_valid_algorithms": [
            row["algorithm"] for row in rows if row["trajectory_health_pass"]
        ],
        "map_consistent_algorithms": [
            row["algorithm"]
            for row in rows
            if row["trajectory_health_pass"]
            and row["map"].get("available")
            and row["map_health_pass"] is True
        ],
        "closest_to_baseline": _best_algorithm(
            rows,
            "rmse_m",
            section="relative_to_baseline",
            baseline=baseline,
            exclude_baseline=True,
        ),
        "lowest_z_range": _best_algorithm(
            rows,
            "z_range_m",
            section="trajectory",
            baseline=baseline,
        ),
        "lowest_mean_cpu": _best_algorithm(
            rows,
            "mean_cpu_percent",
            section="resource",
            baseline=baseline,
        ),
        "lowest_peak_rss": _best_algorithm(
            rows,
            "peak_rss_mib",
            section="resource",
            baseline=baseline,
        ),
        "full_slam_candidates": full_slam_candidates,
        "not_recommended_this_run": [
            row["algorithm"] for row in rows if not row["recommendation_eligible"]
        ],
    }

    dataset = manifest.get("dataset") or {}
    return {
        "schema_version": 3,
        "report_type": "current_run_comprehensive_lio_comparison",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "run": str(run),
        "run_id": run_status.get("run_id", run.name),
        "run_state": run_status.get("state"),
        "baseline": baseline,
        "metric_class": METRIC_CLASS,
        "ground_truth_available": bool(dataset.get("ground_truth")),
        "playback_rate": manifest.get("playback_rate"),
        "dataset": dataset,
        "algorithms": rows,
        "recommendations": recommendations,
        "visualization": {
            "comparison_dashboard": str(run / "figures" / "comparison_dashboard"),
            "resource_curves": str(run / "figures" / "resource_curves"),
            "map_comparison": str(run / "figures" / "fast_livo2_baseline_maps"),
            "trajectory_discontinuity": str(run / "figures" / "trajectory_discontinuity"),
        },
        "limitations": [
            "No independent ground truth: baseline-relative metrics are diagnostic, not ATE/RPE or absolute accuracy.",
            "Map comparison uses the same raw LiDAR input reconstructed with each standardized trajectory; it is a trajectory-induced map-consistency proxy, not native mapper quality.",
            "Map-health thresholds are conservative current-run diagnostics and are reported separately from trajectory lifecycle/health.",
            "Trajectory discontinuity events are diagnostic; a loop-closure correction can be a legitimate pose jump and does not automatically fail trajectory health.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    dataset = report.get("dataset") or {}
    lines = [
        f"# LIO 当前 Run 综合对比报告：{report['run_id']}",
        "",
        f"- Run state: `{report.get('run_state')}`",
        f"- Baseline: `{report['baseline']}`",
        f"- Metric class: `{report['metric_class']}`",
        f"- Dataset duration: `{_format(dataset.get('duration_s'), 2)} s`",
        (
            "- Independent ground truth: `yes`"
            if report.get("ground_truth_available")
            else "- Independent ground truth: `no`"
        ),
        "",
        "> 相对 RMSE/P95 仅表示与 baseline 的轨迹一致性，不是 ATE/RPE 或绝对精度排名。",
        "",
        "## 当前 run 数据",
        "",
        "| Algorithm | Status | Traj health | Eligible | Duration (s) | Path (m) | Z range (m) | Mean CPU (%) | Peak RSS (MiB) | Rel. RMSE (m) | Rel. P95 (m) |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["algorithms"]:
        trajectory = row["trajectory"]
        resource = row["resource"]
        relative = row["relative_to_baseline"]
        health = (
            "normal"
            if row["trajectory_health_pass"]
            else ";".join(row["health_flags"]) or "needs_review"
        )
        lines.append(
            f"| {row['label']} | {row['status']} | {health} | "
            f"{'yes' if row['recommendation_eligible'] else 'no'} | "
            f"{_format(trajectory.get('duration_s'), 2)} | "
            f"{_format(trajectory.get('path_length_m'), 2)} | "
            f"{_format(trajectory.get('z_range_m'), 3)} | "
            f"{_format(resource.get('mean_cpu_percent'), 1)} | "
            f"{_format(resource.get('peak_rss_mib'), 1)} | "
            f"{_format(relative.get('rmse_m'), 3)} | "
            f"{_format(relative.get('p95_m'), 3)} |"
        )

    lines.extend(
        [
            "",
            "## 地图一致性与轨迹跳变诊断",
            "",
            "| Algorithm | Map health | Robust Z span (m) | Voxel IoU | Sym NN P95 (m) | Pos jumps | Yaw jumps | Max Δpos (m) | Max Δyaw (deg) |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in report["algorithms"]:
        map_item = row["map"]
        diagnostics = row["trajectory_diagnostics"]
        robust = map_item.get("robust_extent_xyz_m") or []
        robust_z = robust[2] if len(robust) >= 3 else None
        if not map_item.get("available"):
            map_health = "N/A"
        elif row["map_health_pass"] is True:
            map_health = "normal"
        elif row["map_health_pass"] is False:
            map_health = ";".join(row["map_health_flags"]) or "needs_review"
        else:
            map_health = "legacy/unscored"
        lines.append(
            f"| {row['label']} | {map_health} | "
            f"{_format(robust_z, 3)} | "
            f"{_format(map_item.get('baseline_voxel_iou'), 3)} | "
            f"{_format(map_item.get('symmetric_nn_p95_m'), 3)} | "
            f"{diagnostics.get('position_jump_count', 'N/A')} | "
            f"{diagnostics.get('yaw_jump_count', 'N/A')} | "
            f"{_format(diagnostics.get('max_position_step_m'), 3)} | "
            f"{_format(diagnostics.get('max_yaw_step_deg'), 3)} |"
        )

    recommendations = report["recommendations"]
    lines.extend(
        [
            "",
            "## 数据驱动候选视图",
            "",
            f"- 与 `{report['baseline']}` 最接近（排除 baseline）：`{recommendations.get('closest_to_baseline') or 'N/A'}`",
            f"- 当前地图一致性通过：`{', '.join(recommendations.get('map_consistent_algorithms') or []) or 'N/A'}`",
            f"- 候选中最低 Z range：`{recommendations.get('lowest_z_range') or 'N/A'}`",
            f"- 候选中最低平均 CPU：`{recommendations.get('lowest_mean_cpu') or 'N/A'}`",
            f"- 候选中最低峰值 RSS：`{recommendations.get('lowest_peak_rss') or 'N/A'}`",
            "- 当前 full-SLAM 候选：`"
            + (", ".join(recommendations.get("full_slam_candidates") or []) or "N/A")
            + "`",
            "- 本轮不进入推荐集：`"
            + (", ".join(recommendations.get("not_recommended_this_run") or []) or "none")
            + "`",
            "",
            "这些维度是不同工程目标下的筛选视图，不构成绝对精度总排名。",
            "",
            "## 可视化",
            "",
            "- `figures/fast_livo2_baseline_maps/`：统一尺度 XY/XZ 地图主图与 `*_all` 失败诊断图。",
            "- `figures/trajectory_discontinuity/`：逐样本位置/航向跳变随 rosbag 时间的诊断图。",
            "- `metrics/trajectory_discontinuity/<algorithm>.csv`：后续交互前端可直接使用的带时间戳逐步诊断序列。",
            "",
            "## 限制",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


def write_outputs(run: Path, report: dict[str, Any]) -> None:
    reports = Path(run) / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "comprehensive_comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (reports / "comprehensive_comparison.md").write_text(
        render_markdown(report),
        encoding="utf-8",
    )

    fields = [
        "algorithm",
        "status",
        "trajectory_health",
        "map_health",
        "recommendation_eligible",
        "relative_rmse_m",
        "relative_p95_m",
        "duration_s",
        "path_length_m",
        "z_range_m",
        "mean_cpu_percent",
        "peak_rss_mib",
        "map_points",
        "robust_z_span_m",
        "baseline_voxel_iou",
        "symmetric_nn_p95_m",
        "position_jump_count",
        "yaw_jump_count",
        "max_position_step_m",
        "max_yaw_step_deg",
    ]
    with (reports / "comprehensive_comparison.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in report["algorithms"]:
            map_item = row["map"]
            diagnostics = row["trajectory_diagnostics"]
            robust = map_item.get("robust_extent_xyz_m") or []
            writer.writerow(
                {
                    "algorithm": row["algorithm"],
                    "status": row["status"],
                    "trajectory_health": (
                        "normal"
                        if row["trajectory_health_pass"]
                        else ";".join(row["health_flags"])
                    ),
                    "map_health": (
                        "N/A"
                        if not map_item.get("available")
                        else (
                            "normal"
                            if row["map_health_pass"] is True
                            else ";".join(row["map_health_flags"])
                        )
                    ),
                    "recommendation_eligible": row["recommendation_eligible"],
                    "relative_rmse_m": row["relative_to_baseline"].get("rmse_m"),
                    "relative_p95_m": row["relative_to_baseline"].get("p95_m"),
                    "duration_s": row["trajectory"].get("duration_s"),
                    "path_length_m": row["trajectory"].get("path_length_m"),
                    "z_range_m": row["trajectory"].get("z_range_m"),
                    "mean_cpu_percent": row["resource"].get("mean_cpu_percent"),
                    "peak_rss_mib": row["resource"].get("peak_rss_mib"),
                    "map_points": map_item.get("map_points") if map_item.get("available") else None,
                    "robust_z_span_m": robust[2] if len(robust) >= 3 else None,
                    "baseline_voxel_iou": map_item.get("baseline_voxel_iou"),
                    "symmetric_nn_p95_m": map_item.get("symmetric_nn_p95_m"),
                    "position_jump_count": diagnostics.get("position_jump_count"),
                    "yaw_jump_count": diagnostics.get("yaw_jump_count"),
                    "max_position_step_m": diagnostics.get("max_position_step_m"),
                    "max_yaw_step_deg": diagnostics.get("max_yaw_step_deg"),
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--baseline", default="fast_livo2")
    parser.add_argument(
        "--no-plot",
        action="store_true",
        help="Accepted for postprocess compatibility; this report generator is text/JSON/CSV only.",
    )
    args = parser.parse_args()

    report = build_report(args.run, args.baseline)
    write_outputs(args.run, report)
    print(
        json.dumps(
            {
                "report": str(args.run / "reports" / "comprehensive_comparison.md"),
                "algorithms": len(report["algorithms"]),
                "metric_class": METRIC_CLASS,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
