"""Immutable run-directory creation."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .manifest import resolve_path


BASE_DIRS = ("input", "configs", "standardized/trajectories", "standardized/maps", "metrics", "figures", "reports", "logs", "metadata")


def create_run(manifest: dict, source_manifest: Path, run_id: str | None = None) -> Path:
    actual_id = run_id or f"{manifest['name']}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if not actual_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("run-id 只能包含字母、数字、下划线和短横线")
    run = resolve_path(str(manifest["output_root"])) / actual_id
    if run.exists():
        raise FileExistsError(f"拒绝覆盖已有 run: {run}")
    dirs = list(BASE_DIRS) + [f"raw/{name}" for name, cfg in manifest["algorithms"].items() if cfg.get("enabled")]
    for relative in dirs:
        (run / relative).mkdir(parents=True, exist_ok=False)
    frozen = dict(manifest)
    frozen.update({"run_id": actual_id, "created_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(), "source_manifest": str(source_manifest.resolve())})
    (run / "manifest.json").write_text(json.dumps(frozen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run / "RUN_STATUS.md").write_text(f"# Run {actual_id}\n\n- 状态：initialized\n- bag 回放：not_started\n- 创建时间：{frozen['created_at']}\n", encoding="utf-8")
    return run


def resolve_run(path: Path) -> tuple[Path, dict]:
    from .manifest import load_manifest
    run = path.resolve()
    manifest_path = run / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"不是标准 run 目录，缺少 {manifest_path}")
    return run, load_manifest(manifest_path)
