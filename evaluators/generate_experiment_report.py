#!/usr/bin/env python3
"""Generate a preliminary, ROS-independent report for one benchmark run.

This stage deliberately does not deserialize trajectory messages or rebuild
maps.  It summarizes lifecycle integrity, trajectory metadata, resources and
high-signal log anomalies so a long run can be reviewed while another
algorithm is still running.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - the project already uses PyYAML
    yaml = None


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


LOG_RULES = (
    ("CRITICAL", re.compile(r"NotEnoughMemoryException|terminate called|process has died|segmentation fault|out of memory|\bOOM\b", re.I), "进程异常终止或内存异常"),
    ("HIGH", re.compile(r"\[(?:ERROR|FATAL|CRITICAL)\]|\b(abort|exception|assert)\b|loop back|lidar loop back|imu loop back", re.I), "错误、异常或传感器时间回退"),
    ("MEDIUM", re.compile(r"Excessive time|HARD time lag|timestamps? went backwards|Observation discarded|non-valid|discarded as", re.I), "时间同步、deskew 或数据有效性警告"),
)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json(path: Path, value: Any) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def trajectory_messages(path: Path) -> int | None:
    try:
        if yaml is not None:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return int(data["rosbag2_bagfile_information"]["message_count"])
        match = re.search(r"message_count:\s*(\d+)", path.read_text(encoding="utf-8"))
        return int(match.group(1)) if match else None
    except (OSError, TypeError, ValueError, KeyError):
        return None


def output_directory(run: Path, algorithm: str, entry: dict[str, Any]) -> Path:
    result = entry.get("result") or {}
    configured = result.get("output_dir") or entry.get("output_dir")
    if configured:
        path = Path(configured)
        if path.exists():
            return path
    return run / "raw" / algorithm


def scan_logs(directory: Path, *, max_examples: int = 6) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.log")):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as stream:
                for number, line in enumerate(stream, 1):
                    for severity, pattern, description in LOG_RULES:
                        if pattern.search(line):
                            finding = {"severity": severity, "source": path.name, "line": number, "description": description, "text": line.strip()[:500]}
                            findings.append(finding)
                            break
        except OSError:
            continue
    # Keep all counts useful without retaining hundreds of thousands of log lines.
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for finding in findings:
        key = (finding["severity"], finding["source"], finding["description"])
        item = grouped.setdefault(key, {**finding, "count": 0, "examples": []})
        item["count"] += 1
        if len(item["examples"]) < max_examples:
            item["examples"].append({"line": finding["line"], "text": finding["text"]})
    return sorted(grouped.values(), key=lambda item: (item["severity"], item["source"], item["line"]))


def resource_summary(path: Path) -> dict[str, Any]:
    data = load_json(path, {}) or {}
    state = data.get("status")
    if state == "finished":
        normalized = "finished"
    elif state == "live":
        normalized = "live"
    elif data.get("samples", 0) and data.get("wall_time_s"):
        normalized = "finished_legacy"
    else:
        normalized = "missing_or_invalid"
    return {
        "state": normalized,
        "samples": data.get("samples"),
        "wall_time_s": data.get("wall_time_s"),
        "mean_cpu_percent": data.get("mean_cpu_percent"),
        "peak_cpu_percent": data.get("peak_cpu_percent"),
        "mean_rss_bytes": data.get("mean_rss_bytes"),
        "peak_rss_bytes": data.get("peak_rss_bytes"),
        "peak_threads": data.get("peak_threads"),
        "disk_write_bytes": data.get("disk_write_bytes"),
    }


def classify_algorithm(run: Path, algorithm: str, entry: dict[str, Any]) -> dict[str, Any]:
    result = entry.get("result") or {}
    output = output_directory(run, algorithm, entry)
    metadata = output / "trajectory" / "metadata.yaml"
    validation = load_json(output / "input_validation.json", None)
    resource = resource_summary(output / "resource_monitor.json")
    messages = trajectory_messages(metadata) if metadata.is_file() else result.get("trajectory_messages")
    findings = scan_logs(output)
    statuses = [finding["severity"] for finding in findings]
    if result.get("status") == "RUNTIME_CRASH":
        category = "RUNTIME_CRASH"
    elif not result:
        category = "RUNNING" if entry.get("state") == "running" else "PENDING"
    elif result.get("status") != "SUCCESS":
        category = str(result.get("status"))
    elif any(severity in statuses for severity in ("CRITICAL", "HIGH")):
        category = "SUCCESS_NEEDS_REVIEW"
    elif findings or entry.get("reason"):
        category = "SUCCESS_WITH_WARNINGS"
    else:
        category = "SUCCESS"
    consistency: list[str] = []
    if result.get("status") == "SUCCESS" and entry.get("reason"):
        consistency.append("status entry contains a stale or unexplained reason")
    if result.get("status") == "SUCCESS" and result.get("algorithm_exit_code") not in (None, 0, -15):
        consistency.append(f"algorithm exit code is {result.get('algorithm_exit_code')}")
    if result.get("status") == "SUCCESS" and messages is not None and messages <= 0:
        consistency.append("trajectory message count is not positive")
    standardized = (run / "standardized" / "trajectories" / f"{algorithm}.csv").is_file()
    return {
        "algorithm": algorithm,
        "label": LABELS.get(algorithm, algorithm),
        "group": entry.get("group"),
        "state": entry.get("state", "pending"),
        "result_status": result.get("status"),
        "category": category,
        "started_at": entry.get("started_at"),
        "finished_at": entry.get("finished_at"),
        "output_dir": str(output),
        "trajectory_messages": messages,
        "trajectory_metadata": metadata.is_file(),
        "input_validation": isinstance(validation, dict),
        "bag_playback": result.get("bag_playback"),
        "bag_play_exit_code": result.get("bag_play_exit_code"),
        "algorithm_exit_code": result.get("algorithm_exit_code"),
        "resource": resource,
        "standardized": standardized,
        "consistency_issues": consistency,
        "findings": findings,
    }


def build_report(run: Path) -> dict[str, Any]:
    status = load_json(run / "metadata" / "run_status.json", {}) or {}
    manifest = load_json(run / "manifest.json", {}) or {}
    algorithms = [classify_algorithm(run, name, entry) for name, entry in status.get("algorithms", {}).items()]
    counts: dict[str, int] = {}
    for item in algorithms:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    anomalies = []
    for item in algorithms:
        high_findings = [finding for finding in item["findings"] if finding["severity"] in {"CRITICAL", "HIGH"}]
        if item["category"] == "RUNTIME_CRASH" and not high_findings:
            anomalies.append({
                "algorithm": item["algorithm"],
                "category": item["category"],
                "finding": {
                    "severity": "CRITICAL",
                    "description": "算法运行崩溃",
                    "text": f"status={item.get('result_status')} algorithm_exit_code={item.get('algorithm_exit_code')}",
                },
            })
        anomalies.extend({"algorithm": item["algorithm"], "category": item["category"], "finding": finding} for finding in high_findings)
    has_running = any(item["state"] == "running" for item in algorithms)
    crashed = [item["label"] for item in algorithms if item["category"] == "RUNTIME_CRASH"]
    recommendations = [
        ("等待仍处于 running 的算法完成后再锁定最终排名。" if has_running
         else "所有已登记算法均已结束，可锁定本轮实验结果；失败算法不纳入成功率和精度排名。"),
        (f"对 {', '.join(crashed)} 复核 SIGKILL/资源限制和传感器输入，完成独立复现后再调整参数。" if crashed
         else "对 RUNTIME_CRASH 算法先完成日志、时间同步和轨迹连续性复核。"),
        "对所有 SUCCESS 算法运行统一轨迹标准化，再按 comparison group 分组比较。",
        "没有独立 ground truth 时只发布 diagnostic 指标，不发布绝对精度排名。",
    ]
    return {
        "schema_version": 1,
        "report_type": "preliminary_experiment_report",
        "generated_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
        "run": str(run),
        "run_id": status.get("run_id", run.name),
        "run_state": status.get("state"),
        "dataset": manifest.get("dataset", {}),
        "summary": {"algorithm_count": len(algorithms), "categories": counts, "critical_or_high_anomalies": len(anomalies)},
        "algorithms": algorithms,
        "anomalies": anomalies,
        "recommendations": recommendations,
    }


def _number(value: Any, digits: int = 1) -> str:
    return "" if value is None else f"{float(value):.{digits}f}"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Preliminary Experiment Report: {report['run_id']}",
        "",
        f"Generated: {report['generated_at']}",
        f"Run state: `{report['run_state']}`",
        "",
        "This is a lifecycle and health report. It is not an accuracy ranking and does not replace trajectory standardization, alignment or ground-truth evaluation.",
        "",
        "## Summary",
        "",
        f"- Algorithms observed: {report['summary']['algorithm_count']}",
        f"- Categories: `{json.dumps(report['summary']['categories'], ensure_ascii=False)}`",
        f"- Critical/high findings: {report['summary']['critical_or_high_anomalies']}",
        "",
        "## Algorithm Review",
        "",
        "| Algorithm | State | Category | Messages | Mean CPU % | Peak RSS GiB | Resource | Standardized | Review |",
        "|---|---|---|---:|---:|---:|---|---|---|",
    ]
    for item in report["algorithms"]:
        resource = item["resource"]
        peak_rss = resource.get("peak_rss_bytes")
        peak_rss_gib = float(peak_rss) / (1024 ** 3) if peak_rss is not None else None
        review = "; ".join(item["consistency_issues"] + [finding["description"] for finding in item["findings"][:2]])
        lines.append(
            f"| {item['label']} | {item['state']} | {item['category']} | {item.get('trajectory_messages', '')} | "
            f"{_number(resource.get('mean_cpu_percent'))} | {_number(peak_rss_gib, 2)} | {resource.get('state')} | "
            f"{'yes' if item['standardized'] else 'no'} | {review or 'none'} |"
        )
    lines.extend(["", "## Critical / High Findings", ""])
    if report["anomalies"]:
        for anomaly in report["anomalies"]:
            finding = anomaly["finding"]
            lines.append(f"- **{anomaly['algorithm']} / {finding['severity']}** {finding['description']}: `{finding['text']}`")
    else:
        lines.append("- None detected by the preliminary rules.")
    lines.extend(["", "## Recommendations", ""])
    lines.extend(f"- {item}" for item in report["recommendations"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--name", default="preliminary_experiment_report")
    args = parser.parse_args()
    run = args.run.resolve()
    report = build_report(run)
    output = (args.output_dir or run / "reports").resolve()
    atomic_json(output / f"{args.name}.json", report)
    atomic_write(output / f"{args.name}.md", render_markdown(report))
    print(json.dumps({"json": str(output / f"{args.name}.json"), "markdown": str(output / f"{args.name}.md"), "summary": report["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
