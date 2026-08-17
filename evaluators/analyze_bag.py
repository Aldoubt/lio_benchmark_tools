#!/usr/bin/env python3
"""Read-only analysis of ROS 2 bag sensor/timestamp evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.rosbag_inspection import inspect_ros2_bag  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bag", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = inspect_ros2_bag(args.bag)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
