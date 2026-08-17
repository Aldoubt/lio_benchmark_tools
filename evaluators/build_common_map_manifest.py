#!/usr/bin/env python3
"""Build the strict run-level common matched-scan manifest for Unified Maps."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.common_map_manifest import build_common_map_manifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    print(build_common_map_manifest(args.run.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
