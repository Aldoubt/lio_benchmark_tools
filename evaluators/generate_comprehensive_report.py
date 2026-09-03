#!/usr/bin/env python3
"""Deprecated compatibility entrypoint for comprehensive benchmark reports.

The historical implementation embedded run-specific prose and numeric
constants. Keep the old filename and public ``build_report`` API for callers
and tests, but derive every benchmark value from ``current_run_report``.

The optional hardware argument is preserved only for the historical transparent
CPU-FP32-equivalent proxy fields. It does not restore any historical trajectory,
map, recommendation, or resource constants.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from current_run_report import (
    build_report as _build_current_run_report,
    main,
    render_markdown,
    write_outputs,
)


def _host_peak_nominal_tops(hardware: dict[str, Any]) -> float | None:
    logical_cpus = hardware.get("logical_cpus")
    nominal_ghz = hardware.get("nominal_ghz")
    fp32_ops = hardware.get("fp32_ops_per_cycle_assumption")
    if logical_cpus is None or nominal_ghz is None or fp32_ops is None:
        return None
    return float(logical_cpus) * float(nominal_ghz) * float(fp32_ops) / 1000.0


def _cpu_equivalent(
    mean_cpu_percent: Any,
    hardware: dict[str, Any],
) -> dict[str, float | None]:
    nominal_ghz = hardware.get("nominal_ghz")
    fp32_ops = hardware.get("fp32_ops_per_cycle_assumption")
    if mean_cpu_percent is None or nominal_ghz is None or fp32_ops is None:
        return {"mean_tops_at_nominal": None}
    # 100% process-tree CPU means one logical core. GHz * FP32 ops/cycle is
    # GOPS; divide by 1000 for a transparent FP32-equivalent TOPS proxy.
    return {
        "mean_tops_at_nominal": (
            float(mean_cpu_percent)
            / 100.0
            * float(nominal_ghz)
            * float(fp32_ops)
            / 1000.0
        )
    }


def build_report(
    run: Path,
    hardware: dict[str, Any] | None = None,
    baseline: str = "fast_livo2",
) -> dict[str, Any]:
    """Build the current-run report while preserving the legacy Python API.

    ``hardware`` augments only the CPU-equivalent proxy fields expected by old
    callers. All trajectory, health, map, resource, and recommendation values
    still come from the selected run via ``current_run_report``.
    """
    report = _build_current_run_report(Path(run), baseline=baseline)
    hardware = dict(hardware or {})
    report["hardware"] = hardware
    report["tops"] = {
        "host_peak_nominal_tops": _host_peak_nominal_tops(hardware),
        "proxy_only": True,
    }
    for row in report.get("algorithms", []):
        resource = row.get("resource") or {}
        row["cpu_equivalent"] = _cpu_equivalent(
            resource.get("mean_cpu_percent"),
            hardware,
        )
    return report


if __name__ == "__main__":
    raise SystemExit(main())
