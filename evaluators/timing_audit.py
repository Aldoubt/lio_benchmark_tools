"""ROS-free timing observations in reader order; never infer a root cause."""
from __future__ import annotations

import bisect
import math
import statistics


def finite(value):
    return value is not None and math.isfinite(value)


def series_stats(values):
    values = [value for value in values if finite(value)]
    if not values:
        return dict(count=0, mean=None, median=None, std=None, min=None, max=None)
    return dict(count=len(values), mean=statistics.fmean(values),
                median=statistics.median(values), std=statistics.pstdev(values),
                min=min(values), max=max(values))


def audit_timestamps(recorded, headers, *, gap_threshold_s=0.5, offset_threshold_s=0.2):
    """One header (or None) per record. Thresholds are strict >, in seconds.

    Reader order is preserved. A gap is an observed interval, not proof of lost
    packets. Offset includes clock mismatch and recorder scheduling, not just
    transport latency. No interpolation across missing/nonfinite samples.
    """
    if len(recorded) != len(headers):
        raise ValueError("recorded/header timestamps must be paired")
    for value in (gap_threshold_s, offset_threshold_s):
        if not finite(value) or value <= 0:
            raise ValueError("timing thresholds must be finite and > 0")
    events = []
    clocks = {}
    for name, values in (("recorded", recorded), ("header", headers)):
        counts = dict(backtrack_count=0, duplicate_count=0, gap_count=0,
                      missing_count=0, nonfinite_count=0, zero_count=0)
        intervals = []
        for index, value in enumerate(values):
            kind = None
            delta = None
            if value is None:
                counts["missing_count"] += 1
                kind = "missing"
            elif not finite(value):
                counts["nonfinite_count"] += 1
                kind = "nonfinite"
            else:
                counts["zero_count"] += int(value == 0)
                if index and finite(values[index - 1]):
                    delta = value - values[index - 1]
                    intervals.append(delta)
                    if delta < 0:
                        kind = "backtrack"
                    elif delta == 0:
                        kind = "duplicate"
                    elif delta > gap_threshold_s:
                        kind = "gap"
                    if kind:
                        counts[kind + "_count"] += 1
            if kind:
                events.append(dict(type=name + "_" + kind, sample_index=index,
                                   timestamp_s=value if finite(value) else None,
                                   delta_s=delta))
        clocks[name] = {**counts, "dt_s": series_stats(intervals)}
    offsets = []
    for index, (record, header) in enumerate(zip(recorded, headers)):
        if not finite(record) or not finite(header):
            continue
        offset = record - header
        offsets.append(offset)
        kind = "offset_above_threshold" if offset > offset_threshold_s else (
            "negative_offset" if offset < 0 else None)
        if kind:
            events.append(dict(type=kind, sample_index=index,
                               timestamp_s=header, record_minus_header_s=offset))
    return dict(metric_class="diagnostic/non-ground-truth", sample_count=len(recorded),
                order="reader order; no sorting", clocks=clocks,
                thresholds=dict(gap_s=gap_threshold_s, offset_s=offset_threshold_s,
                                comparison="strictly greater than"),
                record_minus_header_s=series_stats(offsets), events=events,
                limitations=["Gaps do not establish packet loss or its cause.",
                             "Record minus header is a clock-domain offset observation, not proven transport latency.",
                             "Reader ordering may hide original recorder timestamp reversals.",
                             "Seconds use float64 precision; sub-microsecond epoch differences are not guaranteed."])


def nearest_header_offsets(query, reference):
    """Nearest timestamp association, including unsorted/backtracking input.

    Sorting is confined to lookup; raw timing evidence is audited separately.
    Clock-epoch resets can make association ambiguous; this is not sync proof.
    """
    ordered = sorted(value for value in reference if finite(value))
    result = []
    for value in query:
        if not ordered or not finite(value):
            continue
        index = bisect.bisect_left(ordered, value)
        candidates = ordered[max(0, index - 1):index + 1]
        result.append(value - min(candidates, key=lambda item: (abs(item - value), item)))
    return result
