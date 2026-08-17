#!/usr/bin/env python3
"""Generate Same-Bag Mapping Benchmark V1 read-only summary artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.same_bag_summary import summarize_same_bag  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        payload = summarize_same_bag(args.run)
    except (ValueError, FileExistsError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    output = args.run.resolve() / "reports" / "same_bag_mapping_v1.json"
    print(output)
    print(f"algorithms={len(payload['algorithms'])}")
    print(f"scientific_status={payload['scientific_status']}")
    print(f"performance_status={payload['performance_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
