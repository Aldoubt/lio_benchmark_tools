#!/usr/bin/env python3
"""Emit shell-safe environment assignments from one frozen run manifest."""
from __future__ import annotations

import argparse
from pathlib import Path
import shlex
import sys

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.execution_contract import ExecutionContractError, resolve_execution  # noqa: E402
from benchmark_base.lib.manifest import load_json, normalized_replay  # noqa: E402
from benchmark_base.lib.ros_workspace import runtime_overlays_for_algorithm  # noqa: E402


def assignment(name: str, value: str) -> str:
    return f"{name}={shlex.quote(value)}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--algorithm", required=True)
    args = parser.parse_args()

    manifest = load_json(args.run.resolve() / "manifest.json")
    try:
        resolution = resolve_execution(manifest, args.algorithm)
        replay = normalized_replay(manifest)
        overlays = runtime_overlays_for_algorithm(manifest, args.algorithm)
    except (ExecutionContractError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    duration = "" if replay["duration_s"] is None else str(replay["duration_s"])
    resolved = "" if resolution.resolved_executable is None else str(resolution.resolved_executable)
    rows = [
        assignment("BENCHMARK_EXECUTION_RESOLUTION_METHOD", resolution.resolution_method),
        assignment("BENCHMARK_RESOLVED_EXECUTABLE", resolved),
        assignment("BENCHMARK_RUNTIME_OVERLAY_COUNT", str(len(overlays))),
    ]
    rows.extend(
        assignment(f"BENCHMARK_RUNTIME_OVERLAY_{index}", str(path))
        for index, path in enumerate(overlays)
    )
    rows.extend(
        [
            assignment("BENCHMARK_REPLAY_RATE", str(replay["rate"])),
            assignment("BENCHMARK_REPLAY_START_OFFSET_S", str(replay["start_offset_s"])),
            assignment("BENCHMARK_REPLAY_DURATION_S", duration),
            assignment("BAG_PLAY_RATE", str(replay["rate"])),
            assignment("BAG_START_OFFSET", str(replay["start_offset_s"])),
            assignment("BAG_DURATION", duration),
        ]
    )
    print("\n".join(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
