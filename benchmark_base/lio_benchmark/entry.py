"""Top-level CLI dispatcher adding implemented post-processing stages."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .postprocess import execute_stage

POSTPROCESS_COMMANDS = {
    "standardize",
    "evaluate",
    "visualize",
    "report",
    "compare",
    "phase-analysis",
    "diagnostics",
    "viewer",
}


def _postprocess_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="lio-benchmark")
    sub = root.add_subparsers(dest="command", required=True)

    for name in ("standardize", "evaluate"):
        parser = sub.add_parser(name)
        parser.add_argument("--run", type=Path, required=True)
        parser.add_argument("--dry-run", action="store_true")

    for name in ("visualize", "compare"):
        parser = sub.add_parser(name)
        parser.add_argument("--run", type=Path, required=True)
        parser.add_argument("--baseline", default="fast_livo2")
        parser.add_argument("--with-maps", action="store_true", help="also rebuild baseline-aligned maps from the raw bag")
        parser.add_argument("--scan-step", type=int, default=5)
        parser.add_argument("--point-step", type=int, default=20)
        parser.add_argument("--voxel", type=float, default=0.12)
        parser.add_argument("--dry-run", action="store_true")

    parser = sub.add_parser("diagnostics")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--baseline", default="fast_livo2")
    parser.add_argument("--hz", type=float, default=10.0, help="fixed trajectory diagnostic rate")
    parser.add_argument("--window-gap", type=float, default=1.0, help="merge anomaly events separated by at most this many seconds")
    parser.add_argument("--with-pointcloud-index", action="store_true", help="also deserialize LiDAR headers and build an on-demand rosbag frame index")
    parser.add_argument("--dry-run", action="store_true")

    parser = sub.add_parser("viewer")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--mode", choices=("native", "web"), default="native")
    parser.add_argument("--baseline", default="fast_livo2")
    parser.add_argument("--algorithms", help="comma-separated algorithms; default: all diagnostic algorithms")
    parser.add_argument("--lang", choices=("zh-CN", "en"), default="zh-CN", help="repository-owned viewer language")
    parser.add_argument("--no-maps", action="store_true", help="skip reconstructed PLY maps")
    parser.add_argument("--pointcloud-mode", choices=("none", "anomaly", "sampled"), default="anomaly")
    parser.add_argument("--pointcloud-period", type=float, default=1.0, help="seconds between raw scans in sampled mode")
    parser.add_argument("--point-step", type=int, default=20, help="legacy raw LiDAR display stride")
    parser.add_argument("--point-lods", default="10,20,80", help="dense,medium,sparse LiDAR point strides")
    parser.add_argument("--world-pointcloud-mode", choices=("none", "anomaly", "sampled"), default="anomaly")
    parser.add_argument("--world-algorithm", help="world LiDAR algorithm visible by default; default: baseline")
    parser.add_argument("--map-point-step", type=int, default=4, help="display every Nth reconstructed map point")
    parser.add_argument("--save", type=Path, help="native mode only: write a .rrd recording")
    parser.add_argument("--no-spawn", action="store_true", help="native: no app spawn; web: no browser auto-open")
    parser.add_argument("--dry-run", action="store_true")

    parser = sub.add_parser("report")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--no-plot", action="store_true")
    parser.add_argument("--dry-run", action="store_true")

    parser = sub.add_parser("phase-analysis")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--baseline", default="fast_livo2")
    parser.add_argument("--phase-param", action="append", default=[])
    parser.add_argument("--no-plot", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return root


def _legacy_main(argv: list[str]) -> int:
    from .cli import main as legacy_main

    original = sys.argv
    sys.argv = [original[0], *argv]
    try:
        return int(legacy_main() or 0)
    finally:
        sys.argv = original


def main(argv: list[str] | None = None) -> int:
    argsv = list(sys.argv[1:] if argv is None else argv)
    if not argsv or argsv[0] not in POSTPROCESS_COMMANDS:
        return _legacy_main(argsv)

    args = _postprocess_parser().parse_args(argsv)
    kwargs = {"dry_run": args.dry_run}
    if args.command in {"visualize", "compare"}:
        kwargs.update({
            "with_maps": args.with_maps,
            "baseline": args.baseline,
            "scan_step": args.scan_step,
            "point_step": args.point_step,
            "voxel": args.voxel,
        })
    elif args.command == "diagnostics":
        kwargs.update({
            "baseline": args.baseline,
            "diagnostic_hz": args.hz,
            "anomaly_window_gap_s": args.window_gap,
            "with_pointcloud_index": args.with_pointcloud_index,
        })
    elif args.command == "viewer":
        kwargs.update({
            "baseline": args.baseline,
            "viewer_mode": args.mode,
            "viewer_algorithms": args.algorithms,
            "viewer_language": args.lang,
            "viewer_with_maps": not args.no_maps,
            "viewer_pointcloud_mode": args.pointcloud_mode,
            "viewer_pointcloud_period_s": args.pointcloud_period,
            "viewer_point_step": args.point_step,
            "viewer_point_lods": args.point_lods,
            "viewer_world_pointcloud_mode": args.world_pointcloud_mode,
            "viewer_world_algorithm": args.world_algorithm,
            "viewer_map_point_step": args.map_point_step,
            "viewer_save": args.save,
            "viewer_spawn": not args.no_spawn,
        })
    elif args.command == "report":
        kwargs["no_plot"] = args.no_plot
    elif args.command == "phase-analysis":
        kwargs.update({
            "baseline": args.baseline,
            "phase_params": args.phase_param,
            "no_plot": args.no_plot,
        })
    try:
        return execute_stage(args.run, args.command, **kwargs)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
