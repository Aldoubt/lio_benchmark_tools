"""Pure health-gating helpers shared by benchmark summarizers."""
from __future__ import annotations

from typing import Any


FULL_BAG_MIN_COVERAGE_RATIO = 0.98
SMOKE_STARTUP_MARGIN_S = 5.0


def _limited_run_duration_s(run_result: dict[str, Any]) -> float | None:
    for key in ("smoke_duration_s", "duration_s"):
        raw = run_result.get(key)
        if raw is None:
            continue
        value = float(raw)
        return value if value > 0.0 else None
    return None


def expected_trajectory_duration_s(run_result: dict[str, Any], manifest_duration_s: float | None) -> float | None:
    """Return the requested playback duration relevant to this algorithm run."""
    limited = _limited_run_duration_s(run_result)
    if limited is not None:
        return limited
    if manifest_duration_s is None:
        return None
    value = float(manifest_duration_s)
    return value if value > 0.0 else None


def trajectory_short(
    actual_duration_s: float | None,
    run_result: dict[str, Any],
    manifest_duration_s: float | None,
) -> bool:
    """Judge incomplete coverage without comparing a short smoke to the full bag duration."""
    if actual_duration_s is None:
        return False
    expected = expected_trajectory_duration_s(run_result, manifest_duration_s)
    if expected is None:
        return False
    if _limited_run_duration_s(run_result) is not None:
        minimum = max(0.0, expected - SMOKE_STARTUP_MARGIN_S)
    else:
        minimum = expected * FULL_BAG_MIN_COVERAGE_RATIO
    return float(actual_duration_s) < minimum
