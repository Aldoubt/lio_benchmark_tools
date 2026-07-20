#!/usr/bin/env python3
"""Read a dotted manifest key without shell evaluation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("key")
    args = parser.parse_args()
    value = json.loads(args.manifest.read_text(encoding="utf-8"))
    for part in args.key.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    if isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False))
    elif value is None:
        print("")
    else:
        print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
