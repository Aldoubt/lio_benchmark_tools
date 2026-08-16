#!/usr/bin/env python3
"""ROS-independent timestamp cadence and coverage diagnostics."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import statistics
from typing import Sequence


@dataclass(frozen=True)
class TimestampSeriesStats:
    count: int
    first_s: float
    last_s: float
    duration_s: float
    effective_hz: float | None
    median_period_s: float | None
    p95_period_s: float | None
    max_period_s: float | None
    gap_count_over_1p5x_median: int

    def to_dict(self) -> dict[str, int | float | None]:
        return asdict(self)


def _validated(values: Sequence[float]) -> tuple[float, ...]:
    timestamps = tuple(float(value) for value in values)
    if not timestamps:
        raise ValueError("timestamp series requires at least one timestamp")
    if not all(math.isfinite(value) for value in timestamps):
        raise ValueError("timestamps must be finite")
    if any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
        raise ValueError("timestamps must be strictly increasing")
    return timestamps


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def summarize_timestamps(values: Sequence[float]) -> TimestampSeriesStats:
    """Describe a strictly increasing timestamp series without judging quality."""
    timestamps = _validated(values)
    first = timestamps[0]
    last = timestamps[-1]
    duration = last - first
    if len(timestamps) == 1:
        return TimestampSeriesStats(
            count=1,
            first_s=first,
            last_s=last,
            duration_s=0.0,
            effective_hz=None,
            median_period_s=None,
            p95_period_s=None,
            max_period_s=None,
            gap_count_over_1p5x_median=0,
        )

    periods = tuple(current - previous for previous, current in zip(timestamps, timestamps[1:]))
    median_period = statistics.median(periods)
    return TimestampSeriesStats(
        count=len(timestamps),
        first_s=first,
        last_s=last,
        duration_s=duration,
        effective_hz=(len(timestamps) - 1) / duration,
        median_period_s=median_period,
        p95_period_s=_percentile(periods, 0.95),
        max_period_s=max(periods),
        gap_count_over_1p5x_median=sum(period > 1.5 * median_period for period in periods),
    )


def coverage_against_input(
    input_timestamps: Sequence[float],
    output_timestamps: Sequence[float],
) -> dict[str, int | float | None]:
    """Describe output timing relative to a containing input timestamp domain."""
    input_stats = summarize_timestamps(input_timestamps)
    output_stats = summarize_timestamps(output_timestamps)
    tolerance = 1e-9
    if output_stats.first_s < input_stats.first_s - tolerance:
        raise ValueError("output timestamp series starts before input timestamp series")
    if output_stats.last_s > input_stats.last_s + tolerance:
        raise ValueError("output timestamp series ends after input timestamp series")
    return {
        "input_count": input_stats.count,
        "output_count": output_stats.count,
        "output_to_input_count_ratio": output_stats.count / input_stats.count,
        "first_output_lag_from_input_s": output_stats.first_s - input_stats.first_s,
        "last_output_delta_to_input_end_s": output_stats.last_s - input_stats.last_s,
    }
