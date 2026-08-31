from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from freeze_experiment import finalize_freeze, prepare_freeze, write_json_atomic
from freeze_rerun_visual_qa import build_frozen_rerun
from report_data import build_report_data
from report_evidence import build_report_evidence
from report_html import render_report_html
from report_pdf import render_report_pdf

SUPPORTED_LANGUAGES = {"zh-CN", "en"}
REQUIRED_OUTPUTS = (
    "viewer/diagnostic.rrd",
    "report_data.json",
    "evidence/evidence_manifest.json",
    "report/index.html",
    "report/report.pdf",
)


def _load_manifest(frozen: Path) -> dict[str, Any]:
    path = Path(frozen) / "freeze_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _record_failure(frozen: Path, stage: str, exc: Exception) -> None:
    try:
        payload = _load_manifest(frozen)
    except Exception:
        return
    payload["freeze_state"] = "INCOMPLETE"
    payload["failure"] = {
        "stage": stage,
        "type": type(exc).__name__,
        "message": str(exc),
    }
    write_json_atomic(Path(frozen) / "freeze_manifest.json", payload)


def _all_generated_paths(frozen: Path) -> tuple[str, ...]:
    payload = _load_manifest(frozen)
    paths = {
        str(item["path"])
        for item in (payload.get("generated_artifacts") or [])
        if isinstance(item, dict) and item.get("path")
    }
    paths.update(REQUIRED_OUTPUTS)
    return tuple(sorted(paths))


def run_freeze_workflow(
    run: Path,
    *,
    baseline: str = "fast_livo2",
    language: str = "zh-CN",
    repo_root: Path | None = None,
) -> dict[str, Any]:
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"unsupported freeze report language: {language}; expected zh-CN or en"
        )
    run = Path(run).expanduser().resolve()
    root = (
        Path(repo_root).expanduser().resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[1]
    )

    frozen = prepare_freeze(
        run,
        baseline=baseline,
        language=language,
        repo_root=root,
    )

    stages: tuple[tuple[str, Callable[[Path], Any]], ...] = (
        ("viewer/diagnostic.rrd", build_frozen_rerun),
        ("report_data.json", build_report_data),
        ("evidence/evidence_manifest.json", build_report_evidence),
        ("report/index.html", render_report_html),
        ("report/report.pdf", render_report_pdf),
    )
    for stage, function in stages:
        try:
            function(frozen)
        except Exception as exc:
            _record_failure(frozen, stage, exc)
            raise

    try:
        completed = finalize_freeze(
            frozen,
            required_generated_paths=_all_generated_paths(frozen),
        )
    except Exception as exc:
        _record_failure(frozen, "finalize", exc)
        raise

    return {
        "frozen": frozen,
        "freeze_state": completed.get("freeze_state"),
        "manifest": completed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an immutable LIO benchmark freeze")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--baseline", default="fast_livo2")
    parser.add_argument("--lang", choices=sorted(SUPPORTED_LANGUAGES), default="zh-CN")
    args = parser.parse_args()
    result = run_freeze_workflow(
        args.run,
        baseline=args.baseline,
        language=args.lang,
    )
    print(
        json.dumps(
            {
                "frozen": str(result["frozen"]),
                "freeze_state": result["freeze_state"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
