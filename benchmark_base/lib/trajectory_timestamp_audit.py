#!/usr/bin/env python3
"""ROS-independent diagnostics for run-local trajectory timestamp streams.

This module is deliberately descriptive: it classifies the timestamp stream
that the existing trajectory standardizer would consume. It never sorts,
deduplicates, rewrites, or otherwise repairs estimator samples.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


@dataclass(frozen=True)
class TimestampAuditSample:
    index: int
    bag_record_timestamp_s: float
    header_timestamp_s: float | None
    effective_timestamp_s: float
    effective_source: str
    x_m: float
    y_m: float
    z_m: float
    qx: float
    qy: float
    qz: float
    qw: float


def _validate(samples: Sequence[TimestampAuditSample]) -> None:
    if not samples:
        raise ValueError("timestamp audit requires at least one sample")
    for sample in samples:
        required = (
            sample.bag_record_timestamp_s,
            sample.effective_timestamp_s,
            sample.x_m,
            sample.y_m,
            sample.z_m,
            sample.qx,
            sample.qy,
            sample.qz,
            sample.qw,
        )
        if any(not math.isfinite(float(value)) for value in required):
            raise ValueError("timestamp audit sample contains non-finite values")
        if sample.header_timestamp_s is not None and not math.isfinite(
            float(sample.header_timestamp_s)
        ):
            raise ValueError("timestamp audit header timestamp must be finite or null")


def _transition_counts(values: Sequence[float]) -> tuple[int, int, int | None, float]:
    duplicates = 0
    regressions = 0
    first_bad: int | None = None
    max_backward = 0.0
    for index, (left, right) in enumerate(zip(values, values[1:]), start=1):
        if right == left:
            duplicates += 1
            if first_bad is None:
                first_bad = index
        elif right < left:
            regressions += 1
            max_backward = max(max_backward, left - right)
            if first_bad is None:
                first_bad = index
    return duplicates, regressions, first_bad, max_backward


def _header_transition_counts(
    samples: Sequence[TimestampAuditSample],
) -> tuple[int, int]:
    duplicates = 0
    regressions = 0
    for left, right in zip(samples, samples[1:]):
        if left.header_timestamp_s is None or right.header_timestamp_s is None:
            continue
        if right.header_timestamp_s == left.header_timestamp_s:
            duplicates += 1
        elif right.header_timestamp_s < left.header_timestamp_s:
            regressions += 1
    return duplicates, regressions


def summarize_timestamp_samples(samples: Sequence[TimestampAuditSample]) -> dict[str, object]:
    """Describe timestamp monotonicity under the current standardization policy."""
    _validate(samples)
    bag = [float(sample.bag_record_timestamp_s) for sample in samples]
    effective = [float(sample.effective_timestamp_s) for sample in samples]
    bag_dup, bag_reg, _, bag_back = _transition_counts(bag)
    eff_dup, eff_reg, first_bad, eff_back = _transition_counts(effective)
    header_dup, header_reg = _header_transition_counts(samples)
    fallback_count = sum(
        1 for sample in samples if sample.effective_source == "ROSBAG_RECORD_TIME"
    )

    if eff_reg:
        if header_reg:
            classification = "HEADER_REGRESSION"
        elif bag_reg:
            classification = "BAG_RECORD_REGRESSION"
        else:
            classification = "MIXED_POLICY_REGRESSION"
    elif eff_dup:
        if header_dup:
            classification = "HEADER_DUPLICATES"
        elif bag_dup:
            classification = "BAG_RECORD_DUPLICATES"
        else:
            classification = "MIXED_POLICY_DUPLICATES"
    else:
        classification = "PASS"

    return {
        "classification": classification,
        "sample_count": len(samples),
        "bag_record_fallback_count": fallback_count,
        "bag_record_duplicate_count": bag_dup,
        "bag_record_regression_count": bag_reg,
        "header_duplicate_count": header_dup,
        "header_regression_count": header_reg,
        "effective_duplicate_count": eff_dup,
        "effective_regression_count": eff_reg,
        "bag_record_strictly_increasing": bag_dup == 0 and bag_reg == 0,
        "effective_strictly_increasing": eff_dup == 0 and eff_reg == 0,
        "first_offending_index": first_bad,
        "max_bag_record_backward_s": bag_back,
        "max_effective_backward_s": eff_back,
        "first_bag_record_timestamp_s": bag[0],
        "last_bag_record_timestamp_s": bag[-1],
        "first_effective_timestamp_s": effective[0],
        "last_effective_timestamp_s": effective[-1],
    }
