"""Command-line orchestration for reproducible LIO experiments."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from .doctor import check_manifest
from .manifest import REPO_ROOT, load_manifest, migrate_v1, resolve_path, validate_manifest
from .registry import comparison_groups
from .run_directory import create_run, resolve_run


def dump(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def command_for(name: str, config: dict, manifest_path: Path, output: Path, bag: Path) -> list[str]:
    runner = resolve_path(str(config["runner"]))
    algorithm_config = resolve_path(str(config["config"]))
    return ["bash", str(runner), str(bag), str(output), str(algorithm_config), str(manifest_path)]


def cmd_validate(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.config)
    errors = validate_manifest(manifest)
    if errors:
        print("验证失败:\n- " + "\n- ".join(errors), file=sys.stderr)
        return 2
    print(f"验证通过: {manifest['name']} ({len(manifest['algorithms'])} algorithms, playback_rate={manifest.get('playback_rate')})")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    report = check_manifest(load_manifest(args.config))
    dump(report)
    return 0 if report["status"] == "PASS" else 2


def cmd_init(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.config)
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("清单验证失败:\n- " + "\n- ".join(errors))
    print(create_run(manifest, args.config, args.run_id))
    return 0


def cmd_commands(args: argparse.Namespace) -> int:
    if args.run:
        run, manifest = resolve_run(args.run)
        manifest_path, root = run / "manifest.json", run / "raw"
    else:
        manifest_path = args.config.resolve()
        manifest = load_manifest(manifest_path)
        root = resolve_path(str(manifest["output_root"])) / "<run_id>" / "raw"
    bag = resolve_path(str(manifest["dataset"]["bag_dir"]))
    for name, config in manifest["algorithms"].items():
        if config.get("enabled"):
            print(" ".join(command_for(name, config, manifest_path, root / name, bag)))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    run, manifest = resolve_run(args.run)
    selected = args.algorithm or [name for name, cfg in manifest["algorithms"].items() if cfg.get("enabled")]
    bag, manifest_path = resolve_path(str(manifest["dataset"]["bag_dir"])), run / "manifest.json"
    for name in selected:
        if name not in manifest["algorithms"]:
            raise ValueError(f"算法不在 manifest 中: {name}")
        command = command_for(name, manifest["algorithms"][name], manifest_path, run / "raw" / name, bag)
        print(" ".join(command))
        if not args.dry_run:
            environment = os.environ.copy()
            if args.duration is not None:
                environment["LIO_BENCHMARK_DURATION_S"] = str(args.duration)
            result = subprocess.run(command, check=False, env=environment)
            if result.returncode:
                return result.returncode
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    run, manifest = resolve_run(args.run)
    command = [sys.executable, str(REPO_ROOT / "evaluators/analyze_bag.py"), str(resolve_path(manifest["dataset"]["bag_dir"])), "--output", str(run / "metrics/bag_analysis.json"), "--manifest", str(run / "manifest.json")]
    print(" ".join(command))
    if not args.dry_run:
        return subprocess.run(command, check=False).returncode
    return 0


def cmd_stage(args: argparse.Namespace) -> int:
    run, _ = resolve_run(args.run)
    marker = run / "metadata" / f"{args.stage}.json"
    if args.dry_run:
        print(f"dry-run: {args.stage} -> {marker}")
        return 0
    marker.write_text(json.dumps({"stage": args.stage, "status": "NOT_IMPLEMENTED_WITHOUT_INPUTS", "created_at": dt.datetime.now().isoformat()}, indent=2) + "\n", encoding="utf-8")
    print(marker)
    return 3


def cmd_snapshot(args: argparse.Namespace) -> int:
    run, manifest = resolve_run(args.run)
    states = []
    for name, config in manifest["algorithms"].items():
        source = resolve_path(str(config.get("source", "")))
        state = {"algorithm": name, "source": str(source), "exists": source.exists()}
        if (source / ".git").exists():
            def git(*parts: str) -> str:
                return subprocess.run(["git", "-C", str(source), *parts], capture_output=True, text=True, check=False).stdout.strip()
            state.update({"commit": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"), "dirty": bool(git("status", "--porcelain"))})
        states.append(state)
    output = run / "metadata/environment_snapshot.json"
    output.write_text(json.dumps({"captured_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(), "platform": platform.platform(), "python": platform.python_version(), "ros_distro": os.environ.get("ROS_DISTRO", ""), "algorithms": states}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    result = migrate_v1(load_manifest(args.input))
    if args.output.exists() and not args.force:
        raise FileExistsError(f"拒绝覆盖: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0


def cmd_create_manifest(args: argparse.Namespace) -> int:
    metadata_path = args.bag / "metadata.yaml"
    if not metadata_path.is_file():
        raise ValueError(f"bag 缺少 metadata.yaml: {args.bag}")
    info = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))["rosbag2_bagfile_information"]
    topics = {x["topic_metadata"]["name"]: x["topic_metadata"]["type"] for x in info["topics_with_message_count"]}
    lidar = next(((n, t) for n, t in topics.items() if t.endswith(("/PointCloud2", "/CustomMsg"))), ("UNRESOLVED", "UNRESOLVED"))
    imu = next(((n, t) for n, t in topics.items() if t == "sensor_msgs/msg/Imu"), ("UNRESOLVED", "UNRESOLVED"))
    identity = [1,0,0,0,1,0,0,0,1]
    result = {"schema_version": 2, "name": args.bag.name, "output_root": str((args.bag.parent / "runs").resolve()), "playback_rate": 1.0,
              "dataset": {"bag_dir": str(args.bag.resolve()), "storage_id": info.get("storage_identifier") or "sqlite3", "lidar_topic": lidar[0], "lidar_type": lidar[1], "imu_topic": imu[0], "imu_type": imu[1], "wheel_odom_topic": None, "ground_truth": None, "imu_acceleration_unit": "UNRESOLVED", "point_time_field": "UNRESOLVED", "point_time_datatype": "UNRESOLVED", "point_time_unit": "UNRESOLVED", "point_time_semantics": "UNRESOLVED", "start_offset_s": 0.0, "end_offset_s": None},
              "calibration": {name: {"direction": name, "rotation": identity, "translation": [0,0,0], "confidence": "UNRESOLVED"} for name in ("lidar_to_imu", "imu_to_base", "lidar_to_base")}, "algorithms": {}}
    if args.output.exists() and not args.force:
        raise FileExistsError(f"拒绝覆盖: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    stages = ["analyze-bag", "run", "standardize", "evaluate", "visualize", "report", "snapshot"]
    print(json.dumps({"run": str(args.run), "stages": stages, "dry_run": args.dry_run, "stop_on_failure": True}, ensure_ascii=False))
    if not args.dry_run:
        raise ValueError("all 的实际执行需先通过 smoke test；请先使用 --dry-run 审阅命令")
    return 0


def cmd_matrix(args: argparse.Namespace) -> int:
    suite = yaml.safe_load(args.suite.read_text(encoding="utf-8"))
    dump({"suite": suite.get("suite_name"), "datasets": len(suite.get("datasets", [])), "algorithms": suite.get("algorithms", []), "groups": comparison_groups([x for x in suite.get("algorithms", []) if x in __import__('lio_benchmark.registry', fromlist=['ALGORITHMS']).ALGORITHMS]), "dry_run": args.dry_run})
    if not args.dry_run:
        raise ValueError("matrix 实际运行须在单 bag 审阅通过后启用")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="lio-benchmark")
    sub = root.add_subparsers(dest="command", required=True)
    for name, function in (("validate", cmd_validate), ("doctor", cmd_doctor)):
        p = sub.add_parser(name); p.add_argument("--config", type=Path, required=True); p.set_defaults(func=function)
    p = sub.add_parser("init"); p.add_argument("--config", type=Path, required=True); p.add_argument("--run-id"); p.set_defaults(func=cmd_init)
    p = sub.add_parser("commands"); choice=p.add_mutually_exclusive_group(required=True); choice.add_argument("--config", type=Path); choice.add_argument("--run", type=Path); p.set_defaults(func=cmd_commands)
    p = sub.add_parser("run"); p.add_argument("--run", type=Path, required=True); p.add_argument("--algorithm", action="append"); p.add_argument("--duration", type=int); p.add_argument("--dry-run", action="store_true"); p.set_defaults(func=cmd_run)
    p = sub.add_parser("analyze-bag"); p.add_argument("--run", type=Path, required=True); p.add_argument("--dry-run", action="store_true"); p.set_defaults(func=cmd_analyze)
    for stage in ("standardize", "evaluate", "visualize", "report"):
        p = sub.add_parser(stage); p.add_argument("--run", type=Path, required=True); p.add_argument("--dry-run", action="store_true"); p.set_defaults(func=cmd_stage, stage=stage)
    p = sub.add_parser("snapshot"); p.add_argument("--run", type=Path, required=True); p.set_defaults(func=cmd_snapshot)
    p = sub.add_parser("all"); p.add_argument("--run", type=Path, required=True); p.add_argument("--dry-run", action="store_true"); p.add_argument("--duration", type=float); p.add_argument("--smoke-test", action="store_true"); p.add_argument("--repetitions", type=int, default=1); p.set_defaults(func=cmd_all)
    p = sub.add_parser("matrix"); p.add_argument("--suite", type=Path, required=True); p.add_argument("--dry-run", action="store_true"); p.add_argument("--resume", action="store_true"); p.add_argument("--only-dataset"); p.add_argument("--only-algorithm"); p.set_defaults(func=cmd_matrix)
    p = sub.add_parser("migrate-manifest"); p.add_argument("--input", type=Path, required=True); p.add_argument("--output", type=Path, required=True); p.add_argument("--force", action="store_true"); p.set_defaults(func=cmd_migrate)
    p = sub.add_parser("create-manifest"); p.add_argument("--bag", type=Path, required=True); p.add_argument("--output", type=Path, required=True); p.add_argument("--force", action="store_true"); p.set_defaults(func=cmd_create_manifest)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.func(args) or 0)
    except (ValueError, FileExistsError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
