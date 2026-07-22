#!/usr/bin/env python3
"""Create a new benchmark archive by overlaying one algorithm result.

The base run is never modified.  Files from the base run are hard-linked by
default to avoid copying multi-gigabyte recorded bags; directories that are
regenerated later are removed from the new archive before analysis.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import shutil
from pathlib import Path
from typing import Any


REGENERATED_DIRS = ("standardized", "metrics", "figures", "reports")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def replace_paths(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [replace_paths(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: replace_paths(item, old, new) for key, item in value.items()}
    return value


def copy_tree(source: Path, destination: Path, *, hardlink: bool) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if hardlink:
        shutil.copytree(source, destination, copy_function=os.link)
    else:
        shutil.copytree(source, destination)


def require_run(run: Path, label: str) -> None:
    for relative in ("manifest.json", "metadata/run_status.json"):
        if not (run / relative).is_file():
            raise ValueError(f"{label} 不是完整 run，缺少 {run / relative}")


def combine(base: Path, override: Path, output: Path, algorithm: str) -> Path:
    base = base.resolve()
    override = override.resolve()
    output = output.resolve()
    require_run(base, "base run")
    require_run(override, "override run")
    if base == output or override == output:
        raise ValueError("输出目录不能覆盖输入 run")
    if output.exists():
        raise FileExistsError(f"拒绝覆盖已有组合 run: {output}")

    copy_tree(base, output, hardlink=True)
    for relative in REGENERATED_DIRS:
        shutil.rmtree(output / relative, ignore_errors=True)
        (output / relative).mkdir(parents=True, exist_ok=True)

    base_algorithm_dir = output / "raw" / algorithm
    shutil.rmtree(base_algorithm_dir, ignore_errors=True)
    override_algorithm_dir = override / "raw" / algorithm
    if not override_algorithm_dir.is_dir():
        raise ValueError(f"override run 缺少 {override_algorithm_dir}")
    copy_tree(override_algorithm_dir, base_algorithm_dir, hardlink=False)

    manifest = copy.deepcopy(load_json(base / "manifest.json"))
    run_id = output.name
    manifest.update({
        "run_id": run_id,
        "created_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
        "source_manifest": str(base / "manifest.json"),
        "composition": {
            "base_run": str(base),
            "override_algorithm": algorithm,
            "override_run": str(override),
            "preserved_algorithms": [name for name in manifest.get("algorithms", {}) if name != algorithm],
        },
    })
    manifest_path = output / "manifest.json"
    manifest_path.unlink()
    write_json(manifest_path, manifest)

    status = replace_paths(load_json(base / "metadata" / "run_status.json"), str(base), str(output))
    override_status = load_json(override / "metadata" / "run_status.json")
    override_entry = copy.deepcopy(override_status.get("algorithms", {}).get(algorithm))
    if not override_entry or not override_entry.get("result"):
        raise ValueError(f"override run 中 {algorithm} 没有成功结果")
    override_entry = replace_paths(override_entry, str(override), str(output))
    status.setdefault("algorithms", {})[algorithm] = override_entry
    status.update({
        "run_id": run_id,
        "state": "completed",
        "bag_playback": "completed",
        "phase": "completed",
        "current_algorithm": None,
        "last_algorithm": algorithm,
        "updated_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
        "composition": manifest["composition"],
    })
    status.setdefault("events", []).append({
        "at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
        "algorithm": algorithm,
        "state": "completed",
        "bag_playback": "completed",
        "event": f"composed override from {override.name}",
    })
    status_path = output / "metadata" / "run_status.json"
    status_path.unlink()
    lock_path = output / "metadata" / "run_status.json.lock"
    if lock_path.exists():
        lock_path.unlink()
    write_json(status_path, status)

    reproducibility = output / "COMPOSITION.md"
    reproducibility.write_text(
        f"# Composed benchmark run\n\n"
        f"- Base run: `{base}`\n"
        f"- Replaced algorithm: `{algorithm}`\n"
        f"- Override run: `{override}`\n"
        f"- Base run is preserved unchanged. Regenerate standardized trajectories, metrics, maps and reports after composition.\n",
        encoding="utf-8",
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Compose a benchmark run with one algorithm override")
    parser.add_argument("--base-run", type=Path, required=True)
    parser.add_argument("--override-run", type=Path, required=True)
    parser.add_argument("--algorithm", default="mola_lio")
    parser.add_argument("--output-run", type=Path, required=True)
    args = parser.parse_args()
    output = combine(args.base_run, args.override_run, args.output_run, args.algorithm)
    print(json.dumps({"output_run": str(output), "algorithm": args.algorithm, "base_run": str(args.base_run.resolve()), "override_run": str(args.override_run.resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
