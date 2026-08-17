#!/usr/bin/env python3
"""Audit temporal coverage degradation against existing Relative SE(3) onsets."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmark_base.lib.failure_mode_audit import audit_batch  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args()
    print(audit_batch(args.run_root, args.batch_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
