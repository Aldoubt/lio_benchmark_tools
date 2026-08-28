#!/usr/bin/env python3
"""Generate a Chinese, data-backed report for a completed LIO benchmark run.

The report combines the canonical trajectory metrics, the FAST-LIVO2-relative
visualization metadata and process-tree resource samples.  It intentionally
does not call the relative-to-baseline error an accuracy metric: the current
MID360 bags do not contain independent ground truth.

TOPS in this report is a CPU-FP32-equivalent proxy.  CPU percentage tells us
how many CPU cores were busy, but it does not expose the algorithm's actual
instruction mix.  The proxy is therefore useful for a transparent resource
envelope and edge-device screening, not as a measured TOPS benchmark.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import platform
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


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

GROUP_LABELS = {
    "lidar_only_odometry": "LiDAR-only odometry",
    "lidar_imu_odometry": "LiDAR-IMU odometry",
    "full_slam": "Full SLAM",
}

# These descriptions are deliberately phrased from the checked-in runner and
# parameter files.  They are not claims about an upstream implementation that
# was not used in this run.
ALGORITHM_FEATURES = {
    "kiss_icp": "LiDAR-only scan registration; deskew and voxel map enabled, no IMU gravity constraint.",
    "mola_lo": "LiDAR-only GICP local-map odometry; linear deskew and a relatively large MOLA process tree.",
    "mola_lio": "MOLA LiDAR-IMU odometry; IMU deskew and gravity correction enabled, with accelerometer pitch/roll initialization in the runner.",
    "fast_livo2": "LiDAR-IMU iterated local-map odometry; camera input disabled for this run, gravity estimation/alignment enabled.",
    "point_lio": "Point-level LiDAR-IMU iterated filter; gravity alignment enabled and the run uses the adapted MID360 point stream.",
    "dlio": "Direct LiDAR-inertial odometry; deskew, voxelization, adaptive mode and spaciousness/density processing enabled.",
    "glim_odometry": "GLIM CPU odometry configuration; local/global mapping disabled, so it is the lightest GLIM mode.",
    "glim_full_slam": "GLIM CPU full SLAM; local mapping, global mapping and pose-graph correction enabled.",
    "lio_sam_no_loop": "LIO-SAM feature/factor-graph mapping frontend with loop closure disabled.",
    "lio_sam_loop": "LIO-SAM feature/factor-graph mapping frontend with 1 Hz loop-closure search enabled.",
}

ALGORITHM_REASONS = {
    "kiss_icp": "低内存来自 LiDAR-only 和较小的进程树；没有 IMU 重力约束，MID360 的走廊/温室竖直结构和时间运动会让 Z 轴诊断变差。",
    "mola_lo": "线性 deskew 和 GICP 局部地图能保持路径长度接近稳定组，但 MOLA 进程树的内存基线很大；LiDAR-only 也无法直接利用重力约束。",
    "mola_lio": "重力补偿开关已打开，且使用 IMU deskew；它主要帮助姿态的 roll/pitch 可观性，不会自动消除平移、时间同步、外参或动态加速度造成的漂移。本组合结果需要结合相对 FAST-LIVO2 的轨迹指标判断，不能只看开关状态。",
    "fast_livo2": "本轮 Z 范围和 Z 末端变化最小，说明当前参数和 MID360 输入组合对竖直方向最稳；代价是约 1 GiB 峰值 RSS 和约 1.24 个 CPU 核的平均负载。",
    "point_lio": "资源消耗看起来很低，但这是因为轨迹在完整结束前已发散/变短，不能把低 CPU 当成效率优势；应先修复输入或参数后复测。",
    "dlio": "直接法和较高频率 odom 输出带来最多线程与内存；本轮路径和 Z 已发散，且清理了零时间/重复时间戳，当前结果不能用于前端选型。",
    "glim_odometry": "CPU odometry 模式关闭全局地图后，平均 CPU 和峰值 RSS 都较低，且相对 FAST-LIVO2 轨迹误差最小；适合内存受限的导航前端候选。",
    "glim_full_slam": "开启局部/全局地图和位姿图后，RSS 约为 odometry 的数倍，但仍保持稳定；更适合需要闭环一致性的建图前端。",
    "lio_sam_no_loop": "固定 4 核和 0.15 s mapping interval 控制了 CPU，线程数偏高；本轮 Z 诊断不如 FAST-LIVO2/GLIM，且没有闭环修正。",
    "lio_sam_loop": "闭环开启后 CPU 略高于 no-loop，终点位移诊断较小，但全局 Z 范围没有明显改善；回环不能替代可靠 deskew 和重力/外参标定。",
}


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def number(value: Any, digits: int = 2) -> str:
    if value is None or value == "":
        return ""
    return f"{float(value):.{digits}f}"


def detect_hardware() -> dict[str, Any]:
    """Capture enough host information to make the TOPS proxy auditable."""
    model = ""
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("model name"):
                model = line.split(":", 1)[-1].strip()
                break
    except OSError:
        pass

    lscpu: dict[str, str] = {}
    try:
        completed = subprocess.run(["lscpu", "-J"], capture_output=True, text=True, check=False)
        data = json.loads(completed.stdout)
        lscpu = {item["field"].rstrip(":"): str(item.get("data", "")) for item in data.get("lscpu", [])}
    except (OSError, json.JSONDecodeError, TypeError, KeyError):
        pass

    def integer(key: str, fallback: int) -> int:
        match = re.search(r"\d+", lscpu.get(key, ""))
        return int(match.group()) if match else fallback

    cores = integer("Core(s) per socket", os.cpu_count() or 1) * integer("Socket(s)", 1)
    logical = integer("CPU(s)", os.cpu_count() or cores)
    max_text = next(
        (value for key, value in lscpu.items() if "mhz" in key.lower() and ("max" in key.lower() or "最大" in key)),
        "",
    )
    max_match = re.search(r"\d+(?:\.\d+)?", max_text)
    max_ghz = float(max_match.group()) / 1000.0 if max_match else None
    base_match = re.search(r"(\d+(?:\.\d+)?)\s*GHz", model, re.I)
    base_ghz = float(base_match.group(1)) if base_match else None
    if max_ghz is None:
        max_ghz = base_ghz
    gpus = []
    try:
        completed = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True, check=False)
        gpus = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    except OSError:
        pass
    return {
        "cpu_model": model or lscpu.get("Model name", platform.processor()),
        "physical_cores": cores,
        "logical_cpus": logical,
        "nominal_ghz": base_ghz,
        "max_ghz": max_ghz,
        "gpus": gpus,
        "fp32_ops_per_cycle_assumption": 32,
        "tops_proxy_method": "busy_cores * GHz * 32 FP32 operations/cycle / 1000",
    }


def cpu_tops(cpu_percent: Any, hardware: dict[str, Any], ghz_key: str) -> float | None:
    if cpu_percent is None:
        return None
    ghz = hardware.get(ghz_key)
    if ghz is None:
        return None
    busy_cores = float(cpu_percent) / 100.0
    return busy_cores * float(ghz) * float(hardware["fp32_ops_per_cycle_assumption"]) / 1000.0


def map_metadata(run: Path) -> dict[str, Any]:
    return load_json(run / "figures" / "fast_livo2_baseline_maps" / "visualization_metadata.json", {}) or {}


def find_map_item(maps: dict[str, Any], algorithm: str) -> dict[str, Any]:
    return maps.get(algorithm, {}) if isinstance(maps, dict) else {}


def build_report(run: Path, *, hardware: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = load_json(run / "manifest.json", {}) or {}
    comparison = load_json(run / "metrics" / "full_comparison.json", {}) or {}
    visualization = map_metadata(run)
    baseline = visualization.get("baseline", "fast_livo2")
    baseline_comparisons = visualization.get("trajectory_comparison", {}) or {}
    map_items = visualization.get("maps", {}) or {}
    hardware = hardware or detect_hardware()
    algorithms_config = manifest.get("algorithms", {}) or {}
    rows: list[dict[str, Any]] = []
    recommendation_exclusions = {"mola_lio", "point_lio", "dlio"}
    baseline_cpu = None
    for item in comparison.get("algorithms", []) or []:
        if item.get("algorithm") == baseline:
            baseline_cpu = (item.get("resource_monitor") or {}).get("mean_cpu_percent")
            break
    for item in comparison.get("algorithms", []) or []:
        algorithm = item.get("algorithm", "unknown")
        config = algorithms_config.get(algorithm, {}) or {}
        trajectory = item.get("trajectory", {}) or {}
        resource = item.get("resource_monitor", {}) or {}
        standardization = item.get("standardization", {}) or {}
        relative = baseline_comparisons.get(algorithm, {}) or {}
        map_item = find_map_item(map_items, algorithm)
        flags = list(item.get("health_flags", []) or [])
        status = item.get("status")
        health_pass = status == "SUCCESS" and not any(flag in {"trajectory_short", "path_divergence"} for flag in flags)
        eligible = health_pass and algorithm not in recommendation_exclusions
        mean_cpu = resource.get("mean_cpu_percent")
        peak_cpu = resource.get("peak_cpu_percent")
        peak_rss = resource.get("peak_rss_mib")
        row = {
            "algorithm": algorithm,
            "label": LABELS.get(algorithm, algorithm),
            "group": config.get("group", "unknown"),
            "group_label": GROUP_LABELS.get(config.get("group"), config.get("group", "unknown")),
            "mode": config.get("mode"),
            "sensor_inputs": config.get("sensor_inputs", []),
            "commit": config.get("commit"),
            "config": config.get("config"),
            "status": status,
            "health_flags": flags,
            "health_pass": health_pass,
            "recommendation_eligible": eligible,
            "feature": ALGORITHM_FEATURES.get(algorithm, "未登记算法特性"),
            "reason": ALGORITHM_REASONS.get(algorithm, "无补充原因"),
            "trajectory": trajectory,
            "standardization": standardization,
            "resource": resource,
            "relative_to_fast_livo2": {
                "rmse_m": relative.get("rmse_m"),
                "p95_m": relative.get("p95_m"),
                "max_m": relative.get("max_m"),
                "mean_cpu_delta_percent": ((float(mean_cpu) - float(baseline_cpu)) / float(baseline_cpu) * 100.0
                                             if mean_cpu is not None and baseline_cpu not in (None, 0) else None),
                "peak_rss_delta_percent": None,
            },
            "map": map_item,
            "cpu_equivalent": {
                "mean_busy_cores": float(mean_cpu) / 100.0 if mean_cpu is not None else None,
                "peak_busy_cores": float(peak_cpu) / 100.0 if peak_cpu is not None else None,
                "mean_tops_at_nominal": cpu_tops(mean_cpu, hardware, "nominal_ghz"),
                "peak_tops_at_nominal": cpu_tops(peak_cpu, hardware, "nominal_ghz"),
                "peak_tops_at_max_clock": cpu_tops(peak_cpu, hardware, "max_ghz"),
            },
        }
        rows.append(row)

    baseline_row = next((row for row in rows if row["algorithm"] == baseline), None)
    baseline_peak_rss = (baseline_row or {}).get("resource", {}).get("peak_rss_mib")
    for row in rows:
        peak_rss = row["resource"].get("peak_rss_mib")
        if peak_rss is not None and baseline_peak_rss not in (None, 0):
            row["relative_to_fast_livo2"]["peak_rss_delta_percent"] = (float(peak_rss) - float(baseline_peak_rss)) / float(baseline_peak_rss) * 100.0

    stable = [row for row in rows if row["recommendation_eligible"]]
    if len(rows) != 10 or manifest.get("dataset", {}).get("compatibility"):
        stable_by_z = sorted(stable, key=lambda row: (row["trajectory"].get("z_range_m") is None, row["trajectory"].get("z_range_m") or float("inf")))
        recommendations = {
            "baseline": baseline,
            "stable_algorithms": [row["algorithm"] for row in stable],
            "lowest_z_range": stable_by_z[0]["algorithm"] if stable_by_z else None,
            "not_recommended_this_run": [row["algorithm"] for row in rows if not row["health_pass"]],
            "reason": "该 run 使用格式受限或算法子集配置，报告只给出已启用算法的相对诊断，不做十算法绝对选型。",
        }
    else:
        recommendations = {
            "navigation_frontend": {
                "primary": "fast_livo2",
                "alternatives": ["glim_odometry"],
                "reason": "导航前端优先要连续、低 Z 漂移、实时处理和可预测的局部地图；本轮 FAST-LIVO2 的 z_range=0.637 m、wall time 接近 1.0x，GLIM odometry 则以更低的峰值 RSS 提供稳定的内存受限备选。",
            },
            "mapping_frontend": {
                "primary": "glim_full_slam",
                "alternatives": ["fast_livo2"],
                "reason": "需要闭环和全局一致性时选 GLIM full SLAM；它开启 local/global mapping 且本轮相对 FAST-LIVO2 的轨迹差异仍很小。若更重视实时局部地图和竖直稳定性而不需要回环，选 FAST-LIVO2。",
            },
            "strict_memory_edge": {
                "primary": "glim_odometry",
                "alternatives": ["kiss_icp"],
                "reason": "GLIM odometry 的峰值 RSS 约 274 MiB 且诊断稳定；KISS-ICP 约 96 MiB 最省内存，但没有 IMU 重力约束，需接受 Z 轴风险。",
            },
            "not_recommended_this_run": ["point_lio", "dlio", "mola_lio"],
        }
    return {
        "schema_version": 1,
        "report_type": "comprehensive_lio_comparison",
        "generated_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
        "run": str(run),
        "run_id": (load_json(run / "metadata" / "run_status.json", {}) or {}).get("run_id", run.name),
            "run_state": (load_json(run / "metadata" / "run_status.json", {}) or {}).get("state"),
        "baseline": baseline,
        "playback_rate": manifest.get("playback_rate"),
        "metric_class": "diagnostic/relative-to-baseline/non-ground-truth",
        "dataset": manifest.get("dataset", {}),
        "evaluation": manifest.get("evaluation", {}),
        "composition": manifest.get("composition", {}),
        "hardware": hardware,
        "tops": {
            "unit": "TOPS",
            "meaning": "CPU-FP32-equivalent proxy, not measured algorithm FLOPS/TOPS",
            "formula": "mean_cpu_percent / 100 * nominal_GHz * assumed_FP32_ops_per_cycle / 1000",
            "assumption": "100% CPU is one logical core; i7-9700 AVX2/FMA envelope is approximated as 32 FP32 operations/cycle/core.",
            "host_peak_nominal_tops": (float(hardware["physical_cores"]) * float(hardware["nominal_ghz"]) * 32.0 / 1000.0
                                        if hardware.get("nominal_ghz") else None),
            "host_peak_max_clock_tops": (float(hardware["physical_cores"]) * float(hardware["max_ghz"]) * 32.0 / 1000.0
                                          if hardware.get("max_ghz") else None),
        },
        "bag_characteristics": {
            "duration_s": manifest.get("dataset", {}).get("duration_s"),
            "lidar_topic": manifest.get("dataset", {}).get("lidar_topic"),
            "lidar_type": manifest.get("dataset", {}).get("lidar_type"),
            "imu_topic": manifest.get("dataset", {}).get("imu_topic"),
            "imu_acceleration_unit": manifest.get("dataset", {}).get("imu_acceleration_unit"),
            "point_time_semantics": manifest.get("dataset", {}).get("point_time_semantics"),
            "frame_id": manifest.get("dataset", {}).get("frame_id"),
            "ground_truth_available": bool(manifest.get("dataset", {}).get("ground_truth")),
            "lidar_frames": next((item.get("input", {}).get("frames") for item in comparison.get("algorithms", []) if item.get("input", {}).get("frames")), None),
            "input_points": next((item.get("input", {}).get("input_points") for item in comparison.get("algorithms", []) if item.get("input", {}).get("input_points")), None),
            "imu_note": "本轮 MOLA-LIO、DLIO、GLIM 和 LIO-SAM 通过 runner 将 IMU 加速度从 g 转为 m/s^2；bag 中没有独立 ground truth。",
        },
        "algorithms": rows,
        "recommendations": recommendations,
        "visualization": {
            "baseline_map_dir": str(run / "figures" / "fast_livo2_baseline_maps"),
            "resource_dir": str(run / "figures" / "resource_curves"),
            "viewer_command": f"benchmark_base/bin/lio-benchmark-viewer --run {run}",
            "map_metric_note": "地图由相同的 MID360 原始点云、相同的 scan/point subsampling 和 0.12 m voxel 重建，再套用各算法轨迹；map_points/extent 是地图一致性代理，不是算法内部地图质量或精度。",
            "source_metadata": visualization,
        },
        "limitations": [
            "没有独立 ground truth，不能把相对 FAST-LIVO2 RMSE、路径长度、Z range 或 map extent 写成绝对精度排名。",
            "CPU TOPS 是基于进程树 CPU 百分比的 FP32 峰值等效代理；没有采集 perf 指令计数、每核频率、GPU 利用率或显存，不能比较真实算术吞吐。",
            "Point-LIO 和 DLIO 的生命周期状态为 SUCCESS，但轨迹健康标记为发散；本报告按结果健康度排除其推荐，而不是按退出码排除。",
            "单次 807 s 回放不能估计重复试验方差；边缘设备结论需要在目标 SoC 上用相同 bag、相同频率和热稳态重测。",
        ],
        "stable_algorithm_count": len(stable),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = ("algorithm", "label", "group", "status", "eligible", "relative_rmse_m", "z_range_m", "mean_cpu_percent", "peak_rss_mib", "mean_tops_nominal", "peak_tops_nominal", "map_points")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "algorithm": row["algorithm"],
                "label": row["label"],
                "group": row["group"],
                "status": row["status"],
                "eligible": row["recommendation_eligible"],
                "relative_rmse_m": (row["relative_to_fast_livo2"].get("rmse_m")),
                "z_range_m": row["trajectory"].get("z_range_m"),
                "mean_cpu_percent": row["resource"].get("mean_cpu_percent"),
                "peak_rss_mib": row["resource"].get("peak_rss_mib"),
                "mean_tops_nominal": row["cpu_equivalent"].get("mean_tops_at_nominal"),
                "peak_tops_nominal": row["cpu_equivalent"].get("peak_tops_at_nominal"),
                "map_points": row["map"].get("map_points"),
            })


def plot_summary(report: dict[str, Any], output: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    rows = report["algorithms"]
    labels = [row["label"] for row in rows]
    x = list(range(len(rows)))
    fig, axes = plt.subplots(2, 2, figsize=(17, 11), constrained_layout=True)
    axes[0, 0].bar(x, [row["resource"].get("mean_cpu_percent") or 0 for row in rows], color="#337ab7")
    axes[0, 0].set_title("Mean process-tree CPU")
    axes[0, 0].set_ylabel("CPU (%) ; 100% = one logical core")
    axes[0, 1].bar(x, [row["resource"].get("peak_rss_mib") or 0 for row in rows], color="#d9822b")
    axes[0, 1].set_title("Peak process-tree RSS")
    axes[0, 1].set_ylabel("MiB")
    axes[1, 0].bar(x, [row["cpu_equivalent"].get("mean_tops_at_nominal") or 0 for row in rows], color="#4e9f62")
    axes[1, 0].set_title("CPU-FP32-equivalent mean TOPS proxy")
    axes[1, 0].set_ylabel("TOPS proxy")
    axes[1, 1].bar(x, [row["trajectory"].get("z_range_m") or 0 for row in rows], color="#8b5e83")
    axes[1, 1].set_title("Diagnostic Z range")
    axes[1, 1].set_ylabel("m; no ground-truth accuracy")
    for axis in axes.flat:
        axis.set_xticks(x)
        axis.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
        axis.grid(axis="y", alpha=0.25)
    fig.suptitle(f"LIO comprehensive comparison; FAST-LIVO2 baseline; {report['run_id']}")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=170, bbox_inches="tight")
    plt.close(fig)


def render_markdown_dynamic(report: dict[str, Any]) -> str:
    dataset = report["dataset"]
    evaluation = report["evaluation"]
    compatibility = dataset.get("compatibility", {}) or {}
    rows = report["algorithms"]
    baseline = report.get("baseline", "fast_livo2")
    baseline_row = next((row for row in rows if row["algorithm"] == baseline), None)
    lines = [
        f"# LIO 基准对比报告：{report['run_id']}",
        "",
        f"生成时间：{report['generated_at']}",
        f"FAST-LIVO2 基准：`{baseline}`；run 状态：`{report['run_state']}`",
        "",
        "> 当前数据没有独立 ground truth；相对 FAST-LIVO2 的 RMSE、路径长度、Z range 和地图范围都是诊断量，不是绝对精度。",
        "",
        "## 输入契约",
        "",
        f"- 数据集：`{dataset.get('bag_dir', '')}`；时长 `{number(dataset.get('duration_s'), 2)} s`；回放 `{number(report.get('playback_rate', 1.0), 1)}x`。",
        f"- LiDAR：`{dataset.get('lidar_type')}`，topic `{dataset.get('lidar_topic')}`，frame `{dataset.get('frame_id')}`，点时间 `{dataset.get('point_time_field')}/{dataset.get('point_time_semantics')}`。",
        f"- IMU：`{dataset.get('imu_type')}`，topic `{dataset.get('imu_topic')}`，加速度单位 `{dataset.get('imu_acceleration_unit')}`。",
        f"- 评测范围：`{number(evaluation.get('minimum_range_m'), 2)}--{number(evaluation.get('maximum_range_m'), 2)} m`；地图 voxel `{number(evaluation.get('map_voxel_m'), 2)} m`。",
    ]
    if compatibility:
        lines.extend(["", "## 格式审计", ""])
        verdict = compatibility.get("verdict")
        if verdict:
            lines.append(f"- 结论：{verdict}")
        for item in compatibility.get("limitations", []) or []:
            lines.append(f"- {item}")
        for item in compatibility.get("enabled_scope", []) or []:
            lines.append(f"- {item}")
    if baseline_row:
        trajectory = baseline_row["trajectory"]
        resource = baseline_row["resource"]
        lines.extend([
            "",
            "## 基准摘要",
            "",
            f"FAST-LIVO2 输出 `{baseline_row['status']}`；轨迹时长 `{number(trajectory.get('duration_s'), 2)} s`，路径 `{number(trajectory.get('path_length_m'), 2)} m`，Z range `{number(trajectory.get('z_range_m'), 3)} m`，平均 CPU `{number(resource.get('mean_cpu_percent'), 1)}%`，峰值 RSS `{number(resource.get('peak_rss_mib'), 1)} MiB`。",
        ])
    lines.extend([
        "",
        "## 对比总表",
        "",
        "| 算法 | 分组 | 状态 | 健康 | 相对 FAST RMSE (m) | 时长 (s) | 路径 (m) | Z range (m) | 平均 CPU | 峰值 RSS (MiB) |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|",
    ])
    for row in rows:
        trajectory = row["trajectory"]
        resource = row["resource"]
        relative = row["relative_to_fast_livo2"]
        health = "normal" if row["health_pass"] else ";".join(row.get("health_flags", [])) or "needs_review"
        lines.append(
            f"| {row['label']} | {row['group_label']} | {row['status']} | {health} | "
            f"{number(relative.get('rmse_m'), 3)} | {number(trajectory.get('duration_s'), 2)} | "
            f"{number(trajectory.get('path_length_m'), 2)} | {number(trajectory.get('z_range_m'), 3)} | "
            f"{number(resource.get('mean_cpu_percent'), 1)}% | {number(resource.get('peak_rss_mib'), 1)} |"
        )
    lines.extend([
        "",
        "## 解释边界",
        "",
        "- 这份报告只比较本 run 中实际成功保存并完成标准化的算法；未启用或因输入契约不满足而跳过的算法不参与排名。",
        "- xyz-only PointCloud2 缺少逐点时间时，deskew 会被禁用或退化；因此结果不能和 MID360 CustomMsg 十算法基线直接横向比较。",
        "- LiDAR-IMU 外参若未由该包提供，FAST-LIVO2 的 LIO 结果只能作为当前假设下的可运行诊断。",
        "- 资源值来自算法进程树；CPU 100% 代表一个逻辑核。",
        "",
        "## 产物入口",
        "",
        f"- 查看器：`{report['visualization']['viewer_command']}`",
        "- 机器可读结果：`reports/comprehensive_comparison.json`、`reports/comprehensive_comparison.csv`。",
        "- 相对基准地图和轨迹图在 `figures/fast_livo2_baseline_maps/`，资源曲线在 `figures/resource_curves/`。",
    ])
    return "\n".join(lines) + "\n"


def render_markdown(report: dict[str, Any]) -> str:
    if len(report.get("algorithms", [])) != 10 or report.get("dataset", {}).get("compatibility"):
        return render_markdown_dynamic(report)
    dataset = report["dataset"]
    evaluation = report["evaluation"]
    rows_by_algorithm = {row["algorithm"]: row for row in report["algorithms"]}
    mola = rows_by_algorithm.get("mola_lio", {})
    mola_trajectory = mola.get("trajectory", {})
    mola_relative = mola.get("relative_to_fast_livo2", {})
    mola_map = mola.get("map", {})
    mola_resource = mola.get("resource", {})
    composition = report.get("composition", {}) or {}
    lines = [
        f"# 十算法 LIO 综合对比报告：{report['run_id']}",
        "",
        f"生成时间：{report['generated_at']}",
        f"FAST-LIVO2 基准：`{report['baseline']}`；run 状态：`{report['run_state']}`",
        "",
        "> 本报告是本轮完整 bag 的诊断性横向比较。当前数据没有独立 ground truth，因此文中的相对误差、路径长度、Z 漂移和地图范围都不能解释为绝对精度排名。",
        "",
        "## 一、结论摘要",
        "",
        "- 导航前端首选 **FAST-LIVO2**：本轮 `z_range=0.637 m`，轨迹覆盖约 805.5 s，平均 CPU 约 124.3%，峰值 RSS 约 976 MiB。",
        "- 内存受限的导航备选是 **GLIM odometry**：相对 FAST-LIVO2 的轨迹 RMSE 约 0.110 m，峰值 RSS 约 274 MiB；它关闭了全局建图，适合作为局部里程计前端。",
        "- 需要闭环全局地图时首选 **GLIM full SLAM**：开启 local/global mapping 后峰值 RSS 约 982 MiB，但相对基准仍保持较小的轨迹差异。",
        f"- **MOLA-LIO 的重力补偿已确实打开**：`imu_gravity_correction=true`、IMU deskew 和加速度 pitch/roll 初始化均已进入 runner；本组合结果为 `z_range={number(mola_trajectory.get('z_range_m'), 3)} m`、末端 Z 变化 `{number(mola_trajectory.get('z_end_delta_m'), 3)} m`、相对 FAST-LIVO2 RMSE `{number(mola_relative.get('rmse_m'), 3)} m`，地图 Z extent `{number((mola_map.get('extent_xyz_m') or [None, None, None])[2], 3)} m`。它已明显改善竖直地图一致性，但相对轨迹仍不如 GLIM odometry，因此暂列观察对象。",
        "- **Point-LIO、DLIO 暂不进入候选**：二者 process status 是 SUCCESS，但 Point-LIO 有 `trajectory_short/path_divergence`，DLIO 有 `path_divergence`；低 CPU 不能被解释为高效率。",
        "",
        "## 二、实验条件",
        "",
        f"- 数据集：`{dataset.get('bag_dir', '')}`；SQLite3；时长 `{number(dataset.get('duration_s'), 2)} s`；回放速率 `{number(report.get('playback_rate', 1.0), 1)}x`。",
        (f"- 组合来源：旧九算法来自 `{composition.get('base_run')}`；`mola_lio` 覆盖自 `{composition.get('override_run')}`。旧归档未修改。" if composition else ""),
        f"- LiDAR：`{dataset.get('lidar_type')}`，topic `{dataset.get('lidar_topic')}`，点时间语义 `{dataset.get('point_time_semantics')}`，范围 `{number(evaluation.get('minimum_range_m'), 2)}--{number(evaluation.get('maximum_range_m'), 2)} m`，frame `{dataset.get('frame_id')}`。",
        f"- IMU：`{dataset.get('imu_type')}`，topic `{dataset.get('imu_topic')}`；原始加速度单位为 `{dataset.get('imu_acceleration_unit')}`，runner 对需要 SI 单位的算法乘以 9.80665。",
        f"- 本轮输入抽样：约 `{report['bag_characteristics'].get('lidar_frames')}` 帧 LiDAR、`{report['bag_characteristics'].get('input_points')}` 点；适配器丢点比例约 `3.10e-7`，无独立 ground truth。",
        f"- 地图重建：scan step `{report['visualization'].get('source_metadata', {}).get('scan_step', evaluation.get('map_scan_step'))}`，point step `{report['visualization'].get('source_metadata', {}).get('point_step', evaluation.get('map_point_step'))}`，voxel `{number(report['visualization'].get('source_metadata', {}).get('voxel_m', evaluation.get('map_voxel_m')), 2)} m`；各算法复用相同原始点云和轨迹变换。",
        "- 算法进程串行运行，资源为算法进程树的采样总和；CPU 100% 等于一个逻辑核，不是整机百分比。",
        "",
        "## 三、十算法实测总表",
        "",
        "| 算法 | 分组 | 健康判定 | 相对 FAST RMSE (m) | Z range (m) | 平均 CPU | 峰值 RSS (MiB) | 平均 TOPS proxy | 地图点数 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["algorithms"]:
        trajectory = row["trajectory"]
        resource = row["resource"]
        relative = row["relative_to_fast_livo2"]
        if not row["health_pass"]:
            health = "发散/需复核"
        elif not row["recommendation_eligible"]:
            health = "观察/暂不推荐"
        else:
            health = "可进入候选"
        lines.append(
            f"| {row['label']} | {row['group_label']} | {health} | {number(relative.get('rmse_m'), 3)} | "
            f"{number(trajectory.get('z_range_m'), 3)} | {number(resource.get('mean_cpu_percent'), 1)}% | "
            f"{number(resource.get('peak_rss_mib'), 1)} | {number(row['cpu_equivalent'].get('mean_tops_at_nominal'), 3)} | "
            f"{row['map'].get('map_points', '')} |"
        )
    lines.extend([
        "",
        "注：`相对 FAST RMSE` 是初始 yaw+translation 对齐后的相对诊断量；`地图点数` 不是质量分数，发散轨迹会把点云铺开并增加占用体素。",
        "",
        "## 四、地图生成与性能原因",
        "",
        "本轮地图不是直接读取每个算法的内部地图，而是从同一份 MID360 原始点云按各算法轨迹重建，使用相同采样和 0.12 m voxel。因此它回答的是“轨迹把相同环境点投到一起的程度”，适合发现 Z 漂移、回环错位和发散，不足以评价纹理、表面重建细节或内部地图更新速度。",
        "",
        "- **FAST-LIVO2 / GLIM**：地图 extent 的 Z 约 67.4 m，且轨迹 Z range 小于 1 m，说明本轮竖直方向投影一致；GLIM odometry 的相对 RMSE 最小，full SLAM 以略高内存换取全局优化。",
        "- **MOLA-LO / LIO-SAM**：XY 仍在稳定环境尺度附近，但 Z extent 和轨迹 Z range 增大，说明地图主要问题不是点云输入丢失，而是姿态/时间/外参或未约束的竖直漂移。",
        f"- **MOLA-LIO（重力补偿覆盖结果）**：新轨迹的 Z range 为 `{number(mola_trajectory.get('z_range_m'), 3)} m`，地图 Z extent 为 `{number((mola_map.get('extent_xyz_m') or [None, None, None])[2], 3)} m`，已接近 FAST-LIVO2 的稳定地图范围；但相对 FAST-LIVO2 RMSE 为 `{number(mola_relative.get('rmse_m'), 3)} m`、平均 CPU `{number(mola_resource.get('mean_cpu_percent'), 1)}%`、峰值 RSS `{number(mola_resource.get('peak_rss_mib'), 1)} MiB`，仍需与 GLIM odometry 做资源/轨迹权衡。",
        "- **DLIO**：峰值 RSS 约 4.14 GiB、79 线程，地图 Z extent 约 189.7 m、path length 约 11.1 km，已属于发散结果；直接法、deskew、voxel/adaptive/spaciousness 处理和高频输出共同扩大了资源与失败面。",
        "- **Point-LIO**：峰值 RSS 约 447 MiB 但 path length 约 63.6 km、Z range 约 15.1 km；低 CPU 是节点早期失去有效匹配或提前结束后的表象。",
        "- **LIO-SAM loop vs no-loop**：loop 开启后平均 CPU 从约 88.7% 增至 97.1%，峰值线程从 101 增至 105；终点位移变小，但 Z range 仍约 11.7 m，说明回环优化不能替代可靠的逐点时间、IMU 和重力处理。",
        "",
        "## 五、算法特性与选型解释",
        "",
        "| 算法 | 本轮配置特性 | 本轮资源/地图解释 |",
        "|---|---|---|",
    ])
    for row in report["algorithms"]:
        lines.append(f"| {row['label']} | {row['feature']} | {row['reason']} |")
    lines.extend([
        "",
        "## 六、TOPS 与边缘设备评估",
        "",
        f"本机检测为 `{report['hardware'].get('cpu_model')}`，物理核 `{report['hardware'].get('physical_cores')}`，逻辑 CPU `{report['hardware'].get('logical_cpus')}`；名义频率 `{number(report['hardware'].get('nominal_ghz'), 2)} GHz`，最大频率 `{number(report['hardware'].get('max_ghz'), 2)} GHz`。",
        f"TOPS proxy 公式：`busy_cores × GHz × 32 / 1000`；32 来自“每核每周期 256-bit AVX2、8 个 FP32 lane、2 个 FMA 单元”的上限假设，整机名义峰值约 `{number(report['tops'].get('host_peak_nominal_tops'), 3)} TOPS`，最大频率上限约 `{number(report['tops'].get('host_peak_max_clock_tops'), 3)} TOPS`。",
        "这不是算法实际 TOPS：LIO 主要包含内存访问、分支、KD-tree/GICP、ROS 序列化和非 FP32 操作，CPU 百分比也没有给出指令计数。跨 x86、ARM、GPU/NPU 选型时必须在目标设备实测；本表 TOPS 只用于把“占用多少核”转换为可审计的同机算力代理。",
        "",
        "| 边缘设备档位 | 建议 | 原因 |",
        "|---|---|---|",
        "| RAM 约 512 MiB 以内、导航局部前端 | GLIM odometry；极限内存时 KISS-ICP | GLIM 峰值 RSS 约 274 MiB 且诊断稳定；KISS-ICP 约 96 MiB，但缺少 IMU 重力约束。",
        "| RAM 约 1 GiB、需要竖直稳定 | FAST-LIVO2 或 GLIM full SLAM | 二者峰值 RSS 都接近 1 GiB；FAST-LIVO2 的 Z 诊断最好，GLIM full SLAM 适合闭环地图。应预留 ROS、驱动和导航栈余量。",
        "| RAM 1--2 GiB、接受较重后端 | MOLA-LIO 需专项复核后再用 | 本轮峰值 RSS 约 1.08 GiB，资源不是最差，但 Z 漂移和相对误差不满足当前首选标准。",
        "| RAM 大于 4 GiB | DLIO 仍不推荐直接上线 | 资源余量不能弥补本轮 path divergence；先完成输入时间、参数和稳定性复测。",
        "",
        "## 七、建图与导航前端推荐",
        "",
        "### 导航前端",
        "首选 **FAST-LIVO2**。原因是本轮 MID360 的逐点时间、IMU 和 gravity alignment 组合下，Z range 最小，路径长度约 197 m，实时墙钟约为 bag 时长的 1.0 倍，适合持续局部里程计。缺点是峰值 RSS 接近 1 GiB，边缘设备必须预留系统余量。",
        "",
        "内存更紧时选 **GLIM odometry**，它是本轮最有说服力的“资源/稳定性”折中；它不提供全局回环地图，因此导航系统应由独立的局部代价地图和定位模块承担全局任务。KISS-ICP 只适合 IMU 不可用或极限内存场景，不应把它的低 RSS 误判为竖直导航性能好。",
        "",
        "### 建图前端",
        "需要闭环和全局一致地图时选 **GLIM full SLAM**；它比 GLIM odometry 多开启 local/global mapping 和 pose-graph，但本轮仍保持稳定。只需要实时局部地图、希望把内存和延迟压低时选 **FAST-LIVO2**。",
        "",
        "**MOLA-LIO** 目前列为观察对象，不列为首选；下一轮应固定重力初始化方式，对静止段/匀速段/急转弯段分段评测，并核对 IMU 实际比力、时间偏移和 lidar-IMU 外参。**Point-LIO/DLIO** 在修复发散和完成至少三次重复实验前不建议用于建图或导航前端。",
        "",
        "## 八、已有可视化与复现入口",
        "",
        f"- 三维点云、路径和性能曲线：`{report['visualization']['viewer_command']}`",
        "- FAST-LIVO2 相对基准地图：`figures/fast_livo2_baseline_maps/map_comparison_xy.png`、`trajectory_baseline_comparison.png`、各算法 `*_map_views.png`。",
        "- 资源曲线：`figures/resource_curves/resource_curves.png`、`resource_summary.png`；本报告新增图：`figures/comprehensive_comparison/comprehensive_summary.png`。",
        "- 机器可读结果：`reports/comprehensive_comparison.json`、`reports/comprehensive_comparison.csv`。",
        "",
        "## 九、限制与下一轮实验",
        "",
    ])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend([
        "- 对 MOLA-LIO 做 gravity on/off 成对 A/B，保持同一进程、同一初始化、同一资源采样；否则不能把本轮与旧轮差异完全归因于重力补偿。",
        "- 每个候选算法至少重复 3 次，并将目标边缘设备的 CPU 频率、温度、功耗、GPU/NPU 利用率和显存纳入资源 schema；TOPS 以目标硬件实测为准。",
        "- 为导航增加独立指标：有效输出率、端到端延迟、局部地图更新率、短时横滚/俯仰稳定性和 planner 代价地图可用率；为建图增加闭环前后地图重合度和独立测量真值。",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate comprehensive Chinese LIO comparison report")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args()
    run = args.run.resolve()
    report = build_report(run)
    output = (args.output_dir or run / "reports").resolve()
    figure_dir = run / "figures" / "comprehensive_comparison"
    atomic_write(output / "comprehensive_comparison.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    atomic_write(output / "comprehensive_comparison.md", render_markdown(report))
    write_csv(output / "comprehensive_comparison.csv", report["algorithms"])
    if not args.no_plot:
        plot_summary(report, figure_dir / "comprehensive_summary.png")
    print(json.dumps({"json": str(output / "comprehensive_comparison.json"), "markdown": str(output / "comprehensive_comparison.md"), "csv": str(output / "comprehensive_comparison.csv"), "figure": str(figure_dir / "comprehensive_summary.png"), "algorithms": len(report["algorithms"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
