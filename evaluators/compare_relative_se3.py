#!/usr/bin/env python3
"""Run the frozen Relative SE(3) motion comparison for one benchmark run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.relative_se3 import RelativeSE3Error, compare_run  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--algorithms", nargs="+")
    args = parser.parse_args()
    try:
        output = compare_run(args.run, args.algorithms)
    except RelativeSE3Error as exc:
        raise SystemExit(str(exc)) from exc
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    print(output)
    print(json.dumps({
        "eligible_algorithms": metadata["eligible_algorithms"],
        "blocked_algorithms": metadata["blocked_algorithms"],
        "common_start_s": metadata["common_start_s"],
        "common_end_s": metadata["common_end_s"],
        "calibration_status": metadata["calibration_status"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
