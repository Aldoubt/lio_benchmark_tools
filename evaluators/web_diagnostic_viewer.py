#!/usr/bin/env python3
"""Serve the offline LIO recording to a thin local Rerun WebViewer shell."""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_BASE = REPO_ROOT / "benchmark_base"
if str(BENCHMARK_BASE) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_BASE))

from lio_benchmark.web_viewer_server import WebViewerServer
from rerun_diagnostic_viewer import (
    DEFAULT_POINT_LODS,
    parse_point_lods,
    resolve_algorithms,
    send_blueprint,
)
from viewer_i18n import SUPPORTED_LANGUAGES
from web_rerun_recorder import log_recording_web_safe

RERUN_LABEL_LANGUAGE = "en"
WEB_PROFILES = ("empty", "trajectory", "scalar", "pose", "full")


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _browser_grpc_uri(value: str) -> str:
    return str(value).replace("0.0.0.0", "127.0.0.1").replace("[::]", "127.0.0.1")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open the interactive LIO WebViewer")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--baseline", default="fast_livo2")
    parser.add_argument("--algorithms")
    parser.add_argument("--lang", choices=SUPPORTED_LANGUAGES, default="zh-CN")
    parser.add_argument("--web-profile", choices=WEB_PROFILES, default="full")
    parser.add_argument("--no-maps", action="store_true")
    parser.add_argument("--map-point-step", type=int, default=4)
    parser.add_argument("--pointcloud-mode", choices=("none", "anomaly", "sampled"), default="anomaly")
    parser.add_argument("--pointcloud-period", type=float, default=1.0)
    parser.add_argument("--point-step", type=int, default=20)
    parser.add_argument("--point-lods", default=DEFAULT_POINT_LODS)
    parser.add_argument("--world-pointcloud-mode", choices=("none", "anomaly", "sampled"), default="anomaly")
    parser.add_argument("--world-algorithm")
    parser.add_argument("--http-host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=0)
    parser.add_argument("--grpc-port", type=int, default=9876)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()

    if args.map_point_step < 1 or args.point_step < 1 or args.pointcloud_period <= 0:
        raise ValueError("map/point steps must be >=1 and pointcloud period must be >0")
    point_lods = parse_point_lods(args.point_lods)
    run = args.run.resolve()
    algorithms = resolve_algorithms(run, args.algorithms)
    if args.baseline not in algorithms:
        algorithms = [args.baseline, *algorithms]
    world_algorithm = args.world_algorithm or args.baseline
    if world_algorithm not in algorithms:
        raise ValueError(f"world algorithm must be in selected algorithms: {world_algorithm}")

    web_root = REPO_ROOT / "benchmark_base" / "web_viewer"
    dist_dir = web_root / "dist"
    if not (dist_dir / "index.html").is_file():
        raise FileNotFoundError(
            f"web viewer build is missing: {dist_dir}. "
            f"Web mode requires Node >=22.12; run `cd {web_root} && npm ci && npm run build`."
        )

    timeline = load_json(run / "metrics" / "diagnostic_timeline.json", {}) or {}
    windows = [
        dict(item)
        for item in timeline.get("anomaly_windows") or []
        if item.get("algorithm") in algorithms
    ]
    windows.sort(key=lambda item: float(item.get("severity") or 0.0), reverse=True)

    import rerun as rr
    import rerun.blueprint as rrb

    initial_state: dict[str, object] = {
        "visibleAlgorithms": list(algorithms),
        "worldAlgorithm": world_algorithm,
        "pointLod": "medium",
        "language": args.lang,
    }

    def apply_state(state: dict[str, object]) -> None:
        # The browser shell is fully localized at runtime. Rerun's own labels stay
        # English because the native/WebViewer font stack can render CJK as tofu
        # squares on some Ubuntu systems. This keeps entity recognition stable.
        send_blueprint(
            rr,
            rrb,
            algorithms=algorithms,
            visible_algorithms=set(str(item) for item in state["visibleAlgorithms"]),
            world_algorithm=str(state["worldAlgorithm"]),
            point_lod=str(state["pointLod"]),
            language=RERUN_LABEL_LANGUAGE,
        )

    config: dict[str, object] = {
        "grpcUrl": "",
        "language": args.lang,
        "algorithms": algorithms,
        "baseline": args.baseline,
        "worldAlgorithm": world_algorithm,
        "anomalyWindows": windows,
    }
    server = WebViewerServer(
        config,
        apply_state,
        dist_dir,
        host=args.http_host,
        port=args.http_port,
    )

    rr.init("lio_benchmark_offline_diagnostic_viewer", spawn=False)
    grpc_uri = rr.serve_grpc(
        grpc_port=args.grpc_port,
        cors_allow_origin=[server.url],
    )
    grpc_uri = _browser_grpc_uri(grpc_uri)
    server.update_config(grpcUrl=grpc_uri)

    result = log_recording_web_safe(
        rr,
        run,
        algorithms,
        baseline=args.baseline,
        with_maps=not args.no_maps,
        map_point_step=args.map_point_step,
        pointcloud_mode=args.pointcloud_mode,
        pointcloud_period_s=args.pointcloud_period,
        point_lods=point_lods,
        world_pointcloud_mode=args.world_pointcloud_mode,
        world_algorithm=world_algorithm,
        language=RERUN_LABEL_LANGUAGE,
    )
    apply_state(initial_state)

    print(
        json.dumps(
            {
                **result,
                "mode": "web",
                "shell_language": args.lang,
                "rerun_label_language": RERUN_LABEL_LANGUAGE,
                "web_url": server.url,
                "grpc_url": grpc_uri,
                "anomaly_windows_available": len(windows),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not args.no_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        rr.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
